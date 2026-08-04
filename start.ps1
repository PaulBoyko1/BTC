$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Crypto Interval Analyzer - live API launcher" -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv .venv
    } else {
        python -m venv .venv
    }
}

Write-Host "Installing or verifying backend dependencies..."
& ".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"

Write-Host "Opening http://localhost:8000/"
Start-Process "http://localhost:8000/"

Write-Host "Starting the live Binance and contract-price API..." -ForegroundColor Green
& ".venv\Scripts\python.exe" -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000
