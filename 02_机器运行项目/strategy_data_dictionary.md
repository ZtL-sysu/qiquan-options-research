# 策略库数据字典

金额单位统一为人民币元；价格为每ETF份额的人民币价格；日期为上海市场交易日（无日内时区转换）。
机器字段使用任务书规定的英文名称。日频字段不得用于假装已观测到当日收盘前的信号。
最大融资及融资/NAV指标均基于每日结束时的余额；账本另保留同日先借后还明细，不将其当作真实日内授信测算。

## 文件与主键

|文件|主键/用途|
|---|---|
|strategy_registry|strategy_id，恰好576行，结构参数与模块状态|
|strategy_daily|strategy_id、scenario_id、date，全部持仓/资金/状态|
|strategy_trades|strategy_id、scenario_id、trade_id，包含初始ETF买入和全部Call成交|
|strategy_rolls|strategy_id、scenario_id、roll_id，原子换月与明确的到期风险退出例外|
|strategy_cash_ledger|同一策略内按保存顺序的账本事件；一日多行，不得按日期去重|
|strategy_events|同一策略一日多条数据缺失、执行跳过、公司行动事件|
|strategy_metrics|strategy_id、scenario_id，默认历史的完整绩效|
|strategy_regime_metrics|strategy_id、scenario_id、regime_dimension、regime_value|
|strategy_parameter_cube|strategy_id、scenario_id，结构参数与全部指标完整连接|
|strategy_latest_state|strategy_id，默认BASE，576行|
|strategy_latest_state_scenarios|strategy_id、scenario_id，1152行|
|market_state_daily|date，独立事后市场环境|
|benchmark_daily|period_id、date，同资本、同现金分红口径的ETF基准|

根目录为FULL_HISTORY；`common_period`子目录同名长表为COMMON_PERIOD。不能将两个目录合并后只用日期/策略/情景去重；若合并必须把period_id加入主键。

## 每日持仓与净值

|字段|定义|
|---|---|
|NAV|现金+ETF市值+期权市值−融资本金；期权空仓市值为负数|
|daily_return|NAV/上日NAV−1；首日分母为初始资本|
|cumulative_return|NAV/初始资本−1|
|drawdown|NAV/截至当日最高NAV−1，最高值包含初始资本|
|ETF_price|未复权ETF收盘价|
|ETF_shares / ETF_market_value|ETF份额、份额×原始收盘价|
|short_call_code / short_call_contracts|当前唯一空头Call代码、正的整数张数；无仓为0张|
|contract_multiplier|当日有效合约乘数，不能使用未来调整后的静态值|
|option_market_value|−空头张数×乘数×当日盯市价格|
|mark_price / mark_source|结算价优先；结算价缺失则当日收盘价；不跨日填充|
|strike / expiry|当前有效执行价、到期日|
|calendar_DTE|到期日−当日，自然日|
|trading_DTE|完整公布交易日历中(当日,到期日]的交易日数|
|entry_date / entry_spot / entry_strike|本轮STO实际成交日期、原始ETF价格、有效执行价|
|entry_moneyness|入场执行价/入场ETF原始价；不是OTM百分比，后者需减1|
|entry_delta / entry_IV|入场成交日Wind Delta/IV；不用于替换T日选约数据|
|entry_option_price|入场成交日市场收盘价，未包含费用或比例滑点；含滑点价格在trades.execution_price|
|current_moneyness / current_delta / current_IV|当前执行价/当前原始ETF价、当日Wind Delta/IV|
|cash / financing_balance|独立的非负现金和非负融资本金，不能把负现金当作融资|
|coverage_ratio|空头张数×当前乘数/ETF份额；无Call为0|
|over_target_coverage / naked_exposure|分别为超过模块目标coverage、超过100%覆盖的显式标记|
|net_delta|ETF份额−空头对应份额×Wind Delta|
|net_gamma / net_theta / net_vega|−空头对应份额×当日Wind原始Greek；Theta/Vega量纲限制见报告|
|option_unrealized_pnl|当前仓位入场毛权利金+当前负的期权市值，未扣交易费|
|option_realized_pnl|已平仓的入场毛权利金−回购毛金额累计值，未扣交易费|
|option_pnl / option_net_pnl|当日期权盯市变化+期权毛交易现金流；后者再扣当日期权交易费|
|premium_received_cumulative|累计STO毛收入，不减BTC，不等于利润|
|transaction_cost_cumulative|ETF与期权佣金及滑点的累计金额|
|financing_interest_cumulative|已确认融资利息累计金额；借款本金不是利息，也不是利润|
|ETF_pnl / dividend_pnl|当日ETF市值变化+ETF毛现金流；分红经济应计另列，不重复算复权收益|
|strategy_state|单一主状态，优先STOPPED、公司行动、缺失、已换月、待换月、融资|
|event_flags|并存状态，以竖线分隔，避免单一状态丢信息|
|signal / next_action|当日收盘产生的规则信号、下一交易日待办；样本末日也保留待办，不执行未来交易|
|selection_reason|选约缺失或成功原因|
|benchmark_NAV|与本策略起点一致的ETF买入持有净资产|
|excess_NAV|策略NAV/基准NAV，相对财富指数，起点为1|
|excess_return_arithmetic|(策略NAV−基准NAV)/初始资本|
|rolling_excess_3M等|相同日历窗口内策略收益减去基准收益；历史不足为空|
|pnl_reconciliation_error|当日NAV变化−ETF腿−期权腿−分红+融资利息+交易费，应接近0|

持仓时Greek缺失保持NULL；空仓时净Delta为ETF份额，净Gamma/Theta/Vega为0。不得把持仓时的NULL替换成0。
新开仓候选除7–90自然日边界外，还要求到期日晚于T+1交易日；只利用T日可知日历和合约到期日，防止长假后新仓已到期。
Parquet部分计数字段使用可容纳缺失值的数值类型，张数和份额均通过整数值检查，不代表允许分数合约。

## 成交、换月与融资账本

`signal_date`和`execution_date`必须为相邻交易日。`signal_delta/IV/strike/spot/DTE/trading_DTE`保存T日信息；entry字段在成交表为T+1实际行情信息。

`gross_cashflow`为STO正、BTC负；`net_cashflow=gross_cashflow−commission−slippage`。
`slippage`是金额，不是比例。期权执行价格=市场收盘价×(1−滑点比例)用于卖出，×(1+滑点比例)用于买回。

Roll的`buyback_cost`为旧仓回购毛金额，`new_premium`为新仓卖出毛收入。
`net_roll_cashflow=new_premium−buyback_cost−commission−slippage`。
`financing_before/after`为组合结算紧前/紧后的融资本金，已包含当天在此之前的利息、分红影响。
`same_contract`明确记录是否同合约平旧再开，不把这种情况剔除。`status=EXPIRY_RISK_CLOSE_ONLY`为到期风险退出例外，不计入原子换月次数。

现金账本`amount`是现金变化，`debt_change`是融资负债变化。

|事件|现金变化|融资变化|是否形成损益|
|---|---|---|---|
|INITIAL_CAPITAL|+初始资本|0|否|
|FINANCING_DRAW|+借入|+借入|否|
|FINANCING_REPAY|−偿还|−偿还|否|
|FINANCING_INTEREST|−利息|0|费用|
|ATOMIC_ROLL_NET|两腿合并净额|0|结合期权市值变化确认损益|
|OPTION_OPEN_NET / RISK_CLOSE_NET|单次开仓/明确的风险平仓净额|0|同上|
|DIVIDEND_ECONOMIC_ACCRUAL|+经济应计分红|0|分红收入；不宣称真实到账|
|ETF_BUY_NET|−ETF购买及费用|0|ETF购买本身非费用，佣金/滑点为费用|

## 版本与质量证据

run_id标识运行；parameter_version标识结构规则；scenario_id标识成本/融资情景；data_version/source_hash标识冻结数据；engine_version标识核心代码。

独立复算不使用NAV来反推现金：现金从账本累计、融资从debt_change累计，份额和张数从交易累计，再回查来源价计算市值。
`strategy_audit`保存误差，`reproduction_audit`保存逐模块内容散列，`selection_reference_audit`保存独立选约核对，`abnormal_state_audit`和`naked_exposure_audit`保留风险行。
