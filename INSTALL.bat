@echo off
setlocal
title ShortsMaker Studio v0.5.1 Installer

echo ============================================
echo ShortsMaker Studio v0.5.1 Installer
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python Launcher ^(py.exe^) was not found.
    echo Please install Python 3.11 or 3.12 from python.org.
    echo During installation, check "Add python.exe to PATH".
    pause
    exit /b 1
)

set "PY_CMD="

py -3.12 -V >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.12"

if not defined PY_CMD (
    py -3.11 -V >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.11"
)

if not defined PY_CMD (
    py -3 -V >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3"
)

if not defined PY_CMD (
    echo ERROR: Python 3 was not found.
    pause
    exit /b 1
)

echo Python command: %PY_CMD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create .venv
        pause
        exit /b 1
    )
)

echo Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Failed to activate .venv
    pause
    exit /b 1
)

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip upgrade failed.
    pause
    exit /b 1
)

echo Installing requirements...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: requirements installation failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo Installation completed successfully.
echo Run START.bat to launch ShortsMaker Studio.
echo ============================================
pause
endlocal
