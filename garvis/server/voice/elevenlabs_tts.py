"""
Eleven Labs Real-time Text-to-Speech via WebSocket API

This module provides real-time text-to-speech using ElevenLabs' WebSocket streaming API.
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
    ┌──────────────────┐
    │  ElevenLabs WS   │  ← WebSocket with generation_config
    │  (stream-input)  │     chunk_length_schedule: [50, 120, 200, 260]
    └────────┬─────────┘
             │
             ▼ (base64 MP3 chunks)
    ┌──────────────────┐
    │   Audio Buffer   │  ← Prebuffer 8KB before playback
    └────────┬─────────┘
             │
             ▼ (MP3 bytes)
    Voice Pipeline (converts MP3 → PCM for Discord)


WHY WEBSOCKET INSTEAD OF HTTP?
=============================
1. Lower latency for streaming text input (text arrives word-by-word from LLM)
2. Bidirectional - can receive audio while still sending text
3. Better chunk scheduling with generation_config

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
    Real-time text-to-speech using ElevenLabs WebSocket API.
    
    Key features:
    - Uses WebSocket for bidirectional streaming (lowest latency)
    - Direct PCM output (no MP3 conversion artifacts)
    - Text buffering to meet ElevenLabs' minimum chunk requirements
    - Jitter buffer for smooth playback
    """
    
    WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    
    # ElevenLabs requires ~120 chars to start generating audio
    # We buffer text until we have enough, then send with flush=true
    MIN_TEXT_CHARS = 50  # Lower threshold since we use flush
    
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
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._is_speaking = False
        self._stop_event = asyncio.Event()
        
        # Audio buffer for smooth playback (prebuffer ~8KB of MP3, roughly 500ms)
        self._audio_buffer = AudioBuffer(prebuffer_bytes=8000)
        
        # Track if we've sent the initial handshake
        self._initialized = False
        
        # Text buffer - accumulate text before sending to ElevenLabs
        self._text_buffer = ""
    
    async def _connect(self):
        """Connect to ElevenLabs WebSocket API."""
        url = self.WS_URL.format(voice_id=self.voice_id)
        
        # Add query parameters for streaming
        params = [
            f"model_id={self.model_id}",
            f"output_format={ELEVENLABS_OUTPUT_FORMAT}",
            "inactivity_timeout=30",
        ]
        url = f"{url}?{'&'.join(params)}"
        
        print(f"🔊 Connecting to ElevenLabs WebSocket...")
        self._ws = await websockets.connect(url)
        
        # Send initial handshake with voice settings and generation config
        # Using smaller chunk_length_schedule for faster first audio
        handshake = {
            "text": " ",  # Initial space to start the connection
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "speed": 1.0,
            },
            "generation_config": {
                "chunk_length_schedule": [50, 120, 200, 260]  # Lower thresholds for faster response
            },
            "xi_api_key": ELEVENLABS_API_KEY,
        }
        await self._ws.send(json.dumps(handshake))
        self._initialized = True
        print("✅ ElevenLabs WebSocket connected")
    
    async def _receive_audio(self):
        """Task that receives audio from WebSocket and adds to jitter buffer."""
        try:
            while not self._stop_event.is_set():
                if not self._ws:
                    break
                
                try:
                    message = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=0.1
                    )
                    
                    data = json.loads(message)
                    
                    # Check for error
                    if "error" in data:
                        print(f"❌ ElevenLabs error: {data.get('error')} (code: {data.get('code')})")
                    
                    # Check for audio data
                    if "audio" in data and data["audio"]:
                        audio_data = base64.b64decode(data["audio"])
                        self._audio_buffer.add_audio(audio_data)
                    
                    # Check if this is the final chunk
                    if data.get("isFinal", False):
                        self._audio_buffer.mark_finished()
                        break
                
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("⚠️ WebSocket connection closed")
                    break
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ WebSocket receive error: {e}")
        finally:
            self._audio_buffer.mark_finished()
    
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
        if not self._is_speaking:
            # Start streaming on first text
            self._is_speaking = True
            self._stop_event.clear()
            self._audio_buffer.reset()
            self._text_buffer = ""
            
            # Connect to WebSocket
            await self._connect()
            
            # Start receive and playback tasks
            self._receive_task = asyncio.create_task(self._receive_audio())
            self._playback_task = asyncio.create_task(self._playback_loop())
        
        # Buffer the text
        self._text_buffer += text
        
        # Send when we have enough text (ElevenLabs needs ~50+ chars to generate)
        if len(self._text_buffer) >= self.MIN_TEXT_CHARS:
            await self._send_buffered_text()
    
    async def _send_buffered_text(self, flush: bool = False):
        """Send buffered text to ElevenLabs."""
        if not self._text_buffer or not self._ws or not self._initialized:
            return
        
        text_to_send = self._text_buffer
        self._text_buffer = ""
        
        try:
            message = {
                "text": text_to_send,
                "flush": flush,  # Force generation even if below threshold
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:
            print(f"⚠️ Error sending text to ElevenLabs: {e}")
    
    async def flush(self):
        """Signal end of text and wait for audio to finish."""
        if not self._is_speaking:
            return
        
        # Send any remaining buffered text with flush=true
        if self._text_buffer:
            await self._send_buffered_text(flush=True)
        
        # Send end-of-stream signal
        if self._ws and self._initialized:
            try:
                await self._ws.send(json.dumps({"text": ""}))
            except Exception as e:
                print(f"⚠️ Error sending flush: {e}")
        
        # Wait for receive task to complete
        if self._receive_task:
            try:
                await asyncio.wait_for(self._receive_task, timeout=10.0)
            except asyncio.TimeoutError:
                print("⚠️ Receive task timed out")
                self._receive_task.cancel()
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
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
        
        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        
        self._is_speaking = False
        self._initialized = False
        print("✅ TTS streaming complete")
    
    async def stop(self):
        """Stop current TTS playback immediately."""
        self._stop_event.set()
        
        # Cancel tasks
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        if self._playback_task:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None
        
        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        
        # Reset state
        self._audio_buffer.reset()
        self._text_buffer = ""
        self._is_speaking = False
        self._initialized = False
        self._stop_event.clear()
