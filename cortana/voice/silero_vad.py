"""
Silero VAD - Local Voice Activity Detection.

Uses Silero VAD for accurate, real-time speech detection.
"""

import asyncio
import struct
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Awaitable, Optional
from collections import deque

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    VAD_THRESHOLD,
    VAD_MIN_SPEECH_MS,
    VAD_MIN_SILENCE_MS,
    VAD_WINDOW_SIZE_SAMPLES,
    USE_CUDA,
    AUDIO_THREAD_POOL_SIZE,
)

# Try to import PyTorch
try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    print("⚠️ PyTorch not available - Silero VAD disabled")

# Silero VAD model singleton
_vad_model = None
_vad_utils = None
_vad_device = None
_vad_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_vad_thread_pool() -> ThreadPoolExecutor:
    """Get or create the VAD thread pool."""
    global _vad_thread_pool
    if _vad_thread_pool is None:
        pool_size = AUDIO_THREAD_POOL_SIZE if AUDIO_THREAD_POOL_SIZE > 0 else None
        _vad_thread_pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="vad")
    return _vad_thread_pool


def _detect_device() -> str:
    """Detect the best available device for VAD inference."""
    if not HAS_TORCH:
        return "cpu"
    
    if USE_CUDA and torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        print(f"🎮 CUDA available: {device_name}")
        return "cuda"
    elif USE_CUDA:
        print("⚠️ CUDA requested but not available - using CPU")
    
    return "cpu"


def _load_silero_vad():
    """Load Silero VAD model (singleton pattern)."""
    global _vad_model, _vad_utils, _vad_device
    
    if _vad_model is not None:
        return _vad_model, _vad_utils, _vad_device
    
    if not HAS_TORCH:
        return None, None, "cpu"
    
    try:
        _vad_device = _detect_device()
        
        if _vad_device == "cpu":
            torch.set_num_threads(1)
        
        model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True
        )
        
        model = model.to(_vad_device)
        
        _vad_model = model
        _vad_utils = utils
        
        device_emoji = "🎮" if _vad_device == "cuda" else "💻"
        print(f"✅ Silero VAD loaded on {_vad_device.upper()} {device_emoji}")
        
        return model, utils, _vad_device
    except Exception as e:
        print(f"⚠️ Failed to load Silero VAD: {e}")
        return None, None, "cpu"


class SileroVAD:
    """
    Real-time Voice Activity Detection using Silero VAD.
    
    Processes audio chunks and detects speech start/end events.
    """
    
    def __init__(
        self,
        on_speech_start: Optional[Callable[[], Awaitable[None]]] = None,
        on_speech_end: Optional[Callable[[], Awaitable[None]]] = None,
        threshold: float = VAD_THRESHOLD,
        min_speech_ms: int = VAD_MIN_SPEECH_MS,
        min_silence_ms: int = VAD_MIN_SILENCE_MS,
    ):
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self.min_silence_ms = min_silence_ms
        
        self._model, self._utils, self._device = _load_silero_vad()
        self._available = self._model is not None
        
        self._is_speaking = False
        self._speech_start_samples = 0
        self._silence_start_samples = 0
        self._total_samples = 0
        
        self._audio_buffer = bytearray()
        self._prob_history = deque(maxlen=5)
        self._sample_rate = 16000
        self._window_samples = VAD_WINDOW_SIZE_SAMPLES
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
    
    @property
    def device(self) -> str:
        return self._device if self._device else "cpu"
    
    def reset(self):
        """Reset VAD state."""
        self._is_speaking = False
        self._speech_start_samples = 0
        self._silence_start_samples = 0
        self._total_samples = 0
        self._audio_buffer.clear()
        self._prob_history.clear()
        
        if self._model is not None:
            self._model.reset_states()
    
    def _run_inference_sync(self, audio_tensor: "torch.Tensor") -> float:
        """Run VAD inference synchronously."""
        try:
            if self._device == "cuda":
                audio_tensor = audio_tensor.to(self._device)
            
            with torch.no_grad():
                prob = self._model(audio_tensor, self._sample_rate).item()
            return prob
        except Exception as e:
            print(f"⚠️ VAD inference error: {e}")
            return 0.0
    
    async def process_audio(self, audio_bytes: bytes) -> float:
        """
        Process audio chunk and detect speech activity.
        
        Args:
            audio_bytes: 16kHz mono 16-bit PCM audio
            
        Returns:
            Speech probability (0.0-1.0), or -1 if VAD not available
        """
        if not self._available:
            return -1.0
        
        self._audio_buffer.extend(audio_bytes)
        bytes_per_window = self._window_samples * 2
        
        speech_prob = -1.0
        
        while len(self._audio_buffer) >= bytes_per_window:
            window_bytes = bytes(self._audio_buffer[:bytes_per_window])
            del self._audio_buffer[:bytes_per_window]
            
            samples = struct.unpack(f'<{self._window_samples}h', window_bytes)
            audio_tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0
            
            if self._device == "cuda":
                speech_prob = self._run_inference_sync(audio_tensor)
            else:
                loop = asyncio.get_running_loop()
                speech_prob = await loop.run_in_executor(
                    _get_vad_thread_pool(),
                    self._run_inference_sync,
                    audio_tensor
                )
            
            self._total_samples += self._window_samples
            self._prob_history.append(speech_prob)
            smoothed_prob = sum(self._prob_history) / len(self._prob_history)
            
            await self._update_state(smoothed_prob)
        
        return speech_prob
    
    async def _update_state(self, speech_prob: float):
        """Update speaking state based on VAD probability."""
        is_speech = speech_prob >= self.threshold
        samples_per_ms = self._sample_rate / 1000
        
        if not self._is_speaking:
            if is_speech:
                if self._speech_start_samples == 0:
                    self._speech_start_samples = self._total_samples
                
                speech_duration_ms = (self._total_samples - self._speech_start_samples) / samples_per_ms
                
                if speech_duration_ms >= self.min_speech_ms:
                    self._is_speaking = True
                    self._silence_start_samples = 0
                    print(f"🎙️ VAD: Speech started (prob={speech_prob:.2f})")
                    if self.on_speech_start:
                        await self.on_speech_start()
            else:
                self._speech_start_samples = 0
        
        else:
            if not is_speech:
                if self._silence_start_samples == 0:
                    self._silence_start_samples = self._total_samples
                
                silence_duration_ms = (self._total_samples - self._silence_start_samples) / samples_per_ms
                
                if silence_duration_ms >= self.min_silence_ms:
                    self._is_speaking = False
                    self._speech_start_samples = 0
                    print(f"🔇 VAD: Speech ended (silence={silence_duration_ms:.0f}ms)")
                    if self.on_speech_end:
                        await self.on_speech_end()
            else:
                self._silence_start_samples = 0
