"""
Local Speech-to-Text using faster-whisper with CUDA acceleration.
Replaces Deepgram for fully local inference.

faster-whisper uses CTranslate2 for 4x faster inference than OpenAI Whisper.
"""

import asyncio
import time
import io
import wave
import numpy as np
from typing import Callable, Awaitable, Optional
from concurrent.futures import ThreadPoolExecutor

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
    - Batched processing for efficiency
    - Integration with existing VAD for speech detection
    - Low latency local processing
    
    Unlike Deepgram's streaming API, this uses a buffer-and-transcribe approach:
    1. Audio is buffered while user speaks (detected by Silero VAD)
    2. When speech ends, the buffer is transcribed in one shot
    3. Results are returned via callbacks
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
        
        # Audio format: 16kHz, 16-bit, mono (same as Deepgram)
        self._sample_rate = 16000
        self._sample_width = 2  # 16-bit = 2 bytes
        self._channels = 1
        
        self.current_transcript = ""
    
    async def connect(self):
        """Initialize the Whisper model (lazy loading for faster startup)."""
        if self._model is not None:
            self._connected = True
            return
        
        print("🎤 Loading faster-whisper model...")
        
        # Load model in thread pool to avoid blocking
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
        
        # Start silence detection task
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
        
        # Clear buffer
        self._audio_buffer.clear()
        self._is_speaking = False
        
        print("🔌 faster-whisper STT disconnected")
    
    async def send_audio(self, audio_bytes: bytes):
        """
        Receive audio data for transcription.
        
        Audio is buffered and transcribed when speech ends.
        Expected format: 16kHz, 16-bit PCM, mono
        """
        if not self._connected:
            return
        
        # Add to buffer
        self._audio_buffer.append(audio_bytes)
        self._last_speech_time = time.time()
        
        # Mark as speaking if we have audio
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
        
        # Transcribe the buffered audio
        await self._transcribe_buffer()
    
    async def _silence_check_loop(self):
        """Background task to detect silence and trigger transcription."""
        silence_threshold_sec = VAD_MIN_SILENCE_MS / 1000.0
        
        try:
            while self._connected:
                await asyncio.sleep(0.1)
                
                if not self._is_speaking or not self._audio_buffer:
                    continue
                
                # Check if silence threshold exceeded
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
        
        # Combine audio chunks
        audio_data = b''.join(self._audio_buffer)
        self._audio_buffer.clear()
        
        # Skip if too short (less than 0.5 seconds)
        min_samples = int(self._sample_rate * 0.5) * self._sample_width
        if len(audio_data) < min_samples:
            return
        
        # Convert to numpy array for faster-whisper
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Run transcription in thread pool
        loop = asyncio.get_event_loop()
        
        def transcribe():
            segments, info = self._model.transcribe(
                audio_array,
                beam_size=5,
                language="en",
                vad_filter=True,  # Use Silero VAD inside whisper too
                vad_parameters={
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200
                }
            )
            # Collect all segment texts
            return " ".join(segment.text.strip() for segment in segments)
        
        try:
            transcript = await loop.run_in_executor(self._executor, transcribe)
            
            if transcript.strip():
                self.current_transcript = transcript.strip()
                
                # Send transcript update (is_final=True for local STT)
                await self.on_transcript(self.current_transcript, True)
                
                # Trigger speech end callback
                await self.on_speech_end(self.current_transcript)
                
                # Reset for next utterance
                self.current_transcript = ""
        
        except Exception as e:
            print(f"❌ Whisper transcription error: {e}")
    
    def force_transcribe(self):
        """Force transcription of current buffer (used for interruptions)."""
        if self._audio_buffer:
            asyncio.create_task(self._transcribe_buffer())
