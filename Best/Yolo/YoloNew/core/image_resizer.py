import cv2
import numpy as np
from typing import Tuple, List
from .models import BoundingBox

def resize_with_letterboxing(image: np.ndarray, target_shape: Tuple[int, int], boxes: List[BoundingBox] = None) -> Tuple[np.ndarray, List[BoundingBox]]:
    """
    Resizes an image to a target shape using letterboxing (padding) and adjusts bounding boxes accordingly.

    Args:
        image (np.ndarray): The input image as a NumPy array.
        target_shape (Tuple[int, int]): The target shape (height, width).
        boxes (List[BoundingBox]): A list of BoundingBox objects with normalized coordinates.

    Returns:
        Tuple[np.ndarray, List[BoundingBox]]: A tuple containing the resized image and the adjusted list of bounding boxes.
    """
    target_h, target_w = target_shape
    img_h, img_w, _ = image.shape

    # Calculate the scaling factor, keeping aspect ratio
    scale = min(target_w / img_w, target_h / img_h)
    new_w, new_h = int(img_w * scale), int(img_h * scale)

    # Resize the image
    resized_image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    # Create a new image with the target shape and a neutral background (e.g., gray)
    padded_image = np.full((target_h, target_w, 3), 114, dtype=np.uint8)

    # Calculate padding
    pad_top = (target_h - new_h) // 2
    pad_left = (target_w - new_w) // 2

    # Paste the resized image onto the padded background
    padded_image[pad_top:pad_top + new_h, pad_left:pad_left + new_w] = resized_image

    # Adjust bounding boxes if provided
    adjusted_boxes = []
    if boxes:
        for box in boxes:
            # Denormalize original box to pixel coordinates
            cx_norm, cy_norm, w_norm, h_norm = box.bbox_norm
            cx = cx_norm * img_w
            cy = cy_norm * img_h
            w = w_norm * img_w
            h = h_norm * img_h

            # Convert to x1, y1, x2, y2
            x1 = cx - w / 2
            y1 = cy - h / 2
            x2 = cx + w / 2
            y2 = cy + h / 2

            # Scale the pixel coordinates
            new_x1 = x1 * scale + pad_left
            new_y1 = y1 * scale + pad_top
            new_x2 = x2 * scale + pad_left
            new_y2 = y2 * scale + pad_top

            # Convert back to normalized coordinates relative to the new padded image size
            new_cx_norm = (new_x1 + new_x2) / (2 * target_w)
            new_cy_norm = (new_y1 + new_y2) / (2 * target_h)
            new_w_norm = (new_x2 - new_x1) / target_w
            new_h_norm = (new_y2 - new_y1) / target_h
            
            # Create a new box with adjusted coordinates
            adjusted_box = BoundingBox(
                class_id=box.class_id,
                bbox_norm=(new_cx_norm, new_cy_norm, new_w_norm, new_h_norm),
                confidence=box.confidence
            )
            adjusted_boxes.append(adjusted_box)

    return padded_image, adjusted_boxes
