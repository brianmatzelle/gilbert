#!/bin/bash
# Run the Garvis Discord voice assistant bot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/server"

echo "🤖 Starting Garvis Discord Bot..."
echo ""

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found!"
    echo "   Copy env.example to .env and add your API keys:"
    echo "   cp env.example .env"
    exit 1
fi

# Check for DISCORD_BOT_TOKEN
if ! grep -q "DISCORD_BOT_TOKEN=." .env 2>/dev/null; then
    echo "⚠️  DISCORD_BOT_TOKEN not set in .env!"
    echo "   Add your Discord bot token:"
    echo "   DISCORD_BOT_TOKEN=your_token_here"
    exit 1
fi

# Run the bot
uv run python -m discord_bot.bot
