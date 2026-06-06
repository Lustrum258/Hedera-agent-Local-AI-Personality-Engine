@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   Hedera QQ 机器人 启动脚本
echo ========================================
echo.

:: 检查NapCat目录
if not exist "NapCat\launcher.bat" (
    echo [错误] 未找到NapCat
    echo.
    echo 请先下载NapCat:
    echo 1. 访问 https://github.com/NapNeko/NapCatQQ/releases
    echo 2. 下载 NapCat.Shell.zip
    echo 3. 解压到 qq_bot\NapCat 目录
    echo.
    echo 或者运行 setup_napcat.ps1 获取下载链接
    pause
    exit /b 1
)

:: 检查Hedera是否运行
echo [1/3] 检查Hedera服务...
netstat -ano | findstr ":36313" >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] Hedera服务未运行，请先启动Hedera:
    echo   cd ..\hedera
    echo   python -m hedera.server.http
    echo.
    echo 是否继续启动NapCat？(Y/N)
    set /p continue=
    if /i "!continue!" neq "Y" exit /b 1
) else (
    echo ✅ Hedera服务已运行
)

:: 启动NapCat
echo.
echo [2/3] 启动NapCat...
echo.
echo [重要] 首次使用请按以下步骤操作:
echo   1. 扫码登录QQ
echo   2. 访问 http://localhost:6099 配置网络
echo   3. 添加WebSocket服务器，端口设置为 6700
echo.

cd NapCat
start "NapCat" launcher.bat

:: 等待NapCat启动
echo [3/3] 等待NapCat启动...
timeout /t 10 /nobreak >nul

:: 检查NapCat是否启动
netstat -ano | findstr ":6099" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ✅ NapCat已启动
    echo    WebUI地址: http://localhost:6099
) else (
    echo.
    echo ⚠️  NapCat可能还在启动中，请稍候...
)

echo.
echo ========================================
echo   下一步操作:
echo ========================================
echo.
echo 1. 在NapCat WebUI中配置WebSocket:
echo    - 访问 http://localhost:6099
echo    - 网络配置 -^> 添加WebSocket服务器
echo    - 端口: 6700
echo.
echo 2. 启动NoneBot2:
echo    cd qq_bot
echo    python bot.py
echo.
echo 3. 测试连接:
echo    python test_connection.py
echo.

pause