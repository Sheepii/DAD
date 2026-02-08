$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $scriptRoot

Write-Host "Running syncServer.ps1..."
& .\syncServer.ps1

Write-Host "Activating venv..."
& .\.venv\Scripts\Activate.ps1

Write-Host "Starting production server (Waitress)..."
python .\run_prod_server.py

Pop-Location
