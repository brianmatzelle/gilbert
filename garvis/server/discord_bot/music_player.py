"""
Music player for Discord voice channels.

Uses yt-dlp to extract audio stream URLs and FFmpegPCMAudio to decode them
into PCM for the MixingAudioSource. Supports a simple queue for sequential
playback.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import discord

from .audio_mixer import MixingAudioSource

# yt-dlp options: extract best audio, don't download, be quiet
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    # Avoid geo-restriction issues
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
    duration: Optional[int] = None  # seconds
    stream_url: str = ""


class MusicPlayer:
    """
    Manages music playback through a MixingAudioSource.
    
    Usage:
        player = MusicPlayer(mixer)
        result = await player.play("https://youtube.com/watch?v=...")
        await player.stop()
    """

    def __init__(self, mixer: MixingAudioSource):
        self._mixer = mixer
        self._queue: list[SongInfo] = []
        self._current: Optional[SongInfo] = None
        # Capture the running event loop (set on first async call)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Public API ──────────────────────────────────────────────────────

    async def play(self, url: str) -> dict:
        """
        Play audio from a URL (YouTube, SoundCloud, etc.).
        
        Extracts the stream URL via yt-dlp, then creates an FFmpegPCMAudio
        source and hands it to the mixer. If something is already playing,
        the current song is replaced immediately.
        
        Args:
            url: Any URL supported by yt-dlp.
            
        Returns:
            Dict with status, title, and duration.
        """
        # Capture the running event loop for thread-safe callbacks
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        
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

        # Start playback
        self._current = song
        self._start_ffmpeg(song)

        print(f"🎵 Now playing: {song.title}" + (f" ({song.duration}s)" if song.duration else ""))

        return {
            "status": "playing",
            "title": song.title,
            "duration": song.duration,
        }

    async def queue_song(self, url: str) -> dict:
        """
        Add a song to the queue. If nothing is playing, play immediately.
        
        Returns:
            Dict with status, title, duration, and queue position.
        """
        if self._current is None:
            return await self.play(url)

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

        self._queue.append(song)
        position = len(self._queue)

        print(f"🎵 Queued #{position}: {song.title}")

        return {
            "status": "queued",
            "title": song.title,
            "duration": song.duration,
            "position": position,
        }

    async def stop(self) -> dict:
        """Stop playback and clear the queue."""
        self._queue.clear()
        self._current = None
        self._mixer.stop_music()
        print("⏹️ Music stopped")
        return {"status": "stopped"}

    async def skip(self) -> dict:
        """Skip to the next song in the queue."""
        if not self._queue:
            await self.stop()
            return {"status": "stopped", "reason": "queue empty"}

        next_song = self._queue.pop(0)
        self._current = next_song
        self._start_ffmpeg(next_song)

        print(f"⏭️ Skipped to: {next_song.title}")

        return {
            "status": "playing",
            "title": next_song.title,
            "duration": next_song.duration,
        }

    async def set_volume(self, volume: float) -> dict:
        """Set the music volume (0.0 – 1.0)."""
        volume = max(0.0, min(1.0, volume))
        self._mixer.set_music_volume(volume)
        print(f"🔊 Music volume: {volume:.0%}")
        return {"status": "ok", "volume": volume}

    @property
    def is_playing(self) -> bool:
        return self._current is not None and self._mixer.is_music_playing

    @property
    def now_playing(self) -> Optional[dict]:
        if self._current is None:
            return None
        return {
            "title": self._current.title,
            "duration": self._current.duration,
        }

    @property
    def queue_info(self) -> list[dict]:
        return [
            {"title": s.title, "duration": s.duration}
            for s in self._queue
        ]

    # ── Internal helpers ────────────────────────────────────────────────

    async def _extract_info(self, url: str) -> dict:
        """
        Extract stream info via yt-dlp. Runs in a thread pool because
        yt-dlp's extract_info is blocking (network I/O).
        """
        import yt_dlp

        def _do_extract():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                return ydl.extract_info(url, download=False)

        return await asyncio.to_thread(_do_extract)

    def _start_ffmpeg(self, song: SongInfo) -> None:
        """Create an FFmpegPCMAudio source and hand it to the mixer."""
        source = discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTIONS)

        def _on_music_finished():
            """Called from the voice thread when the song ends."""
            self._current = None
            # Schedule next song on the event loop (we're in voice thread)
            if self._queue:
                try:
                    asyncio.run_coroutine_threadsafe(self.skip(), self._loop)
                except Exception:
                    pass

        self._mixer.set_music_source(source, on_finished=_on_music_finished)

    def cleanup(self) -> None:
        """Clean up resources (call on disconnect)."""
        self._queue.clear()
        self._current = None
        # Don't call mixer.stop_music() here – mixer.cleanup() handles it
