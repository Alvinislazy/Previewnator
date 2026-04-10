@echo off
title Previewnator — Uninstall Context Menu
echo.
echo  Previewnator — Removing Windows Context Menu...
echo  ---------------------------------------------
python "%~dp0context_menu.py" --uninstall
echo.
pause
