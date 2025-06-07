# core/yolo_processor.py
import cv2
import torch # Explicit import if needed, ultralytics might handle it
import numpy as np # Added for array operations
from ultralytics import YOLO
from typing import List, Tuple, Optional
import traceback # Added for detailed exception logging

# Assuming models.py defines BoundingBox
from .models import BoundingBox
from . import utils # For coordinate conversions if needed

class YoloProcessor:
    """Handles loading and running YOLO models for detection."""
    def __init__(self):
        self.model: Optional[YOLO] = None

    def load_model(self, model_path: str):
        """Loads a YOLO model from the given path."""
        try:
            self.model = YOLO(model_path)
            print(f"Successfully loaded model: {model_path}")
        except Exception as e:
            self.model = None
            print(f"Error loading YOLO model from {model_path}: {e}")
            raise 

    def is_model_loaded(self) -> bool:
        return self.model is not None

    def detect(self, image_path: str) -> List[BoundingBox]:
        if not self.is_model_loaded():
            print("Error: No YOLO model loaded.")
            return []

        detected_boxes: List[BoundingBox] = []
        try:
            results = self.model(image_path, verbose=False, conf=0.1) # Lowered confidence threshold

            if not results or not results[0]:
                print(f"No results from model for image: {image_path}")
                return detected_boxes

            if results[0].orig_shape is None or len(results[0].orig_shape) < 2:
                print(f"Original shape not available in results for image: {image_path}")
                return detected_boxes
                
            img_h, img_w = results[0].orig_shape[:2] # Correct order: height, width

            if results[0].masks is not None:
                masks_data = results[0].masks
                boxes_data = results[0].boxes # For class/confidence

                contours_to_process = []
                are_contours_normalized = False

                if masks_data.xyn is not None and len(masks_data.xyn) > 0:
                    contours_to_process = masks_data.xyn
                    are_contours_normalized = True
                    print(f"DEBUG: Image: {image_path} - Using normalized contours (masks.xyn), count: {len(contours_to_process)}.")
                elif masks_data.xy is not None and len(masks_data.xy) > 0:
                    contours_to_process = masks_data.xy
                    are_contours_normalized = False
                    print(f"DEBUG: Image: {image_path} - Using pixel contours (masks.xy), count: {len(contours_to_process)}. Will normalize.")
                else:
                    print(f"DEBUG: Image: {image_path} - No mask contours found in masks.xyn or masks.xy.")

                if contours_to_process:
                    class_ids_list: Optional[np.ndarray] = None
                    confidences_list: Optional[np.ndarray] = None
                    use_box_attributes = False

                    if boxes_data is not None and \
                       hasattr(boxes_data, 'cls') and boxes_data.cls is not None and \
                       hasattr(boxes_data, 'conf') and boxes_data.conf is not None and \
                       hasattr(boxes_data, '__len__') and len(boxes_data) == len(contours_to_process):
                        try:
                            class_ids_list = boxes_data.cls.cpu().numpy().astype(int)
                            confidences_list = boxes_data.conf.cpu().numpy()
                            use_box_attributes = True
                            print(f"DEBUG: Image: {image_path} - Successfully extracted class IDs and confidences for {len(contours_to_process)} masks.")
                        except Exception as e_box_attr:
                            print(f"Warning: Image: {image_path} - Error extracting attributes from boxes_data for masks: {e_box_attr}. Proceeding with defaults.")
                    else:
                        box_count_info = len(boxes_data) if boxes_data is not None and hasattr(boxes_data, '__len__') else "None or not iterable"
                        print(f"Warning: Image: {image_path} - Mismatch or missing box data for masks. Masks: {len(contours_to_process)}, Associated Boxes: {box_count_info}. Proceeding with defaults.")

                    for i, contour_points_np in enumerate(contours_to_process):
                        if not isinstance(contour_points_np, np.ndarray):
                            contour_points_np = np.array(contour_points_np)

                        if contour_points_np.ndim == 2 and contour_points_np.shape[1] == 2 and contour_points_np.shape[0] >= 3:
                            current_bbox_norm: Optional[Tuple[float, float, float, float]] = None
                            current_bbox_pixels: Optional[Tuple[int, int, int, int]] = None

                            if are_contours_normalized:
                                # Points are already normalized [0,1]
                                min_x_n = contour_points_np[:, 0].min()
                                max_x_n = contour_points_np[:, 0].max()
                                min_y_n = contour_points_np[:, 1].min()
                                max_y_n = contour_points_np[:, 1].max()

                                w_n = max_x_n - min_x_n
                                h_n = max_y_n - min_y_n
                                cx_n = min_x_n + w_n / 2
                                cy_n = min_y_n + h_n / 2
                                current_bbox_norm = (float(cx_n), float(cy_n), float(w_n), float(h_n))
                                print(f"DEBUG: Image: {image_path} - Mask {i} (from normalized contours) - Calculated bbox_norm: {current_bbox_norm}")
                                current_bbox_pixels = utils.normalized_to_pixel(current_bbox_norm, img_w, img_h)
                                print(f"DEBUG: Image: {image_path} - Mask {i} (from normalized contours) - Calculated bbox_pixels: {current_bbox_pixels}")
                            else: # Points are in pixel coordinates
                                min_x_p = contour_points_np[:, 0].min()
                                max_x_p = contour_points_np[:, 0].max()
                                min_y_p = contour_points_np[:, 1].min()
                                max_y_p = contour_points_np[:, 1].max()
                                
                                # Ensure pixel coordinates are integers and form a valid box
                                x_min_p, y_min_p, x_max_p, y_max_p = int(min_x_p), int(min_y_p), int(max_x_p), int(max_y_p)
                                if x_min_p >= x_max_p: x_max_p = x_min_p + 1 # Ensure min width/height of 1
                                if y_min_p >= y_max_p: y_max_p = y_min_p + 1
                                
                                current_bbox_pixels = (x_min_p, y_min_p, x_max_p, y_max_p)
                                print(f"DEBUG: Image: {image_path} - Mask {i} (from pixel contours) - Calculated bbox_pixels: {current_bbox_pixels}")
                                current_bbox_norm = utils.pixel_to_normalized(current_bbox_pixels, img_w, img_h)
                                print(f"DEBUG: Image: {image_path} - Mask {i} (from pixel contours) - Calculated bbox_norm: {current_bbox_norm}")
                            
                            class_id: int = 0 
                            confidence: Optional[float] = None

                            if use_box_attributes and class_ids_list is not None and confidences_list is not None and i < len(class_ids_list):
                                class_id = int(class_ids_list[i])
                                confidence = float(confidences_list[i])
                            
                            if current_bbox_norm and current_bbox_pixels:
                                detected_boxes.append(BoundingBox(
                                    class_id=class_id,
                                    bbox_norm=current_bbox_norm,
                                    bbox_pixels=current_bbox_pixels,
                                    confidence=confidence
                                ))
                                print(f"DEBUG: Image: {image_path} - Mask {i} - Added BoundingBox: class_id={class_id}, confidence={confidence}, norm={current_bbox_norm}, pixels={current_bbox_pixels}")
                            else:
                                print(f"Warning: Image: {image_path} - Mask {i} - Failed to derive valid norm/pixel bbox. Skipping.")
                        else:
                            shape_info = contour_points_np.shape if isinstance(contour_points_np, np.ndarray) else 'Not an ndarray'
                            print(f"Warning: Image: {image_path} - Mask {i} - Invalid contour data. Shape/Type: {shape_info}. Min points: 3. Skipping.")
            
            if not detected_boxes and results[0].boxes is not None and len(results[0].boxes) > 0:
                print(f"Info: Image: {image_path} - No valid boxes from masks. Falling back to {len(results[0].boxes)} detection boxes.")
                # ... (fallback logic remains the same as previous version)
                boxes_data_fallback = results[0].boxes
                normalized_coords_fallback = boxes_data_fallback.xywhn.cpu().numpy()
                confidences_fallback = boxes_data_fallback.conf.cpu().numpy()
                class_ids_fallback = boxes_data_fallback.cls.cpu().numpy().astype(int)

                for i in range(len(normalized_coords_fallback)):
                    bbox_norm_tuple = tuple(map(float, normalized_coords_fallback[i]))
                    confidence_val = float(confidences_fallback[i])
                    class_id_val = int(class_ids_fallback[i])
                    print(f"DEBUG: Image: {image_path} - Fallback Detection Box {i} - bbox_norm: {bbox_norm_tuple}")

                    bbox_pixels = utils.normalized_to_pixel(bbox_norm_tuple, img_w, img_h)
                    print(f"DEBUG: Image: {image_path} - Fallback Detection Box {i} - bbox_pixels: {bbox_pixels}")

                    if bbox_pixels:
                        detected_boxes.append(BoundingBox(
                            class_id=class_id_val,
                            bbox_norm=bbox_norm_tuple,
                            bbox_pixels=bbox_pixels,
                            confidence=confidence_val
                        ))
                        print(f"DEBUG: Image: {image_path} - Fallback Detection Box {i} - Added BoundingBox: class_id={class_id_val}, confidence={confidence_val}, norm={bbox_norm_tuple}, pixels={bbox_pixels}")
                    else:
                        print(f"Warning: Image: {image_path} - Fallback Detection Box {i} - Failed to convert normalized detection bbox to pixel. Skipping.")
            elif not detected_boxes:
                print(f"Info: Image: {image_path} - No masks or boxes found, or processing failed to yield any valid bounding boxes.")

        except Exception as e:
            print(f"Error during YOLO processing on {image_path}: {e}\n{traceback.format_exc()}")

        print(f"DEBUG: Image: {image_path} - Final detected_boxes count: {len(detected_boxes)}")
        return detected_boxes
