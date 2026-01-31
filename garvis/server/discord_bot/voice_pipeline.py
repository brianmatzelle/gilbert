"""
Discord-adapted voice pipeline.

Orchestrates Deepgram STT → Claude → ElevenLabs TTS for Discord voice channels.
This is similar to the WebSocket pipeline but adapted for Discord's audio format.
"""

import asyncio
import io
import re
from typing import Optional, Callable, Awaitable

# Import the Garvis voice components (using as a library!)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from voice.deepgram_stt import DeepgramSTT
from voice.claude_llm import ClaudeLLM
from voice.elevenlabs_tts import ElevenLabsTTS
from providers import get_providers_by_type, get_provider_by_url, PROVIDERS
from streaming import get_stream_urls
from config import TTS_BUFFER_THRESHOLD

# Audio conversion
# Note: pydub also requires ffmpeg to be installed on the system
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed in voice_pipeline: {e}")


class DiscordVoicePipeline:
    """
    Voice pipeline adapted for Discord voice channels.
    
    Flow:
    1. Receive PCM audio (16kHz mono) from Discord via audio sink
    2. Stream to Deepgram for real-time transcription
    3. On speech end (VAD), send transcript to Claude
    4. Stream Claude response to Eleven Labs TTS
    5. Convert TTS audio (MP3) to PCM for Discord playback
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
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def __init__(
        self,
        on_audio_output: Callable[[bytes], Awaitable[None]],
        on_transcript: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_status: Optional[Callable[[bool, bool], Awaitable[None]]] = None,
    ):
        """
        Args:
            on_audio_output: Callback for PCM audio to play in Discord (48kHz stereo)
            on_transcript: Optional callback (text, role, is_final)
            on_status: Optional callback (listening, speaking)
        """
        self.on_audio_output = on_audio_output
        self.on_transcript = on_transcript
        self.on_status = on_status
        
        self.stt: Optional[DeepgramSTT] = None
        self.llm: Optional[ClaudeLLM] = None
        self.tts: Optional[ElevenLabsTTS] = None
        
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history: list[dict] = []
        self.current_transcript = ""
        
        self._running = False
        
        # Audio buffer for TTS output conversion
        self._tts_buffer = io.BytesIO()
    
    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool and return the result string."""
        print(f"🔧 Executing tool: {tool_name} with args: {args}")
        
        try:
            if tool_name == "SEARCH_CONTENT":
                query = args.get("query", "")
                content_type = args.get("content_type", "sports")
                
                providers = get_providers_by_type(content_type)
                if not providers:
                    return f"No providers available for content type: {content_type}"
                
                all_results = []
                for provider in providers:
                    try:
                        results = await provider.search(query)
                        all_results.extend(results)
                    except Exception as e:
                        print(f"Error searching {provider.name}: {e}")
                        continue
                
                if not all_results:
                    return "No content found matching your search."
                
                result = f"Found {len(all_results)} item(s):\n\n"
                for i, item in enumerate(all_results[:5], 1):
                    result += f"{i}. {item['title']} ({item['metadata']})\n"
                    result += f"   URL: {item['url']}\n"
                
                result += "\nTo watch, use SHOW_CONTENT with a content URL."
                return result
            
            elif tool_name == "SHOW_CONTENT":
                # In Discord context, we can't display video, just acknowledge
                return "I found the stream. Unfortunately, video playback isn't available in Discord voice - you'd need to use the XR client for that. I can describe what's happening if you'd like!"
            
            elif tool_name == "ping":
                import json
                return json.dumps({
                    "status": "pong",
                    "service": "Garvis Discord Bot",
                    "providers": [p.name for p in PROVIDERS]
                })
            
            else:
                return f"Unknown tool: {tool_name}"
        
        except Exception as e:
            print(f"❌ Tool execution error: {e}")
            return f"Error executing tool: {str(e)}"
    
    async def start(self):
        """Initialize and start the pipeline components."""
        self._running = True
        
        # Initialize components
        self.stt = DeepgramSTT(
            on_transcript=self._handle_transcript,
            on_speech_end=self._handle_speech_end
        )
        self.llm = ClaudeLLM()
        self.tts = ElevenLabsTTS(on_audio=self._handle_tts_audio)
        
        # Connect to Deepgram
        await self.stt.connect()
        
        print("🎤 Discord voice pipeline started")
        await self._send_status()
    
    async def stop(self):
        """Clean up pipeline resources."""
        self._running = False
        
        if self.stt:
            await self.stt.disconnect()
        if self.tts:
            await self.tts.stop()
        
        print("🔌 Discord voice pipeline stopped")
    
    async def process_audio(self, audio_bytes: bytes):
        """
        Process incoming audio from Discord user.
        
        Args:
            audio_bytes: 16kHz mono PCM audio
        """
        if not self._running or not self.stt:
            return
        
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
    
    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle transcript updates from Deepgram."""
        text = self._normalize_transcript(text)
        self.current_transcript = text
        
        if self.on_transcript:
            await self.on_transcript(text, "user", is_final)
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def _handle_speech_end(self, final_transcript: str):
        """Handle end of user speech (VAD triggered)."""
        if not final_transcript.strip():
            return
        
        final_transcript = self._normalize_transcript(final_transcript)
        
        self.is_listening = False
        await self._send_status()
        
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": final_transcript
        })
        
        print(f"👤 User: {final_transcript}")
        
        # Get Claude response
        self.is_speaking = True
        await self._send_status()
        
        assistant_response = ""
        
        # Use tool-calling response flow
        async for event in self.llm.stream_response_with_tools(
            self.conversation_history,
            self._execute_tool
        ):
            event_type = event.get("type")
            
            if event_type == "text":
                assistant_response += event.get("content", "")
            
            elif event_type == "tool_use":
                print(f"🔧 Tool call: {event.get('name')} with {event.get('input')}")
        
        # Finalize response
        final_response = self._normalize_llm_output(assistant_response)
        
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            print(f"🤖 Garvis: {final_response}")
            
            if self.on_transcript:
                await self.on_transcript(final_response, "assistant", True)
            
            # Send to TTS
            await self.tts.add_text(final_response)
            await self.tts.flush()
        
        self.is_speaking = False
        await self._send_status()
    
    async def _handle_tts_audio(self, audio_bytes: bytes):
        """
        Handle TTS audio output from ElevenLabs.
        
        ElevenLabs sends MP3 audio - we need to convert to PCM for Discord.
        """
        if not self._running:
            return
        
        # Accumulate MP3 chunks
        self._tts_buffer.write(audio_bytes)
        
        # Try to convert and send audio in chunks
        await self._flush_tts_buffer()
    
    async def _flush_tts_buffer(self):
        """Convert accumulated MP3 to PCM and send to Discord."""
        if self._tts_buffer.tell() < TTS_BUFFER_THRESHOLD:  # Wait for enough data (reduced for faster response)
            return
        
        self._tts_buffer.seek(0)
        mp3_data = self._tts_buffer.read()
        self._tts_buffer.seek(0)
        self._tts_buffer.truncate()
        
        # Convert MP3 to PCM for Discord (48kHz stereo)
        pcm_data = self._convert_mp3_to_pcm(mp3_data)
        if pcm_data:
            await self.on_audio_output(pcm_data)
    
    def _convert_mp3_to_pcm(self, mp3_data: bytes) -> Optional[bytes]:
        """
        Convert MP3 audio to PCM for Discord playback.
        
        Discord expects: 48000 Hz, 16-bit signed, stereo
        """
        if not mp3_data:
            return None
        
        if HAS_PYDUB:
            try:
                # Load MP3
                audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
                
                # Convert to Discord format
                audio = audio.set_channels(2).set_frame_rate(48000).set_sample_width(2)
                
                return audio.raw_data
            
            except Exception as e:
                print(f"⚠️ MP3 to PCM conversion failed: {e}")
                return None
        else:
            print("⚠️ pydub not available - cannot convert TTS audio")
            return None
    
    async def _send_status(self):
        """Send current status."""
        if self.on_status:
            await self.on_status(self.is_listening, self.is_speaking)
