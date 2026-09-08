@echo off
chcp 65001 > nul
cd /d "%~dp0"
C:\ProgramData\miniforge3\python.exe "..\01_机器运行文件\国金数据库取数.py" 健康检查
pause
