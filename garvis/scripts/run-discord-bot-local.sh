#!/bin/bash
# Run the Garvis Discord bot with LOCAL models (no cloud APIs needed)
# Requires: setup-local-models.sh to be run first

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT/server"

echo "🤖 Starting Garvis Discord Bot (LOCAL MODE)"
echo ""
echo "Using local models:"
echo "  🧠 LLM: llama.cpp + Qwen2.5-7B"
echo "  🎤 STT: faster-whisper"
echo "  🔊 TTS: Kokoro (CUDA) or Piper (CPU)"
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
    echo "   Start it first with: ./run-llama-server.sh"
    echo ""
    echo "   Or start it in another terminal and wait for it to load."
    exit 1
fi

echo "✅ llama.cpp server detected"

# Check for TTS model (Kokoro preferred, Piper fallback)
KOKORO_MODEL="$PROJECT_ROOT/models/kokoro/kokoro-v1.0.onnx"
PIPER_MODEL="$PROJECT_ROOT/models/piper/en_US-lessac-medium.onnx"

if [ -f "$KOKORO_MODEL" ]; then
    echo "✅ Kokoro TTS model found (high quality)"
    export USE_KOKORO_TTS=true
    
    # Set up CUDA for Kokoro (onnxruntime-gpu)
    # kokoro-onnx has a bug detecting GPU, so we force it via env var
    export ONNX_PROVIDER=CUDAExecutionProvider
    
    # Add cuDNN libraries to path (bundled with onnxruntime-gpu)
    CUDNN_PATH="$PROJECT_ROOT/server/.venv/lib/python3.13/site-packages/nvidia/cudnn/lib"
    if [ -d "$CUDNN_PATH" ]; then
        export LD_LIBRARY_PATH="$CUDNN_PATH:$LD_LIBRARY_PATH"
        echo "   → CUDA/cuDNN enabled for GPU acceleration"
    fi
elif [ -f "$PIPER_MODEL" ]; then
    echo "✅ Piper TTS model found (fast CPU)"
    export USE_KOKORO_TTS=false
else
    echo "⚠️  No TTS model found!"
    echo "   Run setup-local-models.sh first to download models."
    exit 1
fi
echo ""

# Set environment variables for local mode
export USE_LOCAL_LLM=true
export USE_LOCAL_STT=true
export USE_LOCAL_TTS=true

# Run the bot
uv run python -m discord_bot.bot
