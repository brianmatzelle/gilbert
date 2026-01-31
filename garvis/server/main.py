"""
Garvis XR Voice Assistant Server

FastAPI + FastMCP server providing:
- Real-time voice pipeline (Deepgram STT → Claude → Eleven Labs TTS)
- WebSocket endpoint for XR client voice streaming
- MCP tools for extensibility
- Content streaming with HLS proxy
- Face detection for XR camera overlay
"""

import base64
import io
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from pydantic import BaseModel
from PIL import Image

from config import APP_NAME, APP_VERSION, ALLOWED_ORIGINS
from api import health_router, proxy_router
from voice import voice_router
from tools import register_tools
from providers import get_all_providers
from tools.vision.face_detect import (
    detect_faces_deepface,
    detect_faces_yolo_fallback,
    crop_face,
)
from tools.vision.detect import get_model, detect_objects

# Initialize FastMCP server
mcp = FastMCP(APP_NAME)

# Register content streaming tools (SEARCH_CONTENT, SHOW_CONTENT, ping)
register_tools(mcp)

# Create MCP HTTP app
mcp_app = mcp.http_app(path="/garvis")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Lifespan manager for the application"""
    print(f"🚀 Starting {APP_NAME} v{APP_VERSION}")
    print(f"📺 Registered {len(get_all_providers())} content provider(s):")
    for provider in get_all_providers():
        print(f"   - {provider.name} ({provider.content_type})")
    
    async with mcp_app.lifespan(app):
        yield
    
    print(f"👋 Shutting down {APP_NAME}")


# Create FastAPI app
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Real-time voice assistant for XR applications using Deepgram, Claude, and Eleven Labs",
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
app.include_router(proxy_router)  # HLS proxy for video streaming
app.include_router(voice_router)

# Mount MCP app
app.mount("/mcp", mcp_app)


# ============================================================
# Face Detection Endpoint
# ============================================================

class FaceDetectRequest(BaseModel):
    """Request model for face detection"""
    image_base64: str
    confidence: float = 0.5
    max_detections: int = 10
    include_crops: bool = False


@app.post("/detect-faces")
async def detect_faces_endpoint(request: FaceDetectRequest):
    """
    Fast face detection endpoint.
    Returns bounding boxes for detected faces.
    
    Uses DeepFace (RetinaFace backend) for accurate face detection,
    with YOLO fallback if DeepFace fails.
    """
    try:
        # Decode base64 image
        image_data = base64.b64decode(request.image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Try DeepFace first, fall back to YOLO
        try:
            detections = detect_faces_deepface(image, request.confidence)
        except Exception as e:
            print(f"DeepFace failed, using YOLO fallback: {e}")
            detections = detect_faces_yolo_fallback(image, request.confidence, request.max_detections)
        
        # Limit detections
        detections = detections[:request.max_detections]
        
        # Optionally include face crops (for future identification)
        if request.include_crops:
            for det in detections:
                det['face_crop_base64'] = crop_face(image, det['bbox'])
        
        return {
            "success": True,
            "count": len(detections),
            "image_size": {
                "width": image.width,
                "height": image.height
            },
            "detections": detections
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "detections": []
        }


# ============================================================
# Object Detection Endpoint
# ============================================================

class DetectRequest(BaseModel):
    """Request model for object detection"""
    image_base64: str
    confidence: float = 0.5
    max_detections: int = 20


@app.post("/detect")
async def detect_objects_endpoint(request: DetectRequest):
    """
    Fast real-time object detection endpoint.
    Returns bounding boxes for detected objects using YOLOv8.
    """
    try:
        # Decode base64 image
        image_data = base64.b64decode(request.image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        detections = detect_objects(image, request.confidence, request.max_detections)
        
        return {
            "success": True,
            "count": len(detections),
            "image_size": {
                "width": image.width,
                "height": image.height
            },
            "detections": detections
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "detections": []
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
