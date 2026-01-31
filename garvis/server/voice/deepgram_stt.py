"""
Deepgram real-time Speech-to-Text with Voice Activity Detection
Uses aiohttp WebSocket for Python 3.14 compatibility
"""

import asyncio
import json
import time
from typing import Callable, Awaitable, Optional
import aiohttp

from config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_MODEL,
    DEEPGRAM_UTTERANCE_END_MS,
    DEEPGRAM_ENDPOINTING,
    DEEPGRAM_USE_SPEECH_FINAL,
)


class DeepgramSTT:
    """
    Real-time speech-to-text using Deepgram's streaming WebSocket API.
    
    Features:
    - Real-time transcription streaming
    - Built-in Voice Activity Detection (VAD)
    - Utterance end detection for conversation flow
    """
    
    DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
    
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
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.current_transcript = ""
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._speech_final_fired = False  # Track if we already fired on speech_final
        self._last_audio_time = 0.0  # Track when we last sent audio
    
    async def connect(self):
        """Establish connection to Deepgram"""
        if not DEEPGRAM_API_KEY:
            raise ValueError("DEEPGRAM_API_KEY is not set")
        
        # Build WebSocket URL with query parameters
        # Performance tuning: utterance_end_ms and endpointing control response latency
        # Lower values = faster response but may cut off speech prematurely
        params = {
            "model": DEEPGRAM_MODEL,
            "language": "en-US",
            "smart_format": "true",
            "encoding": "linear16",
            "channels": "1",
            "sample_rate": "16000",
            "vad_events": "true",
            "interim_results": "true",
            "utterance_end_ms": str(DEEPGRAM_UTTERANCE_END_MS),  # Reduced from 1000ms for faster response
            "endpointing": str(DEEPGRAM_ENDPOINTING),  # Reduced from 300ms for faster endpoint detection
        }
        
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.DEEPGRAM_WS_URL}?{query_string}"
        
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}"
        }
        
        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(url, headers=headers)
            self._connected = True
            self._speech_final_fired = False  # Reset on new connection
            print("🎤 Deepgram STT connected")
            
            # Start receiving messages in background
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            # Start keepalive task to prevent 10-second timeout
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            
        except Exception as e:
            print(f"❌ Failed to connect to Deepgram: {e}")
            if self._session:
                await self._session.close()
                self._session = None
            raise
    
    async def disconnect(self):
        """Close the Deepgram connection"""
        self._connected = False
        
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        if self._session:
            await self._session.close()
            self._session = None
            
        print("🔌 Deepgram STT disconnected")
    
    async def send_audio(self, audio_bytes: bytes):
        """Send audio data to Deepgram for transcription"""
        if self._ws and self._connected:
            try:
                await self._ws.send_bytes(audio_bytes)
                self._last_audio_time = time.time()  # Track for keepalive
            except Exception as e:
                # Connection is broken - mark as disconnected so reconnection can happen
                self._connected = False
                print(f"⚠️ Deepgram connection lost: {e}")
    
    async def _keepalive_loop(self):
        """Send KeepAlive messages to prevent Deepgram's 10-second timeout"""
        KEEPALIVE_INTERVAL = 5.0  # Send every 5 seconds if no audio
        
        try:
            while self._connected:
                await asyncio.sleep(1.0)  # Check every second
                
                if not self._connected or not self._ws:
                    break
                
                # Send KeepAlive if no audio sent in the last 5 seconds
                time_since_audio = time.time() - self._last_audio_time
                if time_since_audio >= KEEPALIVE_INTERVAL:
                    try:
                        keepalive_msg = json.dumps({"type": "KeepAlive"})
                        await self._ws.send_str(keepalive_msg)
                        self._last_audio_time = time.time()  # Reset timer
                    except Exception as e:
                        print(f"⚠️ KeepAlive failed: {e}")
                        self._connected = False
                        break
        except asyncio.CancelledError:
            pass
    
    async def _receive_loop(self):
        """Background task to receive messages from Deepgram"""
        try:
            async for msg in self._ws:
                if not self._connected:
                    break
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        print(f"Invalid JSON from Deepgram: {msg.data[:100]}")
                    except Exception as e:
                        print(f"Error handling Deepgram message: {e}")
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print("🔴 Deepgram connection closed")
                    self._connected = False
                    break
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"❌ Deepgram WebSocket error: {msg.data}")
                    self._connected = False
                    break
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Deepgram receive error: {e}")
            self._connected = False
    
    async def _handle_message(self, data: dict):
        """Handle a message from Deepgram"""
        msg_type = data.get("type", "")
        
        if msg_type == "Results":
            # Transcription result
            channel = data.get("channel", {})
            alternatives = channel.get("alternatives", [])
            
            if alternatives:
                transcript = alternatives[0].get("transcript", "")
                is_final = data.get("is_final", False)
                speech_final = data.get("speech_final", False)
                
                if transcript:
                    if is_final:
                        # Append to current transcript
                        if self.current_transcript:
                            self.current_transcript += " " + transcript
                        else:
                            self.current_transcript = transcript
                    
                    # Send to callback
                    display_text = self.current_transcript if is_final else transcript
                    await self.on_transcript(display_text, is_final)
                
                # FAST PATH: Use speech_final (300ms) instead of UtteranceEnd (1000ms+)
                # speech_final fires when endpointing detects a pause in speech
                if DEEPGRAM_USE_SPEECH_FINAL and speech_final and self.current_transcript and not self._speech_final_fired:
                    self._speech_final_fired = True
                    await self.on_speech_end(self.current_transcript)
                    self.current_transcript = ""
        
        elif msg_type == "UtteranceEnd":
            # User stopped speaking (fires after utterance_end_ms of silence)
            # Only use this if we're not using speech_final for faster response
            if not DEEPGRAM_USE_SPEECH_FINAL and self.current_transcript:
                await self.on_speech_end(self.current_transcript)
                self.current_transcript = ""
        
        elif msg_type == "SpeechStarted":
            # User started speaking - reset the speech_final flag
            self._speech_final_fired = False
        
        elif msg_type == "Metadata":
            # Connection metadata
            print(f"📊 Deepgram metadata: request_id={data.get('request_id', 'unknown')}")
        
        elif msg_type == "Error":
            # Error message
            error_msg = data.get("message", "Unknown error")
            print(f"❌ Deepgram error: {error_msg}")
