# core/utils.py
import cv2
from typing import Tuple, Optional

def get_image_dimensions(image_path: str) -> Optional[Tuple[int, int]]:
    """Reads image dimensions (width, height) without loading the full image if possible."""
    try:
        # cv2.imread reads the full image, but it's reliable
        img = cv2.imread(image_path)
        if img is not None:
            height, width = img.shape[:2]
            return width, height
        else:
            # Fallback using QImage might be faster if PyQt is readily available
            # from PyQt6.QtGui import QImageReader
            # reader = QImageReader(image_path)
            # if reader.canRead():
            #     size = reader.size()
            #     if size.isValid():
            #         return size.width(), size.height()
            print(f"Warning: Could not read dimensions for {image_path}")
            return None
    except Exception as e:
        print(f"Error getting dimensions for {image_path}: {e}")
        return None

def normalized_to_pixel(bbox_norm: Tuple[float, float, float, float], img_w: int, img_h: int) -> Optional[Tuple[int, int, int, int]]:
    """Converts YOLO normalized [cx, cy, w, h] to pixel [xmin, ymin, xmax, ymax]."""
    if img_w <= 0 or img_h <= 0:
        return None
    cx, cy, w, h = bbox_norm
    w_px = w * img_w
    h_px = h * img_h
    x_center_px = cx * img_w
    y_center_px = cy * img_h

    x_min = int(x_center_px - (w_px / 2))
    y_min = int(y_center_px - (h_px / 2))
    x_max = int(x_center_px + (w_px / 2))
    y_max = int(y_center_px + (h_px / 2))

    # Clamp values to image boundaries
    x_min = max(0, x_min)
    y_min = max(0, y_min)
    x_max = min(img_w - 1, x_max)
    y_max = min(img_h - 1, y_max)

    # Basic validity check
    if x_min >= x_max or y_min >= y_max:
        # This can happen with invalid input or rounding on very small boxes
        # print(f"Warning: Invalid pixel coordinates generated for {bbox_norm}")
        # Return a minimal valid box or None? Let's return clamped values.
        if x_min >= x_max: x_max = x_min + 1
        if y_min >= y_max: y_max = y_min + 1
        # Re-clamp after potential adjustment
        x_max = min(img_w - 1, x_max)
        y_max = min(img_h - 1, y_max)


    return x_min, y_min, x_max, y_max

def pixel_to_normalized(bbox_pixel: Tuple[int, int, int, int], img_w: int, img_h: int) -> Optional[Tuple[float, float, float, float]]:
    """Converts pixel [xmin, ymin, xmax, ymax] to YOLO normalized [cx, cy, w, h]."""
    if img_w <= 0 or img_h <= 0:
        return None
    x_min, y_min, x_max, y_max = bbox_pixel

    # Ensure coordinates are within bounds
    x_min = max(0, x_min)
    y_min = max(0, y_min)
    x_max = min(img_w - 1, x_max)
    y_max = min(img_h - 1, y_max)

    if x_min >= x_max or y_min >= y_max:
        print(f"Warning: Invalid pixel bbox input: {bbox_pixel}")
        return None # Or handle differently

    w_px = float(x_max - x_min)
    h_px = float(y_max - y_min)
    x_center_px = float(x_min) + w_px / 2.0
    y_center_px = float(y_min) + h_px / 2.0

    cx = x_center_px / img_w
    cy = y_center_px / img_h
    w = w_px / img_w
    h = h_px / img_h

    # Clamp normalized values between 0 and 1
    cx = max(0.0, min(1.0, cx))
    cy = max(0.0, min(1.0, cy))
    w = max(0.0, min(1.0, w))
    h = max(0.0, min(1.0, h))

    return cx, cy, w, h