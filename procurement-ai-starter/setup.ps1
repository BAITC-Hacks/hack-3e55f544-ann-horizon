$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "=== Procurement AI setup ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.13+ and run this script again." -ForegroundColor Red
    exit 1
}

$pyVersion = python --version
Write-Host "Detected: $pyVersion"

$venvPython = ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    python -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Virtual environment creation failed." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Installing dependencies into .venv..."
python -m pip --python $venvPython install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependency installation failed." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env created. No API key is needed for local demo mode." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next: run .\run.ps1 for the sample plan or .\api.ps1 for the API."
