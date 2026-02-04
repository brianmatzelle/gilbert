# Cortana - Lightweight Discord Voice Bot

A streamlined Discord voice bot using a fully local AI stack:

- **STT**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local, CUDA accelerated)
- **LLM**: [Ollama](https://ollama.com/) with [qwen3-abliterated](https://ollama.com/huihui_ai/qwen3-abliterated)
- **TTS**: [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (local, highly realistic voices)
- **VAD**: [Silero VAD](https://github.com/snakers4/silero-vad) (local, CUDA accelerated)

## Prerequisites

1. **Ollama** - Install and run Ollama:
   ```bash
   # Install Ollama (see https://ollama.com/download)
   # Pull the model
   ollama pull huihui_ai/qwen3-abliterated:8b
   
   # Ollama serves at http://localhost:11434 by default
   ```

2. **Kokoro TTS Models** - Download from HuggingFace:
   ```bash
   # Create models directory
   mkdir -p models/kokoro
   
   # Download model and voices
   curl -L -o models/kokoro/kokoro-v1.0.onnx \
     https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v1.0.onnx
   
   curl -L -o models/kokoro/voices-v1.0.bin \
     https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices-v1.0.bin
   ```

3. **FFmpeg** - Required for audio processing:
   ```bash
   # Windows (with Chocolatey)
   choco install ffmpeg
   
   # macOS
   brew install ffmpeg
   
   # Ubuntu/Debian
   sudo apt install ffmpeg
   ```

4. **CUDA** (optional but recommended) - For GPU acceleration

## Installation

```bash
# Navigate to cortana directory
cd cortana

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your Discord bot token:
   ```
   DISCORD_BOT_TOKEN=your_token_here
   ```

3. Adjust other settings as needed (model paths, voice selection, etc.)

## Running

```bash
# Make sure Ollama is running with the model
ollama run huihui_ai/qwen3-abliterated:8b

# In another terminal, run Cortana
python main.py
```

## Discord Commands

| Command | Description |
|---------|-------------|
| `!join` | Join your voice channel |
| `!leave` | Leave the voice channel |
| `!listen @user` | Only listen to a specific user |
| `!listen all` | Listen to everyone |
| `!mute @user` | Mute a user (ignore their audio) |
| `!unmute @user` | Unmute a user |
| `!bargein` | Toggle barge-in (interrupt) feature |
| `!status` | Show current status |

## Architecture

```
User speaks → Discord Audio (48kHz stereo)
                    ↓
              Audio Sink (convert to 16kHz mono)
                    ↓
              Silero VAD (speech detection)
                    ↓
              Whisper STT (transcription)
                    ↓
              Ollama LLM (response generation)
                    ↓
              Kokoro TTS (speech synthesis)
                    ↓
              Audio output (48kHz stereo) → Discord
```

## Compared to Garvis

Cortana is a simplified version of Garvis with:

| Feature | Cortana | Garvis |
|---------|---------|--------|
| LLM | Ollama (local) | Claude/OpenClaw/Local |
| STT | Whisper only | Whisper/Deepgram |
| TTS | Kokoro only | Kokoro/Piper/ElevenLabs |
| Auto-join | No | Yes |
| Wake word | No | Yes |
| API server | No | Yes |
| Speaker attribution | No | Yes |
| Code size | ~1500 lines | ~5000+ lines |

Cortana is designed to be:
- **Lightweight**: Minimal dependencies and code
- **Local**: No cloud APIs required
- **Simple**: Easy to understand and modify

## License

Same license as the parent guitar2discord project.
