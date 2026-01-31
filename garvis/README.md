# 🥽 Garvis XR Voice Assistant

<div align="center">

**An immersive AI voice assistant for Meta Quest 3 and WebXR devices**

Built with [Deepgram](https://deepgram.com) • [Claude](https://anthropic.com) • [Eleven Labs](https://elevenlabs.io)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org/)

</div>

---

## ✨ Features

- **🎤 Real-time Voice Conversations** — Talk naturally with sub-second latency
- **🥽 Quest 3 Native Support** — Immersive AR/VR voice assistant experience
- **🔊 Natural Speech Synthesis** — Eleven Labs voices that sound human
- **🧠 Claude-powered Intelligence** — Anthropic's latest AI for thoughtful responses
- **⚡ Streaming Pipeline** — Audio streams in both directions for minimal delay
- **🔌 MCP Extensibility** — Add custom tools via FastMCP
- **📺 Live Video Streaming** — Watch sports and live content in XR with voice commands
- **👁️ Face Detection AR Overlay** — Real-time face detection with bounding boxes overlaid on passthrough

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Quest 3 / Browser                           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    XR Client (WebXR)                         │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │   │
│  │  │  Mic Input  │───▶│  WebSocket  │◀───│  Audio Playback │  │   │
│  │  │  (16kHz)    │    │   Client    │    │  (MP3 @ 44.1k)  │  │   │
│  │  └─────────────┘    └──────┬──────┘    └─────────────────┘  │   │
│  └────────────────────────────┼────────────────────────────────┘   │
└───────────────────────────────┼─────────────────────────────────────┘
                                │ WSS (Binary + JSON)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Garvis Server (FastAPI)                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Voice Pipeline                           │   │
│  │                                                              │   │
│  │   ┌─────────────┐    ┌─────────────┐    ┌───────────────┐   │   │
│  │   │  Deepgram   │───▶│   Claude    │───▶│  Eleven Labs  │   │   │
│  │   │    STT      │    │    LLM      │    │     TTS       │   │   │
│  │   │  (Nova-2)   │    │ (Sonnet 4)  │    │  (Turbo v2.5) │   │   │
│  │   └─────────────┘    └─────────────┘    └───────────────┘   │   │
│  │                                                              │   │
│  │   Audio ──▶ Text ──▶ Response ──▶ Speech                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  FastMCP Tools (/mcp)  │  Health API  │  WebSocket Handler  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Voice Pipeline Flow

1. **🎙️ Capture** — Browser captures microphone audio via WebAudio API
2. **📡 Stream** — 16-bit PCM @ 16kHz sent to server via WebSocket
3. **📝 Transcribe** — Deepgram Nova-2 provides real-time STT with VAD
4. **🤖 Think** — Claude generates streaming response
5. **🔊 Synthesize** — Eleven Labs converts text to speech in real-time
6. **🎧 Play** — MP3 audio streams back to client for playback

## 🚀 Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Node.js | 18+ | For XR client |
| Python | 3.11-3.13 | TensorFlow (for face detection) doesn't support 3.14 yet |
| uv | latest | [Install here](https://github.com/astral-sh/uv) |
| Quest 3 | — | Or any WebXR-compatible device |

### API Keys Required

- **[Anthropic](https://console.anthropic.com/)** — Claude API key
- **[Deepgram](https://console.deepgram.com/)** — Speech-to-text API key
- **[Eleven Labs](https://elevenlabs.io/)** — Text-to-speech API key

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/garvis.git
cd garvis

# 2. Configure environment
cp server/env.example server/.env
# Edit server/.env and add your API keys

# 3. Install server dependencies
cd server && uv sync

# 4. Install client dependencies
cd ../xr-client && npm install

# 5. Return to root
cd ..
```

### Running

**Option A: All-in-one**
```bash
./run-all.sh
```

**Option B: Separate terminals**
```bash
# Terminal 1: Server
cd server && uv run uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2: XR Client
cd xr-client && npm run dev
```

### Accessing

| Service | URL | Notes |
|---------|-----|-------|
| XR Client | https://localhost:5173 | Accept self-signed cert warning |
| Server API | http://localhost:8000 | REST + WebSocket |
| Health Check | http://localhost:8000/health | Verify server status |
| MCP Tools | http://localhost:8000/mcp | FastMCP endpoint |

**For Quest 3:** Use your computer's LAN IP (e.g., `https://192.168.1.100:5173`)

## 📁 Project Structure

```
garvis/
├── README.md                    # You are here
├── run-all.sh                   # Start all services
│
├── server/                      # Python backend
│   ├── main.py                  # FastAPI + FastMCP entry point
│   ├── config.py                # Configuration & environment
│   ├── env.example              # Environment template
│   ├── pyproject.toml           # Python dependencies
│   │
│   ├── api/
│   │   ├── health.py            # Health check endpoints
│   │   └── proxy.py             # HLS video proxy for CORS
│   │
│   ├── providers/               # Content provider system
│   │   ├── base.py              # Abstract provider interface
│   │   ├── crackstreams.py      # CrackStreams provider
│   │   └── registry.py          # Provider registry
│   │
│   ├── streaming/
│   │   └── helpers.py           # Stream URL helpers
│   │
│   ├── tools/
│   │   ├── mcp_tools.py         # SEARCH_CONTENT, SHOW_CONTENT
│   │   └── vision/              # Face detection tools
│   │       └── face_detect.py   # DeepFace/YOLO detection
│   │
│   └── voice/
│       ├── websocket.py         # WebSocket handler
│       ├── pipeline.py          # Voice pipeline orchestration
│       ├── deepgram_stt.py      # Speech-to-text client
│       ├── claude_llm.py        # Claude LLM with tool calling
│       └── elevenlabs_tts.py    # Text-to-speech client
│
└── xr-client/                   # React + WebXR frontend
    ├── src/
    │   ├── App.tsx              # Main XR application
    │   ├── main.tsx             # Entry point
    │   │
    │   ├── components/
    │   │   ├── XRCameraFeed.tsx     # Camera overlay & face boxes
    │   │   ├── FaceBoundingBox.tsx  # Animated face detection box
    │   │   ├── video/
    │   │   │   └── VideoWindow.tsx  # 3D video player panel
    │   │   └── visor/
    │   │       └── ChatLog.tsx      # HUD chat overlay
    │   │
    │   ├── hooks/               # React hooks
    │   │   ├── useXRCamera.ts       # Quest 3 camera access
    │   │   └── useFaceDetection.ts  # Face detection loop
    │   │
    │   ├── ecs/                 # Koota ECS state management
    │   │   ├── traits.ts        # State definitions (incl. ActiveVideo)
    │   │   ├── world.ts         # World initialization
    │   │   └── actions.ts       # State mutations
    │   │
    │   └── voice/
    │       ├── garvis-client.ts      # WebSocket client
    │       └── useVoiceAssistant.ts  # React hook
    │
    └── vite.config.ts           # HTTPS + proxy configuration
```

## ⚙️ Configuration

### Environment Variables

Create `server/.env` with:

```env
# Required API Keys
ANTHROPIC_API_KEY=sk-ant-...        # From console.anthropic.com
DEEPGRAM_API_KEY=...                 # From console.deepgram.com
ELEVENLABS_API_KEY=...               # From elevenlabs.io

# Optional: Voice customization
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb  # Default: George
ELEVENLABS_MODEL_ID=eleven_turbo_v2_5      # Low latency model

# Optional: Claude model
CLAUDE_MODEL=claude-sonnet-4-20250514      # Default model
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
CLAUDE_SYSTEM_PROMPT = """You are Garvis, a helpful AI assistant integrated into an XR heads-up display.
Keep responses concise and conversational since this is a voice conversation.
Always refer to yourself as Garvis when asked your name.
Be helpful, friendly, and efficient."""
```

## 🔌 MCP Tools

Garvis exposes an MCP (Model Context Protocol) endpoint for extensibility. Add custom tools to let Claude interact with external systems.

### Adding a Custom Tool

```python
# In server/main.py

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

- 🏠 **Smart Home** — Control lights, thermostat, devices
- 📅 **Calendar** — Check and create events
- 🔍 **Search** — Query databases or search engines
- 📧 **Email** — Read and compose messages
- 🎵 **Media** — Control music playback
- 📊 **Analytics** — Query business metrics

## 📺 Video Streaming

Garvis can open live video streams directly in your XR environment. Just ask:

> *"Show me the Lakers game"*  
> *"Find the NFL game"*  
> *"Play the UFC fight"*

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Video Streaming Flow                         │
│                                                                      │
│  1. Voice Command          2. Claude Tool Call       3. Stream Proxy │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐  │
│  │ "Show me    │ ───────▶ │ SEARCH_     │ ───────▶ │ HLS Proxy   │  │
│  │  the game"  │          │ CONTENT     │          │ /mcp/proxy  │  │
│  └─────────────┘          └─────────────┘          └──────┬──────┘  │
│                                                           │         │
│  6. VideoWindow            5. WebSocket Msg       4. Stream URL     │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐  │
│  │  3D Panel   │ ◀─────── │ stream_url  │ ◀─────── │ SHOW_       │  │
│  │  in XR      │          │ message     │          │ CONTENT     │  │
│  └─────────────┘          └─────────────┘          └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Video Window Controls

| Action | Description |
|--------|-------------|
| **Tap video** | First tap unmutes audio, subsequent taps toggle play/pause |
| **Drag title bar** | Move the window anywhere in 3D space |
| **Drag corner handle** | Resize window (0.5x to 2x) |
| **Click ✕** | Close the video window |

### Built-in MCP Tools

| Tool | Description |
|------|-------------|
| `SEARCH_CONTENT` | Search for live sports content by query |
| `SHOW_CONTENT` | Display a video stream in the XR environment |

### Supported Content

Currently supports live sports streams via CrackStreams provider. The modular provider system makes it easy to add new content sources.

## 👁️ Face Detection (Vision System)

Garvis includes a real-time face detection system that overlays bounding boxes on detected faces through Quest 3's passthrough view.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Face Detection Pipeline                         │
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │
│  │   Quest 3   │───▶│  XR Client  │───▶│   POST /detect-faces    │  │
│  │   Camera    │    │  captures   │    │   (base64 image)        │  │
│  │ (getUserMe- │    │  frames at  │    │                         │  │
│  │  dia API)   │    │  ~3 FPS     │    │   DeepFace/RetinaFace   │  │
│  └─────────────┘    └─────────────┘    │   → YOLO fallback       │  │
│                                        └───────────┬─────────────┘  │
│                                                    │                │
│  ┌─────────────────────────────────────────────────▼─────────────┐  │
│  │                   XR Bounding Box Overlay                      │  │
│  │                                                                │  │
│  │   • Positioned to align with passthrough view                 │  │
│  │   • Cyan corner-accent boxes with confidence labels           │  │
│  │   • Video feed hidden by default (overlay-only mode)          │  │
│  │                                                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Enabling/Disabling

Use the **VISION ON/OFF** toggle in the web UI before entering XR, or adjust settings:

| Setting | Range | Description |
|---------|-------|-------------|
| **Face FPS** | 1-10 | Detection frequency (higher = more responsive, more CPU) |
| **Confidence** | 0.1-0.9 | Minimum detection confidence threshold |
| **Enabled** | on/off | Toggle the entire vision system |

### Overlay Positioning

The bounding box overlay is positioned to align with real-world objects as seen through Quest 3 passthrough. The positioning is configured in `XRCameraFeed.tsx`:

```typescript
const OVERLAY_CONFIG = {
  distance: 0.6,      // Distance from eyes (meters) - reduces stereo mismatch
  xOffset: 0.04,      // Horizontal offset - compensates for camera position
  yOffset: -0.130,    // Vertical offset - camera is below eye level
  planeHeight: 0.2,   // Base overlay plane height (meters)
  baseDistance: 0.18, // Reference distance for scale calculation
}
```

These values were tuned heuristically on Quest 3. If overlays don't align with faces in your setup, adjust these values.

### Detection Backend

The server uses a two-tier detection approach:

1. **Primary: DeepFace + RetinaFace** — Most accurate face detection
2. **Fallback: YOLOv8** — If DeepFace fails, estimates face region from person detection

Both are included in the server dependencies and will be downloaded automatically on first run.

### API Endpoint

**POST `/detect-faces`**

```json
// Request
{
  "image_base64": "<base64 JPEG>",
  "confidence": 0.5,
  "max_detections": 10,
  "include_crops": false
}

// Response
{
  "success": true,
  "count": 2,
  "image_size": { "width": 640, "height": 480 },
  "detections": [
    {
      "id": 0,
      "class": "face",
      "confidence": 0.95,
      "bbox": { "x1": 100, "y1": 50, "x2": 200, "y2": 180 },
      "center": { "x": 150, "y": 115 }
    }
  ]
}
```

## 📡 WebSocket Protocol

### Client → Server

| Type | Format | Description |
|------|--------|-------------|
| Audio | Binary | 16-bit PCM, 16kHz, mono |
| `start` | JSON | Begin listening |
| `stop` | JSON | Stop listening |
| `interrupt` | JSON | Stop TTS playback |
| `config` | JSON | Update settings |

### Server → Client

| Type | Format | Description |
|------|--------|-------------|
| Audio | Binary | MP3 audio stream |
| `transcript` | JSON | Speech transcription |
| `status` | JSON | Listening/speaking state |
| `error` | JSON | Error message |

### Message Examples

```json
// Transcript update
{
  "type": "transcript",
  "text": "Hello, how can I help?",
  "is_final": true,
  "role": "assistant"
}

// Status update
{
  "type": "status",
  "listening": true,
  "speaking": false
}
```

## 🔧 Troubleshooting

### Common Issues

<details>
<summary><strong>🔴 "WebSocket connection failed"</strong></summary>

1. Ensure server is running on port 8000
2. Check if the proxy in `vite.config.ts` is configured correctly
3. Verify no firewall blocking WebSocket connections

</details>

<details>
<summary><strong>🔴 "Microphone access denied"</strong></summary>

1. HTTPS is required for microphone access
2. Accept the self-signed certificate warning
3. Grant microphone permission when prompted
4. On Quest 3, ensure browser has microphone permissions

</details>

<details>
<summary><strong>🔴 "No audio playback"</strong></summary>

1. Check browser console for audio context errors
2. User interaction may be required before audio plays
3. Verify Eleven Labs API key is valid
4. Check server logs for TTS errors

</details>

<details>
<summary><strong>🔴 "Quest 3 can't connect"</strong></summary>

1. Use your computer's LAN IP, not `localhost`
2. Ensure both devices are on the same network
3. Accept the self-signed certificate in Quest browser
4. Check firewall allows connections on ports 5173 and 8000

</details>

<details>
<summary><strong>🔴 "Transcription not working"</strong></summary>

1. Verify Deepgram API key is set
2. Check server logs for STT connection errors
3. Ensure microphone is capturing audio (browser indicator should show)
4. VAD may need audio above threshold to trigger

</details>

<details>
<summary><strong>🔴 "Face detection not showing boxes"</strong></summary>

1. Ensure Vision is enabled (toggle in UI before entering XR)
2. Check that camera permission was granted
3. Look at server logs for detection errors
4. Face detection requires good lighting
5. First request may be slow as models download

</details>

<details>
<summary><strong>🔴 "Face boxes don't align with faces"</strong></summary>

1. The overlay positioning is tuned for Quest 3 passthrough
2. Different headsets may need different positioning values
3. Edit `OVERLAY_CONFIG` in `xr-client/src/components/XRCameraFeed.tsx`:
   - `distance`: How far in front (0.5-1.0m typical)
   - `xOffset`: Left/right adjustment (-0.1 to 0.1m)
   - `yOffset`: Up/down adjustment (-0.2 to 0.0m)

</details>

<details>
<summary><strong>🔴 "Python 3.14 error during uv sync"</strong></summary>

TensorFlow (required by DeepFace) doesn't support Python 3.14 yet.

```bash
cd server
uv python pin 3.13
uv sync
```

</details>

### Debug Mode

Enable verbose logging:

```bash
# Server with debug output
cd server && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --log-level debug
```

## 🎯 Performance Tips

### Reducing Latency

1. **Use Eleven Labs Turbo** — `eleven_turbo_v2_5` is optimized for speed
2. **Shorter responses** — Tune system prompt for concise replies
3. **Stable network** — Quest on 5GHz WiFi, wired computer
4. **Local server** — Run server on same network as Quest

### Estimated Latency Breakdown

| Stage | Typical Time |
|-------|--------------|
| Audio capture + send | ~50ms |
| Deepgram STT | ~200-400ms |
| Claude response (first token) | ~300-600ms |
| Eleven Labs TTS (first audio) | ~200-400ms |
| **Total first response** | **~750ms-1.5s** |

## 🛠️ Development

### Running Tests

```bash
# Server tests
cd server && uv run pytest

# Client linting
cd xr-client && npm run lint
```

### Building for Production

```bash
# Build XR client
cd xr-client && npm run build

# Output in xr-client/dist/
```

### Tech Stack

**Server:**
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Python web framework
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Deepgram SDK](https://developers.deepgram.com/) — Speech-to-text
- [ElevenLabs SDK](https://elevenlabs.io/docs) — Text-to-speech
- [Anthropic SDK](https://docs.anthropic.com/) — Claude AI
- [DeepFace](https://github.com/serengil/deepface) — Face detection (RetinaFace backend)
- [Ultralytics](https://ultralytics.com/) — YOLOv8 for fallback detection

**Client:**
- [React 19](https://react.dev/) — UI framework
- [Three.js](https://threejs.org/) — 3D rendering
- [React Three Fiber](https://r3f.docs.pmnd.rs/) — React renderer for Three.js
- [React Three XR](https://github.com/pmndrs/xr) — WebXR integration
- [Koota](https://github.com/pmndrs/koota) — ECS state management
- [Vite](https://vitejs.dev/) — Build tool

## 🎙️ Discord Voice Assistant

Garvis can also run as a Discord bot, allowing you to have voice conversations in Discord voice channels.

### Setup

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

3. **Run the Bot**:
   ```bash
   # Linux/macOS
   ./run-discord-bot.sh
   
   # Windows
   run-discord-bot.bat
   ```

### Discord Commands

| Command | Description |
|---------|-------------|
| `!join` | Join your current voice channel |
| `!leave` | Leave the voice channel |
| `!listen @user` | Only respond to a specific user |
| `!listen all` | Respond to everyone in the channel |
| `!status` | Show current bot status |

### How It Works

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

The Discord bot uses the same voice pipeline components as the XR client:
- **Deepgram** for real-time speech-to-text
- **Claude** for intelligent responses  
- **ElevenLabs** for natural text-to-speech

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with 💜 for immersive AI experiences**

[Report Bug](https://github.com/yourusername/garvis/issues) · [Request Feature](https://github.com/yourusername/garvis/issues)

</div>
