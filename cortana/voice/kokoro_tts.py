"""
Local Text-to-Speech using Kokoro TTS.

Kokoro is a neural TTS model ranked #1 on HuggingFace's TTS Arena.
Highly realistic, natural-sounding voices.
"""

import asyncio
import io
import wave
from pathlib import Path
from typing import Callable, Awaitable
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    KOKORO_MODEL_PATH,
    KOKORO_VOICES_PATH,
    KOKORO_VOICE,
    KOKORO_SPEED,
    KOKORO_LANG,
)


class KokoroTTS:
    """
    Local text-to-speech using Kokoro.
    
    Features:
    - Highly realistic neural voices
    - Fast synthesis (~100-200ms for short phrases)
    - No network dependency
    
    Output format: 16-bit PCM WAV at 24000Hz
    """
    
    MIN_TEXT_CHARS = 10
    
    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        model_path: str = KOKORO_MODEL_PATH,
        voices_path: str = KOKORO_VOICES_PATH,
        voice: str = KOKORO_VOICE,
        speed: float = KOKORO_SPEED,
        lang: str = KOKORO_LANG,
    ):
        self.on_audio = on_audio
        self.model_path = model_path
        self.voices_path = voices_path
        self.voice = voice
        self.speed = speed
        self.lang = lang
        
        self._kokoro = None
        self._is_speaking = False
        self._stop_event = asyncio.Event()
        self._text_buffer = ""
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._sample_rate = 24000
    
    async def _load_model(self):
        """Load Kokoro model (lazy loading)."""
        if self._kokoro is not None:
            return
        
        print(f"🔊 Loading Kokoro TTS model...")
        
        model_path = Path(self.model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Kokoro model not found: {self.model_path}\n"
                "Please download the model files."
            )
        
        voices_path = Path(self.voices_path)
        if not voices_path.exists():
            raise FileNotFoundError(
                f"Kokoro voices not found: {self.voices_path}\n"
                "Please download the voice files."
            )
        
        loop = asyncio.get_event_loop()
        
        def load():
            from kokoro_onnx import Kokoro
            return Kokoro(str(model_path), str(voices_path))
        
        self._kokoro = await loop.run_in_executor(self._executor, load)
        print(f"✅ Kokoro TTS loaded (voice={self.voice}, speed={self.speed})")
    
    async def add_text(self, text: str):
        """Add text to be converted to speech."""
        if not self._is_speaking:
            self._is_speaking = True
            self._stop_event.clear()
            self._text_buffer = ""
            await self._load_model()
        
        self._text_buffer += text
        
        if len(self._text_buffer) >= self.MIN_TEXT_CHARS:
            if any(self._text_buffer.rstrip().endswith(p) for p in ['.', '!', '?', ',', ';', ':']):
                await self._synthesize_buffer()
    
    async def _synthesize_buffer(self):
        """Synthesize buffered text to audio."""
        if not self._text_buffer.strip() or not self._kokoro:
            return
        
        text_to_speak = self._text_buffer.strip()
        self._text_buffer = ""
        
        if self._stop_event.is_set():
            return
        
        loop = asyncio.get_event_loop()
        
        def synthesize():
            samples, sample_rate = self._kokoro.create(
                text_to_speak,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang
            )
            
            samples_int16 = (samples * 32767).astype(np.int16)
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(samples_int16.tobytes())
            
            return wav_buffer.getvalue()
        
        try:
            audio_data = await loop.run_in_executor(self._executor, synthesize)
            
            if not self._stop_event.is_set() and audio_data:
                await self.on_audio(audio_data)
        
        except Exception as e:
            print(f"❌ Kokoro TTS error: {e}")
    
    async def flush(self):
        """Signal end of text and wait for synthesis to complete."""
        if not self._is_speaking:
            return
        
        if self._text_buffer.strip():
            await self._synthesize_buffer()
        
        self._is_speaking = False
        print("✅ TTS synthesis complete")
    
    async def stop(self):
        """Stop current TTS synthesis immediately."""
        self._stop_event.set()
        self._text_buffer = ""
        self._is_speaking = False
        self._stop_event.clear()
