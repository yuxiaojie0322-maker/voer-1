@echo off
chcp 65001 >nul
title 提取 GitHub Actions 部署专用凭据 (VOER_SESSION)
cd /d "%~dp0"

echo ========================================================
echo       提取 GitHub Actions 部署专用凭据 (VOER_SESSION)
echo ========================================================
echo.
echo 即将启动浏览器协助您登录：
echo 1. 登录成功后，脚本将自动提取 Session 凭证；
echo 2. 控制台会打印一行整段文本，直接复制到 GitHub Secrets 即可；
echo 3. GitHub Actions 将直接凭此 Session 免验证码秒进面板！
echo.
pause

python voer_renew.py login

echo.
echo 请复制上方内容，填入 GitHub 仓库:
echo Settings -> Secrets and variables -> Actions -> New repository secret
echo.
pause
