# core/yolo_processor.py
import cv2
import torch # Explicit import if needed, ultralytics might handle it
from ultralytics import YOLO
from typing import List, Tuple, Optional

# Assuming models.py defines BoundingBox
from .models import BoundingBox
from . import utils # For coordinate conversions if needed (YOLO usually gives normalized)

class YoloProcessor:
    """Handles loading and running YOLO models for detection."""
    def __init__(self):
        self.model: Optional[YOLO] = None

    def load_model(self, model_path: str):
        """Loads a YOLO model from the given path."""
        try:
            # device='cpu' or device=0 for GPU etc. can be added
            # Ultralytics YOLO automatically selects device if possible
            self.model = YOLO(model_path)
            # You might want to run a dummy inference to fully initialize
            # self.model(np.zeros((640, 640, 3), dtype=np.uint8))
            print(f"Successfully loaded model: {model_path}")
        except Exception as e:
            self.model = None
            print(f"Error loading YOLO model from {model_path}: {e}")
            raise # Re-raise exception to be caught by AppLogic

    def is_model_loaded(self) -> bool:
        """Checks if a model is currently loaded."""
        return self.model is not None

    def detect(self, image_path: str, confidence_threshold: float = 0.25) -> List[BoundingBox]:
        """Runs detection on a single image."""
        if not self.is_model_loaded():
            print("Error: No YOLO model loaded.")
            return []

        detected_boxes: List[BoundingBox] = []
        try:
            # Run inference
            # results is a list, usually with one element for one image
            results = self.model(image_path, conf=confidence_threshold, verbose=False) # verbose=False reduces console output

            if results and results[0].boxes:
                boxes_data = results[0].boxes
                # Access normalized xywhn format directly if available
                normalized_coords = boxes_data.xywhn.cpu().numpy() # [cx, cy, w, h]
                confidences = boxes_data.conf.cpu().numpy()
                class_ids = boxes_data.cls.cpu().numpy().astype(int)

                img_w = results[0].orig_shape[1] # width from results
                img_h = results[0].orig_shape[0] # height from results

                for i in range(len(normalized_coords)):
                    bbox_norm: Tuple[float, float, float, float] = tuple(normalized_coords[i])
                    confidence: float = float(confidences[i])
                    class_id: int = int(class_ids[i])

                    # Optionally calculate pixel coords here if needed elsewhere frequently
                    bbox_pixels = utils.normalized_to_pixel(bbox_norm, img_w, img_h)

                    detected_boxes.append(BoundingBox(
                        class_id=class_id,
                        bbox_norm=bbox_norm,
                        bbox_pixels=bbox_pixels,
                        confidence=confidence
                    ))

        except Exception as e:
            print(f"Error during YOLO detection on {image_path}: {e}")
            # Optionally re-raise or just return empty list

        return detected_boxes
