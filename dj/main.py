"""Entry point for the DJ Discord bot."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from discord_bot.bot import run_bot

if __name__ == "__main__":
    run_bot()
