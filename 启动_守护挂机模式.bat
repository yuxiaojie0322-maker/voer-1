@echo off
chcp 65001 >nul
title Voer.host 7x24小时全自动续签守护进程
cd /d "%~dp0"

echo ========================================================
echo       Voer.host 7x24小时无人值守守护模式 (Daemon)
echo ========================================================
echo.
echo 脚本将在后台保持运行：
echo - 自动监测每台服务器的剩余使用时间
echo - 时间不足时自动看视频增加 4 小时
echo - 今日达到上限（16小时）后自动休眠等待次日 UTC 重置
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

python voer_renew.py loop

pause
