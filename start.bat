@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0;%PYTHONPATH%

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

:menu
cls
echo.
echo   ========================================
echo     Hedera - AI Agent
echo   ========================================
echo.
echo   [1] Web UI
echo   [2] CLI
echo   [3] Exit
echo.
set /p choice=Select:

if "%choice%"=="1" goto webui
if "%choice%"=="2" goto cli
if "%choice%"=="3" goto end
goto menu

:webui
echo Starting Web UI...
start "Hedera" python -m hedera desktop
echo Started. Close this window to stop.
pause
goto menu

:cli
python -m hedera chat
pause
goto menu

:end
