@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist "..\04_示例输出_给人查看" mkdir "..\04_示例输出_给人查看"
C:\ProgramData\miniforge3\python.exe "..\01_机器运行文件\国金数据库取数.py" 下载 --表 AShareEODPrices --代码 600519.SH --开始 20250101 --结束 20250131 --字段 S_INFO_WINDCODE,TRADE_DT,S_DQ_OPEN,S_DQ_HIGH,S_DQ_LOW,S_DQ_CLOSE,S_DQ_PCTCHANGE --行数上限 1000 --输出 "..\04_示例输出_给人查看\茅台_2025年1月日行情.xlsx"
pause
