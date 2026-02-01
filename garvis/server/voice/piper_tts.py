"""
Local Text-to-Speech using Piper TTS.
Replaces ElevenLabs for fully local synthesis.

Piper is a fast, local neural TTS using ONNX Runtime.
It runs on CPU, leaving GPU memory free for LLM and STT.
"""

import asyncio
import io
import wave
from pathlib import Path
from typing import Callable, Awaitable
from concurrent.futures import ThreadPoolExecutor

from config import PIPER_MODEL_PATH


class PiperTTS:
    """
    Local text-to-speech using Piper.
    
    Features:
    - Ultra-fast synthesis on CPU
    - Low latency (~20-50ms for short phrases)
    - High-quality neural voices
    - No network dependency
    
    Output format: 16-bit PCM WAV at model sample rate (typically 22050Hz)
    The voice pipeline handles any necessary resampling.
    """
    
    # Minimum text length before synthesis (prevents tiny chunks)
    MIN_TEXT_CHARS = 10
    
    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        model_path: str = PIPER_MODEL_PATH
    ):
        """
        Args:
            on_audio: Callback for synthesized audio chunks
            model_path: Path to Piper .onnx model file
        """
        self.on_audio = on_audio
        self.model_path = model_path
        
        self._voice = None
        self._synthesizer = None
        self._is_speaking = False
        self._stop_event = asyncio.Event()
        self._text_buffer = ""
        self._executor = ThreadPoolExecutor(max_workers=1)
        
        # Audio parameters (set after model load)
        self._sample_rate = 22050  # Default, updated from model config
    
    async def _load_model(self):
        """Load Piper model (lazy loading)."""
        if self._voice is not None:
            return
        
        print(f"🔊 Loading Piper TTS model: {self.model_path}")
        
        model_path = Path(self.model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        
        config_path = Path(f"{self.model_path}.json")
        if not config_path.exists():
            raise FileNotFoundError(f"Piper config not found: {config_path}")
        
        # Load in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        
        def load():
            # Import here to avoid slow startup
            from piper import PiperVoice
            
            voice = PiperVoice.load(str(model_path), config_path=str(config_path))
            return voice
        
        self._voice = await loop.run_in_executor(self._executor, load)
        
        # Get sample rate from voice config
        self._sample_rate = self._voice.config.sample_rate
        
        print(f"✅ Piper TTS loaded (sample_rate={self._sample_rate})")
    
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
        if not self._text_buffer.strip() or not self._voice:
            return
        
        text_to_speak = self._text_buffer.strip()
        self._text_buffer = ""
        
        if self._stop_event.is_set():
            return
        
        # Synthesize in thread pool
        loop = asyncio.get_event_loop()
        
        def synthesize():
            # Synthesize - returns iterator with audio_int16_bytes
            audio_bytes = b''
            for audio_chunk in self._voice.synthesize(text_to_speak):
                audio_bytes += audio_chunk.audio_int16_bytes
            
            # Wrap in WAV format for the pipeline
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)  # 16-bit
                wav.setframerate(self._sample_rate)
                wav.writeframes(audio_bytes)
            
            return wav_buffer.getvalue()
        
        try:
            audio_data = await loop.run_in_executor(self._executor, synthesize)
            
            if not self._stop_event.is_set() and audio_data:
                await self.on_audio(audio_data)
        
        except Exception as e:
            print(f"❌ Piper TTS error: {e}")
    
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


class SimplePiperTTS:
    """
    Simplified Piper TTS that synthesizes complete text at once.
    
    For when streaming synthesis isn't needed or for simpler integration.
    """
    
    def __init__(self, model_path: str = PIPER_MODEL_PATH):
        self.model_path = model_path
        self._voice = None
        self._sample_rate = 22050
        self._executor = ThreadPoolExecutor(max_workers=1)
    
    async def load(self):
        """Load the Piper model."""
        if self._voice is not None:
            return
        
        model_path = Path(self.model_path)
        config_path = Path(f"{self.model_path}.json")
        
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        
        loop = asyncio.get_event_loop()
        
        def load():
            from piper import PiperVoice
            return PiperVoice.load(str(model_path), config_path=str(config_path))
        
        self._voice = await loop.run_in_executor(self._executor, load)
        
        # Get sample rate from voice config
        self._sample_rate = self._voice.config.sample_rate
    
    async def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to WAV audio.
        
        Returns:
            WAV audio bytes
        """
        await self.load()
        
        loop = asyncio.get_event_loop()
        
        def synth():
            # Synthesize - returns iterator with audio_int16_bytes
            audio_bytes = b''
            for audio_chunk in self._voice.synthesize(text):
                audio_bytes += audio_chunk.audio_int16_bytes
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self._sample_rate)
                wav.writeframes(audio_bytes)
            
            return wav_buffer.getvalue()
        
        return await loop.run_in_executor(self._executor, synth)
    
    @property
    def sample_rate(self) -> int:
        return self._sample_rate
