# 510050 Covered Call：Milestone 2

本目录新增独立数据层和回测模块，不改原有科创50双卖代码与原数据库工具包。

**当前状态：标准数据层与测试通过；Delta策略完成，OTM策略因现金不足未跑通全历史。资金处理规则尚待确认，不算整个Milestone 2完成。** 详细结果见 `milestone2_report.md`。

## 如何运行

在 Windows 文件资源管理器打开本项目文件夹，在地址栏输入 `powershell` 并回车。

依次执行：

```powershell
& 'C:\ProgramData\miniforge3\python.exe' '.\scripts\sync_covered_call_data.py'
& 'C:\ProgramData\miniforge3\python.exe' -m unittest discover -s tests -v
& 'C:\ProgramData\miniforge3\python.exe' '.\scripts\run_covered_call_milestone2.py'
& 'C:\ProgramData\miniforge3\python.exe' '.\scripts\build_milestone2_report.py'
```

- 第一条同步Parquet并输出日期范围、记录数与数据完整性结果。第二次运行自动增量回查35自然日。更早历史数据发生修订时加 `--refresh` 全量刷新。
- 第二条末尾 `OK` 表示测试通过，不表示策略有效。
- 第三条为两个固定策略运行0.5%和1%期权单边滑点情景，没有参数寻优。检查输出的 `completed`；`False` 不能解释为全历史成功。
- 第四条生成当前阶段Markdown报告和8幅PNG图，不会启动网站。

首次同步可能需要数分钟。网络错误时不需要复制账号密码；程序仍读取原工具的集中配置。停止中的不完整快照不能用于回测，数据哈希检查失败时请重新同步。

## 配置与边界

`config/covered_call.yaml` 保存目标期限、交易成本和资金规则。默认目标期限35自然日，ETF单边费用1bp、100份整手；这些都是明示研究假设。当前 `cash_policy: stop` 禁止负现金融资；缺钱买回Call会记录失败，不能进入行权时停止。不要把年化融资率0自动理解为可以免费融资。

信号T收盘、成交T+1收盘。开仓只使用当日未调整合约；持仓发生调整时按真实生效日切换乘数和执行价，不自动买卖ETF，覆盖不足会标记。

分红计入除息日经济应计账户，不是实际现金支付日。回测使用未复权ETF价格加分红；复权价只供核对。标准层保留两套Greeks，交易信号只用Wind来源，不跨源补值。

## 文件结构

- `covered_call/data.py`：数据库只读取数、Parquet和数据检查；直接复用Milestone 1的历史条款恢复函数。
- `covered_call/selection.py`：纯信号选约，不读取未来日期。
- `covered_call/engine.py`：逐日现金、ETF、期权、分红和交易成本账本。
- `covered_call/metrics.py`：指标和独立对账，包括与标准源行情逐条核对。
- `covered_call/reporting.py`：当前阶段报告与静态图表。
- `data_mart/`：原始按年缓存、7个标准Parquet文件、质量检查与哈希清单。
- `outputs/milestone2/<run_id>/`：每次运行的所有CSV、JSON、参数、源码哈希及图表。

输出CSV按任务书保留标准机器字段名；报告、指标解释和说明使用中文。每次运行不会覆盖历史run_id；`latest_run.json`指向最近一次。
