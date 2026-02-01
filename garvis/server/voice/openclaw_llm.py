"""
OpenClaw LLM integration for conversational responses with persistent memory and tools.

OpenClaw provides:
- Persistent memory across sessions (JSONL storage)
- Tool calling that works across all providers
- Session management with compaction
- Multi-agent routing

This client connects to OpenClaw Gateway's OpenAI-compatible HTTP API.
"""

import json
import re
from typing import AsyncGenerator, Optional, Callable, Awaitable
import httpx

from config import (
    OPENCLAW_GATEWAY_URL,
    OPENCLAW_GATEWAY_TOKEN,
    OPENCLAW_AGENT_ID,
    OPENCLAW_SESSION_KEY,
    CLAUDE_SYSTEM_PROMPT,  # Use same system prompt as Claude
)


class OpenClawLLM:
    """
    OpenClaw integration for generating conversational responses.
    
    Connects to OpenClaw Gateway's HTTP API which provides:
    - Persistent memory (conversation history survives restarts)
    - Tool execution across any provider
    - Session management with automatic compaction
    - Multi-model support (routes to configured provider)
    
    Features:
    - Streaming responses via SSE for low-latency TTS
    - Conversation history support (handled by OpenClaw)
    - Tool calling support
    - Configurable system prompt
    - Cancellation support for barge-in interruption
    """
    
    def __init__(self, system_prompt: str = CLAUDE_SYSTEM_PROMPT):
        self.gateway_url = OPENCLAW_GATEWAY_URL.rstrip("/")
        self.token = OPENCLAW_GATEWAY_TOKEN
        self.agent_id = OPENCLAW_AGENT_ID
        self.session_key = OPENCLAW_SESSION_KEY
        self.system_prompt = system_prompt
        
        # Cancellation support for barge-in
        self._cancel_requested = False
        
        # HTTP client with longer timeouts for streaming
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0)
        )
    
    def cancel(self):
        """
        Request cancellation of current stream.
        
        Called during barge-in when the user interrupts the bot.
        The streaming loop checks this flag and exits early.
        """
        self._cancel_requested = True
    
    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_requested
    
    def _get_headers(self) -> dict:
        """Get HTTP headers for OpenClaw API requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    async def stream_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from OpenClaw given conversation history.
        
        OpenClaw handles persistent memory, so we only send the latest
        user message. OpenClaw maintains the full conversation context
        based on the session key.
        
        Supports cancellation via cancel() for barge-in interruption.
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Yields:
            Text chunks as they're generated
        """
        # Reset cancellation flag at start of new stream
        self._cancel_requested = False
        
        if not conversation_history:
            return
        
        # Build messages - include system prompt and recent history
        # OpenClaw maintains its own memory, but we still send context
        # for the current session turn
        messages = []
        
        # Add system prompt as first message
        if self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt
            })
        
        # Add conversation history (OpenClaw will dedupe with its memory)
        messages.extend(conversation_history)
        
        # Build request payload
        payload = {
            "model": self.agent_id,  # OpenClaw uses model field for agent routing
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "user": self.session_key,  # Session key for persistent memory
        }
        
        url = f"{self.gateway_url}/v1/chat/completions"
        
        try:
            async with self._client.stream(
                "POST",
                url,
                headers=self._get_headers(),
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    print(f"❌ OpenClaw error {response.status_code}: {error_text.decode()}")
                    yield f"I apologize, but I encountered an error connecting to OpenClaw."
                    return
                
                # Process SSE stream
                async for line in response.aiter_lines():
                    # Check for cancellation (barge-in)
                    if self._cancel_requested:
                        print("🛑 LLM stream cancelled (barge-in)")
                        break
                    
                    if not line:
                        continue
                    
                    # SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        
                        # Check for stream end
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            
                            # Extract content delta from OpenAI-compatible response
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                                
                                # Check for finish reason
                                finish_reason = choices[0].get("finish_reason")
                                if finish_reason == "stop":
                                    break
                        
                        except json.JSONDecodeError:
                            # Skip malformed JSON lines
                            continue
        
        except httpx.ConnectError as e:
            print(f"❌ OpenClaw connection error: {e}")
            print(f"   Make sure OpenClaw Gateway is running at {self.gateway_url}")
            yield "I apologize, but I cannot connect to OpenClaw. Please make sure the gateway is running."
        
        except Exception as e:
            if not self._cancel_requested:
                print(f"❌ OpenClaw error: {e}")
                yield f"I apologize, but I encountered an error: {str(e)}"
    
    async def stream_response_with_tools(
        self,
        conversation_history: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[str]],
        max_tokens: int = 1024,
        max_tool_iterations: int = 10
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a response from OpenClaw with tool calling support.
        
        Note: OpenClaw handles tool execution internally, so this method
        primarily provides compatibility with the existing interface.
        For full tool support, OpenClaw should be configured with the
        appropriate tools in its agent configuration.
        
        Args:
            conversation_history: List of messages
            tool_executor: Async function to execute tools (may be called by OpenClaw internally)
            max_tokens: Maximum tokens in response
            max_tool_iterations: Maximum number of tool call rounds
            
        Yields:
            Dicts with:
                - {"type": "text", "content": "..."} for text chunks
                - {"type": "tool_use", "name": "...", "input": {...}} when tool is called
                - {"type": "tool_result", "name": "...", "result": "..."} after tool execution
                - {"type": "stream_url", "url": "..."} when [DISPLAY_STREAM:url] is detected
        """
        # For now, use the simple streaming method
        # OpenClaw handles tool execution internally
        text_buffer = ""
        
        async for chunk in self.stream_response(conversation_history, max_tokens):
            text_buffer += chunk
            yield {"type": "text", "content": chunk}
            
            # Check for stream URL markers in accumulated text
            if "[DISPLAY_STREAM:" in text_buffer:
                match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', text_buffer)
                if match:
                    yield {"type": "stream_url", "url": match.group(1)}
                    # Clear the marker from buffer to avoid duplicate yields
                    text_buffer = text_buffer.replace(match.group(0), "")
    
    async def get_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> str:
        """
        Get a complete response from OpenClaw (non-streaming).
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Returns:
            Complete response text
        """
        chunks = []
        async for chunk in self.stream_response(conversation_history, max_tokens):
            chunks.append(chunk)
        return "".join(chunks)
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
