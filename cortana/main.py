"""
Cortana - Lightweight Discord Voice Bot

Local voice stack using:
- Whisper STT (faster-whisper)
- Ollama LLM (huihui_ai/qwen3-abliterated)
- Kokoro TTS

Run with: python main.py
"""

from discord_bot.bot import run_bot

if __name__ == "__main__":
    run_bot()
