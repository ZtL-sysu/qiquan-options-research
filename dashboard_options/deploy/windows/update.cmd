@echo off
set PYTHONUTF8=1
set GJ_SCRIPTS=C:\JinkeDashboard\gjdata\scripts
cd /d C:\OptionsDashboard\app
C:\JinkeDashboard\conda\python.exe update.py >> C:\OptionsDashboard\app\logs\scheduled.log 2>&1
exit /b %errorlevel%
