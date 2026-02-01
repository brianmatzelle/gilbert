"""
API routers for Garvis server
"""

from .health import router as health_router

__all__ = ["health_router"]
