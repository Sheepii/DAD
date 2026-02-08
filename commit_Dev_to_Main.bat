@echo off
setlocal

cd /d "%~dp0"
echo Working folder: %cd%
echo.

set /p COMMIT_MSG=Commit message: 
if "%COMMIT_MSG%"=="" (
    echo Commit cancelled: no message entered.
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
git status --porcelain > "%TEMP%\dad_git_status.tmp"
for %%A in ("%TEMP%\dad_git_status.tmp") do set STATUS_SIZE=%%~zA
if "%STATUS_SIZE%"=="0" (
    echo No new file changes to commit. Continuing to push existing local commits...
) else (
    del "%TEMP%\dad_git_status.tmp" >nul 2>nul
    goto :git_error
)
del "%TEMP%\dad_git_status.tmp" >nul 2>nul

:push_step
echo Pushing dev into origin/main...
git push origin dev:main
if errorlevel 1 goto :git_error

echo.
echo SUCCESS: commit and push completed.
goto :end

:git_error
echo.
echo ERROR: Git command failed. See output above.

:end
echo.
pause
endlocal
