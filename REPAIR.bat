@echo off
setlocal
title ShortsMaker Studio v0.7.1 Repair

echo Removing broken virtual environment...
if exist ".venv" rmdir /s /q ".venv"

echo.
echo Repair complete.
echo Now run INSTALL.bat.
pause
endlocal
