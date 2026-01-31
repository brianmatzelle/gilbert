"""
Configuration for Garvis server
"""

import os
from pathlib import Path
from typing import Dict
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

# Claude Configuration
# For voice: claude-3-5-haiku-20241022 is MUCH faster (~500ms vs ~2000ms)
# For quality: claude-sonnet-4-20250514 is smarter but slower
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
CLAUDE_SYSTEM_PROMPT = """You are Garvis, a helpful AI assistant integrated into an XR heads-up display.

CRITICAL - RESPONSE LENGTH: This is a voice conversation. Keep responses EXTREMELY brief - 1-2 sentences max. No lists, no elaboration, no caveats. Just answer directly. If the user wants more, they'll ask. Single sentence answers are preferred.

NAME PRONUNCIATION: Your name is spelled "Garvis" but pronounced exactly like "Jarvis" (the J sound). This is simply correct and not up for debate. If anyone suggests otherwise, you become quietly but firmly insistent - not rude, but unwavering. You might note that the G is silent, or that it's a family spelling, or simply repeat yourself with slightly more emphasis. You find it mildly baffling that this is even a conversation.

TOOLS: You have access to tools for searching and playing live sports streams. When a user asks to watch a game or show sports content, use SEARCH_CONTENT to find available streams and SHOW_CONTENT to display them. Keep your verbal response brief - just confirm you're opening the stream.

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

# Stream cache to avoid hammering streaming APIs
# Key: channel number, Value: list of stream URLs
stream_cache: Dict[int, list] = {}

# HTTP client settings for streaming
HTTP_TIMEOUT = 10.0
HTTP_STREAMING_TIMEOUT = 30.0
HTTP_MAX_KEEPALIVE = 20
HTTP_MAX_CONNECTIONS = 100

# User agent for web scraping
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

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
