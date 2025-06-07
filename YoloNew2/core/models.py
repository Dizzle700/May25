from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
import numpy as np  # Add import for numpy

# Using dataclasses for structured annotation data

@dataclass
class BoundingBox:
    """Represents a single bounding box annotation."""
    class_id: int
    # Storing both normalized and potentially pixel coordinates can be useful
    # Normalized YOLO format [cx, cy, w, h] relative to image dimensions
    bbox_norm: Tuple[float, float, float, float]
    # Optional: Pixel coordinates [x_min, y_min, x_max, y_max]
    bbox_pixels: Optional[Tuple[int, int, int, int]] = None
    confidence: Optional[float] = None # From model detection
    # Add fields for other formats if needed during conversion later
    object_id: Optional[int] = None # Useful for COCO tracking

@dataclass
class ImageAnnotation:
    """Holds all annotations for a single image."""
    image_path: str
    width: int # Image width in pixels
    height: int # Image height in pixels
    boxes: List[BoundingBox] = field(default_factory=list)
    processed: bool = False # Flag if YOLO detection has been run
    augmented_from: Optional[str] = None # Path of original if this is augmented
    _temp_image_data: Optional[np.ndarray] = field(default=None, repr=False) # Store augmented image data temporarily

@dataclass
class AppData:
    """Overall application data state."""
    images: Dict[str, ImageAnnotation] = field(default_factory=dict) # key: image_path
    classes: List[str] = field(default_factory=list)
    model_path: Optional[str] = None
    # Could add model management list here later
    # models: List[Dict[str,str]] = field(default_factory=list) # e.g. [{'name': 'yolov8n', 'path': '...'}, ...]