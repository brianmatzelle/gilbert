"""
MCP tool definitions for Garvis.

Tools are registered with FastMCP and can be called by the LLM.
The tool system will be rebuilt when OpenClaw integration is complete.
"""

from typing import Optional
from fastmcp import FastMCP

# Module-level reference to the MCP instance (set after registration)
_mcp_instance: Optional[FastMCP] = None

# Tools to exclude from Claude (utility tools not meant for conversation)
EXCLUDED_TOOLS = {"ping"}


def get_claude_tools() -> list[dict]:
    """
    Dynamically extract tool definitions from registered MCP tools.
    Returns tools in Claude/Anthropic format.
    """
    if _mcp_instance is None:
        return []
    
    claude_tools = []
    for tool in _mcp_instance._tool_manager._tools.values():
        # Skip excluded tools
        if tool.name in EXCLUDED_TOOLS:
            continue
            
        claude_tools.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": {
                "type": "object",
                "properties": tool.parameters.get("properties", {}),
                "required": tool.parameters.get("required", [])
            }
        })
    
    return claude_tools


def get_tool_names() -> list[str]:
    """Get list of all registered tool names."""
    if _mcp_instance is None:
        return []
    return [t.name for t in _mcp_instance._tool_manager._tools.values()]


def register_tools(mcp: FastMCP):
    """Register all MCP tools with the FastMCP instance"""
    global _mcp_instance
    _mcp_instance = mcp

    @mcp.tool()
    async def ping():
        """Ping endpoint for health checks"""
        return {
            "status": "pong",
            "service": "Garvis Voice Server",
            "version": "0.1.0"
        }

    # ── Music Playback Tools ────────────────────────────────────────────

    @mcp.tool()
    async def play_music(url: str) -> dict:
        """Play music from a URL in the current voice channel.
        
        Supports YouTube, SoundCloud, and many other sites.
        If music is already playing, it will be replaced with the new song.
        
        Args:
            url: The URL of the song to play (e.g. a YouTube link).
            
        Returns:
            Status dict with title, duration, and playback status.
        """
        # This is a stub -- actual execution happens in voice_pipeline._execute_tool()
        # which has access to the MusicPlayer instance.
        return {"status": "error", "error": "No active voice session"}

    @mcp.tool()
    async def stop_music() -> dict:
        """Stop the currently playing music and clear the queue."""
        return {"status": "error", "error": "No active voice session"}

    @mcp.tool()
    async def set_music_volume(volume: float) -> dict:
        """Set the music playback volume.
        
        Args:
            volume: Volume level from 0.0 (silent) to 1.0 (full volume).
                    Default is 0.3. When Garvis speaks, music is automatically
                    ducked to a lower volume.
        """
        return {"status": "error", "error": "No active voice session"}
