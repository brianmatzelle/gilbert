"""
Face Detection using RetinaFace via DeepFace

Fast, accurate face detection for XR applications.
Uses DeepFace with RetinaFace backend for high-quality face detection,
with YOLO fallback for robustness.
"""
import base64
import io
import json
from PIL import Image
import numpy as np

# Lazy load to avoid import errors
_detector = None


def get_face_detector():
    """Lazy load face detector (RetinaFace via DeepFace)"""
    global _detector
    if _detector is None:
        try:
            from deepface import DeepFace
            _detector = DeepFace
            print("✅ DeepFace face detector loaded")
        except ImportError:
            print("⚠️ DeepFace not available, falling back to YOLO person detection")
            from ultralytics import YOLO
            _detector = YOLO("yolov8n.pt")
    return _detector


def detect_faces_deepface(image: Image.Image, confidence_threshold: float = 0.5):
    """Detect faces using DeepFace (RetinaFace backend)"""
    from deepface import DeepFace
    
    # Convert PIL to numpy array
    img_array = np.array(image)
    
    try:
        # Use RetinaFace for detection (most accurate)
        faces = DeepFace.extract_faces(
            img_path=img_array,
            detector_backend='retinaface',
            enforce_detection=False,
            align=False
        )
        
        detections = []
        for i, face in enumerate(faces):
            if face['confidence'] < confidence_threshold:
                continue
                
            facial_area = face['facial_area']
            x1 = facial_area['x']
            y1 = facial_area['y']
            x2 = x1 + facial_area['w']
            y2 = y1 + facial_area['h']
            
            # Calculate center and dimensions
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            width = x2 - x1
            height = y2 - y1
            
            detections.append({
                "id": i,
                "class": "face",
                "confidence": round(float(face['confidence']), 3),
                "bbox": {
                    "x1": round(x1, 1),
                    "y1": round(y1, 1),
                    "x2": round(x2, 1),
                    "y2": round(y2, 1),
                },
                "center": {
                    "x": round(center_x, 1),
                    "y": round(center_y, 1),
                },
                "dimensions": {
                    "width": round(width, 1),
                    "height": round(height, 1),
                },
                "face_crop_base64": None  # Populated if include_crops=True
            })
        
        return detections
        
    except Exception as e:
        print(f"DeepFace detection error: {e}")
        return []


def detect_faces_yolo_fallback(image: Image.Image, confidence_threshold: float = 0.5, max_detections: int = 10):
    """Fallback: Detect persons using YOLO and estimate face region"""
    from ultralytics import YOLO
    
    model = YOLO("yolov8n.pt")
    results = model(image, conf=confidence_threshold, verbose=False)
    
    detections = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
            
        for i, box in enumerate(boxes):
            if i >= max_detections:
                break
                
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            
            # Only keep person detections as proxy for face
            if class_name != "person":
                continue
            
            xyxy = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            
            x1, y1, x2, y2 = xyxy
            width = x2 - x1
            height = y2 - y1
            
            # Estimate face region as top 30% of person bbox
            face_y2 = y1 + height * 0.3
            center_x = (x1 + x2) / 2
            
            detections.append({
                "id": i,
                "class": "face",
                "confidence": round(confidence, 3),
                "bbox": {
                    "x1": round(x1, 1),
                    "y1": round(y1, 1),
                    "x2": round(x2, 1),
                    "y2": round(face_y2, 1),
                },
                "center": {
                    "x": round(center_x, 1),
                    "y": round((y1 + face_y2) / 2, 1),
                },
                "dimensions": {
                    "width": round(width, 1),
                    "height": round(face_y2 - y1, 1),
                },
                "face_crop_base64": None
            })
    
    return detections


def crop_face(image: Image.Image, bbox: dict, padding: float = 0.2) -> str:
    """
    Crop face from image and return as base64.
    
    Args:
        image: PIL Image
        bbox: Bounding box dict with x1, y1, x2, y2
        padding: Padding around face as fraction of dimensions
    
    Returns:
        Base64 encoded JPEG of cropped face
    """
    x1, y1, x2, y2 = bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2']
    width = x2 - x1
    height = y2 - y1
    
    # Add padding
    pad_w = width * padding
    pad_h = height * padding
    
    x1 = max(0, x1 - pad_w)
    y1 = max(0, y1 - pad_h)
    x2 = min(image.width, x2 + pad_w)
    y2 = min(image.height, y2 + pad_h)
    
    # Crop and encode
    face_crop = image.crop((int(x1), int(y1), int(x2), int(y2)))
    
    buffer = io.BytesIO()
    face_crop.save(buffer, format='JPEG', quality=90)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


async def detect_faces(
    image_base64: str,
    confidence_threshold: float = 0.5,
    max_detections: int = 10,
    include_crops: bool = False
) -> str:
    """
    MCP Tool: Detect faces in an image.
    
    Args:
        image_base64: Base64 encoded image (JPEG or PNG)
        confidence_threshold: Minimum confidence score (0-1)
        max_detections: Maximum number of face detections to return
        include_crops: Whether to include base64 face crops in response
    
    Returns:
        JSON string with detected faces, bounding boxes, and confidence scores
    """
    try:
        # Decode base64 image
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Try DeepFace first, fall back to YOLO
        try:
            detections = detect_faces_deepface(image, confidence_threshold)
        except Exception as e:
            print(f"DeepFace failed, using YOLO fallback: {e}")
            detections = detect_faces_yolo_fallback(image, confidence_threshold, max_detections)
        
        # Limit detections
        detections = detections[:max_detections]
        
        # Optionally include face crops
        if include_crops:
            for det in detections:
                det['face_crop_base64'] = crop_face(image, det['bbox'])
        
        return json.dumps({
            "success": True,
            "count": len(detections),
            "image_size": {
                "width": image.width,
                "height": image.height
            },
            "detections": detections
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "detections": []
        })

