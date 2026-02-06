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
if errorlevel 1 goto :git_error

echo Pushing to origin/main...
git push origin main
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
