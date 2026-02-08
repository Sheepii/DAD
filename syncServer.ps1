Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-NativeOrFail {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLabel,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$CommandLabel failed with exit code $LASTEXITCODE."
    }
}

function Test-PythonImport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )

    & .\.venv\Scripts\python -c "import $ModuleName"
    return ($LASTEXITCODE -eq 0)
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptRoot
try {
    Write-Host "Pulling latest changes from origin/main..."
    Invoke-NativeOrFail -CommandLabel "git pull" -Command { git pull --ff-only origin main }

    Write-Host "Ensuring dependencies are installed..."
    Invoke-NativeOrFail -CommandLabel "pip install requirements" -Command { .\.venv\Scripts\python -m pip install -r requirements.txt }
    Invoke-NativeOrFail -CommandLabel "pip install waitress" -Command { .\.venv\Scripts\python -m pip install waitress==2.1.0 }

    Write-Host "Verifying waitress import..."
    Invoke-NativeOrFail -CommandLabel "waitress import check" -Command { .\.venv\Scripts\python -c "import waitress; import importlib.metadata as m; print('waitress', m.version('waitress'))" }

    Write-Host "Verifying Django import..."
    if (-not (Test-PythonImport -ModuleName "django.conf")) {
        Write-Host "Django import failed; force-reinstalling Django==6.0.2..."
        Invoke-NativeOrFail -CommandLabel "pip reinstall django" -Command { .\.venv\Scripts\python -m pip install --no-cache-dir --force-reinstall Django==6.0.2 }
        Invoke-NativeOrFail -CommandLabel "django import check" -Command { .\.venv\Scripts\python -c "import django.conf; import django; print('django', django.get_version())" }
    } else {
        Invoke-NativeOrFail -CommandLabel "django import check" -Command { .\.venv\Scripts\python -c "import django.conf; import django; print('django', django.get_version())" }
    }

    # TODO: restart your server process here if needed (e.g., stop/start or service restart).
    Write-Host "Sync completed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}
