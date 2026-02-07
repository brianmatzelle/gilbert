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
    MAX_CONVERSATION_TURNS,
    CONVERSATION_RESPONSE_DELAY_MS,
    CONVERSATION_MAX_WAIT_MS,
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
        """Normalize LLM output to remove markers and gateway artifacts."""
        text = re.sub(r'\[DISPLAY_STREAM:[^\]]+\]', '', text)
        text = re.sub(r'\[DISCONNECT\]', '', text)  # Remove disconnect marker
        # Remove MEDIA: file paths from OpenClaw gateway TTS artifacts
        # e.g. "MEDIA:/tmp/tts-EX9KNi/voice-1770505554459.mp3"
        text = re.sub(r'MEDIA:\S+', '', text)
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
        music_player=None,
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
            music_player: Optional MusicPlayer instance for music playback tools
        """
        self.on_audio_output = on_audio_output
        self.on_transcript = on_transcript
        self.on_status = on_status
        self.on_interrupt = on_interrupt
        self.on_disconnect_request = on_disconnect_request
        self.user_lookup = user_lookup
        self._barge_in_enabled = barge_in_enabled
        self._assistant_mode = assistant_mode
        self._music_player = music_player
        
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
        
        # ===== Multi-speaker support =====
        # Per-user silence tracking: detect when individual users stop speaking,
        # even if others continue.  This is the key fix for group conversations
        # where the global VAD never fires speech_end.
        self._user_last_audio: dict[int, float] = {}          # user_id → timestamp of last audio
        self._users_speaking: set[int] = set()                 # user IDs currently producing audio
        self._user_silence_tasks: dict[int, asyncio.Task] = {} # per-user silence timers
        
        # Conversation response timer: gives a short window for multiple speakers
        # to finish before Garvis responds
        self._response_timer_task: Optional[asyncio.Task] = None
        self._first_transcript_time: float = 0.0  # When transcript accumulation started this cycle
        
        # Audio buffer for TTS conversion (MP3 for cloud, WAV for local)
        self._tts_buffer = io.BytesIO()
        
        # Performance instrumentation timestamps
        self._t_first_tts_audio = 0.0      # When first TTS audio chunk arrives
        self._t_speech_end = 0.0           # When speech end was triggered (VAD/STT)
        self._tts_audio_received = False   # Whether we've received any TTS audio this turn
        self._convert_time_total_ms = 0.0  # Accumulated audio conversion time per response
        
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
        import json as _json
        print(f"🔧 Executing tool: {tool_name} with args: {args}")
        
        try:
            if tool_name == "ping":
                return _json.dumps({
                    "status": "pong",
                    "service": "Garvis Discord Bot"
                })
            
            # ── Music playback tools ────────────────────────────────
            elif tool_name == "play_music":
                if not self._music_player:
                    return _json.dumps({"status": "error", "error": "Music playback not available"})
                result = await self._music_player.play(args.get("url", ""))
                return _json.dumps(result)
            
            elif tool_name == "stop_music":
                if not self._music_player:
                    return _json.dumps({"status": "error", "error": "Music playback not available"})
                result = await self._music_player.stop()
                return _json.dumps(result)
            
            elif tool_name == "set_music_volume":
                if not self._music_player:
                    return _json.dumps({"status": "error", "error": "Music playback not available"})
                result = await self._music_player.set_volume(float(args.get("volume", 0.3)))
                return _json.dumps(result)
            
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
            # When Silero VAD is available, tell Whisper to skip its internal silence
            # detection polling loop -- VAD will trigger transcription directly via
            # on_vad_speech_end(), saving ~600ms of redundant silence detection
            has_external_vad = self.vad is not None and self.vad.is_available
            self.stt = WhisperSTT(
                on_transcript=self._handle_transcript,
                on_speech_end=_stt_speech_end,
                use_external_vad=has_external_vad,
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
        
        # Clean up per-user silence tasks and response timer
        for task in self._user_silence_tasks.values():
            if not task.done():
                task.cancel()
        self._user_silence_tasks.clear()
        if self._response_timer_task and not self._response_timer_task.done():
            self._response_timer_task.cancel()
        
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
    
    async def process_text_request(self, text: str, speaker_name: str = None, max_tokens: int = 4096) -> str:
        """
        Process a text request from a Discord text channel.
        
        Sends the text through the LLM with tool support, streams the response
        to TTS (so Garvis speaks it aloud), and returns the full text response.
        
        This is used by the !r command to allow text channel interaction.
        OpenClaw's gateway-level tools (like web_fetch) handle URL fetching
        transparently, so requests like "read this paper at <url>" work
        automatically.
        
        Args:
            text: The user's text message
            speaker_name: Display name of the user who sent the message
            max_tokens: Maximum tokens in LLM response (higher for text requests)
            
        Returns:
            The full text response from the LLM
        """
        if not self._running or not self.llm or not self.tts:
            return ""
        
        # Don't interrupt if currently speaking
        if self._turn_state == TurnState.SPEAKING:
            return ""
        
        # Acquire processing lock
        async with self._state_lock:
            if self._turn_state != TurnState.LISTENING:
                return ""
            self._turn_state = TurnState.PROCESSING
            self._processing_response = True
        
        try:
            # Format message with speaker attribution
            if speaker_name:
                message_content = f"{speaker_name}: {text}"
            else:
                message_content = text
            
            # Add context note for text channel requests - this overrides the
            # "1-2 sentences max" voice constraint from the system prompt so
            # OpenClaw can provide full-length responses when appropriate.
            # IMPORTANT: We explicitly tell the agent NOT to use its own TTS/audio
            # tools — Garvis has a local TTS pipeline that will speak the text.
            message_content = (
                "[Text channel request — respond as fully as needed, "
                "longer responses are fine. If asked to read or recite content, "
                "return the FULL TEXT directly in your response. "
                "Do NOT use any TTS, audio generation, or text-to-speech tools. "
                "Do NOT output MEDIA: file paths. "
                "Garvis has his own voice pipeline that will speak your text aloud.]\n"
                + message_content
            )
            
            print(f"📝 Text request from {speaker_name or 'unknown'}: {text[:80]}...")
            
            # Add user message to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": message_content
            })
            
            # Set speaking state
            self.is_speaking = True
            self._speaking_start_time = time.time()
            async with self._state_lock:
                self._turn_state = TurnState.SPEAKING
            await self._send_status()
            
            assistant_response = ""
            t_start = time.time()
            
            # Reset per-response performance counters
            self._tts_audio_received = False
            self._t_first_tts_audio = 0.0
            self._convert_time_total_ms = 0.0
            
            # Stream LLM response with tool support
            async for event in self.llm.stream_response_with_tools(
                self.conversation_history,
                self._execute_tool,
                max_tokens=max_tokens,
            ):
                if event.get("type") == "text":
                    chunk = event["content"]
                    assistant_response += chunk
                    # Stream to TTS for voice output
                    await self.tts.add_text(chunk)
                elif event.get("type") == "tool_use":
                    print(f"🔧 Tool call: {event.get('name')} ({event.get('input', {})})")
                elif event.get("type") == "tool_result":
                    print(f"🔧 Tool result: {event.get('name')} → {str(event.get('result', ''))[:100]}")
            
            # Finalize response
            final_response = self._normalize_llm_output(assistant_response)
            
            if final_response:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_response
                })
                
                # Trim conversation history
                max_messages = MAX_CONVERSATION_TURNS * 2
                if len(self.conversation_history) > max_messages:
                    self.conversation_history = self.conversation_history[-max_messages:]
                
                print(f"🤖 Garvis (text request): {final_response[:100]}...")
                
                if self.on_transcript:
                    await self.on_transcript(final_response, "assistant", True)
                
                # Flush TTS
                await self.tts.flush()
                await self._flush_tts_buffer(flush=True)
                
                t_end = time.time()
                print(f"⏱️ Text request total: {(t_end - t_start)*1000:.0f}ms")
                
                # Check if Garvis wants to disconnect
                if "[DISCONNECT]" in assistant_response and self.on_disconnect_request:
                    asyncio.create_task(self._delayed_disconnect())
            
            return final_response
        
        finally:
            # Always reset state
            self.is_speaking = False
            self._processing_response = False
            self._pending_transcript = ""
            if self.stt:
                self.stt.current_transcript = ""
            
            self._first_transcript_time = 0.0
            if self._response_timer_task and not self._response_timer_task.done():
                self._response_timer_task.cancel()
            
            async with self._state_lock:
                self._turn_state = TurnState.LISTENING
            await self._send_status()
    
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
        
        # Reset multi-speaker state
        self._first_transcript_time = 0.0
        self._users_speaking.clear()
        for task in self._user_silence_tasks.values():
            if not task.done():
                task.cancel()
        self._user_silence_tasks.clear()
        if self._response_timer_task and not self._response_timer_task.done():
            self._response_timer_task.cancel()
        
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
        
        # ===== Per-user silence tracking (multi-speaker fix) =====
        # Track when each user last sent audio.  When a specific user goes
        # silent for VAD_MIN_SILENCE_MS, we know *they* finished speaking --
        # even if other users are still talking.  This is the parallel trigger
        # path that complements the global VAD (which only fires when ALL
        # audio stops).
        if user_id is not None:
            self._user_last_audio[user_id] = time.time()
            self._users_speaking.add(user_id)
            
            # Cancel existing silence timer for this user and start a new one
            old_task = self._user_silence_tasks.get(user_id)
            if old_task and not old_task.done():
                old_task.cancel()
            
            # Capture speaker name now (may change by the time timer fires)
            speaker_name = self._current_speaker_name
            self._user_silence_tasks[user_id] = asyncio.create_task(
                self._on_user_silence(user_id, speaker_name)
            )
        
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
        
        For local Whisper STT: triggers transcription directly instead of relying
        on Whisper's internal silence polling (~600ms faster).
        
        Semantic Turn Detection:
        - If the utterance appears incomplete (ends with "but", "um", etc.),
          we wait for an extended silence period before triggering a response.
        - This prevents cutting off users mid-thought while maintaining responsiveness.
        """
        # Record speech end time for performance instrumentation
        self._t_speech_end = time.time()
        
        # Don't trigger if already processing
        if self._processing_response:
            return
        
        # Check turn state - only process if we're in LISTENING state
        async with self._state_lock:
            if self._turn_state != TurnState.LISTENING:
                return
        
        # For local Whisper STT: trigger transcription directly via VAD callback
        # This bypasses Whisper's internal silence detection polling (~600ms savings)
        # Whisper's on_speech_end callback will then call _handle_speech_end
        if isinstance(self.stt, WhisperSTT):
            await self.stt.on_vad_speech_end()
            return
        
        # For cloud STT (Deepgram): use pending transcript from streaming
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
    
    # ===== Multi-speaker conversation support =====
    # These methods provide an alternative trigger path for group conversations
    # where the global VAD never fires speech_end because someone is always talking.
    
    async def _on_user_silence(self, user_id: int, speaker_name: Optional[str]):
        """
        Per-user silence detection.
        
        Fires when a specific user hasn't sent audio for VAD_MIN_SILENCE_MS.
        In a group conversation this means *that* user finished their thought,
        even if others are still talking.
        
        Two outcomes:
        - ALL users silent → respond immediately (same as current 1-on-1 path)
        - Some users still talking → start a response delay timer so Garvis
          waits briefly for the conversation to settle before jumping in
        """
        try:
            await asyncio.sleep(VAD_MIN_SILENCE_MS / 1000.0)
        except asyncio.CancelledError:
            return  # User resumed speaking – timer reset by process_audio
        
        # Mark this user as no longer speaking
        self._users_speaking.discard(user_id)
        
        # Don't trigger if already processing or not in listening state
        if self._processing_response or self._turn_state != TurnState.LISTENING:
            return
        
        transcript = self._pending_transcript.strip()
        if not transcript:
            return
        
        if not self._users_speaking:
            # ── All users are now silent ──
            # Let the existing VAD path handle this case (it fires at roughly
            # the same time).  This avoids duplicating the incomplete-utterance
            # logic.  If for some reason the VAD doesn't fire (no trailing
            # audio from Discord), the response timer below acts as a backstop.
            
            # Start a short backstop timer in case the global VAD doesn't fire
            if not self._response_timer_task or self._response_timer_task.done():
                self._response_timer_task = asyncio.create_task(
                    self._conversation_response_timer(source="all-silent-backstop")
                )
        else:
            # ── Other users still talking ──
            # This is the key multi-speaker path.  Start a response timer
            # so Garvis waits a beat for the conversation to settle, then
            # responds even though others haven't stopped.
            if not self._response_timer_task or self._response_timer_task.done():
                names = speaker_name or str(user_id)
                print(f"👤 {names} finished speaking, others still active – starting response timer ({CONVERSATION_RESPONSE_DELAY_MS}ms)")
                self._response_timer_task = asyncio.create_task(
                    self._conversation_response_timer(source="multi-speaker")
                )
    
    async def _conversation_response_timer(self, source: str = "timer"):
        """
        Delayed response trigger for multi-speaker conversations.
        
        Waits CONVERSATION_RESPONSE_DELAY_MS then triggers a response with
        whatever transcript has accumulated, bypassing the global VAD.
        """
        try:
            await asyncio.sleep(CONVERSATION_RESPONSE_DELAY_MS / 1000.0)
        except asyncio.CancelledError:
            return
        
        # Re-check state (may have changed during sleep)
        if self._processing_response or self._turn_state != TurnState.LISTENING:
            return
        
        transcript = self._pending_transcript.strip()
        if not transcript:
            return
        
        print(f"⏰ Conversation response timer fired ({source}) – responding to: '{transcript[:60]}...'")
        
        # Record trigger time (blocks redundant Deepgram/VAD triggers)
        self._last_vad_trigger_time = time.time()
        self._t_speech_end = time.time()
        
        # Clear transcript state for next cycle
        self._pending_transcript = ""
        self._first_transcript_time = 0.0
        if self.stt:
            self.stt.current_transcript = ""
        
        await self._handle_speech_end(transcript, source=f"conversation-{source}")
    
    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle transcript updates from STT (Deepgram or Whisper)."""
        text = self._normalize_transcript(text)
        self.current_transcript = text
        
        # Store the latest transcript for VAD-triggered responses
        if text.strip():
            self._pending_transcript = text
            
            # Track when transcript accumulation started this cycle
            # (reset to 0 after each response in _handle_speech_end)
            if self._first_transcript_time == 0.0:
                self._first_transcript_time = time.time()
            
            # ===== Max-wait backstop =====
            # If transcript has been accumulating for too long without a
            # response (nobody ever shuts up), force a response now.
            # This is the hard cap that guarantees Garvis eventually speaks.
            if (
                self._first_transcript_time > 0
                and not self._processing_response
                and self._turn_state == TurnState.LISTENING
            ):
                elapsed_ms = (time.time() - self._first_transcript_time) * 1000
                if elapsed_ms >= CONVERSATION_MAX_WAIT_MS:
                    transcript = self._pending_transcript.strip()
                    if transcript:
                        print(f"⏰ Max wait ({CONVERSATION_MAX_WAIT_MS}ms) exceeded – forcing response")
                        
                        self._last_vad_trigger_time = time.time()
                        self._t_speech_end = time.time()
                        self._pending_transcript = ""
                        self._first_transcript_time = 0.0
                        if self.stt:
                            self.stt.current_transcript = ""
                        
                        # Cancel any pending response timer
                        if self._response_timer_task and not self._response_timer_task.done():
                            self._response_timer_task.cancel()
                        
                        await self._handle_speech_end(transcript, source="max-wait")
                        return  # Don't fall through to the callback below
        
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
        
        # Reset VAD state for next utterance – but only when all users are
        # actually silent.  In multi-speaker conversations we may start a
        # response while others are still talking; resetting the VAD mid-speech
        # would cause a false speech_start → spurious barge-in.
        if self.vad and not self._users_speaking:
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
        
        # Get LLM response
        self.is_speaking = True
        self._speaking_start_time = time.time()  # Track for barge-in delay
        async with self._state_lock:
            self._turn_state = TurnState.SPEAKING
        await self._send_status()
        
        assistant_response = ""
        t_llm_start = time.time()
        t_first_chunk = None
        
        # Reset per-response performance counters
        self._tts_audio_received = False
        self._t_first_tts_audio = 0.0
        self._convert_time_total_ms = 0.0
        
        # Stream LLM response with tool support
        # Text chunks stream directly to TTS for low latency.
        # If the LLM calls a tool (e.g. play_music), _execute_tool() runs
        # and the result is fed back to the LLM for a follow-up response.
        async for event in self.llm.stream_response_with_tools(
            self.conversation_history,
            self._execute_tool,
        ):
            if event.get("type") == "text":
                chunk = event["content"]
                assistant_response += chunk
                # Stream each text chunk to TTS immediately
                await self.tts.add_text(chunk)
                if t_first_chunk is None:
                    t_first_chunk = time.time()
                    print(f"⏱️ LLM TTFC: {(t_first_chunk - t_llm_start)*1000:.0f}ms")
            elif event.get("type") == "tool_use":
                print(f"🔧 Tool call: {event.get('name')} ({event.get('input', {})})")
            elif event.get("type") == "tool_result":
                print(f"🔧 Tool result: {event.get('name')} → {str(event.get('result', ''))[:100]}")
        
        t_llm_end = time.time()
        
        # Finalize response
        final_response = self._normalize_llm_output(assistant_response)
        
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            # Trim conversation history to prevent unbounded growth
            # Keep only the last MAX_CONVERSATION_TURNS turns (pairs of user+assistant)
            max_messages = MAX_CONVERSATION_TURNS * 2
            if len(self.conversation_history) > max_messages:
                self.conversation_history = self.conversation_history[-max_messages:]
            
            print(f"🤖 Garvis: {final_response}")
            print(f"⏱️ LLM total: {(t_llm_end - t_llm_start)*1000:.0f}ms")
            
            if self.on_transcript:
                await self.on_transcript(final_response, "assistant", True)
            
            # Flush remaining TTS audio
            t_tts_start = time.time()
            await self.tts.flush()
            
            # Flush any remaining TTS buffer
            await self._flush_tts_buffer(flush=True)
            
            t_tts_end = time.time()
            
            # ===== Performance Summary =====
            print(f"⏱️ TTS flush: {(t_tts_end - t_tts_start)*1000:.0f}ms")
            if self._t_first_tts_audio > 0:
                ttfb = (self._t_first_tts_audio - t_start) * 1000
                print(f"⏱️ TTFB (speech_end → first audio): {ttfb:.0f}ms")
            if self._convert_time_total_ms > 0:
                print(f"⏱️ Audio conversion total: {self._convert_time_total_ms:.0f}ms")
            print(f"⏱️ Total response: {(t_tts_end - t_start)*1000:.0f}ms")
            
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
        
        # Reset multi-speaker state for next conversation cycle
        self._first_transcript_time = 0.0
        if self._response_timer_task and not self._response_timer_task.done():
            self._response_timer_task.cancel()
        
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
        
        # Track first TTS audio chunk for TTFB instrumentation
        if not self._tts_audio_received:
            self._tts_audio_received = True
            self._t_first_tts_audio = time.time()
        
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
        t_convert_start = time.time()
        loop = asyncio.get_running_loop()
        pcm_data = await loop.run_in_executor(
            _get_tts_thread_pool(),
            self._convert_audio_to_pcm,
            audio_data
        )
        t_convert_end = time.time()
        self._convert_time_total_ms += (t_convert_end - t_convert_start) * 1000
        
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