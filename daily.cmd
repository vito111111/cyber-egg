@echo off
REM cyber-egg · daily fetch and rebuild the dashboard
REM Called by Windows Task Scheduler, or run by double-clicking.
REM Passes --sync-ranking on Mondays (model ranking updates weekly).

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

REM Resolve a working Python: prefer the py launcher, then python on PATH.
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY (
  where python >nul 2>&1 && set PY=python
)
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
  exit /b 1
)

REM Sync the model ranking on Mondays.
set SYNC=
for /f "tokens=*" %%d in ('powershell -NoProfile -Command "(Get-Date).DayOfWeek"') do set DOW=%%d
if /i "%DOW%"=="Monday" set SYNC=--sync-ranking

if not exist "%~dp0data" mkdir "%~dp0data"
echo [%date% %time%] start %SYNC% >> "%~dp0data\run-history.log"
%PY% run.py %SYNC% >> "%~dp0data\run-history.log" 2>&1
echo [%date% %time%] done, exit code %errorlevel% >> "%~dp0data\run-history.log"
echo. >> "%~dp0data\run-history.log"
