#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptRoot
try {
    Write-Host "Checking repository status..." -ForegroundColor Cyan
    git status --short

    $message = $args -join " "
    if (-not $message) {
        $message = Read-Host "Commit message"
    }

    if (-not $message) {
        Write-Host "Commit cancelled (no message provided)." -ForegroundColor Yellow
        return
    }

    Write-Host "Adding all changes..." -ForegroundColor Cyan
    git add --all

    Write-Host "Committing: $message" -ForegroundColor Cyan
    git commit -m "$message"

    Write-Host "Pushing to origin/main..." -ForegroundColor Cyan
    git push origin main

    Write-Host "Commit and push complete." -ForegroundColor Green
} finally {
    Pop-Location
}
