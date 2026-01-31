# Garvis Server

FastAPI + FastMCP server providing real-time voice assistant capabilities for XR applications.

## 🏗️ Architecture

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

## 🚀 Quick Start

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

## 📡 API Reference

### REST Endpoints

| Endpoint | Method | Description | Response |
|----------|--------|-------------|----------|
| `/health` | GET | Full health check | `{"status": "healthy", ...}` |
| `/ping` | GET | Simple ping | `{"status": "pong"}` |
| `/mcp/*` | * | FastMCP tools endpoint | MCP protocol |
| `/mcp/proxy/playlist.m3u8` | GET | HLS playlist proxy | M3U8 playlist |
| `/mcp/proxy/chunk` | GET | HLS chunk proxy | Video segment |

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

// Update configuration (reserved)
{"type": "config", "voice_id": "...", "model": "..."}
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

// Stream URL (video player)
{
  "type": "stream_url",
  "url": "/mcp/proxy/playlist.m3u8?channel=926&cdn=0"
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Claude API key |
| `DEEPGRAM_API_KEY` | ✅ | — | Deepgram API key |
| `ELEVENLABS_API_KEY` | ✅ | — | Eleven Labs API key |
| `ELEVENLABS_VOICE_ID` | ❌ | `JBFqnCBsd6RMkjVDRZzb` | Voice ID (George) |
| `ELEVENLABS_MODEL_ID` | ❌ | `eleven_flash_v2_5` | TTS model (flash is faster) |
| `ELEVENLABS_OUTPUT_FORMAT` | ❌ | `mp3_44100_128` | Audio format (WebSocket only supports MP3) |
| `CLAUDE_MODEL` | ❌ | `claude-sonnet-4-20250514` | Claude model |
| `DISCORD_BOT_TOKEN` | ❌ | — | Discord bot token (for voice bot) |
| `DISCORD_SEND_TEXT_MESSAGES` | ❌ | `true` | Send responses to text chat |

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

## 🔌 MCP Tools

The server exposes MCP tools via FastMCP at `/mcp`. Tools are available for Claude to call during conversations.

### Built-in Tools

| Tool | Description |
|------|-------------|
| `ping` | Health check tool |
| `SEARCH_CONTENT` | Search for live sports streams by query |
| `SHOW_CONTENT` | Display a video stream in the XR client |

### Adding Custom Tools

```python
# In main.py

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

@mcp.tool()
async def control_lights(room: str, brightness: int) -> dict:
    """Control smart home lights.
    
    Args:
        room: Room name (living_room, bedroom, etc.)
        brightness: Brightness level 0-100
        
    Returns:
        Confirmation of light state
    """
    # Your implementation
    return {"room": room, "brightness": brightness, "status": "set"}
```

### Tool Best Practices

1. **Clear docstrings** — Claude uses these to understand tool purpose
2. **Type hints** — Required for proper MCP schema generation
3. **Error handling** — Return error info rather than raising exceptions
4. **Async** — Use `async def` for I/O-bound operations

## 🎙️ Discord Bot

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
│   Deepgram STT    │ ── Real-time transcription
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   Claude LLM      │ ── Generate response
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  ElevenLabs TTS   │ ── WebSocket streaming (MP3)
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Voice Pipeline   │ ── Convert MP3 → PCM (48kHz stereo)
└─────────┬─────────┘
          │
          ▼
Discord Voice Channel (playback)
```

## 📁 File Structure

```
server/
├── main.py              # FastAPI app + MCP tools
├── config.py            # Environment configuration
├── env.example          # Environment template
├── pyproject.toml       # Python dependencies
│
├── api/
│   ├── __init__.py      # Router exports
│   ├── health.py        # Health check endpoints
│   └── proxy.py         # HLS video proxy
│
├── discord_bot/         # Discord voice assistant
│   ├── __init__.py      # Module exports
│   ├── bot.py           # Discord bot + commands
│   ├── audio_sink.py    # Capture voice channel audio
│   └── voice_pipeline.py # Discord-adapted pipeline (MP3→PCM)
│
├── providers/           # Content provider system
│   ├── __init__.py      # Provider exports
│   ├── base.py          # Abstract ContentProvider
│   ├── crackstreams.py  # CrackStreams implementation
│   └── registry.py      # Provider registry
│
├── streaming/
│   ├── __init__.py      # Streaming exports
│   └── helpers.py       # Stream URL helpers
│
├── tools/
│   ├── __init__.py      # Tool exports
│   └── mcp_tools.py     # SEARCH_CONTENT, SHOW_CONTENT
│
└── voice/
    ├── __init__.py      # Module exports
    ├── websocket.py     # WebSocket handler (XR client)
    ├── pipeline.py      # Voice pipeline + stream_url handling
    ├── deepgram_stt.py  # Speech-to-text
    ├── claude_llm.py    # Claude LLM with tool calling
    └── elevenlabs_tts.py # Text-to-speech (WebSocket API)
```

## 📺 Video Streaming Components

### Content Providers

The provider system allows searching and streaming from multiple content sources.

**Base Interface (`providers/base.py`):**
```python
class ContentProvider(ABC):
    @abstractmethod
    async def search(self, query: str) -> list[dict]:
        """Search for content matching query."""
        pass
    
    @abstractmethod
    async def get_stream_info(self, url: str) -> dict | None:
        """Extract stream info from a content URL."""
        pass
```

**Available Providers:**

| Provider | Source | Content Type |
|----------|--------|--------------|
| `CrackStreamsProvider` | crackstreams.ms | Live sports |

### Adding a New Provider

```python
# providers/my_provider.py
from .base import ContentProvider

class MyProvider(ContentProvider):
    name = "my_source"
    base_url = "https://example.com"
    
    async def search(self, query: str) -> list[dict]:
        # Scrape/API search implementation
        return [{"title": "...", "url": "...", "time": "..."}]
    
    async def get_stream_info(self, url: str) -> dict | None:
        # Extract HLS/embed URL
        return {"source": "sharkstreams", "channel": 123}

# Register in providers/registry.py
PROVIDERS = [MyProvider()]
```

### HLS Proxy

The `/mcp/proxy/*` endpoints handle CORS and rewrite HLS playlists:

- **`/mcp/proxy/playlist.m3u8`** — Fetches and rewrites M3U8 playlists
- **`/mcp/proxy/chunk`** — Proxies video segments (.ts files)

This allows the XR client (HTTPS) to stream from HTTP sources without mixed-content errors.

### MCP Tools for Video

**SEARCH_CONTENT:**
```python
# Searches all registered providers
await SEARCH_CONTENT(query="Lakers game")
# Returns: [{"title": "Lakers vs...", "url": "...", "time": "..."}]
```

**SHOW_CONTENT:**
```python
# Triggers video display in XR client
await SHOW_CONTENT(content_url="https://crackstreams.ms/...")
# Returns: "[DISPLAY_STREAM:/mcp/proxy/playlist.m3u8?channel=926&cdn=0]"
```

The `[DISPLAY_STREAM:url]` marker is parsed by `pipeline.py` and sent as a `stream_url` WebSocket message.

---

## 🔧 Voice Pipeline Components

### DeepgramSTT

Real-time speech-to-text using Deepgram's streaming API.

**Features:**
- Nova-2 model for accuracy
- Voice Activity Detection (VAD)
- Utterance end detection
- Interim results for real-time feedback

**Configuration:**
```python
# In deepgram_stt.py
params = {
    "model": "nova-2",
    "language": "en-US",
    "smart_format": "true",
    "vad_events": "true",
    "interim_results": "true",
    "utterance_end_ms": "1000",
    "endpointing": "300",
}
```

### ClaudeLLM

Claude integration for conversational responses.

**Features:**
- Streaming responses for low latency
- Conversation history management
- Configurable system prompt

### ElevenLabsTTS

Real-time text-to-speech using ElevenLabs WebSocket API for lowest latency.

**Features:**
- WebSocket streaming for bidirectional communication
- Text buffering to meet ElevenLabs' minimum chunk requirements (50+ chars)
- Audio buffering for smooth playback (prebuffers ~8KB before starting)
- Flash model (`eleven_flash_v2_5`) for ~75ms inference time

**Architecture:**
```
Claude text chunks → Buffer 50+ chars → ElevenLabs WebSocket → MP3 chunks → Buffer 8KB → Convert to PCM → Discord/Client
```

**Why WebSocket over HTTP?**
- Lower time-to-first-byte for streaming text input
- Better handling of partial text from LLM streaming
- Automatic chunk scheduling with `generation_config`

**Configuration:**
```python
# Voice settings (in handshake message)
{
    "stability": 0.5,
    "similarity_boost": 0.75,
    "speed": 1.0
}

# Generation config for faster first audio
{
    "chunk_length_schedule": [50, 120, 200, 260]
}
```

**Note:** WebSocket API only supports MP3 output format. PCM conversion is handled by the voice pipeline.

## 🐛 Debugging

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
- Consider using a smaller model
- Tune system prompt for shorter responses
- Check Anthropic API status

**TTS audio stuttering or choppy:**
- Use `eleven_flash_v2_5` for lowest latency (~75ms vs ~150ms for turbo)
- The WebSocket TTS buffers text (50+ chars) and audio (8KB) before sending
- Check network bandwidth and stability
- MP3 conversion to PCM happens in 16KB chunks to avoid partial frame issues

**No audio from ElevenLabs:**
- WebSocket API only supports MP3 format (not PCM)
- Check for `output_format_not_allowed` error in logs
- Ensure `ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128`

## 📊 Performance

### Latency Targets

| Stage | Target | Notes |
|-------|--------|-------|
| STT | <400ms | First transcript |
| LLM | <600ms | First token |
| TTS | <400ms | First audio chunk |
| Total | <1.5s | Speech → Response |

### Optimization Tips

1. **Keep conversations short** — Fewer messages = faster processing
2. **Tune VAD** — Adjust `utterance_end_ms` for your use case
3. **Use Turbo TTS** — Fastest Eleven Labs model
4. **Concise prompts** — System prompt affects response length

## 📜 License

MIT
