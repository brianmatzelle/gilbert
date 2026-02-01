# Garvis Server

FastAPI + FastMCP server providing real-time voice assistant capabilities, primarily for Discord voice channels.

## Architecture

```
                         ┌─────────────────────────────────┐
                         │        FastAPI Application       │
                         │                                  │
                         │  ┌───────────┐  ┌────────────┐  │
                         │  │  Health   │  │  FastMCP   │  │
     ─────HTTP/REST────▶ │  │   API     │  │   Tools    │  │
                         │  └───────────┘  └────────────┘  │
                         │                                  │
     ─────WebSocket────▶ │  ┌────────────────────────────┐ │
                         │  │      Voice Pipeline         │ │
                         │  │                             │ │
                         │  │  ┌─────────┐   ┌─────────┐  │ │
                         │  │  │Deepgram │──▶│ Claude  │  │ │
                         │  │  │  STT    │   │  LLM    │  │ │
                         │  │  └─────────┘   └────┬────┘  │ │
                         │  │                     │       │ │
                         │  │                     ▼       │ │
                         │  │              ┌───────────┐  │ │
                         │  │              │ElevenLabs │  │ │
                         │  │              │   TTS     │  │ │
                         │  │              └───────────┘  │ │
                         │  └────────────────────────────┘ │
                         └─────────────────────────────────┘
```

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp env.example .env
# Edit .env with your API keys

# Run server
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API Reference

### REST Endpoints

| Endpoint | Method | Description | Response |
|----------|--------|-------------|----------|
| `/health` | GET | Full health check | `{"status": "healthy", ...}` |
| `/ping` | GET | Simple ping | `{"status": "pong"}` |
| `/mcp/*` | * | FastMCP tools endpoint | MCP protocol |

### WebSocket Endpoint

**`/ws/voice`** — Real-time voice streaming

#### Connection Flow

```
Client                                  Server
  │                                       │
  │────────── WebSocket Connect ─────────▶│
  │                                       │
  │◀────────── {"type": "status"} ────────│ (ready)
  │                                       │
  │──────────── Audio PCM Data ──────────▶│
  │                                       │
  │◀───── {"type": "transcript"} ─────────│ (user speech)
  │                                       │
  │◀───── {"type": "transcript"} ─────────│ (assistant)
  │                                       │
  │◀─────────── TTS Audio ────────────────│
  │                                       │
```

#### Client → Server Messages

**Binary Audio Data**
- Format: 16-bit PCM
- Sample rate: 16kHz
- Channels: Mono

**JSON Control Messages**

```json
// Start listening
{"type": "start"}

// Stop listening
{"type": "stop"}

// Interrupt TTS playback
{"type": "interrupt"}
```

#### Server → Client Messages

**Binary Audio Data**
- Format: MP3
- Sample rate: 44.1kHz

**JSON Messages**

```json
// Transcript update
{
  "type": "transcript",
  "text": "Hello, how can I help?",
  "is_final": true,
  "role": "user" | "assistant"
}

// Status update
{
  "type": "status",
  "listening": true,
  "speaking": false
}

// Error
{
  "type": "error",
  "message": "Error description"
}
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `DEEPGRAM_API_KEY` | Yes | — | Deepgram API key |
| `ELEVENLABS_API_KEY` | Yes | — | Eleven Labs API key |
| `ELEVENLABS_VOICE_ID` | No | `JBFqnCBsd6RMkjVDRZzb` | Voice ID (George) |
| `ELEVENLABS_MODEL_ID` | No | `eleven_flash_v2_5` | TTS model (flash is faster) |
| `ELEVENLABS_OUTPUT_FORMAT` | No | `mp3_44100_128` | Audio format |
| `CLAUDE_MODEL` | No | `claude-3-5-haiku-20241022` | Claude model |
| `DISCORD_BOT_TOKEN` | No | — | Discord bot token (for voice bot) |
| `DISCORD_SEND_TEXT_MESSAGES` | No | `true` | Send responses to text chat |
| `USE_LOCAL_LLM` | No | `false` | Use local llama.cpp instead of Claude |
| `USE_LOCAL_STT` | No | `false` | Use local Whisper instead of Deepgram |
| `USE_LOCAL_TTS` | No | `false` | Use local Piper instead of ElevenLabs |
| `USE_OPENCLAW` | No | `false` | Use OpenClaw agent engine |
| `OPENCLAW_GATEWAY_URL` | No | `http://127.0.0.1:18789` | OpenClaw Gateway URL |
| `OPENCLAW_GATEWAY_TOKEN` | No | — | OpenClaw auth token |
| `OPENCLAW_AGENT_ID` | No | `main` | OpenClaw agent ID |
| `OPENCLAW_SESSION_KEY` | No | `discord-voice-main` | Session key for memory |

### Service Configuration

Edit `config.py` to customize:

```python
# System prompt (personality)
CLAUDE_SYSTEM_PROMPT = """You are Garvis..."""

# CORS origins
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://localhost:5173",
    # Add your domains
]
```

## MCP Tools

The server exposes MCP tools via FastMCP at `/mcp`. Tools are available for the LLM to call during conversations.

### Built-in Tools

| Tool | Description |
|------|-------------|
| `ping` | Health check tool |

### Adding Custom Tools

```python
# In tools/mcp_tools.py

@mcp.tool()
async def search_web(query: str) -> dict:
    """Search the web for information.
    
    Args:
        query: The search query
        
    Returns:
        Search results with titles and snippets
    """
    # Your implementation
    return {"results": [...]}
```

### Tool Best Practices

1. **Clear docstrings** — Claude uses these to understand tool purpose
2. **Type hints** — Required for proper MCP schema generation
3. **Error handling** — Return error info rather than raising exceptions
4. **Async** — Use `async def` for I/O-bound operations

## Discord Bot

The server includes a Discord voice bot that brings Garvis to Discord voice channels.

### Running the Discord Bot

```bash
# From the garvis directory
./run-discord-bot.sh

# Or directly
cd server && uv run python -m discord_bot.bot
```

### Commands

| Command | Description |
|---------|-------------|
| `!join` | Join your voice channel and start listening |
| `!leave` | Leave the voice channel |
| `!listen @user` | Only respond to a specific user |
| `!listen all` | Respond to everyone (default) |
| `!status` | Show current bot status |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | — | Bot token from Discord Developer Portal |
| `DISCORD_SEND_TEXT_MESSAGES` | `true` | Also send responses to text chat |

### Architecture

```
Discord Voice Channel
        │
        ▼ (48kHz stereo PCM)
┌───────────────────┐
│   Audio Sink      │ ── Resample to 16kHz mono
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   Silero VAD      │ ── Local voice activity detection
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   Deepgram STT    │ ── Real-time transcription
└─────────┬─────────┘    (or local Whisper)
          │
          ▼
┌───────────────────┐
│   LLM Provider    │ ── Generate response
│  ┌─────────────┐  │    Options:
│  │   Claude    │  │    - Claude (cloud)
│  │  OpenClaw   │  │    - OpenClaw (persistent memory)
│  │ Local LLM   │  │    - llama.cpp (local)
│  └─────────────┘  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  ElevenLabs TTS   │ ── WebSocket streaming (MP3)
└─────────┬─────────┘    (or local Piper)
          │
          ▼
┌───────────────────┐
│  Voice Pipeline   │ ── Convert MP3 → PCM (48kHz stereo)
└─────────┬─────────┘
          │
          ▼
Discord Voice Channel (playback)
```

## OpenClaw Integration

OpenClaw is an agent engine that provides persistent memory, tool calling, and session management. When enabled, it replaces direct Claude API calls with a more capable agent runtime.

### Benefits

| Feature | Without OpenClaw | With OpenClaw |
|---------|-----------------|---------------|
| Persistent Memory | None (session only) | JSONL storage, survives restarts |
| Tool Calling | Only with Anthropic API | Works across all providers |
| Session Management | Manual | Automatic with compaction |
| Multi-Agent | No | Yes (route to different agents) |
| Skills System | No | Yes (ClawHub, custom skills) |

### Setup

1. **Install OpenClaw Gateway**

```bash
# Requires Node.js >= 22
npm install -g openclaw@latest

# Run onboarding wizard
openclaw onboard
```

2. **Enable HTTP API**

Edit `~/.openclaw/openclaw.json`:

```json
{
  "gateway": {
    "http": {
      "endpoints": {
        "chatCompletions": { "enabled": true }
      }
    }
  },
  "providers": {
    "anthropic": { "apiKey": "sk-ant-..." }
  }
}
```

3. **Start OpenClaw Gateway**

```bash
openclaw gateway
```

4. **Enable in Garvis**

In your `.env` file:

```bash
USE_OPENCLAW=true
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=  # Optional, if you configured auth
OPENCLAW_AGENT_ID=main
OPENCLAW_SESSION_KEY=discord-voice-main
```

### Workspace Files

The `garvis/openclaw/` directory contains agent configuration:

- `AGENTS.md` — Agent role, constraints, and behavior
- `SOUL.md` — Character identity and personality

Copy these to your OpenClaw workspace (`~/.openclaw/`) to customize Garvis's personality.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_OPENCLAW` | `false` | Enable OpenClaw as LLM provider |
| `OPENCLAW_GATEWAY_URL` | `http://127.0.0.1:18789` | Gateway HTTP endpoint |
| `OPENCLAW_GATEWAY_TOKEN` | — | Bearer token (if configured) |
| `OPENCLAW_AGENT_ID` | `main` | Agent to route requests to |
| `OPENCLAW_SESSION_KEY` | `discord-voice-main` | Session key for memory |

## File Structure

```
server/
├── main.py              # FastAPI app + MCP tools
├── config.py            # Environment configuration
├── env.example          # Environment template
├── pyproject.toml       # Python dependencies
│
├── api/
│   ├── __init__.py      # Router exports
│   └── health.py        # Health check endpoints
│
├── discord_bot/         # Discord voice assistant
│   ├── __init__.py      # Module exports
│   ├── bot.py           # Discord bot + commands
│   ├── audio_sink.py    # Capture voice channel audio
│   └── voice_pipeline.py # Discord-adapted pipeline
│
├── tools/
│   ├── __init__.py      # Tool exports
│   └── mcp_tools.py     # MCP tool definitions
│
└── voice/
    ├── __init__.py       # Module exports
    ├── websocket.py      # WebSocket handler
    ├── pipeline.py       # Voice pipeline
    ├── silero_vad.py     # Local VAD for turn detection
    ├── deepgram_stt.py   # Speech-to-text (cloud)
    ├── whisper_stt.py    # Speech-to-text (local)
    ├── claude_llm.py     # Claude LLM with tool calling
    ├── local_llm.py      # Local LLM (llama.cpp)
    ├── openclaw_llm.py   # OpenClaw agent engine
    ├── elevenlabs_tts.py # Text-to-speech (cloud)
    └── piper_tts.py      # Text-to-speech (local)
```

## Voice Pipeline Components

### DeepgramSTT

Real-time speech-to-text using Deepgram's streaming API.

**Features:**
- Nova-2 model for accuracy
- Voice Activity Detection (VAD)
- Utterance end detection
- Interim results for real-time feedback

### ClaudeLLM

Claude integration for conversational responses.

**Features:**
- Streaming responses for low latency
- Conversation history management
- Tool calling support
- Configurable system prompt

### OpenClawLLM

OpenClaw agent engine integration for enhanced capabilities.

**Features:**
- Persistent memory across sessions
- Tool calling across all providers
- Automatic session management
- Multi-agent routing support
- SSE streaming for low latency

### ElevenLabsTTS

Real-time text-to-speech using ElevenLabs WebSocket API for lowest latency.

**Features:**
- WebSocket streaming for bidirectional communication
- Text buffering to meet minimum chunk requirements
- Audio buffering for smooth playback
- Flash model for ~75ms inference time

### Silero VAD

Local voice activity detection for accurate turn-taking.

**Features:**
- GPU-accelerated inference (CUDA)
- Configurable speech/silence thresholds
- Semantic turn detection (incomplete utterance handling)
- Barge-in support (interrupt bot mid-response)

## Debugging

### Enable Debug Logging

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --log-level debug
```

### Common Issues

**Deepgram connection fails:**
- Check API key is valid
- Ensure network allows WebSocket connections
- Verify API key has Nova-2 access

**Claude responses slow:**
- Use `claude-3-5-haiku-20241022` for faster responses
- Tune system prompt for shorter responses
- Check Anthropic API status

**TTS audio stuttering:**
- Use `eleven_flash_v2_5` for lowest latency
- Check network bandwidth and stability
- Audio is buffered before playback to smooth jitter

## Performance

### Latency Targets

| Stage | Target | Notes |
|-------|--------|-------|
| STT | <400ms | First transcript |
| LLM | <600ms | First token |
| TTS | <400ms | First audio chunk |
| Total | <1.5s | Speech → Response |

### Optimization Tips

1. **Keep conversations short** — Fewer messages = faster processing
2. **Tune VAD** — Adjust silence thresholds for your use case
3. **Use Flash TTS** — Fastest Eleven Labs model
4. **Concise prompts** — System prompt affects response length
5. **Local models** — Eliminate network latency with local STT/LLM/TTS

## License

MIT
