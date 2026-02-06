Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptRoot
try {
    Write-Host "Pulling latest changes from origin/main..."
    git pull origin main

    Write-Host "Ensuring dependencies are installed..."
    .\.venv\Scripts\python -m pip install -r requirements.txt

    # TODO: restart your server process here if needed (e.g., stop/start or service restart).
    Write-Host "Sync completed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}
