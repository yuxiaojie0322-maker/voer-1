@echo off
cd /d "%~dp0"
echo ========================================================
echo       Exporting VOER_SESSION for GitHub Actions
echo ========================================================
echo.
echo Launching browser, please login in the opened window...
echo.
python voer_renew.py login
echo.
pause
