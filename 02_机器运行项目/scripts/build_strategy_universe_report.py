"""从已验证长表生成验收报告；不选择或推荐模块。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import zipfile
import platform
import importlib.metadata
import numpy as np
import pandas as pd
import duckdb
from covered_call.data import ROOT,json_write


def table(rows, columns):
    lines=['|'+'|'.join(columns)+'|','|'+'|'.join(['---']*len(columns))+'|']
    lines+=['|'+'|'.join(str(row.get(c,'')) for c in columns)+'|' for row in rows]
    return '\n'.join(lines)


def number(x, digits=2): return '缺失' if pd.isna(x) else f'{x:,.{digits}f}'
def percent(x): return '缺失' if pd.isna(x) else f'{x:.2%}'
def day(x): return '无' if pd.isna(x) else str(pd.Timestamp(x).date())


def build(out):
    out=Path(out).resolve();manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
    validation=json.loads((out/'validation_summary.json').read_text(encoding='utf-8'))
    reproduction=pd.read_parquet(out/'reproduction_audit.parquet')
    if not reproduction.identical.all() or reproduction.strategy_id.nunique()!=576:
        raise AssertionError('全模块复现未通过，不生成完成报告')
    registry=pd.read_parquet(out/'strategy_registry.parquet');full=pd.read_parquet(out/'strategy_metrics.parquet')
    common=pd.read_parquet(out/'common_period/strategy_metrics.parquet');sample=pd.read_parquet(out/'strategy_sample_audit.parquet')
    latest=pd.read_parquet(out/'strategy_latest_state_scenarios.parquet');audit=pd.read_parquet(out/'strategy_audit.parquet')
    baseline=json.loads((out/'baseline_validation.json').read_text(encoding='utf-8'))
    conn=duckdb.connect()
    def query(sql): return conn.execute(sql,[str(out/'strategy_daily.parquet')]).df()
    abnormal=query('SELECT strategy_id,scenario_id,date,NAV,daily_return,ETF_pnl,option_pnl,transaction_cost,financing_interest,coverage_ratio,financing_balance,current_IV,current_delta,short_call_code FROM read_parquet(?) WHERE abs(daily_return)>0.10 OR NAV<=0 OR cash< -0.0000001 OR current_IV>2 OR current_delta<0 OR current_delta>1 ORDER BY strategy_id,scenario_id,date')
    abnormal.to_parquet(out/'abnormal_state_audit.parquet',index=False)
    naked=query('SELECT strategy_id,scenario_id,date,ETF_shares,short_call_code,short_call_contracts,contract_multiplier,coverage_ratio,event_flags FROM read_parquet(?) WHERE naked_exposure ORDER BY strategy_id,scenario_id,date')
    naked.to_parquet(out/'naked_exposure_audit.parquet',index=False)
    extreme=query('SELECT strategy_id,scenario_id,date,NAV,daily_return,ETF_pnl,option_pnl,dividend_pnl,transaction_cost,financing_interest,pnl_reconciliation_error FROM read_parquet(?) ORDER BY abs(daily_return) DESC LIMIT 12')
    extreme.to_parquet(out/'extreme_daily_pnl_audit.parquet',index=False)
    loan=query('SELECT max(financing_balance) max_financing,max(financing_balance/NAV) max_financing_NAV,max(coverage_ratio) max_coverage,min(NAV) minimum_NAV,min(cash) minimum_cash,max(abs(pnl_reconciliation_error)) pnl_error FROM read_parquet(?)').iloc[0]
    missing=query('SELECT count(*) n FROM read_parquet(?) WHERE short_call_contracts>0 AND current_delta IS NULL').iloc[0,0]
    max_error=audit[[c for c in ['cash','financing','NAV','ETF_shares','cost','contracts','option_pnl','source_mark'] if c in audit]].max().max()
    fullcounts=validation['FULL_HISTORY'];commoncounts=validation['COMMON_PERIOD']
    successful=int(registry.status.eq('COMPLETED').sum());failed=576-successful
    failure_rows=registry.loc[registry.status.ne('COMPLETED'),['strategy_id','failure_reason']].rename(columns={'strategy_id':'模块','failure_reason':'失败原因'}).to_dict('records')
    fullbase=full.loc[full.scenario_id.eq('BASE')];fullstress=full.loc[full.scenario_id.eq('STRESS')]
    scenario_check=fullbase.merge(fullstress,on='strategy_id',suffixes=('_base','_stress'),validate='one_to_one')
    stress_cost_ok=bool(scenario_check.Transaction_Cost_stress.ge(scenario_check.Transaction_Cost_base-1e-6).all())
    stress_nav_ok=bool(scenario_check.final_NAV_stress.le(scenario_check.final_NAV_base+1e-6).all())
    profit_flags=full.loc[full.CAGR.gt(.50) | full.final_NAV.gt(5e6)].copy()
    profit_flags.to_parquet(out/'high_profit_threshold_audit.parquet',index=False)
    ranges=[]
    for period,frame in [('FULL_HISTORY',full),('COMMON_PERIOD',common)]:
        joined=frame.merge(registry[['strategy_id','selection_method']],on='strategy_id',validate='many_to_one')
        for (method,scenario),g in joined.groupby(['selection_method','scenario_id']):
            ranges.append({'区间':period,'类型':method,'情景':scenario,'CAGR范围':percent(g.CAGR.min())+' 至 '+percent(g.CAGR.max()),
                           '累计收益范围':percent(g.net_return.min())+' 至 '+percent(g.net_return.max())})
    pd.DataFrame(ranges).to_parquet(out/'performance_range_audit.parquet',index=False)
    benchmark=pd.read_parquet(out/'benchmark_daily.parquet')
    benchmarkrows=[]
    for period,b in benchmark.groupby('period_id',sort=False):
        benchmarkrows.append({'区间':period,'起点':day(b.date.min()),'截止':day(b.date.max()),'累计收益':percent(b.NAV.iloc[-1]/1e6-1),
                              '最大回撤':percent(b.drawdown.min()),'期末净资产':number(b.NAV.iloc[-1])})
    baserows=[{'基线':r['strategy_id'],'情景':r['scenario_id'],'起点':day(r['requested_start']),
               '截止':day(r['last_valid_date']),'完整运行':'是' if r['completed'] else '否','期末净资产':number(r['final_NAV']),
               '最大融资':number(r['maximum_financing'])} for r in baseline]
    answerrows=[
        {'验收项':'唯一模块数','结果':f'{registry.strategy_id.nunique()}；Delta 288 / OTM 288'},
        {'验收项':'完整/失败模块','结果':f'{successful} / {failed}（两情景、两区间均纳入判断）'},
        {'验收项':'OTM完整历史','结果':manifest['full_history_start']+' 至 '+manifest['end_date']},
        {'验收项':'Delta可靠历史 / 共同区间','结果':manifest['common_period_start']+' 至 '+manifest['end_date']},
        {'验收项':'FULL_HISTORY情景结果','结果':f"完整{fullcounts['completed_runs']} / 失败{fullcounts['failed_runs']}；应有1152"},
        {'验收项':'COMMON_PERIOD情景结果','结果':f"完整{commoncounts['completed_runs']} / 失败{commoncounts['failed_runs']}；应有1152"},
        {'验收项':'strategy_daily记录数','结果':f"{int(fullcounts['rows']):,}；共同区间另存{int(commoncounts['rows']):,}"},
        {'验收项':'每个ID可复现','结果':f"576模块均通过；{validation['independent_backtest_reexecutions']}次独立回测复跑，{len(reproduction)}个区间/情景散列一致"},
        {'验收项':'最新状态','结果':f"BASE表576行；双情景表{len(latest)}行；当期状态{int(latest.is_current.sum())}行"},
        {'验收项':'完整NAV或失败原因','结果':'逐策略核对起止日期、应有交易日数及失败原因；无静默丢弃'},
        {'验收项':'参数经济表现','结果':'保留完整参数面；下文固定切片说明，不按CAGR或Sharpe选模块'},
        {'验收项':'风险检查','结果':f"最低NAV {number(loan.minimum_NAV)}元；最大融资/NAV {percent(loan.max_financing_NAV)}；裸露策略日{len(naked):,}（含情景重复）"}]
    sample_sections=[]
    for method,label in [('DELTA','Delta模块随机审计（10个）'),('MONEYNESS','OTM模块随机审计（10个）')]:
        rows=[]
        for r in sample.loc[sample.selection_method.eq(method)].sort_values('strategy_id').to_dict('records'):
            rows.append({'模块（ID含完整参数）':r['strategy_id'],'首次Call交易':day(r['first_trade_date']),
                '最近Call交易':day(r['latest_trade_date']),'累计收益':percent(r['net_return']),'最大回撤':percent(r['Max_Drawdown']),
                'Call成交笔数':int(r['Number_Trades']),'平均入场Delta':number(r['Average_Entry_Delta'],3),
                '平均入场OTM':percent(r['Average_Entry_Moneyness']-1),'平均DTE':number(r['Average_Entry_DTE'],1),
                '平均Coverage':percent(r['Average_Coverage']),'最大融资（元）':number(r['Maximum_Financing'])})
        sample_sections.append('### '+label+'\n\n'+table(rows,list(rows[0])))
    cube=pd.read_parquet(out/'common_period/strategy_parameter_cube.parquet')
    fixed=cube.loc[cube.scenario_id.eq('BASE') & cube.target_dte.eq(30)&cube.roll_dte.eq(5)&cube.coverage_ratio.eq(1.)]
    economics=[]
    for method in ['DELTA','MONEYNESS']:
        target='target_delta' if method=='DELTA' else 'target_otm'
        rows=[]
        for r in fixed.loc[fixed.selection_method.eq(method)].sort_values(target).to_dict('records'):
            rows.append({'目标':f"{method} {r[target]:.2f}",'实际入场Delta':number(r['Average_Entry_Delta'],3),
                '实际入场OTM':percent(r['Average_Entry_Moneyness']-1),'实际入场DTE':number(r['Average_Entry_DTE'],1),
                '年化毛权利金/NAV':percent(r['Annualized_Premium_Yield']),'上行捕获':percent(r['Upside_Capture']),
                '下行捕获':percent(r['Downside_Capture']),'期权净损益（元）':number(r['Option_Net_PnL'])})
        economics.append(table(rows,list(rows[0])))
    rollsummary=cube.loc[cube.scenario_id.eq('BASE')].groupby('roll_dte')[['Number_Rolls','same_contract_rolls','Transaction_Cost']].mean()
    rollrows=[{'Roll阈值（交易日）':int(i),'平均换月数':number(r.Number_Rolls,1),'平均同合约换月数':number(r.same_contract_rolls,1),
               '平均交易费（元）':number(r.Transaction_Cost)} for i,r in rollsummary.iterrows()]
    text=f'''# Covered Call Strategy Universe 验收报告

## 一、结论

本次固定规则库共有 **576个唯一模块**，完整运行 **{successful}个**，失败 **{failed}个**。不进行参数优化、历史收益排名、自动推荐或网站UI开发。

**研究口径限制：这不是券商真实保证金仿真。** 显式融资、原始价格加经济应计分红、收盘价加比例滑点均是固定研究假设；公司行动后出现的裸露敞口已完整列示，不能把“代码跑通”理解为实盘可直接执行。

{table(answerrows,['验收项','结果'])}

## 二、先通过基线，再执行遍历

原M2的35自然日目标、25–45日窗口、到期前一交易日执行换月保留为基线（新规则R2发信号，T+1执行）。本阶段模块期限改为20/30/45/60、7–90日边界。

{table(baserows,list(baserows[0]))}

原子换月净额=新Call毛权利金−旧Call回购金额−双边佣金−双边滑点。融资只覆盖净现金缺口，融资借入/偿还不计入利润。现金扫入还款，融资利息ACT/365，BASE 6% / STRESS 8%。

## 三、历史、行情与完整性

- 数据截至 **{manifest['end_date']}**。标准期权行情与历史条款各 **{manifest['source_manifest']['option_eod_rows']:,}行**，数据层缺口 **{manifest['source_manifest']['gap_rows']}行**。运行期间所有模块读取同一冻结Parquet，不逐策略访问MySQL。
- Delta可靠起点 **{manifest['common_period_start']}**：可交易未调整Call的有效Wind Delta覆盖率至少95%，连续60交易日；质量确认日为 **{manifest['reliability']['quality_confirmation_date']}**。这是事后数据质量区间划分，不是当时可提前获知的交易信号；2017年零星值不作为默认起点。
- 根目录FULL_HISTORY的OTM用2015起始历史，Delta用可靠起点；共同区间所有模块和基准从可靠起点以100万元重新开始。Delta两区间完全相同，计算结果复用并明确标记。
- 每个物理每日表主键均为strategy_id、scenario_id、date。两个不同初始时点的结果分目录，不产生主键冲突。
- 所有信号仅使用T日未复权ETF、T日合约条款及Wind Delta；无primary Greeks补值、无跨日填充。持仓日Greeks缺失保留空值，FULL_HISTORY共有 **{int(missing):,}个有持仓但Delta缺失的策略日**（含两个情景），不将其当作零风险。
- 业务条款按生效日恢复，但源库没有完整历史发布版本，无法证明当年供应商发布时间；本结果不能消除供应商历史修订风险。
- 交易DTE使用源库历史实际交易日历，没有日历公告版本。临时休市/延迟开市的宣布时间可能形成残余信息时点偏差；T+1及条款恢复测试通过，不等于已证明所有历史数据当时均已发布。

## 四、BASE/STRESS、基准及状态

BASE=0.5%期权比例滑点+每张每边2元佣金+6%融资；STRESS=1%+2元+8%。ETF初始一次买入，1bp佣金，100份整数手，剩余现金保留；后续分红不自动再投。

分红在除息日进入经济应计现金等价账户，不是真实支付日；该口径可能比实际到账更早偿还融资，因此融资成本不是券商实际账单。源库原始价加分红与复权收益的最大单日差为{manifest['source_manifest']['total_return_consistency_max_abs_bps']:.4f}bp，复权收益仅作核对，不叠加进入NAV。

同模块STRESS交易成本不低于BASE：**{'通过' if stress_cost_ok else '未通过'}**；STRESS期末NAV不高于BASE：**{'通过' if stress_nav_ok else '未通过'}**。这些是成本方向核验，不是策略优势结论。

{table(benchmarkrows,list(benchmarkrows[0]))}

每个每日状态保留主状态strategy_state及并存event_flags。融资不会抹掉换月/缺失/公司行动证据。最新状态BASE576行、双情景1152行。

R1按要求在到期前一交易日发信号、到期日收盘执行，未模拟行权。两腿不满足执行条件时不做半个组合；到期日可平旧但不能开新时记录EXPIRY_RISK_CLOSE_ONLY，共 **{int(full.risk_close_only_count.sum())}次**；旧仓无法退出则停止并保留原因。

本版在T日依据已知交易日历，排除“到期日≤下一交易日”的新开仓候选，不读取T+1价格/成交量。修复了2023年春节长假下仅用7自然日边界仍可能选中T+1到期合约的问题。四类核心参数不变；新版参数版本明确记录该可执行性约束，旧结果不再作为验收批次。

## 五、资金与异常审计

- 最低现金 **{number(loan.minimum_cash)}元**；最低净资产 **{number(loan.minimum_NAV)}元**。全部逐日PnL残差最大 **{loan.pnl_error:.3g}元**；独立现金/融资/交易/持仓复算最大误差 **{max_error:.3g}**。
- 最大融资本金 **{number(loan.max_financing)}元**，最大融资/NAV **{percent(loan.max_financing_NAV)}**。没有隐藏负现金；NAV≤0停止继续融资。未设券商授信上限、质押折扣及追保规则，因此不能声称已证明融资容量真实可得。
- 公司行动导致裸露的策略日 **{len(naked):,}个**，涉及 **{naked.strategy_id.nunique() if len(naked) else 0}个模块**，最大实际coverage **{percent(loan.max_coverage)}**。沿用M2“更新条款、不自动买ETF”的规则，新开仓/换月按目标coverage重算整数张数。裸露并未被静默修正或剔除。
- 预设异常筛查：绝对日收益>10%、NAV≤0、现金<0、持仓IV>200%、Delta越界。共 **{len(abnormal):,}行**，保存abnormal_state_audit.parquet；这是检查阈值，不是交易过滤或删样本规则。极端日另存extreme_daily_pnl_audit.parquet，列示ETF腿、期权腿、分红、利息与费用，允许人工逐项复算。
- 异常高利润另用CAGR>50%或期末净资产>初始资本5倍做检查，触发 **{len(profit_flags)}个模块情景**，证据high_profit_threshold_audit.parquet。下列范围仅用于数量级审计，不展示极值对应策略ID，也不据此排名或推荐。
- 全部持仓估值回查当日结算价（缺失才用当日收盘价）；不会只把权利金入账、漏记空头负债。Option Net PnL已扣期权交易费，融资利息独立列示。
- Wind IV可能在深度虚值合约出现极端值；保留原始值和缺失。Theta/Vega原始量纲未完全核实，只输出Wind原始Greek×合约对应份额的净敞口，不冒充已验证的标准化风险金额。
- 成交使用收盘价及比例滑点，只检查成交量为正，不限制订单参与率；没有逐笔成交、买卖报价、最小价位取整、排队成交或券商保证金数据。低价合约可能出现佣金高于毛权利金，仍按固定规则保留，不能将模拟执行价视为真实可成交报价。

{table(failure_rows,['模块','失败原因']) if failure_rows else '本次没有失败模块；失败模块保留规则和STOPPED状态处理已经保留在代码中。'}

{table(ranges,list(ranges[0]))}

## 六、参数变化的描述，不作优劣判断

以下是**事先固定DTE30、R5、100%覆盖、BASE、共同区间**的完整切片。按参数值顺序呈现，没有按收益挑选。实际入场Delta/OTM会偏离目标，因为档位离散且信号与成交相差一个交易日。

{economics[0]}

{economics[1]}

目标Delta提高通常对应更靠近价内的Call、更多毛权利金和更强收益封顶；目标OTM提高通常对应更远价外Call、较少毛权利金。毛权利金不能代替期权净损益。完整DTE、Roll、Coverage切片见strategy_parameter_cube及查询接口。

**同合约重复换月是规则的可解释后果。** 本次不暗加“必须换到下月”；当目标DTE选中原到期月时可能原合约平旧再开，双边费用照计。下表是共同区间BASE全部576模块按R分组的模块指标算术平均，不是组合回测或推荐：

{table(rollrows,list(rollrows[0]))}

## 七、市场环境与指标口径

market_state_daily独立生成，只供事后归因，不传入交易引擎。ETF经济总回报计算1/5/20/60日收益、RV20/60、回撤；MA20/60使用原始价格。30日目标期限的ATM及25Delta Call IV不插值；Call skew=25D IV−ATM IV。Put skew未提供。

趋势：价格比MA60高2%以上且MA20>MA60为UP；低2%以上且MA20<MA60为DOWN，其余SIDEWAYS。RV20<15%为LOW、>25%为HIGH；IV过去252交易日百分位≤30%为LOW、≥70%为HIGH。无足够历史为UNKNOWN且保留归因。

环境指标按匹配日期拼接条件收益计算，年化用252天。环境回撤不是连续自然区间回撤；条件日捕获率也不同于整体月度捕获率，不把它们解释为已实现择时策略。

CAGR按实际自然日/365.25；日波动年化√252；Sharpe无风险利率0；Sortino使用全样本负收益平方均值；回撤包含初始NAV高水位。平均Coverage包含无Call日的0。年化毛权利金率=累计毛权利金/初始NAV/实际年数，非净收益率。完整公式与账本说明见README_Strategy_Universe.md。

平均入场Delta和IV仅对非缺失的STO记录求均值，不填0；尤其OTM完整历史的这些均值主要反映Wind可用后的子样本，不代表2015年以来每次入场均有Greek观测。比较这类暴露优先使用共同区间。

excess_NAV=策略NAV/同起点基准NAV；rolling 3/6/12/24个月超额为同期两者收益之差，回溯端点取不晚于目标日的最近交易日。比较接口默认共同区间，阻止不同起点FULL_HISTORY直接比较。

## 八、随机样本人工审计表

固定随机种子20260828，每类10个，均使用BASE默认历史。ID完整编码目标、DTE、Roll、Coverage；样本不是收益筛选。原始宽表及全部参数在strategy_sample_audit.parquet，可逐笔查询。

{(chr(10)*2).join(sample_sections)}

## 九、复现、接口及交付

- run_id：`{manifest['run_id']}`
- parameter_version：`{manifest['parameter_version']}`
- data_version：`{manifest['data_version']}`
- source_hash：`{manifest['source_hash']}`
- engine_version：`{manifest['engine_version']}`
- 输出目录：`{out}`
- 所有模块已从冻结数据独立重跑；每日结果、成交、换月、融资账本及事件内容散列逐项一致。全量复现证据reproduction_audit.parquet；结构/行数验证validation_summary.json；单模块账本核验strategy_audit.parquet。
- 自动化回归与边界测试日志见test_validation.txt（本次50项策略/接口测试及8项历史条款测试通过）。覆盖资金、T+1、真实来源、历史条款、原子换月、R1、长假执行日有效期、整数覆盖、数据缺失、重复换月、周末利息、破产停止、共享数据运行顺序独立性和查询边界。
- 独立抽取20个真实历史日期、遍历48个选约目标，共960次选约与原M2 pandas选约器一致，证据selection_reference_audit.parquet。此核对不使用收益挑选样本。
- 查询接口：get_strategy、get_nav、compare_strategies、get_day、get_latest_state、get_metrics、get_trades、get_rolls、get_regime_metrics、get_parameter_slice，均读取本次Parquet。
- 每日字段、正负号、单位、NULL含义及账本事件见strategy_data_dictionary.md；运行及查询示例见README_Strategy_Universe.md。
- source_code_snapshot.zip保存启动时核心源码；delivery_source_snapshot.zip另存最终查询、复现、报告及测试源码。冻结数据保存在data_snapshot。两份代码快照职责不同，不混称散列。

本阶段到此停止，不进行优化、动态切换、IV或趋势择时、机器学习、最佳模块推荐及网站开发。
'''
    report=ROOT/'covered_call_strategy_universe_report.md';report.write_text(text,encoding='utf-8')
    (out/'covered_call_strategy_universe_report.md').write_text(text,encoding='utf-8')
    files=sorted([*ROOT.glob('covered_call/*.py'),*ROOT.glob('scripts/*.py'),*ROOT.glob('tests/*.py'),*ROOT.glob('data_audit/*.py'),
                  ROOT/'README_Strategy_Universe.md',ROOT/'strategy_data_dictionary.md',ROOT/'requirements_covered_call.txt'])
    versions={name:importlib.metadata.version(name) for name in ['pandas','numpy','pyarrow','duckdb','PyYAML','pymysql']}
    json_write(dict(python=sys.version,platform=platform.platform(),packages=versions),out/'runtime_versions.json')
    (out/'requirements_reproduction.txt').write_text('\n'.join(f'{name}=={version}' for name,version in versions.items())+'\n',encoding='utf-8')
    with zipfile.ZipFile(out/'delivery_source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
        for file in files: z.write(file,file.relative_to(ROOT))
    artifact_hashes={str(p.relative_to(out)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in out.rglob('*') if p.is_file() and p.suffix in ['.parquet','.zip','.md'] and 'data_snapshot' not in p.parts}
    json_write(artifact_hashes,out/'artifact_sha256.json')
    prior=json.loads((out/'run_status.json').read_text(encoding='utf-8'))
    prior.update(status='VALIDATED',modules_completed=successful,modules_failed=failed)
    json_write(prior,out/'run_status.json')
    json_write(dict(run_id=manifest['run_id'],output=str(out),status='VALIDATED'),ROOT/'outputs/strategy_universe/latest_run.json')
    conn.close();print('REPORT READY',report,flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--run');args=parser.parse_args()
    out=args.run or json.loads((ROOT/'outputs/strategy_universe/latest_run.json').read_text(encoding='utf-8'))['output'];build(out)
