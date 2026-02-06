"""
Local LLM integration using llama.cpp with OpenAI-compatible API.
Supports tool calling for content streaming.

This replaces the Claude integration for fully local inference.
Optimized for Qwen2.5-7B-Instruct running on llama.cpp with CUDA.
"""

import json
import re
from typing import AsyncGenerator, Optional, Callable, Awaitable
from openai import AsyncOpenAI

from config import (
    LOCAL_LLM_URL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_SYSTEM_PROMPT,
    MAX_CONVERSATION_TURNS,
)
from tools import get_claude_tools


class LocalLLM:
    """
    Local LLM integration using llama.cpp's OpenAI-compatible API.
    
    Features:
    - Streaming responses for low-latency TTS
    - Conversation history support
    - Tool calling support (OpenAI function calling format)
    - Configurable system prompt
    - Cancellation support for barge-in interruption
    """
    
    def __init__(self, system_prompt: str = LOCAL_LLM_SYSTEM_PROMPT):
        self.client = AsyncOpenAI(
            base_url=LOCAL_LLM_URL,
            api_key="not-needed"  # llama.cpp doesn't require auth
        )
        self.system_prompt = system_prompt
        self.model = LOCAL_LLM_MODEL
        self.tools = self._convert_tools_to_openai_format(get_claude_tools())
        
        # Cancellation support for barge-in
        self._cancel_requested = False
    
    def _convert_tools_to_openai_format(self, claude_tools: list[dict]) -> list[dict]:
        """Convert Claude tool format to OpenAI function calling format."""
        openai_tools = []
        for tool in claude_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"]
                }
            })
        return openai_tools
    
    def cancel(self):
        """
        Request cancellation of current stream.
        Called during barge-in when the user interrupts the bot.
        """
        self._cancel_requested = True
    
    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_requested
    
    async def stream_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from the local LLM.
        NOTE: This method does NOT support tool calling.
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Yields:
            Text chunks as they're generated
        """
        self._cancel_requested = False
        
        # Truncate conversation history to last N turns to reduce token count
        max_messages = MAX_CONVERSATION_TURNS * 2
        recent_history = conversation_history[-max_messages:] if len(conversation_history) > max_messages else conversation_history
        
        # Build messages with system prompt
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(recent_history)
        
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True
            )
            
            async for chunk in stream:
                if self._cancel_requested:
                    print("🛑 LLM stream cancelled (barge-in)")
                    break
                
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        
        except Exception as e:
            if not self._cancel_requested:
                print(f"❌ Local LLM error: {e}")
                yield f"I apologize, but I encountered an error: {str(e)}"
    
    async def stream_response_with_tools(
        self,
        conversation_history: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[str]],
        max_tokens: int = 1024,
        max_tool_iterations: int = 10
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a response from the local LLM with tool calling support.
        
        Args:
            conversation_history: List of messages
            tool_executor: Async function to execute tools: (tool_name, args) -> result string
            max_tokens: Maximum tokens in response
            max_tool_iterations: Maximum number of tool call rounds
            
        Yields:
            Dicts with:
                - {"type": "text", "content": "..."} for text chunks
                - {"type": "tool_use", "name": "...", "input": {...}} when tool is called
                - {"type": "tool_result", "name": "...", "result": "..."} after tool execution
                - {"type": "stream_url", "url": "..."} when [DISPLAY_STREAM:url] is detected
        """
        # Build messages with system prompt
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(conversation_history)
        
        iterations = 0
        
        while iterations < max_tool_iterations:
            iterations += 1
            
            try:
                # Make API call with tools
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    tools=self.tools if self.tools else None,
                    tool_choice="auto" if self.tools else None
                )
                
                choice = response.choices[0]
                message = choice.message
                
                # Process text content
                text_content = message.content or ""
                if text_content:
                    yield {"type": "text", "content": text_content}
                    
                    # Check for stream URL in text content
                    if "[DISPLAY_STREAM:" in text_content:
                        match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', text_content)
                        if match:
                            yield {"type": "stream_url", "url": match.group(1)}
                
                # Check for tool calls
                tool_calls = message.tool_calls or []
                
                if not tool_calls:
                    # No tool calls, we're done
                    break
                
                # Process tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    yield {"type": "tool_use", "name": tool_name, "input": tool_args}
                    
                    # Execute the tool
                    result = await tool_executor(tool_name, tool_args)
                    
                    yield {"type": "tool_result", "name": tool_name, "result": result}
                    
                    # Check for stream URL in tool result
                    if "[DISPLAY_STREAM:" in result:
                        match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', result)
                        if match:
                            yield {"type": "stream_url", "url": match.group(1)}
                
                # Add assistant message and tool results to messages for next iteration
                messages.append({
                    "role": "assistant",
                    "content": text_content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in tool_calls
                    ]
                })
                
                # Add tool results
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    result = await tool_executor(tool_name, tool_args)
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                
                # Check finish reason
                if choice.finish_reason == "stop":
                    break
            
            except Exception as e:
                print(f"❌ Local LLM error: {e}")
                yield {"type": "text", "content": f"I apologize, but I encountered an error: {str(e)}"}
                break
    
    async def get_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> str:
        """
        Get a complete response from the local LLM (non-streaming).
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Returns:
            Complete response text
        """
        # Build messages with system prompt
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(conversation_history)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content or ""
        
        except Exception as e:
            print(f"❌ Local LLM error: {e}")
            return f"I apologize, but I encountered an error: {str(e)}"
