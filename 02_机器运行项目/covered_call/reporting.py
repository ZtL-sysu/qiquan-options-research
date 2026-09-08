"""Markdown研究报告与可复现静态图；不启动或开发网站。"""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager,ticker
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd

from .data import ROOT, MART

BLUE='#2459A6'; GOLD='#B18119'; GREY='#62666D'


def report(out):
    out=Path(out); charts=out/'charts';charts.mkdir(exist_ok=True)
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.unicode_minus':False,'figure.facecolor':'white','axes.spines.top':False,'axes.spines.right':False,'axes.labelcolor':'#333333','text.color':'#252525','font.size':10,'axes.titlesize':13,'axes.grid':True,'grid.color':'#E6E7EA','grid.linewidth':.6})
    names=['CC_OTM_5_full_base','CC_OTM_5_common_base','CC_DELTA_025_common_base','CC_DELTA_025_common_stress','BUY_HOLD_full','BUY_HOLD_common']
    frames={n:pd.read_csv(out/n/'daily_nav.csv',parse_dates=['date']) for n in names}
    metrics={n:json.loads((out/n/'metrics.json').read_text(encoding='utf-8')) for n in names}
    trades={n:pd.read_csv(out/n/'trades.csv',parse_dates=['signal_date','execution_date']) for n in names}
    manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
    data=json.loads((MART/'manifest.json').read_text(encoding='utf-8'))
    short=frames['CC_OTM_5_full_base'];delta=frames['CC_DELTA_025_common_base'];bench=frames['BUY_HOLD_common'];dm=metrics['CC_DELTA_025_common_base'];bm=metrics['BUY_HOLD_common']
    incomplete=not all(metrics[n]['completed'] for n in names)
    map_rows=[]

    def save(fig,name,question,family,source):
        fig.savefig(charts/(name+'.png'),dpi=160,bbox_inches='tight')
        plt.close(fig)
        map_rows.append({'图表':name,'分析问题':question,'图形':family,'配色':'蓝/金双色上限，灰色基准；辅以虚线/标签','来源':source,'交付':'Markdown内嵌PNG','限制':'OTM未跑通时只能显示已验证短区间，不外推'})

    def finish(ax,title,ylabel):
        ax.set_title(title,loc='left',pad=12);ax.set_ylabel(ylabel)

    # 图1：分面，避免把OTM的短暂净值误当作全区间完成。
    fig,axes=plt.subplots(2,1,figsize=(12,8),layout='constrained')
    for n,color,style,label in [('CC_DELTA_025_common_base',BLUE,'-','Delta 0.25'),('BUY_HOLD_common',GREY,'--','ETF买入持有'),('CC_OTM_5_common_base',GOLD,':','OTM 5%（未完成）' if incomplete else 'OTM 5%')]:
        d=frames[n];axes[0].plot(d.date,d.NAV/1e6,color=color,linestyle=style,label=label,lw=1.4)
    finish(axes[0],'共同起始日期净值｜初始资金100万元，未完成序列不延长','净值（初始=1）');axes[0].legend(loc='upper left',ncol=3,frameon=False)
    b=frames['BUY_HOLD_full'];b=b.loc[b.date<=short.date.max()]
    axes[1].plot(short.date,short.NAV/1e6,color=GOLD,label='OTM 5% 已验证区间')
    axes[1].plot(b.date,b.NAV/1e6,color=GREY,ls='--',label='完全同期ETF买入持有')
    finish(axes[1],f'OTM全历史运行的有效区间｜{short.date.min():%Y-%m-%d}—{short.date.max():%Y-%m-%d}','净值（初始=1）');axes[1].legend(frameon=False)
    save(fig,'01_NAV','相同起点的净值路径如何变化','分面折线','daily_nav.csv')
    fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained')
    for n,color,style,label in [('CC_DELTA_025_common_base',BLUE,'-','Delta 0.25'),('BUY_HOLD_common',GREY,'--','ETF买入持有')]:
        d=frames[n];ax.plot(d.date,d.drawdown,color=color,ls=style,label=label)
    finish(ax,'回撤｜共同区间，净值相对历史高点','回撤');ax.yaxis.set_major_formatter(ticker.PercentFormatter(1));ax.legend(frameon=False)
    save(fig,'02_drawdown','回撤的深度与持续时间','折线','daily_nav.csv.drawdown')
    month=pd.read_csv(out/'CC_DELTA_025_common_base/monthly_returns.csv',parse_dates=['月份'])
    month['年']=month['月份'].dt.year;month['月']=month['月份'].dt.month
    matrix=month.pivot(index='年',columns='月',values='收益率').reindex(columns=range(1,13))
    fig,ax=plt.subplots(figsize=(12,5),layout='constrained');limit=np.nanmax(abs(matrix.to_numpy()))
    cmap=LinearSegmentedColormap.from_list('gold_white_blue',[GOLD,'#FFFFFF',BLUE])
    im=ax.imshow(matrix,cmap=cmap,vmin=-limit,vmax=limit,aspect='auto');ax.grid(False)
    ax.set_xticks(range(12),range(1,13));ax.set_yticks(range(len(matrix)),matrix.index)
    for i,row in enumerate(matrix.to_numpy()):
        for j,v in enumerate(row):
            if np.isfinite(v):ax.text(j,i,f'{v:.1%}',ha='center',va='center',fontsize=8,color='white' if abs(v)>.65*limit else '#222222')
    finish(ax,'Delta策略月度收益｜2017年4月起；2020年12月前未实际卖出Call','年份');ax.set_xlabel('月份');fig.colorbar(im,ax=ax,format=ticker.PercentFormatter(1),shrink=.8)
    save(fig,'03_monthly_returns','月收益分布是否集中于特定阶段','热力图','monthly_returns.csv')
    year_d=pd.read_csv(out/'CC_DELTA_025_common_base/annual_returns.csv');year_b=pd.read_csv(out/'BUY_HOLD_common/annual_returns.csv')
    fig,ax=plt.subplots(figsize=(12,4.8),layout='constrained');x=np.arange(len(year_d))
    ax.bar(x-.18,year_d['收益率'],width=.36,color=BLUE,label='Delta 0.25');ax.bar(x+.18,year_b['收益率'],width=.36,facecolor='white',edgecolor=GREY,hatch='//',label='ETF买入持有')
    ax.axhline(0,color='#444444',lw=.8);ax.set_xticks(x,year_d['年份'].str[:4]);ax.yaxis.set_major_formatter(ticker.PercentFormatter(1));ax.legend(frameon=False)
    finish(ax,'年度收益｜首尾年为不完整年度；两序列日期完全一致','年度收益')
    save(fig,'04_annual_returns','每年相对基准表现如何','分组柱状','annual_returns.csv')
    joined=delta[['date','NAV']].merge(bench[['date','NAV']],on='date',suffixes=('_cc','_bh'),validate='one_to_one')
    fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained');ax.plot(joined.date,(joined.NAV_cc-joined.NAV_bh)/1e6,color=BLUE)
    ax.axhline(0,color=GREY,ls='--',lw=.8);ax.yaxis.set_major_formatter(ticker.PercentFormatter(1));finish(ax,'累计超额收益｜Delta净值减同期ETF净值，再除以初始资本','累计收益差（百分点）')
    save(fig,'05_excess_return','相对相同账本基准的收益差','折线','daily_nav.csv + benchmark_daily_nav.csv')
    entry=trades['CC_DELTA_025_common_base'].query("side=='SELL_TO_OPEN'")
    for field,name,title in [('moneyness','06_entry_moneyness','开仓执行日Moneyness'),('delta_wind','07_entry_delta','开仓执行日Wind Delta')]:
        values=entry[field].dropna();fig,ax=plt.subplots(figsize=(9,4.5),layout='constrained');ax.hist(values,bins=16,color=BLUE,edgecolor='white')
        finish(ax,f'{title}分布｜Delta策略，{len(values)}笔开仓；选约使用前一日值','开仓笔数');ax.set_xlabel(field)
        save(fig,name,'执行日入场属性与信号目标有多大偏离','直方图','trades.csv SELL_TO_OPEN')
    fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained')
    option_cost=trades['CC_DELTA_025_common_base'].query("instrument=='OPTION'").assign(cost=lambda d:d.slippage+d.commission).groupby('execution_date').cost.sum().reindex(pd.DatetimeIndex(delta.date),fill_value=0).cumsum()
    ax.plot(delta.date,delta.option_PnL.cumsum()/10000,color=BLUE,label='期权腿毛损益');ax.plot(delta.date,(delta.option_PnL.cumsum().to_numpy()-option_cost.to_numpy())/10000,color=GOLD,ls='--',label='扣期权费用及滑点')
    finish(ax,'期权累计损益｜含期末未平仓盯市，不等于累计权利金','累计损益（万元）');ax.legend(frameon=False)
    save(fig,'08_option_pnl','期权腿扣成本后贡献多少','折线','daily_nav.csv.option_PnL + trades.csv')
    pd.DataFrame(map_rows).to_csv(out/'chart_map.csv',index=False,encoding='utf-8-sig')

    def pct(value):
        return '不适用' if value is None else f'{value:.2%}'
    def money(value):
        return f'{value:,.2f}'
    def image(name):
        return f'![{name}]({(charts/(name+".png")).as_posix()})'
    table='| 指标 | CC_DELTA_025 基准成本 | 同期ETF买入持有 |\n|---|---:|---:|\n'
    for label,key in [('累计净收益','net_return'),('CAGR','CAGR'),('年化波动率','Annualized_Volatility'),('最大回撤','Max_Drawdown'),('上涨捕获率','Upside_Capture'),('下跌捕获率','Downside_Capture')]:
        table+=f'| {label} | {pct(dm[key])} | {pct(bm[key])} |\n'
    table+=f'| Sharpe（无风险利率0） | {dm["Sharpe"]:.4f} | {bm["Sharpe"]:.4f} |\n'
    stress=metrics['CC_DELTA_025_common_stress']
    missing=pd.read_csv(out/'CC_DELTA_025_common_base/missing_signal_log.csv').reason.value_counts().to_dict()
    worst=delta.nsmallest(1,'option_PnL').iloc[0]
    most_drift=entry.nlargest(1,'delta_wind').iloc[0]
    trcheck=pd.read_csv(MART/'quality'/'etf_total_return_consistency.csv')
    tr_error_bps=trcheck.return_difference.abs().max()*10000
    body=f'''# Milestone 2：510050数据层与基础Covered Call验证报告

## 技术摘要：数据层通过，OTM全历史因资金规则未完成

本报告是**阶段性验证结果，不是Milestone 2全部验收通过**。运行编号：`{out.name}`。

- 标准数据覆盖 {data['start_date']}—{data['end_date']}，{data['calendar_days']}个交易日，{data['option_eod_rows']:,}条期权行情；历史条款与行情代码日期集合一致。完成历史条款恢复、两独立估值来源保留、分红经济事件、SSE日历与增量更新。
- **CC_OTM_5未跑通全历史**：不融资、不卖ETF时，2015-03-24的旧Call平仓需要100,037.28元，经济现金35,828.48元，缺64,208.80元；共同起点运行在2017-06-27同样出现现金不足。程序停止，不模拟行权，不凭空关闭仓位。不能用这些短区间的年化值宣称长期业绩。
- **CC_DELTA_025已从2017-04-05运行至最新完整交易日**，基准与压力成本均完成。但首笔Call直到2020-12-15才执行：早期Wind Delta有大段缺失，不能把这段策略称为连续备兑。
- 不评价统计优势，也未开发网站、参数寻优、IV过滤或择时模型。**完成OTM全历史需要用户确认现金不足时的处理。**

## 1. 数据和比较口径

初始资金100万元，初始信号日在区间首日，ETF于下一上交所交易日收盘买入，按100份整手尽量买满。ETF交易费率为单边1bp、最低费0、额外滑点0，均可配置；这不代表实际券商费率。ETF买入持有基准使用相同初始资本、实际开始持有日、ETF费率及分红口径。

目标期限35自然日，窗口25—45日；先选到期月，再选执行价。到期月距离并列时选较早到期，执行价评分并列时选较低执行价再按合约代码排序。本版只在未调整合约中新开仓，持有期间调整则继续跟踪原代码；该设置写入配置，未按未来是否会调整筛历史合约。

所有信号只读取T日数据，成交在下一交易日收盘，执行日只作价格、有效状态与可覆盖数量检查，不重新选合约。成交日也必须有正成交量和正收盘价。有效状态是挂牌日期窗与行情有成交的代理条件，库中没有独立历史停牌状态和Bid/Ask，无法证明精确成交。

Greeks交易信号只使用 `windchinaoptionvaluation.W_ANAL_DELTA`；IV仅供分析。`chinaoptionvaluation`另存Parquet用于质量比较，没有拼入交易信号或自动补值。

## 2. 期权行情完整不等于Wind Delta完整

全历史有26条期权收盘价缺失，结算价无缺失，因此盯市可用结算价；这些缺失Close不能用于执行。未对期权价格前向填充。

Wind表仅184,422条记录，2017年114条、2018及2019年无记录，2020年12月8日起恢复较连续覆盖；已存在记录中另有21个Delta、264个IV空值。策略决策时记录 {missing.get('missing_signal:wind_delta_in_target_expiry',0)} 次“目标到期月Wind Delta缺失”，以及 {missing.get('no_eligible_expiry',0)} 次“无符合期限/流动性条件合约”。后者不是Greeks缺失，不应混算。

数据源缺失既影响卖Call频率，也改变收益分布。不能从现有Delta结果推断2015年至今连续执行该规则的表现。相同起点的OTM运行又因资金问题中止，因此目前**无法给出两套策略全共同区间谁更好的结论**。

## 3. Delta策略与相同口径的Buy & Hold

下表区间均为2017-04-05—{data['end_date']}。收益为净收益，波动按252交易日年化；捕获率采用基准上涨/下跌月份的策略平均月收益除以基准平均月收益。**早期缺失信号时仅持ETF**是这组结果的重要组成部分。

{table}

在该数据覆盖和执行假设下，Delta策略的净收益、波动和回撤指标优于同期基准；这是本次历史实现的描述，不构成统计显著性或未来表现判断。还没有样本内外检验，且数据缺失非随机。

{image('01_NAV')}

OTM曲线只保留可复算部分，之后为空，不作连线、延长或收益外推。完整共同区间的横向比较尚未完成。

{image('02_drawdown')}

回撤图只比较已完成相同日期区间的Delta和基准。净值含期权结算价盯市，不是按每日清算可实现的价格。

## 4. 收益月份、年份与超额路径

{image('03_monthly_returns')}

2017—2020年大部分时段没有实际卖Call；月度收益中的这部分主要来自ETF。没有把缺失期权信号日排出统计样本。

{image('04_annual_returns')}

首尾年度为不完整年度，不能拿其收益率直接与完整年度比较；两条序列的实际日期窗一致。

{image('05_excess_return')}

超额收益定义为两组期末NAV之差除以初始资本，而非策略收益除以基准收益。相同ETF份数及分红下，差异主要来自期权腿扣成本贡献。

## 5. 权利金、期权损益与上涨限制

Delta策略累计卖出**毛权利金 {money(dm['total_option_premium_received'])}元**；这不是利润。计入买回旧Call和期末未平仓负债后，期权腿毛损益为 {money(dm['option_PnL_gross'])}元，扣期权佣金与滑点后为 **{money(dm['option_PnL_net'])}元**，占初始资本 {pct(dm['option_PnL_over_initial'])}。

亏损的已平仓期权交易累计毛亏损为 {money(dm['realized_losing_option_trades_gross_loss'])}元。它反映部分上涨/波动带来的回购代价，**不等于严格分离出的“上涨封顶损失”**，因为回购发生于到期前且包含时间价值和IV变化。本阶段没有行权模型，不能凭空给出纯到期封顶损失。上涨捕获率低于100%反映上涨月份参与程度下降，不能直接换算成一笔独立现金损失。

{image('08_option_pnl')}

图中同时计入未平仓盯市。每笔已实现损益通过 `entry_trade_id` 关联开、平仓交易，避免将累计毛权利金直接当作期权收益。

## 6. 入场属性与公司行动

{image('06_entry_moneyness')}

{image('07_entry_delta')}

这两幅图使用**执行日**属性，选约评分使用前一日属性，所以执行日Delta偏离0.25不是未来函数，也不能据此宣称当日精确按0.25成交。OTM运行样本太短，未将其少数开仓画成有代表性的分布。

具体例子：{most_drift.signal_date:%Y-%m-%d}信号Delta为{most_drift.signal_delta_wind:.4f}，到{most_drift.execution_date:%Y-%m-%d}执行时已升至{most_drift.delta_wind:.4f}，原始ETF价格从{most_drift.signal_spot:.3f}升至{most_drift.spot:.3f}。最大单日期权腿毛亏损发生在{worst.date:%Y-%m-%d}，为{money(worst.option_PnL)}元，同日ETF价格损益{money(worst.ETF_PnL)}元。这说明隔日执行和上涨封顶风险不能被平均入场Delta掩盖。

全量恢复使用1,048条历史合约调整事件。Delta回测有 **{dm['undercovered_days']}个交易日 coverage_ratio<1**：合约单位调整后，保持ETF份数和原期权张数不变。已显式记录，未自动交易ETF补足。它意味着这些天不再完全备兑，应在实盘可执行性上单独处理。

## 7. 交易成本与压力结果

Base单边滑点为期权权利金0.5%，Stress为1%；每张单边佣金2元。卖出执行价=Close×(1−滑点率)，买回=Close×(1+滑点率)。现金账本分别记录市价毛流量、佣金、滑点，不能再把滑点重复扣进损益。

Delta Base总成本 **{money(dm['total_transaction_costs'])}元**，Stress总成本 **{money(stress['total_transaction_costs'])}元**；累计净收益分别为 **{pct(dm['net_return'])}、{pct(stress['net_return'])}**。压力测试未改策略参数。

`gross_NAV_same_positions = NAV + 累计交易成本` 是同一实际头寸路径的成本加回口径，不是重新跑一个零成本、不同初始ETF份数的策略。融资和现金利息当前均为0，且本次禁止负现金融资。

## 8. 账本与分红方法

每日 `NAV = economic_cash + ETF_shares × raw_close + signed_option_qty × mark × current_multiplier`；空头数量为负，mark优先结算价、缺失才用同日Close，禁止价格前向填充。

`ETF_PnL = ETF市值变化 + ETF买卖毛现金流`；`option_PnL = 期权市值变化 + 期权买卖毛现金流`；`daily_PnL = ETF_PnL + option_PnL + dividend_PnL + interest_PnL − transaction_cost`。

分红从净值累计分配字段按日期差分，并用ETF前收盘与除权昨收价差交叉检查。除息日前持有份额×每份分红记入**经济应计现金等价账户**；没有实际支付日，不宣称资金当天到账。因为本V1无支付日，这一应计余额进入可用经济现金，是模型近似。ETF复权价仅用于一致性检查，未参与收益记账或执行价比较；没有复权收益与分红双算。

已输出 `data_mart/quality/etf_total_return_consistency.csv`：日度“原始价格+每份分红”与复权收盘价收益的最大绝对差为{tr_error_bps:.3f}bp。两者不是应当逐位相等的现金账本：复权价格有舍入，除息再投资口径与现金分红口径也存在差别；该检查不用于替换策略收益。

财务指标公式：CAGR按实际自然日/365.25年化；波动率为日收益样本标准差×√252；Sharpe以日超额收益均值/日波动×√252，无风险利率配置为0；Sortino下行波动分母使用全样本的 `sqrt(mean(min(excess_return,0)^2))`；最大回撤含初始资本高点；Calmar=CAGR/最大回撤绝对值。

## 9. 验证、限制与待确认事项

要求的2025-07-15回归用例：原始spot=2.855，期限窗口选择2025-08-27、43自然日；OTM选3.00；Wind Delta选2.95（0.2752），3.00的Wind Delta为0.1918。自动测试会在这些结果改变时失败。

每次运行另从导出现金账本、交易记录和头寸独立重算每日现金、ETF份数、期权整数张数、费用与NAV，误差阈值1e-5元；不只检查引擎内部自洽。旧Call平仓后张数归零，Roll记录old→new和成功/失败状态。

局限包括：历史数据库发布版本不可得；恢复业务条款不等于证明当年发布时间；Bid/Ask缺失；未独立识别历史停牌；应计分红不是支付现金；调整后不足额备兑；Wind早期大段缺失；OTM现金不足未完成。**不能标注“整个Milestone 2通过”，也不能对两套策略宣布胜者。**

待用户确认：现金不足平仓时，是允许显式融资并指定年利率，还是允许卖出少量ETF筹资并改变持股路径？确认后需重跑两策略、两个成本情景、同期基准与共同区间，再更新本报告。当前未自动采用任一种处理。

## 10. 输出位置与复现

标准数据位于 `data_mart/`；本次所有CSV/JSON、独立对账和图表位于 `{out.as_posix()}`。每次运行保留独立run_id及完整参数。数据manifest包含日期范围、增量策略与标准文件SHA256校验，读取时拒绝不完整或被改写的快照。

```powershell
& 'C:\\ProgramData\\miniforge3\\python.exe' '.\\scripts\\sync_covered_call_data.py'
& 'C:\\ProgramData\\miniforge3\\python.exe' -m unittest discover -s tests -v
& 'C:\\ProgramData\\miniforge3\\python.exe' '.\\scripts\\run_covered_call_milestone2.py'
& 'C:\\ProgramData\\miniforge3\\python.exe' '.\\scripts\\build_milestone2_report.py'
```

增量更新回查最近35自然日的期权行情/估值；全部静态条款、变更事件、ETF、分红和日历每次重取。新代码回补历史。更早供应商修订需 `--refresh` 全量更新。这不是对任意旧记录修订的实时捕捉。

本阶段不开始网站、不寻优、不增加IV过滤或择时；当前停止点为资金不足处理规则。
'''
    (ROOT/'milestone2_report.md').write_text(body,encoding='utf-8')
    (out/'milestone2_report.md').write_text(body,encoding='utf-8')
    print('REPORT',ROOT/'milestone2_report.md',flush=True)
