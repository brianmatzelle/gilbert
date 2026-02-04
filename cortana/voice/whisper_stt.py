"""
Local Speech-to-Text using faster-whisper with CUDA acceleration.

faster-whisper uses CTranslate2 for 4x faster inference than OpenAI Whisper.
"""

import asyncio
import time
import numpy as np
from typing import Callable, Awaitable, Optional
from concurrent.futures import ThreadPoolExecutor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    VAD_MIN_SILENCE_MS,
)


class WhisperSTT:
    """
    Local speech-to-text using faster-whisper.
    
    Features:
    - GPU-accelerated inference via CUDA
    - Integration with Silero VAD for speech detection
    - Low latency local processing
    """
    
    def __init__(
        self,
        on_transcript: Callable[[str, bool], Awaitable[None]],
        on_speech_end: Callable[[str], Awaitable[None]]
    ):
        """
        Args:
            on_transcript: Callback for transcript updates (text, is_final)
            on_speech_end: Callback when speech ends (final transcript)
        """
        self.on_transcript = on_transcript
        self.on_speech_end = on_speech_end
        
        self._model = None
        self._connected = False
        self._audio_buffer: list[bytes] = []
        self._is_speaking = False
        self._last_speech_time = 0.0
        self._silence_check_task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        
        # Audio format: 16kHz, 16-bit, mono
        self._sample_rate = 16000
        self._sample_width = 2
        self._channels = 1
        
        self.current_transcript = ""
    
    async def connect(self):
        """Initialize the Whisper model."""
        if self._model is not None:
            self._connected = True
            return
        
        print("🎤 Loading faster-whisper model...")
        
        loop = asyncio.get_event_loop()
        
        def load_model():
            from faster_whisper import WhisperModel
            return WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
        
        self._model = await loop.run_in_executor(self._executor, load_model)
        self._connected = True
        
        self._silence_check_task = asyncio.create_task(self._silence_check_loop())
        
        print(f"✅ faster-whisper loaded ({WHISPER_MODEL} on {WHISPER_DEVICE})")
    
    async def disconnect(self):
        """Clean up resources."""
        self._connected = False
        
        if self._silence_check_task:
            self._silence_check_task.cancel()
            try:
                await self._silence_check_task
            except asyncio.CancelledError:
                pass
            self._silence_check_task = None
        
        self._audio_buffer.clear()
        self._is_speaking = False
        
        print("🔌 faster-whisper STT disconnected")
    
    async def send_audio(self, audio_bytes: bytes):
        """
        Receive audio data for transcription.
        Expected format: 16kHz, 16-bit PCM, mono
        """
        if not self._connected:
            return
        
        self._audio_buffer.append(audio_bytes)
        self._last_speech_time = time.time()
        
        if not self._is_speaking and len(self._audio_buffer) > 5:
            self._is_speaking = True
    
    def on_vad_speech_start(self):
        """Called by Silero VAD when speech starts."""
        self._is_speaking = True
        self._last_speech_time = time.time()
    
    async def on_vad_speech_end(self):
        """Called by Silero VAD when speech ends - triggers transcription."""
        if not self._is_speaking or not self._audio_buffer:
            return
        
        self._is_speaking = False
        await self._transcribe_buffer()
    
    async def _silence_check_loop(self):
        """Background task to detect silence and trigger transcription."""
        silence_threshold_sec = VAD_MIN_SILENCE_MS / 1000.0
        
        try:
            while self._connected:
                await asyncio.sleep(0.1)
                
                if not self._is_speaking or not self._audio_buffer:
                    continue
                
                time_since_speech = time.time() - self._last_speech_time
                if time_since_speech >= silence_threshold_sec:
                    self._is_speaking = False
                    await self._transcribe_buffer()
        
        except asyncio.CancelledError:
            pass
    
    async def _transcribe_buffer(self):
        """Transcribe accumulated audio buffer."""
        if not self._audio_buffer or not self._model:
            return
        
        audio_data = b''.join(self._audio_buffer)
        self._audio_buffer.clear()
        
        # Skip if too short (less than 0.5 seconds)
        min_samples = int(self._sample_rate * 0.5) * self._sample_width
        if len(audio_data) < min_samples:
            return
        
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        loop = asyncio.get_event_loop()
        
        def transcribe():
            segments, info = self._model.transcribe(
                audio_array,
                beam_size=5,
                language="en",
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200
                }
            )
            return " ".join(segment.text.strip() for segment in segments)
        
        try:
            transcript = await loop.run_in_executor(self._executor, transcribe)
            
            if transcript.strip():
                self.current_transcript = transcript.strip()
                await self.on_transcript(self.current_transcript, True)
                await self.on_speech_end(self.current_transcript)
                self.current_transcript = ""
        
        except Exception as e:
            print(f"❌ Whisper transcription error: {e}")
    
    def force_transcribe(self):
        """Force transcription of current buffer (used for interruptions)."""
        if self._audio_buffer:
            asyncio.create_task(self._transcribe_buffer())
