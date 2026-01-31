"""
Discord-adapted voice pipeline.

Orchestrates Deepgram STT → Claude → ElevenLabs TTS for Discord voice channels.
This is similar to the WebSocket pipeline but adapted for Discord's audio format.

AUDIO FORMAT CONVERSIONS:
========================

    Discord Input (from users speaking):
    - 48kHz, stereo, 16-bit PCM
    - Converted to 16kHz mono by audio_sink.py
    - Sent to Deepgram for transcription

    ElevenLabs Output:
    - MP3 @ 44.1kHz (WebSocket API only supports MP3!)
    - We accumulate 16KB before converting (avoid partial MP3 frame issues)
    - pydub converts MP3 → 48kHz stereo PCM

    Discord Output (Garvis speaking):
    - 48kHz, stereo, 16-bit PCM
    - Played via discord.PCMAudio

WHY BUFFER MP3 BEFORE CONVERTING?
=================================
MP3 uses frames (~400-1000 bytes each). If we try to decode partial frames,
pydub/ffmpeg will fail or produce glitchy audio. By buffering 16KB (~10-40 frames),
we ensure we always have complete frames to decode.

The bot.py also buffers converted PCM (~48KB, ~250ms) before starting playback
to avoid gaps between chunks.
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

# Audio conversion - pydub requires ffmpeg
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception as e:
    HAS_PYDUB = False
    print(f"⚠️ pydub import failed: {e}")


class DiscordVoicePipeline:
    """
    Voice pipeline adapted for Discord voice channels.
    
    Flow:
    1. Receive PCM audio (16kHz mono) from Discord via audio sink
    2. Stream to Deepgram for real-time transcription
    3. On speech end (VAD), send transcript to Claude
    4. Stream Claude response to Eleven Labs TTS (WebSocket API)
    5. TTS outputs PCM directly (48kHz stereo) - no conversion needed!
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
        on_audio_output: Callable[[bytes, bool], Awaitable[None]],
        on_transcript: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_status: Optional[Callable[[bool, bool], Awaitable[None]]] = None,
    ):
        """
        Args:
            on_audio_output: Callback for PCM audio (bytes, flush: bool) to play in Discord (48kHz stereo)
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
        self._processing_response = False  # Prevent double-triggering
        self._pending_transcript = ""  # Latest transcript from Deepgram
        self._last_processed_transcript = ""  # Avoid processing same transcript twice
        self._last_discord_silence_time = 0.0  # Timestamp when Discord silence last triggered a response
        
        # MP3 buffer for TTS audio conversion
        self._mp3_buffer = io.BytesIO()
    
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
        
        # Wrapper to tag Deepgram's speech_end calls with source
        async def _deepgram_speech_end(transcript: str):
            await self._handle_speech_end(transcript, source="deepgram")
        
        # Initialize components
        self.stt = DeepgramSTT(
            on_transcript=self._handle_transcript,
            on_speech_end=_deepgram_speech_end
        )
        self.llm = ClaudeLLM()
        
        # TTS now uses WebSocket API with direct PCM output - no conversion needed!
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
        
        # Store the latest transcript for when silence is detected
        if text.strip():
            self._pending_transcript = text
            # Reset duplicate detection when new speech content arrives
            # (allows user to intentionally repeat themselves)
            # BUT don't reset while processing a response - this prevents the race condition
            # where Discord's silence detection fires, then Deepgram's speech_final arrives
            # after the response completes, causing a duplicate response
            if not self._processing_response and text.strip().lower() != self._last_processed_transcript:
                self._last_processed_transcript = ""
        
        if self.on_transcript:
            await self.on_transcript(text, "user", is_final)
        
        if not self.is_listening:
            self.is_listening = True
            await self._send_status()
    
    async def handle_user_silence(self):
        """
        Called when Discord detects the user stopped speaking.
        This triggers faster than Deepgram's speech_final, giving us lower latency.
        """
        import time
        import json
        
        # #region agent log
        try:
            with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"hypothesisId":"A,B","location":"voice_pipeline.py:handle_user_silence","message":"Discord silence detected","data":{"pending_transcript":self._pending_transcript[:50] if self._pending_transcript else "","processing_response":self._processing_response,"stt_current_transcript":self.stt.current_transcript[:50] if self.stt and self.stt.current_transcript else ""},"timestamp":int(time.time()*1000)}) + '\n')
        except: pass
        # #endregion
        
        # Don't trigger if already processing or no transcript
        if self._processing_response or not self._pending_transcript.strip():
            return
        
        # Record timestamp - used to block Deepgram's speech_final that arrives shortly after
        self._last_discord_silence_time = time.time()
        
        # Also clear Deepgram's accumulated transcript to prevent stale text
        if self.stt:
            self.stt.current_transcript = ""
        
        # Trigger response immediately with whatever transcript we have
        await self._handle_speech_end(self._pending_transcript, source="discord")
    
    async def _handle_speech_end(self, final_transcript: str, source: str = "deepgram"):
        """Handle end of user speech (VAD triggered)."""
        import time
        import json
        
        if not final_transcript.strip():
            return
        
        # #region agent log
        try:
            with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"hypothesisId":"A,B,C,D","location":"voice_pipeline.py:_handle_speech_end:entry","message":"speech_end called","data":{"transcript":final_transcript[:50],"source":source,"processing_response":self._processing_response,"last_processed":self._last_processed_transcript[:50] if self._last_processed_transcript else "","time_since_discord":time.time()-self._last_discord_silence_time},"timestamp":int(time.time()*1000)}) + '\n')
        except: pass
        # #endregion
        
        # Prevent double-triggering from concurrent calls
        if self._processing_response:
            # #region agent log
            try:
                with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"hypothesisId":"D","location":"voice_pipeline.py:_handle_speech_end:blocked","message":"BLOCKED by processing_response","data":{"transcript":final_transcript[:50],"source":source},"timestamp":int(time.time()*1000)}) + '\n')
            except: pass
            # #endregion
            return
        
        # FIX: If this is from Deepgram and Discord already triggered a response recently,
        # skip this to prevent duplicate responses. The 10-second window accounts for
        # response time + potential delays in Deepgram's speech_final.
        DISCORD_SILENCE_GUARD_SECONDS = 10.0
        time_since_discord = time.time() - self._last_discord_silence_time
        if source == "deepgram" and time_since_discord < DISCORD_SILENCE_GUARD_SECONDS:
            # #region agent log
            try:
                with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"hypothesisId":"NEW","location":"voice_pipeline.py:_handle_speech_end:discord_guard","message":"BLOCKED by discord silence guard","data":{"transcript":final_transcript[:50],"source":source,"time_since_discord":time_since_discord},"timestamp":int(time.time()*1000)}) + '\n')
            except: pass
            # #endregion
            return
        
        # Skip if we already processed this exact transcript
        # (Discord silence detection and Deepgram speech_final can both trigger)
        normalized = final_transcript.strip().lower()
        if normalized == self._last_processed_transcript:
            # #region agent log
            try:
                with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"hypothesisId":"C","location":"voice_pipeline.py:_handle_speech_end:dedup","message":"BLOCKED by dedup","data":{"normalized":normalized[:50],"last_processed":self._last_processed_transcript[:50]},"timestamp":int(time.time()*1000)}) + '\n')
            except: pass
            # #endregion
            return
        self._last_processed_transcript = normalized
        
        # #region agent log
        try:
            with open('/mnt/s/Projects/guitar2discord/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"hypothesisId":"C","location":"voice_pipeline.py:_handle_speech_end:proceeding","message":"PROCEEDING with response","data":{"normalized":normalized[:50],"source":source},"timestamp":int(time.time()*1000)}) + '\n')
        except: pass
        # #endregion
        
        self._processing_response = True
        
        t_start = time.time()
        
        final_transcript = self._normalize_transcript(final_transcript)
        
        # Clear pending transcript to prevent re-triggering
        self._pending_transcript = ""
        
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
            
            # Flush any remaining MP3 buffer
            await self._flush_mp3_buffer(flush=True)
            
            t_tts_end = time.time()
            
            print(f"⏱️ TTS flush took {(t_tts_end - t_tts_start)*1000:.0f}ms")
            print(f"⏱️ Total response time: {(t_tts_end - t_start)*1000:.0f}ms")
        
        self.is_speaking = False
        self._processing_response = False  # Allow new triggers
        await self._send_status()
    
    async def _handle_tts_audio(self, audio_bytes: bytes):
        """
        Handle TTS audio output from ElevenLabs.
        
        ElevenLabs WebSocket outputs MP3 audio - we need to convert to PCM for Discord.
        We accumulate MP3 data to ensure complete frames before decoding.
        """
        if not self._running:
            return
        
        if not audio_bytes:
            return
        
        # Accumulate MP3 data
        self._mp3_buffer.write(audio_bytes)
        
        # Convert and send when we have enough data (avoid partial frame issues)
        # MP3 frames are ~400-1000 bytes, so 16KB should have many complete frames
        MIN_MP3_BYTES = 16000
        
        if self._mp3_buffer.tell() >= MIN_MP3_BYTES:
            await self._flush_mp3_buffer(flush=False)
    
    async def _flush_mp3_buffer(self, flush: bool = False):
        """Convert accumulated MP3 to PCM and send to Discord."""
        if self._mp3_buffer.tell() == 0:
            return
        
        self._mp3_buffer.seek(0)
        mp3_data = self._mp3_buffer.read()
        self._mp3_buffer.seek(0)
        self._mp3_buffer.truncate()
        
        # Convert MP3 to PCM for Discord (48kHz stereo 16-bit)
        pcm_data = self._convert_mp3_to_pcm(mp3_data)
        if pcm_data:
            await self.on_audio_output(pcm_data, flush)
    
    def _convert_mp3_to_pcm(self, mp3_data: bytes) -> Optional[bytes]:
        """
        Convert MP3 audio to PCM for Discord playback.
        
        Discord expects: 48000 Hz, 16-bit signed, stereo
        """
        if not mp3_data or not HAS_PYDUB:
            if not HAS_PYDUB:
                print("⚠️ pydub not available - cannot convert TTS audio")
            return None
        
        try:
            # Load MP3
            audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
            
            # Convert to Discord format
            audio = audio.set_channels(2).set_frame_rate(48000).set_sample_width(2)
            
            return audio.raw_data
        
        except Exception as e:
            print(f"⚠️ MP3 to PCM conversion failed: {e}")
            return None
    
    async def _send_status(self):
        """Send current status."""
        if self.on_status:
            await self.on_status(self.is_listening, self.is_speaking)
