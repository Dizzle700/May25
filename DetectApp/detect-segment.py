# --- START OF FILE det-objects-enhanced.py ---

import sys
import os
import json
import time
import shutil
import cv2
import numpy as np
from ultralytics import YOLO
from typing import Optional, List, Dict, Any, Tuple

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QMessageBox,
    QSizePolicy, QListWidget, QListWidgetItem, QTextEdit, QDoubleSpinBox,
    QCheckBox, QComboBox
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QObject, QMutex, QWaitCondition, QSettings, QSize,
    QCoreApplication # For organization name/app name
)
from PyQt6.QtGui import QPixmap, QImage, QFont, QCursor, QIcon # Added QIcon for potential future use

# --- Constants ---
ORGANIZATION_NAME = "MyCompany" # Change as needed
APPLICATION_NAME = "YOLOv8SegmentationDetector"
DEFAULT_MODEL = "yolo11-seg.pt"  # Default segmentation model
DEFAULT_CONFIDENCE = 0.35 # Default confidence threshold
DEFAULT_BLUR_STRENGTH = 5 # Default blur strength for anti-aliasing
RESULTS_FOLDER_NAME = "segmentation_results_annotated"
PERSON_MASKS_FOLDER_NAME = "person_masks_transparent"
JSON_RESULTS_FILENAME = "segmentation_results.json"
SETTINGS_LAST_FOLDER = "lastFolderPath"
SETTINGS_LAST_MODEL = "lastModelPath"
SETTINGS_CONFIDENCE = "lastConfidence"
SETTINGS_SAVE_IMMEDIATE = "lastSaveImmediate"
SETTINGS_BLUR_STRENGTH = "lastBlurStrength"
MODELS_FOLDER_NAME = "Models"

# --- Helper Functions ---
def draw_results_on_image(image: cv2.Mat, detections: List[Dict[str, Any]]) -> cv2.Mat:
    """Draws bounding boxes, masks, and labels on an image."""
    if image is None:
        return None
    img_copy = image.copy()
    
    # Generate random distinct colors for different classes if needed
    class_colors = {}
    
    for detection in detections:
        try:
            box = detection["box"] # Should be [int, int, int, int]
            class_name = detection["class_name"]
            class_id = detection["class_id"]
            confidence = detection["confidence"]
            
            # Get a consistent color for this class
            if class_id not in class_colors:
                # Generate a random bright color
                hue = (class_id * 35) % 180  # Use class_id to generate different hues
                # Make sure color is a proper BGR tuple of integers
                color = tuple([int(c) for c in reversed(cv2.cvtColor(
                    np.uint8([[[hue, 250, 230]]]), cv2.COLOR_HSV2BGR)[0, 0])])
                class_colors[class_id] = color
            
            color = class_colors[class_id]
            
            # Draw mask if available
            if "mask" in detection and detection["mask"] is not None:
                mask = detection["mask"]
                if mask.shape[:2] != img_copy.shape[:2]:
                    # Resize mask if dimensions don't match
                    mask = cv2.resize(mask, (img_copy.shape[1], img_copy.shape[0]))
                
                # Create a colored mask overlay
                colored_mask = np.zeros_like(img_copy)
                mask_color = color  # Use the same color as bounding box
                colored_mask[mask > 0] = mask_color
                
                # Blend the mask with the image (semi-transparent)
                alpha = 0.45  # Transparency factor
                mask_area = mask > 0
                img_copy[mask_area] = cv2.addWeighted(
                    img_copy[mask_area], 1-alpha, 
                    colored_mask[mask_area], alpha, 0)
                
                # Add a border to the mask
                contours, _ = cv2.findContours(
                    mask.astype(np.uint8), 
                    cv2.RETR_EXTERNAL, 
                    cv2.CHAIN_APPROX_SIMPLE
                )
                cv2.drawContours(img_copy, contours, -1, color, 2)

            # Draw bounding box
            cv2.rectangle(img_copy, (box[0], box[1]), (box[2], box[3]), color, 2)

            # Prepare label text
            label = f"{class_name}: {confidence:.2f}"

            # Calculate text size for background rectangle - increase font size for better visibility
            font_scale = 0.8  # Increased from 0.6
            thickness = 2
            (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)

            # Put label background rectangle slightly above the box
            # Add more padding around text for better visibility
            padding = 4  # Increased padding
            label_bg_y1 = box[1] - text_height - baseline - padding
            label_bg_y2 = box[1] - baseline + padding
            
            # Ensure background is within image bounds (top)
            if label_bg_y1 < 0:
                # Place label inside the top of box instead of above it
                label_bg_y1 = box[1] + padding
                label_bg_y2 = box[1] + text_height + baseline + padding * 2

            # Draw background rectangle - make it slightly wider for better text visibility
            cv2.rectangle(img_copy, 
                         (box[0], label_bg_y1), 
                         (box[0] + text_width + padding * 2, label_bg_y2), 
                         color, -1)  # Filled background

            # Put label text - ensure it's positioned correctly within the background
            label_y = label_bg_y1 + text_height + padding // 2  # Adjusted Y position
            
            # Fix: Ensure coordinates are passed as a tuple
            cv2.putText(img_copy, label, (box[0] + padding, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness)  # Black text, thicker

        except Exception as e:
            print(f"Error drawing detection {detection}: {e}")
            continue # Skip this detection if error occurs

    return img_copy

# Keeping the old function name for backward compatibility
def draw_boxes_on_image(image: cv2.Mat, detections: List[Dict[str, Any]]) -> cv2.Mat:
    """Legacy function that calls draw_results_on_image."""
    return draw_results_on_image(image, detections)

def create_transparent_person_mask(image: cv2.Mat, detection: Dict[str, Any], blur_strength: int = 5) -> Optional[np.ndarray]:
    """Creates a transparent PNG/WebP image with only the person mask visible.
    
    Args:
        image: Original image
        detection: Detection data containing mask and class info
        blur_strength: Controls the anti-aliasing strength (default: 5, higher = more blurry edges)
        
    Returns:
        RGBA image with transparent background and only the person visible with smooth edges
    """
    if not detection or "mask" not in detection or detection["mask"] is None:
        return None
        
    # Check if this is a person (class 0 in COCO dataset)
    if detection["class_name"].lower() != "person" and detection["class_id"] != 0:
        return None
        
    # Get the mask
    mask = detection["mask"]
    if mask.shape[:2] != image.shape[:2]:
        mask = cv2.resize(mask, (image.shape[1], image.shape[0]))
    
    # Create transparent image (RGBA)
    transparent_img = np.zeros((image.shape[0], image.shape[1], 4), dtype=np.uint8)
    
    # For anti-aliasing, we'll create a slightly blurred version of the mask
    # This will create a soft transition at the edges
    mask_uint8 = (mask * 255).astype(np.uint8)
    
    # First, dilate the mask slightly to expand the edges
    kernel = np.ones((3, 3), np.uint8)
    dilated_mask = cv2.dilate(mask_uint8, kernel, iterations=1)
    
    # Apply Gaussian blur to create a gradient at the edges
    # The blur_strength parameter controls the level of smoothing
    kernel_size = max(3, blur_strength)
    # Ensure kernel size is odd
    if kernel_size % 2 == 0:
        kernel_size += 1
    blurred_mask = cv2.GaussianBlur(dilated_mask, (kernel_size, kernel_size), 0)
    
    # Convert back to float [0-1] range
    smooth_mask = blurred_mask.astype(float) / 255.0
    
    # Copy RGB channels from original image
    transparent_img[..., :3] = image
    
    # Create alpha channel with the smooth mask
    transparent_img[..., 3] = blurred_mask
    
    # Make fully transparent where the original mask was 0
    # This ensures only edges are anti-aliased, not the entire background
    zero_mask = (mask == 0)
    transparent_img[zero_mask, 3] = 0
    
    return transparent_img

def convert_cv_image_to_qpixmap(cv_image: cv2.Mat) -> Optional[QPixmap]:
    """Converts an OpenCV image (BGR) to a QPixmap."""
    if cv_image is None:
        return None
    try:
        height, width, channel = cv_image.shape
        bytes_per_line = 3 * width
        # Note: OpenCV reads as BGR. QImage needs RGB for Format_RGB888 or BGR for Format_BGR888.
        # If using Format_RGB888, use rgbSwapped(). If using Format_BGR888, don't swap.
        # Let's use BGR888 directly as it avoids an extra conversion step if possible.
        # However, many systems expect RGB, so rgbSwapped() might be safer. Test!
        # Let's stick to the proven rgbSwapped() approach for broader compatibility.
        q_image = QImage(cv_image.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
        q_image = q_image.rgbSwapped() # Convert BGR to RGB
        return QPixmap.fromImage(q_image)
    except Exception as e:
        print(f"Error converting cv2 image to QPixmap: {e}")
        return None


# --- Worker Thread for Processing ---
class DetectionWorker(QObject):
    """Handles the background image processing"""
    progressUpdated = pyqtSignal(int, int)  # current_value, max_value
    statusUpdated = pyqtSignal(str)
    # Sends: original_path, annotated_cv_image (or None if error/not saving), detections list
    imageProcessed = pyqtSignal(str, object, list)
    processingFinished = pyqtSignal(dict)   # Final results_data dictionary
    errorOccurred = pyqtSignal(str)

    def __init__(self, model_path: str, folder_path: str, files: List[str],
                 confidence_threshold: float, save_immediately: bool, results_dir: str):
        super().__init__()
        self.model_path = model_path
        self.folder_path = folder_path
        self.files = files
        self.confidence_threshold = confidence_threshold
        self.save_immediately = save_immediately
        self.results_dir = results_dir # Needed for immediate save
        self.model: Optional[YOLO] = None
        self.is_segmentation_model = False
        self._is_running = True
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def run(self):
        """Main processing loop"""
        results_data: Dict[str, List[Dict[str, Any]]] = {}
        total_files = len(self.files)

        try:
            self.statusUpdated.emit(f"Loading model: {os.path.basename(self.model_path)}...")
            QCoreApplication.processEvents() # Allow UI update for status
            self.model = YOLO(self.model_path)
            
            # Check if this is a segmentation model
            self.is_segmentation_model = hasattr(self.model, 'task') and self.model.task == 'segment'
            
            if self.is_segmentation_model:
                self.statusUpdated.emit(f"Segmentation model loaded. Starting processing in: {self.folder_path}")
            else:
                self.statusUpdated.emit(f"Detection model loaded. Starting processing in: {self.folder_path}")
                
        except Exception as e:
            self.errorOccurred.emit(f"FATAL: Error loading YOLO model ({self.model_path}): {e}")
            self.processingFinished.emit({}) # Emit empty results on fatal error
            return # Stop processing

        # Create results dir if saving immediately
        if self.save_immediately:
            try:
                os.makedirs(self.results_dir, exist_ok=True)
            except OSError as e:
                self.errorOccurred.emit(f"Warning: Could not create results directory '{self.results_dir}' for immediate save: {e}. Disabling immediate save.")
                self.save_immediately = False # Disable if creation fails

        for idx, filename in enumerate(self.files):
            self._mutex.lock()
            while self._is_paused:
                self.statusUpdated.emit(f"Paused ({idx + 1}/{total_files})")
                self._pause_cond.wait(self._mutex) # Wait until resumed

            should_stop = not self._is_running
            self._mutex.unlock()

            if should_stop:
                self.statusUpdated.emit("Processing stopped by user.")
                break # Exit loop if stopped

            file_path = os.path.join(self.folder_path, filename)
            self.statusUpdated.emit(f"Processing: {filename} ({idx + 1}/{total_files})")

            annotated_image: Optional[cv2.Mat] = None
            current_detections: List[Dict[str, Any]] = []

            try:
                # Read image using OpenCV
                original_image = cv2.imread(file_path)
                if original_image is None:
                    print(f"Warning: Could not read image {filename}. Skipping.")
                    results_data[filename] = [] # Store empty result
                    # Still emit signal so UI knows it's processed
                    self.imageProcessed.emit(file_path, None, [])
                    self.progressUpdated.emit(idx + 1, total_files)
                    continue

                # Perform detection/segmentation
                results = self.model(original_image, verbose=False, conf=self.confidence_threshold)

                # Process results
                if results and len(results) > 0:
                    result = results[0]  # Get the first result

                    # Process object instances
                    if result.boxes is not None and len(result.boxes) > 0:
                        for i, box in enumerate(result.boxes):
                            # Confidence already filtered by model(conf=...), but double check if needed
                            confidence = float(box.conf.item())
                            class_id = int(box.cls.item())
                            box_coords = [int(x) for x in box.xyxy[0].tolist()] # x1, y1, x2, y2
                            class_name = self.model.names.get(class_id, f"Unknown:{class_id}")

                            detection_data = {
                                "class_id": class_id,
                                "class_name": class_name,
                                "confidence": confidence,
                                "box": box_coords
                            }

                            # Add mask data if this is a segmentation model and masks are available
                            if self.is_segmentation_model and result.masks is not None and i < len(result.masks.data):
                                try:
                                    # Get mask for this object
                                    mask_tensor = result.masks.data[i]
                                    mask_np = mask_tensor.cpu().numpy()
                                    
                                    # Convert to binary mask
                                    binary_mask = np.zeros(original_image.shape[:2], dtype=np.uint8)
                                    
                                    # Need to resize the mask to match the image dimensions
                                    mask_resized = cv2.resize(
                                        mask_np, 
                                        (original_image.shape[1], original_image.shape[0])
                                    )
                                    
                                    # Set mask areas to 1
                                    binary_mask[mask_resized > 0.5] = 1
                                    
                                    # Add mask to detection data
                                    detection_data["mask"] = binary_mask
                                except Exception as mask_err:
                                    print(f"Error processing mask for detection {i}: {mask_err}")
                                    # Still include the detection without mask

                            current_detections.append(detection_data)

                results_data[filename] = current_detections

                # Draw results IF there are detections OR if saving immediately (to save blank if no detections)
                if current_detections or self.save_immediately:
                     annotated_image = draw_results_on_image(original_image, current_detections)

                # Save immediately if requested AND drawing was successful
                if self.save_immediately and annotated_image is not None:
                    save_path = os.path.join(self.results_dir, filename)
                    try:
                        success = cv2.imwrite(save_path, annotated_image)
                        if not success:
                            print(f"Warning: Failed to save immediately: {save_path}")
                    except Exception as e:
                        print(f"Error during immediate save for {filename}: {e}")
                        self.errorOccurred.emit(f"Error saving {filename}: {e}") # Inform user non-fatally

                # Emit signal with original path, annotated image (if drawn), and detections
                self.imageProcessed.emit(file_path, annotated_image, current_detections)
                self.progressUpdated.emit(idx + 1, total_files)

            except Exception as e:
                self.errorOccurred.emit(f"Error processing {filename}: {e}")
                results_data[filename] = [] # Store empty result on error
                self.imageProcessed.emit(file_path, None, []) # Signal progress even on error
                self.progressUpdated.emit(idx + 1, total_files)
                # time.sleep(0.01) # Optional small delay

        # --- Loop Finished ---
        if self._is_running: # Only emit finished if not stopped
             self.statusUpdated.emit("Processing finished.")
             self.processingFinished.emit(results_data)
        # Worker automatically finishes here (thread will terminate)

    def stop(self):
        self._mutex.lock()
        self._is_running = False
        if self._is_paused:
            self._is_paused = False
            self._pause_cond.wakeAll()
        self._mutex.unlock()

    def pause(self):
        self._mutex.lock()
        self._is_paused = True
        # Status updated in run loop when pause is detected
        self._mutex.unlock()

    def resume(self):
        self._mutex.lock()
        if self._is_paused:
            self._is_paused = False
            self.statusUpdated.emit("Processing resumed.")
            self._pause_cond.wakeAll() # Wake up the waiting thread
        self._mutex.unlock()

# --- Worker Thread for Saving Annotated Images (Separately) ---
class SaveWorker(QObject):
    progressUpdated = pyqtSignal(int, int) # current, total
    statusUpdated = pyqtSignal(str)
    saveFinished = pyqtSignal(int, int, int) # saved_count, person_mask_count, error_count
    errorOccurred = pyqtSignal(str)

    # Save modes
    MODE_ALL = 0         # Save both segmentation and person masks
    MODE_SEGMENTATION = 1 # Save only segmentation results
    MODE_PERSON_WEBP = 2  # Save only person masks as WebP

    def __init__(self, folder_path: str, results_data: Dict[str, list], results_dir: str, 
                 blur_strength: int = 5, save_mode: int = MODE_ALL):
        super().__init__()
        self.folder_path = folder_path
        self.results_data = results_data
        self.results_dir = results_dir
        self.person_masks_dir = os.path.join(os.path.dirname(results_dir), PERSON_MASKS_FOLDER_NAME)
        self.blur_strength = blur_strength  # Anti-aliasing strength for person masks
        self.save_mode = save_mode  # What to save: all, segmentation only, or person masks only
        self._is_running = True

    def run(self):
        if self.save_mode == self.MODE_SEGMENTATION:
            self.statusUpdated.emit(f"Saving annotated images to {self.results_dir}...")
        elif self.save_mode == self.MODE_PERSON_WEBP:
            self.statusUpdated.emit(f"Saving person masks to {self.person_masks_dir}...")
        else:
            self.statusUpdated.emit(f"Saving annotated images and person masks...")
            
        saved_count = 0
        person_mask_count = 0
        error_count = 0
        total_items = len(self.results_data)
        self.progressUpdated.emit(0, total_items)

        # Create results directory if needed
        if self.save_mode in [self.MODE_ALL, self.MODE_SEGMENTATION]:
            try:
                os.makedirs(self.results_dir, exist_ok=True)
            except OSError as e:
                self.errorOccurred.emit(f"Error creating results directory '{self.results_dir}': {e}")
                if self.save_mode == self.MODE_SEGMENTATION:
                    self.saveFinished.emit(0, 0, total_items) # Indicate 0 saved, all errors
                    return
        
        # Create person masks directory if needed
        if self.save_mode in [self.MODE_ALL, self.MODE_PERSON_WEBP]:
            try:
                os.makedirs(self.person_masks_dir, exist_ok=True)
            except OSError as e:
                self.errorOccurred.emit(f"Error creating person masks directory '{self.person_masks_dir}': {e}")
                if self.save_mode == self.MODE_PERSON_WEBP:
                    self.saveFinished.emit(0, 0, total_items) # Indicate 0 saved, all errors
                    return

        for i, (filename, detections) in enumerate(self.results_data.items()):
            if not self._is_running:
                self.statusUpdated.emit("Saving stopped.")
                break

            original_path = os.path.join(self.folder_path, filename)
            result_path = os.path.join(self.results_dir, filename)
            
            # For WebP output of person masks, change extension
            base_filename = os.path.splitext(filename)[0]

            try:
                image = cv2.imread(original_path)
                if image is None:
                    print(f"Warning: Could not read original image {filename} during save. Skipping.")
                    self.errorOccurred.emit(f"Skipped saving {filename}: Cannot read original.")
                    error_count += 1
                    continue

                # Save the annotated segmentation image
                if self.save_mode in [self.MODE_ALL, self.MODE_SEGMENTATION]:
                    # Draw the results (boxes and masks) using the enhanced function
                    annotated_image = draw_results_on_image(image, detections)

                    if annotated_image is not None:
                        success = cv2.imwrite(result_path, annotated_image)
                        if not success:
                            print(f"Warning: Could not write annotated image {result_path}. Skipping.")
                            self.errorOccurred.emit(f"Failed to write annotated {filename}.")
                            error_count += 1
                        else:
                            saved_count += 1
                    else:
                         print(f"Warning: Annotated image was None for {filename}, not saving.")
                         self.errorOccurred.emit(f"Failed to create annotation for {filename}.")
                         error_count += 1
                
                # Save person masks as transparent WebP files
                if self.save_mode in [self.MODE_ALL, self.MODE_PERSON_WEBP]:
                    person_idx = 0
                    for det in detections:
                        if det.get("class_name", "").lower() == "person" or det.get("class_id") == 0:
                            # Only for detections with masks
                            if "mask" in det and det["mask"] is not None:
                                try:
                                    transparent_mask = create_transparent_person_mask(image, det, self.blur_strength)
                                    if transparent_mask is not None:
                                        # Save as WebP with unique index
                                        person_mask_filename = f"{base_filename}_person_{person_idx}.webp"
                                        person_mask_path = os.path.join(self.person_masks_dir, person_mask_filename)
                                        
                                        # WebP requires quality parameter, 100 for lossless
                                        success = cv2.imwrite(
                                            person_mask_path, 
                                            transparent_mask, 
                                            [cv2.IMWRITE_WEBP_QUALITY, 100]
                                        )
                                        
                                        if success:
                                            person_mask_count += 1
                                        else:
                                            self.errorOccurred.emit(f"Failed to save person mask for {filename}")
                                        
                                        person_idx += 1
                                except Exception as e:
                                    print(f"Error saving person mask for {filename}: {e}")
                                    self.errorOccurred.emit(f"Error saving person mask: {e}")

            except Exception as e:
                print(f"Error processing/saving {filename} for annotation: {e}")
                self.errorOccurred.emit(f"Error saving {filename}: {e}")
                error_count += 1

            self.progressUpdated.emit(i + 1, total_items)
            # Allow GUI responsiveness (less critical than detection worker)
            if i % 20 == 0:
                QCoreApplication.processEvents()

        if self._is_running:
            if self.save_mode == self.MODE_SEGMENTATION:
                self.statusUpdated.emit(f"Segmentation saving complete. Saved {saved_count} images.")
            elif self.save_mode == self.MODE_PERSON_WEBP:
                self.statusUpdated.emit(f"Person mask saving complete. Saved {person_mask_count} masks.")
            else:
                self.statusUpdated.emit(f"Saving complete. Saved {saved_count} images and {person_mask_count} masks.")
                
        self.saveFinished.emit(saved_count, person_mask_count, error_count)

    def stop(self):
        self._is_running = False


# --- Main Application Window ---
class ObjectDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APPLICATION_NAME} - YOLOv8 Object Segmentation (PyQt6)")
        self.setGeometry(100, 100, 1200, 800) # Increased size

        # --- State Variables ---
        self.folder_path: Optional[str] = None
        self.model_path: Optional[str] = DEFAULT_MODEL
        self.result_data: Dict[str, List[Dict[str, Any]]] = {} # Stores detections per filename
        # Caching Pixmaps: Can consume memory for many large images. Alternative is re-drawing on selection.
        # Let's use re-drawing for now for better memory usage.
        # self.annotated_pixmaps: Dict[str, Optional[QPixmap]] = {}
        self.current_files: List[str] = []
        self.detection_worker_thread: Optional[QThread] = None
        self.detection_worker: Optional[DetectionWorker] = None
        self.save_worker_thread: Optional[QThread] = None
        self.save_worker: Optional[SaveWorker] = None
        self.is_detecting = False
        self.is_saving = False
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME) # For saving state

        # --- UI Setup ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self._load_settings() # Load last paths before creating controls
        self._create_controls_section()
        self._create_main_display_area() # Using QSplitter
        self._create_status_section()
        self._apply_styles() # Apply custom styles

        self._update_button_states() # Initial button state
        self._check_model_exists() # Check default/loaded model

    def _load_settings(self):
        """Load last used paths and settings"""
        self.folder_path = self.settings.value(SETTINGS_LAST_FOLDER, None)
        self.model_path = self.settings.value(SETTINGS_LAST_MODEL, DEFAULT_MODEL)
        # Ensure loaded paths are still valid (basic check)
        if self.folder_path and not os.path.isdir(self.folder_path):
            print(f"Warning: Last folder path '{self.folder_path}' not found.")
            self.folder_path = None
        if self.model_path and not os.path.isfile(self.model_path):
            # Check if it might be in the Models folder
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODELS_FOLDER_NAME)
            model_in_folder = os.path.join(models_dir, os.path.basename(self.model_path))
            if os.path.isfile(model_in_folder):
                self.model_path = model_in_folder
            else:
                print(f"Warning: Last model path '{self.model_path}' not found.")
                # Will try to find in the Models folder during initialization

    def _save_settings(self):
        """Save current paths and settings"""
        if self.folder_path:
            self.settings.setValue(SETTINGS_LAST_FOLDER, self.folder_path)
        if self.model_path:
            self.settings.setValue(SETTINGS_LAST_MODEL, self.model_path)
        self.settings.setValue(SETTINGS_CONFIDENCE, self.confidence_spinbox.value())
        self.settings.setValue(SETTINGS_SAVE_IMMEDIATE, self.save_immediately_checkbox.isChecked())
        self.settings.setValue(SETTINGS_BLUR_STRENGTH, self.blur_strength_spinbox.value())

    def _check_model_exists(self):
        """Checks if the current model path points to a valid file."""
        if not self.model_path or not os.path.isfile(self.model_path):
            # Check if we have any valid models in the dropdown
            if self.model_combo.count() > 0 and self.model_combo.itemData(0):
                # Use the first available model
                self.model_path = self.model_combo.itemData(0)
                self.status_label.setText(f"Using model: {os.path.basename(self.model_path)}")
            else:
                self.status_label.setText(f"Warning: No valid model files found. Please add .pt files to the Models folder.")

    def _find_available_models(self):
        """Scan the Models folder for available YOLO model files (.pt)"""
        models = []
        # Get the absolute path to the Models folder (next to the script)
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODELS_FOLDER_NAME)
        
        # Create the Models folder if it doesn't exist
        if not os.path.exists(models_dir):
            os.makedirs(models_dir, exist_ok=True)
            print(f"Created Models folder at: {models_dir}")
            
        # Scan for .pt files
        if os.path.exists(models_dir):
            for file in os.listdir(models_dir):
                if file.endswith(".pt"):
                    models.append((file, os.path.join(models_dir, file)))
                    
        # Sort by name
        models.sort(key=lambda x: x[0])
        return models
        
    def _create_controls_section(self):
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0,0,0,0) # No margins for this inner layout

        # --- Top Row: File/Folder Selection ---
        file_select_layout = QHBoxLayout()
        # Model Selection
        model_group_box = QWidget() # Use simple widgets for grouping
        model_layout = QHBoxLayout(model_group_box)
        model_layout.setContentsMargins(0,0,0,0)
        model_label = QLabel("YOLO Model:")
        
        # Create model dropdown
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Select a YOLOv8 model from the Models folder")
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Populate the combobox with available models
        available_models = self._find_available_models()
        
        if available_models:
            for model_name, model_path in available_models:
                self.model_combo.addItem(model_name, model_path)
                
            # Set the last used model if it's in the list
            if self.model_path:
                model_name = os.path.basename(self.model_path)
                index = self.model_combo.findText(model_name)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                else:
                    # If not found, default to the first model
                    self.model_path = self.model_combo.itemData(0)
        else:
            # No models found, add placeholder
            self.model_combo.addItem("No models found in Models folder", "")
            
        # Connect the combobox change signal
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        
        # Add refresh button for models
        self.refresh_models_btn = QPushButton("↻")  # Refresh symbol
        self.refresh_models_btn.setToolTip("Refresh the list of available models")
        self.refresh_models_btn.setFixedWidth(30)  # Make it square-ish
        self.refresh_models_btn.clicked.connect(self._refresh_models)
        
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo, 1)  # Let it expand
        model_layout.addWidget(self.refresh_models_btn)

        # Folder Selection
        folder_group_box = QWidget()
        folder_layout = QHBoxLayout(folder_group_box)
        folder_layout.setContentsMargins(0,0,0,0)
        folder_label = QLabel("Image Folder:")
        self.folder_path_edit = QLineEdit(self.folder_path or "No folder selected")
        self.folder_path_edit.setReadOnly(True)
        self.folder_path_edit.setToolTip("Folder containing images for detection")
        self.select_folder_btn = QPushButton("Select Folder...")  # Store reference
        self.select_folder_btn.setToolTip("Select image folder")
        self.select_folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_path_edit, 1) # Stretch line edit
        folder_layout.addWidget(self.select_folder_btn)

        file_select_layout.addWidget(model_group_box)
        file_select_layout.addWidget(folder_group_box)
        controls_layout.addLayout(file_select_layout)

        # --- Second Row: Settings & Actions ---
        settings_action_layout = QHBoxLayout()

        # Confidence Threshold
        conf_label = QLabel("Confidence:")
        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setRange(0.01, 1.0)
        self.confidence_spinbox.setSingleStep(0.05)
        self.confidence_spinbox.setValue(self.settings.value(SETTINGS_CONFIDENCE, DEFAULT_CONFIDENCE, type=float))
        self.confidence_spinbox.setDecimals(2)
        self.confidence_spinbox.setToolTip("Minimum confidence threshold for detections (0.01 to 1.0)")
        self.confidence_spinbox.setFixedWidth(80)
        settings_action_layout.addWidget(conf_label)
        settings_action_layout.addWidget(self.confidence_spinbox)

        # Blur Strength
        blur_label = QLabel("Blur Strength:")
        self.blur_strength_spinbox = QDoubleSpinBox()
        self.blur_strength_spinbox.setRange(1, 15)
        self.blur_strength_spinbox.setSingleStep(1)
        self.blur_strength_spinbox.setValue(self.settings.value(SETTINGS_BLUR_STRENGTH, DEFAULT_BLUR_STRENGTH, type=float))
        self.blur_strength_spinbox.setDecimals(0)
        self.blur_strength_spinbox.setToolTip("Blur strength for anti-aliasing person mask edges (1-15)")
        self.blur_strength_spinbox.setFixedWidth(70)
        settings_action_layout.addWidget(blur_label)
        settings_action_layout.addWidget(self.blur_strength_spinbox)

        # Save Immediately Checkbox
        self.save_immediately_checkbox = QCheckBox("Save Annotated Immediately")
        self.save_immediately_checkbox.setToolTip("If checked, save annotated images during detection.\nOtherwise, use 'Draw & Save Results' button later.")
        self.save_immediately_checkbox.setChecked(self.settings.value(SETTINGS_SAVE_IMMEDIATE, False, type=bool))
        settings_action_layout.addWidget(self.save_immediately_checkbox)

        settings_action_layout.addStretch(1) # Push buttons to the right

        # Action Buttons
        self.start_button = QPushButton("Start Detection")
        self.start_button.setObjectName("StartButton") # For styling
        self.start_button.setToolTip("Start detecting objects in the selected folder")
        self.start_button.clicked.connect(self.start_detection)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setToolTip("Pause or resume the ongoing detection process")
        self.pause_button.clicked.connect(self.toggle_pause)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("StopButton") # For styling
        self.stop_button.setToolTip("Stop the current detection or saving process")
        self.stop_button.clicked.connect(self.stop_processing) # Now stops either detection or saving

        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Clear results, selections, and reset UI")
        self.clear_button.clicked.connect(self.clear_ui)

        # Replace the single Draw & Save button with two separate buttons
        self.save_segmentation_button = QPushButton("S - Save")
        self.save_segmentation_button.setObjectName("SegmentationButton") # For styling
        self.save_segmentation_button.setToolTip(f"Save annotated images with segmentation masks to '{RESULTS_FOLDER_NAME}' subfolder")
        self.save_segmentation_button.clicked.connect(self.start_save_segmentation)
        
        self.save_webp_button = QPushButton("Webp Save")
        self.save_webp_button.setObjectName("WebpButton") # For styling
        self.save_webp_button.setToolTip(f"Save person masks as transparent WebP files to '{PERSON_MASKS_FOLDER_NAME}'")
        self.save_webp_button.clicked.connect(self.start_save_webp)

        settings_action_layout.addWidget(self.start_button)
        settings_action_layout.addWidget(self.pause_button)
        settings_action_layout.addWidget(self.stop_button)
        settings_action_layout.addWidget(self.clear_button)
        settings_action_layout.addWidget(self.save_segmentation_button)
        settings_action_layout.addWidget(self.save_webp_button)

        controls_layout.addLayout(settings_action_layout)
        self.main_layout.addWidget(controls_widget)


    def _create_main_display_area(self):
        """Creates the central area with list, image, and details using a splitter."""
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Side: File List
        self.file_list_widget = QListWidget()
        self.file_list_widget.setToolTip("List of processed image files. Click to view.")
        self.file_list_widget.currentItemChanged.connect(self.display_selected_result)
        splitter.addWidget(self.file_list_widget)

        # Right Side: Image and Details (Vertical Splitter)
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        self.image_label = QLabel("Select a folder and start detection.\nProcessed images will appear here.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored) # Allow scaling
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("border: 1px solid #ccc; background-color: #f8f8f8;")
        right_splitter.addWidget(self.image_label)

        self.details_textedit = QTextEdit()
        self.details_textedit.setReadOnly(True)
        self.details_textedit.setToolTip("Details of detections for the selected image")
        self.details_textedit.setPlaceholderText("Detection details will be shown here...")
        right_splitter.addWidget(self.details_textedit)

        # Set initial sizes for the right splitter (image gets more space initially)
        right_splitter.setSizes([650, 150]) # Adjust as needed

        splitter.addWidget(right_splitter)

        # Set initial sizes for the main splitter (list gets less space initially)
        splitter.setSizes([250, 750]) # Adjust as needed

        self.main_layout.addWidget(splitter, 1) # Give splitter the stretchy space


    def _create_status_section(self):
        status_layout = QHBoxLayout()

        self.status_label = QLabel("Idle.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        status_layout.addWidget(self.status_label, 1) # Give label stretchy space
        status_layout.addWidget(self.progress_bar)

        self.main_layout.addLayout(status_layout)

    def _apply_styles(self):
        """Apply application-wide styling"""
        # More modern/cleaner style example
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f2f5; /* Light grey background */
            }
            QWidget { /* Default font for most widgets */
                 font-size: 10pt;
            }
            QPushButton {
                padding: 7px 15px;
                background-color: #0078d4; /* Microsoft blue */
                color: white;
                border: 1px solid #005a9e;
                border-radius: 4px;
                min-width: 90px;
            }
            QPushButton:hover {
                background-color: #005a9e; /* Darker blue */
                border: 1px solid #004c87;
            }
            QPushButton:pressed {
                background-color: #004c87; /* Even darker */
            }
            QPushButton:disabled {
                background-color: #e1e1e1; /* Light gray when disabled */
                color: #a0a0a0;
                border: 1px solid #c0c0c0;
            }
            QPushButton#StartButton {
                background-color: #107c10; /* Green */
                border-color: #0e600e;
            }
            QPushButton#StartButton:hover {
                background-color: #0e600e;
                border-color: #0a4d0a;
            }
            QPushButton#StopButton {
                background-color: #d93025; /* Red */
                border-color: #a52714;
            }
            QPushButton#StopButton:hover {
                background-color: #a52714;
                border-color: #8b2111;
            }
            QPushButton#SegmentationButton {
                background-color: #6b2ebf; /* Purple for segmentation */
                border-color: #5b25a0;
            }
            QPushButton#SegmentationButton:hover {
                background-color: #5b25a0;
                border-color: #4c1d85;
            }
            QPushButton#WebpButton {
                background-color: #0b6e4f; /* Teal/Green for WebP */
                border-color: #095039;
            }
            QPushButton#WebpButton:hover {
                background-color: #095039;
                border-color: #073b2a;
            }
            QLineEdit, QTextEdit, QListWidget, QDoubleSpinBox {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QLineEdit:read-only {
                background-color: #f0f0f0; /* Slightly different bg for read-only */
            }
            QProgressBar {
                text-align: center;
                height: 22px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #0078d4; /* Blue progress */
                border-radius: 3px;
                margin: 1px; /* Small margin around chunk */
            }
            QLabel {
                 padding: 2px; /* Less padding than before */
            }
            QSplitter::handle {
                background-color: #d0d2d5; /* Handle color */
            }
            QSplitter::handle:horizontal {
                width: 5px;
            }
            QSplitter::handle:vertical {
                height: 5px;
            }
            QListWidget::item:selected {
                background-color: #cce8ff; /* Light blue selection */
                color: #000000;
            }
        """)

    # --- UI Action Methods ---
    def select_folder(self):
        """Open a folder selection dialog and set the folder path."""
        start_dir = self.folder_path or os.path.expanduser("~")
        folder_path = QFileDialog.getExistingDirectory(self, "Select Image Folder", start_dir)
        if folder_path:
            self.folder_path = folder_path
            self.folder_path_edit.setText(self.folder_path)
            self._update_button_states()
            
            # Check for .pt files in the selected folder
            pt_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pt')]
            if pt_files:
                # Check if any of these models are not in the Models folder
                models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODELS_FOLDER_NAME)
                existing_models = [os.path.basename(f) for f in os.listdir(models_dir)] if os.path.exists(models_dir) else []
                new_models = [f for f in pt_files if f not in existing_models]
                
                if new_models:
                    reply = QMessageBox.question(
                        self, 
                        "Model Files Found", 
                        f"Found {len(new_models)} YOLO model files in the selected folder that are not in your Models folder.\n\nWould you like to copy them to the Models folder?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        # Create Models folder if it doesn't exist
                        if not os.path.exists(models_dir):
                            os.makedirs(models_dir, exist_ok=True)
                            
                        # Copy new models
                        for model_file in new_models:
                            src = os.path.join(folder_path, model_file)
                            dst = os.path.join(models_dir, model_file)
                            try:
                                shutil.copy2(src, dst)
                                print(f"Copied {model_file} to Models folder")
                            except Exception as e:
                                print(f"Error copying {model_file}: {e}")
                                
                        # Refresh the models dropdown
                        self._refresh_models()
                    
            # Scan for images in the selected folder
            self.status_label.setText(f"Folder selected: {os.path.basename(folder_path)}")
            
            # Count image files
            image_files = [f for f in os.listdir(folder_path) 
                          if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'))]
            
            self.status_label.setText(f"Folder selected: {os.path.basename(folder_path)} ({len(image_files)} images)")
            
            # Save the folder path in settings
            self.settings.setValue(SETTINGS_LAST_FOLDER, self.folder_path)

    def select_model(self):
        """Legacy method - now opens the Models folder instead of a file dialog"""
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODELS_FOLDER_NAME)
        
        # Create the directory if it doesn't exist
        if not os.path.exists(models_dir):
            os.makedirs(models_dir, exist_ok=True)
            
        # Open the folder in file explorer
        if sys.platform == 'win32':
            os.startfile(models_dir)
        elif sys.platform == 'darwin':  # macOS
            os.system(f'open "{models_dir}"')
        else:  # Linux
            os.system(f'xdg-open "{models_dir}"')
            
        # Show instructions
        QMessageBox.information(self, "Add Models", 
                               f"The Models folder has been opened.\n\n"
                               f"Add your .pt model files to this folder, then click the refresh button ↻ "
                               f"next to the model dropdown to update the list.")

    def start_detection(self):
        """Start the detection process by setting up and running a worker thread."""
        if not self.folder_path or not os.path.isdir(self.folder_path):
            QMessageBox.warning(self, "No Folder", "Please select a valid folder containing images first.")
            return
        
        # Get the currently selected model from the dropdown
        if self.model_combo.currentIndex() >= 0 and self.model_combo.itemData(self.model_combo.currentIndex()):
            self.model_path = self.model_combo.itemData(self.model_combo.currentIndex())
        
        if not self.model_path or not os.path.isfile(self.model_path):
            QMessageBox.warning(self, "Invalid Model", "Please select a valid YOLOv8 model (.pt file) first.")
            return
            
        # If already running, ask to stop first
        if self.is_detecting:
            QMessageBox.information(self, "Already Running", "Detection is already in progress. Stop it first before starting a new one.")
            return
            
        # Get the list of image files in the selected folder
        self.current_files = [f for f in sorted(os.listdir(self.folder_path)) 
                            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'))]
        
        if not self.current_files:
            QMessageBox.warning(self, "No Images", f"No supported image files found in: {self.folder_path}")
            return
            
        # Confirm detection
        confidence = self.confidence_spinbox.value()
        immediate_save = self.save_immediately_checkbox.isChecked()
        results_dir = os.path.join(self.folder_path, RESULTS_FOLDER_NAME) if immediate_save else "Not saving immediately"
        
        confirm_msg = (f"Ready to start detection with:\n"
                       f"- Model: {os.path.basename(self.model_path)}\n"
                       f"- Folder: {self.folder_path}\n"
                       f"- Images: {len(self.current_files)}\n"
                       f"- Confidence: {confidence}\n"
                       f"- Immediate save: {'Yes' if immediate_save else 'No'}\n")
                       
        if immediate_save:
            confirm_msg += f"- Results dir: {results_dir}\n\nContinue?"
        else:
            confirm_msg += "\nContinue?"
            
        reply = QMessageBox.question(self, "Confirm Detection", confirm_msg,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            return
            
        # Clear previous results
        self.clear_results_and_display()
        
        # Setup and run the worker
        self.is_detecting = True
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.current_files))
        self._update_button_states()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        # Save settings before running
        self._save_settings()
        
        # Setup the worker thread
        self.detection_worker_thread = QThread()
        self.detection_worker = DetectionWorker(
            model_path=self.model_path,
            folder_path=self.folder_path,
            files=self.current_files,
            confidence_threshold=confidence,
            save_immediately=immediate_save,
            results_dir=results_dir if immediate_save else ""
        )
        self.detection_worker.moveToThread(self.detection_worker_thread)
        
        # Connect signals
        self.detection_worker.progressUpdated.connect(self.update_progress)
        self.detection_worker.statusUpdated.connect(self.update_status)
        self.detection_worker.imageProcessed.connect(self.handle_processed_image)
        self.detection_worker.processingFinished.connect(self.on_detection_finished)
        self.detection_worker.errorOccurred.connect(self.show_processing_error)
        self.detection_worker_thread.started.connect(self.detection_worker.run)
        
        # Connect cleanup signals
        self.detection_worker.processingFinished.connect(self.on_detection_worker_done)
        self.detection_worker_thread.finished.connect(self.on_detection_worker_done)
            
        # Start the thread
        self.status_label.setText("Starting detection...")
        self.detection_worker_thread.start()

    def toggle_pause(self):
        if not self.is_detecting or not self.detection_worker:
            return

        if self.detection_worker._is_paused:
            self.detection_worker.resume()
            self.pause_button.setText("Pause")
        else:
            self.detection_worker.pause()
            self.pause_button.setText("Resume")
        # Status is updated by the worker itself when paused/resumed

    def stop_processing(self):
        """Stops either the detection or the saving worker."""
        if self.is_detecting and self.detection_worker:
            self.status_label.setText("Stopping detection...")
            self.detection_worker.stop() # Signal the worker to stop
            # Cleanup happens in on_detection_worker_done
        elif self.is_saving and self.save_worker:
            self.status_label.setText("Stopping saving...")
            self.save_worker.stop()
            # Cleanup happens in on_save_worker_done
        else:
             self.status_label.setText("Nothing to stop.")

    def clear_ui(self):
        reply = QMessageBox.question(self, "Confirm Clear",
                                     "Clear current results, list, and displayed image?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_results_and_display()
            self.folder_path = None
            self.folder_path_edit.setText("No folder selected")
            # Reset model selection to first item if available
            if self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
                if self.model_combo.itemData(0):
                    self.model_path = self.model_combo.itemData(0)
            self.status_label.setText("Cleared.")
            self.progress_bar.setValue(0)
            self._update_button_states()

    def clear_results_and_display(self):
        """Clears internal result data and UI display elements."""
        self.result_data = {}
        # self.annotated_pixmaps = {} # Clear cache if using pixmap caching
        self.file_list_widget.clear()
        self.image_label.clear()
        self.image_label.setText("...") # Placeholder
        self.details_textedit.clear()


    def start_save_segmentation(self):
        """Initiates the process of saving annotated images via the SaveWorker."""
        if not self.result_data:
            QMessageBox.warning(self, "No Results", "No detection results available to save. Run detection first.")
            return
        if not self.folder_path:
             QMessageBox.warning(self, "No Folder Path", "Original folder path is not set. Cannot save results.")
             return
        if self.is_detecting or self.is_saving:
            QMessageBox.information(self, "Busy", "Another process (detection or saving) is already running.")
            return

        results_dir = os.path.join(self.folder_path, RESULTS_FOLDER_NAME)
        
        reply = QMessageBox.question(self, "Confirm Save",
                                     f"This will save annotated images to:\n"
                                     f"{results_dir}\n\n"
                                     f"Existing files with the same names will be overwritten. Continue?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            return

        self.is_saving = True
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.result_data))
        self._update_button_states()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Setup and start the save worker thread with SEGMENTATION mode
        self.save_worker_thread = QThread()
        self.save_worker = SaveWorker(
            folder_path=self.folder_path, 
            results_data=self.result_data, 
            results_dir=results_dir,
            save_mode=SaveWorker.MODE_SEGMENTATION
        )
        self.save_worker.moveToThread(self.save_worker_thread)

        # Connect signals
        self.save_worker.progressUpdated.connect(self.update_progress)
        self.save_worker.statusUpdated.connect(self.update_status)
        self.save_worker.saveFinished.connect(self.on_save_finished)
        self.save_worker.errorOccurred.connect(self.show_saving_error) # Can show non-fatal saving errors
        self.save_worker_thread.started.connect(self.save_worker.run)
        # Cleanup
        self.save_worker.saveFinished.connect(self.on_save_worker_done)
        self.save_worker_thread.finished.connect(self.on_save_worker_done) # Also connect thread finish

        self.status_label.setText("Starting to save annotated images...")
        self.save_worker_thread.start()

    def start_save_webp(self):
        """Initiates the process of saving person masks as transparent WebP files."""
        if not self.result_data:
            QMessageBox.warning(self, "No Results", "No detection results available to save. Run detection first.")
            return
        if not self.folder_path:
             QMessageBox.warning(self, "No Folder Path", "Original folder path is not set. Cannot save results.")
             return
        if self.is_detecting or self.is_saving:
            QMessageBox.information(self, "Busy", "Another process (detection or saving) is already running.")
            return

        person_masks_dir = os.path.join(self.folder_path, PERSON_MASKS_FOLDER_NAME)
        
        # Get the blur strength from the spinbox
        blur_strength = int(self.blur_strength_spinbox.value())
        
        reply = QMessageBox.question(self, "Confirm Save",
                                     f"This will save person masks as transparent WebP files to:\n"
                                     f"{person_masks_dir}\n"
                                     f"(with edge smoothing level: {blur_strength})\n\n"
                                     f"Existing files with the same names will be overwritten. Continue?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            return

        self.is_saving = True
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.result_data))
        self._update_button_states()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Setup and start the save worker thread with PERSON_WEBP mode
        results_dir = os.path.join(self.folder_path, RESULTS_FOLDER_NAME)
        self.save_worker_thread = QThread()
        self.save_worker = SaveWorker(
            folder_path=self.folder_path, 
            results_data=self.result_data, 
            results_dir=results_dir, 
            blur_strength=blur_strength,
            save_mode=SaveWorker.MODE_PERSON_WEBP
        )
        self.save_worker.moveToThread(self.save_worker_thread)

        # Connect signals
        self.save_worker.progressUpdated.connect(self.update_progress)
        self.save_worker.statusUpdated.connect(self.update_status)
        self.save_worker.saveFinished.connect(self.on_save_finished)
        self.save_worker.errorOccurred.connect(self.show_saving_error) # Can show non-fatal saving errors
        self.save_worker_thread.started.connect(self.save_worker.run)
        # Cleanup
        self.save_worker.saveFinished.connect(self.on_save_worker_done)
        self.save_worker_thread.finished.connect(self.on_save_worker_done) # Also connect thread finish


        self.status_label.setText("Starting to save person masks as WebP files...")
        self.save_worker_thread.start()


    # --- Slot Methods (Called by Worker Signals) ---
    def update_progress(self, value: int, max_value: int):
        if self.progress_bar.maximum() != max_value:
            self.progress_bar.setMaximum(max_value)
        self.progress_bar.setValue(value)

    def update_status(self, message: str):
        self.status_label.setText(message)

    def handle_processed_image(self, original_path: str, annotated_cv_image: Optional[cv2.Mat], detections: list):
        """Handles the signal when one image is processed by the detection worker."""
        filename = os.path.basename(original_path)
        # Add filename to the list widget
        item = QListWidgetItem(filename)
        self.file_list_widget.addItem(item)

        # Store detection results (already done in worker, but this confirms)
        # self.result_data[filename] = detections # Already happens in worker

        # Optionally select the item to show progress visually
        self.file_list_widget.setCurrentItem(item)
        # display_selected_result will be called automatically due to currentItemChanged signal

        # If NOT caching pixmaps, display_selected_result will handle loading/drawing.
        # If caching pixmaps:
        # pixmap = convert_cv_image_to_qpixmap(annotated_cv_image)
        # self.annotated_pixmaps[filename] = pixmap # Cache it

    def display_selected_result(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        """Displays the annotated image and details for the selected file."""
        if current_item is None:
            self.image_label.clear()
            self.image_label.setText("Select an item from the list.")
            self.details_textedit.clear()
            return

        filename = current_item.text()
        if filename not in self.result_data or not self.folder_path:
             self.image_label.setText(f"Result data missing for {filename}")
             self.details_textedit.clear()
             return

        original_path = os.path.join(self.folder_path, filename)
        detections = self.result_data.get(filename, [])

        # --- Display Image (Re-draw on demand) ---
        try:
            original_image = cv2.imread(original_path)
            if original_image is None:
                raise IOError("Could not read original image")

            # Draw boxes and masks fresh each time (more memory efficient than caching pixmaps)
            annotated_image = draw_results_on_image(original_image, detections)
            pixmap = convert_cv_image_to_qpixmap(annotated_image)

            if pixmap:
                # Scale pixmap to fit the label while keeping aspect ratio
                scaled_pixmap = pixmap.scaled(self.image_label.size(),
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.image_label.setText(f"Error displaying {filename}")

        except Exception as e:
            print(f"Error loading/displaying image {filename}: {e}")
            self.image_label.setText(f"Error loading/displaying {filename}:\n{e}")


        # --- Display Details ---
        if not detections:
            self.details_textedit.setText("No objects detected.")
        else:
            details_text = f"Detections for: {filename}\n-----------------------------\n"
            for i, det in enumerate(detections):
                 details_text += (
                     f"  {i+1}. Class: {det['class_name']} (ID: {det['class_id']})\n"
                     f"     Confidence: {det['confidence']:.3f}\n"
                     f"     Box (xyxy): {det['box']}\n"
                 )
                 if "mask" in det:
                     mask = det["mask"]
                     pixel_count = np.sum(mask > 0)
                     details_text += f"     Mask: {pixel_count} pixels\n"
                 details_text += "\n"
            self.details_textedit.setText(details_text)

    def on_detection_finished(self, final_results_data: dict):
        """Called when the detection worker's run() method finishes successfully."""
        # This signal might arrive slightly before thread.finished
        self.result_data = final_results_data
        self.is_detecting = False # Mark detection as finished
        # Don't clean up worker/thread here, let on_detection_worker_done handle it
        self._save_results_to_json()
        self._update_button_states()
        # Final status update handled by worker signal already
        QMessageBox.information(self, "Detection Complete", f"Object detection finished.\nFound results for {len(self.result_data)} images.")


    def on_detection_worker_done(self):
        """Called when the detection worker thread finishes (normally or stopped)."""
        # This ensures cleanup regardless of how the worker finished
        print("Detection worker thread finished signal received.")
        self.is_detecting = False # Ensure state is updated
        self.pause_button.setText("Pause") # Reset pause button
        QApplication.restoreOverrideCursor() # Restore cursor
        
        if self.detection_worker_thread and self.detection_worker_thread.isRunning():
            print("Requesting detection thread quit...")
            self.detection_worker_thread.quit()
            if not self.detection_worker_thread.wait(3000): # Wait 3 secs
                 print("Warning: Detection thread did not terminate gracefully.")

        print("Cleaning up detection worker references...")
        self.detection_worker = None
        if self.detection_worker_thread :
             self.detection_worker_thread.deleteLater() # Schedule for deletion
             self.detection_worker_thread = None

        self.progress_bar.setValue(0) # Reset progress bar
        self._update_button_states()
        # Status label should reflect the final state (Finished/Stopped)


    def on_save_finished(self, saved_count: int, person_mask_count: int, error_count: int):
        """Called when the save worker finishes successfully."""
        self.is_saving = False
        QApplication.restoreOverrideCursor()
        self._update_button_states()
        
        # Get the blur strength that was used
        blur_strength = int(self.blur_strength_spinbox.value())
        
        # Customize message based on which save operation was performed
        if self.save_worker.save_mode == SaveWorker.MODE_SEGMENTATION:
            msg = f"Finished saving annotated images.\n" \
                  f"Successfully saved: {saved_count}\n" \
                  f"Errors: {error_count}"
        elif self.save_worker.save_mode == SaveWorker.MODE_PERSON_WEBP:
            msg = f"Finished saving person masks as WebP files.\n" \
                  f"Successfully saved: {person_mask_count} (with edge blur: {blur_strength})\n" \
                  f"Errors: {error_count}"
        else:
            # Both segmentation and WebP (MODE_ALL)
            msg = f"Finished saving all results.\n" \
                  f"Annotated images saved: {saved_count}\n" \
                  f"Person masks saved: {person_mask_count} (with edge blur: {blur_strength})\n" \
                  f"Errors: {error_count}"
            
        QMessageBox.information(self, "Save Complete", msg)
        # Don't clean up worker/thread here, let on_save_worker_done handle it


    def on_save_worker_done(self):
        """Called when the save worker thread finishes (normally or stopped)."""
        print("Save worker thread finished signal received.")
        self.is_saving = False # Ensure state is updated
        QApplication.restoreOverrideCursor() # Ensure cursor is restored
        if self.save_worker_thread and self.save_worker_thread.isRunning():
            print("Requesting save thread quit...")
            self.save_worker_thread.quit()
            if not self.save_worker_thread.wait(3000):
                 print("Warning: Save thread did not terminate gracefully.")

        print("Cleaning up save worker references...")
        self.save_worker = None
        if self.save_worker_thread:
            self.save_worker_thread.deleteLater()
            self.save_worker_thread = None

        self.progress_bar.setValue(0) # Reset progress bar
        self._update_button_states()


    def show_processing_error(self, error_message: str):
        # Show non-fatal errors from detection worker
        print(f"Processing Warning/Error: {error_message}")
        # Could add to a log window, or just update status briefly
        # self.status_label.setText(f"Warning: {error_message[:100]}...") # Show truncated error
        # Optionally use QMessageBox for more critical non-fatal errors if needed


    def show_saving_error(self, error_message: str):
         # Show non-fatal errors from save worker
         print(f"Saving Warning/Error: {error_message}")
         # self.status_label.setText(f"Save Warning: {error_message[:100]}...")


    # --- Utility Methods ---
    def _update_button_states(self):
        """Enable/disable buttons based on current state"""
        folder_selected = bool(self.folder_path and os.path.isdir(self.folder_path))
        model_selected = bool(self.model_path and os.path.isfile(self.model_path))
        results_exist = bool(self.result_data)

        can_start_detection = folder_selected and model_selected and not self.is_detecting and not self.is_saving
        can_save_results = results_exist and not self.is_detecting and not self.is_saving and folder_selected

        self.start_button.setEnabled(can_start_detection)
        self.pause_button.setEnabled(self.is_detecting)
        # Stop button enabled if either process is running
        self.stop_button.setEnabled(self.is_detecting or self.is_saving)
        self.save_segmentation_button.setEnabled(can_save_results)
        self.save_webp_button.setEnabled(can_save_results)
        
        # Use stored references to buttons
        self.refresh_models_btn.setEnabled(not self.is_detecting and not self.is_saving)
        self.model_combo.setEnabled(not self.is_detecting and not self.is_saving)
        self.select_folder_btn.setEnabled(not self.is_detecting and not self.is_saving)
        
        self.clear_button.setEnabled(not self.is_detecting and not self.is_saving)
        self.confidence_spinbox.setEnabled(not self.is_detecting and not self.is_saving)
        self.save_immediately_checkbox.setEnabled(not self.is_detecting and not self.is_saving)
        self.blur_strength_spinbox.setEnabled(not self.is_detecting and not self.is_saving)


    def _save_results_to_json(self):
        """Saves the detection results dictionary to a JSON file."""
        if not self.result_data or not self.folder_path:
            # No results or no base path to save relative to
            return

        save_path = os.path.join(self.folder_path, JSON_RESULTS_FILENAME)
        try:
            with open(save_path, "w") as f:
                json.dump(self.result_data, f, indent=4)
            print(f"Detection results saved to {save_path}") # Log to console
            self.status_label.setText(f"Idle. Results saved to {JSON_RESULTS_FILENAME}")
        except Exception as e:
            QMessageBox.critical(self, "JSON Save Error", f"Error saving results to JSON:\n{save_path}\n\n{e}")


    def resizeEvent(self, event):
        """Handle window resize events to rescale the displayed image."""
        super().resizeEvent(event)
        # Re-display the currently selected image to fit the new label size
        current_item = self.file_list_widget.currentItem()
        if current_item:
             # Calling this will re-fetch, re-draw, re-scale, and re-set the pixmap
             self.display_selected_result(current_item, None)


    def closeEvent(self, event):
        """Ensure workers are stopped and settings saved on close."""
        print("Close event triggered.")
        # Check if any worker is running
        if self.is_detecting or self.is_saving:
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "A process (detection or saving) is still running. Stop and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                print("Stopping workers due to close event...")
                self.stop_processing() # Signal workers to stop

                # Wait a short time for threads to potentially finish
                if self.detection_worker_thread and self.detection_worker_thread.isRunning():
                    self.detection_worker_thread.wait(500) # 0.5 sec timeout
                if self.save_worker_thread and self.save_worker_thread.isRunning():
                    self.save_worker_thread.wait(500)

                print("Saving settings...")
                self._save_settings() # Save settings before exiting
                print("Accepting close event.")
                event.accept() # Proceed with closing
            else:
                print("Ignoring close event.")
                event.ignore() # Don't close
        else:
            print("No workers running. Saving settings...")
            self._save_settings() # Save settings before exiting
            print("Accepting close event.")
            event.accept() # No processing, close normally

    def _on_model_changed(self, index):
        """Handle model selection changed in the combobox"""
        if index >= 0:
            self.model_path = self.model_combo.itemData(index)
            print(f"Selected model: {self.model_path}")
            self._check_model_exists()

    def _refresh_models(self):
        """Refresh the list of available models"""
        # Remember current selection
        current_model = None
        if self.model_combo.currentIndex() >= 0:
            current_model = self.model_combo.itemData(self.model_combo.currentIndex())
            
        # Clear and repopulate
        self.model_combo.clear()
        available_models = self._find_available_models()
        
        if available_models:
            for model_name, model_path in available_models:
                self.model_combo.addItem(model_name, model_path)
                
            # Try to restore previous selection
            if current_model:
                index = -1
                for i in range(self.model_combo.count()):
                    if self.model_combo.itemData(i) == current_model:
                        index = i
                        break
                        
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                else:
                    # Previous model no longer exists, use first one
                    self.model_path = self.model_combo.itemData(0)
            else:
                # No previous selection, use first one
                self.model_path = self.model_combo.itemData(0)
        else:
            # No models found, add placeholder
            self.model_combo.addItem("No models found in Models folder", "")
            self.model_path = None
            
        self._check_model_exists()
        QMessageBox.information(self, "Models Refreshed", 
                               f"Found {len(available_models)} models in the Models folder.")


# --- Main Execution ---
if __name__ == "__main__":
    # Set organization and application name for QSettings
    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setApplicationName(APPLICATION_NAME)

    app = QApplication(sys.argv)
    # Optional: Set default font
    # font = QFont("Segoe UI", 10)
    # app.setFont(font)

    main_window = ObjectDetectionApp()
    main_window.show()
    sys.exit(app.exec())

# --- END OF FILE det-objects-enhanced.py --