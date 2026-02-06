@echo off
setlocal
cd /d C:\Users\Administrator\Desktop\DAD

echo Removing existing virtualenv (if any)...
if exist .venv (
    rmdir /s /q .venv
)

echo Creating fresh virtualenv...
py -3 -m venv .venv
if %errorlevel% neq 0 (
    echo Failed to create virtualenv.
    goto :end
)

echo Activating virtualenv...
call .\.venv\Scripts\activate

echo Upgrading pip and installing requirements...
python -m pip install --upgrade pip > nul
python -m pip install --no-deps -r requirements.txt

echo Starting the GUI server controller...
start "" "%cd%\.venv\Scripts\python.exe" "%cd%\runserver_gui.py"

echo Setup complete. The GUI should open shortly.

:end
endlocal
