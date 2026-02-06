"""
Tests for the MixingAudioSource.

Validates PCM mixing, volume ducking, TTS buffer management, and music
source integration without requiring Discord or any network access.

Run:  python -m pytest tests/test_audio_mixer.py -v
      (from the server/ directory)
"""

import importlib
import struct
import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest

# Direct imports that bypass discord_bot/__init__.py (which pulls in the
# full bot + py-cord, not needed for these unit tests).
import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Provide a minimal discord.AudioSource stub so audio_mixer.py can be
# imported without the full py-cord voice extension installed.
import importlib.util

_discord_mod = sys.modules.get("discord")
if _discord_mod is None or not hasattr(_discord_mod, "AudioSource"):
    # Create / patch a lightweight discord stub with AudioSource
    if _discord_mod is None:
        _discord_mod = types.ModuleType("discord")
        sys.modules["discord"] = _discord_mod

    class _AudioSourceStub:
        """Minimal stand-in for discord.AudioSource."""
        def read(self) -> bytes:
            raise NotImplementedError
        def is_opus(self) -> bool:
            return False
        def cleanup(self) -> None:
            pass

    _discord_mod.AudioSource = _AudioSourceStub
    _discord_mod.FFmpegPCMAudio = type("FFmpegPCMAudio", (_AudioSourceStub,), {})

# Now import the module directly by file path to avoid __init__.py chain
_mixer_spec = importlib.util.spec_from_file_location(
    "audio_mixer",
    str(Path(__file__).parent.parent / "discord_bot" / "audio_mixer.py"),
)
_mixer_mod = importlib.util.module_from_spec(_mixer_spec)
_mixer_spec.loader.exec_module(_mixer_mod)

MixingAudioSource = _mixer_mod.MixingAudioSource
FRAME_SIZE = _mixer_mod.FRAME_SIZE
SILENCE_FRAME = _mixer_mod.SILENCE_FRAME


# ── Helpers ─────────────────────────────────────────────────────────────

def make_pcm_frame(value: int = 1000) -> bytes:
    """Create a FRAME_SIZE PCM frame filled with a constant int16 sample."""
    samples = FRAME_SIZE // 2  # 2 bytes per int16 sample
    return struct.pack(f"<{samples}h", *([value] * samples))


def frame_to_array(frame: bytes) -> np.ndarray:
    """Convert a PCM frame to a numpy int16 array."""
    return np.frombuffer(frame, dtype=np.int16)


class FakeAudioSource:
    """
    A fake discord.AudioSource that yields a fixed number of frames,
    then returns b"" (EOF). No dependency on discord module.
    """

    def __init__(self, frame_value: int = 500, num_frames: int = 5):
        self._frame = make_pcm_frame(frame_value)
        self._remaining = num_frames
        self.cleaned_up = False

    def read(self) -> bytes:
        if self._remaining <= 0:
            return b""
        self._remaining -= 1
        return self._frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self.cleaned_up = True


# ── Tests ───────────────────────────────────────────────────────────────

class TestMixerSilence:
    """When nothing is playing, the mixer should output silence."""

    def test_read_returns_silence_when_empty(self):
        mixer = MixingAudioSource()
        frame = mixer.read()
        assert frame == SILENCE_FRAME
        assert len(frame) == FRAME_SIZE

    def test_multiple_reads_stay_silent(self):
        mixer = MixingAudioSource()
        for _ in range(10):
            assert mixer.read() == SILENCE_FRAME


class TestTTSBuffer:
    """TTS write/read/clear operations."""

    def test_write_and_read_single_frame(self):
        mixer = MixingAudioSource()
        pcm = make_pcm_frame(1000)
        mixer.write_tts(pcm)

        assert mixer.has_tts_data()
        frame = mixer.read()
        # Should get our TTS data back (no music, so no mixing)
        assert frame == pcm
        assert not mixer.has_tts_data()

    def test_write_multiple_chunks_reassembled(self):
        """Small TTS chunks are reassembled into full frames."""
        mixer = MixingAudioSource()
        full_frame = make_pcm_frame(2000)

        # Write in 4 quarter-frame chunks
        quarter = FRAME_SIZE // 4
        for i in range(4):
            mixer.write_tts(full_frame[i * quarter : (i + 1) * quarter])

        assert mixer.has_tts_data()
        frame = mixer.read()
        assert frame == full_frame

    def test_partial_frame_padded_with_silence(self):
        """If TTS buffer has less than one frame, pad with silence."""
        mixer = MixingAudioSource()
        # Write only 100 bytes
        mixer.write_tts(b"\x01" * 100)

        frame = mixer.read()
        assert len(frame) == FRAME_SIZE
        # First 100 bytes should be our data, rest silence
        assert frame[:100] == b"\x01" * 100
        assert frame[100:] == b"\x00" * (FRAME_SIZE - 100)

    def test_clear_tts_empties_buffer(self):
        mixer = MixingAudioSource()
        mixer.write_tts(make_pcm_frame(3000))
        mixer.write_tts(make_pcm_frame(3000))
        assert mixer.has_tts_data()

        mixer.clear_tts()
        assert not mixer.has_tts_data()
        assert mixer.read() == SILENCE_FRAME

    def test_write_empty_bytes_is_noop(self):
        mixer = MixingAudioSource()
        mixer.write_tts(b"")
        assert not mixer.has_tts_data()


class TestMusicSource:
    """Music source integration."""

    def test_music_plays_with_volume(self):
        mixer = MixingAudioSource(music_volume=0.5)
        source = FakeAudioSource(frame_value=1000, num_frames=3)
        mixer.set_music_source(source)

        assert mixer.is_music_playing

        frame = mixer.read()
        arr = frame_to_array(frame)
        # All samples should be ~500 (1000 * 0.5)
        expected = 500
        assert np.allclose(arr, expected, atol=1)

    def test_music_source_eof_triggers_cleanup(self):
        mixer = MixingAudioSource()
        source = FakeAudioSource(frame_value=1000, num_frames=1)
        mixer.set_music_source(source)

        # First read consumes the one frame
        mixer.read()
        # Second read hits EOF
        frame = mixer.read()
        assert frame == SILENCE_FRAME
        assert not mixer.is_music_playing
        assert source.cleaned_up

    def test_music_finished_callback_fires(self):
        mixer = MixingAudioSource()
        source = FakeAudioSource(frame_value=1000, num_frames=1)
        callback = MagicMock()
        mixer.set_music_source(source, on_finished=callback)

        mixer.read()  # consume the frame
        mixer.read()  # triggers EOF + callback

        callback.assert_called_once()

    def test_stop_music_cleans_source(self):
        mixer = MixingAudioSource()
        source = FakeAudioSource(frame_value=1000, num_frames=10)
        mixer.set_music_source(source)
        assert mixer.is_music_playing

        mixer.stop_music()
        assert not mixer.is_music_playing
        assert source.cleaned_up

    def test_replace_music_source(self):
        mixer = MixingAudioSource(music_volume=1.0)
        source1 = FakeAudioSource(frame_value=100, num_frames=10)
        source2 = FakeAudioSource(frame_value=200, num_frames=10)

        mixer.set_music_source(source1)
        frame1 = mixer.read()
        arr1 = frame_to_array(frame1)
        assert np.allclose(arr1, 100, atol=1)

        # Replace – source1 should be cleaned up
        mixer.set_music_source(source2)
        assert source1.cleaned_up

        frame2 = mixer.read()
        arr2 = frame_to_array(frame2)
        assert np.allclose(arr2, 200, atol=1)


class TestMixing:
    """TTS + music mixing and volume ducking."""

    def test_mixing_tts_and_music(self):
        """When both are active, TTS is full volume and music is ducked."""
        mixer = MixingAudioSource(music_volume=0.5, duck_volume=0.2)
        source = FakeAudioSource(frame_value=1000, num_frames=5)
        mixer.set_music_source(source)

        tts_frame = make_pcm_frame(2000)
        mixer.write_tts(tts_frame)

        frame = mixer.read()
        arr = frame_to_array(frame)

        # Expected: TTS (2000) + music (1000 * duck 0.2) = 2200
        expected = 2200
        assert np.allclose(arr, expected, atol=1)

    def test_ducking_only_during_tts(self):
        """Music should play at full volume when TTS buffer is empty."""
        mixer = MixingAudioSource(music_volume=0.5, duck_volume=0.1)
        source = FakeAudioSource(frame_value=1000, num_frames=5)
        mixer.set_music_source(source)

        # First read: no TTS → music at music_volume (0.5)
        frame_no_tts = mixer.read()
        arr_no_tts = frame_to_array(frame_no_tts)
        assert np.allclose(arr_no_tts, 500, atol=1)

        # Write TTS then read: TTS present → music ducked to 0.1
        mixer.write_tts(make_pcm_frame(2000))
        frame_with_tts = mixer.read()
        arr_with_tts = frame_to_array(frame_with_tts)
        # 2000 + 1000*0.1 = 2100
        assert np.allclose(arr_with_tts, 2100, atol=1)

        # Next read: TTS exhausted → back to music_volume
        frame_after_tts = mixer.read()
        arr_after_tts = frame_to_array(frame_after_tts)
        assert np.allclose(arr_after_tts, 500, atol=1)

    def test_clipping_prevents_overflow(self):
        """Mixed values should clip to int16 range, not wrap."""
        mixer = MixingAudioSource(music_volume=1.0, duck_volume=1.0)
        source = FakeAudioSource(frame_value=30000, num_frames=3)
        mixer.set_music_source(source)

        mixer.write_tts(make_pcm_frame(30000))
        frame = mixer.read()
        arr = frame_to_array(frame)

        # 30000 + 30000 = 60000 which exceeds int16 max (32767)
        # Should be clipped to 32767
        assert np.all(arr == 32767)


class TestVolumeControl:
    """Volume setters and edge cases."""

    def test_set_music_volume_clamped(self):
        mixer = MixingAudioSource()
        mixer.set_music_volume(1.5)
        assert mixer.music_volume == 1.0

        mixer.set_music_volume(-0.5)
        assert mixer.music_volume == 0.0

    def test_set_duck_volume_clamped(self):
        mixer = MixingAudioSource()
        mixer.set_duck_volume(2.0)
        assert mixer.duck_volume == 1.0

        mixer.set_duck_volume(-1.0)
        assert mixer.duck_volume == 0.0

    def test_volume_1_returns_original(self):
        """apply_volume at 1.0 should return the frame unchanged."""
        frame = make_pcm_frame(12345)
        result = MixingAudioSource._apply_volume(frame, 1.0)
        assert result == frame

    def test_volume_zero_returns_silence(self):
        frame = make_pcm_frame(12345)
        result = MixingAudioSource._apply_volume(frame, 0.0)
        arr = frame_to_array(result)
        assert np.all(arr == 0)


class TestCleanup:
    """Cleanup and stop behavior."""

    def test_cleanup_stops_reads(self):
        mixer = MixingAudioSource()
        mixer.write_tts(make_pcm_frame(1000))
        mixer.cleanup()

        # After cleanup, read returns empty (signals py-cord to stop)
        assert mixer.read() == b""

    def test_cleanup_cleans_music_source(self):
        mixer = MixingAudioSource()
        source = FakeAudioSource(frame_value=1000, num_frames=10)
        mixer.set_music_source(source)
        mixer.cleanup()

        assert source.cleaned_up
        assert not mixer.has_tts_data()


class TestThreadSafety:
    """Basic thread safety: concurrent writes and reads shouldn't crash."""

    def test_concurrent_write_and_read(self):
        mixer = MixingAudioSource()
        errors = []

        def writer():
            try:
                for _ in range(200):
                    mixer.write_tts(make_pcm_frame(500))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    mixer.read()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Thread safety errors: {errors}"

    def test_concurrent_clear_and_read(self):
        mixer = MixingAudioSource()
        errors = []

        def writer_clearer():
            try:
                for i in range(200):
                    mixer.write_tts(make_pcm_frame(500))
                    if i % 10 == 0:
                        mixer.clear_tts()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    frame = mixer.read()
                    assert len(frame) == FRAME_SIZE
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer_clearer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Thread safety errors: {errors}"


class TestMusicPlayerUnit:
    """Unit tests for MusicPlayer logic that don't need network/yt-dlp."""

    @staticmethod
    def _import_music_player():
        """Import MusicPlayer directly by file path (avoids __init__.py chain)."""
        # Ensure discord_bot package stub exists with audio_mixer already loaded
        if "discord_bot" not in sys.modules:
            pkg = types.ModuleType("discord_bot")
            pkg.__path__ = [str(Path(__file__).parent.parent / "discord_bot")]
            sys.modules["discord_bot"] = pkg
        sys.modules["discord_bot.audio_mixer"] = _mixer_mod

        spec = importlib.util.spec_from_file_location(
            "discord_bot.music_player",
            str(Path(__file__).parent.parent / "discord_bot" / "music_player.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_queue_management(self):
        """Test queue add/skip/clear without actual playback."""
        mod = self._import_music_player()
        MusicPlayer = mod.MusicPlayer
        SongInfo = mod.SongInfo

        mixer = MixingAudioSource()
        player = MusicPlayer(mixer)

        # Manually set current + queue (bypass yt-dlp)
        player._current = SongInfo(url="test1", title="Song 1", stream_url="http://fake")
        player._queue = [
            SongInfo(url="test2", title="Song 2", stream_url="http://fake2"),
            SongInfo(url="test3", title="Song 3", stream_url="http://fake3"),
        ]

        assert player.now_playing["title"] == "Song 1"
        assert len(player.queue_info) == 2
        assert player.queue_info[0]["title"] == "Song 2"

    def test_cleanup_clears_state(self):
        mod = self._import_music_player()
        MusicPlayer = mod.MusicPlayer
        SongInfo = mod.SongInfo

        mixer = MixingAudioSource()
        player = MusicPlayer(mixer)
        player._current = SongInfo(url="x", title="X", stream_url="http://x")
        player._queue = [SongInfo(url="y", title="Y", stream_url="http://y")]

        player.cleanup()
        assert player._current is None
        assert len(player._queue) == 0
