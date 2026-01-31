"""
Claude LLM integration for conversational responses with tool calling support
"""

from typing import AsyncGenerator, Optional, Callable, Awaitable
from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_SYSTEM_PROMPT
from tools import get_claude_tools


class ClaudeLLM:
    """
    Claude integration for generating conversational responses.
    
    Features:
    - Streaming responses for low-latency TTS
    - Conversation history support
    - Tool calling support for content streaming
    - Configurable system prompt
    """
    
    def __init__(self, system_prompt: str = CLAUDE_SYSTEM_PROMPT):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        
        self.client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self.system_prompt = system_prompt
        self.model = CLAUDE_MODEL
        self.tools = get_claude_tools()
    
    async def stream_response(
        self,
        conversation_history: list[dict],
        max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from Claude given conversation history.
        NOTE: This method does NOT support tool calling. Use stream_response_with_tools for tool support.
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            max_tokens: Maximum tokens in response
            
        Yields:
            Text chunks as they're generated
        """
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system_prompt,
                messages=conversation_history
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        
        except Exception as e:
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
                - {"type": "stream_url", "url": "..."} when [DISPLAY_STREAM:url] is detected
        """
        messages = list(conversation_history)
        iterations = 0
        
        while iterations < max_tool_iterations:
            iterations += 1
            
            try:
                # Make API call with tools
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=self.system_prompt,
                    messages=messages,
                    tools=self.tools
                )
                
                # Process response content blocks
                text_content = ""
                tool_uses = []
                
                for block in response.content:
                    if block.type == "text":
                        text_content += block.text
                        yield {"type": "text", "content": block.text}
                    elif block.type == "tool_use":
                        tool_uses.append(block)
                        yield {"type": "tool_use", "name": block.name, "input": block.input}
                
                # Check for stream URL in text content
                if "[DISPLAY_STREAM:" in text_content:
                    import re
                    match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', text_content)
                    if match:
                        yield {"type": "stream_url", "url": match.group(1)}
                
                # If no tool calls, we're done
                if response.stop_reason == "end_turn" or not tool_uses:
                    break
                
                # Execute tools and add results to messages
                if tool_uses:
                    # Add assistant message with tool use
                    messages.append({
                        "role": "assistant",
                        "content": response.content
                    })
                    
                    # Execute each tool and collect results
                    tool_results = []
                    for tool_use in tool_uses:
                        tool_name = tool_use.name
                        tool_input = tool_use.input
                        
                        # Execute the tool
                        result = await tool_executor(tool_name, tool_input)
                        
                        yield {"type": "tool_result", "name": tool_name, "result": result}
                        
                        # Check for stream URL in tool result
                        if "[DISPLAY_STREAM:" in result:
                            import re
                            match = re.search(r'\[DISPLAY_STREAM:([^\]]+)\]', result)
                            if match:
                                yield {"type": "stream_url", "url": match.group(1)}
                        
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result
                        })
                    
                    # Add tool results to messages
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
            
            except Exception as e:
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
