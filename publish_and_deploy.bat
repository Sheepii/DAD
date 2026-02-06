@echo off
setlocal

cd /d "%~dp0"
echo Working folder: %cd%
echo.

set /p COMMIT_MSG=Commit message: 
if "%COMMIT_MSG%"=="" (
    echo Publish cancelled: no message entered.
    goto :end
)

echo.
echo Staging changes...
git add -A
if errorlevel 1 goto :git_error

echo Creating commit...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 goto :commit_maybe_clean
goto :push_step

:commit_maybe_clean
git status --porcelain > "%TEMP%\dad_git_status_publish.tmp"
for %%A in ("%TEMP%\dad_git_status_publish.tmp") do set STATUS_SIZE=%%~zA
if "%STATUS_SIZE%"=="0" (
    echo No new file changes to commit. Continuing...
) else (
    del "%TEMP%\dad_git_status_publish.tmp" >nul 2>nul
    goto :git_error
)
del "%TEMP%\dad_git_status_publish.tmp" >nul 2>nul

:push_step
echo Pushing to origin/main...
git push origin main
if errorlevel 1 goto :git_error

echo Triggering VPS deploy...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deploy_to_vps.ps1"
if errorlevel 1 goto :deploy_error

echo.
echo SUCCESS: publish and deploy completed.
goto :end

:git_error
echo.
echo ERROR: Git command failed. See output above.
goto :end

:deploy_error
echo.
echo ERROR: Deploy script failed. Git push may still have succeeded.

:end
echo.
pause
endlocal
