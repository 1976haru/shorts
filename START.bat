@echo off
setlocal
title ShortsMaker Studio v0.5.1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo Run INSTALL.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python app.py

if errorlevel 1 (
    echo.
    echo The program closed with an error.
    pause
)
endlocal
