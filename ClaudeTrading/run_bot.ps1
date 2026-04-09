# Political Trade Mirror Bot Launcher (PowerShell)
# Handles Windows Store Python and PATH resolution

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "Starting Political Trade Mirror Bot..." -ForegroundColor Green
Write-Host "Working directory: $scriptDir" -ForegroundColor Gray

# Try multiple Python detection methods
$pythonFound = $false
$pythonCmd = $null

# Method 1: Direct python command (works if in PATH)
try {
    $test = python --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pythonCmd = "python"
        $pythonFound = $true
        Write-Host "Found: python" -ForegroundColor Yellow
    }
} catch {}

# Method 2: python3 command
if (-not $pythonFound) {
    try {
        $test = python3 --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = "python3"
            $pythonFound = $true
            Write-Host "Found: python3" -ForegroundColor Yellow
        }
    } catch {}
}

# Method 3: py launcher (Windows)
if (-not $pythonFound) {
    try {
        $test = py --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = "py"
            $pythonFound = $true
            Write-Host "Found: py launcher" -ForegroundColor Yellow
        }
    } catch {}
}

# Method 4: Full path to Windows Store Python
if (-not $pythonFound) {
    $winStorePath = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe"
    if (Test-Path $winStorePath) {
        $pythonCmd = $winStorePath
        $pythonFound = $true
        Write-Host "Found: Windows Store Python at $winStorePath" -ForegroundColor Yellow
    }
}

# Method 5: FL Studio Python (if installed)
if (-not $pythonFound) {
    $flPath = "C:\Program Files\Image-Line\FL Studio 21\System\Tools\LilyPond\bin\python.exe"
    if (Test-Path $flPath) {
        $pythonCmd = $flPath
        $pythonFound = $true
        Write-Host "Found: FL Studio Python" -ForegroundColor Yellow
    }
}

if (-not $pythonFound) {
    Write-Host "ERROR: Python not found in any standard location" -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org or https://www.microsoft.com/store/apps" -ForegroundColor Red
    exit 1
}

# Run main.py
Write-Host "Launching main.py with: $pythonCmd" -ForegroundColor Cyan
& $pythonCmd main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Bot exited with code: $LASTEXITCODE" -ForegroundColor Red
} else {
    Write-Host "Bot completed successfully" -ForegroundColor Green
}
