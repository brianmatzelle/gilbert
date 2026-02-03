#!/bin/bash
#
# Garvis Setup Wizard
# Interactive setup script for Docker deployment
#
# Usage: ./setup.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Header
clear
echo -e "${CYAN}"
echo "  ▄████  ▄▄▄       ██▀███   ██▒   █▓ ██▓  ██████ "
echo " ██▒ ▀█▒▒████▄    ▓██ ▒ ██▒▓██░   █▒▓██▒▒██    ▒ "
echo "▒██░▄▄▄░▒██  ▀█▄  ▓██ ░▄█ ▒ ▓██  █▒░▒██▒░ ▓██▄   "
echo "░▓█  ██▓░██▄▄▄▄██ ▒██▀▀█▄    ▒██ █░░░██░  ▒   ██▒"
echo "░▒▓███▀▒ ▓█   ▓██▒░██▓ ▒██▒   ▒▀█░  ░██░▒██████▒▒"
echo " ░▒   ▒  ▒▒   ▓▒█░░ ▒▓ ░▒▓░   ░ ▐░  ░▓  ▒ ▒▓▒ ▒ ░"
echo "  ░   ░   ▒   ▒▒ ░  ░▒ ░ ▒░   ░ ░░   ▒ ░░ ░▒  ░ ░"
echo "                Discord Voice Assistant"
echo -e "${NC}"
echo ""

# Functions
prompt() {
    local var_name=$1
    local prompt_text=$2
    local default_value=$3
    local is_secret=${4:-false}
    
    if [ "$is_secret" = true ]; then
        echo -ne "${BLUE}$prompt_text${NC}"
        if [ -n "$default_value" ]; then
            echo -ne " ${YELLOW}[hidden]${NC}"
        fi
        echo -ne ": "
        read -s value
        echo ""
    else
        echo -ne "${BLUE}$prompt_text${NC}"
        if [ -n "$default_value" ]; then
            echo -ne " ${YELLOW}[$default_value]${NC}"
        fi
        echo -ne ": "
        read value
    fi
    
    if [ -z "$value" ]; then
        value="$default_value"
    fi
    
    eval "$var_name='$value'"
}

confirm() {
    local prompt_text=$1
    local default=${2:-n}
    
    if [ "$default" = "y" ]; then
        echo -ne "${BLUE}$prompt_text${NC} ${YELLOW}[Y/n]${NC}: "
    else
        echo -ne "${BLUE}$prompt_text${NC} ${YELLOW}[y/N]${NC}: "
    fi
    
    read -n1 response
    echo ""
    
    case "$response" in
        [yY]) return 0 ;;
        [nN]) return 1 ;;
        "") 
            if [ "$default" = "y" ]; then
                return 0
            else
                return 1
            fi
            ;;
        *) return 1 ;;
    esac
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is not installed.${NC}"
        echo "Please install Docker first: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo -e "${RED}Error: Docker daemon is not running.${NC}"
        echo "Please start Docker and try again."
        exit 1
    fi
    
    echo -e "${GREEN}✓ Docker is installed and running${NC}"
}

check_gpu() {
    if command -v nvidia-smi &> /dev/null; then
        if nvidia-smi &> /dev/null; then
            echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
            return 0
        fi
    fi
    return 1
}

# =============================================================================
# Main Setup Flow
# =============================================================================

echo -e "${BOLD}Welcome to Garvis Setup!${NC}"
echo "This wizard will help you configure Garvis for Docker deployment."
echo ""

# Check prerequisites
echo -e "${BOLD}Checking prerequisites...${NC}"
check_docker

HAS_GPU=false
if check_gpu; then
    HAS_GPU=true
fi
echo ""

# =============================================================================
# Discord Bot Token
# =============================================================================
echo -e "${BOLD}Step 1: Discord Bot Token${NC}"
echo "Create a Discord bot at: https://discord.com/developers/applications"
echo "Required intents: Message Content, Server Members, Presence"
echo "Bot permissions: Connect, Speak, Use Voice Activity"
echo ""

prompt DISCORD_BOT_TOKEN "Enter your Discord bot token" "" true

if [ -z "$DISCORD_BOT_TOKEN" ]; then
    echo -e "${RED}Error: Discord bot token is required.${NC}"
    exit 1
fi

echo ""

# =============================================================================
# Mode Selection
# =============================================================================
echo -e "${BOLD}Step 2: Choose Your Mode${NC}"
echo ""
echo -e "${CYAN}Cloud Mode (Recommended)${NC}"
echo "  - Uses cloud APIs: Claude, Deepgram, ElevenLabs"
echo "  - Fast setup, works immediately"
echo "  - Requires API keys (free tiers available)"
echo ""

if [ "$HAS_GPU" = true ]; then
    echo -e "${CYAN}Local Mode${NC}"
    echo "  - Runs all AI locally on your GPU"
    echo "  - No API costs, fully offline"
    echo "  - Downloads ~6GB of models"
    echo "  - Requires NVIDIA GPU with 8GB+ VRAM"
    echo ""
fi

USE_LOCAL=false
if [ "$HAS_GPU" = true ]; then
    if confirm "Use local models instead of cloud APIs?" "n"; then
        USE_LOCAL=true
    fi
else
    echo -e "${YELLOW}No NVIDIA GPU detected. Using cloud mode.${NC}"
fi
echo ""

# =============================================================================
# Cloud API Keys (if cloud mode)
# =============================================================================
if [ "$USE_LOCAL" = false ]; then
    echo -e "${BOLD}Step 3: Cloud API Keys${NC}"
    echo ""
    
    echo "Anthropic Claude (LLM): https://console.anthropic.com/"
    prompt ANTHROPIC_API_KEY "Enter your Anthropic API key" "" true
    echo ""
    
    echo "Deepgram (Speech-to-Text): https://console.deepgram.com/"
    prompt DEEPGRAM_API_KEY "Enter your Deepgram API key" "" true
    echo ""
    
    echo "ElevenLabs (Text-to-Speech): https://elevenlabs.io/"
    prompt ELEVENLABS_API_KEY "Enter your ElevenLabs API key" "" true
    echo ""
fi

# =============================================================================
# OpenClaw Configuration
# =============================================================================
echo -e "${BOLD}Step 4: OpenClaw Configuration${NC}"
echo "OpenClaw provides persistent memory and proactive features."
echo "Self-host or get access at: https://docs.molt.bot/"
echo ""

prompt OPENCLAW_GATEWAY_URL "OpenClaw gateway URL" "http://host.docker.internal:18789"
prompt OPENCLAW_GATEWAY_TOKEN "OpenClaw gateway token (leave empty if none)" ""
prompt OPENCLAW_AGENT_ID "OpenClaw agent ID" "main"
prompt OPENCLAW_SESSION_KEY "OpenClaw session key" "discord-voice-main"
echo ""

# =============================================================================
# Local Models Download (if local mode)
# =============================================================================
if [ "$USE_LOCAL" = true ]; then
    echo -e "${BOLD}Step 5: Download Local Models${NC}"
    echo "This will download approximately 6GB of AI models."
    echo ""
    
    if confirm "Download models now?" "y"; then
        echo ""
        ./download-models.sh
    else
        echo -e "${YELLOW}Skipping model download. Run ./download-models.sh later.${NC}"
    fi
    echo ""
fi

# =============================================================================
# Generate .env File
# =============================================================================
echo -e "${BOLD}Generating configuration...${NC}"

# Start with the template
cp .env.docker.example .env

# Update values using sed
sed -i "s|^DISCORD_BOT_TOKEN=.*|DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN|" .env

if [ "$USE_LOCAL" = false ]; then
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY|" .env
    sed -i "s|^DEEPGRAM_API_KEY=.*|DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY|" .env
    sed -i "s|^ELEVENLABS_API_KEY=.*|ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY|" .env
else
    sed -i "s|^USE_LOCAL_LLM=.*|USE_LOCAL_LLM=true|" .env
    sed -i "s|^USE_LOCAL_STT=.*|USE_LOCAL_STT=true|" .env
    sed -i "s|^USE_LOCAL_TTS=.*|USE_LOCAL_TTS=true|" .env
    sed -i "s|^USE_KOKORO_TTS=.*|USE_KOKORO_TTS=true|" .env
    sed -i "s|^USE_CUDA=.*|USE_CUDA=true|" .env
fi

sed -i "s|^OPENCLAW_GATEWAY_URL=.*|OPENCLAW_GATEWAY_URL=$OPENCLAW_GATEWAY_URL|" .env
sed -i "s|^OPENCLAW_GATEWAY_TOKEN=.*|OPENCLAW_GATEWAY_TOKEN=$OPENCLAW_GATEWAY_TOKEN|" .env
sed -i "s|^OPENCLAW_AGENT_ID=.*|OPENCLAW_AGENT_ID=$OPENCLAW_AGENT_ID|" .env
sed -i "s|^OPENCLAW_SESSION_KEY=.*|OPENCLAW_SESSION_KEY=$OPENCLAW_SESSION_KEY|" .env

echo -e "${GREEN}✓ Configuration saved to .env${NC}"
echo ""

# =============================================================================
# Build and Start
# =============================================================================
echo -e "${BOLD}Setup Complete!${NC}"
echo ""

if confirm "Build and start Garvis now?" "y"; then
    echo ""
    echo -e "${CYAN}Building Docker image...${NC}"
    
    if [ "$USE_LOCAL" = true ]; then
        docker compose -f docker-compose.yml -f docker-compose.local.yml build
        echo ""
        echo -e "${CYAN}Starting Garvis with local models...${NC}"
        docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
    else
        docker compose build
        echo ""
        echo -e "${CYAN}Starting Garvis...${NC}"
        docker compose up -d
    fi
    
    echo ""
    echo -e "${GREEN}✓ Garvis is starting!${NC}"
    echo ""
    echo "View logs:        docker compose logs -f"
    echo "Stop Garvis:      docker compose down"
    echo "Restart Garvis:   docker compose restart"
    echo ""
    
    if confirm "View startup logs now?" "y"; then
        echo ""
        docker compose logs -f
    fi
else
    echo ""
    echo -e "${YELLOW}To start Garvis later:${NC}"
    if [ "$USE_LOCAL" = true ]; then
        echo "  docker compose -f docker-compose.yml -f docker-compose.local.yml up -d"
    else
        echo "  docker compose up -d"
    fi
fi

echo ""
echo -e "${GREEN}Happy chatting! 🎙️${NC}"
