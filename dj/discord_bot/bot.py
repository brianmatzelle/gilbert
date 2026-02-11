"""
DJ Discord Bot — stream songs to voice channels via ?play {url}.

Lightweight music bot using yt-dlp + ffmpeg under the hood.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.getLogger("discord.player").setLevel(logging.WARNING)
logging.getLogger("discord.voice_client").setLevel(logging.WARNING)

import discord
from discord.ext import commands

from config import DISCORD_BOT_TOKEN, DEFAULT_VOLUME
from .music_player import MusicPlayer


class GuildState:
    """Per-guild voice + music state."""

    def __init__(self):
        self.voice_client: Optional[discord.VoiceClient] = None
        self.player: Optional[MusicPlayer] = None
        self.volume: float = DEFAULT_VOLUME


class DJBot(commands.Bot):
    """
    Discord music bot.

    Commands:
        ?join       — Join your voice channel
        ?leave      — Disconnect from voice
        ?play {url} — Play a song (or queue it if something is playing)
        ?skip       — Skip the current song
        ?stop       — Stop playback and clear queue
        ?queue      — Show the current queue
        ?np         — Show what's playing now
        ?volume N   — Set volume (0–100)
    """

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True

        super().__init__(
            command_prefix="?",
            intents=intents,
            description="DJ — your music bot",
        )

        self._states: Dict[int, GuildState] = {}
        self._add_commands()

    def _get_guild_state(self, guild_id: int) -> GuildState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildState()
        return self._states[guild_id]

    # -- Commands -------------------------------------------------------------

    def _add_commands(self):

        @self.command(name="join", help="Join your voice channel")
        async def join(ctx: commands.Context):
            if not ctx.author.voice:
                await ctx.send("You need to be in a voice channel.")
                return

            channel = ctx.author.voice.channel
            state = self._get_guild_state(ctx.guild.id)

            if state.voice_client and state.voice_client.is_connected():
                await state.voice_client.move_to(channel)
            else:
                state.voice_client = await channel.connect()

            state.player = MusicPlayer(
                state.voice_client,
                asyncio.get_running_loop(),
                volume=state.volume,
            )

            await ctx.send(f"Joined **{channel.name}**.")

        @self.command(name="leave", help="Leave the voice channel")
        async def leave(ctx: commands.Context):
            state = self._get_guild_state(ctx.guild.id)
            if not state.voice_client or not state.voice_client.is_connected():
                await ctx.send("I'm not in a voice channel.")
                return

            if state.player:
                await state.player.stop()
                state.player.cleanup()
                state.player = None

            await state.voice_client.disconnect()
            state.voice_client = None
            await ctx.send("Left the voice channel.")

        @self.command(name="play", help="Play a song from a URL")
        async def play(ctx: commands.Context, *, url: str):
            state = self._get_guild_state(ctx.guild.id)

            # Auto-join if not connected
            if not state.voice_client or not state.voice_client.is_connected():
                if not ctx.author.voice:
                    await ctx.send("You need to be in a voice channel.")
                    return
                channel = ctx.author.voice.channel
                state.voice_client = await channel.connect()
                state.player = MusicPlayer(
                    state.voice_client,
                    asyncio.get_running_loop(),
                    volume=state.volume,
                )

            if not state.player:
                state.player = MusicPlayer(
                    state.voice_client,
                    asyncio.get_running_loop(),
                    volume=state.volume,
                )

            await ctx.send(f"Searching **{url}** ...")
            result = await state.player.play(url)

            if result["status"] == "error":
                await ctx.send(f"Error: {result['error']}")
            elif result["status"] == "playing":
                duration = _fmt_duration(result.get("duration"))
                await ctx.send(f"Now playing: **{result['title']}** {duration}")
            elif result["status"] == "queued":
                duration = _fmt_duration(result.get("duration"))
                await ctx.send(
                    f"Queued #{result['position']}: **{result['title']}** {duration}"
                )

        @self.command(name="skip", help="Skip the current song")
        async def skip(ctx: commands.Context):
            state = self._get_guild_state(ctx.guild.id)
            if not state.player or not state.player.is_playing:
                await ctx.send("Nothing is playing.")
                return
            result = await state.player.skip()
            await ctx.send("Skipped.")

        @self.command(name="stop", help="Stop playback and clear queue")
        async def stop(ctx: commands.Context):
            state = self._get_guild_state(ctx.guild.id)
            if not state.player:
                await ctx.send("Nothing is playing.")
                return
            await state.player.stop()
            await ctx.send("Stopped.")

        @self.command(name="queue", aliases=["q"], help="Show the queue")
        async def queue(ctx: commands.Context):
            state = self._get_guild_state(ctx.guild.id)
            if not state.player:
                await ctx.send("Nothing is playing.")
                return

            lines = []

            now = state.player.now_playing
            if now:
                duration = _fmt_duration(now.duration)
                lines.append(f"Now playing: **{now.title}** {duration}")

            q = state.player.queue
            if q:
                lines.append("")
                for i, song in enumerate(q, 1):
                    duration = _fmt_duration(song.duration)
                    lines.append(f"`{i}.` {song.title} {duration}")
            elif not now:
                lines.append("Queue is empty.")

            await ctx.send("\n".join(lines) if lines else "Queue is empty.")

        @self.command(name="np", aliases=["nowplaying"], help="Now playing")
        async def np(ctx: commands.Context):
            state = self._get_guild_state(ctx.guild.id)
            if not state.player or not state.player.now_playing:
                await ctx.send("Nothing is playing.")
                return
            song = state.player.now_playing
            duration = _fmt_duration(song.duration)
            await ctx.send(f"Now playing: **{song.title}** {duration}")

        @self.command(name="volume", aliases=["vol"], help="Set volume (0–100)")
        async def volume(ctx: commands.Context, level: int):
            state = self._get_guild_state(ctx.guild.id)
            state.volume = max(0.0, min(1.0, level / 100))

            if state.player:
                state.player.set_volume(state.volume)

            await ctx.send(f"Volume set to **{int(state.volume * 100)}%**.")

    # -- Events ---------------------------------------------------------------

    async def on_ready(self):
        print(f"\nDJ bot is ready! Logged in as {self.user.name} ({self.user.id})", flush=True)
        print(f"Servers: {len(self.guilds)}", flush=True)
        print(flush=True)
        print("Commands:", flush=True)
        print("  ?join          Join your voice channel", flush=True)
        print("  ?play {url}    Play a song", flush=True)
        print("  ?skip          Skip current song", flush=True)
        print("  ?stop          Stop and clear queue", flush=True)
        print("  ?queue         Show queue", flush=True)
        print("  ?np            Now playing", flush=True)
        print("  ?volume 0-100  Set volume", flush=True)
        print("  ?leave         Disconnect", flush=True)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # Clean up if bot gets disconnected
        if member.id == self.user.id and before.channel and not after.channel:
            state = self._get_guild_state(member.guild.id)
            if state.player:
                state.player.cleanup()
                state.player = None
            state.voice_client = None

        # Auto-leave if channel empties
        guild_id = member.guild.id
        state = self._get_guild_state(guild_id)
        if state.voice_client and state.voice_client.is_connected():
            if before.channel == state.voice_client.channel:
                channel = member.guild.get_channel(before.channel.id)
                if channel:
                    non_bots = [m for m in channel.members if not m.bot]
                    if not non_bots:
                        if state.player:
                            await state.player.stop()
                            state.player.cleanup()
                            state.player = None
                        await state.voice_client.disconnect()
                        state.voice_client = None


def _fmt_duration(seconds: Optional[int]) -> str:
    """Format seconds into (M:SS) or empty string."""
    if seconds is None:
        return ""
    m, s = divmod(seconds, 60)
    return f"({m}:{s:02d})"


def run_bot():
    """Run the DJ bot."""
    if not DISCORD_BOT_TOKEN:
        print("DISCORD_BOT_TOKEN is not set!")
        print("Copy dj/.env.example to dj/.env and add your token.")
        return

    async def _run():
        import logging
        logging.basicConfig(level=logging.INFO)
        bot = DJBot()
        print("Starting bot...", flush=True)
        await bot.start(DISCORD_BOT_TOKEN)

    asyncio.run(_run())


if __name__ == "__main__":
    run_bot()
