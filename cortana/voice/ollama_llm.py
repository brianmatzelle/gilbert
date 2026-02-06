"""
Ollama LLM integration for Cortana.

Uses the Ollama Python SDK for local LLM inference.
Simple streaming interface optimized for voice conversations.
"""

import asyncio
from typing import AsyncIterator, Optional

# Ollama Python SDK
try:
    from ollama import AsyncClient
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    print("⚠️ Ollama SDK not installed. Run: pip install ollama")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OLLAMA_URL, OLLAMA_MODEL, CORTANA_SYSTEM_PROMPT


class OllamaLLM:
    """
    Ollama LLM client for Cortana.
    
    Features:
    - Async streaming responses for low latency
    - Simple conversation history management
    - Cancellation support for barge-in
    """
    
    def __init__(
        self,
        model: str = OLLAMA_MODEL,
        system_prompt: str = CORTANA_SYSTEM_PROMPT,
        base_url: str = OLLAMA_URL,
    ):
        """
        Args:
            model: Ollama model name (e.g., "huihui_ai/qwen3-abliterated:8b")
            system_prompt: System prompt for the assistant
            base_url: Ollama API base URL
        """
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url
        
        self._client: Optional[AsyncClient] = None
        self._cancelled = False
    
    def _get_client(self) -> AsyncClient:
        """Get or create the Ollama async client."""
        if self._client is None:
            self._client = AsyncClient(host=self.base_url)
        return self._client
    
    async def stream_response(
        self,
        conversation_history: list[dict]
    ) -> AsyncIterator[str]:
        """
        Stream a response from Ollama.
        
        Args:
            conversation_history: List of {"role": "user/assistant", "content": "..."}
            
        Yields:
            Text chunks as they're generated
        """
        if not HAS_OLLAMA:
            yield "Ollama SDK not installed. Please run: pip install ollama"
            return
        
        self._cancelled = False
        
        # Build messages with system prompt
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(conversation_history)
        
        client = self._get_client()
        
        try:
            stream = await client.chat(
                model=self.model,
                messages=messages,
                stream=True,
            )
            
            async for chunk in stream:
                if self._cancelled:
                    break
                
                # Extract content from chunk
                if chunk and "message" in chunk:
                    content = chunk["message"].get("content", "")
                    if content:
                        yield content
        
        except Exception as e:
            print(f"❌ Ollama error: {e}")
            yield f"Sorry, I encountered an error: {str(e)}"
    
    def cancel(self):
        """Cancel the current streaming response (for barge-in)."""
        self._cancelled = True
    
    async def close(self):
        """Clean up resources."""
        self._client = None


async def test_ollama():
    """Quick test for Ollama connection."""
    print(f"Testing Ollama at {OLLAMA_URL} with model {OLLAMA_MODEL}...")
    
    llm = OllamaLLM()
    
    messages = [{"role": "user", "content": "Hello, who are you?"}]
    
    response = ""
    async for chunk in llm.stream_response(messages):
        print(chunk, end="", flush=True)
        response += chunk
    
    print(f"\n\nFull response: {response}")
    await llm.close()


if __name__ == "__main__":
    asyncio.run(test_ollama())
