@echo off
setlocal
cd /d "%~dp0"

echo Crypto Interval Analyzer - live API launcher
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :error
)

echo Installing or verifying backend dependencies...
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :error

echo.
echo Opening http://localhost:8000/
start "" http://localhost:8000/

echo Starting the live Binance and contract-price API...
.venv\Scripts\python.exe -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000
exit /b %errorlevel%

:error
echo.
echo Startup failed. Confirm Python 3.11 or newer is installed.
pause
exit /b 1
