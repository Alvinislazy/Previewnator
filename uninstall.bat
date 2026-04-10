@echo off
setlocal
title Previewnator — Uninstall Context Menu

echo.
echo  Previewnator — Removing Windows Context Menu...
echo  ---------------------------------------------

:: Check for python command
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto :UNINSTALL
)

:: Check for py (Python Launcher)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py
    goto :UNINSTALL
)

:: Python not found
color 0C
echo  ERROR: Python was not found on your system.
echo  -----------------------------------------------
echo  Previewnator requires Python for uninstallation.
echo.
echo  Please download and install Python from:
echo  https://www.python.org/downloads/
echo.
echo  Opening download page...
timeout /t 3 >nul
start https://www.python.org/downloads/
pause
exit /b 1

:UNINSTALL
%PY_CMD% "%~dp0context_menu.py" --uninstall
echo.
pause

