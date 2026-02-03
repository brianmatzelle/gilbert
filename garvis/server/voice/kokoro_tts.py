"""
Local Text-to-Speech using Kokoro TTS.
A more realistic-sounding alternative to Piper TTS.

Kokoro is a neural TTS model ranked #1 on HuggingFace's TTS Arena
among open-weight models. In blind tests, it's often indistinguishable
from commercial solutions like ElevenLabs.

Features:
- Highly realistic, natural-sounding voices
- ~82M parameters, runs on CPU or GPU
- Multiple voice options with different characteristics
- ONNX runtime for efficient inference
"""

import asyncio
import io
import wave
from pathlib import Path
from typing import Callable, Awaitable
from concurrent.futures import ThreadPoolExecutor

import numpy as np

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
    - Multiple voice options (see VOICES.md)
    - No network dependency
    
    Output format: 16-bit PCM WAV at 24000Hz
    The voice pipeline handles any necessary resampling.
    
    Recommended voices:
    - af_heart: Female, highest quality (A grade)
    - af_bella: Female, high quality (A- grade)
    - af_nicole: Female, good quality with headset style (B- grade)
    - am_michael: Male, good quality (C+ grade)
    - am_fenrir: Male, good quality (C+ grade)
    """
    
    # Minimum text length before synthesis (prevents tiny chunks)
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
        """
        Args:
            on_audio: Callback for synthesized audio chunks
            model_path: Path to Kokoro .onnx model file
            voices_path: Path to voices .bin file
            voice: Voice name (e.g., "af_heart", "af_bella", "am_michael")
            speed: Speaking speed (1.0 = normal, lower = faster)
            lang: Language code (e.g., "en-us", "en-gb")
        """
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
        
        # Kokoro outputs 24kHz audio
        self._sample_rate = 24000
    
    async def _load_model(self):
        """Load Kokoro model (lazy loading)."""
        if self._kokoro is not None:
            return
        
        print(f"🔊 Loading Kokoro TTS model: {self.model_path}")
        
        model_path = Path(self.model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Kokoro model not found: {self.model_path}\n"
                "Run setup-local-models.sh to download the model files."
            )
        
        voices_path = Path(self.voices_path)
        if not voices_path.exists():
            raise FileNotFoundError(
                f"Kokoro voices not found: {self.voices_path}\n"
                "Run setup-local-models.sh to download the voice files."
            )
        
        # Load in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        
        def load():
            from kokoro_onnx import Kokoro
            return Kokoro(str(model_path), str(voices_path))
        
        self._kokoro = await loop.run_in_executor(self._executor, load)
        print(f"✅ Kokoro TTS loaded (voice={self.voice}, speed={self.speed})")
    
    async def add_text(self, text: str):
        """
        Add text to be converted to speech.
        Text is buffered and synthesized when we have enough.
        """
        if not self._is_speaking:
            self._is_speaking = True
            self._stop_event.clear()
            self._text_buffer = ""
            
            # Ensure model is loaded
            await self._load_model()
        
        # Buffer the text
        self._text_buffer += text
        
        # Synthesize when we have enough text or hit sentence boundary
        if len(self._text_buffer) >= self.MIN_TEXT_CHARS:
            # Check for natural break points
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
        
        # Synthesize in thread pool
        loop = asyncio.get_event_loop()
        
        def synthesize():
            # Kokoro returns (samples, sample_rate)
            samples, sample_rate = self._kokoro.create(
                text_to_speak,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang
            )
            
            # Convert float32 samples to int16
            samples_int16 = (samples * 32767).astype(np.int16)
            
            # Wrap in WAV format for the pipeline
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)  # 16-bit
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
        
        # Synthesize any remaining text
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


class SimpleKokoroTTS:
    """
    Simplified Kokoro TTS that synthesizes complete text at once.
    
    For when streaming synthesis isn't needed or for simpler integration.
    """
    
    def __init__(
        self,
        model_path: str = KOKORO_MODEL_PATH,
        voices_path: str = KOKORO_VOICES_PATH,
        voice: str = KOKORO_VOICE,
        speed: float = KOKORO_SPEED,
        lang: str = KOKORO_LANG,
    ):
        self.model_path = model_path
        self.voices_path = voices_path
        self.voice = voice
        self.speed = speed
        self.lang = lang
        
        self._kokoro = None
        self._sample_rate = 24000
        self._executor = ThreadPoolExecutor(max_workers=1)
    
    async def load(self):
        """Load the Kokoro model."""
        if self._kokoro is not None:
            return
        
        model_path = Path(self.model_path)
        voices_path = Path(self.voices_path)
        
        if not model_path.exists():
            raise FileNotFoundError(f"Kokoro model not found: {self.model_path}")
        
        if not voices_path.exists():
            raise FileNotFoundError(f"Kokoro voices not found: {self.voices_path}")
        
        loop = asyncio.get_event_loop()
        
        def load():
            from kokoro_onnx import Kokoro
            return Kokoro(str(model_path), str(voices_path))
        
        self._kokoro = await loop.run_in_executor(self._executor, load)
    
    async def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to WAV audio.
        
        Returns:
            WAV audio bytes
        """
        await self.load()
        
        loop = asyncio.get_event_loop()
        
        def synth():
            samples, sample_rate = self._kokoro.create(
                text,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang
            )
            
            # Convert float32 samples to int16
            samples_int16 = (samples * 32767).astype(np.int16)
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(samples_int16.tobytes())
            
            return wav_buffer.getvalue()
        
        return await loop.run_in_executor(self._executor, synth)
    
    @property
    def sample_rate(self) -> int:
        return self._sample_rate
