"""
Vision tools for Garvis XR
- Face detection using DeepFace/RetinaFace
- Object detection using YOLOv8
"""

from .face_detect import (
    detect_faces,
    detect_faces_deepface,
    detect_faces_yolo_fallback,
    crop_face,
)
from .detect import (
    get_model,
    detect_objects,
    detect_objects_tool,
)

__all__ = [
    "detect_faces",
    "detect_faces_deepface",
    "detect_faces_yolo_fallback",
    "crop_face",
    "get_model",
    "detect_objects",
    "detect_objects_tool",
]

