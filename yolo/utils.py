"""
Utility functions for YOLO Dataset Creator
"""

import os
import numpy as np
import cv2
from typing import Tuple, List, Union
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtCore import QRect, QPoint

def xyxy_to_cxcywh_normalized(xyxy: Union[List[float], np.ndarray], img_width: int, img_height: int) -> List[float]:
    """
    Convert bounding box from [x1, y1, x2, y2] format (pixel coordinates) to
    [center_x, center_y, width, height] format normalized (0-1)
    """
    if img_width <= 0 or img_height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    x1, y1, x2, y2 = xyxy
    width = float(x2 - x1)
    height = float(y2 - y1)
    center_x = float(x1 + width / 2)
    center_y = float(y1 + height / 2)
    center_x_norm = center_x / img_width
    center_y_norm = center_y / img_height
    width_norm = width / img_width
    height_norm = height / img_height
    return [center_x_norm, center_y_norm, width_norm, height_norm]

def cxcywh_normalized_to_xyxy(cxcywh_norm: Union[List[float], np.ndarray], img_width: int, img_height: int) -> List[int]:
    """
    Convert bounding box from [center_x, center_y, width, height] format normalized (0-1) to
    [x1, y1, x2, y2] format (pixel coordinates)
    """
    if img_width <= 0 or img_height <= 0:
        return [0, 0, 0, 0]
    center_x_norm, center_y_norm, width_norm, height_norm = cxcywh_norm
    center_x = center_x_norm * img_width
    center_y = center_y_norm * img_height
    width = width_norm * img_width
    height = height_norm * img_height
    x1 = center_x - width / 2
    y1 = center_y - height / 2
    x2 = center_x + width / 2
    y2 = center_y + height / 2
    return [int(x1), int(y1), int(x2), int(y2)]

def resize_with_aspect_ratio(image: np.ndarray, target_width: int | None = None, target_height: int | None = None) -> np.ndarray:
    """Resize an image maintaining aspect ratio"""
    h, w = image.shape[:2]
    if target_width is None and target_height is None:
        return image
    if h == 0 or w == 0: return image # Avoid division by zero

    if target_width is None:
        aspect_ratio = target_height / h
        new_width = int(w * aspect_ratio)
        new_height = target_height
    elif target_height is None:
        aspect_ratio = target_width / w
        new_width = target_width
        new_height = int(h * aspect_ratio)
    else:
        aspect_ratio_width = target_width / w
        aspect_ratio_height = target_height / h
        aspect_ratio = min(aspect_ratio_width, aspect_ratio_height)
        new_width = int(w * aspect_ratio)
        new_height = int(h * aspect_ratio)

    # Ensure new dimensions are at least 1
    new_width = max(1, new_width)
    new_height = max(1, new_height)

    return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)

def ensure_dir(directory: str):
    """Make sure the directory exists, create it if it doesn't"""
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
        except OSError as e:
            print(f"Error creating directory {directory}: {e}")

def calculate_contrast_color(bg_color: QColor) -> QColor:
    """Calculate whether black or white contrasts better with a background color."""
    luminance = (0.299 * bg_color.redF() + 0.587 * bg_color.greenF() + 0.114 * bg_color.blueF())
    return QColor(0, 0, 0) if luminance > 0.5 else QColor(255, 255, 255)

def cv2_to_qimage(cv_img: np.ndarray) -> QImage | None:
    """Convert OpenCV image (numpy array) to QImage."""
    try:
        if cv_img is None: return None
        height, width, channel = cv_img.shape
        bytes_per_line = 3 * width
        qimg = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        return qimg.copy() # Return a copy to avoid issues with underlying data
    except Exception as e:
        print(f"Error converting CV2 image to QImage: {e}")
        return None

def clamp(value, min_value, max_value):
    """Clamps value between min_value and max_value."""
    return max(min_value, min(value, max_value))