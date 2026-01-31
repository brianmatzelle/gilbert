"""
Voice WebSocket endpoint for real-time audio streaming
"""

import asyncio
import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .pipeline import VoicePipeline

router = APIRouter(tags=["voice"])


class VoiceConnectionManager:
    """Manages WebSocket connections for voice streaming"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.pipelines: dict[WebSocket, VoicePipeline] = {}
    
    async def connect(self, websocket: WebSocket) -> VoicePipeline:
        """Accept a new voice connection and create a pipeline"""
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # Create a voice pipeline for this connection
        pipeline = VoicePipeline(websocket)
        self.pipelines[websocket] = pipeline
        
        print(f"🎤 Voice client connected. Total: {len(self.active_connections)}")
        return pipeline
    
    def disconnect(self, websocket: WebSocket):
        """Clean up a disconnected voice client"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        if websocket in self.pipelines:
            pipeline = self.pipelines.pop(websocket)
            asyncio.create_task(pipeline.cleanup())
        
        print(f"🔌 Voice client disconnected. Total: {len(self.active_connections)}")


# Global connection manager
manager = VoiceConnectionManager()


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time voice streaming.
    
    Client sends:
    - Binary audio chunks (PCM 16-bit, 16kHz mono)
    - JSON control messages: {"type": "start"}, {"type": "stop"}, {"type": "config", ...}
    
    Server sends:
    - JSON transcripts: {"type": "transcript", "text": "...", "is_final": true/false, "role": "user/assistant"}
    - Binary TTS audio chunks (PCM 16-bit, 24kHz mono)
    - JSON status: {"type": "status", "listening": true/false, "speaking": true/false}
    """
    pipeline = await manager.connect(websocket)
    
    try:
        # Start the pipeline
        await pipeline.start()
        
        while True:
            message = await websocket.receive()
            
            if "bytes" in message:
                # Binary audio data from client microphone
                await pipeline.process_audio(message["bytes"])
            
            elif "text" in message:
                # JSON control message
                try:
                    data = json.loads(message["text"])
                    await pipeline.handle_control(data)
                except json.JSONDecodeError:
                    print(f"⚠️ Invalid JSON from client: {message['text'][:100]}")
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"❌ Voice WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)

