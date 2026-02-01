#!/bin/bash
# Start llama.cpp server with Qwen2.5-7B

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="$SCRIPT_DIR/models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
LLAMA_SERVER="$SCRIPT_DIR/llama.cpp/build/bin/llama-server"

if [ ! -f "$MODEL" ]; then
    echo "❌ Model not found: $MODEL"
    echo "   Run setup-local-models.sh first"
    exit 1
fi

if [ ! -f "$LLAMA_SERVER" ]; then
    echo "❌ llama-server not found: $LLAMA_SERVER"
    echo "   Run setup-local-models.sh first"
    exit 1
fi

echo "🚀 Starting llama.cpp server..."
echo "   Model: Qwen2.5-7B-Instruct Q4_K_M"
echo "   Port: 8080"
echo "   GPU Layers: All (99)"
echo ""

"$LLAMA_SERVER" \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8080 \
    --n-gpu-layers 99 \
    --ctx-size 8192 \
    --batch-size 512 \
    --threads 4 \
    --parallel 1 \
    --cont-batching
