@echo off
setlocal
title Previewnator — Install Context Menu

echo.
echo  Previewnator — Installing Windows Context Menu...
echo  -----------------------------------------------

:: Check for python command
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto :INSTALL
)

:: Check for py (Python Launcher)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py
    goto :INSTALL
)

:: Python not found
color 0C
echo  ERROR: Python was not found on your system.
echo  -----------------------------------------------
echo  Previewnator requires Python 3.7 or higher to function.
echo.
echo  Please download and install Python from:
echo  https://www.python.org/downloads/
echo.
echo  *Note: Ensure "Add Python to PATH" is checked during installation.*
echo.
echo  Opening download page...
timeout /t 3 >nul
start https://www.python.org/downloads/
pause
exit /b 1

:INSTALL
%PY_CMD% "%~dp0context_menu.py" --install
echo.
pause

