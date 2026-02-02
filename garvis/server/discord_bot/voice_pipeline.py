"""
Discord-adapted voice pipeline.

Orchestrates STT → LLM → TTS for Discord voice channels.
Supports both cloud APIs and local models for low-latency inference.

Cloud (default):
    Deepgram STT → Claude LLM → ElevenLabs TTS

Local (faster, requires setup-local-models.sh):
    faster-whisper STT → llama.cpp LLM → Piper TTS

AUDIO FORMAT CONVERSIONS:
========================

    Discord Input (from users speaking):
    - 48kHz, stereo, 16-bit PCM
    - Converted to 16kHz mono by audio_sink.py
    - Sent to STT for transcription

    TTS Output:
    - Cloud (ElevenLabs): MP3 @ 44.1kHz → convert to PCM
    - Local (Piper): WAV @ 22kHz → convert to PCM

    Discord Output (Garvis speaking):
    - 48kHz, stereo, 16-bit PCM
    - Played via discord.PCMAudio

WHY BUFFER AUDIO BEFORE CONVERTING?
===================================
MP3 uses frames (~400-1000 bytes each). If we try to decode partial frames,
pydub/ffmpeg will fail or produce glitchy audio. By buffering 16KB (~10-40 frames),
we ensure we always have complete frames to decode.

The bot.py also buffers converted PCM (~48KB, ~250ms) before starting playback
to avoid gaps between chunks.

VOICE ACTIVITY DETECTION & TURN DETECTION:
==========================================
Speech detection is handled by two systems:
1. Silero VAD - Local, fast VAD for speech start/end (no network latency)
2. STT endpointing - Server/local VAD that fires speech_final events

SEMANTIC TURN DETECTION:
=======================
To avoid cutting users off mid-thought, we use semantic heuristics:
- If utterance ends with conjunctions/fillers ("but", "um", "and"...),
  we wait for extended silence (1200ms) before responding
- A turn state machine prevents race conditions between VAD and STT
- This balances responsiveness with natural conversation flow

Research shows 500ms silence threshold is the developer consensus sweet spot.
Incomplete utterance detection prevents 70-80% of premature interruptions.
"""

import asyncio
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Awaitable, Union

# Import the Garvis voice components (using as a library!)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cloud providers
from voice.deepgram_stt import DeepgramSTT
from voice.claude_llm import ClaudeLLM
from voice.elevenlabs_tts import ElevenLabsTTS

# Local providers
from voice.whisper_stt import WhisperSTT
from voice.local_llm import LocalLLM
from voice.piper_tts import PiperTTS
from voice.kokoro_tts import KokoroTTS

# OpenClaw integration
from voice.openclaw_llm import OpenClawLLM

# Common components
from voice.silero_vad import SileroVAD
from config import (
    INCOMPLETE_UTTERANCE_PATTERNS, 
    INCOMPLETE_UTTERANCE_EXTENDED_SILENCE_MS, 
    VAD_MIN_SILENCE_MS,
    AUDIO_THREAD_POOL_SIZE,
    ENABLE_BARGE_IN,
    BARGE_IN_MIN_SPEAK_MS,
    USE_LOCAL_LLM,
    USE_LOCAL_STT,
    USE_LOCAL_TTS,
    USE_OPENCLAW,
    USE_KOKORO_TTS,
    DISCORD_SPEAKER_ATTRIBUTION,
    ASSISTANT_MODE,
    WAKE_WORD,
)

# Audio conversion - pydub requires ffmpeg
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed: {e}")

# Thread pool for CPU-bound MP3→PCM conversion
_tts_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_tts_thread_pool() -> ThreadPoolExecutor:
    """Get or create the TTS audio conversion thread pool."""
    global _tts_thread_pool
    if _tts_thread_pool is None:
        pool_size = AUDIO_THREAD_POOL_SIZE if AUDIO_THREAD_POOL_SIZE > 0 else None
        _tts_thread_pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="tts")
    return _tts_thread_pool


class TurnState:
    """Turn-taking state machine to prevent race conditions."""
    LISTENING = "listening"      # Waiting for user to speak
    PROCESSING = "processing"    # User spoke, processing response
    SPEAKING = "speaking"        # Bot is responding


class DiscordVoicePipeline:
    """
    Voice pipeline adapted for Discord voice channels.
    
    Flow:
    1. Receive PCM audio (16kHz mono) from Discord via audio sink
    2. Process through Silero VAD for speaking state detection
    3. Stream to Deepgram for real-time transcription
    4. On speech_final from Deepgram, send transcript to Claude
    5. Stream Claude response to Eleven Labs TTS (WebSocket API)
    6. TTS outputs PCM directly (48kHz stereo) - no conversion needed!
    
    Speaker Attribution:
    - Tracks which user is currently speaking based on audio source
    - Includes speaker name in messages to LLM ("Brian: Hello Garvis")
    - Enables personalized responses and per-user memory with OpenClaw
    
    Turn Detection Strategy:
    - Uses Silero VAD (local) + Deepgram endpointing (server) as dual triggers
    - Applies semantic heuristics to detect incomplete utterances
    - Extends silence timeout when user appears mid-thought (e.g., "but...", "um...")
    - State machine prevents race conditions between VAD and STT
    """
    
    @staticmethod
    def _normalize_transcript(text: str) -> str:
        """Normalize transcript to fix common STT misinterpretations."""
        text = re.sub(r'\bjarvis\b', 'Garvis', text, flags=re.IGNORECASE)
        text = re.sub(r'\btravis\b', 'Garvis', text, flags=re.IGNORECASE)
        return text
    
    @staticmethod
    def _normalize_llm_output(text: str) -> str:
        """Normalize LLM output to remove markers."""
        text = re.sub(r'\[DISPLAY_STREAM:[^\]]+\]', '', text)
        text = re.sub(r'\[DISCONNECT\]', '', text)  # Remove disconnect marker
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    @staticmethod
    def _appears_incomplete(text: str) -> bool:
        """
        Check if utterance appears incomplete based on trailing patterns.
        
        This is a semantic heuristic to prevent cutting off users mid-thought.
        Examples that should return True:
        - "I want to order a pizza but"
        - "Let me think um"
        - "The answer is, you know,"
        """
        if not text:
            return False
        
        text_lower = text.lower().strip()
        
        # Check for trailing patterns that suggest more speech is coming
        for pattern in INCOMPLETE_UTTERANCE_PATTERNS:
            if text_lower.endswith(pattern):
                return True
            # Also check with punctuation stripped
            if text_lower.rstrip('.,!?').endswith(pattern):
                return True
        
        # Check for very short utterances (likely incomplete)
        word_count = len(text_lower.split())
        if word_count <= 2 and not text_lower.endswith(('?', '!', '.')):
            # Short utterances without terminal punctuation may be incomplete
            # But allow common short commands like "yes", "no", "stop", "help"
            short_complete = {'yes', 'no', 'stop', 'help', 'thanks', 'okay', 'ok', 'sure', 'bye', 'hi', 'hello'}
            if text_lower.rstrip('.,!?') not in short_complete:
                return True
        
        return False
    
    def __init__(
        self,
        on_audio_output: Callable[[bytes, bool], Awaitable[None]],
        on_transcript: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_status: Optional[Callable[[bool, bool], Awaitable[None]]] = None,
        on_interrupt: Optional[Callable[[], Awaitable[None]]] = None,
        on_disconnect_request: Optional[Callable[[], Awaitable[None]]] = None,
        user_lookup: Optional[Callable[[int], Optional[str]]] = None,
        barge_in_enabled: bool = ENABLE_BARGE_IN,
        assistant_mode: bool = ASSISTANT_MODE,
    ):
        """
        Args:
            on_audio_output: Callback for PCM audio (bytes, flush: bool) to play in Discord (48kHz stereo)
            on_transcript: Optional callback (text, role, is_final)
            on_status: Optional callback (listening, speaking)
            on_interrupt: Optional callback when barge-in interruption occurs (to stop Discord playback)
            on_disconnect_request: Optional callback when Garvis wants to disconnect from voice
            user_lookup: Optional callback to get display name from user ID (for speaker attribution)
            barge_in_enabled: Whether barge-in (interruption) is enabled
            assistant_mode: Whether wake word is required (only respond to "Garvis...")
        """
        self.on_audio_output = on_audio_output
        self.on_transcript = on_transcript
        self.on_status = on_status
        self.on_interrupt = on_interrupt
        self.on_disconnect_request = on_disconnect_request
        self.user_lookup = user_lookup
        self._barge_in_enabled = barge_in_enabled
        self._assistant_mode = assistant_mode
        
        self.stt: Optional[Union[DeepgramSTT, WhisperSTT]] = None
        self.llm: Optional[Union[ClaudeLLM, LocalLLM, OpenClawLLM]] = None
        self.tts: Optional[Union[ElevenLabsTTS, PiperTTS, KokoroTTS]] = None
        self.vad: Optional[SileroVAD] = None
        
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history: list[dict] = []
        self.current_transcript = ""
        
        self._running = False
        self._processing_response = False  # Prevent double-triggering
        self._pending_transcript = ""  # Latest transcript from STT
        self._last_vad_trigger_time = 0.0  # When VAD last triggered a response
        self._speaking_start_time = 0.0  # When bot started speaking (for barge-in delay)
        
        # Speaker attribution
        self._current_speaker_id: Optional[int] = None  # User ID of current speaker
        self._current_speaker_name: Optional[str] = None  # Display name of current speaker
        self._use_speaker_attribution = DISCORD_SPEAKER_ATTRIBUTION
        
        # Turn state machine
        self._turn_state = TurnState.LISTENING
        self._state_lock = asyncio.Lock()  # Prevent race conditions
        
        # Incomplete utterance handling
        self._incomplete_utterance_detected = False
        self._extended_silence_task: Optional[asyncio.Task] = None
        
        # Audio buffer for TTS conversion (MP3 for cloud, WAV for local)
        self._tts_buffer = io.BytesIO()
        
        # Track which providers we're using
        self._use_local_stt = USE_LOCAL_STT
        self._use_local_llm = USE_LOCAL_LLM
        self._use_local_tts = USE_LOCAL_TTS
        self._use_openclaw = USE_OPENCLAW
        self._use_kokoro_tts = USE_KOKORO_TTS
    
    def set_barge_in_enabled(self, enabled: bool):
        """Enable or disable barge-in (interruption) at runtime."""
        self._barge_in_enabled = enabled
        status = "enabled" if enabled else "disabled"
        print(f"🛑 Barge-in {status}")
    
    def set_assistant_mode(self, enabled: bool):
        """Enable or disable assistant mode (wake word required) at runtime."""
        self._assistant_mode = enabled
        status = "enabled" if enabled else "disabled"
        print(f"🎯 Assistant mode {status}")
    
    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool and return the result string."""
        print(f"🔧 Executing tool: {tool_name} with args: {args}")
        
        try:
            if tool_name == "ping":
                import json
                return json.dumps({
                    "status": "pong",
                    "service": "Garvis Discord Bot"
                })
            
            else:
                return f"Unknown tool: {tool_name}"
        
        except Exception as e:
            print(f"❌ Tool execution error: {e}")
            return f"Error executing tool: {str(e)}"
    
    async def start(self):
        """Initialize and start the pipeline components."""
        self._running = True
        
        # Initialize Silero VAD for local speaking detection
        self.vad = SileroVAD(
            on_speech_start=self._on_vad_speech_start,
            on_speech_end=self._on_vad_speech_end,
        )
        
        if self.vad.is_available:
            vad_device = self.vad.device.upper()
            device_emoji = "🎮" if self.vad.device == "cuda" else "💻"
            print(f"✅ Silero VAD enabled on {vad_device} {device_emoji}")
        else:
            print("⚠️ Silero VAD not available, using STT VAD only")
        
        # Wrapper to tag STT's speech_end calls with source
        async def _stt_speech_end(transcript: str):
            await self._handle_speech_end(transcript, source="stt")
        
        # Initialize STT (Speech-to-Text)
        if self._use_local_stt:
            print("🎤 Using local STT (faster-whisper)")
            self.stt = WhisperSTT(
                on_transcript=self._handle_transcript,
                on_speech_end=_stt_speech_end
            )
        else:
            print("🎤 Using cloud STT (Deepgram)")
            self.stt = DeepgramSTT(
                on_transcript=self._handle_transcript,
                on_speech_end=_stt_speech_end
            )
        
        # Initialize LLM
        # Priority: OpenClaw > Local > Cloud (Claude)
        if self._use_openclaw:
            print("🧠 Using OpenClaw agent engine (persistent memory + tools)")
            self.llm = OpenClawLLM()
        elif self._use_local_llm:
            print("🧠 Using local LLM (llama.cpp + Qwen2.5)")
            self.llm = LocalLLM()
        else:
            print("🧠 Using cloud LLM (Claude)")
            self.llm = ClaudeLLM()
        
        # Initialize TTS
        # Priority: Cloud (ElevenLabs) > Local Kokoro > Local Piper
        if self._use_local_tts:
            if self._use_kokoro_tts:
                print("🔊 Using local TTS (Kokoro - realistic voice)")
                self.tts = KokoroTTS(on_audio=self._handle_tts_audio)
            else:
                print("🔊 Using local TTS (Piper)")
                self.tts = PiperTTS(on_audio=self._handle_tts_audio)
        else:
            print("🔊 Using cloud TTS (ElevenLabs - persistent connection)")
            self.tts = ElevenLabsTTS(on_audio=self._handle_tts_audio)
        
        # Connect to STT
        await self.stt.connect()
        
        # Connect TTS (ElevenLabs uses persistent WebSocket for lower latency)
        if isinstance(self.tts, ElevenLabsTTS):
            await self.tts.connect()
        
        print("🎤 Discord voice pipeline started")
        await self._send_status()
    
    async def stop(self):
        """Clean up pipeline resources."""
        self._running = False
        
        if self.stt:
            await self.stt.disconnect()
        if self.tts:
            await self.tts.stop()
            # Disconnect persistent TTS connections (ElevenLabs)
            if hasattr(self.tts, 'disconnect'):
                await self.tts.disconnect()
        if self.vad:
            self.vad.reset()
        
        print("🔌 Discord voice pipeline stopped")
    
    async def speak_proactively(self, text: str) -> bool:
        """
        Make Garvis speak proactively without waiting for user input.
        
        This allows Garvis to initiate conversations, greet users, or
        speak up whenever he wants to.
        
        Args:
            text: What Garvis should say (natural spoken language)
            
        Returns:
            True if speech was successful, False otherwise
        """
        if not self._running or not self.tts:
            print("⚠️ Cannot speak proactively - pipeline not running")
            return False
        
        # Don't interrupt if already speaking
        if self._turn_state == TurnState.SPEAKING:
            print("⚠️ Cannot speak proactively - already speaking")
            return False
        
        print(f"🗣️ Garvis speaking proactively: {text[:50]}...")
        
        try:
            # Set speaking state
            self.is_speaking = True
            self._speaking_start_time = time.time()
            async with self._state_lock:
                self._turn_state = TurnState.SPEAKING
            await self._send_status()
            
            # Add to conversation history as assistant message
            self.conversation_history.append({
                "role": "assistant",
                "content": text
            })
            
            # Send transcript callback
            if self.on_transcript:
                await self.on_transcript(text, "assistant", True)
            
            # Stream text to TTS
            await self.tts.add_text(text)
            
            # Flush TTS
            await self.tts.flush()
            
            # Flush any remaining buffer
            await self._flush_tts_buffer(flush=True)
            
            print("✅ Proactive speech complete")
            
            # Reset state
            self.is_speaking = False
            async with self._state_lock:
                self._turn_state = TurnState.LISTENING
            await self._send_status()
            
            return True
            
        except Exception as e:
            print(f"❌ Proactive speech failed: {e}")
            self.is_speaking = False
            async with self._state_lock:
                self._turn_state = TurnState.LISTENING
            return False
    
    async def interrupt(self):
        """
        Cancel current response for barge-in interruption.
        
        Called when the user starts speaking while the bot is still responding.
        This allows natural conversation flow where users can interrupt.
        
        IMPORTANT: This also cleans up conversation_history to prevent the LLM
        from seeing the interrupted exchange. The last user message is removed
        since we didn't complete a proper response to it.
        """
        # Only interrupt if we're actually speaking
        if self._turn_state != TurnState.SPEAKING:
            return
        
        print("🛑 Barge-in detected - interrupting response")
        
        # Cancel LLM streaming FIRST to stop compute
        if self.llm:
            self.llm.cancel()
        
        # Stop TTS immediately
        if self.tts:
            await self.tts.stop()
        
        # Clear TTS buffer
        self._tts_buffer.seek(0)
        self._tts_buffer.truncate()
        
        # ===== BARGE-IN FIX: Clean up conversation history =====
        # Remove the last user message since we didn't complete a response to it
        # This prevents the LLM from seeing incomplete exchanges and wasting compute
        # on context that was never properly addressed
        if self.conversation_history and self.conversation_history[-1]["role"] == "user":
            removed_msg = self.conversation_history.pop()
            print(f"🧹 Removed interrupted user message: '{removed_msg['content'][:50]}...'")
        
        # Clear any pending transcripts accumulated during bot speech
        self._pending_transcript = ""
        if self.stt:
            self.stt.current_transcript = ""
        
        # Reset state to allow new processing
        self._processing_response = False
        self.is_speaking = False
        self.is_listening = True
        
        async with self._state_lock:
            self._turn_state = TurnState.LISTENING
        
        await self._send_status()
        
        # Notify bot.py to stop Discord audio playback
        if self.on_interrupt:
            await self.on_interrupt()
    
    async def process_audio(self, audio_bytes: bytes, user_id: Optional[int] = None):
        """
        Process incoming audio from Discord user.
        
        Args:
            audio_bytes: 16kHz mono PCM audio
            user_id: Optional user ID of the speaker (for attribution)
        """
        if not self._running or not self.stt:
            return
        
        # Track current speaker for attribution
        if user_id is not None and user_id != self._current_speaker_id:
            self._current_speaker_id = user_id
            # Look up display name if we have a lookup function
            if self.user_lookup:
                self._current_speaker_name = self.user_lookup(user_id)
            else:
                self._current_speaker_name = None
        
        # Process through local VAD for speaking state (non-blocking)
        if self.vad and self.vad.is_available:
            await self.vad.process_audio(audio_bytes)
        
        # Check if STT connection is still alive, reconnect if needed
        if not self.stt._connected:
            # Avoid reconnection spam - only reconnect if not already trying
            if not getattr(self, '_reconnecting', False):
                self._reconnecting = True
                print("🔄 Reconnecting to Deepgram STT...")
                try:
                    # Clean up old connection first
                    await self.stt.disconnect()
                    # Reset transcript state
                    self.stt.current_transcript = ""
                    await self.stt.connect()
                    print("✅ Deepgram STT reconnected")
                except Exception as e:
                    print(f"❌ Failed to reconnect to Deepgram: {e}")
                    return
                finally:
                    self._reconnecting = False
            else:
                return  # Skip this audio chunk while reconnecting
        
        # Forward audio to Deepgram STT
        await self.stt.send_audio(audio_bytes)
    
    async def _on_vad_speech_start(self):
        """Called by Silero VAD when speech starts."""
        # Cancel extended silence task if user starts speaking again
        if self._extended_silence_task and not self._extended_silence_task.done():
            self._extended_silence_task.cancel()
            self._incomplete_utterance_detected = False
            print("🎙️ User resumed speaking - cancelled extended silence wait")
        
        # Barge-in: If bot is speaking and user starts talking, interrupt the response
        # Only allow barge-in after minimum speaking time to avoid echo/feedback triggers
        if self._barge_in_enabled and self._turn_state == TurnState.SPEAKING:
            speaking_duration_ms = (time.time() - self._speaking_start_time) * 1000
            if speaking_duration_ms >= BARGE_IN_MIN_SPEAK_MS:
                await self.interrupt()
                return  # Don't update listening state - interrupt() handles it
            # else: Ignore - too soon, likely echo/feedback
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def _on_vad_speech_end(self):
        """
        Called by Silero VAD when speech ends.
        
        This triggers faster than Deepgram's speech_final since it's local
        (no network latency). We use the pending transcript from Deepgram.
        
        Semantic Turn Detection:
        - If the utterance appears incomplete (ends with "but", "um", etc.),
          we wait for an extended silence period before triggering a response.
        - This prevents cutting off users mid-thought while maintaining responsiveness.
        """
        # Don't trigger if already processing
        if self._processing_response:
            return
        
        # Check turn state - only process if we're in LISTENING state
        async with self._state_lock:
            if self._turn_state != TurnState.LISTENING:
                return
        
        transcript = self._pending_transcript.strip()
        if not transcript:
            # No transcript yet - let Deepgram's speech_final handle it
            return
        
        # Check if utterance appears incomplete (semantic heuristic)
        if self._appears_incomplete(transcript):
            print(f"🔄 Incomplete utterance detected: '{transcript[-30:]}...' - waiting for extended silence")
            self._incomplete_utterance_detected = True
            
            # Cancel any existing extended silence task
            if self._extended_silence_task and not self._extended_silence_task.done():
                self._extended_silence_task.cancel()
            
            # Start extended silence timer - only trigger if silence continues
            self._extended_silence_task = asyncio.create_task(
                self._wait_for_extended_silence(transcript)
            )
            return
        
        # Reset incomplete utterance flag
        self._incomplete_utterance_detected = False
        
        # Record when VAD triggered - used to block Deepgram's speech_final
        self._last_vad_trigger_time = time.time()
        
        # Clear pending transcript and trigger response
        self._pending_transcript = ""
        
        # Also clear Deepgram's accumulated transcript to prevent double-trigger
        if self.stt:
            self.stt.current_transcript = ""
        
        await self._handle_speech_end(transcript, source="vad")
    
    async def _wait_for_extended_silence(self, transcript: str):
        """
        Wait for extended silence before triggering response for incomplete utterances.
        
        If the user starts speaking again during this window, the task is cancelled
        and we continue accumulating their speech.
        """
        try:
            # Wait for extended silence period
            extended_wait_ms = INCOMPLETE_UTTERANCE_EXTENDED_SILENCE_MS - VAD_MIN_SILENCE_MS
            await asyncio.sleep(extended_wait_ms / 1000.0)
            
            # Check if we're still in a valid state to respond
            if self._processing_response:
                return
            
            async with self._state_lock:
                if self._turn_state != TurnState.LISTENING:
                    return
            
            # Use the latest transcript (may have been updated during wait)
            final_transcript = self._pending_transcript.strip() or transcript
            
            print(f"⏰ Extended silence elapsed - triggering response for: '{final_transcript[:50]}...'")
            
            # Record when VAD triggered
            self._last_vad_trigger_time = time.time()
            
            # Clear pending transcript
            self._pending_transcript = ""
            self._incomplete_utterance_detected = False
            
            if self.stt:
                self.stt.current_transcript = ""
            
            await self._handle_speech_end(final_transcript, source="vad-extended")
            
        except asyncio.CancelledError:
            # User started speaking again - good, we didn't interrupt them
            print("🔄 Extended silence cancelled - user continued speaking")
    
    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle transcript updates from Deepgram."""
        text = self._normalize_transcript(text)
        self.current_transcript = text
        
        # Store the latest transcript for VAD-triggered responses
        if text.strip():
            self._pending_transcript = text
        
        if self.on_transcript:
            await self.on_transcript(text, "user", is_final)
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    def _check_wake_word(self, transcript: str) -> tuple[bool, str]:
        """
        Check if transcript starts with the wake word.
        
        Returns:
            (has_wake_word, cleaned_transcript)
            - has_wake_word: True if wake word was found
            - cleaned_transcript: Transcript with wake word stripped (if found)
        """
        transcript_lower = transcript.lower().strip()
        wake_word_lower = WAKE_WORD.lower()
        
        # Check for wake word at the start (with some flexibility)
        # "garvis", "garvis,", "garvis ", "hey garvis", etc.
        patterns = [
            f"{wake_word_lower} ",
            f"{wake_word_lower},",
            f"{wake_word_lower}.",
            f"{wake_word_lower}?",
            f"{wake_word_lower}!",
            f"hey {wake_word_lower}",
            f"hi {wake_word_lower}",
            f"ok {wake_word_lower}",
            f"okay {wake_word_lower}",
        ]
        
        for pattern in patterns:
            if transcript_lower.startswith(pattern):
                # Find where the actual command starts
                prefix_len = len(pattern)
                cleaned = transcript[prefix_len:].lstrip(" ,.:!?")
                return True, cleaned
        
        # Also check if transcript is JUST the wake word (user said "Garvis" and paused)
        if transcript_lower.rstrip(" ,.:!?") == wake_word_lower:
            return True, ""  # Wake word only, no command yet
        
        return False, transcript
    
    async def _handle_speech_end(self, final_transcript: str, source: str = "deepgram"):
        """Handle end of user speech (from VAD or Deepgram's speech_final)."""
        if not final_transcript.strip():
            return
        
        # Use state machine to prevent race conditions
        async with self._state_lock:
            # Prevent double-triggering from concurrent calls
            if self._processing_response or self._turn_state != TurnState.LISTENING:
                return
            
            # If Deepgram triggers shortly after VAD, skip it (VAD already handled it)
            if source == "deepgram":
                time_since_vad = time.time() - self._last_vad_trigger_time
                if time_since_vad < 5.0:  # 5 second guard window
                    return
            
            # Transition to PROCESSING state
            self._turn_state = TurnState.PROCESSING
            self._processing_response = True
        
        t_start = time.time()
        
        final_transcript = self._normalize_transcript(final_transcript)
        
        # ===== ASSISTANT MODE: Check for wake word =====
        # If assistant mode is enabled, only respond when user says "Garvis..."
        # This saves LLM compute by not processing unaddressed speech
        if self._assistant_mode:
            has_wake_word, cleaned_transcript = self._check_wake_word(final_transcript)
            
            if not has_wake_word:
                # No wake word - ignore this input entirely (don't send to LLM)
                print(f"🔇 Assistant mode: Ignoring '{final_transcript[:50]}...' (no wake word)")
                async with self._state_lock:
                    self._turn_state = TurnState.LISTENING
                self._processing_response = False
                return
            
            # Wake word found - use cleaned transcript
            if cleaned_transcript:
                final_transcript = cleaned_transcript
                print(f"🎯 Wake word detected, processing: '{final_transcript[:50]}...'")
            else:
                # User just said "Garvis" with no command - acknowledge and wait
                print(f"🎯 Wake word only - waiting for command...")
                async with self._state_lock:
                    self._turn_state = TurnState.LISTENING
                self._processing_response = False
                # TODO: Could play a "listening" sound here
                return
        
        self.is_listening = False
        await self._send_status()
        
        # Reset VAD state for next utterance
        if self.vad:
            self.vad.reset()
        
        # Format message with speaker attribution if enabled
        if self._use_speaker_attribution and self._current_speaker_name:
            # Include speaker name in the message so LLM knows who said it
            message_content = f"{self._current_speaker_name}: {final_transcript}"
            print(f"👤 {self._current_speaker_name}: {final_transcript}")
        else:
            message_content = final_transcript
            print(f"👤 User: {final_transcript}")
        
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": message_content
        })
        
        # Get Claude response
        self.is_speaking = True
        self._speaking_start_time = time.time()  # Track for barge-in delay
        async with self._state_lock:
            self._turn_state = TurnState.SPEAKING
        await self._send_status()
        
        assistant_response = ""
        t_llm_start = time.time()
        t_first_chunk = None
        
        # Stream Claude's response directly to TTS for minimum latency
        # This uses the simple streaming method (no tools) for fastest response
        async for chunk in self.llm.stream_response(self.conversation_history):
            assistant_response += chunk
            # Stream each chunk to TTS immediately
            await self.tts.add_text(chunk)
            if t_first_chunk is None:
                t_first_chunk = time.time()
                print(f"⏱️ Time to first chunk: {(t_first_chunk - t_llm_start)*1000:.0f}ms")
        
        t_llm_end = time.time()
        
        # Finalize response
        final_response = self._normalize_llm_output(assistant_response)
        
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            print(f"🤖 Garvis: {final_response}")
            print(f"⏱️ LLM took {(t_llm_end - t_llm_start)*1000:.0f}ms")
            
            if self.on_transcript:
                await self.on_transcript(final_response, "assistant", True)
            
            # Flush remaining TTS audio
            t_tts_start = time.time()
            await self.tts.flush()
            
            # Flush any remaining TTS buffer
            await self._flush_tts_buffer(flush=True)
            
            t_tts_end = time.time()
            
            print(f"⏱️ TTS flush took {(t_tts_end - t_tts_start)*1000:.0f}ms")
            print(f"⏱️ Total response time: {(t_tts_end - t_start)*1000:.0f}ms")
            
            # Check if Garvis wants to disconnect
            if "[DISCONNECT]" in assistant_response and self.on_disconnect_request:
                print("🚪 Garvis requested disconnect")
                # Schedule disconnect after response completes
                asyncio.create_task(self._delayed_disconnect())
        
        self.is_speaking = False
        self._processing_response = False  # Allow new triggers
        
        # Clear any stale transcripts to prevent reprocessing
        self._pending_transcript = ""
        if self.stt:
            self.stt.current_transcript = ""
        
        async with self._state_lock:
            self._turn_state = TurnState.LISTENING
        await self._send_status()
    
    async def _handle_tts_audio(self, audio_bytes: bytes):
        """
        Handle TTS audio output from ElevenLabs (MP3) or Piper (WAV).
        
        We accumulate audio data and convert to PCM for Discord.
        """
        if not self._running:
            return
        
        if not audio_bytes:
            return
        
        # Accumulate audio data
        self._tts_buffer.write(audio_bytes)
        
        # Convert and send when we have enough data
        # MP3 frames are ~400-1000 bytes, WAV chunks can be any size
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
        
        # Convert audio to PCM for Discord (48kHz stereo 16-bit)
        # Run in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        pcm_data = await loop.run_in_executor(
            _get_tts_thread_pool(),
            self._convert_audio_to_pcm,
            audio_data
        )
        if pcm_data:
            await self.on_audio_output(pcm_data, flush)
    
    def _convert_audio_to_pcm(self, audio_data: bytes) -> Optional[bytes]:
        """
        Convert TTS audio (MP3 or WAV) to PCM for Discord playback.
        Runs in thread pool - do not call from async context directly.
        
        Discord expects: 48000 Hz, 16-bit signed, stereo
        """
        if not audio_data or not HAS_PYDUB:
            if not HAS_PYDUB:
                print("⚠️ pydub not available - cannot convert TTS audio")
            return None
        
        try:
            # Detect format from header
            # WAV starts with "RIFF", MP3 with 0xFF 0xFB or ID3
            if audio_data[:4] == b'RIFF':
                # WAV format (from Piper)
                audio = AudioSegment.from_wav(io.BytesIO(audio_data))
            else:
                # MP3 format (from ElevenLabs)
                audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
            
            # Convert to Discord format
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
        """Disconnect after a short delay (to let the goodbye message finish)."""
        await asyncio.sleep(1.0)  # Wait for audio to finish playing
        if self.on_disconnect_request:
            await self.on_disconnect_request()
