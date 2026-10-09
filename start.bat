@echo off
rem Windows: double-click this file to start LeadPilot.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python run.py %*
  ) else (
    echo Python 3.12 or newer is required. Install it from https://www.python.org/downloads/
    echo Tick "Add python.exe to PATH" in the installer, then double-click this file again.
  )
)
echo.
pause
