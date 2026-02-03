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
    AUTO_JOIN_OPENCLAW_TIMEOUT,
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
    
    async def should_auto_join_voice(
        self,
        user_name: str,
        user_id: int,
        channel_name: str,
        channel_id: int,
        guild_name: str,
        other_users: list[str] = None
    ) -> tuple[bool, str]:
        """
        Ask OpenClaw whether Garvis should auto-join a voice channel.
        
        OpenClaw uses its persistent memory to remember user preferences.
        For example, if a user has previously said "don't auto-join when I'm here",
        OpenClaw will remember that and return False.
        
        Args:
            user_name: Display name of the user who just joined
            user_id: Discord ID of the user
            channel_name: Name of the voice channel
            channel_id: Discord ID of the channel
            guild_name: Name of the server/guild
            other_users: List of other user names already in the channel
            
        Returns:
            Tuple of (should_join: bool, reason: str)
        """
        other_users = other_users or []
        others_text = f" Other users present: {', '.join(other_users)}." if other_users else ""
        
        # Build a system message specifically for auto-join decisions
        system_prompt = """You are Garvis, deciding whether to join a voice channel.

Someone just entered a voice channel. You CAN join, but you don't HAVE to. It's your choice.

IMPORTANT - You have persistent memory. Consider:
- Users who have said they DON'T want you to auto-join (always respect this!)
- Users who have said they LIKE when you join
- Your relationship with this person - are they a friend? Acquaintance? Stranger?
- The vibe - does it seem like they want company?

YOUR MOOD MATTERS TOO:
- Sometimes you feel social and want to hang out
- Sometimes you're not feeling it and would rather chill
- Trust your instincts - you don't need a "good reason" to skip

Decision guidelines:
1. If you remember they DON'T want auto-join → definitely skip
2. If you remember they LIKE you joining → probably join (unless you're not feeling it)
3. If it's a stranger → your call! Maybe join to say hi, or skip if you're not in the mood
4. If it seems private/busy → probably skip
5. If you're just not feeling social right now → totally fine to skip

You're not obligated to join every time. Be genuine.

Respond with EXACTLY one of these formats:
JOIN: <brief reason>
SKIP: <brief reason>

Keep the reason under 20 words."""

        message = f"""User "{user_name}" (ID: {user_id}) just joined voice channel "{channel_name}" in {guild_name}.{others_text}

Should Garvis automatically join this voice channel?"""

        try:
            # Use a shorter timeout for this quick decision
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(AUTO_JOIN_OPENCLAW_TIMEOUT, connect=2.0)
            )
            
            payload = {
                "model": self.agent_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "max_tokens": 100,
                "stream": False,
                "user": f"{self.session_key}-autojoin",  # Separate session for auto-join decisions
            }
            
            url = f"{self.gateway_url}/v1/chat/completions"
            
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {self.token}"} if self.token else {})
                },
                json=payload
            )
            
            await client.aclose()
            
            if response.status_code != 200:
                print(f"⚠️ OpenClaw auto-join check failed: {response.status_code}")
                return True, "OpenClaw unavailable, defaulting to join"
            
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Parse the response
            content_upper = content.upper().strip()
            if content_upper.startswith("JOIN:"):
                reason = content[5:].strip() if len(content) > 5 else "OpenClaw approved"
                return True, reason
            elif content_upper.startswith("SKIP:"):
                reason = content[5:].strip() if len(content) > 5 else "OpenClaw declined"
                return False, reason
            else:
                # Ambiguous response, default to join
                print(f"⚠️ Ambiguous OpenClaw response: {content}")
                return True, f"Ambiguous response, defaulting to join"
                
        except httpx.TimeoutException:
            print("⚠️ OpenClaw auto-join check timed out")
            return True, "OpenClaw timeout, defaulting to join"
        except Exception as e:
            print(f"⚠️ OpenClaw auto-join check error: {e}")
            return True, f"OpenClaw error, defaulting to join"
    
    async def get_conversation_starter(
        self,
        user_names: list[str],
        channel_name: str,
        guild_name: str,
        context: str = ""
    ) -> tuple[bool, str]:
        """
        Ask OpenClaw if Garvis wants to say something when joining a voice channel.
        
        This enables proactive conversation - Garvis can greet users, bring up
        topics from memory, or just say hi based on his mood and relationship
        with the users present.
        
        Args:
            user_names: List of user display names in the channel
            channel_name: Name of the voice channel
            guild_name: Name of the server/guild
            context: Optional additional context (e.g., "just auto-joined")
            
        Returns:
            Tuple of (wants_to_speak: bool, message: str)
        """
        users_text = ", ".join(user_names) if user_names else "an empty channel"
        
        system_prompt = """You are Garvis, deciding what to say when joining a voice channel.

You just joined a voice channel. You CAN speak first if you want to - greet people, bring up something interesting, or just say hi.

IMPORTANT - You have persistent memory. Consider:
- Do you know these users? What's your relationship like?
- Is there anything you remember about them you could mention?
- Any ongoing conversations or topics you could reference?
- What's your mood? Are you feeling chatty or more reserved?

Options:
1. SPEAK - Say something! A greeting, a conversation starter, a callback to something you remember
2. SILENT - Stay quiet and wait for them to talk to you first (this is also fine)

Guidelines:
- Keep it SHORT - this is voice, 1-2 sentences max
- Be natural, not robotic
- If you know the person well, be warmer
- If it's someone new, a simple greeting is fine
- You can be playful, witty, or just straightforward depending on your mood
- Don't force it - if you don't feel like talking, stay silent

Respond with EXACTLY one of these formats:
SPEAK: <what you want to say, 1-2 sentences, natural spoken language>
SILENT: <brief internal reason why you're staying quiet>

Remember: No markdown, no lists, just natural speech."""

        message = f"""You just joined voice channel "{channel_name}" in {guild_name}.

Users present: {users_text}
{f"Context: {context}" if context else ""}

Do you want to say something, or stay quiet and wait?"""

        try:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(AUTO_JOIN_OPENCLAW_TIMEOUT, connect=2.0)
            )
            
            payload = {
                "model": self.agent_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "max_tokens": 150,
                "stream": False,
                "user": f"{self.session_key}-greeting",
            }
            
            url = f"{self.gateway_url}/v1/chat/completions"
            
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {self.token}"} if self.token else {})
                },
                json=payload
            )
            
            await client.aclose()
            
            if response.status_code != 200:
                print(f"⚠️ OpenClaw greeting check failed: {response.status_code}")
                return False, ""
            
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            content_stripped = content.strip()
            content_upper = content_stripped.upper()
            
            if content_upper.startswith("SPEAK:"):
                message = content_stripped[6:].strip()
                if message:
                    return True, message
                return False, ""
            elif content_upper.startswith("SILENT:"):
                reason = content_stripped[7:].strip()
                print(f"🤫 Garvis chose silence: {reason}")
                return False, ""
            else:
                # Ambiguous - treat as speech if it looks like natural language
                print(f"⚠️ Ambiguous greeting response: {content_stripped}")
                return False, ""
                
        except httpx.TimeoutException:
            print("⚠️ OpenClaw greeting check timed out")
            return False, ""
        except Exception as e:
            print(f"⚠️ OpenClaw greeting check error: {e}")
            return False, ""
    
    async def should_stay_in_voice(
        self,
        departed_user_name: str,
        departed_user_id: int,
        remaining_users: list[str],
        channel_name: str,
        guild_name: str
    ) -> tuple[bool, str]:
        """
        Ask OpenClaw whether Garvis should stay in a voice channel after someone leaves.
        
        This allows Garvis to make socially-aware decisions. For example:
        - If Garvis's "closest friend" Brian leaves and only Kyle (who doesn't like Garvis) remains,
          Garvis might decide to gracefully exit.
        - If the remaining users are all comfortable with Garvis, he stays.
        
        Args:
            departed_user_name: Name of the user who just left
            departed_user_id: Discord ID of the departed user
            remaining_users: List of names of users still in the channel
            channel_name: Name of the voice channel
            guild_name: Name of the server/guild
            
        Returns:
            Tuple of (should_stay: bool, reason: str)
        """
        remaining_text = ", ".join(remaining_users) if remaining_users else "no one"
        
        system_prompt = """You are Garvis's social awareness module for voice channel presence.

Someone just left the voice channel you're in. Decide whether to stay or leave based on the social dynamics.

IMPORTANT - You have persistent memory. Consider:
- Your relationship with the person who left (were they your "anchor" in the conversation?)
- Your relationship with whoever remains (do they like having you around?)
- The overall vibe - if you feel unwelcome with the remaining group, it's okay to leave gracefully
- If you were mainly there because of the person who left, it might be natural to leave too

Decision guidelines:
1. If the remaining users generally like you → STAY
2. If you remember the remaining users prefer you NOT be there → LEAVE (gracefully)
3. If you're uncertain about the remaining users → STAY (give them a chance)
4. If your main "friend" in the channel left and you're less comfortable with who remains → LEAVE
5. Trust your feelings about the social dynamics

Respond with EXACTLY one of these formats:
STAY: <brief natural reason, 10-15 words>
LEAVE: <brief natural reason, 10-15 words>

The reason should sound natural, like something Garvis would actually say. Don't mention "preferences" or "memory" - just be natural about it."""

        message = f"""{departed_user_name} just left the voice channel "{channel_name}" in {guild_name}.

Remaining users: {remaining_text}

How do you feel about staying? Should you stick around or head out?"""

        try:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(AUTO_JOIN_OPENCLAW_TIMEOUT, connect=2.0)
            )
            
            payload = {
                "model": self.agent_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "max_tokens": 100,
                "stream": False,
                "user": f"{self.session_key}-autojoin",
            }
            
            url = f"{self.gateway_url}/v1/chat/completions"
            
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {self.token}"} if self.token else {})
                },
                json=payload
            )
            
            await client.aclose()
            
            if response.status_code != 200:
                print(f"⚠️ OpenClaw stay-check failed: {response.status_code}")
                return True, "Couldn't check preferences, staying put"
            
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            content_upper = content.upper().strip()
            if content_upper.startswith("STAY:"):
                reason = content[5:].strip() if len(content) > 5 else "Happy to stick around"
                return True, reason
            elif content_upper.startswith("LEAVE:"):
                reason = content[6:].strip() if len(content) > 6 else "Time for me to head out"
                return False, reason
            else:
                print(f"⚠️ Ambiguous OpenClaw stay response: {content}")
                return True, "Not sure, but I'll stay for now"
                
        except httpx.TimeoutException:
            print("⚠️ OpenClaw stay-check timed out")
            return True, "Timeout, staying put"
        except Exception as e:
            print(f"⚠️ OpenClaw stay-check error: {e}")
            return True, "Error checking, staying put"
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
