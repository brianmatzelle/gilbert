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
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

# Discord Bot Configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Claude Configuration
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
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
# Lower values = faster response but may cut off speech prematurely
# Higher values = more accurate but slower response

# Deepgram STT Configuration
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")  # nova-2 is fast and accurate
DEEPGRAM_UTTERANCE_END_MS = int(os.getenv("DEEPGRAM_UTTERANCE_END_MS", "1000"))  # ms of silence before UtteranceEnd (min=1000, max=5000)
DEEPGRAM_ENDPOINTING = int(os.getenv("DEEPGRAM_ENDPOINTING", "300"))  # endpoint detection threshold in ms - fires speech_final
# Use speech_final (fast, 300ms) instead of UtteranceEnd (slow, 1000ms minimum) to trigger LLM response
DEEPGRAM_USE_SPEECH_FINAL = os.getenv("DEEPGRAM_USE_SPEECH_FINAL", "true").lower() == "true"

# Audio processing intervals (seconds)
AUDIO_PROCESS_INTERVAL = float(os.getenv("AUDIO_PROCESS_INTERVAL", "0.05"))  # how often to process audio (default was 0.1)
AUDIO_SILENCE_THRESHOLD = float(os.getenv("AUDIO_SILENCE_THRESHOLD", "0.2"))  # silence before speech end callback (default was 0.3)

# TTS streaming configuration  
TTS_BUFFER_THRESHOLD = int(os.getenv("TTS_BUFFER_THRESHOLD", "500"))  # bytes before flushing TTS audio (default was 1000)

