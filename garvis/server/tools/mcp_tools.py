"""
MCP tool definitions for content streaming.
"""

from typing import Optional
from fastmcp import FastMCP

from providers import get_providers_by_type, get_provider_by_url, PROVIDERS
from streaming import get_stream_urls

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
    global _mcp_instance
    _mcp_instance = mcp
    """Register all MCP tools with the FastMCP instance"""

    @mcp.tool()
    async def SEARCH_CONTENT(query: str = "", content_type: str = "sports") -> str:
        """
        Search for live content (sports, movies, TV shows) across all providers.

        Args:
            query: Search terms (e.g., "Missouri Oklahoma", "Chiefs", "Breaking Bad")
                   Leave empty to see all available content.
            content_type: Type of content - "sports", "movies", "tv", or "all" (default: "sports")

        Returns:
            Formatted list of available content with streaming information
        """
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

        # Format the results nicely
        result = f"Found {len(all_results)} item(s) across {len(providers)} provider(s):\n\n"

        for i, item in enumerate(all_results, 1):
            result += f"{i}. **{item['title']}**\n"
            result += f"   - Provider: {item['provider']}\n"
            result += f"   - Category: {item['metadata']}\n"
            if item['time']:
                result += f"   - Time: {item['time']}\n"
            result += f"   - URL: {item['url']}\n\n"

        result += "\nTo watch, use SHOW_CONTENT with the content URL:\n"
        result += f"Example: SHOW_CONTENT(content_url=\"{all_results[0]['url']}\")"

        return result

    @mcp.tool()
    async def SHOW_CONTENT(
        content_url: Optional[str] = None,
        channel: Optional[int] = None,
        source: str = "auto",
        cdn: int = 0,
        server_url: str = ""
    ) -> str:
        """
        Display live streaming content in the chat interface.

        Args:
            content_url: Content URL from any supported provider
            channel: Direct channel number for sharkstreams (optional, for legacy support)
            source: Stream source - "auto" (try all), "watchlive", or "sharkstreams" (default: "auto")
            cdn: CDN index to use for sharkstreams (default: 0)
            server_url: Base URL (leave empty for relative URLs that work with proxies)

        Returns:
            A marker string that the frontend will detect and render as a video player
        """

        # If content_url is provided, find the appropriate provider and get stream info
        if content_url:
            provider = get_provider_by_url(content_url)

            if not provider:
                return "Error: No provider found that can handle this URL. Please check the URL and try again."

            stream_info = await provider.get_stream_info(content_url)

            if stream_info:
                # Handle watchlive.top embeds
                if stream_info['source'] == 'watchlive' and source in ["auto", "watchlive"]:
                    # Use watchlive.top embed directly (no proxy needed)
                    embed_url = stream_info['embed_url']
                    return f"[DISPLAY_STREAM:{embed_url}]"

                # Handle sharkstreams URLs
                if stream_info['source'] == 'sharkstreams' and source in ["auto", "sharkstreams"]:
                    # Extract channel number and use our proxy
                    channel = int(stream_info['channel'])
                    # Continue to proxy setup below

            if not stream_info and source == "watchlive":
                return "Error: Could not extract stream information from the provided URL. The page format may have changed."

            # If we couldn't extract info and source is auto, try fallback to default channel
            if source == "auto" and not stream_info:
                # Try sharkstreams as fallback with a default channel
                if not channel:
                    channel = 548  # Default fallback channel

        # If no content_url or using sharkstreams source
        if source in ["auto", "sharkstreams"]:
            if not channel:
                channel = 548  # Default channel

            # Fetch the stream URLs to ensure they're cached
            try:
                urls = await get_stream_urls(channel)
                if not urls:
                    if source == "sharkstreams":
                        return f"Error: No streams found for channel {channel} on sharkstreams."
                    # If auto mode, we already tried other sources, so all failed
                    if content_url:
                        return "Error: Could not load stream from any source. The stream may not be available."
            except Exception as e:
                if source == "sharkstreams":
                    return f"Error: Failed to fetch stream from sharkstreams: {str(e)}"

            # Build the playlist proxy URL for sharkstreams
            playlist_url = f"{server_url}/mcp/proxy/playlist.m3u8?channel={channel}&cdn={cdn}"
            return f"[DISPLAY_STREAM:{playlist_url}]"

        # If we get here, something went wrong
        return "Error: Unable to load stream. Please check your parameters and try again."

    @mcp.tool()
    async def ping():
        """Ping endpoint for health checks"""
        return {
            "status": "pong",
            "service": "Garvis Voice Server",
            "version": "0.1.0",
            "providers": [p.name for p in PROVIDERS]
        }

