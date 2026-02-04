"""
Cortana Voice Pipeline - Simplified STT → LLM → TTS orchestration.

Local stack: Whisper STT → Ollama LLM → Kokoro TTS
"""

import asyncio
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Awaitable

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice.whisper_stt import WhisperSTT
from voice.ollama_llm import OllamaLLM
from voice.kokoro_tts import KokoroTTS
from voice.silero_vad import SileroVAD

from config import (
    AUDIO_THREAD_POOL_SIZE,
    ENABLE_BARGE_IN,
    BARGE_IN_MIN_SPEAK_MS,
)

# Audio conversion
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed: {e}")

_tts_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_tts_thread_pool() -> ThreadPoolExecutor:
    """Get or create the TTS audio conversion thread pool."""
    global _tts_thread_pool
    if _tts_thread_pool is None:
        pool_size = AUDIO_THREAD_POOL_SIZE if AUDIO_THREAD_POOL_SIZE > 0 else None
        _tts_thread_pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="tts")
    return _tts_thread_pool


class TurnState:
    """Turn-taking state machine."""
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


class CortanaVoicePipeline:
    """
    Simplified voice pipeline for Cortana.
    
    Flow:
    1. Receive PCM audio (16kHz mono) from Discord
    2. Process through Silero VAD for speech detection
    3. Transcribe with Whisper STT
    4. Generate response with Ollama LLM
    5. Synthesize speech with Kokoro TTS
    6. Output PCM to Discord (48kHz stereo)
    """
    
    @staticmethod
    def _normalize_llm_output(text: str) -> str:
        """Normalize LLM output to remove markers."""
        text = re.sub(r'\[DISCONNECT\]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def __init__(
        self,
        on_audio_output: Callable[[bytes, bool], Awaitable[None]],
        on_transcript: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_status: Optional[Callable[[bool, bool], Awaitable[None]]] = None,
        on_interrupt: Optional[Callable[[], Awaitable[None]]] = None,
        on_disconnect_request: Optional[Callable[[], Awaitable[None]]] = None,
        barge_in_enabled: bool = ENABLE_BARGE_IN,
    ):
        """
        Args:
            on_audio_output: Callback for PCM audio (bytes, flush: bool)
            on_transcript: Optional callback (text, role, is_final)
            on_status: Optional callback (listening, speaking)
            on_interrupt: Optional callback for barge-in
            on_disconnect_request: Optional callback when Cortana wants to disconnect
            barge_in_enabled: Whether barge-in is enabled
        """
        self.on_audio_output = on_audio_output
        self.on_transcript = on_transcript
        self.on_status = on_status
        self.on_interrupt = on_interrupt
        self.on_disconnect_request = on_disconnect_request
        self._barge_in_enabled = barge_in_enabled
        
        self.stt: Optional[WhisperSTT] = None
        self.llm: Optional[OllamaLLM] = None
        self.tts: Optional[KokoroTTS] = None
        self.vad: Optional[SileroVAD] = None
        
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history: list[dict] = []
        self.current_transcript = ""
        
        self._running = False
        self._processing_response = False
        self._pending_transcript = ""
        self._last_vad_trigger_time = 0.0
        self._speaking_start_time = 0.0
        
        self._turn_state = TurnState.LISTENING
        self._state_lock = asyncio.Lock()
        
        self._tts_buffer = io.BytesIO()
    
    def set_barge_in_enabled(self, enabled: bool):
        """Enable or disable barge-in at runtime."""
        self._barge_in_enabled = enabled
        status = "enabled" if enabled else "disabled"
        print(f"🛑 Barge-in {status}")
    
    async def start(self):
        """Initialize and start the pipeline components."""
        self._running = True
        
        # Initialize VAD
        self.vad = SileroVAD(
            on_speech_start=self._on_vad_speech_start,
            on_speech_end=self._on_vad_speech_end,
        )
        
        if self.vad.is_available:
            vad_device = self.vad.device.upper()
            print(f"✅ Silero VAD enabled on {vad_device}")
        
        # Wrapper for STT speech end
        async def _stt_speech_end(transcript: str):
            await self._handle_speech_end(transcript, source="stt")
        
        # Initialize STT (Whisper)
        print("🎤 Using local STT (faster-whisper)")
        self.stt = WhisperSTT(
            on_transcript=self._handle_transcript,
            on_speech_end=_stt_speech_end
        )
        
        # Initialize LLM (Ollama)
        print("🧠 Using Ollama LLM")
        self.llm = OllamaLLM()
        
        # Initialize TTS (Kokoro)
        print("🔊 Using local TTS (Kokoro)")
        self.tts = KokoroTTS(on_audio=self._handle_tts_audio)
        
        # Connect STT
        await self.stt.connect()
        
        print("🎤 Cortana voice pipeline started")
        await self._send_status()
    
    async def stop(self):
        """Clean up pipeline resources."""
        self._running = False
        
        if self.stt:
            await self.stt.disconnect()
        if self.tts:
            await self.tts.stop()
        if self.vad:
            self.vad.reset()
        if self.llm:
            await self.llm.close()
        
        print("🔌 Cortana voice pipeline stopped")
    
    async def interrupt(self):
        """Cancel current response for barge-in."""
        if self._turn_state != TurnState.SPEAKING:
            return
        
        print("🛑 Barge-in detected - interrupting response")
        
        if self.llm:
            self.llm.cancel()
        
        if self.tts:
            await self.tts.stop()
        
        self._tts_buffer.seek(0)
        self._tts_buffer.truncate()
        
        if self.conversation_history and self.conversation_history[-1]["role"] == "user":
            removed_msg = self.conversation_history.pop()
            print(f"🧹 Removed interrupted user message")
        
        self._pending_transcript = ""
        if self.stt:
            self.stt.current_transcript = ""
        
        self._processing_response = False
        self.is_speaking = False
        self.is_listening = True
        
        async with self._state_lock:
            self._turn_state = TurnState.LISTENING
        
        await self._send_status()
        
        if self.on_interrupt:
            await self.on_interrupt()
    
    async def process_audio(self, audio_bytes: bytes, user_id: Optional[int] = None):
        """Process incoming audio from Discord user."""
        if not self._running or not self.stt:
            return
        
        # Process through VAD
        if self.vad and self.vad.is_available:
            await self.vad.process_audio(audio_bytes)
        
        # Forward to STT
        await self.stt.send_audio(audio_bytes)
    
    async def _on_vad_speech_start(self):
        """Called by Silero VAD when speech starts."""
        if self._barge_in_enabled and self._turn_state == TurnState.SPEAKING:
            speaking_duration_ms = (time.time() - self._speaking_start_time) * 1000
            if speaking_duration_ms >= BARGE_IN_MIN_SPEAK_MS:
                await self.interrupt()
                return
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def _on_vad_speech_end(self):
        """Called by Silero VAD when speech ends."""
        if self._processing_response:
            return
        
        async with self._state_lock:
            if self._turn_state != TurnState.LISTENING:
                return
        
        transcript = self._pending_transcript.strip()
        if not transcript:
            return
        
        self._last_vad_trigger_time = time.time()
        self._pending_transcript = ""
        
        if self.stt:
            self.stt.current_transcript = ""
        
        await self._handle_speech_end(transcript, source="vad")
    
    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle transcript updates from STT."""
        self.current_transcript = text
        
        if text.strip():
            self._pending_transcript = text
        
        if self.on_transcript:
            await self.on_transcript(text, "user", is_final)
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def _handle_speech_end(self, final_transcript: str, source: str = "stt"):
        """Handle end of user speech."""
        if not final_transcript.strip():
            return
        
        async with self._state_lock:
            if self._processing_response or self._turn_state != TurnState.LISTENING:
                return
            
            if source == "stt":
                time_since_vad = time.time() - self._last_vad_trigger_time
                if time_since_vad < 5.0:
                    return
            
            self._turn_state = TurnState.PROCESSING
            self._processing_response = True
        
        t_start = time.time()
        
        self.is_listening = False
        await self._send_status()
        
        if self.vad:
            self.vad.reset()
        
        print(f"👤 User: {final_transcript}")
        
        self.conversation_history.append({
            "role": "user",
            "content": final_transcript
        })
        
        # Generate response
        self.is_speaking = True
        self._speaking_start_time = time.time()
        async with self._state_lock:
            self._turn_state = TurnState.SPEAKING
        await self._send_status()
        
        assistant_response = ""
        t_llm_start = time.time()
        t_first_chunk = None
        
        async for chunk in self.llm.stream_response(self.conversation_history):
            assistant_response += chunk
            await self.tts.add_text(chunk)
            if t_first_chunk is None:
                t_first_chunk = time.time()
                print(f"⏱️ Time to first chunk: {(t_first_chunk - t_llm_start)*1000:.0f}ms")
        
        t_llm_end = time.time()
        
        # Check for disconnect marker before normalizing
        wants_disconnect = "[DISCONNECT]" in assistant_response
        
        final_response = self._normalize_llm_output(assistant_response)
        
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            print(f"🤖 Cortana: {final_response}")
            print(f"⏱️ LLM took {(t_llm_end - t_llm_start)*1000:.0f}ms")
            
            if self.on_transcript:
                await self.on_transcript(final_response, "assistant", True)
            
            # Flush TTS
            t_tts_start = time.time()
            await self.tts.flush()
            await self._flush_tts_buffer(flush=True)
            t_tts_end = time.time()
            
            print(f"⏱️ TTS flush took {(t_tts_end - t_tts_start)*1000:.0f}ms")
            print(f"⏱️ Total response time: {(t_tts_end - t_start)*1000:.0f}ms")
            
            if wants_disconnect and self.on_disconnect_request:
                print("🚪 Cortana requested disconnect")
                asyncio.create_task(self._delayed_disconnect())
        
        self.is_speaking = False
        self._processing_response = False
        
        self._pending_transcript = ""
        if self.stt:
            self.stt.current_transcript = ""
        
        async with self._state_lock:
            self._turn_state = TurnState.LISTENING
        await self._send_status()
    
    async def _handle_tts_audio(self, audio_bytes: bytes):
        """Handle TTS audio output."""
        if not self._running or not audio_bytes:
            return
        
        self._tts_buffer.write(audio_bytes)
        
        MIN_BUFFER_BYTES = 16000
        
        if self._tts_buffer.tell() >= MIN_BUFFER_BYTES:
            await self._flush_tts_buffer(flush=False)
    
    async def _flush_tts_buffer(self, flush: bool = False):
        """Convert accumulated TTS audio to PCM and send to Discord."""
        if self._tts_buffer.tell() == 0:
            return
        
        self._tts_buffer.seek(0)
        audio_data = self._tts_buffer.read()
        self._tts_buffer.seek(0)
        self._tts_buffer.truncate()
        
        loop = asyncio.get_running_loop()
        pcm_data = await loop.run_in_executor(
            _get_tts_thread_pool(),
            self._convert_audio_to_pcm,
            audio_data
        )
        if pcm_data:
            await self.on_audio_output(pcm_data, flush)
    
    def _convert_audio_to_pcm(self, audio_data: bytes) -> Optional[bytes]:
        """Convert TTS audio (WAV) to PCM for Discord playback."""
        if not audio_data or not HAS_PYDUB:
            return None
        
        try:
            if audio_data[:4] == b'RIFF':
                audio = AudioSegment.from_wav(io.BytesIO(audio_data))
            else:
                return None
            
            audio = audio.set_channels(2).set_frame_rate(48000).set_sample_width(2)
            return audio.raw_data
        
        except Exception as e:
            print(f"⚠️ Audio to PCM conversion failed: {e}")
            return None
    
    async def _send_status(self):
        """Send current status."""
        if self.on_status:
            await self.on_status(self.is_listening, self.is_speaking)
    
    async def _delayed_disconnect(self):
        """Disconnect after a short delay."""
        await asyncio.sleep(1.0)
        if self.on_disconnect_request:
            await self.on_disconnect_request()
