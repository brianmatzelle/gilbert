"""
Discord audio sink for capturing user voice input.

Receives Opus-encoded audio from Discord, decodes it, and resamples to 16kHz mono
for the STT pipeline.
"""

import asyncio
import io
import struct
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Awaitable, Optional, Dict
from collections import defaultdict

import discord
from discord.sinks import Sink

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import AUDIO_PROCESS_INTERVAL, AUDIO_THREAD_POOL_SIZE

# Audio conversion
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed: {e} - audio conversion will be limited")

# Thread pool for CPU-bound audio conversion
_audio_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_audio_thread_pool() -> ThreadPoolExecutor:
    """Get or create the audio processing thread pool."""
    global _audio_thread_pool
    if _audio_thread_pool is None:
        pool_size = AUDIO_THREAD_POOL_SIZE if AUDIO_THREAD_POOL_SIZE > 0 else None
        _audio_thread_pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="audio")
        print(f"🧵 Audio thread pool created (workers={pool_size or 'default'})")
    return _audio_thread_pool


class CortanaAudioSink(Sink):
    """
    Custom Discord sink that captures voice data from users.
    
    Converts Discord's 48kHz stereo PCM to 16kHz mono PCM for STT.
    """
    
    def __init__(
        self,
        on_audio: Callable[[bytes, int], Awaitable[None]],
        target_user_id: Optional[int] = None,
        muted_user_ids: Optional[set] = None,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        super().__init__()
        self.on_audio = on_audio
        self.target_user_id = target_user_id
        self.muted_user_ids: set = muted_user_ids or set()
        self._loop = event_loop
        
        self._buffers: Dict[int, io.BytesIO] = defaultdict(io.BytesIO)
        self._process_task: Optional[asyncio.Task] = None
        self._running = False
    
    def write(self, data: bytes, user) -> None:
        """Called by discord.py when audio is received from a user."""
        user_id = user if isinstance(user, int) else user.id
        
        if self.target_user_id and user_id != self.target_user_id:
            return
        
        if user_id in self.muted_user_ids:
            return
        
        self._buffers[user_id].write(data)
    
    def add_muted_user(self, user_id: int):
        """Add a user to the mute list."""
        self.muted_user_ids.add(user_id)
    
    def remove_muted_user(self, user_id: int):
        """Remove a user from the mute list."""
        self.muted_user_ids.discard(user_id)
    
    async def start_processing(self):
        """Start the background audio processing loop."""
        self._running = True
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
        while self._running:
            try:
                await asyncio.sleep(AUDIO_PROCESS_INTERVAL)
                
                for user_id in list(self._buffers.keys()):
                    buffer = self._buffers[user_id]
                    
                    if buffer.tell() > 0:
                        buffer.seek(0)
                        audio_data = buffer.read()
                        buffer.seek(0)
                        buffer.truncate()
                        
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
        """Convert 48kHz stereo PCM to 16kHz mono PCM."""
        if not data:
            return None
        
        if HAS_PYDUB:
            try:
                audio = AudioSegment(
                    data=data,
                    sample_width=2,
                    frame_rate=48000,
                    channels=2
                )
                audio = audio.set_channels(1).set_frame_rate(16000)
                return audio.raw_data
            
            except Exception as e:
                print(f"⚠️ pydub conversion failed: {e}")
                return self._manual_convert(data)
        else:
            return self._manual_convert(data)
    
    def _manual_convert(self, data: bytes) -> Optional[bytes]:
        """Manual conversion without pydub."""
        try:
            samples = []
            for i in range(0, len(data), 4):
                if i + 4 > len(data):
                    break
                left = struct.unpack('<h', data[i:i+2])[0]
                right = struct.unpack('<h', data[i+2:i+4])[0]
                mono = (left + right) // 2
                samples.append(mono)
            
            downsampled = samples[::3]
            return struct.pack(f'<{len(downsampled)}h', *downsampled)
        
        except Exception as e:
            print(f"⚠️ Manual conversion failed: {e}")
            return None
    
    def cleanup(self):
        """Clean up resources."""
        for buffer in self._buffers.values():
            buffer.close()
        self._buffers.clear()
