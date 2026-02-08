$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $scriptRoot
try {
    Write-Host "Running syncServer.ps1..."
    & .\syncServer.ps1

    Write-Host "Starting production server (Waitress)..."
    & .\.venv\Scripts\python .\run_prod_server.py
} finally {
    Pop-Location
}
