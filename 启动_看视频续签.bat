@echo off
chcp 65001 >nul
title Voer.host 自动看视频续签
cd /d "%~dp0"

echo ========================================================
echo         Voer.host 免费服务器看视频续签工具
echo ========================================================
echo.

if not exist config.json (
    if exist config.example.json (
        copy config.example.json config.json >nul
        echo [提示] 已自动为您创建 config.json，请先编辑填写账号密码！
        notepad config.json
        pause
        exit /b
    )
)

echo [1] 自动看视频续签 (默认第一台服务器)
echo [2] 一键为所有服务器续签 (--all)
echo [3] 查询服务器状态与剩余时间 (status)
echo [4] 启动 7x24 小时无人值守挂机守护模式 (loop)
echo.
set /p opt="请选择操作编号 [1-4, 默认1]: "

if "%opt%"=="2" (
    python voer_renew.py run --all
) else if "%opt%"=="3" (
    python voer_renew.py status
) else if "%opt%"=="4" (
    python voer_renew.py loop
) else (
    python voer_renew.py run
)

echo.
echo 执行完毕。按任意键退出...
pause >nul
