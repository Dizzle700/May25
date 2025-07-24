# --- START OF FILE person-detect-qt.py ---

import sys
import os
import shutil
import json
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO
from PIL import Image

# Import PyQt6 components
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar, QMessageBox, QFrame
)
from PyQt6.QtGui import QPixmap, QImage, QFont
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal, pyqtSlot

# --- Configuration ---
MODEL_NAME = "yolo12n.pt"  # Use standard nano model, change if 'yolo11n.pt' is custom and correct
PERSON_CLASS_NAME = "person" # YOLOv8 default name for person class
RESULTS_FOLDER_NAME = "results_drawn"
PERSON_PREFIX = "p_"
NO_PERSON_PREFIX = "n_"
# --- Configuration End ---

# Check CUDA availability
try:
    CUDA_AVAILABLE = torch.cuda.is_available()
    if CUDA_AVAILABLE:
        # Basic check if device can be accessed
        torch.cuda.get_device_name(0)
        DEVICE = "cuda"
        # Clear cache once at the start if using CUDA
        torch.cuda.empty_cache()
    else:
        DEVICE = "cpu"
except Exception as e:
    print(f"CUDA check failed: {e}. Falling back to CPU.")
    CUDA_AVAILABLE = False
    DEVICE = "cpu"

print(f"Using device: {DEVICE}")

# --- Worker Object for Threading ---
class DetectionWorker(QObject):
    """ Handles long-running tasks in a separate thread """
    # Signals to communicate with the main GUI thread
    progress_updated = pyqtSignal(int, int, str) # current, total, task_name
    status_updated = pyqtSignal(str)
    image_processed = pyqtSignal(str) # path to image to display
    task_finished = pyqtSignal(str, str) # task_name, message
    error_occurred = pyqtSignal(str, str) # task_name, error_message

    def __init__(self, model_path):
        super().__init__()
        self.model = None
        self.model_path = model_path
        self.folder_path = ""
        self.files_to_process = []
        self.result_data = {}
        self.batch_size = 4 if CUDA_AVAILABLE else 1
        self.is_paused = False
        self.is_stopped = False

    def _load_model(self):
        """ Loads the YOLO model """
        if self.model is None:
            try:
                self.status_updated.emit(f"Loading model '{self.model_path}' onto {DEVICE}...")
                self.model = YOLO(self.model_path)
                self.model.to(DEVICE)
                self.status_updated.emit("Model loaded successfully.")
            except Exception as e:
                self.error_occurred.emit("Model Loading", f"Failed to load model: {e}")
                self.model = None # Ensure model is None if loading failed
                return False
        return True

    def setup(self, folder_path, files):
        """ Set up parameters for the next task """
        self.folder_path = folder_path
        self.files_to_process = files
        self.result_data = {} # Clear previous results
        self.is_paused = False
        self.is_stopped = False

    @pyqtSlot()
    def run_detection(self):
        """ Performs object detection on the images """
        task_name = "Detection"
        if not self.folder_path or not self.files_to_process:
            self.error_occurred.emit(task_name, "Folder path or file list not set.")
            return

        if not self._load_model(): # Ensure model is loaded
             return

        total_files = len(self.files_to_process)
        self.status_updated.emit(f"Starting detection on {total_files} files...")
        processed_count = 0

        try:
            for i in range(0, total_files, self.batch_size):
                if self.is_stopped:
                    self.status_updated.emit("Detection stopped by user.")
                    self.task_finished.emit(task_name, "Stopped")
                    return

                while self.is_paused:
                    if self.is_stopped:
                        self.status_updated.emit("Detection stopped during pause.")
                        self.task_finished.emit(task_name, "Stopped")
                        return
                    time.sleep(0.5) # Wait while paused

                batch_files = self.files_to_process[i:min(i + self.batch_size, total_files)]
                if not batch_files: continue

                batch_paths = [os.path.join(self.folder_path, f) for f in batch_files]
                batch_images = []
                valid_indices = [] # Keep track of images successfully loaded

                # Prepare batch - handle potential load errors
                for idx, file_path in enumerate(batch_paths):
                    try:
                        # Load with OpenCV, convert color BGR->RGB for consistency if needed by model
                        # Although YOLOv8 handles BGR/RGB well internally usually
                        image = cv2.imread(file_path)
                        if image is None:
                            print(f"Warning: Could not read image {batch_files[idx]}, skipping.")
                            continue
                        batch_images.append(image)
                        valid_indices.append(idx)
                    except Exception as e:
                         print(f"Warning: Error loading image {batch_files[idx]}: {e}, skipping.")


                if not batch_images: # Skip if batch is empty after loading errors
                     processed_count += len(batch_files) # Still count them as processed
                     self.progress_updated.emit(processed_count, total_files, task_name)
                     continue

                # Process batch
                try:
                    # Use torch.inference_mode() for efficiency if not training
                    with torch.inference_mode():
                        results = self.model(batch_images, device=DEVICE, verbose=False) # verbose=False to reduce console spam
                except Exception as e:
                    self.error_occurred.emit(task_name, f"Error during model inference: {e}")
                    # Attempt to continue with next batch? Or stop? Let's stop here for safety.
                    self.task_finished.emit(task_name, "Error")
                    return


                # Process results for successfully loaded images
                current_valid_idx = 0
                for original_idx, filename in enumerate(batch_files):
                    if original_idx not in valid_indices:
                        # This file was skipped during loading
                        processed_count += 1
                        self.progress_updated.emit(processed_count, total_files, task_name)
                        continue

                    result = results[current_valid_idx]
                    current_valid_idx += 1

                    detections = []
                    for r in result.boxes:
                        class_id = int(r.cls.item())
                        confidence = float(r.conf.item())
                        # Ensure box coordinates are valid floats
                        box = [float(x) for x in r.xyxy[0].tolist()]
                        detections.append({
                            "class": class_id,
                            "class_name": self.model.names[class_id],
                            "confidence": confidence,
                            "box": box
                        })
                    self.result_data[filename] = detections

                    processed_count += 1
                    self.progress_updated.emit(processed_count, total_files, task_name)
                    self.status_updated.emit(f"Processing: {filename} ({processed_count}/{total_files})")

                    # Display the last processed valid image of the batch
                    if current_valid_idx == len(batch_images):
                       self.image_processed.emit(batch_paths[valid_indices[-1]]) # Emit path of last valid image


            # Save results after loop
            results_file = os.path.join(self.folder_path, "detection_results.json")
            try:
                with open(results_file, "w") as f:
                    json.dump(self.result_data, f, indent=4)
                self.status_updated.emit(f"Detection results saved to {results_file}")
            except Exception as e:
                self.error_occurred.emit(task_name, f"Failed to save results JSON: {e}")


            self.task_finished.emit(task_name, "Detection completed successfully.")

        except Exception as e:
            self.error_occurred.emit(task_name, f"An unexpected error occurred: {e}")
            self.task_finished.emit(task_name, "Error") # Signal finish even on error
        finally:
            # Optional: Clear cache after a large task, but might not be necessary
            # if CUDA_AVAILABLE:
            #    torch.cuda.empty_cache()
            pass

    @pyqtSlot()
    def run_drawing(self):
        """ Draws bounding boxes on images and saves them """
        task_name = "Drawing"
        if not self.folder_path or not self.result_data:
            self.error_occurred.emit(task_name, "Folder path or detection results not available.")
            return

        results_dir = Path(self.folder_path) / RESULTS_FOLDER_NAME
        results_dir.mkdir(parents=True, exist_ok=True)
        self.status_updated.emit(f"Saving annotated images to '{results_dir}'...")

        total_files = len(self.result_data)
        processed_count = 0

        try:
            for filename, detections in self.result_data.items():
                if self.is_stopped:
                    self.status_updated.emit("Drawing stopped by user.")
                    self.task_finished.emit(task_name, "Stopped")
                    return
                # No pause functionality needed for drawing/renaming usually, they are faster

                source_path = os.path.join(self.folder_path, filename)
                dest_path = results_dir / filename

                try:
                    image = cv2.imread(source_path)
                    if image is None:
                        print(f"Warning: Could not read {filename} for drawing, skipping.")
                        processed_count += 1
                        self.progress_updated.emit(processed_count, total_files, task_name)
                        continue

                    for detection in detections:
                        box = detection["box"]
                        class_name = detection["class_name"]
                        confidence = detection["confidence"]

                        start_point = (int(box[0]), int(box[1]))
                        end_point = (int(box[2]), int(box[3]))
                        # Use different colors for person vs other objects
                        color = (0, 255, 0) if class_name.lower() == PERSON_CLASS_NAME else (255, 0, 0) # Green for person, Red for others
                        thickness = 2 # Adjusted thickness
                        font_scale = 0.6 # Adjusted font scale
                        font_thickness = 1

                        cv2.rectangle(image, start_point, end_point, color, thickness)

                        label = f"{class_name}: {confidence:.2f}"
                        # Put label slightly above the box
                        label_position = (start_point[0], start_point[1] - 10 if start_point[1] > 20 else start_point[1] + 20)
                        cv2.putText(image, label, label_position, cv2.FONT_HERSHEY_SIMPLEX,
                                    font_scale, color, font_thickness, cv2.LINE_AA) # Use LINE_AA for smoother text

                    cv2.imwrite(str(dest_path), image)

                except Exception as e:
                     print(f"Warning: Error drawing/saving {filename}: {e}, skipping.")
                     # Optionally emit an error signal here too

                processed_count += 1
                self.progress_updated.emit(processed_count, total_files, task_name)
                self.status_updated.emit(f"Drawing: {filename} ({processed_count}/{total_files})")
                # Optionally display the drawn image
                # self.image_processed.emit(str(dest_path))

            self.task_finished.emit(task_name, f"Annotated images saved to '{results_dir}'.")

        except Exception as e:
            self.error_occurred.emit(task_name, f"An unexpected error occurred: {e}")
            self.task_finished.emit(task_name, "Error")


    @pyqtSlot()
    def run_renaming(self):
        """ Renames original files based on person detection """
        task_name = "Renaming"
        if not self.folder_path or not self.result_data:
            self.error_occurred.emit(task_name, "Folder path or detection results not available.")
            return

        self.status_updated.emit(f"Renaming files in '{self.folder_path}' based on detection...")

        total_files = len(self.result_data)
        processed_count = 0
        renamed_count = 0
        skipped_count = 0

        try:
            files_in_folder = set(os.listdir(self.folder_path)) # Get current files to avoid renaming already renamed ones incorrectly

            for original_filename, detections in self.result_data.items():
                if self.is_stopped:
                    self.status_updated.emit("Renaming stopped by user.")
                    self.task_finished.emit(task_name, "Stopped")
                    return

                processed_count += 1
                self.progress_updated.emit(processed_count, total_files, task_name)

                # Check if the file actually still exists with the original name
                if original_filename not in files_in_folder:
                    print(f"Info: Original file '{original_filename}' not found (already renamed or moved?), skipping.")
                    skipped_count += 1
                    continue

                has_person = any(d["class_name"].lower() == PERSON_CLASS_NAME for d in detections)
                prefix = PERSON_PREFIX if has_person else NO_PERSON_PREFIX

                # Avoid re-prefixing if already done
                if original_filename.startswith(PERSON_PREFIX) or original_filename.startswith(NO_PERSON_PREFIX):
                    print(f"Info: File '{original_filename}' seems already prefixed, skipping.")
                    skipped_count += 1
                    continue

                new_filename = f"{prefix}{original_filename}"
                source_path = os.path.join(self.folder_path, original_filename)
                dest_path = os.path.join(self.folder_path, new_filename)

                # Check if destination already exists (unlikely with prefixes, but good practice)
                if os.path.exists(dest_path):
                    print(f"Warning: Target file '{new_filename}' already exists, skipping rename for '{original_filename}'.")
                    skipped_count += 1
                    continue

                try:
                    os.rename(source_path, dest_path)
                    renamed_count += 1
                    self.status_updated.emit(f"Renamed: {original_filename} -> {new_filename} ({processed_count}/{total_files})")
                    # Update the internal list of files in the folder to reflect the change
                    files_in_folder.remove(original_filename)
                    files_in_folder.add(new_filename)

                except OSError as e:
                    print(f"Warning: Error renaming {original_filename} to {new_filename}: {e}, skipping.")
                    self.error_occurred.emit(task_name, f"Could not rename {original_filename}: {e}")
                    skipped_count += 1


            self.task_finished.emit(task_name, f"Renaming complete. Renamed: {renamed_count}, Skipped/Not found: {skipped_count}.")

        except Exception as e:
            self.error_occurred.emit(task_name, f"An unexpected error occurred during renaming: {e}")
            self.task_finished.emit(task_name, "Error")

    def stop_task(self):
        self.is_stopped = True
        self.is_paused = False # Ensure it's not stuck in pause

    def pause_task(self):
        self.is_paused = True

    def resume_task(self):
        self.is_paused = False


# --- Main Application Window ---
class ObjectDetectionApp(QMainWindow):
    # Signal to start a task in the worker thread
    start_detection_signal = pyqtSignal()
    start_drawing_signal = pyqtSignal()
    start_renaming_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Object Detection with YOLOv8 ({DEVICE})")
        self.setGeometry(100, 100, 1024, 768) # x, y, width, height

        self.folder_path = ""
        self.image_files = []
        self.detection_results = {} # Store results here after detection finishes

        # --- Setup Worker Thread ---
        self.worker_thread = QThread()
        self.worker = DetectionWorker(MODEL_NAME)
        self.worker.moveToThread(self.worker_thread)

        # Connect worker signals to GUI slots
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.status_updated.connect(self.update_status)
        self.worker.image_processed.connect(self.display_image)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.error_occurred.connect(self.show_error)

        # Connect GUI signals to worker slots (via signal forwarding)
        self.start_detection_signal.connect(self.worker.run_detection)
        self.start_drawing_signal.connect(self.worker.run_drawing)
        self.start_renaming_signal.connect(self.worker.run_renaming)

        self.worker_thread.start()

        # --- Apply Stylesheet ---
        self.setStyleSheet(self.get_stylesheet())

        # --- Create UI Elements ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20) # Add padding around window
        self.main_layout.setSpacing(15) # Spacing between major sections

        self._create_control_section()
        self._create_image_display_section()
        self._create_status_section()

        # Initial button states
        self.reset_button_states(initial=True)


    def get_stylesheet(self):
        # Simple dark theme - customize colors as needed
        return """
            QMainWindow {
                background-color: #2E2E2E; /* Dark gray background */
            }
            QWidget { /* Default for widgets unless overridden */
                color: #E0E0E0; /* Light gray text */
                font-size: 10pt;
            }
            QPushButton {
                background-color: #007ACC; /* Blue accent */
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px; /* Rounded corners */
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005C99; /* Darker blue on hover */
            }
            QPushButton:disabled {
                background-color: #555555; /* Gray when disabled */
                color: #AAAAAA;
            }
            QLabel#StatusLabel { /* Specific style for status label */
                color: #CCCCCC;
                font-size: 9pt;
            }
            QLabel#ImageLabel {
                background-color: #404040; /* Slightly lighter gray for image background */
                border: 1px solid #555555;
                border-radius: 5px;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 5px;
                text-align: center;
                background-color: #404040;
                color: white; /* Progress text color */
            }
            QProgressBar::chunk {
                background-color: #007ACC; /* Blue progress fill */
                border-radius: 4px;
                 margin: 0.5px;
            }
            QFrame#ImageContainerFrame {
                 border: 2px solid #555555;
                 border-radius: 5px;
                 padding: 5px; /* Padding inside the frame */
            }
        """

    def _create_control_section(self):
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)

        self.select_btn = QPushButton("Select Folder")
        self.select_btn.clicked.connect(self.select_folder)
        control_layout.addWidget(self.select_btn)

        self.start_btn = QPushButton("Start Detection")
        self.start_btn.clicked.connect(self.start_detection)
        control_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True) # Make it a toggle button
        self.pause_btn.clicked.connect(self.toggle_pause)
        control_layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_task)
        control_layout.addWidget(self.stop_btn)

        # Post-processing buttons
        self.draw_btn = QPushButton("Draw Results")
        self.draw_btn.clicked.connect(self.draw_results)
        control_layout.addWidget(self.draw_btn)

        self.rename_btn = QPushButton("Rename Files (p_/n_)")
        self.rename_btn.clicked.connect(self.rename_files)
        control_layout.addWidget(self.rename_btn)

        control_layout.addStretch(1) # Pushes buttons to the left

        self.main_layout.addLayout(control_layout)

    def _create_image_display_section(self):
        # Use a QFrame for a visible border/container
        image_container_frame = QFrame(self)
        image_container_frame.setObjectName("ImageContainerFrame") # For styling
        image_container_frame.setFrameShape(QFrame.Shape.StyledPanel) # Or NoFrame if border comes from QSS
        image_container_frame.setFrameShadow(QFrame.Shadow.Raised) # Optional shadow

        image_layout = QVBoxLayout(image_container_frame) # Layout inside the frame
        image_layout.setContentsMargins(5, 5, 5, 5)

        self.image_label = QLabel("Select a folder and start detection to see images here.")
        self.image_label.setObjectName("ImageLabel") # For styling
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 480) # Minimum size
        # self.image_label.setScaledContents(False) # Important: Let us handle scaling

        image_layout.addWidget(self.image_label)

        # Add the frame (containing the label) to the main layout
        # Allow the image section to expand vertically
        self.main_layout.addWidget(image_container_frame, stretch=1)

    def _create_status_section(self):
        status_layout = QVBoxLayout()
        status_layout.setSpacing(5)

        # Use specific object names for styling if needed
        self.detection_progress = QProgressBar()
        self.detection_progress.setFormat("Detection: %v/%m (%p%)")
        status_layout.addWidget(QLabel("Detection Progress:"))
        status_layout.addWidget(self.detection_progress)

        self.drawing_progress = QProgressBar()
        self.drawing_progress.setFormat("Drawing: %v/%m (%p%)")
        status_layout.addWidget(QLabel("Drawing Progress:"))
        status_layout.addWidget(self.drawing_progress)

        self.renaming_progress = QProgressBar()
        self.renaming_progress.setFormat("Renaming: %v/%m (%p%)")
        status_layout.addWidget(QLabel("Renaming Progress:"))
        status_layout.addWidget(self.renaming_progress)

        self.status_label = QLabel("Ready. Select a folder.")
        self.status_label.setObjectName("StatusLabel") # For styling
        status_layout.addWidget(self.status_label)

        self.main_layout.addLayout(status_layout)


    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if path:
            self.folder_path = path
            self.status_label.setText(f"Folder selected: {self.folder_path}")
            self.image_files = [f for f in os.listdir(self.folder_path)
                                if f.lower().endswith(('jpg', 'jpeg', 'png', 'bmp', 'webp'))]
            if not self.image_files:
                self.show_error("Folder Selection", "No supported image files found in the selected folder.")
                self.reset_button_states(initial=True)
            else:
                self.status_label.setText(f"Selected {len(self.image_files)} images in: {self.folder_path}")
                self.reset_button_states(folder_selected=True)
                self.display_image(os.path.join(self.folder_path, self.image_files[0])) # Show first image
                # Clear previous results if a new folder is selected
                self.detection_results = {}
                # Reset progress bars
                self.reset_progress_bars()

    def start_detection(self):
        if not self.folder_path or not self.image_files:
            self.show_error("Start Detection", "Please select a folder with images first.")
            return

        self.reset_button_states(processing=True)
        self.status_label.setText("Preparing for detection...")
        self.reset_progress_bars()
        self.detection_results = {} # Clear results before starting

        # Setup worker and emit signal to start
        self.worker.setup(self.folder_path, self.image_files)
        self.start_detection_signal.emit()

    def toggle_pause(self, checked):
        if checked:
            self.worker.pause_task()
            self.pause_btn.setText("Resume")
            self.status_label.setText("Detection paused.")
        else:
            self.worker.resume_task()
            self.pause_btn.setText("Pause")
            self.status_label.setText("Detection resumed.")

    def stop_task(self):
        self.status_label.setText("Stopping task...")
        self.worker.stop_task() # Signal the worker to stop
        # Buttons will be reset by the on_task_finished signal when the worker confirms stop

    def draw_results(self):
        if not self.detection_results:
             self.show_error("Draw Results", "No detection results available. Run detection first.")
             return

        self.reset_button_states(processing=True, task="Drawing")
        self.status_label.setText("Preparing to draw results...")
        self.reset_progress_bars() # Reset all for clarity, or just drawing
        self.drawing_progress.setValue(0)
        self.drawing_progress.setMaximum(len(self.detection_results))

        # Worker already has results, just tell it to draw
        self.worker.is_stopped = False # Ensure stop flag is reset for the new task
        self.start_drawing_signal.emit()

    def rename_files(self):
        if not self.detection_results:
             self.show_error("Rename Files", "No detection results available. Run detection first.")
             return

        reply = QMessageBox.question(self, "Confirm Rename",
                                     f"This will rename original files in '{self.folder_path}' "
                                     f"by adding prefixes '{PERSON_PREFIX}' (person found) or "
                                     f"'{NO_PERSON_PREFIX}' (no person). This cannot be undone easily.\n\nProceed?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Yes:
            self.reset_button_states(processing=True, task="Renaming")
            self.status_label.setText("Preparing to rename files...")
            self.reset_progress_bars()
            self.renaming_progress.setValue(0)
            self.renaming_progress.setMaximum(len(self.detection_results))

            # Worker already has results, tell it to rename
            self.worker.is_stopped = False # Ensure stop flag is reset
            self.start_renaming_signal.emit()


    @pyqtSlot(int, int, str)
    def update_progress(self, current, total, task_name):
        if task_name == "Detection":
            self.detection_progress.setMaximum(total)
            self.detection_progress.setValue(current)
        elif task_name == "Drawing":
            self.drawing_progress.setMaximum(total)
            self.drawing_progress.setValue(current)
        elif task_name == "Renaming":
             self.renaming_progress.setMaximum(total)
             self.renaming_progress.setValue(current)

    @pyqtSlot(str)
    def update_status(self, message):
        self.status_label.setText(message)

    @pyqtSlot(str)
    def display_image(self, image_path):
        try:
            if not os.path.exists(image_path):
                 print(f"Debug: Image path does not exist: {image_path}")
                 # Keep the last valid image or show placeholder
                 # self.image_label.setText("Image not found.")
                 return

            # Load image using QPixmap for display
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                 print(f"Debug: QPixmap could not load image: {image_path}")
                 # Keep the last valid image or show placeholder
                 # self.image_label.setText("Could not load image.")
                 return

            # Scale pixmap to fit the label while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(self.image_label.size(),
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)

        except Exception as e:
            print(f"Error displaying image {image_path}: {e}")
            self.image_label.setText("Error displaying image.")


    @pyqtSlot(str, str)
    def on_task_finished(self, task_name, message):
        """ Called when a worker task completes, fails, or is stopped """
        print(f"Task Finished: {task_name}, Message: {message}")
        if task_name == "Detection" and message != "Error" and message != "Stopped":
             # Store results locally only on successful completion
             self.detection_results = self.worker.result_data.copy()
             self.reset_button_states(detection_done=True)
             self.status_label.setText(f"Detection complete. Found results for {len(self.detection_results)} images.")
             # Update progress bar to 100% if it wasn't already
             self.detection_progress.setValue(self.detection_progress.maximum())

        elif task_name == "Drawing" and message != "Error" and message != "Stopped":
             self.reset_button_states(detection_done=True) # Go back to state after detection
             self.status_label.setText(message)
             self.drawing_progress.setValue(self.drawing_progress.maximum())
        elif task_name == "Renaming" and message != "Error" and message != "Stopped":
             self.reset_button_states(detection_done=True) # Go back to state after detection
             self.status_label.setText(message)
             self.renaming_progress.setValue(self.renaming_progress.maximum())
             # Refresh file list? Or inform user? Let's just show status msg.
        else:
             # Task was stopped or encountered an error
             self.reset_button_states(folder_selected=bool(self.folder_path)) # Enable select/start if folder exists
             if message == "Stopped":
                 self.status_label.setText(f"{task_name} stopped by user.")
             elif message == "Error":
                  # Error message should have already been shown by show_error slot
                  self.status_label.setText(f"{task_name} finished with errors.")
             else: # Other messages
                 self.status_label.setText(message)


        # Ensure pause button is reset
        self.pause_btn.setChecked(False)
        self.pause_btn.setText("Pause")


    @pyqtSlot(str, str)
    def show_error(self, title, message):
        print(f"Error ({title}): {message}") # Log error to console
        QMessageBox.critical(self, title, message)
        # Update status bar as well?
        self.status_label.setText(f"Error ({title}): {message[:100]}...") # Show truncated error

    def reset_progress_bars(self):
        self.detection_progress.setValue(0)
        self.detection_progress.setMaximum(100) # Default max until set
        self.drawing_progress.setValue(0)
        self.drawing_progress.setMaximum(100)
        self.renaming_progress.setValue(0)
        self.renaming_progress.setMaximum(100)


    def reset_button_states(self, initial=False, folder_selected=False, processing=False, detection_done=False, task=None):
        """ Manages the enabled/disabled state of buttons """
        if initial:
            self.select_btn.setEnabled(True)
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.draw_btn.setEnabled(False)
            self.rename_btn.setEnabled(False)
        elif folder_selected:
             self.select_btn.setEnabled(True)
             self.start_btn.setEnabled(True)
             self.pause_btn.setEnabled(False)
             self.stop_btn.setEnabled(False)
             self.draw_btn.setEnabled(False) # Disabled until detection is done
             self.rename_btn.setEnabled(False) # Disabled until detection is done
        elif processing:
             self.select_btn.setEnabled(False)
             self.start_btn.setEnabled(False)
             # Only enable pause/stop during detection
             is_detection = task == "Detection" or task is None # Default to detection if task not specified
             self.pause_btn.setEnabled(is_detection)
             self.stop_btn.setEnabled(True) # Allow stopping any task
             self.draw_btn.setEnabled(False)
             self.rename_btn.setEnabled(False)
        elif detection_done:
             self.select_btn.setEnabled(True)
             self.start_btn.setEnabled(True) # Allow restarting detection
             self.pause_btn.setEnabled(False) # Not active task
             self.stop_btn.setEnabled(False) # Not active task
             # Enable post-processing only if results exist
             has_results = bool(self.detection_results)
             self.draw_btn.setEnabled(has_results)
             self.rename_btn.setEnabled(has_results)

        # Ensure pause button text is correct if disabled
        if not self.pause_btn.isEnabled():
            self.pause_btn.setChecked(False)
            self.pause_btn.setText("Pause")


    def closeEvent(self, event):
        """ Ensure thread is stopped cleanly on exit """
        print("Closing application...")
        self.worker.stop_task() # Signal worker to stop
        self.worker_thread.quit() # Tell thread's event loop to exit
        if not self.worker_thread.wait(3000): # Wait up to 3s for thread to finish
            print("Warning: Worker thread did not terminate gracefully.")
            self.worker_thread.terminate() # Force terminate if stuck

        print("Worker thread stopped.")
        event.accept()


# --- Application Entry Point ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ObjectDetectionApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE person-detect-qt.py ---