# 期权研究看板

静态公开看板，部署路径为 `/options/`。它把冻结研究证据与每日收盘后市场观测严格分层：510050备兑规则库、三个按风险筛选的研究观察规则、科创50双卖的失败证据，以及510050和588000的ETF与期权链日频状态。

## 重要边界

- 看板不会提供“今天买/卖/开仓”的指令，也不会连接券商或账户。
- 日更数据来自 gjdata：ETF收盘价、涨跌、成交量/额、20日实现波动率；活跃期权合约数、到期月数、Call/Put成交量和持仓量，以及 Wind EOD Greeks 的覆盖率。每个数据源都带有业务日期与 `FRESH/PARTIAL/NO_DATA` 状态。
- 日更只代表收盘后观测。没有14:45盘口、Bid/Ask、订单参与率或成交回报，因此不会生成实时选约或科创50盘中Delta建议。
- 三个备兑规则基于共同区间、BASE/STRESS、无裸露、融资上限和覆盖率筛选，不按历史最高收益或Sharpe挑选。

## 本机构建

```sh
/Users/xhf/miniconda3/bin/conda run --no-capture-output -n base python build_baseline.py
/Users/xhf/miniconda3/bin/conda run --no-capture-output -n base python update.py --no-refresh
```

有有效 gjdata 配置时，去掉 `--no-refresh` 可读取510050和588000的最新日频市场数据及其对应期权链。部署脚本会在Windows服务器每天03:45运行同一更新程序；若任一数据源不可用，页面显示明确的数据质量状态，且不会把冻结研究仓位改写为实时信号。
