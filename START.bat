@echo off
setlocal
title ShortsMaker Studio v0.7.0

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo Run INSTALL.bat first.
    pause
    exit /b 1
)

rem Some Windows virtualenvs can load Tcl/Tk DLLs from the system Python.
rem Point Tkinter at the matching system Tcl scripts before activating venv.
for /f "delims=" %%P in ('python -c "import pathlib, sysconfig; print(pathlib.Path(sysconfig.get_path('data')) / 'tcl' / 'tcl8.6')" 2^>nul') do (
    if exist "%%~P\init.tcl" set "TCL_LIBRARY=%%~P"
)
for /f "delims=" %%P in ('python -c "import pathlib, sysconfig; print(pathlib.Path(sysconfig.get_path('data')) / 'tcl' / 'tk8.6')" 2^>nul') do (
    if exist "%%~P\tk.tcl" set "TK_LIBRARY=%%~P"
)

call ".venv\Scripts\activate.bat"
python app.py

if errorlevel 1 (
    echo.
    echo The program closed with an error.
    pause
)
endlocal
