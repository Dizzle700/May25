
import sys
import os
import json
import time
import shutil
import cv2
from ultralytics import YOLO
from typing import Optional, List, Dict, Any, Tuple

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QMessageBox,
    QSizePolicy, QListWidget, QListWidgetItem, QTextEdit, QDoubleSpinBox,
    QCheckBox
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QObject, QMutex, QWaitCondition, QSettings, QSize,
    QCoreApplication # For organization name/app name
)
from PyQt6.QtGui import QPixmap, QImage, QFont, QCursor, QIcon # Added QIcon for potential future use

# --- Constants ---
ORGANIZATION_NAME = "MyCompany" # Change as needed
APPLICATION_NAME = "YOLOv8ObjectDetector"
DEFAULT_MODEL = "yolo12x.pt"  # Default nano model
DEFAULT_CONFIDENCE = 0.35 # Default confidence threshold
RESULTS_FOLDER_NAME = "detection_results_annotated"
JSON_RESULTS_FILENAME = "detection_results.json"
SETTINGS_LAST_FOLDER = "lastFolderPath"
SETTINGS_LAST_MODEL = "lastModelPath"
SETTINGS_CONFIDENCE = "lastConfidence"
SETTINGS_SAVE_IMMEDIATE = "lastSaveImmediate"

# --- Helper Functions ---
def draw_boxes_on_image(image: cv2.Mat, detections: List[Dict[str, Any]]) -> cv2.Mat:
    """Draws bounding boxes and labels on an image."""
    if image is None:
        return None
    img_copy = image.copy()
    for detection in detections:
        try:
            box = detection["box"] # Should be [int, int, int, int]
            class_name = detection["class_name"]
            confidence = detection["confidence"]
            # Basic color - could be enhanced with class-specific colors
            color = (36, 255, 12) # Bright green

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
            print(f"Error drawing box for detection {detection}: {e}")
            continue # Skip this box if error occurs

    return img_copy

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
            # Optionally display model classes:
            # class_names = self.model.names
            # self.statusUpdated.emit(f"Model loaded. Classes: {', '.join(class_names.values())}")
            self.statusUpdated.emit(f"Model loaded. Starting detection in: {self.folder_path}")
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

                # Perform detection
                results = self.model(original_image, verbose=False, conf=self.confidence_threshold)

                # Process results
                if results and results[0].boxes:
                    for r in results[0].boxes:
                        # Confidence already filtered by model(conf=...), but double check if needed
                        confidence = float(r.conf.item())
                        # if confidence >= self.confidence_threshold: # Redundant if conf passed to model
                        class_id = int(r.cls.item())
                        box = [int(x) for x in r.xyxy[0].tolist()] # x1, y1, x2, y2
                        class_name = self.model.names.get(class_id, f"Unknown:{class_id}")

                        current_detections.append({
                            "class_id": class_id,
                            "class_name": class_name,
                            "confidence": confidence,
                            "box": box
                        })

                results_data[filename] = current_detections

                # Draw boxes IF there are detections OR if saving immediately (to save blank if no detections)
                if current_detections or self.save_immediately:
                     annotated_image = draw_boxes_on_image(original_image, current_detections)

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
             self.statusUpdated.emit("Detection processing finished.")
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
    saveFinished = pyqtSignal(int, int) # saved_count, error_count
    errorOccurred = pyqtSignal(str)

    def __init__(self, folder_path: str, results_data: Dict[str, list], results_dir: str):
        super().__init__()
        self.folder_path = folder_path
        self.results_data = results_data
        self.results_dir = results_dir
        self._is_running = True

    def run(self):
        self.statusUpdated.emit(f"Saving annotated images to {self.results_dir}...")
        saved_count = 0
        error_count = 0
        total_items = len(self.results_data)
        self.progressUpdated.emit(0, total_items)

        try:
            os.makedirs(self.results_dir, exist_ok=True)
        except OSError as e:
            self.errorOccurred.emit(f"Error creating results directory '{self.results_dir}': {e}")
            self.saveFinished.emit(0, total_items) # Indicate 0 saved, all errors
            return

        for i, (filename, detections) in enumerate(self.results_data.items()):
            if not self._is_running:
                self.statusUpdated.emit("Saving stopped.")
                break

            original_path = os.path.join(self.folder_path, filename)
            result_path = os.path.join(self.results_dir, filename)

            try:
                image = cv2.imread(original_path)
                if image is None:
                    print(f"Warning: Could not read original image {filename} during save. Skipping.")
                    self.errorOccurred.emit(f"Skipped saving {filename}: Cannot read original.")
                    error_count += 1
                    continue

                # Draw boxes (using the helper function)
                annotated_image = draw_boxes_on_image(image, detections)

                # Save the annotated image
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


            except Exception as e:
                print(f"Error processing/saving {filename} for annotation: {e}")
                self.errorOccurred.emit(f"Error saving annotated {filename}: {e}")
                error_count += 1

            self.progressUpdated.emit(i + 1, total_items)
            # Allow GUI responsiveness (less critical than detection worker)
            if i % 20 == 0:
                QCoreApplication.processEvents()

        if self._is_running:
            self.statusUpdated.emit("Annotation saving complete.")
        self.saveFinished.emit(saved_count, error_count)

    def stop(self):
        self._is_running = False


# --- Main Application Window ---
class ObjectDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APPLICATION_NAME} - YOLOv8 Object Detection (PyQt6)")
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
             print(f"Warning: Last model path '{self.model_path}' not found.")
             # Keep the path, _check_model_exists will warn user if needed
             # self.model_path = DEFAULT_MODEL # Or reset to default


    def _save_settings(self):
        """Save current paths and settings"""
        if self.folder_path:
            self.settings.setValue(SETTINGS_LAST_FOLDER, self.folder_path)
        if self.model_path:
            self.settings.setValue(SETTINGS_LAST_MODEL, self.model_path)
        self.settings.setValue(SETTINGS_CONFIDENCE, self.confidence_spinbox.value())
        self.settings.setValue(SETTINGS_SAVE_IMMEDIATE, self.save_immediately_checkbox.isChecked())

    def _check_model_exists(self):
         """Checks if the current model path points to a valid file."""
         if not self.model_path or not os.path.isfile(self.model_path):
              self.status_label.setText(f"Warning: Model file not found: {self.model_path}")
              # Optionally show a message box
              # QMessageBox.warning(self, "Model Not Found",
              #                     f"The model file specified could not be found:\n{self.model_path}\n\nPlease select a valid model.")


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
        model_label = QLabel("YOLO Model (.pt):")
        self.model_path_edit = QLineEdit(self.model_path or "")
        self.model_path_edit.setReadOnly(True)
        self.model_path_edit.setToolTip("Path to the YOLOv8 model file (.pt)")
        self.select_model_btn = QPushButton("Browse...")  # Store reference
        self.select_model_btn.setToolTip("Select YOLOv8 model file")
        self.select_model_btn.clicked.connect(self.select_model)
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_path_edit, 1) # Stretch line edit
        model_layout.addWidget(self.select_model_btn)

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
        settings_action_layout.addWidget(conf_label)
        settings_action_layout.addWidget(self.confidence_spinbox)

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

        self.draw_save_button = QPushButton("Draw & Save Results")
        self.draw_save_button.setToolTip(f"Draw detections on images and save them to '{RESULTS_FOLDER_NAME}' subfolder")
        self.draw_save_button.clicked.connect(self.start_save_results) # Starts the save worker

        settings_action_layout.addWidget(self.start_button)
        settings_action_layout.addWidget(self.pause_button)
        settings_action_layout.addWidget(self.stop_button)
        settings_action_layout.addWidget(self.clear_button)
        settings_action_layout.addWidget(self.draw_save_button)

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
        # Use the last used path if available
        start_dir = self.folder_path or os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(self, "Select Image Folder", start_dir)
        if dir_path:
            self.folder_path = dir_path
            self.folder_path_edit.setText(self.folder_path)
            self.clear_results_and_display() # Clear previous results/list
            self._update_button_states()

    def select_model(self):
        start_dir = os.path.dirname(self.model_path) if self.model_path else os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(self, "Select YOLO Model", start_dir, "PyTorch Models (*.pt)")
        if file_path:
            self.model_path = file_path
            self.model_path_edit.setText(self.model_path)
            self._check_model_exists() # Check the newly selected model
            self._update_button_states()

    def start_detection(self):
        if not self.folder_path or not os.path.isdir(self.folder_path):
            QMessageBox.warning(self, "Folder Not Selected", "Please select a valid image folder first.")
            return
        if not self.model_path or not os.path.isfile(self.model_path):
             QMessageBox.warning(self, "Model Not Found", f"Model file not found or invalid:\n{self.model_path}\nPlease select a valid model.")
             return
        if self.is_detecting or self.is_saving:
            QMessageBox.information(self, "Busy", "Another process (detection or saving) is already running.")
            return

        # Get list of image files
        try:
            all_files = os.listdir(self.folder_path)
            self.current_files = sorted([ # Sort for consistent processing order
                f for f in all_files
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'))
            ])
            if not self.current_files:
                 QMessageBox.warning(self, "No Images Found", "No supported image files found in the selected folder.")
                 return
        except OSError as e:
             QMessageBox.critical(self, "Folder Error", f"Could not read folder contents: {e}")
             return

        self.is_detecting = True
        self.pause_button.setText("Pause") # Reset pause button text
        self.clear_results_and_display() # Clear previous results
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.current_files))
        self._update_button_states()

        # Get settings from UI
        confidence = self.confidence_spinbox.value()
        save_immediately = self.save_immediately_checkbox.isChecked()
        results_dir = os.path.join(self.folder_path, RESULTS_FOLDER_NAME)

        # Setup and start the worker thread
        self.detection_worker_thread = QThread()
        self.detection_worker = DetectionWorker(
            model_path=self.model_path,
            folder_path=self.folder_path,
            files=self.current_files,
            confidence_threshold=confidence,
            save_immediately=save_immediately,
            results_dir=results_dir
        )
        self.detection_worker.moveToThread(self.detection_worker_thread)

        # Connect signals
        self.detection_worker.progressUpdated.connect(self.update_progress)
        self.detection_worker.statusUpdated.connect(self.update_status)
        self.detection_worker.imageProcessed.connect(self.handle_processed_image)
        self.detection_worker.processingFinished.connect(self.on_detection_finished)
        self.detection_worker.errorOccurred.connect(self.show_processing_error) # Show non-fatal errors
        self.detection_worker_thread.started.connect(self.detection_worker.run)
        # Cleanup connection: worker signals thread finished -> thread calls deleteLater
        self.detection_worker.processingFinished.connect(self.on_detection_worker_done)
        self.detection_worker_thread.finished.connect(self.on_detection_worker_done) # Also connect thread finish

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
            # Keep model path? Or clear? Let's keep it.
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


    def start_save_results(self):
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
                                     f"This will save annotated images to:\n{results_dir}\n\nExisting files with the same name will be overwritten. Continue?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            return

        self.is_saving = True
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.result_data))
        self._update_button_states()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Setup and start the save worker thread
        self.save_worker_thread = QThread()
        self.save_worker = SaveWorker(self.folder_path, self.result_data, results_dir)
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

            # Draw boxes fresh each time (more memory efficient than caching pixmaps)
            annotated_image = draw_boxes_on_image(original_image, detections)
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
        if self.detection_worker_thread and self.detection_worker_thread.isRunning():
            print("Requesting detection thread quit...")
            self.detection_worker_thread.quit()
            if not self.detection_worker_thread.wait(3000): # Wait 3 secs
                 print("Warning: Detection thread did not terminate gracefully.")
                 # Force terminate if needed (use with caution)
                 # self.detection_worker_thread.terminate()
                 # self.detection_worker_thread.wait()

        print("Cleaning up detection worker references...")
        self.detection_worker = None
        if self.detection_worker_thread :
             self.detection_worker_thread.deleteLater() # Schedule for deletion
             self.detection_worker_thread = None

        self.progress_bar.setValue(0) # Reset progress bar
        self._update_button_states()
        # Status label should reflect the final state (Finished/Stopped)


    def on_save_finished(self, saved_count: int, error_count: int):
        """Called when the save worker finishes successfully."""
        self.is_saving = False
        QApplication.restoreOverrideCursor()
        self._update_button_states()
        QMessageBox.information(self, "Save Complete",
                                f"Finished saving annotated images.\n"
                                f"Successfully saved: {saved_count}\n"
                                f"Errors: {error_count}")
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
        self.draw_save_button.setEnabled(can_save_results)
        
        # Use stored references to buttons
        self.select_model_btn.setEnabled(not self.is_detecting and not self.is_saving)
        self.select_folder_btn.setEnabled(not self.is_detecting and not self.is_saving)
        
        self.clear_button.setEnabled(not self.is_detecting and not self.is_saving)
        self.confidence_spinbox.setEnabled(not self.is_detecting and not self.is_saving)
        self.save_immediately_checkbox.setEnabled(not self.is_detecting and not self.is_saving)


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

# --- END OF FILE det-objects-enhanced.py ---