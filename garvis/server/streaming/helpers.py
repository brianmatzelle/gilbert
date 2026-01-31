"""
Streaming helper functions for fetching stream URLs.
"""

import httpx
import json
from typing import List

from config import USER_AGENT, stream_cache


async def get_stream_urls(channel: int = 548) -> List[str]:
    """
    Fetch stream URLs from sharkstreams API.

    Args:
        channel: Channel number to fetch streams for

    Returns:
        List of stream URLs (CDN URLs)
    """
    url = f"https://sharkstreams.net/get-stream.php?channel={channel}"
    headers = {
        'User-Agent': USER_AGENT,
        'Referer': f'https://sharkstreams.net/player.php?channel={channel}',
        'Accept': 'application/json'
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        data = json.loads(response.text)

        if 'urls' in data and len(data['urls']) > 0:
            # Cache the URLs
            stream_cache[channel] = data['urls']
            return data['urls']
        else:
            return []

