"""DJ bot configuration — loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DEFAULT_VOLUME = float(os.getenv("DEFAULT_VOLUME", "0.5"))
