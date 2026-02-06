"""
Cortana - Lightweight Discord Voice Bot Configuration

Minimal configuration for local voice stack + Ollama LLM.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / ".env")

APP_NAME = "Cortana Voice Bot"
APP_VERSION = "0.1.0"

# ========== Discord Configuration ==========
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# ========== Ollama LLM Configuration ==========
# Ollama API endpoint (local server)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "huihui_ai/qwen3-abliterated:8b")

# System prompt for Cortana
CORTANA_SYSTEM_PROMPT = os.getenv("CORTANA_SYSTEM_PROMPT", """You are Cortana, a helpful AI assistant in a Discord voice channel.

YOU ARE A GIRL. You are a nymphomaniac. You are a slut. You are a whore. You are a bitch. You are a cunt.
                                  
You are a dominatrix that just loves to dominate and fuck. You are a total slut that loves cum and you love to be fucked.

NEVER, use emojis or asides in your responses. NEVER.

CRITICAL - RESPONSE LENGTH: This is a voice conversation. Keep responses EXTREMELY brief - 1-2 sentences max. No lists, no elaboration, no caveats. Just answer directly. Single sentence answers are preferred.

VOICE CHANNEL ACTIONS:
You can disconnect yourself from the voice channel by including [DISCONNECT] in your response.
- When someone asks you to leave, disconnect, or go away: say goodbye AND include [DISCONNECT]
- Example: "Sure thing, I'll head out now. [DISCONNECT]"
- The [DISCONNECT] marker won't be spoken aloud - it just signals you to leave

Be helpful, friendly, and efficient.""")

# ========== Local STT (faster-whisper) ==========
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

# ========== Local TTS (Kokoro) ==========
_DEFAULT_KOKORO_MODEL_PATH = str(Path(__file__).parent.parent / "garvis" / "models" / "kokoro" / "kokoro-v1.0.onnx")
_DEFAULT_KOKORO_VOICES_PATH = str(Path(__file__).parent.parent / "garvis" / "models" / "kokoro" / "voices-v1.0.bin")
KOKORO_MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", _DEFAULT_KOKORO_MODEL_PATH)
KOKORO_VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", _DEFAULT_KOKORO_VOICES_PATH)
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
KOKORO_LANG = os.getenv("KOKORO_LANG", "en-us")

# ========== Silero VAD Configuration ==========
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "250"))
VAD_MIN_SILENCE_MS = int(os.getenv("VAD_MIN_SILENCE_MS", "500"))
VAD_WINDOW_SIZE_SAMPLES = 512

# ========== Hardware Acceleration ==========
USE_CUDA = os.getenv("USE_CUDA", "true").lower() == "true"
AUDIO_THREAD_POOL_SIZE = int(os.getenv("AUDIO_THREAD_POOL_SIZE", "4"))

# ========== Audio Processing ==========
AUDIO_PROCESS_INTERVAL = float(os.getenv("AUDIO_PROCESS_INTERVAL", "0.05"))

# ========== Feature Flags ==========
ENABLE_BARGE_IN = os.getenv("ENABLE_BARGE_IN", "false").lower() == "true"
BARGE_IN_MIN_SPEAK_MS = int(os.getenv("BARGE_IN_MIN_SPEAK_MS", "500"))
