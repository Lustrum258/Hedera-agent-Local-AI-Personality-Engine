@echo off
chcp 65001 >nul
title Hedera 构建工具
setlocal enabledelayedexpansion

set PROJECT_DIR=%~dp0
set BUILD_DIR=%PROJECT_DIR%build
set DIST_DIR=%PROJECT_DIR%dist

echo ┌───────────────────────────────────────────────┐
echo │        Hedera v0.7.0 - 独立版构建工具           │
echo └───────────────────────────────────────────────┘
echo.

:: ── 检查依赖 ──
echo [1/5] 检查依赖...

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo !!! 找不到 Python，请安装 Python 3.10+ !!!
    pause
    exit /b 1
)

python -c "import PyInstaller" 2>nul
if %ERRORLEVEL% neq 0 (
    echo 安装 PyInstaller...
    python -m pip install pyinstaller
)

python -c "import openpyxl" 2>nul
if %ERRORLEVEL% neq 0 (
    echo 安装 openpyxl...
    python -m pip install openpyxl
)

python -c "import requests" 2>nul
if %ERRORLEVEL% neq 0 (
    echo 安装 requests...
    python -m pip install requests
)

python -c "import yaml" 2>nul
if %ERRORLEVEL% neq 0 (
    echo 安装 pyyaml...
    python -m pip install pyyaml
)

echo  ✓ 依赖检查完成
echo.

:: ── 读取版本号 ──
for /f "tokens=2 delims= " %%a in ('findstr "version" "%PROJECT_DIR%hedera\__init__.py"') do set HEDERA_VER=%%a
set HEDERA_VER=%HEDERA_VER:"=%
echo [2/5] 版本: Hedera %HEDERA_VER%
echo.

:: ── 清理旧构建 ──
echo [3/5] 清理旧构建...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
echo  ✓ 清理完成
echo.

:: ── 构建 ──
echo [4/5] 开始构建 PyInstaller 包...

:: 收集数据文件
set DATA_FLAGS=--add-data "%PROJECT_DIR%hedera\default.yaml;hedera"
set DATA_FLAGS=%DATA_FLAGS% --add-data "%PROJECT_DIR%hedera\server\static;hedera\server\static"
set DATA_FLAGS=%DATA_FLAGS% --add-data "%PROJECT_DIR%hedera\plugin\builtin;hedera\plugin\builtin"
set DATA_FLAGS=%DATA_FLAGS% --add-data "%PROJECT_DIR%hedera\plugin\examples;hedera\plugin\examples"
set DATA_FLAGS=%DATA_FLAGS% --add-data "%PROJECT_DIR%hedera\plugin\base.py;hedera\plugin"
set DATA_FLAGS=%DATA_FLAGS% --add-data "%PROJECT_DIR%hedera\plugin\manager.py;hedera\plugin"

python -m PyInstaller ^
    --name "Hedera" ^
    --onefile ^
    --console ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    --specpath "%BUILD_DIR%" ^
    --hidden-import "openpyxl" ^
    --hidden-import "openpyxl.cell._writer" ^
    --hidden-import "yaml" ^
    --hidden-import "requests" ^
    %DATA_FLAGS% ^
    "%PROJECT_DIR%hedera\__main__.py"

if %ERRORLEVEL% neq 0 (
    echo !!! 构建失败，错误码 %ERRORLEVEL% !!!
    pause
    exit /b %ERRORLEVEL%
)

echo  ✓ 构建完成
echo    输出: %DIST_DIR%\Hedera.exe
echo.

:: ── 复制额外文件 ──
echo [5/5] 复制额外文件...
copy "%PROJECT_DIR%config.yaml" "%DIST_DIR%\config.yaml" >nul 2>&1
if exist "%PROJECT_DIR%README.md" copy "%PROJECT_DIR%README.md" "%DIST_DIR%\" >nul 2>&1

:: 复制默认配置和数据
xcopy "%PROJECT_DIR%data" "%DIST_DIR%\data\" /E /I /Q >nul 2>&1
xcopy "%PROJECT_DIR%plugins" "%DIST_DIR%\plugins\" /E /I /Q >nul 2>&1

echo  ✓ 文件复制完成
echo.

:: ── 输出结果 ──
echo ┌───────────────────────────────────────────────┐
echo │               构建完成 ✓                        │
echo ├───────────────────────────────────────────────┤
echo │  EXE: %DIST_DIR%\Hedera.exe                    │
echo │  配置: %DIST_DIR%\config.yaml                   │
echo │  大小: 
for %%f in ("%DIST_DIR%\Hedera.exe") do echo         %%~zf 字节
echo └───────────────────────────────────────────────┘
echo.
echo 使用方法:
echo   %DIST_DIR%\Hedera.exe serve
echo   %DIST_DIR%\Hedera.exe init
echo.
echo 注意: 首次运行需填写 config.yaml 中的 API Key
echo.

pause
