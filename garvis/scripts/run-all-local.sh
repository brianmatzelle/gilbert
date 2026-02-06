#!/bin/bash
# Run both llama.cpp server AND the Discord bot with local models
# This script handles starting everything in the right order

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

echo "=========================================="
echo "  Garvis Local AI - Full Stack Startup"
echo "=========================================="
echo ""

# Check if models exist
MODEL="$PROJECT_ROOT/models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
if [ ! -f "$MODEL" ]; then
    echo "❌ Qwen model not found!"
    echo "   Run setup-local-models.sh first."
    exit 1
fi

PIPER_MODEL="$PROJECT_ROOT/models/piper/en_US-lessac-medium.onnx"
if [ ! -f "$PIPER_MODEL" ]; then
    echo "❌ Piper model not found!"
    echo "   Run setup-local-models.sh first."
    exit 1
fi

# Check if llama.cpp is built
LLAMA_SERVER="$PROJECT_ROOT/llama.cpp/build/bin/llama-server"
if [ ! -f "$LLAMA_SERVER" ]; then
    echo "❌ llama.cpp not built!"
    echo "   Run setup-local-models.sh first."
    exit 1
fi

echo "✅ All models and binaries found"
echo ""

# Start llama.cpp server in background
echo "🚀 Starting llama.cpp server..."
"$LLAMA_SERVER" \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8080 \
    --n-gpu-layers 99 \
    --ctx-size 8192 \
    --batch-size 512 \
    --threads 4 \
    --parallel 1 \
    --cont-batching &

LLAMA_PID=$!
echo "   PID: $LLAMA_PID"

# Wait for server to be ready
echo "⏳ Waiting for llama.cpp server to be ready..."
for i in {1..60}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "✅ llama.cpp server ready!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "❌ Timeout waiting for llama.cpp server"
        kill $LLAMA_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $LLAMA_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start Discord bot
echo "🤖 Starting Discord bot with local models..."
cd "$PROJECT_ROOT/server"

export USE_LOCAL_LLM=true
export USE_LOCAL_STT=true
export USE_LOCAL_TTS=true

uv run python -m discord_bot.bot

# If bot exits, cleanup
cleanup
