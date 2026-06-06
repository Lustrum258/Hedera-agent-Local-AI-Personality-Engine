@echo off
echo Starting Hedera QQ Bot...
echo.
echo Make sure you have:
echo 1. NapCat or LLOneBot running (default port 6700)
echo 2. Hedera server running (default port 36313)
echo.
cd /d "%~dp0"
python bot.py
pause