@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo       Voer.host 核心脚本私人仓库访问凭据 (Token) 配置
echo ========================================================
echo.
echo 本工具用于为本地环境配置访问私有核心仓库的只读 Token。
echo 如果您只在 GitHub Actions 中运行，可直接在 GitHub 仓库中配置 Secret：
echo   Secret 名称: CORE_SCRIPT_TOKEN
echo.
echo --------------------------------------------------------
set /p user_token="请输入您的 GitHub Personal Access Token (PAT): "
if "%user_token%"=="" (
    echo.
    echo 未输入 Token，配置取消。
    pause
    exit /b
)

set /p user_repo="请输入私有核心仓库名称 [回车默认: yuxiaojie0322-maker/my-private-scripts]: "
if "%user_repo%"=="" (
    set user_repo=yuxiaojie0322-maker/my-private-scripts
)

echo.
echo 正在保存配置至 config.json...

node -e "
const fs = require('fs');
let cfg = {};
if (fs.existsSync('config.json')) {
    try { cfg = JSON.parse(fs.readFileSync('config.json', 'utf-8')); } catch(e){}
}
cfg.core_token = process.argv[1];
cfg.core_repo = process.argv[2];
fs.writeFileSync('config.json', JSON.stringify(cfg, null, 2), 'utf-8');
console.log('✅ 配置已成功保存至 config.json！');
" "%user_token%" "%user_repo%"

echo.
echo 配置完成！您现在可以正常运行其它启动脚本。
echo.
pause
