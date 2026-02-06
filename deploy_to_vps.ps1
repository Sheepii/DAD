Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [string]$Host = "46.8.112.66",
    [string]$User = "Administrator",
    [string]$Branch = "main",
    [string]$RemotePath = "C:\Users\Administrator\Desktop\DAD",
    [switch]$SkipMigrate,
    [string]$RestartCommand = ""
)

$migrateStep = ""
if (-not $SkipMigrate) {
    $migrateStep = ".\.venv\Scripts\python manage.py migrate`n"
}

$restartStep = ""
if ($RestartCommand) {
    $restartStep = "$RestartCommand`n"
}

$remoteScript = @"
Set-StrictMode -Version Latest
`$ErrorActionPreference = 'Stop'
Set-Location '$RemotePath'
git pull origin $Branch
.\.venv\Scripts\python -m pip install -r requirements.txt
$migrateStep$restartStep
Write-Host 'Remote deploy completed successfully.' -ForegroundColor Green
"@

$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))
$target = "$User@$Host"

Write-Host "Deploying to $target ..." -ForegroundColor Cyan
ssh $target "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"

Write-Host "Done." -ForegroundColor Green
