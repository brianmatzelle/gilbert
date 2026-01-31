"""
Discord audio sink for capturing user voice input.

Receives Opus-encoded audio from Discord, decodes it, and resamples to 16kHz mono
for the Deepgram STT pipeline.
"""

import asyncio
import io
import struct
from typing import Callable, Awaitable, Optional, Dict
from collections import defaultdict

import discord
from discord.sinks import Sink

# Import config for tunable parameters
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import AUDIO_PROCESS_INTERVAL, AUDIO_SILENCE_THRESHOLD

def _run_async_from_thread(coro, loop):
    """Safely run an async coroutine from a sync thread context."""
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        # Fallback: try to create a new loop (not ideal but better than crashing)
        try:
            asyncio.run(coro)
        except RuntimeError:
            pass  # No event loop available, skip the callback

# Audio conversion - need pydub for format conversion
# Note: pydub also requires ffmpeg to be installed on the system
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed: {e} - audio conversion will be limited")


class GarvisAudioSink(Sink):
    """
    Custom Discord sink that captures voice data from users.
    
    Converts Discord's 48kHz stereo PCM to 16kHz mono PCM for Deepgram.
    Accumulates audio from speaking users and fires callbacks for the voice pipeline.
    """
    
    def __init__(
        self,
        on_audio: Callable[[bytes, int], Awaitable[None]],
        on_speaking_start: Optional[Callable[[int], Awaitable[None]]] = None,
        on_speaking_end: Optional[Callable[[int], Awaitable[None]]] = None,
        target_user_id: Optional[int] = None,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """
        Args:
            on_audio: Async callback (pcm_bytes, user_id) for 16kHz mono PCM
            on_speaking_start: Optional callback when a user starts speaking
            on_speaking_end: Optional callback when a user stops speaking
            target_user_id: If set, only process audio from this user
            event_loop: The asyncio event loop to use for callbacks
        """
        super().__init__()
        self.on_audio = on_audio
        self.on_speaking_start = on_speaking_start
        self.on_speaking_end = on_speaking_end
        self.target_user_id = target_user_id
        self._loop = event_loop
        
        # Track speaking state per user
        self._speaking: Dict[int, bool] = defaultdict(bool)
        
        # Audio buffer per user (accumulate before resampling)
        self._buffers: Dict[int, io.BytesIO] = defaultdict(io.BytesIO)
        
        # Timestamp of last audio per user (for silence detection)
        self._last_audio_time: Dict[int, float] = {}
        
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
        
        # Track speaking state
        was_speaking = self._speaking[user_id]
        self._speaking[user_id] = True
        
        if not was_speaking and self.on_speaking_start:
            # Called from thread - use thread-safe method
            _run_async_from_thread(self.on_speaking_start(user_id), self._loop)
        
        # Store audio in buffer
        self._buffers[user_id].write(data)
        
        # Update last audio timestamp
        import time
        self._last_audio_time[user_id] = time.time()
    
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
        import time
        # Use configurable values for performance tuning
        # Lower values = faster response but more CPU usage
        SILENCE_THRESHOLD = AUDIO_SILENCE_THRESHOLD  # seconds of silence before considering speech ended
        PROCESS_INTERVAL = AUDIO_PROCESS_INTERVAL  # how often to process accumulated audio
        
        while self._running:
            try:
                await asyncio.sleep(PROCESS_INTERVAL)
                
                current_time = time.time()
                
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
                        converted = self._convert_audio(audio_data)
                        if converted:
                            await self.on_audio(converted, user_id)
                    
                    # Check for silence (speech ended)
                    last_time = self._last_audio_time.get(user_id, current_time)
                    if self._speaking[user_id] and (current_time - last_time) > SILENCE_THRESHOLD:
                        self._speaking[user_id] = False
                        if self.on_speaking_end:
                            await self.on_speaking_end(user_id)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Audio processing error: {e}")
    
    def _convert_audio(self, data: bytes) -> Optional[bytes]:
        """
        Convert 48kHz stereo PCM to 16kHz mono PCM.
        
        Discord sends: 48000 Hz, 16-bit signed, stereo (2 channels)
        Deepgram wants: 16000 Hz, 16-bit signed, mono (1 channel)
        """
        if not data:
            return None
        
        if HAS_PYDUB:
            try:
                # Create AudioSegment from raw PCM
                audio = AudioSegment(
                    data=data,
                    sample_width=2,  # 16-bit
                    frame_rate=48000,
                    channels=2
                )
                
                # Convert to mono 16kHz
                audio = audio.set_channels(1).set_frame_rate(16000)
                
                # Export as raw PCM
                return audio.raw_data
            
            except Exception as e:
                print(f"⚠️ pydub conversion failed: {e}")
                return self._manual_convert(data)
        else:
            return self._manual_convert(data)
    
    def _manual_convert(self, data: bytes) -> Optional[bytes]:
        """
        Manual conversion without pydub.
        Simple downsampling: stereo to mono, then 48kHz to 16kHz (1:3 ratio).
        """
        try:
            # Stereo 16-bit = 4 bytes per sample pair
            # First: convert stereo to mono (average left and right)
            samples = []
            for i in range(0, len(data), 4):
                if i + 4 > len(data):
                    break
                left = struct.unpack('<h', data[i:i+2])[0]
                right = struct.unpack('<h', data[i+2:i+4])[0]
                mono = (left + right) // 2
                samples.append(mono)
            
            # Then: downsample from 48kHz to 16kHz (take every 3rd sample)
            downsampled = samples[::3]
            
            # Pack back to bytes
            return struct.pack(f'<{len(downsampled)}h', *downsampled)
        
        except Exception as e:
            print(f"⚠️ Manual conversion failed: {e}")
            return None
    
    def cleanup(self):
        """Clean up resources."""
        for buffer in self._buffers.values():
            buffer.close()
        self._buffers.clear()
        self._speaking.clear()
        self._last_audio_time.clear()
