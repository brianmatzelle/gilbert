"""
Health check endpoints
"""

from fastapi import APIRouter

from config import APP_NAME, APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": APP_NAME,
        "version": APP_VERSION
    }


@router.get("/ping")
async def ping():
    """Simple ping endpoint"""
    return {"status": "pong"}

