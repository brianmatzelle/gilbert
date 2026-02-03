# Garvis Voice Assistant

<div align="center">

**An AI voice assistant for Discord voice channels**

Built with [Deepgram](https://deepgram.com) • [Claude](https://anthropic.com) • [Eleven Labs](https://elevenlabs.io)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)

</div>

---

## Features

- **Real-time Voice Conversations** — Talk naturally with sub-second latency
- **Discord Integration** — Join voice channels and chat with friends
- **Natural Speech Synthesis** — Eleven Labs voices that sound human
- **Claude-powered Intelligence** — Anthropic's latest AI for thoughtful responses
- **Streaming Pipeline** — Audio streams in both directions for minimal delay
- **MCP Extensibility** — Add custom tools via FastMCP
- **Local Model Support** — Run STT, LLM, and TTS locally for zero-latency inference

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Discord Voice Pipeline                            │
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │
│  │  Discord    │───▶│  Audio Sink │───▶│   Deepgram STT          │  │
│  │  Voice      │    │  48kHz→16kHz │    │   (Speech-to-Text)      │  │
│  │  Channel    │    └─────────────┘    └───────────┬─────────────┘  │
│  │             │                                    │                │
│  │  ◀────────────────────────────────────────┐     ▼                │
│  │             │    ┌─────────────┐    ┌─────┴─────────────────┐   │
│  │  PCM Audio  │◀───│ ElevenLabs  │◀───│   Claude LLM          │   │
│  │  Playback   │    │    TTS      │    │   (Response)          │   │
│  └─────────────┘    └─────────────┘    └───────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Voice Pipeline Flow

1. **Capture** — Discord captures voice channel audio
2. **Resample** — Convert 48kHz stereo to 16kHz mono
3. **VAD** — Silero VAD detects speech boundaries locally
4. **Transcribe** — Deepgram Nova-2 provides real-time STT
5. **Think** — Claude generates streaming response
6. **Synthesize** — Eleven Labs converts text to speech
7. **Play** — Audio streams back to Discord voice channel

## Quick Start

### Docker (Recommended)

The fastest way to deploy Garvis. Requires only [Docker](https://docs.docker.com/get-docker/).

```bash
# Clone the repository
git clone https://github.com/yourusername/garvis.git
cd garvis

# Run the interactive setup wizard
./setup.sh        # Linux/Mac
.\setup.ps1       # Windows PowerShell

# Start Garvis
docker compose up -d

# View logs
docker compose logs -f
```

The setup wizard will guide you through:
- Entering your Discord bot token
- Choosing cloud mode (API keys) or local mode (GPU)
- Configuring OpenClaw for persistent memory

See [DEPLOY.md](DEPLOY.md) for the full deployment guide.

---

### Manual Installation (Development)

For development or customization, you can run without Docker.

#### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11-3.13 | 3.14 not yet supported |
| uv | latest | [Install here](https://github.com/astral-sh/uv) |

#### API Keys Required

- **[Anthropic](https://console.anthropic.com/)** — Claude API key
- **[Deepgram](https://console.deepgram.com/)** — Speech-to-text API key
- **[Eleven Labs](https://elevenlabs.io/)** — Text-to-speech API key
- **[Discord](https://discord.com/developers/applications)** — Bot token

#### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/garvis.git
cd garvis

# 2. Configure environment
cp server/env.example server/.env
# Edit server/.env and add your API keys

# 3. Install dependencies
cd server && uv sync
```

#### Running

```bash
# Linux/macOS
./run-discord-bot.sh

# Windows
run-discord-bot.bat

# Or directly
cd server && uv run python -m discord_bot.bot
```

## Discord Bot Setup

1. **Create a Discord Bot**:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to Bot tab and create a bot
   - Copy the bot token
   - Under OAuth2 > URL Generator:
     - Scopes: `bot`
     - Bot Permissions: `Connect`, `Speak`, `Use Voice Activity`, `Send Messages`
   - Use the generated URL to invite the bot to your server

2. **Configure Environment**:
   Add to your `server/.env`:
   ```env
   DISCORD_BOT_TOKEN=your_bot_token_here
   ```

### Commands

| Command | Description |
|---------|-------------|
| `!join` | Join your current voice channel |
| `!leave` | Leave the voice channel |
| `!listen @user` | Only respond to a specific user |
| `!listen all` | Respond to everyone in the channel |
| `!status` | Show current bot status |

## Configuration

### Environment Variables

Create `server/.env` with:

```env
# Required API Keys
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
DISCORD_BOT_TOKEN=...

# Optional: Voice customization
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb  # Default: George
ELEVENLABS_MODEL_ID=eleven_flash_v2_5      # Low latency model

# Optional: Claude model
CLAUDE_MODEL=claude-3-5-haiku-20241022     # Fast model for voice

# Optional: Local models (for offline/low-latency)
USE_LOCAL_LLM=false
USE_LOCAL_STT=false
USE_LOCAL_TTS=false
```

### Available Eleven Labs Voices

| Voice | ID | Character |
|-------|-----|-----------|
| George | `JBFqnCBsd6RMkjVDRZzb` | Warm British male (default) |
| Rachel | `21m00Tcm4TlvDq8ikWAM` | Calm American female |
| Adam | `pNInz6obpgDQGcFmaJgB` | Deep American male |
| Bella | `EXAVITQu4vr4xnSDxMaL` | Young American female |

Find more at [Eleven Labs Voice Library](https://elevenlabs.io/voice-library)

### Customizing the Personality

Edit `server/config.py`:

```python
CLAUDE_SYSTEM_PROMPT = """You are Garvis, a helpful AI assistant in a Discord voice channel.
Keep responses concise since this is a voice conversation.
Be helpful, friendly, and efficient."""
```

## Project Structure

```
garvis/
├── README.md
├── run-discord-bot.sh       # Start the Discord bot
├── run-discord-bot.bat      # Windows version
│
└── server/                  # Python backend
    ├── main.py              # FastAPI + FastMCP entry point
    ├── config.py            # Configuration & environment
    ├── env.example          # Environment template
    ├── pyproject.toml       # Python dependencies
    │
    ├── api/
    │   └── health.py        # Health check endpoints
    │
    ├── discord_bot/         # Discord voice assistant
    │   ├── bot.py           # Discord bot + commands
    │   ├── audio_sink.py    # Capture voice channel audio
    │   └── voice_pipeline.py # Voice pipeline for Discord
    │
    ├── tools/
    │   └── mcp_tools.py     # MCP tool definitions
    │
    └── voice/
        ├── pipeline.py      # Voice pipeline orchestration
        ├── silero_vad.py    # Local voice activity detection
        ├── deepgram_stt.py  # Speech-to-text (cloud)
        ├── whisper_stt.py   # Speech-to-text (local)
        ├── claude_llm.py    # Claude LLM
        ├── local_llm.py     # Local LLM (llama.cpp)
        ├── elevenlabs_tts.py # Text-to-speech (cloud)
        └── piper_tts.py     # Text-to-speech (local)
```

## MCP Tools

Garvis exposes an MCP (Model Context Protocol) endpoint for extensibility. Add custom tools to let Claude interact with external systems.

### Adding a Custom Tool

```python
# In server/tools/mcp_tools.py

@mcp.tool()
async def get_weather(city: str) -> dict:
    """Get current weather for a city.
    
    Args:
        city: Name of the city to get weather for
        
    Returns:
        Weather information including temperature and conditions
    """
    # Your implementation here
    return {"city": city, "temp": 72, "conditions": "sunny"}
```

### Example Tool Ideas

- **Smart Home** — Control lights, thermostat, devices
- **Calendar** — Check and create events
- **Search** — Query databases or search engines
- **Email** — Read and compose messages
- **Media** — Control music playback
- **Analytics** — Query business metrics

## Local Models

For lower latency or offline use, Garvis supports local AI models:

### Setup Local Models

```bash
./setup-local-models.sh  # Linux/macOS
./setup-local-models.ps1 # Windows
```

### Enable Local Mode

In `server/.env`:

```env
USE_LOCAL_LLM=true   # Use llama.cpp + Qwen2.5
USE_LOCAL_STT=true   # Use faster-whisper
USE_LOCAL_TTS=true   # Use Piper TTS
```

### Local Model Stack

| Component | Model | Notes |
|-----------|-------|-------|
| LLM | Qwen2.5-7B-Instruct | Via llama.cpp server |
| STT | Whisper small | GPU accelerated |
| TTS | Piper (Lessac) | Fast neural TTS |

## Performance

### Latency Targets

| Stage | Target | Notes |
|-------|--------|-------|
| STT | <400ms | First transcript |
| LLM | <600ms | First token |
| TTS | <400ms | First audio chunk |
| Total | <1.5s | Speech → Response |

### Optimization Tips

1. **Use fast models** — `claude-3-5-haiku-20241022` and `eleven_flash_v2_5`
2. **Shorter responses** — Tune system prompt for concise replies
3. **Stable network** — Low latency helps STT and TTS
4. **Local models** — Eliminate network latency entirely

## Troubleshooting

### Common Issues

**Bot can't connect to Discord:**
- Verify your bot token is correct
- Check that the bot has been invited with voice permissions
- Ensure the bot has permission to connect to the target channel

**No audio from Garvis:**
- Check server logs for TTS errors
- Verify Eleven Labs API key is valid
- Ensure bot has Speak permission in the channel

**Transcription not working:**
- Verify Deepgram API key is set
- Check server logs for STT connection errors
- VAD may need audio above threshold to trigger

**Bot not responding:**
- Check that you're in a voice channel when using `!join`
- Verify the bot can hear you (`!listen all` to respond to everyone)
- Check server logs for LLM errors

### Debug Mode

```bash
# Enable verbose logging
cd server && uv run python -m discord_bot.bot --debug
```

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with 💜 for voice-first AI experiences**

</div>
