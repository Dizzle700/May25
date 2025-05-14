"""
YoloProcessor module - Handles YOLO model loading and inference (PyQt6 version)
"""

import os
import cv2
import numpy as np
import torch
from typing import Optional, List, Dict, Any

# Try importing ONNX runtime, fail gracefully if not installed
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ort = None
    ONNX_AVAILABLE = False
    print("Warning: onnxruntime not found. ONNX model loading disabled.")

# Try importing Ultralytics, fail gracefully
try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    YOLO = None
    ULTRALYTICS_AVAILABLE = False
    print("Warning: ultralytics package not found. Will try torch.hub if needed.")


class YoloProcessor:
    """Handles loading and running YOLO models for object detection."""

    def __init__(self):
        self.model: Optional[Any] = None
        self.model_path: Optional[str] = None
        self.model_type: Optional[str] = None  # 'ultralytics', 'torch', 'onnx'
        self.class_names: List[str] = [] # Store class names from the model if available

    def is_model_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self.model is not None and self.model_type is not None

    def load_model(self, model_path: str) -> bool:
        """Load a YOLO model (.pt or .onnx)."""
        if not os.path.exists(model_path):
            print(f"Model Error: File not found at {model_path}")
            return False

        self.model_path = model_path
        extension = os.path.splitext(model_path)[1].lower()
        self.model = None # Reset model state
        self.model_type = None
        self.class_names = []

        try:
            if extension == '.pt':
                if ULTRALYTICS_AVAILABLE:
                    try:
                        self.model = YOLO(model_path)
                        # Check if model loaded successfully (e.g., has names attribute)
                        if hasattr(self.model, 'names'):
                             self.model_type = 'ultralytics'
                             self.class_names = list(self.model.names.values()) if self.model.names else []
                             print(f"Model Info: Loaded ultralytics YOLO model: {model_path}")
                             print(f"Model Info: Found {len(self.class_names)} classes: {self.class_names}")
                             return True
                        else:
                            raise ValueError("Ultralytics model loaded but seems invalid.")
                    except Exception as ultra_e:
                        print(f"Model Warning: Failed to load with ultralytics ({ultra_e}). Trying torch.hub...")
                        # Fall through to torch.hub attempt if ultralytics fails
                # Try torch.hub (YOLOv5 style)
                try:
                    self.model = torch.hub.load('ultralytics/yolov5', 'custom', path=model_path, force_reload=False) # Avoid re-download if cached
                    # Check if model loaded successfully
                    if hasattr(self.model, 'names'):
                        self.model_type = 'torch'
                        self.class_names = list(self.model.names) if self.model.names else []
                        print(f"Model Info: Loaded torch.hub YOLOv5 model: {model_path}")
                        print(f"Model Info: Found {len(self.class_names)} classes: {self.class_names}")
                        return True
                    else:
                         raise ValueError("Torch Hub model loaded but seems invalid.")
                except Exception as torch_e:
                    print(f"Model Error: Failed to load .pt model with torch.hub: {torch_e}")
                    return False

            elif extension == '.onnx':
                if ONNX_AVAILABLE:
                    try:
                        # Consider providers=['CPUExecutionProvider'] or ['CUDAExecutionProvider']
                        self.model = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                        self.model_type = 'onnx'
                        # Note: Getting class names from ONNX models is not standardized.
                        # They might be in metadata, or you might need a separate label file.
                        # self._try_get_onnx_metadata() # Example helper
                        print(f"Model Info: Loaded ONNX model: {model_path}")
                        print("Model Info: Class names for ONNX models must be managed manually or via associated files.")
                        return True
                    except Exception as onnx_e:
                        print(f"Model Error: Failed to load ONNX model: {onnx_e}")
                        return False
                else:
                    print("Model Error: ONNX Runtime is not installed. Cannot load .onnx model.")
                    return False
            else:
                print(f"Model Error: Unsupported model format: {extension}")
                return False

        except Exception as e:
            print(f"Model Error: Unexpected error loading model {model_path}: {e}")
            self.model = None
            self.model_type = None
            self.class_names = []
            return False

    def detect(self, image_path: str, conf_threshold: float = 0.25, iou_threshold: float = 0.45) -> Optional[List[Dict]]:
        """
        Run object detection on an image.
        Returns list of {'bbox_xyxy': [x1,y1,x2,y2], 'confidence': float, 'model_class_id': int} or None.
        """
        if self.model is None or self.model_type is None:
            print("Detection Error: No model loaded.")
            return None

        try:
            img_bgr = cv2.imread(image_path)
            if img_bgr is None:
                print(f"Detection Error: Could not read image: {image_path}")
                return None

            detections = []

            if self.model_type == 'ultralytics':
                # Ultralytics model handles BGR input directly
                results = self.model(img_bgr, conf=conf_threshold, iou=iou_threshold, verbose=False) # Less console output
                if results:
                    result = results[0] # Assuming single image result
                    boxes = result.boxes
                    for i in range(len(boxes)):
                        x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().tolist()
                        conf = boxes.conf[i].item()
                        cls_id = int(boxes.cls[i].item())
                        detections.append({
                            'bbox_xyxy': [x1, y1, x2, y2],
                            'confidence': conf,
                            'model_class_id': cls_id
                        })

            elif self.model_type == 'torch': # Assumes YOLOv5 torch hub model
                results = self.model(img_bgr) # Model expects BGR by default here
                preds = results.xyxy[0].cpu().numpy() # N x 6 (x1, y1, x2, y2, conf, cls)
                for *xyxy, conf, cls_id in preds:
                    if conf >= conf_threshold: # Apply confidence threshold here
                         detections.append({
                            'bbox_xyxy': xyxy,
                            'confidence': conf,
                            'model_class_id': int(cls_id)
                         })
                # Note: YOLOv5 torch hub model applies NMS internally before returning results.

            elif self.model_type == 'onnx':
                detections = self._detect_onnx(img_bgr, conf_threshold, iou_threshold)

            else:
                print(f"Detection Error: Unsupported model type '{self.model_type}' for detection.")
                return None

            return detections

        except Exception as e:
            print(f"Detection Error: An error occurred during detection: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _detect_onnx(self, img_bgr: np.ndarray, conf_threshold: float, iou_threshold: float) -> List[Dict]:
        """Internal helper for ONNX inference (example for YOLOv8 ONNX)."""
        if not ONNX_AVAILABLE or self.model is None: return []

        try:
            input_details = self.model.get_inputs()[0]
            input_name = input_details.name
            input_shape = input_details.shape # e.g., [1, 3, 640, 640]
            _, _, input_height, input_width = input_shape

            img_height, img_width = img_bgr.shape[:2]

            # Preprocessing: Resize, BGR->RGB, HWC->CHW, Normalize, Add Batch dim
            img_resized = cv2.resize(img_bgr, (input_width, input_height))
            img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
            img_normalized = img_rgb.astype(np.float32) / 255.0
            img_transposed = np.transpose(img_normalized, (2, 0, 1)) # HWC -> CHW
            input_tensor = np.expand_dims(img_transposed, axis=0) # Add batch dimension

            # Inference
            outputs = self.model.run(None, {input_name: input_tensor})
            # Output format for many YOLO ONNX models: [1, 84, N] where 84 = 4 (box) + n_classes
            # Or [1, N, 84] - check your specific model
            predictions = np.squeeze(outputs[0]).T # Transpose if output is [1, 84, N] -> [N, 84]

            # Filter out low confidence scores
            scores = np.max(predictions[:, 4:], axis=1)
            predictions = predictions[scores > conf_threshold, :]
            scores = scores[scores > conf_threshold]

            if len(predictions) == 0:
                return []

            # Get boxes and class IDs
            boxes = predictions[:, :4] # cx, cy, w, h
            class_ids = np.argmax(predictions[:, 4:], axis=1)

            # Rescale boxes from normalized [0,1] relative to input size (640x640)
            # back to pixel coords relative to original image size
            scale_x = img_width / input_width
            scale_y = img_height / input_height

            # Convert cxcywh to xyxy
            x_center = boxes[:, 0] * scale_x
            y_center = boxes[:, 1] * scale_y
            width = boxes[:, 2] * scale_x
            height = boxes[:, 3] * scale_y

            x1 = x_center - width / 2
            y1 = y_center - height / 2
            x2 = x_center + width / 2
            y2 = y_center + height / 2

            boxes_xyxy = np.column_stack((x1, y1, x2, y2))

            # Apply Non-Maximum Suppression (NMS)
            # Note: cv2.dnn.NMSBoxes expects boxes in (x, y, w, h) format - requires conversion
            # Or use a simpler NMS implementation if needed. TorchVision's NMS is often used.
            indices = cv2.dnn.NMSBoxes(boxes_xyxy.tolist(), scores.tolist(), conf_threshold, iou_threshold)
            # indices = torchvision.ops.nms(torch.tensor(boxes_xyxy), torch.tensor(scores), iou_threshold).numpy()


            final_detections = []
            for i in indices:
                # i = i[0] # If NMSBoxes returns list of lists
                final_detections.append({
                    'bbox_xyxy': boxes_xyxy[i].tolist(),
                    'confidence': scores[i].item(),
                    'model_class_id': class_ids[i].item()
                })

            return final_detections

        except Exception as e:
            print(f"ONNX Detection Error: {e}")
            import traceback
            traceback.print_exc()
            return []

    # def _try_get_onnx_metadata(self):
    #     if not self.model or not hasattr(self.model, 'get_modelmeta'): return
    #     try:
    #         metadata = self.model.get_modelmeta()
    #         if metadata and hasattr(metadata, 'custom_metadata_map'):
    #             custom_map = metadata.custom_metadata_map
    #             if 'names' in custom_map:
    #                 # Assumes names are stored as a JSON string or similar
    #                 import json
    #                 try:
    #                     self.class_names = json.loads(custom_map['names'])
    #                     print(f"Model Info: Found {len(self.class_names)} classes in ONNX metadata.")
    #                 except json.JSONDecodeError:
    #                     print("Model Info: 'names' found in ONNX metadata but couldn't decode as JSON.")
    #     except Exception as e:
    #         print(f"Model Info: Could not read metadata from ONNX model: {e}")