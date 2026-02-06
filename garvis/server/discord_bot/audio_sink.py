"""
Discord audio sink for capturing user voice input.

Receives Opus-encoded audio from Discord, decodes it, and resamples to 16kHz mono
for the STT pipeline.

THREADING MODEL:
===============
Audio format conversion (48kHz stereo → 16kHz mono) uses numpy array operations,
which are fast enough to run in a thread pool without subprocess overhead.
Previously used pydub (which spawns ffmpeg subprocess) -- replaced with numpy
for ~20x faster conversion with no external process overhead.
"""

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Awaitable, Optional, Dict
from collections import defaultdict

import numpy as np
import discord
from discord.sinks import Sink

# Import config for tunable parameters
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import AUDIO_PROCESS_INTERVAL, AUDIO_THREAD_POOL_SIZE, DISCORD_MUTED_USERS_SET

# Thread pool for CPU-bound audio conversion (shared across instances)
_audio_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_audio_thread_pool() -> ThreadPoolExecutor:
    """Get or create the audio processing thread pool."""
    global _audio_thread_pool
    if _audio_thread_pool is None:
        pool_size = AUDIO_THREAD_POOL_SIZE if AUDIO_THREAD_POOL_SIZE > 0 else None
        _audio_thread_pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="audio")
        print(f"🧵 Audio thread pool created (workers={pool_size or 'default'})")
    return _audio_thread_pool


class GarvisAudioSink(Sink):
    """
    Custom Discord sink that captures voice data from users.
    
    Converts Discord's 48kHz stereo PCM to 16kHz mono PCM for Deepgram.
    Accumulates audio from speaking users and fires callbacks for the voice pipeline.
    
    Features:
    - Per-user audio separation
    - Mute list filtering (ignore specific users/bots)
    - User ID tracking for speaker attribution
    
    Threading: Audio conversion runs in a thread pool to avoid blocking the event loop.
    
    Note: Speaking detection is handled by Silero VAD in the voice pipeline,
    not by timestamp-based silence detection here. This sink just forwards audio.
    """
    
    def __init__(
        self,
        on_audio: Callable[[bytes, int], Awaitable[None]],
        target_user_id: Optional[int] = None,
        muted_user_ids: Optional[set] = None,
        user_lookup: Optional[Callable[[int], Optional[str]]] = None,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """
        Args:
            on_audio: Async callback (pcm_bytes, user_id) for 16kHz mono PCM
            target_user_id: If set, only process audio from this user
            muted_user_ids: Set of user IDs to ignore (muted users/bots)
            user_lookup: Function to get display name from user ID
            event_loop: The asyncio event loop to use for callbacks
        """
        super().__init__()
        self.on_audio = on_audio
        self.target_user_id = target_user_id
        self.muted_user_ids: set = muted_user_ids or set()
        self.user_lookup = user_lookup
        self._loop = event_loop
        
        # Audio buffer per user (accumulate before resampling)
        self._buffers: Dict[int, io.BytesIO] = defaultdict(io.BytesIO)
        
        # Background task for processing audio
        self._process_task: Optional[asyncio.Task] = None
        self._running = False
    
    def write(self, data: bytes, user) -> None:
        """
        Called by discord.py when audio is received from a user.
        
        Args:
            data: Raw PCM audio data (48kHz, 16-bit, stereo)
            user: Either a Discord User object or user_id integer (py-cord passes int)
        """
        # py-cord passes user_id as int, not User object
        user_id = user if isinstance(user, int) else user.id
        
        # Filter to target user if specified
        if self.target_user_id and user_id != self.target_user_id:
            return
        
        # Check mute list (by user ID)
        if user_id in self.muted_user_ids:
            return
        
        # Store audio in buffer
        self._buffers[user_id].write(data)
    
    def add_muted_user(self, user_id: int):
        """Add a user to the mute list."""
        self.muted_user_ids.add(user_id)
    
    def remove_muted_user(self, user_id: int):
        """Remove a user from the mute list."""
        self.muted_user_ids.discard(user_id)
    
    def is_muted(self, user_id: int) -> bool:
        """Check if a user is muted."""
        return user_id in self.muted_user_ids
    
    async def start_processing(self):
        """Start the background audio processing loop."""
        self._running = True
        # Capture the event loop if not already set
        if not self._loop:
            self._loop = asyncio.get_running_loop()
        self._process_task = asyncio.create_task(self._process_loop())
    
    async def stop_processing(self):
        """Stop the background audio processing loop."""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None
    
    async def _process_loop(self):
        """Background loop that processes accumulated audio."""
        # Use configurable value for performance tuning
        PROCESS_INTERVAL = AUDIO_PROCESS_INTERVAL  # how often to process accumulated audio
        
        while self._running:
            try:
                await asyncio.sleep(PROCESS_INTERVAL)
                
                for user_id in list(self._buffers.keys()):
                    buffer = self._buffers[user_id]
                    
                    # Check if we have audio to process
                    if buffer.tell() > 0:
                        # Get the accumulated audio
                        buffer.seek(0)
                        audio_data = buffer.read()
                        buffer.seek(0)
                        buffer.truncate()
                        
                        # Convert from 48kHz stereo to 16kHz mono
                        # Run in thread pool to avoid blocking event loop
                        loop = asyncio.get_running_loop()
                        converted = await loop.run_in_executor(
                            _get_audio_thread_pool(),
                            self._convert_audio,
                            audio_data
                        )
                        if converted:
                            await self.on_audio(converted, user_id)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Audio processing error: {e}")
    
    def _convert_audio(self, data: bytes) -> Optional[bytes]:
        """
        Convert 48kHz stereo PCM to 16kHz mono PCM using numpy.
        
        Discord sends: 48000 Hz, 16-bit signed, stereo (2 channels)
        STT expects:   16000 Hz, 16-bit signed, mono (1 channel)
        
        Uses numpy array operations instead of pydub (which spawned ffmpeg subprocess).
        This is ~20x faster: numpy operates in-process on contiguous memory.
        48kHz / 16kHz = 3, so we simply take every 3rd sample after mono mixdown.
        """
        if not data:
            return None
        
        try:
            # Interpret raw bytes as int16 samples (stereo interleaved: L R L R ...)
            samples = np.frombuffer(data, dtype=np.int16)
            
            # Ensure even number of samples for stereo reshape
            if len(samples) % 2 != 0:
                samples = samples[:len(samples) - 1]
            
            # Reshape to (num_frames, 2) for stereo channels
            stereo = samples.reshape(-1, 2)
            
            # Mix stereo to mono: average left and right channels
            # Use int32 to avoid int16 overflow during addition
            mono = (stereo[:, 0].astype(np.int32) + stereo[:, 1].astype(np.int32)) // 2
            mono = mono.astype(np.int16)
            
            # Downsample 48kHz → 16kHz (ratio 3:1, take every 3rd sample)
            downsampled = mono[::3]
            
            return downsampled.tobytes()
        
        except Exception as e:
            print(f"⚠️ Audio conversion failed: {e}")
            return None
    
    def cleanup(self):
        """Clean up resources."""
        for buffer in self._buffers.values():
            buffer.close()
        self._buffers.clear()
