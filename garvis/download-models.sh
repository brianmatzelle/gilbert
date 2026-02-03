#!/bin/bash
#
# Garvis Model Download Script
# Downloads AI models for local inference (~6GB total)
#
# Usage: ./download-models.sh
#
# Models downloaded:
#   - Qwen2.5-7B-Instruct (Q4_K_M quantization) - ~4.5GB
#   - Piper TTS voice (en_US-lessac-medium) - ~100MB
#   - Kokoro TTS model + voices - ~300MB
#   - Whisper models are downloaded automatically by faster-whisper
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/models"

echo -e "${CYAN}"
echo "==========================================="
echo "  Garvis Local Model Download"
echo "==========================================="
echo -e "${NC}"

# Check disk space
REQUIRED_GB=8
AVAILABLE_KB=$(df "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
AVAILABLE_GB=$((AVAILABLE_KB / 1024 / 1024))

if [ "$AVAILABLE_GB" -lt "$REQUIRED_GB" ]; then
    echo -e "${RED}Error: Not enough disk space.${NC}"
    echo "Required: ${REQUIRED_GB}GB, Available: ${AVAILABLE_GB}GB"
    exit 1
fi

echo -e "${GREEN}✓ Disk space check passed (${AVAILABLE_GB}GB available)${NC}"
echo ""

# Create directories
mkdir -p "$MODELS_DIR/llm"
mkdir -p "$MODELS_DIR/piper"
mkdir -p "$MODELS_DIR/kokoro"
mkdir -p "$MODELS_DIR/whisper"

# =============================================================================
# 1. Download Qwen2.5-7B-Instruct (LLM)
# =============================================================================
echo -e "${CYAN}[1/3] Downloading Qwen2.5-7B-Instruct LLM (~4.5GB)...${NC}"

LLM_MODEL="$MODELS_DIR/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
LLM_URL="https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"

if [ -f "$LLM_MODEL" ]; then
    echo -e "${GREEN}✓ LLM model already downloaded${NC}"
else
    echo "Downloading from HuggingFace..."
    
    # Try huggingface-cli first, fall back to curl/wget
    if command -v huggingface-cli &> /dev/null; then
        huggingface-cli download bartowski/Qwen2.5-7B-Instruct-GGUF \
            Qwen2.5-7B-Instruct-Q4_K_M.gguf \
            --local-dir "$MODELS_DIR/llm" \
            --local-dir-use-symlinks False
    elif command -v curl &> /dev/null; then
        curl -L --progress-bar -o "$LLM_MODEL" "$LLM_URL"
    elif command -v wget &> /dev/null; then
        wget --show-progress -O "$LLM_MODEL" "$LLM_URL"
    else
        echo -e "${RED}Error: No download tool found (curl, wget, or huggingface-cli)${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ LLM model downloaded${NC}"
fi
echo ""

# =============================================================================
# 2. Download Piper TTS Voice
# =============================================================================
echo -e "${CYAN}[2/3] Downloading Piper TTS voice (~100MB)...${NC}"

PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
PIPER_ONNX="$MODELS_DIR/piper/en_US-lessac-medium.onnx"
PIPER_JSON="$MODELS_DIR/piper/en_US-lessac-medium.onnx.json"

if [ -f "$PIPER_ONNX" ] && [ -f "$PIPER_JSON" ]; then
    echo -e "${GREEN}✓ Piper voice already downloaded${NC}"
else
    if command -v curl &> /dev/null; then
        curl -L --progress-bar -o "$PIPER_ONNX" "$PIPER_BASE/en_US-lessac-medium.onnx"
        curl -L --progress-bar -o "$PIPER_JSON" "$PIPER_BASE/en_US-lessac-medium.onnx.json"
    else
        wget --show-progress -O "$PIPER_ONNX" "$PIPER_BASE/en_US-lessac-medium.onnx"
        wget --show-progress -O "$PIPER_JSON" "$PIPER_BASE/en_US-lessac-medium.onnx.json"
    fi
    echo -e "${GREEN}✓ Piper voice downloaded${NC}"
fi
echo ""

# =============================================================================
# 3. Download Kokoro TTS (Recommended)
# =============================================================================
echo -e "${CYAN}[3/3] Downloading Kokoro TTS model (~300MB)...${NC}"

KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_MODEL="$MODELS_DIR/kokoro/kokoro-v1.0.onnx"
KOKORO_VOICES="$MODELS_DIR/kokoro/voices-v1.0.bin"

if [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]; then
    echo -e "${GREEN}✓ Kokoro TTS already downloaded${NC}"
else
    if command -v curl &> /dev/null; then
        curl -L --progress-bar -o "$KOKORO_MODEL" "$KOKORO_BASE/kokoro-v1.0.onnx"
        curl -L --progress-bar -o "$KOKORO_VOICES" "$KOKORO_BASE/voices-v1.0.bin"
    else
        wget --show-progress -O "$KOKORO_MODEL" "$KOKORO_BASE/kokoro-v1.0.onnx"
        wget --show-progress -O "$KOKORO_VOICES" "$KOKORO_BASE/voices-v1.0.bin"
    fi
    echo -e "${GREEN}✓ Kokoro TTS downloaded${NC}"
fi
echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${CYAN}==========================================="
echo "  Download Complete!"
echo -e "===========================================${NC}"
echo ""
echo "Models directory: $MODELS_DIR"
echo ""
echo "Downloaded models:"
echo "  - LLM: Qwen2.5-7B-Instruct (Q4_K_M)"
echo "  - TTS: Piper en_US-lessac-medium"
echo "  - TTS: Kokoro v1.0 (recommended)"
echo ""
echo "Whisper STT model will be downloaded automatically on first use."
echo ""
echo -e "${YELLOW}VRAM Requirements:${NC}"
echo "  - Qwen2.5-7B Q4_K_M: ~4.5GB"
echo "  - Whisper small: ~1GB"
echo "  - Piper/Kokoro: CPU only"
echo "  - Total: ~5.5GB VRAM"
echo ""
echo -e "${GREEN}Kokoro TTS voices available:${NC}"
echo "  Female (best): af_heart, af_bella"
echo "  Male (good): am_michael, am_fenrir, am_puck"
echo ""
echo "To use local models, run:"
echo "  docker compose -f docker-compose.yml -f docker-compose.local.yml up -d"
