@echo off
setlocal
cd /d "%~dp0" || goto failed

if not exist ".venv\Scripts\python.exe" (
    where /q py.exe
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3 -m venv .venv
    )
    if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" -c "import tkinter, comtypes" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    ".venv\Scripts\python.exe" -c "import tkinter, comtypes"
    if errorlevel 1 goto failed
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0overlay.py"
exit /b %errorlevel%

:failed
echo Setup failed. Install Python 3.9 or later for Windows with Tkinter and pip, then try again.
echo See README.md for manual setup commands.
pause
exit /b 1
