"""
Voice pipeline orchestrating Deepgram STT → Claude → Eleven Labs TTS
With tool calling support for content streaming
"""

import asyncio
import json
import re
from typing import Optional
from fastapi import WebSocket

from .deepgram_stt import DeepgramSTT
from .claude_llm import ClaudeLLM
from .elevenlabs_tts import ElevenLabsTTS

# Import tool functions for execution
from providers import get_providers_by_type, get_provider_by_url, PROVIDERS
from streaming import get_stream_urls


class VoicePipeline:
    """
    Orchestrates the real-time voice conversation flow:
    1. Receives audio from client
    2. Streams to Deepgram for real-time transcription
    3. On speech end (VAD), sends transcript to Claude with tools
    4. Executes any tool calls (SEARCH_CONTENT, SHOW_CONTENT)
    5. Streams Claude response to Eleven Labs TTS
    6. Streams TTS audio back to client
    7. Sends stream URLs to client for video playback
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
        """Normalize LLM output to fix unwanted phrases and remove markers."""
        # Remove [DISPLAY_STREAM:...] markers (they shouldn't be spoken)
        text = re.sub(r'\[DISPLAY_STREAM:[^\]]+\]', '', text)
        # Clean up any extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    @staticmethod
    def _extract_stream_url(text: str) -> Optional[str]:
        """Extract stream URL from [DISPLAY_STREAM:url] marker if present."""
        match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', text)
        return match.group(1) if match else None
    
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.stt: Optional[DeepgramSTT] = None
        self.llm: Optional[ClaudeLLM] = None
        self.tts: Optional[ElevenLabsTTS] = None
        
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history: list[dict] = []
        self.current_transcript = ""
        
        self._running = False
    
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
                    return "No content found matching your search. Try different keywords or check if content is currently available."
                
                result = f"Found {len(all_results)} item(s):\n\n"
                for i, item in enumerate(all_results[:5], 1):  # Limit to 5 for voice
                    result += f"{i}. {item['title']} ({item['metadata']})\n"
                    result += f"   URL: {item['url']}\n"
                
                result += "\nTo watch, use SHOW_CONTENT with a content URL."
                return result
            
            elif tool_name == "SHOW_CONTENT":
                content_url = args.get("content_url")
                channel = args.get("channel")
                source = args.get("source", "auto")
                cdn = args.get("cdn", 0)
                # Use relative URL so the XR client's Vite proxy handles it
                # This avoids mixed-content (HTTPS client -> HTTP server) issues
                server_url = ""
                
                if content_url:
                    provider = get_provider_by_url(content_url)
                    if not provider:
                        return "Error: No provider found for this URL."
                    
                    stream_info = await provider.get_stream_info(content_url)
                    
                    if stream_info:
                        if stream_info['source'] == 'watchlive' and source in ["auto", "watchlive"]:
                            embed_url = stream_info['embed_url']
                            return f"[DISPLAY_STREAM:{embed_url}]"
                        
                        if stream_info['source'] == 'sharkstreams' and source in ["auto", "sharkstreams"]:
                            channel = int(stream_info['channel'])
                
                # Sharkstreams proxy fallback
                if source in ["auto", "sharkstreams"]:
                    if not channel:
                        channel = 548
                    
                    try:
                        urls = await get_stream_urls(channel)
                        if not urls:
                            return f"Error: No streams found for channel {channel}."
                    except Exception as e:
                        return f"Error: Failed to fetch stream: {str(e)}"
                    
                    playlist_url = f"{server_url}/mcp/proxy/playlist.m3u8?channel={channel}&cdn={cdn}"
                    return f"[DISPLAY_STREAM:{playlist_url}]"
                
                return "Error: Unable to load stream."
            
            elif tool_name == "ping":
                return json.dumps({
                    "status": "pong",
                    "service": "Garvis Voice Server",
                    "providers": [p.name for p in PROVIDERS]
                })
            
            else:
                return f"Unknown tool: {tool_name}"
        
        except Exception as e:
            print(f"❌ Tool execution error: {e}")
            return f"Error executing tool: {str(e)}"
    
    async def start(self):
        """Initialize and start the pipeline components"""
        self._running = True
        
        # Initialize components
        self.stt = DeepgramSTT(
            on_transcript=self._handle_transcript,
            on_speech_end=self._handle_speech_end
        )
        self.llm = ClaudeLLM()
        self.tts = ElevenLabsTTS(on_audio=self._send_audio)
        
        # Connect to Deepgram
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
        
        # Forward audio to Deepgram STT
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
        """Handle transcript updates from Deepgram"""
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
        
        # Get Claude response with tool support
        self.is_speaking = True
        await self._send_status()
        
        assistant_response = ""
        stream_url_sent = False
        
        # Use tool-calling response flow
        async for event in self.llm.stream_response_with_tools(
            self.conversation_history,
            self._execute_tool
        ):
            event_type = event.get("type")
            
            if event_type == "text":
                # Accumulate text content
                assistant_response += event.get("content", "")
                
                # Normalize and send to TTS (strip markers)
                normalized = self._normalize_llm_output(assistant_response)
                if normalized:
                    # Send partial transcript to client (for display)
                    await self.websocket.send_json({
                        "type": "transcript",
                        "text": normalized,
                        "is_final": False,
                        "role": "assistant"
                    })
            
            elif event_type == "tool_use":
                # Notify client that a tool is being called
                print(f"🔧 Tool call: {event.get('name')} with {event.get('input')}")
            
            elif event_type == "tool_result":
                # Check tool result for stream URL
                result = event.get("result", "")
                stream_url = self._extract_stream_url(result)
                if stream_url and not stream_url_sent:
                    await self._send_stream_url(stream_url)
                    stream_url_sent = True
            
            elif event_type == "stream_url":
                # Direct stream URL event
                if not stream_url_sent:
                    await self._send_stream_url(event.get("url"))
                    stream_url_sent = True
        
        # Finalize response - normalize and remove markers
        final_response = self._normalize_llm_output(assistant_response)
        
        # Only add to history and TTS if there's actual text content
        if final_response:
            self.conversation_history.append({
                "role": "assistant",
                "content": final_response
            })
            
            # Send to TTS
            await self.tts.add_text(final_response)
            
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
    
    async def _send_stream_url(self, url: str):
        """Send stream URL to client for video playback"""
        if not self._running:
            return
        
        try:
            print(f"📺 Sending stream URL to client: {url}")
            await self.websocket.send_json({
                "type": "stream_url",
                "url": url
            })
        except Exception as e:
            print(f"Error sending stream URL: {e}")
    
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
