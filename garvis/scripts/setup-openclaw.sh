#!/bin/bash
#
# Setup OpenClaw for Garvis Discord Voice Assistant
#
# Configures the OpenClaw gateway with local vector memory search so Garvis
# can recall memories across sessions without needing any external API keys
# for embeddings.
#
# What this script does:
#   1. Verifies OpenClaw is installed and the gateway is running
#   2. Configures local embeddings (embeddinggemma-300M) for memory search
#   3. Enables hybrid search (vector + text) for best recall
#   4. Enables memory flush before compaction so facts survive session resets
#   5. Creates the workspace memory directory
#   6. Downloads the embedding model (~328MB) if not already cached
#   7. Restarts the gateway to apply changes
#
# Prerequisites:
#   - OpenClaw installed (pacman -S openclaw-git or yay -S openclaw-git)
#   - OpenClaw gateway running (openclaw gateway start)
#   - ANTHROPIC_API_KEY configured (openclaw auth login --provider anthropic)
#
# Usage:
#   ./setup-openclaw.sh
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "${CYAN}${BOLD}Garvis OpenClaw Setup${NC}"
echo "======================================"
echo ""

# ─── Step 1: Check OpenClaw is installed ─────────────────────────────────────

echo -e "${YELLOW}[1/7] Checking OpenClaw installation...${NC}"

if ! command -v openclaw &> /dev/null; then
    echo -e "${RED}  OpenClaw is not installed.${NC}"
    echo ""
    echo "  Install it with:"
    echo "    yay -S openclaw-git"
    echo ""
    echo "  Then run the setup wizard:"
    echo "    openclaw configure"
    exit 1
fi

VERSION=$(openclaw --version 2>/dev/null | head -1 || echo "unknown")
echo -e "${GREEN}  OpenClaw found: ${VERSION}${NC}"

# ─── Step 2: Check gateway is running ────────────────────────────────────────

echo -e "${YELLOW}[2/7] Checking gateway status...${NC}"

if ! openclaw gateway status &> /dev/null; then
    echo -e "${YELLOW}  Gateway is not running. Starting it...${NC}"
    openclaw gateway start 2>&1 | head -5
    sleep 3

    if ! openclaw gateway status &> /dev/null; then
        echo -e "${RED}  Failed to start gateway.${NC}"
        echo ""
        echo "  Try starting it manually:"
        echo "    openclaw gateway start"
        echo "    openclaw gateway logs"
        exit 1
    fi
fi

echo -e "${GREEN}  Gateway is running.${NC}"

# ─── Step 3: Configure local embeddings for memory search ────────────────────

echo -e "${YELLOW}[3/7] Configuring local embeddings for memory search...${NC}"

# Set provider to local so embeddings run on-device (no OpenAI key needed)
openclaw config set agents.defaults.memorySearch.provider local > /dev/null 2>&1

# Set explicit model path so auto-download works reliably
openclaw config set agents.defaults.memorySearch.local.modelPath \
    "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf" > /dev/null 2>&1

# Disable fallback to remote APIs — if local fails, we want a real error,
# not a confusing "quota exceeded" from an OpenAI key we don't have
openclaw config set agents.defaults.memorySearch.fallback none > /dev/null 2>&1

echo -e "${GREEN}  Provider: local (embeddinggemma-300M, ~328MB)${NC}"
echo -e "${GREEN}  Fallback: none (no silent OpenAI fallback)${NC}"

# ─── Step 4: Configure hybrid search ─────────────────────────────────────────

echo -e "${YELLOW}[4/7] Configuring hybrid search (vector + text)...${NC}"

# Hybrid search combines semantic vector similarity with keyword text matching
# for better recall on both exact terms and conceptual queries
openclaw config set agents.defaults.memorySearch.query.hybrid.enabled true > /dev/null 2>&1
openclaw config set agents.defaults.memorySearch.query.hybrid.vectorWeight 0.7 > /dev/null 2>&1
openclaw config set agents.defaults.memorySearch.query.hybrid.textWeight 0.3 > /dev/null 2>&1

echo -e "${GREEN}  Hybrid search: enabled (70% vector, 30% text)${NC}"

# ─── Step 5: Configure memory flush before compaction ─────────────────────────

echo -e "${YELLOW}[5/7] Configuring memory flush before compaction...${NC}"

# Before the context window compacts, run a silent turn that writes durable
# facts to memory/ files so they survive transcript rotation
openclaw config set agents.defaults.compaction.memoryFlush.enabled true > /dev/null 2>&1
openclaw config set agents.defaults.compaction.memoryFlush.softThresholdTokens 6000 > /dev/null 2>&1

echo -e "${GREEN}  Memory flush: enabled (threshold: 6000 tokens)${NC}"

# ─── Step 6: Create workspace memory directory ───────────────────────────────

echo -e "${YELLOW}[6/7] Setting up workspace memory directory...${NC}"

WORKSPACE=$(openclaw config get agents.defaults.workspace 2>/dev/null || echo "$HOME/.openclaw/workspace")
# Strip quotes if present
WORKSPACE="${WORKSPACE%\"}"
WORKSPACE="${WORKSPACE#\"}"

MEMORY_DIR="${WORKSPACE}/memory"

if [ ! -d "$MEMORY_DIR" ]; then
    mkdir -p "$MEMORY_DIR"
    echo -e "${GREEN}  Created: ${MEMORY_DIR}${NC}"
else
    echo -e "${GREEN}  Already exists: ${MEMORY_DIR}${NC}"
fi

# Count existing memory files
FILE_COUNT=$(find "$MEMORY_DIR" -name "*.md" 2>/dev/null | wc -l)
echo -e "  Memory files found: ${FILE_COUNT}"

# ─── Step 7: Restart gateway and verify ──────────────────────────────────────

echo -e "${YELLOW}[7/7] Restarting gateway and verifying...${NC}"

openclaw gateway restart > /dev/null 2>&1
sleep 3

# Run memory status to trigger model download if needed and verify config
echo ""
STATUS_OUTPUT=$(openclaw memory status --deep 2>&1)

# Check provider
if echo "$STATUS_OUTPUT" | grep -q "Provider: local"; then
    echo -e "${GREEN}  Provider: local${NC}"
else
    PROVIDER=$(echo "$STATUS_OUTPUT" | grep "^Provider:" | head -1)
    echo -e "${RED}  Unexpected provider: ${PROVIDER}${NC}"
    echo "  Run 'openclaw memory status --deep' to debug."
fi

# Check embeddings
if echo "$STATUS_OUTPUT" | grep -q "Embeddings: ready"; then
    echo -e "${GREEN}  Embeddings: ready${NC}"
elif echo "$STATUS_OUTPUT" | grep -q "Downloading"; then
    echo -e "${YELLOW}  Embedding model is downloading (~328MB)...${NC}"
    echo "  This is a one-time download. Run 'openclaw memory status --deep'"
    echo "  after it finishes to verify."
else
    EMBED_ERR=$(echo "$STATUS_OUTPUT" | grep -A2 "Embeddings:" | head -3)
    echo -e "${RED}  Embeddings issue: ${EMBED_ERR}${NC}"
    echo "  Run 'openclaw memory status --deep --verbose' to debug."
fi

# Check vector store
if echo "$STATUS_OUTPUT" | grep -q "Vector: ready"; then
    echo -e "${GREEN}  Vector store: ready (sqlite-vec)${NC}"
fi

# Check FTS
if echo "$STATUS_OUTPUT" | grep -q "FTS: ready"; then
    echo -e "${GREEN}  Full-text search: ready${NC}"
fi

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}${BOLD}Setup complete.${NC}"
echo ""
echo "Garvis can now use local vector memory search with no external API"
echo "keys for embeddings. All computation runs on-device."
echo ""
echo -e "${BOLD}Useful commands:${NC}"
echo "  openclaw memory status --deep   # Check memory search health"
echo "  openclaw memory index --force   # Reindex all memory files"
echo "  openclaw memory search \"query\"  # Test a memory search"
echo "  openclaw gateway logs           # View gateway logs"
echo ""
echo -e "${BOLD}Project config reference:${NC}"
echo "  ${PROJECT_DIR}/openclaw/openclaw.json"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo "  1. Start Garvis:  ./run-discord-bot.sh"
echo "  2. Setup cron:    ./scripts/setup-openclaw-cron.sh"
echo ""
