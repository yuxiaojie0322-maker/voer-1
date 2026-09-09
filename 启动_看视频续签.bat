@echo off
cd /d "%~dp0"

echo ========================================================
echo       Voer.host Auto Renew Tool
echo ========================================================
echo.
echo [1] Watch Ads Renew (Default single server)
echo [2] Renew All Servers (--all)
echo [3] Check Status and Time Remaining (status)
echo [4] Start 24x7 Daemon Loop Mode (loop)
echo [5] Auto Detect and Start Server (start)
echo [6] Test Push Notification (notify)
echo.
set /p opt="Select option [1-6, default 1]: "

if "%opt%"=="2" (
    python voer_renew.py run --all
) else if "%opt%"=="3" (
    python voer_renew.py status
) else if "%opt%"=="4" (
    python voer_renew.py loop
) else if "%opt%"=="5" (
    python voer_renew.py start
) else if "%opt%"=="6" (
    python voer_renew.py notify
) else (
    python voer_renew.py run
)

echo.
pause
