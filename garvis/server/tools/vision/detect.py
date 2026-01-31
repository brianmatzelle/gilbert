"""
Object Detection using YOLOv8

Fast, real-time object detection for XR applications.
"""
import base64
import io
import json
from PIL import Image

# Lazy load to avoid import errors if ultralytics isn't installed
_model = None


def get_model():
    """Lazy load YOLO model"""
    global _model
    if _model is None:
        from ultralytics import YOLO
        # Use YOLOv8n for speed, can upgrade to yolov8m/l for accuracy
        _model = YOLO("yolov8n.pt")
        print("✅ YOLOv8 model loaded")
    return _model


def detect_objects(
    image: Image.Image,
    confidence_threshold: float = 0.5,
    max_detections: int = 20
) -> list:
    """
    Detect objects in an image using YOLOv8.
    
    Args:
        image: PIL Image
        confidence_threshold: Minimum confidence score (0-1)
        max_detections: Maximum number of detections to return
    
    Returns:
        List of detected objects with bounding boxes and confidence scores
    """
    model = get_model()
    results = model(image, conf=confidence_threshold, verbose=False)
    
    detections = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
            
        for i, box in enumerate(boxes):
            if i >= max_detections:
                break
                
            # Get box coordinates (xyxy format)
            xyxy = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            
            x1, y1, x2, y2 = xyxy
            
            detections.append({
                "id": i,
                "class": class_name,
                "confidence": round(confidence, 3),
                "bbox": {
                    "x1": round(x1, 1),
                    "y1": round(y1, 1),
                    "x2": round(x2, 1),
                    "y2": round(y2, 1),
                }
            })
    
    return detections


async def detect_objects_tool(
    image_base64: str,
    confidence_threshold: float = 0.5,
    max_detections: int = 20
) -> str:
    """
    MCP Tool: Detect objects in an image using YOLOv8.
    
    Args:
        image_base64: Base64 encoded image (JPEG or PNG)
        confidence_threshold: Minimum confidence score (0-1)
        max_detections: Maximum number of detections to return
    
    Returns:
        JSON string with detected objects, bounding boxes, and confidence scores
    """
    try:
        # Decode base64 image
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        detections = detect_objects(image, confidence_threshold, max_detections)
        
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
