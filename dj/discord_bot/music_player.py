"""
Music player for the DJ bot.

Uses yt-dlp to extract audio stream URLs and FFmpegPCMAudio to play them
into a Discord voice channel. Supports a queue for sequential playback.

Adapted from garvis/server/discord_bot/music_player.py — stripped down to
play directly via voice_client instead of going through a MixingAudioSource.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import discord

# yt-dlp options: extract best audio, don't download, be quiet
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "geo_bypass": True,
}

# FFmpeg options for streaming from a URL
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


@dataclass
class SongInfo:
    """Metadata for a queued song."""
    url: str
    title: str = "Unknown"
    duration: Optional[int] = None
    stream_url: str = ""


class MusicPlayer:
    """
    Manages music playback for a single guild.

    Usage:
        player = MusicPlayer(voice_client, loop, volume=0.5)
        result = await player.play("https://youtube.com/watch?v=...")
        await player.skip()
        await player.stop()
    """

    def __init__(
        self,
        voice_client: discord.VoiceClient,
        loop: asyncio.AbstractEventLoop,
        volume: float = 0.5,
    ):
        self.voice_client = voice_client
        self._loop = loop
        self._queue: list[SongInfo] = []
        self._current: Optional[SongInfo] = None
        self._volume = max(0.0, min(1.0, volume))

    # -- Public API -----------------------------------------------------------

    async def play(self, url: str) -> dict:
        """
        Play audio from a URL. If something is already playing, queue it.
        """
        try:
            info = await self._extract_info(url)
        except Exception as e:
            return {"status": "error", "error": str(e)}

        song = SongInfo(
            url=url,
            title=info.get("title", "Unknown"),
            duration=info.get("duration"),
            stream_url=info.get("url", ""),
        )

        if not song.stream_url:
            return {"status": "error", "error": "Could not extract audio stream URL"}

        if self._current is not None:
            self._queue.append(song)
            position = len(self._queue)
            return {
                "status": "queued",
                "title": song.title,
                "duration": song.duration,
                "position": position,
            }

        self._current = song
        self._start_playback(song)
        return {
            "status": "playing",
            "title": song.title,
            "duration": song.duration,
        }

    async def skip(self) -> dict:
        """Skip to the next song in the queue."""
        self.voice_client.stop()  # triggers _on_song_end via the after callback
        # _on_song_end will advance the queue, but if we want immediate feedback:
        if not self._queue:
            self._current = None
            return {"status": "stopped", "reason": "queue empty"}
        return {"status": "skipping"}

    async def stop(self) -> dict:
        """Stop playback and clear the queue."""
        self._queue.clear()
        self._current = None
        if self.voice_client.is_playing():
            self.voice_client.stop()
        return {"status": "stopped"}

    def set_volume(self, volume: float) -> float:
        """Set volume (0.0–1.0). Returns the clamped value."""
        self._volume = max(0.0, min(1.0, volume))
        # Update live source if playing
        if self.voice_client.source and isinstance(
            self.voice_client.source, discord.PCMVolumeTransformer
        ):
            self.voice_client.source.volume = self._volume
        return self._volume

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._current is not None

    @property
    def now_playing(self) -> Optional[SongInfo]:
        return self._current

    @property
    def queue(self) -> list[SongInfo]:
        return list(self._queue)

    # -- Internals ------------------------------------------------------------

    async def _extract_info(self, url: str) -> dict:
        """Run yt-dlp extraction in a thread (it's blocking I/O)."""
        import yt_dlp

        def _do():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                return ydl.extract_info(url, download=False)

        return await asyncio.to_thread(_do)

    def _start_playback(self, song: SongInfo) -> None:
        """Create FFmpeg source, wrap with volume transformer, and play."""
        source = discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=self._volume)

        self.voice_client.play(source, after=self._on_song_end)

    def _on_song_end(self, error: Optional[Exception]) -> None:
        """Called from the voice thread when a song finishes."""
        if error:
            print(f"Playback error: {error}")

        if self._queue:
            next_song = self._queue.pop(0)
            self._current = next_song
            self._start_playback(next_song)
        else:
            self._current = None

    def cleanup(self) -> None:
        """Clean up on disconnect."""
        self._queue.clear()
        self._current = None
