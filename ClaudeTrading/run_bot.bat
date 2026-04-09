@echo off
REM Political Trade Mirror Bot Launcher
REM Bypasses Windows Store Python shortcut issues

cd /d "%~dp0"

REM Try to find a working Python installation
for %%I in (python.exe python3.exe py.exe) do (
    where %%I >nul 2>&1
    if errorlevel 0 (
        echo Starting Political Trade Mirror Bot with %%I...
        %%I main.py
        goto :eof
    )
)

REM Fallback: Try Windows Store Python directly
echo Attempting Windows Store Python fallback...
cmd /c start "" python.exe main.py

:eof
