"""
Claude LLM integration for conversational responses with tool calling support
"""

from typing import AsyncGenerator, Optional, Callable, Awaitable
from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_SYSTEM_PROMPT, MAX_CONVERSATION_TURNS
from tools import get_claude_tools


class ClaudeLLM:
    """
    Claude integration for generating conversational responses.
    
    Features:
    - Streaming responses for low-latency TTS
    - Conversation history support
    - Tool calling support for content streaming
    - Configurable system prompt
    - Cancellation support for barge-in interruption
    """
    
    def __init__(self, system_prompt: str = CLAUDE_SYSTEM_PROMPT):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        
        self.client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self.system_prompt = system_prompt
        self.model = CLAUDE_MODEL
        self.tools = get_claude_tools()
        
        # Cancellation support for barge-in
        self._cancel_requested = False
    
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
    
    async def stream_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from Claude given conversation history.
        NOTE: This method does NOT support tool calling. Use stream_response_with_tools for tool support.
        
        Supports cancellation via cancel() for barge-in interruption.
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Yields:
            Text chunks as they're generated
        """
        # Reset cancellation flag at start of new stream
        self._cancel_requested = False
        
        # Truncate conversation history to last N turns to reduce token count
        max_messages = MAX_CONVERSATION_TURNS * 2
        recent_history = conversation_history[-max_messages:] if len(conversation_history) > max_messages else conversation_history
        
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system_prompt,
                messages=recent_history
            ) as stream:
                async for text in stream.text_stream:
                    # Check for cancellation (barge-in)
                    if self._cancel_requested:
                        print("🛑 LLM stream cancelled (barge-in)")
                        break
                    yield text
        
        except Exception as e:
            if not self._cancel_requested:  # Don't log errors during intentional cancellation
                print(f"❌ Claude error: {e}")
                yield f"I apologize, but I encountered an error: {str(e)}"
    
    async def stream_response_with_tools(
        self,
        conversation_history: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[str]],
        max_tokens: int = 1024,
        max_tool_iterations: int = 10
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a response from Claude with tool calling support.
        
        Uses the streaming API (messages.stream) so text flows to TTS in
        real-time even when tools are available. When the LLM decides to
        call a tool, the tool is executed and the result is fed back for
        a follow-up streamed response.
        
        Args:
            conversation_history: List of messages in Anthropic format
            tool_executor: Async function to execute tools: (tool_name, args) -> result string
            max_tokens: Maximum tokens in response
            max_tool_iterations: Maximum number of tool call rounds
            
        Yields:
            Dicts with:
                - {"type": "text", "content": "..."} for text chunks
                - {"type": "tool_use", "name": "...", "input": {...}} when tool is called
                - {"type": "tool_result", "name": "...", "result": "..."} after tool execution
        """
        self._cancel_requested = False
        
        # Truncate conversation history
        max_messages = MAX_CONVERSATION_TURNS * 2
        messages = list(conversation_history[-max_messages:]) if len(conversation_history) > max_messages else list(conversation_history)
        
        iterations = 0
        
        while iterations < max_tool_iterations:
            iterations += 1
            
            try:
                # Build kwargs – only include tools if we have any
                kwargs = dict(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=self.system_prompt,
                    messages=messages,
                )
                if self.tools:
                    kwargs["tools"] = self.tools
                
                # Stream the response (text arrives in real-time)
                async with self.client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        if self._cancel_requested:
                            break
                        yield {"type": "text", "content": text}
                    
                    if self._cancel_requested:
                        break
                    
                    # Get the complete message to check for tool calls
                    response = await stream.get_final_message()
                
                # Extract tool_use blocks
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                
                if response.stop_reason != "tool_use" or not tool_uses:
                    break  # No tools called, we're done
                
                # -- Tool execution loop --
                # Add the full assistant message (text + tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})
                
                tool_results = []
                for tool_use in tool_uses:
                    yield {"type": "tool_use", "name": tool_use.name, "input": tool_use.input}
                    
                    result = await tool_executor(tool_use.name, tool_use.input)
                    yield {"type": "tool_result", "name": tool_use.name, "result": result}
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    })
                
                # Feed tool results back so the LLM can respond
                messages.append({"role": "user", "content": tool_results})
                # Loop continues → next iteration streams the follow-up response
            
            except Exception as e:
                if not self._cancel_requested:
                    print(f"❌ Claude error: {e}")
                    yield {"type": "text", "content": f"I apologize, but I encountered an error: {str(e)}"}
                break
    
    async def get_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> str:
        """
        Get a complete response from Claude (non-streaming).
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Returns:
            Complete response text
        """
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system_prompt,
                messages=conversation_history
            )
            
            return response.content[0].text
        
        except Exception as e:
            print(f"❌ Claude error: {e}")
            return f"I apologize, but I encountered an error: {str(e)}"
