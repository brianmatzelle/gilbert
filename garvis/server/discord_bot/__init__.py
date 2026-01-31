"""
Discord voice assistant integration for Garvis.

This module provides a Discord bot that uses the Garvis voice pipeline
to create an AI assistant you can talk to in Discord voice channels.
"""

from .bot import GarvisDiscordBot, run_bot
from .audio_sink import GarvisAudioSink

__all__ = ["GarvisDiscordBot", "GarvisAudioSink", "run_bot"]
