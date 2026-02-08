"""
Local LLM integration using llama.cpp with OpenAI-compatible API.
Supports tool calling for content streaming.

This replaces the Claude integration for fully local inference.
Optimized for Qwen2.5-7B-Instruct running on llama.cpp with CUDA.
"""

import json
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
        
        Text is streamed in real-time for low-latency TTS.  When the
        model calls a tool, we execute it locally and feed the result
        back for a follow-up streamed response.
        
        Args:
            conversation_history: List of messages
            tool_executor: Async function: (tool_name, args_dict) -> result string
            max_tokens: Maximum tokens in response
            max_tool_iterations: Max tool→response round-trips
            
        Yields:
            Dicts with:
                - {"type": "text", "content": "..."} for text chunks
                - {"type": "tool_use", "name": "...", "input": {...}} when a tool is called
                - {"type": "tool_result", "name": "...", "result": "..."} after execution
        """
        self._cancel_requested = False
        
        # Build messages with system prompt
        messages = [{"role": "system", "content": self.system_prompt}]
        max_messages = MAX_CONVERSATION_TURNS * 2
        recent = conversation_history[-max_messages:] if len(conversation_history) > max_messages else conversation_history
        messages.extend(recent)
        
        iterations = 0
        
        while iterations < max_tool_iterations:
            iterations += 1
            
            try:
                # Stream the response so text arrives in real-time
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    tools=self.tools if self.tools else None,
                    tool_choice="auto" if self.tools else None,
                    stream=True,
                )
                
                text_content = ""
                # Accumulate tool calls streamed incrementally
                tool_calls_acc: dict[int, dict] = {}
                finish_reason = None
                
                async for chunk in stream:
                    if self._cancel_requested:
                        print("🛑 LLM stream cancelled (barge-in)")
                        break
                    
                    if not chunk.choices:
                        continue
                    
                    choice = chunk.choices[0]
                    delta = choice.delta
                    
                    # ---- streamed text ----
                    if delta.content:
                        text_content += delta.content
                        yield {"type": "text", "content": delta.content}
                    
                    # ---- streamed tool_calls (incremental) ----
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if tc.index is not None else 0
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments
                    
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                
                if self._cancel_requested:
                    break
                
                # No tool calls → we're done
                if not tool_calls_acc or finish_reason not in ("tool_calls", "function_call"):
                    break
                
                # -- execute tools locally and feed results back --
                
                # 1) Add assistant message (text + tool_calls)
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": text_content or None,
                    "tool_calls": [
                        {
                            "id": tc_data["id"],
                            "type": "function",
                            "function": {
                                "name": tc_data["name"],
                                "arguments": tc_data["arguments"],
                            },
                        }
                        for _, tc_data in sorted(tool_calls_acc.items())
                    ],
                }
                messages.append(assistant_msg)
                
                # 2) Execute each tool once and append results
                for _, tc_data in sorted(tool_calls_acc.items()):
                    name = tc_data["name"]
                    try:
                        args = json.loads(tc_data["arguments"])
                    except json.JSONDecodeError:
                        args = {}
                    
                    yield {"type": "tool_use", "name": name, "input": args}
                    result = await tool_executor(name, args)
                    yield {"type": "tool_result", "name": name, "result": result}
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_data["id"],
                        "content": result,
                    })
                
                # Loop continues → next iteration streams the follow-up
            
            except Exception as e:
                if not self._cancel_requested:
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
