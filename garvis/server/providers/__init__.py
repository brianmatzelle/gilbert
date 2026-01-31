"""
Content provider system for streaming sources.
"""

from .base import ContentProvider
from .crackstreams import CrackStreamsProvider
from .registry import (
    PROVIDERS,
    get_provider_by_url,
    get_providers_by_type,
    get_all_providers
)

__all__ = [
    'ContentProvider',
    'CrackStreamsProvider',
    'PROVIDERS',
    'get_provider_by_url',
    'get_providers_by_type',
    'get_all_providers'
]

