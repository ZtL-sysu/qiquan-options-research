# 期权研究看板

静态公开看板，部署路径为 `/options/`。它把510050备兑规则库的冻结验收结果、三个按风险筛选的研究观察规则、科创50双卖的失败证据和日频510050行情放在同一页面。

## 重要边界

- 看板不会提供“今天买/卖/开仓”的指令，也不会连接券商或账户。
- 日更数据仅来自日频行情。没有14:45盘口、Bid/Ask或经验证Greeks，因此不会生成实时选约或科创50盘中Delta建议。
- 三个备兑规则基于共同区间、BASE/STRESS、无裸露、融资上限和覆盖率筛选，不按历史最高收益或Sharpe挑选。

## 本机构建

```sh
/Users/xhf/miniconda3/bin/conda run --no-capture-output -n base python build_baseline.py
/Users/xhf/miniconda3/bin/conda run --no-capture-output -n base python update.py --no-refresh
```

有有效gjdata配置时，去掉 `--no-refresh` 可读取510050的最新日频市场数据。部署脚本会在Windows服务器每天03:45运行同一更新程序。
