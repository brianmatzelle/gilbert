"""
Base provider class for content streaming sources.
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class ContentProvider(ABC):
    """Base class for content streaming providers"""

    def __init__(self):
        self.name = "Base Provider"
        self.content_type = "unknown"  # "sports", "movies", "tv"
        self.base_url = ""

    @abstractmethod
    async def search(self, query: str) -> List[dict]:
        """
        Search for content matching the query.

        Args:
            query: Search terms to find content

        Returns:
            List of dicts with:
                - title: Content title
                - url: Content URL
                - metadata: Additional info (league/genre/etc)
                - time: Time information (if available)
                - provider: Provider name
        """
        pass

    @abstractmethod
    async def get_stream_info(self, content_url: str) -> Optional[dict]:
        """
        Extract stream information from content page URL.

        Args:
            content_url: URL to the content page

        Returns:
            dict with stream details:
                - embed_url: Direct embed URL
                - channel: Channel number (if applicable)
                - source: Stream source identifier
                - label: Stream label/quality
                - provider: Provider name
            Returns None if stream info cannot be extracted
        """
        pass

    def can_handle_url(self, url: str) -> bool:
        """
        Check if this provider can handle the given URL.

        Args:
            url: URL to check

        Returns:
            True if this provider can handle the URL
        """
        return self.base_url in url

