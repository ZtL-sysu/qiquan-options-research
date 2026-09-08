# Covered Call 固定规则策略库

本阶段只建立576个固定参数模块，不做寻优、收益排名、自动推荐或网站。

## 查看结果

先打开项目根目录的 `covered_call_strategy_universe_report.md`。它说明是否全部完成、实际数据截止日、融资及裸露敞口等风险。

本次输出位置记录在 `outputs/strategy_universe/latest_run.json` 的 `output` 字段。
每次运行单独保存，不覆盖过去结果。主要表位于该目录；共同区间表位于其 `common_period` 子目录。

- 根目录 `strategy_daily.parquet`、`strategy_metrics.parquet`：FULL_HISTORY；OTM从2015开始，Delta从可靠数据起点开始。
- `common_period/strategy_daily.parquet`、`strategy_metrics.parquet`：COMMON_PERIOD；所有策略同日起始资金，OTM重新建仓计算。
- `strategy_latest_state.parquet`：BASE每策略一行，共576行。
- `strategy_latest_state_scenarios.parquet`：BASE/STRESS每策略情景一行，共1152行。
- 两个区间分别使用 `strategy_id + scenario_id + date` 作为每日主键，不将两个起始资金不同的净值混在同一主键下。
- 每个区间均保存统一的 trades、rolls、cash_ledger、events、regime_metrics、parameter_cube。

若运行目录包含`recomputed`，它是规则修复的中间审计批次，不能与正式长表再次拼接；查询接口只读根目录及`common_period`。`repair_scope.json`与`t1_expiry_selection_changes.parquet`记录规则差异和受影响模块，不按绩效决定重算范围。

## 在Windows运行

在项目文件夹地址栏输入 `powershell`，回车，然后按顺序执行：

```powershell
& 'C:\ProgramData\miniforge3\python.exe' -m unittest discover -s tests -v
& 'C:\ProgramData\miniforge3\python.exe' scripts\run_strategy_universe.py
& 'C:\ProgramData\miniforge3\python.exe' scripts\verify_strategy_universe.py
& 'C:\ProgramData\miniforge3\python.exe' scripts\build_strategy_universe_report.py
```

第一步应显示 `OK`。全量运行会打印 `576/576` 和 `COMPUTATION COMPLETE`；核验应显示 `VALIDATION PASSED`。
只有核验与报告完成，才能把结果视为本阶段交付。出现异常请保留输出目录，不要手动删除失败模块。

本程序读取本地数据快照，不会每个策略重复查询数据库。需要更新数据时，先单独运行：

```powershell
& 'C:\ProgramData\miniforge3\python.exe' scripts\sync_covered_call_data.py
```

## 查询示例

新建Python文件，放在项目根目录运行：

```python
from covered_call.query import StrategyUniverse

u = StrategyUniverse()
strategy = u.get_strategy(dict(
    selection_method='DELTA', target_delta=.25,
    target_dte=30, roll_dte=5, coverage_ratio=1.00))
sid = strategy['strategy_id']
nav = u.get_nav(sid, scenario_id='BASE', period='COMMON_PERIOD')
day = u.get_day(sid, '2025-07-15')
latest = u.get_latest_state(sid)
trades = u.get_trades(sid)
rolls = u.get_rolls(sid)
metrics = u.get_metrics(sid)
regimes = u.get_regime_metrics(sid)
comparison = u.compare_strategies([sid, 'CC_OTM05_DTE30_R5_C100'])
surface = u.get_parameter_slice(
    selection_method='DELTA', roll_dte=5, coverage_ratio=1.00)
print(strategy)
print(latest[['date', 'NAV', 'strategy_state', 'financing_balance']])
```

比较接口默认使用COMMON_PERIOD；显式请求不同历史起点的FULL_HISTORY比较会报错。
参数面返回全部匹配组合，没有“最佳”标记。

## 固定规则与账本

1. T收盘用当日原始ETF价格、Wind Delta选Call；下一交易日收盘价模拟执行，按比例滑点和每张佣金收费。
2. 新开仓仅使用当时未调整、正成交量、正持仓量、正收盘价、有效条款的Call。DTE在7至90自然日内，且到期日必须晚于已知下一交易日（长假边界）；先选最接近目标DTE的到期日，并列选较早日期，再选最接近目标Delta或moneyness的执行价，并列选较低执行价、较小代码。该约束不读取T+1价格或成交量。
3. 当前Call剩余交易DTE≤R时产生信号。R1在到期日执行；只有两腿都可成交才执行组合。同合约重选允许，照收两边费用，不暗加“必须次月”。
4. 选约或执行失败时组合两腿均不成交，次日重新检查。到期日若新仓失败但旧仓可平，明确记录 `EXPIRY_RISK_CLOSE_ONLY`；旧仓也无法平仓则STOPPED，不模拟行权，不消灭负债。
5. 数量为 `floor(ETF份额×目标coverage/合约乘数)`；coverage定义为期权对应份额/ETF份额。
6. 原子组合现金流为 `新卖权利金－旧权回购金额－两边佣金－两边滑点`。只为组合净支出借款，不单独为旧权回购借入毛金额。
7. `NAV=现金+ETF市值−空头Call负债−融资本金`；现金不能隐式为负。收到现金后自动偿还已有融资。融资利息为 `上交易日末融资本金×年利率×间隔自然日数/365`，不足部分显式借入并记利息支出。无现金利息。BASE为6%，STRESS为8%。
8. 未模拟券商授信上限、抵押折扣、保证金追缴；NAV≤0停止融资和交易。必须结合报告中的最大融资/NAV理解风险。
9. 除息日分红记入经济应计现金等价账户，不宣称是真实到账日；保持ETF原始价格，不叠加复权收益。ETF初始买入一次，其后不自动再投资分红或调仓。
10. 持有期间条款按生效日更新，乘数变化可能超目标coverage甚至裸露，明确记录，不自动增买ETF。新仓按新的整数份额重算。

源库缺少完整历史发布版本，包含临时休市的日历公告版本。因此，历史修订和临时休市“当时是否已经可知”的残余偏差不能完全排除；T+1规则及条款恢复只排查可验证的执行时间与业务条款错误。

旧 `run_backtest` 保留原Milestone 2严格现金规则供历史回归核验；本阶段生产入口为同一 `covered_call.engine` 暴露的 `PreparedMarket` / `run_margin_backtest`。

## 指标定义

- CAGR按实际自然年天数/365.25；波动率日收益样本标准差×√252；Sharpe无风险利率0；Sortino分母为全样本负收益平方均值的平方根×√252。
- 最大回撤包含初始100万元高水位。Calmar=CAGR/最大回撤绝对值。
- 整体上下行捕获率按基准上涨/下跌月份的策略平均月收益/基准平均月收益。环境分组使用相应日期的日收益捕获率，口径不同，不能直接混比。
- 权利金收益率=累计卖出毛权利金/初始NAV/实际年数，绝非净收益率。Option Net PnL=持仓盯市变化+期权毛交易现金流−期权交易费；融资利息单列，没有强行归入期权腿。
- entry字段使用实际成交日数据；signal字段保存T日数据。两者Delta偏离可能来自T+1市场波动，不应改用成交日Delta回填信号。
- 平均entry指标按每笔STO等权；平均coverage包含未覆盖日的0。平均Roll Debit只统计净现金流为负的原子换月，借款本金变化不算利润。
- 净Delta=ETF份额−空头张数×乘数×Wind Delta；其余净Greeks=−张数×乘数×相应Wind原始Greek。源库未充分证明Theta日/年及Vega百分点评价单位，保留原始量纲，不能直接把这些列当作统一标准化风险金额。
- excess_NAV=策略NAV/基准NAV；rolling excess为相同日历3/6/12/24个月窗口的策略收益−基准收益，回溯端点取不晚于目标日的最近交易日。

## 市场环境（只做事后归因）

ETF收益/RV基于原始价格加现金分红形成的经济总回报；MA基于原始价格，除息可能影响短期标签。
趋势：价格高于MA60超过2%且MA20>MA60为UP；低于MA60超过2%且MA20<MA60为DOWN；其余SIDEWAYS。
RV20小于15%为LOW、大于25%为HIGH，其余MID。ATM IV滚动252交易日百分位≤30%为LOW、≥70%为HIGH，其余MID。
不足窗口或IV缺失为UNKNOWN，归因表保留，不丢日期。ATM/25Delta Call IV使用30日目标期限、不插值；call_skew=25D Call IV−ATM Call IV。
Put skew不提供：本阶段只处理Call策略，不引入未经验证的Put口径。
每种环境的回撤和年化将所有匹配日期按时间排序拼接为条件收益序列，并非某一连续自然区间，不能解释为可交易择时收益。
市场标签从不传入执行引擎。

## 复现证据

`data_snapshot`保存运行时标准行情及SHA256；`source_code_snapshot.zip`保存启动时核心源码；`run_manifest.json`记录所有结构/执行规则版本和散列。
`strategy_result_hashes.parquet`保存逐模块/情景/区间的原始账本、成交、每日结果内容散列；`reproduction_audit.parquet`保存独立复跑比对结果。
内容散列不包括run_id等运行标识；两次运行的元数据可以不同，不要求整个Parquet文件字节相同。`runtime_versions.json`和`requirements_reproduction.txt`保存本次Python/依赖版本。
Delta的FULL_HISTORY和COMMON_PERIOD起点相同，因此计算一次分别写入两套结果；复现表明确标记复用，不冒充独立复跑两次。
报告不会把完成代码实现等同于策略存在统计优势。
