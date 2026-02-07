"""
Mixing audio source for Discord voice.

Combines TTS (Garvis speech) and music streams into a single audio output.
Implements volume ducking so Garvis's voice always has priority over music.

The mixer runs as a persistent AudioSource on the voice connection, outputting
silence when idle. Both TTS and music write into thread-safe buffers that the
mixer reads from in its read() method (called every 20ms by py-cord's voice thread).
"""

import threading
from collections import deque
from typing import Optional

import discord
import numpy as np


# Discord PCM frame: 20ms at 48kHz, stereo, 16-bit = 3840 bytes
FRAME_SIZE = 3840
SILENCE_FRAME = b"\x00" * FRAME_SIZE


class MixingAudioSource(discord.AudioSource):
    """
    Audio source that mixes TTS speech and music into a single stream.
    
    - TTS audio is written in variable-size PCM chunks via write_tts().
    - Music audio is read frame-by-frame from an inner AudioSource (FFmpegPCMAudio).
    - When both are active, they are mixed with music ducked to duck_volume.
    - When only music plays, it uses music_volume.
    - When neither has data, outputs silence (keeps the connection alive).
    
    Thread safety: read() is called from py-cord's voice sender thread,
    while write_tts() / set_music_source() are called from asyncio coroutines.
    All shared state is protected by a lock.
    """

    def __init__(
        self,
        music_volume: float = 0.30,
        duck_volume: float = 0.15,
    ):
        self._lock = threading.Lock()

        # TTS buffer: stores raw PCM bytes in a deque of chunks
        self._tts_buffer: deque[bytes] = deque()
        self._tts_offset: int = 0  # Read offset into the first chunk

        # Music source (e.g. FFmpegPCMAudio)
        self._music_source: Optional[discord.AudioSource] = None
        self._music_finished_callback: Optional[callable] = None

        # Volume controls
        self.music_volume: float = music_volume
        self.duck_volume: float = duck_volume

        # Stop flag
        self._stopped = False

    # ── Public API (called from async context) ──────────────────────────

    def write_tts(self, pcm_data: bytes) -> None:
        """Append TTS PCM data to the buffer. Thread-safe."""
        if not pcm_data:
            return
        with self._lock:
            self._tts_buffer.append(pcm_data)

    def clear_tts(self) -> None:
        """Clear all pending TTS audio (used for barge-in). Thread-safe."""
        with self._lock:
            self._tts_buffer.clear()
            self._tts_offset = 0

    def has_tts_data(self) -> bool:
        """Whether there is TTS audio waiting to be played."""
        with self._lock:
            return len(self._tts_buffer) > 0

    def set_music_source(
        self,
        source: Optional[discord.AudioSource],
        on_finished: Optional[callable] = None,
    ) -> None:
        """
        Set (or replace) the music audio source.
        
        Args:
            source: A discord.AudioSource (e.g. FFmpegPCMAudio), or None to clear.
            on_finished: Optional callback invoked (from voice thread) when the
                         source runs out of data.
        """
        with self._lock:
            old = self._music_source
            self._music_source = source
            self._music_finished_callback = on_finished
        # Clean up old source outside the lock
        if old is not None:
            try:
                old.cleanup()
            except Exception:
                pass

    def stop_music(self) -> None:
        """Stop music playback and clean up the source."""
        self.set_music_source(None)

    def set_music_volume(self, volume: float) -> None:
        """Set normal music volume (0.0 – 1.0)."""
        self.music_volume = max(0.0, min(1.0, volume))

    def set_duck_volume(self, volume: float) -> None:
        """Set ducked music volume when TTS is active (0.0 – 1.0)."""
        self.duck_volume = max(0.0, min(1.0, volume))

    @property
    def is_music_playing(self) -> bool:
        """Whether a music source is currently set."""
        with self._lock:
            return self._music_source is not None

    # ── discord.AudioSource interface ───────────────────────────────────

    def read(self) -> bytes:
        """
        Return one 20ms PCM frame (3840 bytes).
        
        Called from py-cord's voice sender thread at ~50 Hz.
        Must never block for long or raise exceptions.
        """
        if self._stopped:
            return b""  # Signal py-cord to stop

        tts_frame = self._read_tts_frame()
        music_frame = self._read_music_frame()

        if tts_frame and music_frame:
            # Mix both, duck music
            return self._mix(tts_frame, music_frame, self.duck_volume)
        elif tts_frame:
            return tts_frame
        elif music_frame:
            return self._apply_volume(music_frame, self.music_volume)
        else:
            return SILENCE_FRAME

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        """Clean up all resources."""
        self._stopped = True
        with self._lock:
            self._tts_buffer.clear()
            self._tts_offset = 0
            src = self._music_source
            self._music_source = None
        if src is not None:
            try:
                src.cleanup()
            except Exception:
                pass

    # ── Internal helpers ────────────────────────────────────────────────

    def _read_tts_frame(self) -> Optional[bytes]:
        """
        Read exactly FRAME_SIZE bytes from the TTS buffer.
        Returns None if insufficient data.
        """
        with self._lock:
            if not self._tts_buffer:
                return None

            # Collect bytes up to FRAME_SIZE
            collected = bytearray()
            needed = FRAME_SIZE

            while needed > 0 and self._tts_buffer:
                chunk = self._tts_buffer[0]
                available = len(chunk) - self._tts_offset
                take = min(available, needed)

                collected.extend(chunk[self._tts_offset : self._tts_offset + take])
                self._tts_offset += take
                needed -= take

                if self._tts_offset >= len(chunk):
                    self._tts_buffer.popleft()
                    self._tts_offset = 0

            if len(collected) < FRAME_SIZE:
                # Pad with silence if we have a partial frame (end of TTS)
                collected.extend(b"\x00" * (FRAME_SIZE - len(collected)))

            return bytes(collected)

    def _read_music_frame(self) -> Optional[bytes]:
        """Read one frame from the music source. Returns None if no source or EOF."""
        with self._lock:
            src = self._music_source
            callback = self._music_finished_callback

        if src is None:
            return None

        try:
            data = src.read()
        except Exception:
            data = b""

        if not data:
            # Music source is exhausted
            with self._lock:
                self._music_source = None
                self._music_finished_callback = None
            try:
                src.cleanup()
            except Exception:
                pass
            # Fire callback (from voice thread – keep it lightweight)
            if callback is not None:
                try:
                    callback()
                except Exception:
                    pass
            return None

        # Pad if source returned a short frame
        if len(data) < FRAME_SIZE:
            data = data + b"\x00" * (FRAME_SIZE - len(data))

        return data

    @staticmethod
    def _mix(tts_frame: bytes, music_frame: bytes, music_vol: float) -> bytes:
        """Mix TTS (full volume) with music (at music_vol) using numpy."""
        tts_arr = np.frombuffer(tts_frame, dtype=np.int16).astype(np.int32)
        music_arr = np.frombuffer(music_frame, dtype=np.int16).astype(np.int32)
        mixed = tts_arr + (music_arr * music_vol).astype(np.int32)
        mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
        return mixed.tobytes()

    @staticmethod
    def _apply_volume(frame: bytes, volume: float) -> bytes:
        """Scale a PCM frame by a volume factor."""
        if volume >= 1.0:
            return frame
        arr = np.frombuffer(frame, dtype=np.int16).astype(np.int32)
        arr = (arr * volume).astype(np.int32)
        arr = np.clip(arr, -32768, 32767).astype(np.int16)
        return arr.tobytes()
