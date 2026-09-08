@echo off
chcp 65001 > nul
cd /d "%~dp0"
C:\ProgramData\miniforge3\python.exe "..\01_机器运行文件\检查基金指数更新时间.py" --输出目录 "..\00_给人看的说明"
pause
