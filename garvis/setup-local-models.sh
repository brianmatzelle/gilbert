#!/bin/bash
# Setup script for local AI models (llama.cpp + Qwen, faster-whisper, Piper TTS)
# Optimized for RTX 4070 (12GB VRAM)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/models"

echo "=========================================="
echo "  Garvis Local AI Setup"
echo "  Target: RTX 4070 (12GB VRAM)"
echo "=========================================="
echo ""

# Create models directory
mkdir -p "$MODELS_DIR"
mkdir -p "$MODELS_DIR/llm"
mkdir -p "$MODELS_DIR/whisper"
mkdir -p "$MODELS_DIR/piper"
mkdir -p "$MODELS_DIR/kokoro"

# Check for CUDA
echo "Checking CUDA availability..."
if command -v nvcc &> /dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $6}' | cut -d',' -f1)
    echo "✅ CUDA found: $CUDA_VERSION"
else
    echo "⚠️  CUDA not found in PATH. Make sure CUDA toolkit is installed."
    echo "   Download from: https://developer.nvidia.com/cuda-downloads"
fi

# ==========================================
# 1. LLAMA.CPP SETUP
# ==========================================
echo ""
echo "=========================================="
echo "  1. Setting up llama.cpp with CUDA"
echo "=========================================="

LLAMA_DIR="$SCRIPT_DIR/llama.cpp"

if [ -d "$LLAMA_DIR" ]; then
    echo "llama.cpp directory exists, updating..."
    cd "$LLAMA_DIR"
    git pull
else
    echo "Cloning llama.cpp..."
    cd "$SCRIPT_DIR"
    git clone https://github.com/ggerganov/llama.cpp.git
    cd "$LLAMA_DIR"
fi

echo "Building llama.cpp with CUDA support..."
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)

echo "✅ llama.cpp built successfully"

# ==========================================
# 2. DOWNLOAD QWEN2.5-7B MODEL
# ==========================================
echo ""
echo "=========================================="
echo "  2. Downloading Qwen2.5-7B-Instruct"
echo "=========================================="

LLM_MODEL="$MODELS_DIR/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"

if [ -f "$LLM_MODEL" ]; then
    echo "✅ Qwen2.5-7B model already downloaded"
else
    echo "Downloading Qwen2.5-7B-Instruct Q4_K_M (~4.7GB)..."
    
    # Using bartowski's quantized version (single file, properly quantized)
    if command -v huggingface-cli &> /dev/null; then
        huggingface-cli download bartowski/Qwen2.5-7B-Instruct-GGUF \
            Qwen2.5-7B-Instruct-Q4_K_M.gguf \
            --local-dir "$MODELS_DIR/llm"
    else
        echo "huggingface-cli not found, using wget..."
        wget -O "$LLM_MODEL" \
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
    fi
    
    echo "✅ Qwen2.5-7B model downloaded"
fi

# ==========================================
# 3. SETUP WHISPER MODEL
# ==========================================
echo ""
echo "=========================================="
echo "  3. Setting up faster-whisper"
echo "=========================================="

# faster-whisper auto-downloads models, but we can pre-download
echo "faster-whisper will auto-download the model on first use."
echo "Recommended model: 'small' (~1GB VRAM)"
echo ""
echo "To pre-download, run in Python:"
echo "  from faster_whisper import WhisperModel"
echo "  model = WhisperModel('small', device='cuda', compute_type='float16')"

# ==========================================
# 4. SETUP PIPER TTS
# ==========================================
echo ""
echo "=========================================="
echo "  4. Setting up Piper TTS"
echo "=========================================="

PIPER_MODEL_DIR="$MODELS_DIR/piper"
PIPER_VOICE="en_US-lessac-medium"

# Download Piper voice model
VOICE_ONNX="$PIPER_MODEL_DIR/$PIPER_VOICE.onnx"
VOICE_JSON="$PIPER_MODEL_DIR/$PIPER_VOICE.onnx.json"

if [ -f "$VOICE_ONNX" ] && [ -f "$VOICE_JSON" ]; then
    echo "✅ Piper voice model already downloaded"
else
    echo "Downloading Piper voice: $PIPER_VOICE..."
    
    PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
    
    wget -O "$VOICE_ONNX" "$PIPER_BASE/en_US-lessac-medium.onnx"
    wget -O "$VOICE_JSON" "$PIPER_BASE/en_US-lessac-medium.onnx.json"
    
    echo "✅ Piper voice downloaded"
fi

# ==========================================
# 5. SETUP KOKORO TTS (Realistic Voice)
# ==========================================
echo ""
echo "=========================================="
echo "  5. Setting up Kokoro TTS (Realistic Voice)"
echo "=========================================="

KOKORO_MODEL_DIR="$MODELS_DIR/kokoro"
KOKORO_MODEL="$KOKORO_MODEL_DIR/kokoro-v1.0.onnx"
KOKORO_VOICES="$KOKORO_MODEL_DIR/voices-v1.0.bin"

if [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]; then
    echo "✅ Kokoro TTS model already downloaded"
else
    echo "Downloading Kokoro TTS model (~300MB)..."
    
    KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    
    wget -O "$KOKORO_MODEL" "$KOKORO_BASE/kokoro-v1.0.onnx"
    wget -O "$KOKORO_VOICES" "$KOKORO_BASE/voices-v1.0.bin"
    
    echo "✅ Kokoro TTS downloaded"
fi

echo ""
echo "Kokoro voices available (see: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md):"
echo "  Female (A-grade): af_heart, af_bella"
echo "  Female (good):    af_nicole, af_sarah, af_sky"
echo "  Male (good):      am_michael, am_fenrir, am_puck"

# ==========================================
# 6. CREATE START SCRIPT
# ==========================================
echo ""
echo "=========================================="
echo "  6. Creating llama.cpp server script"
echo "=========================================="

cat > "$SCRIPT_DIR/run-llama-server.sh" << 'EOF'
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
EOF

chmod +x "$SCRIPT_DIR/run-llama-server.sh"
echo "✅ Created run-llama-server.sh"

# ==========================================
# SUMMARY
# ==========================================
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Models directory: $MODELS_DIR"
echo ""
echo "VRAM Usage Estimate:"
echo "  - Qwen2.5-7B Q4_K_M: ~4.5GB"
echo "  - faster-whisper small: ~1GB"
echo "  - Piper/Kokoro TTS: CPU only (ONNX)"
echo "  - Total: ~5.5GB / 12GB"
echo ""
echo "Next steps:"
echo "  1. Start llama.cpp server:  ./run-llama-server.sh"
echo "  2. Update .env with local settings"
echo "  3. Run the Discord bot:     ./run-discord-bot.sh"
echo ""
echo "Environment variables to set in server/.env:"
echo "  USE_LOCAL_LLM=true"
echo "  USE_LOCAL_STT=true"
echo "  USE_LOCAL_TTS=true"
echo "  LOCAL_LLM_URL=http://localhost:8080/v1"
echo "  WHISPER_MODEL=small"
echo ""
echo "For Piper TTS (robotic but fast):"
echo "  USE_KOKORO_TTS=false"
echo "  PIPER_MODEL_PATH=$MODELS_DIR/piper/en_US-lessac-medium.onnx"
echo ""
echo "For Kokoro TTS (realistic voice - recommended):"
echo "  USE_KOKORO_TTS=true"
echo "  KOKORO_MODEL_PATH=$MODELS_DIR/kokoro/kokoro-v1.0.onnx"
echo "  KOKORO_VOICES_PATH=$MODELS_DIR/kokoro/voices-v1.0.bin"
echo "  KOKORO_VOICE=af_heart  # or af_bella, am_michael, etc."
