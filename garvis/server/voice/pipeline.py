"""
Voice pipeline orchestrating STT → LLM → TTS
Supports both cloud APIs and local models for low-latency inference.

Cloud (default):
    Deepgram STT → Claude LLM → ElevenLabs TTS

Local (faster, requires setup-local-models.sh):
    faster-whisper STT → llama.cpp LLM → Piper TTS
"""

import asyncio
import json
import re
from typing import Optional, Union
from fastapi import WebSocket

# Cloud providers
from .deepgram_stt import DeepgramSTT
from .claude_llm import ClaudeLLM
from .elevenlabs_tts import ElevenLabsTTS

# Local providers
from .whisper_stt import WhisperSTT
from .local_llm import LocalLLM
from .piper_tts import PiperTTS
from .kokoro_tts import KokoroTTS

# OpenClaw integration
from .openclaw_llm import OpenClawLLM

# Configuration
from config import USE_LOCAL_LLM, USE_LOCAL_STT, USE_LOCAL_TTS, USE_OPENCLAW, USE_KOKORO_TTS


class VoicePipeline:
    """
    Orchestrates the real-time voice conversation flow:
    1. Receives audio from client
    2. Streams to STT for real-time transcription
    3. On speech end (VAD), sends transcript to LLM
    4. Streams LLM response to TTS
    5. Streams TTS audio back to client
    """
    
    @staticmethod
    def _normalize_transcript(text: str) -> str:
        """Normalize transcript to fix common STT misinterpretations."""
        # STT hears "Jarvis" or "Travis" when users say "Garvis" - fix it
        text = re.sub(r'\bjarvis\b', 'Garvis', text, flags=re.IGNORECASE)
        text = re.sub(r'\btravis\b', 'Garvis', text, flags=re.IGNORECASE)
        return text
    
    @staticmethod
    def _normalize_llm_output(text: str) -> str:
        """Normalize LLM output to fix unwanted phrases."""
        # Clean up any extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.stt: Optional[Union[DeepgramSTT, WhisperSTT]] = None
        self.llm: Optional[Union[ClaudeLLM, LocalLLM, OpenClawLLM]] = None
        self.tts: Optional[Union[ElevenLabsTTS, PiperTTS, KokoroTTS]] = None
        
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history: list[dict] = []
        self.current_transcript = ""
        
        self._running = False
        
        # Track which providers we're using
        self._use_local_stt = USE_LOCAL_STT
        self._use_local_llm = USE_LOCAL_LLM
        self._use_local_tts = USE_LOCAL_TTS
        self._use_openclaw = USE_OPENCLAW
        self._use_kokoro_tts = USE_KOKORO_TTS
    
    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool and return the result string."""
        print(f"🔧 Executing tool: {tool_name} with args: {args}")
        
        try:
            if tool_name == "ping":
                return json.dumps({
                    "status": "pong",
                    "service": "Garvis Voice Server"
                })
            
            else:
                return f"Unknown tool: {tool_name}"
        
        except Exception as e:
            print(f"❌ Tool execution error: {e}")
            return f"Error executing tool: {str(e)}"
    
    async def start(self):
        """Initialize and start the pipeline components"""
        self._running = True
        
        # Initialize STT (Speech-to-Text)
        if self._use_local_stt:
            print("🎤 Using local STT (faster-whisper)")
            self.stt = WhisperSTT(
                on_transcript=self._handle_transcript,
                on_speech_end=self._handle_speech_end
            )
        else:
            print("🎤 Using cloud STT (Deepgram)")
            self.stt = DeepgramSTT(
                on_transcript=self._handle_transcript,
                on_speech_end=self._handle_speech_end
            )
        
        # Initialize LLM (Language Model)
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
        
        # Initialize TTS (Text-to-Speech)
        # Priority: Cloud (ElevenLabs) > Local Kokoro > Local Piper
        if self._use_local_tts:
            if self._use_kokoro_tts:
                print("🔊 Using local TTS (Kokoro - realistic voice)")
                self.tts = KokoroTTS(on_audio=self._send_audio)
            else:
                print("🔊 Using local TTS (Piper)")
                self.tts = PiperTTS(on_audio=self._send_audio)
        else:
            print("🔊 Using cloud TTS (ElevenLabs)")
            self.tts = ElevenLabsTTS(on_audio=self._send_audio)
        
        # Connect STT
        await self.stt.connect()
        
        # Send ready status
        await self._send_status()
    
    async def cleanup(self):
        """Clean up pipeline resources"""
        self._running = False
        
        if self.stt:
            await self.stt.disconnect()
        if self.tts:
            await self.tts.stop()
    
    async def process_audio(self, audio_bytes: bytes):
        """Process incoming audio from the client"""
        if not self._running or not self.stt:
            return
        
        # Forward audio to STT
        await self.stt.send_audio(audio_bytes)
    
    async def handle_control(self, data: dict):
        """Handle control messages from the client"""
        msg_type = data.get("type")
        
        if msg_type == "start":
            self.is_listening = True
            await self._send_status()
        
        elif msg_type == "stop":
            self.is_listening = False
            await self._send_status()
        
        elif msg_type == "interrupt":
            # Stop current TTS playback
            if self.tts:
                await self.tts.stop()
            self.is_speaking = False
            await self._send_status()
        
        elif msg_type == "config":
            # Update configuration (voice, model, etc.)
            pass
    
    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle transcript updates from STT"""
        text = self._normalize_transcript(text)
        self.current_transcript = text
        
        # Send transcript to client
        await self.websocket.send_json({
            "type": "transcript",
            "text": text,
            "is_final": is_final,
            "role": "user"
        })
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def _handle_speech_end(self, final_transcript: str):
        """Handle end of user speech (VAD triggered)"""
        if not final_transcript.strip():
            return
        
        # Normalize transcript (e.g., "Jarvis" -> "Garvis")
        final_transcript = self._normalize_transcript(final_transcript)
        
        self.is_listening = False
        await self._send_status()
        
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": final_transcript
        })
        
        # Get LLM response
        self.is_speaking = True
        await self._send_status()
        
        assistant_response = ""
        
        # Stream response from LLM
        async for chunk in self.llm.stream_response(self.conversation_history):
            assistant_response += chunk
            
            # Send partial transcript to client (for display)
            await self.websocket.send_json({
                "type": "transcript",
                "text": assistant_response,
                "is_final": False,
                "role": "assistant"
            })
            
            # Stream to TTS
            await self.tts.add_text(chunk)
        
        # Finalize response
        final_response = self._normalize_llm_output(assistant_response)
        
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            # Send final transcript
            await self.websocket.send_json({
                "type": "transcript",
                "text": final_response,
                "is_final": True,
                "role": "assistant"
            })
            
            # Wait for TTS to finish
            await self.tts.flush()
        
        self.is_speaking = False
        await self._send_status()
    
    async def _send_audio(self, audio_bytes: bytes):
        """Send TTS audio to the client"""
        if not self._running:
            return
        
        try:
            await self.websocket.send_bytes(audio_bytes)
        except Exception as e:
            print(f"Error sending audio: {e}")
    
    async def _send_status(self):
        """Send current status to the client"""
        if not self._running:
            return
        
        try:
            await self.websocket.send_json({
                "type": "status",
                "listening": self.is_listening,
                "speaking": self.is_speaking
            })
        except Exception as e:
            print(f"Error sending status: {e}")
