@echo off
cd /d "%~dp0"
echo ========================================================
echo   Launch Real Chrome to Bypass Turnstile Verification
echo ========================================================
echo.
echo 1. Starting your real Chrome with remote debugging on port 9222...
echo.

start "" chrome.exe --remote-debugging-port=9222 --user-data-dir="%TEMP%\voer_chrome_debug" "https://voer.host/login"

echo 2. Please log in on the opened Real Chrome window.
echo    Because it is your REAL Chrome, Cloudflare Turnstile will succeed!
echo.
echo 3. Once you see the server panel (https://voer.host/panel),
echo    press any key below to extract the session...
echo.
pause

echo.
echo Extracting session from real Chrome...
python voer_renew.py login --cdp http://127.0.0.1:9222

echo.
pause
