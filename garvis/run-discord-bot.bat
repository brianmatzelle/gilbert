@echo off
REM Run the Garvis Discord voice assistant bot on Windows

cd /d "%~dp0server"

echo Starting Garvis Discord Bot...
echo.

REM Check for .env file
if not exist ".env" (
    echo WARNING: No .env file found!
    echo    Copy env.example to .env and add your API keys:
    echo    copy env.example .env
    pause
    exit /b 1
)

REM Run the bot
uv run python -m discord_bot.bot

pause
