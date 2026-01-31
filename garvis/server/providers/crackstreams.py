"""
CrackStreams provider for sports streaming.
"""

import httpx
import json
import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import ContentProvider
from config import USER_AGENT, HTTP_TIMEOUT


class CrackStreamsProvider(ContentProvider):
    """Provider for CrackStreams sports streaming"""

    def __init__(self):
        super().__init__()
        self.name = "CrackStreams"
        self.content_type = "sports"
        self.base_url = "crackstreams.ms"
        self.leagues = [
            ('nflstreams', 'NFL'),
            ('ncaa', 'NCAA'),
            ('nbaregular', 'NBA'),
            ('nhlstreams', 'NHL'),
            ('mmastreams', 'UFC/MMA'),
            ('boxingcasino', 'Boxing'),
            ('wwestreams', 'WWE'),
            ('mlbwildcard', 'MLB')
        ]

    async def search(self, query: str) -> List[dict]:
        """Search CrackStreams for sports games matching the query"""
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        query_lower = query.lower()
        results = []

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for league_slug, league_name in self.leagues:
                try:
                    url = f"https://{self.base_url}/league/{league_slug}"
                    response = await client.get(url, headers=headers, follow_redirects=True)
                    soup = BeautifulSoup(response.text, 'lxml')

                    # Find game listings - looking for links to /stream/ pages
                    game_links = soup.find_all('a', href=re.compile(r'/stream/'))

                    for link in game_links:
                        game_title = link.get_text(strip=True)
                        game_url = link.get('href', '')

                        # Make absolute URL if needed
                        if game_url.startswith('/'):
                            game_url = f"https://{self.base_url}{game_url}"

                        # Filter by query if provided
                        if query_lower:
                            if not any(word in game_title.lower() for word in query_lower.split()):
                                continue

                        # Try to find time information near the link
                        time_text = ""
                        parent = link.parent
                        if parent:
                            time_elem = parent.find(text=re.compile(r'\d{1,2}:\d{2}'))
                            if time_elem:
                                time_text = time_elem.strip()

                        # Avoid duplicates
                        if not any(r['url'] == game_url for r in results):
                            results.append({
                                'title': game_title,
                                'url': game_url,
                                'metadata': league_name,
                                'time': time_text,
                                'provider': self.name
                            })

                except Exception as e:
                    print(f"Error scraping {league_name}: {e}")
                    continue

        return results

    async def get_stream_info(self, content_url: str) -> Optional[dict]:
        """
        Extract stream information from CrackStreams game page.
        Scrapes the 'const allStreams = [...]' JavaScript variable.
        """
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': f'https://{self.base_url}/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(content_url, headers=headers, follow_redirects=True)
                html_content = response.text

                # Look for the allStreams JavaScript variable
                match = re.search(r'const allStreams = (\[.*?\]);', html_content)
                if not match:
                    return None

                streams_json = match.group(1)
                streams = json.loads(streams_json)

                if not streams or len(streams) == 0:
                    return None

                # Get the first stream
                first_stream = streams[0]
                embed_url = first_stream.get('value', '')

                if not embed_url:
                    return None

                # Check if it's a watchlive.top embed URL
                # Format: https://watchlive.top/embed/{sport}/{channel}-{channel}
                embed_match = re.search(r'/embed/([^/]+)/(\d+)-\d+', embed_url)
                if embed_match:
                    sport = embed_match.group(1)
                    channel = embed_match.group(2)

                    return {
                        'embed_url': embed_url,
                        'channel': channel,
                        'sport': sport,
                        'source': 'watchlive',
                        'label': first_stream.get('label', 'Stream'),
                        'provider': self.name
                    }

                # Check if it's a sharkstreams player URL
                # Format: https://sharkstreams.net/player.php?channel=601
                shark_match = re.search(r'sharkstreams\.net/player\.php\?channel=(\d+)', embed_url)
                if shark_match:
                    channel = shark_match.group(1)

                    return {
                        'embed_url': embed_url,
                        'channel': channel,
                        'sport': 'unknown',
                        'source': 'sharkstreams',
                        'label': first_stream.get('label', 'Stream'),
                        'provider': self.name
                    }

                return None

        except Exception as e:
            print(f"Error scraping CrackStreams URL {content_url}: {e}")
            return None

