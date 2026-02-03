# Deploying Garvis

This guide walks you through deploying your own Garvis voice assistant using Docker.

## Prerequisites

1. **Docker** - [Install Docker](https://docs.docker.com/get-docker/)
2. **Discord Bot Token** - [Create a Discord Application](https://discord.com/developers/applications)
3. **OpenClaw** - [Self-host](https://github.com/moltbot/openclaw) or get access at [docs.molt.bot](https://docs.molt.bot)

## Quick Start (Cloud Mode)

Cloud mode uses Anthropic Claude, Deepgram, and ElevenLabs APIs. This is the fastest way to get started.

```bash
# Clone the repository
git clone https://github.com/your-repo/garvis.git
cd garvis

# Run the setup wizard
./setup.sh        # Linux/Mac
# or
.\setup.ps1       # Windows PowerShell

# Start Garvis
docker compose up -d

# View logs
docker compose logs -f
```

## Quick Start (Local Mode)

Local mode runs everything on your GPU. Requires an NVIDIA GPU with 8GB+ VRAM.

```bash
# Clone and setup
git clone https://github.com/your-repo/garvis.git
cd garvis

# Download AI models (~6GB)
./download-models.sh        # Linux/Mac
# or
.\download-models.ps1       # Windows

# Run setup wizard (select "local mode")
./setup.sh

# Start with local models
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

## Manual Configuration

If you prefer to configure manually instead of using the setup wizard:

### 1. Create your `.env` file

```bash
cp .env.docker.example .env
```

### 2. Fill in required values

```env
# Required
DISCORD_BOT_TOKEN=your_discord_bot_token

# OpenClaw (required for memory/proactive features)
OPENCLAW_GATEWAY_URL=http://host.docker.internal:18789
USE_OPENCLAW=true

# Cloud APIs (required for cloud mode)
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
```

### 3. Start Garvis

```bash
docker compose up -d
```

## Discord Bot Setup

### Creating the Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to "Bot" in the sidebar
4. Click "Reset Token" and copy the token to your `.env` file

### Required Intents

Enable these under Bot > Privileged Gateway Intents:
- Message Content Intent
- Server Members Intent  
- Presence Intent

### Inviting to Your Server

1. Go to OAuth2 > URL Generator
2. Select scopes: `bot`, `applications.commands`
3. Select permissions: `Connect`, `Speak`, `Use Voice Activity`
4. Copy the generated URL and open it to invite the bot

## OpenClaw Setup

Garvis uses OpenClaw for persistent memory and proactive features.

### Self-Hosting OpenClaw

```bash
# Install OpenClaw
pip install openclaw

# Start the gateway
openclaw gateway
```

### Configuring Garvis

```env
USE_OPENCLAW=true
OPENCLAW_GATEWAY_URL=http://host.docker.internal:18789  # Docker
# or
OPENCLAW_GATEWAY_URL=http://localhost:18789             # Local
```

### Setting Up Proactive Voice Scanning

Garvis can periodically check voice channels and decide to join:

```bash
# After Garvis is running, set up the cron job
./setup-openclaw-cron.sh 5m   # Scans every 5 minutes
```

## Commands

Once Garvis is in a voice channel:

| Command | Description |
|---------|-------------|
| `!join` | Join your voice channel |
| `!leave` | Leave the voice channel |
| `!listen` | Start listening (after !join) |
| `!mute @user` | Stop listening to a user |
| `!status` | Show current status |
| `!bargein on/off` | Toggle interruption |
| `!assistant on/off` | Toggle wake word mode |

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs garvis

# Common issues:
# - Missing API keys: check your .env file
# - Port conflict: change BOT_API_PORT in .env
# - Permission denied: run with sudo or add user to docker group
```

### Bot connects but doesn't respond

1. Check if OpenClaw is running and accessible
2. Verify your API keys are correct
3. Check the logs for errors: `docker compose logs -f`

### Audio issues

```bash
# Increase logging
DEEPGRAM_DEBUG=true   # Add to .env

# Restart
docker compose restart
```

### GPU not detected (local mode)

```bash
# Verify NVIDIA driver
nvidia-smi

# Install nvidia-container-toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.1-base-ubuntu22.04 nvidia-smi
```

## Updating

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d
```

## Resource Usage

### Cloud Mode
- RAM: ~512MB - 1GB
- CPU: Low (audio processing only)
- Network: Depends on usage

### Local Mode
- RAM: ~2-4GB
- VRAM: ~5.5GB (Qwen + Whisper)
- CPU: Moderate (TTS runs on CPU)
- Disk: ~6GB for models

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│  ┌─────────────┐                    ┌─────────────────┐ │
│  │   Garvis    │◄──── local mode ──►│  llama-server   │ │
│  │  (Discord   │                    │  (Qwen 7B LLM)  │ │
│  │   Bot)      │                    └─────────────────┘ │
│  └──────┬──────┘                                        │
│         │                                               │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │  Discord  │     │  OpenClaw │     │Cloud APIs │
    │    API    │     │  Gateway  │     │(Claude,   │
    │           │     │ (Memory)  │     │Deepgram,  │
    └───────────┘     └───────────┘     │ElevenLabs)│
                                        └───────────┘
```

## Environment Variables Reference

See [.env.docker.example](.env.docker.example) for all available options with descriptions.

Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Discord bot token | Required |
| `USE_OPENCLAW` | Enable OpenClaw integration | `true` |
| `USE_LOCAL_LLM` | Use local LLM instead of Claude | `false` |
| `USE_LOCAL_STT` | Use local Whisper instead of Deepgram | `false` |
| `USE_LOCAL_TTS` | Use local TTS instead of ElevenLabs | `false` |
| `ASSISTANT_MODE` | Require wake word ("Garvis") | `false` |
| `AUTO_JOIN_ENABLED` | Auto-join voice channels | `false` |
