"""
Eleven Labs Real-time Text-to-Speech via WebSocket API

This module provides real-time text-to-speech using ElevenLabs' Multi-Context WebSocket API.
It's optimized for voice assistants where text arrives incrementally from an LLM.

ARCHITECTURE:
============

    Claude LLM (streaming)
           │
           ▼ (small text chunks, word by word)
    ┌──────────────────┐
    │   Text Buffer    │  ← Accumulate until 50+ chars
    └────────┬─────────┘
             │
             ▼ (buffered text)
    ┌──────────────────────────────────────────────────┐
    │  ElevenLabs Multi-Context WebSocket (PERSISTENT) │
    │  (multi-stream-input)                            │
    │  - Single connection for entire session          │
    │  - Multiple contexts for concurrent audio        │
    │  - Keep-alive to prevent timeout                 │
    └────────┬─────────────────────────────────────────┘
             │
             ▼ (base64 MP3 chunks per context)
    ┌──────────────────┐
    │   Audio Buffer   │  ← Prebuffer 8KB before playback
    └────────┬─────────┘
             │
             ▼ (MP3 bytes)
    Voice Pipeline (converts MP3 → PCM for Discord)


WHY MULTI-CONTEXT WEBSOCKET?
============================
1. PERSISTENT CONNECTION: No reconnect latency between responses (~200-500ms saved)
2. Multiple "contexts" allow concurrent audio streams within one connection
3. Graceful interruption handling - close old context, start new one
4. Keep-alive mechanism prevents 20-second timeout

WHY TEXT BUFFERING?
==================
ElevenLabs requires ~120 characters before generating audio (chunk_length_schedule).
Since Claude streams word-by-word (5-20 chars each), we buffer until 50+ chars
then send with the buffer. Without this, no audio is generated.

WHY AUDIO BUFFERING?
===================
Network jitter can cause gaps in audio playback. By prebuffering ~8KB (~500ms)
of audio before starting playback, we smooth out network variations.

IMPORTANT: WebSocket API only supports MP3 output!
PCM formats (pcm_44100, etc.) return "output_format_not_allowed" error.
MP3→PCM conversion is handled by the voice pipeline, not here.
"""

import asyncio
import base64
import json
import uuid
from collections import deque
from typing import Callable, Awaitable, Optional

import websockets

from config import (
    ELEVENLABS_API_KEY, 
    ELEVENLABS_VOICE_ID, 
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
)


class AudioBuffer:
    """
    Simple audio buffer that accumulates audio data before playback starts.
    
    This smooths out network jitter by pre-buffering audio.
    No format conversion is done here - that's handled by the pipeline.
    """
    
    def __init__(self, prebuffer_bytes: int = 8000):
        """
        Args:
            prebuffer_bytes: Bytes of audio to buffer before starting playback
        """
        self._prebuffer_bytes = prebuffer_bytes
        self._buffer: deque[bytes] = deque()
        self._total_bytes = 0
        self._finished = False
    
    def add_audio(self, audio_data: bytes):
        """Add audio data to the buffer."""
        if audio_data:
            self._buffer.append(audio_data)
            self._total_bytes += len(audio_data)
    
    def mark_finished(self):
        """Mark that no more audio will be added."""
        self._finished = True
    
    def is_ready(self) -> bool:
        """Check if buffer has enough data to start playback."""
        return self._total_bytes >= self._prebuffer_bytes or self._finished
    
    def get_all_audio(self) -> Optional[bytes]:
        """
        Get all buffered audio.
        
        Returns None if not ready yet.
        """
        if not self.is_ready() and not self._finished:
            return None
        
        if self._total_bytes == 0:
            return None
        
        # Combine all buffered chunks
        all_data = b''.join(self._buffer)
        self._buffer.clear()
        self._total_bytes = 0
        
        return all_data
    
    def reset(self):
        """Reset the buffer for a new stream."""
        self._buffer.clear()
        self._total_bytes = 0
        self._finished = False


class ElevenLabsTTS:
    """
    Real-time text-to-speech using ElevenLabs Multi-Context WebSocket API.
    
    Key features:
    - PERSISTENT WebSocket connection (no reconnect latency between responses)
    - Multiple contexts for concurrent/sequential audio generation
    - Keep-alive mechanism to prevent timeout
    - Graceful interruption handling
    - Text buffering to meet ElevenLabs' minimum chunk requirements
    - Jitter buffer for smooth playback
    """
    
    # Multi-stream endpoint for persistent connections with multiple contexts
    WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input"
    
    # ElevenLabs requires ~120 chars to start generating audio
    # We buffer text until we have enough, then send with flush=true
    MIN_TEXT_CHARS = 50  # Lower threshold since we use flush
    
    # Keep-alive interval (send ping before 20s timeout)
    KEEP_ALIVE_INTERVAL = 15  # seconds
    
    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        voice_id: str = ELEVENLABS_VOICE_ID,
        model_id: str = ELEVENLABS_MODEL_ID
    ):
        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        
        self.on_audio = on_audio
        self.voice_id = voice_id
        self.model_id = model_id
        
        # Persistent WebSocket connection
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        
        # Background tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        
        # Current context for this speech generation
        self._current_context_id: Optional[str] = None
        self._is_speaking = False
        self._stop_event = asyncio.Event()
        
        # Audio buffer for smooth playback (prebuffer ~8KB of MP3, roughly 500ms)
        self._audio_buffer = AudioBuffer(prebuffer_bytes=8000)
        
        # Text buffer - accumulate text before sending to ElevenLabs
        self._text_buffer = ""
        
        # Track completed contexts to filter late messages
        self._completed_contexts: set[str] = set()
    
    async def connect(self):
        """
        Establish persistent WebSocket connection to ElevenLabs.
        Call this once when the voice pipeline starts (e.g., when joining voice channel).
        """
        if self._connected and self._ws:
            return
        
        url = self.WS_URL.format(voice_id=self.voice_id)
        
        # Add query parameters - use longer inactivity timeout for persistent connection
        params = [
            f"model_id={self.model_id}",
            f"output_format={ELEVENLABS_OUTPUT_FORMAT}",
            "inactivity_timeout=180",  # Max timeout (3 minutes)
        ]
        url = f"{url}?{'&'.join(params)}"
        
        print(f"🔊 Connecting to ElevenLabs WebSocket (persistent)...")
        
        try:
            self._ws = await websockets.connect(
                url,
                max_size=16 * 1024 * 1024,  # 16MB max message size
                additional_headers={"xi-api-key": ELEVENLABS_API_KEY}
            )
            self._connected = True
            print("✅ ElevenLabs WebSocket connected (persistent)")
            
            # Start background receive task
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            # Start keep-alive task
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            
        except Exception as e:
            print(f"❌ Failed to connect to ElevenLabs: {e}")
            self._connected = False
            raise
    
    async def _keepalive_loop(self):
        """Send periodic keep-alive messages to prevent timeout."""
        try:
            while self._connected and self._ws:
                await asyncio.sleep(self.KEEP_ALIVE_INTERVAL)
                
                if self._ws and self._connected:
                    try:
                        # Send a space to keep connection alive without generating audio
                        # Only if we have a current context; otherwise the connection stays alive anyway
                        if self._current_context_id:
                            await self._ws.send(json.dumps({
                                "context_id": self._current_context_id,
                                "text": " ",  # Single space keeps context alive
                            }))
                    except Exception as e:
                        print(f"⚠️ Keep-alive failed: {e}")
                        await self._handle_disconnect()
                        break
        except asyncio.CancelledError:
            pass
    
    async def _handle_disconnect(self):
        """Handle unexpected disconnection."""
        print("⚠️ ElevenLabs WebSocket disconnected")
        self._connected = False
        self._ws = None
        
        # Mark current context as finished if speaking
        if self._is_speaking:
            self._audio_buffer.mark_finished()
    
    async def _receive_loop(self):
        """
        Background task that receives all audio from WebSocket.
        Filters messages by context_id to handle the current speech.
        """
        try:
            while self._connected and self._ws:
                try:
                    message = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=0.5
                    )
                    
                    data = json.loads(message)
                    context_id = data.get("contextId", data.get("context_id"))
                    
                    # Ignore messages from completed/old contexts
                    if context_id in self._completed_contexts:
                        continue
                    
                    # Check for error
                    if "error" in data:
                        print(f"❌ ElevenLabs error: {data.get('error')} (code: {data.get('code')})")
                        continue
                    
                    # Only process audio for current context
                    if context_id == self._current_context_id:
                        # Check for audio data
                        if "audio" in data and data["audio"]:
                            audio_data = base64.b64decode(data["audio"])
                            self._audio_buffer.add_audio(audio_data)
                        
                        # Check if this is the final chunk for this context
                        if data.get("isFinal", False) or data.get("is_final", False):
                            self._audio_buffer.mark_finished()
                            self._completed_contexts.add(context_id)
                
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    await self._handle_disconnect()
                    break
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ WebSocket receive error: {e}")
            await self._handle_disconnect()
    
    async def _playback_loop(self):
        """Task that plays buffered audio when ready."""
        try:
            # Wait for buffer to be ready (prebuffer filled or stream finished)
            while not self._stop_event.is_set():
                if self._audio_buffer.is_ready():
                    break
                # Only exit early if finished AND empty (no audio at all)
                if self._audio_buffer._finished and self._audio_buffer._total_bytes == 0:
                    print("⚠️ TTS playback: No audio received")
                    return
                await asyncio.sleep(0.01)
            
            # Play audio as it becomes available
            while not self._stop_event.is_set():
                audio = self._audio_buffer.get_all_audio()
                
                if audio:
                    await self.on_audio(audio)
                
                # Only break if finished AND buffer is now empty
                if self._audio_buffer._finished and self._audio_buffer._total_bytes == 0:
                    break
                
                # Small delay to allow more audio to accumulate
                await asyncio.sleep(0.05)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Playback error: {e}")
    
    async def add_text(self, text: str):
        """
        Add text to be converted to speech.
        Text is buffered and sent to ElevenLabs when we have enough.
        """
        # Ensure we have a connection
        if not self._connected or not self._ws:
            await self.connect()
        
        if not self._is_speaking:
            # Start a new context for this speech
            self._is_speaking = True
            self._stop_event.clear()
            self._audio_buffer.reset()
            self._text_buffer = ""
            
            # Generate unique context ID for this speech
            self._current_context_id = f"ctx_{uuid.uuid4().hex[:8]}"
            
            # Send initial message to create context with voice settings
            initial_message = {
                "context_id": self._current_context_id,
                "text": " ",  # Initial space to start the context
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": 1.0,
                },
                "generation_config": {
                    "chunk_length_schedule": [50, 120, 200, 260]
                },
            }
            
            try:
                await self._ws.send(json.dumps(initial_message))
            except Exception as e:
                print(f"❌ Failed to create context: {e}")
                await self._handle_disconnect()
                await self.connect()
                await self._ws.send(json.dumps(initial_message))
            
            # Start playback task for this context
            self._playback_task = asyncio.create_task(self._playback_loop())
        
        # Buffer the text
        self._text_buffer += text
        
        # Send when we have enough text (ElevenLabs needs ~50+ chars to generate)
        if len(self._text_buffer) >= self.MIN_TEXT_CHARS:
            await self._send_buffered_text()
    
    async def _send_buffered_text(self, flush: bool = False):
        """Send buffered text to ElevenLabs."""
        if not self._text_buffer or not self._ws or not self._current_context_id:
            return
        
        text_to_send = self._text_buffer
        self._text_buffer = ""
        
        try:
            message = {
                "context_id": self._current_context_id,
                "text": text_to_send,
                "flush": flush,  # Force generation even if below threshold
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:
            print(f"⚠️ Error sending text to ElevenLabs: {e}")
    
    async def flush(self):
        """Signal end of text for current context and wait for audio to finish."""
        if not self._is_speaking:
            return
        
        # Send any remaining buffered text with flush=true
        if self._text_buffer:
            await self._send_buffered_text(flush=True)
        
        # Close this context (signals end of this speech)
        if self._ws and self._current_context_id:
            try:
                await self._ws.send(json.dumps({
                    "context_id": self._current_context_id,
                    "close_context": True
                }))
            except Exception as e:
                print(f"⚠️ Error closing context: {e}")
        
        # Wait for playback to complete
        if self._playback_task:
            try:
                await asyncio.wait_for(self._playback_task, timeout=10.0)
            except asyncio.TimeoutError:
                print("⚠️ Playback task timed out")
                self._playback_task.cancel()
            except asyncio.CancelledError:
                pass
            self._playback_task = None
        
        # Reset speaking state but keep connection open!
        self._is_speaking = False
        self._current_context_id = None
        print("✅ TTS streaming complete")
    
    async def stop(self):
        """Stop current TTS playback immediately (but keep connection open)."""
        self._stop_event.set()
        
        # Close current context to stop generation
        if self._ws and self._current_context_id:
            try:
                await self._ws.send(json.dumps({
                    "context_id": self._current_context_id,
                    "close_context": True
                }))
                self._completed_contexts.add(self._current_context_id)
            except Exception:
                pass
        
        # Cancel playback task
        if self._playback_task:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None
        
        # Reset state but keep connection open
        self._audio_buffer.reset()
        self._text_buffer = ""
        self._is_speaking = False
        self._current_context_id = None
        self._stop_event.clear()
    
    async def disconnect(self):
        """
        Close the persistent WebSocket connection.
        Call this when leaving the voice channel.
        """
        print("🔌 Disconnecting from ElevenLabs...")
        
        # Cancel keep-alive task
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        
        # Cancel receive task
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        # Cancel playback task
        if self._playback_task:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None
        
        # Close WebSocket gracefully
        if self._ws:
            try:
                await self._ws.send(json.dumps({"close_socket": True}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        
        # Reset all state
        self._connected = False
        self._audio_buffer.reset()
        self._text_buffer = ""
        self._is_speaking = False
        self._current_context_id = None
        self._completed_contexts.clear()
        print("✅ Disconnected from ElevenLabs")
