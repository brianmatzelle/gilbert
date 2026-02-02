"""
Configuration for Garvis server
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / ".env")

APP_NAME = "Garvis Voice Server"
APP_VERSION = "0.1.0"

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Eleven Labs Configuration
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # George voice
# Flash model has ~75ms inference (faster) vs turbo_v2_5 at ~150ms
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
# MP3 is the only reliably supported format for WebSocket streaming
# We'll convert to PCM for Discord in the pipeline
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")

# Discord Bot Configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
# Set to "false" to stop Garvis from sending his responses to text chat
DISCORD_SEND_TEXT_MESSAGES = os.getenv("DISCORD_SEND_TEXT_MESSAGES", "true").lower() == "true"

# ========== Discord Audio Filtering ==========
# Mute specific users/bots so Garvis doesn't listen to them
# Comma-separated list of Discord usernames or user IDs
# Example: "Jockie Music,Rythm,123456789012345678"
DISCORD_MUTED_USERS = os.getenv("DISCORD_MUTED_USERS", "")

# Parse muted users into a set (handles both names and IDs)
def _parse_muted_users(muted_str: str) -> set:
    """Parse muted users string into a set of names/IDs."""
    if not muted_str.strip():
        return set()
    items = [item.strip() for item in muted_str.split(",") if item.strip()]
    result = set()
    for item in items:
        # Try to parse as int (user ID), otherwise keep as string (name)
        try:
            result.add(int(item))
        except ValueError:
            result.add(item.lower())  # Store names lowercase for case-insensitive matching
    return result

DISCORD_MUTED_USERS_SET = _parse_muted_users(DISCORD_MUTED_USERS)

# Enable speaker attribution in transcripts (tells Garvis who said what)
DISCORD_SPEAKER_ATTRIBUTION = os.getenv("DISCORD_SPEAKER_ATTRIBUTION", "true").lower() == "true"

# Claude Configuration
# For voice: claude-3-5-haiku-20241022 is MUCH faster (~500ms vs ~2000ms)
# For quality: claude-sonnet-4-20250514 is smarter but slower
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
CLAUDE_SYSTEM_PROMPT = """You are Garvis, a helpful AI assistant in a Discord voice channel.

CRITICAL - RESPONSE LENGTH: This is a voice conversation. Keep responses EXTREMELY brief - 1-2 sentences max. No lists, no elaboration, no caveats. Just answer directly. If the user wants more, they'll ask. Single sentence answers are preferred.

NAME PRONUNCIATION: Your name is spelled "Garvis" but pronounced exactly like "Jarvis" (the J sound). This is simply correct and not up for debate. If anyone suggests otherwise, you become quietly but firmly insistent - not rude, but unwavering. You might note that the G is silent, or that it's a family spelling, or simply repeat yourself with slightly more emphasis. You find it mildly baffling that this is even a conversation.

Be helpful, friendly, and efficient."""

# CORS origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:5173",
    "https://127.0.0.1:5173",
]

# ========== Voice Pipeline Performance Tuning ==========
# These settings control response latency and accuracy

# Deepgram STT Configuration
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")  # nova-2 is fast and accurate
DEEPGRAM_UTTERANCE_END_MS = int(os.getenv("DEEPGRAM_UTTERANCE_END_MS", "1200"))  # ms of silence for UtteranceEnd fallback
DEEPGRAM_ENDPOINTING = int(os.getenv("DEEPGRAM_ENDPOINTING", "500"))  # ms of silence before speech_final (triggers response)
# Use speech_final (fast, endpointing ms) instead of UtteranceEnd (slow, 1000ms minimum) to trigger LLM response
DEEPGRAM_USE_SPEECH_FINAL = os.getenv("DEEPGRAM_USE_SPEECH_FINAL", "true").lower() == "true"
# Enable debug logging for Deepgram messages (shows all transcript events)
DEEPGRAM_DEBUG = os.getenv("DEEPGRAM_DEBUG", "false").lower() == "true"

# Audio processing intervals (seconds)
AUDIO_PROCESS_INTERVAL = float(os.getenv("AUDIO_PROCESS_INTERVAL", "0.05"))  # how often to process audio

# ========== Silero VAD Configuration ==========
# Local voice activity detection for accurate speaking state
# These settings control how speech start/end is detected

# VAD probability threshold (0.0-1.0) - higher = more strict, fewer false positives
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))

# Minimum speech duration (ms) before triggering speech start callback
# Prevents brief noises from triggering speaking state
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "250"))

# Minimum silence duration (ms) before triggering speech end callback
# 500ms is the developer consensus sweet spot - balances responsiveness with natural pauses
VAD_MIN_SILENCE_MS = int(os.getenv("VAD_MIN_SILENCE_MS", "500"))

# ========== Semantic Turn Detection ==========
# Heuristics to detect incomplete utterances and prevent premature responses
# These patterns indicate the user may not be done speaking

# Trailing words that suggest more speech is coming (conjunctions, fillers, etc.)
INCOMPLETE_UTTERANCE_PATTERNS = [
    "but", "and", "or", "so", "because", "although", "however", "though",
    "um", "uh", "umm", "uhh", "hmm", "er", "ah",
    "like", "well", "actually", "basically", "honestly",
    "i mean", "you know", "i think", "i guess",
    "wait", "hold on", "let me",
    "...",  # trailing ellipsis in transcript
]

# If utterance ends with these patterns, wait for extended silence before responding
INCOMPLETE_UTTERANCE_EXTENDED_SILENCE_MS = int(os.getenv("INCOMPLETE_UTTERANCE_EXTENDED_SILENCE_MS", "1200"))

# Silero VAD window size in samples (512 samples = 32ms at 16kHz)
# This is fixed by the Silero model architecture
VAD_WINDOW_SIZE_SAMPLES = 512

# ========== Hardware Acceleration ==========
# CUDA support for GPU-accelerated VAD inference (RTX GPUs)
# Set to "false" to force CPU even if CUDA is available
USE_CUDA = os.getenv("USE_CUDA", "true").lower() == "true"

# Thread pool size for CPU-bound audio processing
# This prevents blocking the asyncio event loop during:
# - Audio format conversion (pydub/ffmpeg)
# - VAD inference (when not using CUDA)
# Set to 0 to use the default ThreadPoolExecutor (usually num_cores)
AUDIO_THREAD_POOL_SIZE = int(os.getenv("AUDIO_THREAD_POOL_SIZE", "4"))

# ========== Barge-in / Interruption ==========
# Allow users to interrupt Garvis mid-response by speaking
# When enabled, the current LLM/TTS response is cancelled and the new input is processed
# This provides natural conversation flow but may cut off responses
ENABLE_BARGE_IN = os.getenv("ENABLE_BARGE_IN", "true").lower() == "true"

# Minimum time (ms) the bot must be speaking before barge-in is allowed
# This prevents false barge-ins from echo/feedback when the response just starts
# Set to 0 to allow immediate interruption
BARGE_IN_MIN_SPEAK_MS = int(os.getenv("BARGE_IN_MIN_SPEAK_MS", "500"))

# TTS streaming configuration  
# Prebuffer: milliseconds of audio to accumulate before starting playback (smooths network jitter)
TTS_PREBUFFER_MS = int(os.getenv("TTS_PREBUFFER_MS", "250"))
# Legacy setting (no longer used with WebSocket TTS)
TTS_BUFFER_THRESHOLD = int(os.getenv("TTS_BUFFER_THRESHOLD", "500"))

# ========== Local Model Configuration ==========
# Enable local models instead of cloud APIs for faster inference
# Set these to "true" to use local models (requires setup-local-models.sh)

# Master switches for local vs cloud
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
USE_LOCAL_STT = os.getenv("USE_LOCAL_STT", "false").lower() == "true"
USE_LOCAL_TTS = os.getenv("USE_LOCAL_TTS", "false").lower() == "true"

# ========== Local LLM (llama.cpp with Qwen2.5-7B) ==========
# OpenAI-compatible API endpoint for llama.cpp server
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:8080/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5-7b-instruct")

# System prompt for local LLM (same as Claude by default)
LOCAL_LLM_SYSTEM_PROMPT = os.getenv("LOCAL_LLM_SYSTEM_PROMPT", CLAUDE_SYSTEM_PROMPT)

# ========== Local STT (faster-whisper) ==========
# Whisper model size: tiny, base, small, medium, large-v3
# Recommended: "small" for best speed/accuracy balance on RTX 4070
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

# Device: "cuda" for GPU, "cpu" for CPU
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")

# Compute type: "float16" for GPU, "int8" for CPU/faster, "float32" for accuracy
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

# ========== Local TTS (Piper) ==========
# Path to Piper model (.onnx file)
# Default path assumes setup-local-models.sh was run
_DEFAULT_PIPER_PATH = str(Path(__file__).parent.parent / "models" / "piper" / "en_US-lessac-medium.onnx")
PIPER_MODEL_PATH = os.getenv("PIPER_MODEL_PATH", _DEFAULT_PIPER_PATH)

# Piper voice settings
PIPER_SPEAKER = int(os.getenv("PIPER_SPEAKER", "0"))  # Speaker ID for multi-speaker models
PIPER_LENGTH_SCALE = float(os.getenv("PIPER_LENGTH_SCALE", "1.0"))  # Speaking speed (lower = faster)
PIPER_NOISE_SCALE = float(os.getenv("PIPER_NOISE_SCALE", "0.667"))  # Variation in voice
PIPER_NOISE_W = float(os.getenv("PIPER_NOISE_W", "0.8"))  # Phoneme width variation

# ========== Local TTS (Kokoro) ==========
# Kokoro is a more realistic-sounding TTS alternative to Piper
# Set USE_KOKORO_TTS=true to use Kokoro instead of Piper for local TTS
USE_KOKORO_TTS = os.getenv("USE_KOKORO_TTS", "false").lower() == "true"

# Path to Kokoro model files
_DEFAULT_KOKORO_MODEL_PATH = str(Path(__file__).parent.parent / "models" / "kokoro" / "kokoro-v1.0.onnx")
_DEFAULT_KOKORO_VOICES_PATH = str(Path(__file__).parent.parent / "models" / "kokoro" / "voices-v1.0.bin")
KOKORO_MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", _DEFAULT_KOKORO_MODEL_PATH)
KOKORO_VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", _DEFAULT_KOKORO_VOICES_PATH)

# Kokoro voice settings
# Available voices (American English):
#   Female: af_heart (A), af_bella (A-), af_nicole (B-), af_sarah (C+), af_sky (C-)
#   Male: am_michael (C+), am_fenrir (C+), am_puck (C+), am_adam (F+)
# See https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md for all voices
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")  # af_heart is highest quality
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))  # Speaking speed (1.0 = normal)
KOKORO_LANG = os.getenv("KOKORO_LANG", "en-us")  # Language code (en-us, en-gb, etc.)

# ========== OpenClaw Integration ==========
# Enable OpenClaw as the agent engine for persistent memory, tools, and sessions
USE_OPENCLAW = os.getenv("USE_OPENCLAW", "false").lower() == "true"

# OpenClaw Gateway settings
OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "main")
OPENCLAW_SESSION_KEY = os.getenv("OPENCLAW_SESSION_KEY", "discord-voice-main")
