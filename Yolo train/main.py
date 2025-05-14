import sys
import os
import cv2 # OpenCV for image manipulation
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar, QListWidget,
    QGroupBox, QSizePolicy, QMessageBox, QComboBox
)
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize

from ultralytics import YOLO

# --- Configuration ---
# DEFAULT_MODEL_PATH = "yolov8n.pt" # Nano model, good for speed. Use yolov8s.pt, yolov8m.pt etc. for better accuracy
IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp")
# MODEL_DIRS = [".", "models"] # Directories to search for .pt files - REMOVED

class DetectionWorker(QThread):
    """Worker thread for running YOLO model inference."""
    progress_updated = pyqtSignal(int)  # Current progress (0-100)
    image_processed = pyqtSignal(QPixmap, str, list) # Processed pixmap, original path, detections list
    batch_finished = pyqtSignal(str) # Message on batch completion
    error_occurred = pyqtSignal(str) # For error messages

    def __init__(self, model_path, image_paths, output_dir=None):
        super().__init__()
        self.model_path = model_path
        self.image_paths = image_paths
        self.output_dir = output_dir
        self.is_batch = bool(output_dir) and len(image_paths) > 1
        self.model = None

    def load_model(self):
        try:
            self.model = YOLO(self.model_path)
            print(f"Model '{self.model_path}' loaded successfully.")
        except Exception as e:
            self.error_occurred.emit(f"Error loading YOLO model: {e}")
            self.model = None

    def run(self):
        if not self.image_paths:
            self.error_occurred.emit("No images selected for processing.")
            return

        if not self.model_path:
            self.error_occurred.emit("No model selected for processing.")
            return

        if not self.model:
            self.load_model()
            if not self.model: # If model loading failed
                return

        total_images = len(self.image_paths)
        for i, image_path_str in enumerate(self.image_paths):
            if not self.isRunning(): # Check if thread was stopped
                break
            
            image_path = Path(image_path_str)
            if not image_path.exists():
                print(f"Warning: Image not found {image_path_str}, skipping.")
                continue

            try:
                # Perform detection
                results = self.model(str(image_path), verbose=False) # verbose=False for cleaner console
                
                if not results or not results[0].boxes:
                    print(f"No detections in {image_path.name}")
                    annotated_frame = cv2.imread(str(image_path)) # Load original if no detections
                    detections_info = ["No objects detected."]
                else:
                    annotated_frame = results[0].plot() # Returns a BGR numpy array with detections
                    
                    detections_info = []
                    names = results[0].names # Class names
                    for box in results[0].boxes:
                        class_id = int(box.cls)
                        class_name = names[class_id]
                        confidence = float(box.conf)
                        detections_info.append(f"{class_name}: {confidence:.2f}")

                # Convert BGR (OpenCV) to RGB for QPixmap
                rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                q_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(q_image)

                self.image_processed.emit(pixmap, str(image_path), detections_info)

                if self.is_batch and self.output_dir:
                    output_path = self.output_dir / f"processed_{image_path.name}"
                    cv2.imwrite(str(output_path), annotated_frame) # Save BGR image

                if total_images > 0:
                    progress = int(((i + 1) / total_images) * 100)
                    self.progress_updated.emit(progress)

            except Exception as e:
                self.error_occurred.emit(f"Error processing {image_path.name}: {e}")
                # Continue with the next image in batch
        
        if self.is_batch:
            self.batch_finished.emit(f"Batch processing complete. Processed {total_images} images.")
        elif total_images == 1:
             self.batch_finished.emit(f"Processing complete for {Path(self.image_paths[0]).name}.")


class ModernYoloApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6 YOLO Object Detector")
        self.setGeometry(100, 100, 1000, 700) # x, y, width, height

        self.selected_image_paths = []
        self.output_directory = ""
        self.detection_worker = None
        # self.model_selector = None # REMOVED
        # self.available_models = {} # Display name -> actual path # REMOVED
        self.selected_model_path = None # Path to the user-selected model file
        self.last_processed_pixmap_original = None # Store the original pixmap for rescaling

        self.init_ui()
        self.load_stylesheet()
        # self.populate_model_selector() # Populate models after UI is set up - REMOVED
        self.update_model_selection_status() # Initial status

    def load_stylesheet(self):
        try:
            with open("styles.qss", "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print("Warning: styles.qss not found. Using default Qt styles.")
        except Exception as e:
            print(f"Error loading stylesheet: {e}")

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- Input Group ---
        input_group = QGroupBox("Input Selection")
        input_layout = QVBoxLayout(input_group)

        # Model Selection
        model_selection_layout = QHBoxLayout()
        self.btn_select_model = QPushButton("Browse for Model File (.pt)")
        self.btn_select_model.clicked.connect(self.select_model_file)
        model_selection_layout.addWidget(self.btn_select_model)
        self.lbl_selected_model = QLabel("Model: Not Selected")
        self.lbl_selected_model.setWordWrap(True)
        model_selection_layout.addWidget(self.lbl_selected_model, 1) # Allow label to expand
        input_layout.addLayout(model_selection_layout)

        # Single Image Selection
        self.btn_select_image = QPushButton("Select Single Image")
        self.btn_select_image.clicked.connect(self.select_single_image)
        input_layout.addWidget(self.btn_select_image)

        # Batch Images Selection
        self.btn_select_images_batch = QPushButton("Select Images for Batch")
        self.btn_select_images_batch.clicked.connect(self.select_batch_images)
        input_layout.addWidget(self.btn_select_images_batch)
        
        self.lbl_selected_files_count = QLabel("No images selected for batch.")
        input_layout.addWidget(self.lbl_selected_files_count)

        # Output Directory Selection
        output_dir_layout = QHBoxLayout()
        self.btn_select_output_dir = QPushButton("Select Output Directory (for Batch)")
        self.btn_select_output_dir.clicked.connect(self.select_output_directory)
        output_dir_layout.addWidget(self.btn_select_output_dir)
        self.lbl_output_dir = QLabel("Output: Not Set")
        self.lbl_output_dir.setWordWrap(True)
        output_dir_layout.addWidget(self.lbl_output_dir)
        input_layout.addLayout(output_dir_layout)
        
        main_layout.addWidget(input_group)

        # --- Processing Group ---
        processing_group = QGroupBox("Processing & Results")
        processing_layout = QHBoxLayout(processing_group)

        # Image Display Area
        display_v_layout = QVBoxLayout()
        self.image_display_label = QLabel("Processed image will appear here.")
        self.image_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_display_label.setMinimumSize(400, 300)
        self.image_display_label.setStyleSheet("border: 1px solid #606060; background-color: #202020;")
        # self.image_display_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored) # To allow shrinking
        display_v_layout.addWidget(self.image_display_label, 1) # Stretch factor

        self.lbl_current_image_path = QLabel("Current image: None")
        self.lbl_current_image_path.setWordWrap(True)
        display_v_layout.addWidget(self.lbl_current_image_path)
        
        processing_layout.addLayout(display_v_layout, 3) # Stretch factor 3 for image area

        # Detections List
        detections_v_layout = QVBoxLayout()
        detections_v_layout.addWidget(QLabel("Detected Objects:"))
        self.detections_list_widget = QListWidget()
        self.detections_list_widget.setMinimumWidth(200)
        detections_v_layout.addWidget(self.detections_list_widget, 1) # Stretch factor
        processing_layout.addLayout(detections_v_layout, 1) # Stretch factor 1 for list

        main_layout.addWidget(processing_group, 1) # Main stretch for this group


        # --- Controls and Progress ---
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)

        self.btn_process = QPushButton("Start Processing")
        self.btn_process.clicked.connect(self.start_processing)
        controls_layout.addWidget(self.btn_process)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        controls_layout.addWidget(self.progress_bar)

        main_layout.addWidget(controls_group)

        # Status Bar
        self.statusBar().showMessage("Ready. Select model and image(s) to begin.")

    def update_model_selection_status(self):
        if self.selected_model_path and self.selected_model_path.exists():
            self.lbl_selected_model.setText(f"Model: {self.selected_model_path.name}")
            self.btn_process.setEnabled(True)
        else:
            self.lbl_selected_model.setText("Model: Not Selected (Required)")
            self.btn_process.setEnabled(False) # Disable processing if no model selected

    def select_model_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select YOLO Model File", "", "Model Files (*.pt)")
        if file_name:
            self.selected_model_path = Path(file_name)
            self.update_model_selection_status()
            self.statusBar().showMessage(f"Model selected: {self.selected_model_path.name}")
        else:
            # User cancelled dialog, keep previous selection or none
            self.update_model_selection_status() # Update UI just in case

    def select_single_image(self):
        self.clear_previous_selection()
        file_filter = f"Images ({' '.join(IMAGE_EXTENSIONS)})"
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Single Image", "", file_filter)
        if file_name:
            self.selected_image_paths = [file_name]
            self.lbl_selected_files_count.setText(f"Selected: {Path(file_name).name}")
            self.lbl_output_dir.setText("Output: N/A (Single Image Mode)")
            self.output_directory = "" # Reset output dir for single image mode
            self.statusBar().showMessage(f"Image selected: {Path(file_name).name}. Click 'Start Processing'.")
            # Optionally, display the original image immediately
            # self.display_image(QPixmap(file_name), file_name, ["Original Image - Not Processed"])

    def select_batch_images(self):
        self.clear_previous_selection()
        file_filter = f"Images ({' '.join(IMAGE_EXTENSIONS)})"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Images for Batch Processing", "", file_filter)
        if files:
            self.selected_image_paths = files
            self.lbl_selected_files_count.setText(f"{len(files)} images selected for batch.")
            self.statusBar().showMessage(f"{len(files)} images selected. Select output directory and process.")
            if not self.output_directory:
                 self.statusBar().showMessage(f"{len(files)} images selected. Please select an output directory.")


    def select_output_directory(self):
        dir_name = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_name:
            self.output_directory = Path(dir_name)
            self.lbl_output_dir.setText(f"Output: {self.output_directory}")
            self.statusBar().showMessage(f"Output directory set to: {self.output_directory}")


    def clear_previous_selection(self):
        self.selected_image_paths = []
        self.image_display_label.clear()
        self.image_display_label.setText("Processed image will appear here.")
        self.lbl_current_image_path.setText("Current image: None")
        self.detections_list_widget.clear()
        self.progress_bar.setValue(0)
        # Keep output_directory unless explicitly changed for a new batch

    def start_processing(self):
        if not self.selected_image_paths:
            QMessageBox.warning(self, "No Input", "Please select image(s) first.")
            return

        if not self.selected_model_path or not self.selected_model_path.exists():
            QMessageBox.warning(self, "No Model", "Please select a YOLO model file first (.pt).")
            return

        model_path = self.selected_model_path

        is_batch = len(self.selected_image_paths) > 1
        if is_batch and not self.output_directory:
            QMessageBox.warning(self, "No Output Directory", "Please select an output directory for batch processing.")
            return

        self.set_ui_enabled(False)
        self.progress_bar.setValue(0)
        self.detections_list_widget.clear()
        self.statusBar().showMessage("Processing...")

        output_dir_for_worker = self.output_directory if is_batch or (self.selected_image_paths and self.output_directory) else None

        self.detection_worker = DetectionWorker(
            str(model_path),
            self.selected_image_paths,
            output_dir_for_worker
        )
        self.detection_worker.progress_updated.connect(self.update_progress)
        self.detection_worker.image_processed.connect(self.display_image)
        self.detection_worker.batch_finished.connect(self.on_processing_finished)
        self.detection_worker.error_occurred.connect(self.on_processing_error)
        self.detection_worker.finished.connect(self.on_worker_thread_finished) # To re-enable UI
        
        self.detection_worker.start()

    def set_ui_enabled(self, enabled):
        self.btn_select_image.setEnabled(enabled)
        self.btn_select_images_batch.setEnabled(enabled)
        self.btn_select_output_dir.setEnabled(enabled)
        self.btn_process.setEnabled(enabled)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def display_image(self, pixmap, image_path, detections_info):
        self.last_processed_pixmap_original = pixmap # Store for resize
        scaled_pixmap = pixmap.scaled(
            self.image_display_label.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_display_label.setPixmap(scaled_pixmap)
        self.lbl_current_image_path.setText(f"Showing: {Path(image_path).name}")
        
        self.detections_list_widget.clear()
        if detections_info:
            self.detections_list_widget.addItems(detections_info)
        else:
            self.detections_list_widget.addItem("No detections or info available.")


    def on_processing_finished(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.information(self, "Processing Complete", message)
        # self.set_ui_enabled(True) # Re-enable UI if thread is truly done

    def on_processing_error(self, error_message):
        self.statusBar().showMessage(f"Error: {error_message}")
        QMessageBox.critical(self, "Processing Error", error_message)
        # self.set_ui_enabled(True) # Re-enable UI even on error, if thread is done
        # It's better to rely on the worker's finished signal to re-enable UI

    def on_worker_thread_finished(self):
        """Called when the QThread's run() method has finished."""
        self.set_ui_enabled(True)
        self.detection_worker = None # Allow garbage collection
        print("Detection worker thread finished.")
        if self.progress_bar.value() < 100 and len(self.selected_image_paths) > 0 : # If not fully complete (e.g. error)
             pass # Message is already shown by error or completion signal


    def resizeEvent(self, event):
        """Handle window resize to rescale displayed image."""
        super().resizeEvent(event)
        if self.image_display_label.pixmap() and not self.image_display_label.pixmap().isNull():
            # This assumes you store the original full-size pixmap somewhere
            # or re-fetch it. For simplicity, let's just rescale current one.
            # A better way would be to store the original QPixmap and re-scale from it.
            # For this example, we'll just rescale the currently displayed pixmap.
            # This might lead to quality loss on multiple resizes if not careful.
            # A robust way: store the path or original QPixmap and call display_image again.
            
            # Simple rescale of current pixmap (may degrade quality over multiple resizes if not from original)
            current_pixmap = self.image_display_label.pixmap() # This gets the *scaled* one.
            # To do it properly, you'd need to have access to the *original* full-resolution pixmap
            # and rescale that. Let's assume `self.last_processed_pixmap_original` exists.
            # For now, this will just try to rescale whatever is there, which is not ideal.
            if hasattr(self, 'last_processed_pixmap_original') and self.last_processed_pixmap_original:
                 scaled_pixmap = self.last_processed_pixmap_original.scaled(
                    self.image_display_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                 self.image_display_label.setPixmap(scaled_pixmap)


    def closeEvent(self, event):
        """Ensure worker thread is stopped before closing."""
        if self.detection_worker and self.detection_worker.isRunning():
            print("Stopping detection worker...")
            self.detection_worker.quit() # Politely ask to stop
            self.detection_worker.wait(2000) # Wait up to 2 seconds
            if self.detection_worker.isRunning(): # Force stop if still running
                print("Terminating worker...")
                self.detection_worker.terminate()
                self.detection_worker.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Optional: Force a specific style if QSS fails or for consistency
    # app.setStyle("Fusion")
    window = ModernYoloApp()
    window.show()
    sys.exit(app.exec())