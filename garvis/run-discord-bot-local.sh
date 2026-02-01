#!/bin/bash
# Run the Garvis Discord bot with LOCAL models (no cloud APIs needed)
# Requires: setup-local-models.sh to be run first

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/server"

echo "🤖 Starting Garvis Discord Bot (LOCAL MODE)"
echo ""
echo "Using local models:"
echo "  🧠 LLM: llama.cpp + Qwen2.5-7B"
echo "  🎤 STT: faster-whisper"
echo "  🔊 TTS: Piper"
echo ""

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found!"
    echo "   Copy env.example to .env and configure:"
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

# Check if llama.cpp server is running
if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "⚠️  llama.cpp server not running!"
    echo "   Start it first with: ../run-llama-server.sh"
    echo ""
    echo "   Or start it in another terminal and wait for it to load."
    exit 1
fi

echo "✅ llama.cpp server detected"

# Check for Piper model
PIPER_MODEL="$SCRIPT_DIR/models/piper/en_US-lessac-medium.onnx"
if [ ! -f "$PIPER_MODEL" ]; then
    echo "⚠️  Piper model not found!"
    echo "   Run setup-local-models.sh first to download models."
    exit 1
fi

echo "✅ Piper TTS model found"
echo ""

# Set environment variables for local mode
export USE_LOCAL_LLM=true
export USE_LOCAL_STT=true
export USE_LOCAL_TTS=true

# Run the bot
uv run python -m discord_bot.bot
