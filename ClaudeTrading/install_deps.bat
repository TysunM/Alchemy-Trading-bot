@echo off
REM Install dependencies for Political Trade Mirror Bot

cd /d "%~dp0"

echo Installing dependencies...
echo.

REM Try multiple Python commands
for %%P in (python python3 py) do (
    %%P -m pip install -q alpaca-py pandas requests schedule 2>nul
    if %errorlevel% equ 0 (
        echo ✓ Dependencies installed with %%P
        exit /b 0
    )
)

REM Try Windows Store Python explicitly
"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe" -m pip install -q alpaca-py pandas requests schedule 2>nul
if %errorlevel% equ 0 (
    echo ✓ Dependencies installed with Windows Store Python
    exit /b 0
)

echo.
echo ERROR: Could not install dependencies. Try running manually:
echo   python -m pip install alpaca-py pandas requests schedule
exit /b 1
