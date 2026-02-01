"""
Garvis Voice Assistant Server

FastAPI + FastMCP server providing:
- Real-time voice pipeline (Deepgram STT → Claude/OpenClaw → Eleven Labs TTS)
- WebSocket endpoint for voice streaming
- MCP tools for extensibility
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

from config import APP_NAME, APP_VERSION, ALLOWED_ORIGINS
from api import health_router
from voice import voice_router
from tools import register_tools

# Initialize FastMCP server
mcp = FastMCP(APP_NAME)

# Register tools
register_tools(mcp)

# Create MCP HTTP app
mcp_app = mcp.http_app(path="/garvis")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Lifespan manager for the application"""
    print(f"🚀 Starting {APP_NAME} v{APP_VERSION}")
    
    async with mcp_app.lifespan(app):
        yield
    
    print(f"👋 Shutting down {APP_NAME}")


# Create FastAPI app
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Real-time voice assistant using Deepgram, Claude/OpenClaw, and Eleven Labs",
    lifespan=app_lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(voice_router)

# Mount MCP app
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
