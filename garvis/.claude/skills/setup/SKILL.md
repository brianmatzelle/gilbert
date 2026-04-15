---
name: setup
description: Set up and run the Garvis Discord voice assistant bot. Use when the user asks how to get started, set up, install, or run Garvis.
argument-hint: [cloud|local]
allowed-tools: Bash(uv *) Bash(python3 *) Bash(ffmpeg *) Read
---

# Garvis Setup Guide

Help the user get Garvis up and running. Follow these steps, checking each prerequisite and reporting status before proceeding.

## Prerequisites Check

Run these checks first and report results:

1. **Python 3.11-3.13** (NOT 3.14 — `requires-python = ">=3.11,<3.14"`)
   - Check: `python3.13 --version` or `python3.12 --version`
   - If only 3.14 is available: `uv python install 3.13`

2. **uv** (Python package manager)
   - Check: `uv --version`
   - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`

3. **FFmpeg** (audio encoding/decoding)
   - Check: `ffmpeg -version`
   - Install (Linux): `sudo apt install ffmpeg` or `brew install ffmpeg`

4. **CUDA** (optional, for GPU-accelerated VAD)
   - Check: `nvidia-smi` and `python -c "import torch; print(torch.cuda.is_available())"`

## Environment Setup

1. Navigate to server directory:
   ```
   cd garvis/server
   ```

2. Check for `.env` file:
   - If missing: `cp env.example .env`
   - Verify these **required** keys are set (not placeholder values):
     - `ANTHROPIC_API_KEY` — get from https://console.anthropic.com/
     - `DEEPGRAM_API_KEY` — get from https://console.deepgram.com/
     - `ELEVENLABS_API_KEY` — get from https://elevenlabs.io/
     - `DISCORD_BOT_TOKEN` — get from https://discord.com/developers/applications
       - Bot needs permissions: Connect, Speak, Use Voice Activity, Message Content Intent

3. Install dependencies:
   ```
   uv sync
   ```

4. Verify core imports:
   ```
   uv run python -c "import discord; import anthropic; import deepgram; print('OK')"
   ```

## Running — Cloud Mode (default)

Uses Anthropic Claude + Deepgram STT + ElevenLabs TTS. Requires API keys.

```bash
# From the garvis/ directory:
./run-discord-bot.sh

# Or from garvis/server/:
uv run python -m discord_bot.bot
```

## Running — Local Mode (if $ARGUMENTS contains "local")

Uses local models for offline/low-latency operation. Requires GPU (~6GB VRAM minimum).

### Step 1: Download local models (~15GB)
```bash
./scripts/setup-local-models.sh
```

### Step 2: Set local flags in `.env`
```
USE_LOCAL_LLM=true
USE_LOCAL_STT=true
USE_LOCAL_TTS=true
USE_KOKORO_TTS=true    # Recommended over Piper for quality
```

### Step 3: Start llama.cpp server (terminal 1)
```bash
./scripts/run-llama-server.sh
```

### Step 4: Start bot (terminal 2)
```bash
./scripts/run-discord-bot-local.sh
```

## Discord Bot Setup (if user needs to create a bot)

1. Go to https://discord.com/developers/applications
2. Click "New Application", name it "Garvis"
3. Go to Bot tab, click "Reset Token", copy the token
4. Enable these Privileged Gateway Intents:
   - Message Content Intent
5. Go to OAuth2 > URL Generator:
   - Scopes: `bot`
   - Bot Permissions: Connect, Speak, Use Voice Activity, Send Messages
6. Copy the generated URL and open it to invite the bot to your server

## Troubleshooting

- **`ImportError: No module named 'audioop'`** — Python 3.13+ removed audioop; `audioop-lts` should be installed automatically via `uv sync`
- **Bot connects but no audio** — Check that FFmpeg is installed and the bot has Connect + Speak permissions in the Discord channel
- **`RuntimeError: PyNaCl not installed`** — Run `uv sync` again, it installs `pynacl` via `py-cord[voice]`
- **High latency** — Switch to `claude-3-5-haiku-20241022` model and `eleven_flash_v2_5` TTS in `.env`
- **CUDA not detected** — Install PyTorch with CUDA: `uv pip install torch --index-url https://download.pytorch.org/whl/cu121`
