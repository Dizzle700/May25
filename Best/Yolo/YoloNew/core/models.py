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
class AugmentationSettings:
    """Holds all settings related to image augmentation."""
    geometric_transforms_prob: float = 0.5
    color_transforms_prob: float = 0.5
    weather_transforms_prob: float = 0.3
    noise_transforms_prob: float = 0.3
    blur_transforms_prob: float = 0.3
    hflip_prob: float = 0.5
    vflip_prob: float = 0.5
    rotate_prob: float = 0.3
    rotate_limit: int = 30
    brightness_contrast_prob: float = 0.5
    hue_saturation_prob: float = 0.3
    rgb_shift_prob: float = 0.3
    blur_prob: float = 0.3
    gaussian_noise_prob: float = 0.3
    
    # Add the missing fields
    shift_scale_rotate_prob: float = 0.3
    elastic_transform_prob: float = 0.1
    grid_distortion_prob: float = 0.1
    optical_distortion_prob: float = 0.1
    clahe_prob: float = 0.3
    channel_shuffle_prob: float = 0.1
    gamma_prob: float = 0.3
    fog_prob: float = 0.3
    rain_prob: float = 0.2
    sunflare_prob: float = 0.1
    shadow_prob: float = 0.2
    iso_noise_prob: float = 0.3
    jpeg_compression_prob: float = 0.3
    posterize_prob: float = 0.2
    equalize_prob: float = 0.2
    gaussian_blur_prob: float = 0.3
    motion_blur_prob: float = 0.2
    median_blur_prob: float = 0.2
    glass_blur_prob: float = 0.1

    enabled_transforms: Dict[str, bool] = field(default_factory=lambda: {
        "geometric": True,
        "color": True,
        "weather": True,
        "noise": True,
        "blur": True
    })

@dataclass
class AppData:
    """Overall application data state."""
    images: Dict[str, ImageAnnotation] = field(default_factory=dict) # key: image_path
    classes: List[str] = field(default_factory=list)
    model_path: Optional[str] = None
    confidence_threshold: float = 0.25
    resize_output_enabled: bool = False
    resize_output_resolution: str = "640x640"
    augmentation_settings: AugmentationSettings = field(default_factory=AugmentationSettings)
    # Could add model management list here later
    # models: List[Dict[str,str]] = field(default_factory=list) # e.g. [{'name': 'yolov8n', 'path': '...'}, ...]
