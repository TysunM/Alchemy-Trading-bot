@echo off
REM Political Trade Mirror Bot - Setup & Run
REM Installs dependencies and launches bot

echo.
echo ════════════════════════════════════════════════════════════
echo  Political Trade Mirror Bot - Setup & Run
echo ════════════════════════════════════════════════════════════
echo.

cd /d "%~dp0"

REM Step 1: Find Python
echo [1/3] Detecting Python installation...
set PYTHON_CMD=

REM Try python
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    echo       ✓ Found: python
    goto :python_found
)

REM Try python3
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    echo       ✓ Found: python3
    goto :python_found
)

REM Try py launcher
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    echo       ✓ Found: py launcher
    goto :python_found
)

REM Try Windows Store Python
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe" (
    set PYTHON_CMD=%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe
    echo       ✓ Found: Windows Store Python
    goto :python_found
)

REM If no Python found, exit
echo.
echo ERROR: Python not found. Please install Python first:
echo   - From https://www.python.org (recommended)
echo   - Or: Microsoft Store ^> Search for Python
echo.
pause
exit /b 1

:python_found
echo.
echo [2/3] Installing dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [3/3] Launching bot...
echo.
%PYTHON_CMD% main.py

if %errorlevel% neq 0 (
    echo.
    echo Bot exited with error code: %errorlevel%
    pause
)

exit /b %errorlevel%
