import sys
import os
import json
from pathlib import Path
import textwrap

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QComboBox, QFileDialog,
    QProgressBar, QMessageBox, QTextEdit, QStatusBar, QListWidgetItem
)
from PyQt6.QtGui import QPixmap, QFont, QPalette, QColor, QIcon # Import QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSize # Import QSize

from PIL import Image
import torch
from transformers import AutoProcessor, AutoModelForCausalLM
import subprocess

# --- Optional: Attempt Flash Attention Installation (handle potential errors) ---
try:
    import flash_attn
    print("Flash Attention found.")
except ImportError:
    print("Flash Attention not found. Consider installing for potential speedup.")
    print("Attempting installation (might require build tools):")
    try:
        subprocess.run(
            'pip install flash-attn --no-build-isolation',
            env={'FLASH_ATTENTION_SKIP_CUDA_BUILD': "TRUE"}, # As per original script
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        print("Flash Attention installed successfully via pip.")
        # Verify import again
        import flash_attn
    except Exception as e:
        print(f"Could not install or import flash-attn: {e}\nApp will continue without it.")
# --- End Optional Installation ---


# --- Configuration ---
WRAP_TEXT_WIDTH = 80  # Characters per line for JSON export
DEFAULT_MODEL = 'gokaygokay/Florence-2-Flux'
AVAILABLE_MODELS = [
    'gokaygokay/Florence-2-Flux-Large',
    'gokaygokay/Florence-2-Flux',
]

# --- Model Loading ---
# Load models and processors outside the main class to do it once
# Use a dictionary to store them
models = {}
processors = {}

# Determine device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

def load_model_processor(model_name):
    """Loads a model and processor, handling potential errors."""
    global models, processors
    if model_name not in models:
        try:
            print(f"Loading model: {model_name}...")
            # Use float16 for GPU usage if available, might need adjustments based on GPU RAM
            dtype = torch.float16 if device.type == 'cuda' else torch.float32
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                trust_remote_code=True,
                torch_dtype=dtype # Use float16 on GPU
            ).eval().to(device)
            print(f"Loading processor: {model_name}...")
            processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
            models[model_name] = model
            processors[model_name] = processor
            print(f"Successfully loaded {model_name}")
            return True
        except Exception as e:
            print(f"Error loading {model_name}: {e}")
            QMessageBox.critical(None, "Model Load Error", f"Failed to load model/processor {model_name}:\n{e}")
            # Remove partially loaded entries if error occurred
            if model_name in models: del models[model_name]
            if model_name in processors: del processors[model_name]
            return False
    return True # Already loaded


# --- Worker Thread for Processing ---
class Worker(QObject):
    finished = pyqtSignal(dict)  # Emits dictionary {filepath: caption}
    progress = pyqtSignal(int)   # Emits percentage complete
    log = pyqtSignal(str)        # Emits status messages
    error = pyqtSignal(str)      # Emits error messages

    def __init__(self, image_paths, model_name):
        super().__init__()
        self.image_paths = image_paths
        self.model_name = model_name
        self.is_cancelled = False

    def run(self):
        results = {}
        total_images = len(self.image_paths)
        task_prompt = "<DESCRIPTION>" # As per original script

        # Ensure model/processor are loaded (should be pre-loaded, but check)
        if self.model_name not in models or self.model_name not in processors:
             if not load_model_processor(self.model_name):
                 self.error.emit(f"Failed to ensure model {self.model_name} is loaded.")
                 return # Stop if model loading failed

        model = models[self.model_name]
        processor = processors[self.model_name]

        self.log.emit(f"Starting processing with {self.model_name} on {device}...")

        for i, img_path in enumerate(self.image_paths):
            if self.is_cancelled:
                self.log.emit("Processing cancelled.")
                break
            try:
                self.log.emit(f"Processing {os.path.basename(img_path)} ({i+1}/{total_images})...")
                image = Image.open(img_path)
                if image.mode != "RGB":
                    image = image.convert("RGB")

                prompt = task_prompt + "Describe this image in great detail." # As per original script

                inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)
                # Use float16 on GPU if model is loaded in float16
                if device.type == 'cuda' and model.dtype == torch.float16:
                    inputs['pixel_values'] = inputs['pixel_values'].half()

                generated_ids = model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3,
                    repetition_penalty=1.10,
                    # early_stopping=True # Consider adding if needed
                )

                # Ensure generated_ids are on CPU for decoding
                generated_ids_cpu = generated_ids.cpu()
                generated_text = processor.batch_decode(generated_ids_cpu, skip_special_tokens=False)[0]
                # Use post_process_generation correctly
                parsed_answer = processor.post_process_generation(
                    generated_text,
                    task=task_prompt,
                    image_size=(image.width, image.height)
                )

                caption = parsed_answer.get(task_prompt, "Caption not found in model output.")
                results[img_path] = caption
                self.progress.emit(int(((i + 1) / total_images) * 100))

            except FileNotFoundError:
                err_msg = f"Error: Image file not found at {img_path}"
                self.log.emit(err_msg)
                results[img_path] = f"Error: File not found"
                self.error.emit(err_msg) # Also emit as specific error
            except Exception as e:
                err_msg = f"Error processing {os.path.basename(img_path)}: {e}"
                self.log.emit(err_msg)
                results[img_path] = f"Error: {e}"
                self.error.emit(err_msg) # Also emit as specific error
                # Optional: Stop processing on first error, or continue
                # break

            # Allow Qt event loop to process updates
            QApplication.processEvents()


        self.log.emit("Processing finished.")
        self.finished.emit(results)

    def cancel(self):
        self.is_cancelled = True

# --- Main Application Window ---
class CaptioningApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Florence-2 Batch Captioner (PyQt6)")
        self.setGeometry(100, 100, 1000, 700) # x, y, width, height

        # Data storage
        self.image_paths = []
        self.results = {} # {filepath: caption}
        self.current_index = -1
        self.processing_thread = None
        self.worker = None

        # --- Preload Default Model ---
        if not load_model_processor(DEFAULT_MODEL):
             # Handle case where even default model fails? Maybe exit?
             QMessageBox.critical(self, "Critical Error", f"Failed to load default model {DEFAULT_MODEL}. Application might not function.")
             # Potentially disable processing buttons here or sys.exit(1)


        self.initUI()
        self.apply_stylesheet() # Apply dark theme

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget) # Main horizontal layout

        # --- Left Panel: Image List ---
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(0, 0, 5, 0) # Add spacing to the right

        self.image_list_widget = QListWidget()
        self.image_list_widget.currentItemChanged.connect(self.on_list_item_selected)
        left_panel.addWidget(QLabel("Image Files:"))
        left_panel.addWidget(self.image_list_widget)

        # --- Right Panel: Controls, Gallery, Output ---
        right_panel = QVBoxLayout()

        # Top Controls
        control_layout = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.addItems(AVAILABLE_MODELS)
        self.model_combo.setCurrentText(DEFAULT_MODEL)
        self.model_combo.currentTextChanged.connect(self.on_model_changed) # Connect signal

        self.add_button = QPushButton("Add Images")
        self.add_button.setIcon(QIcon.fromTheme("list-add")) # Example icon
        self.add_button.clicked.connect(self.add_images)

        self.export_button = QPushButton("Export JSON")
        self.export_button.setIcon(QIcon.fromTheme("document-save")) # Example icon
        self.export_button.clicked.connect(self.export_json)
        self.export_button.setEnabled(False) # Disabled initially

        self.start_button = QPushButton("Start Processing")
        self.start_button.setIcon(QIcon.fromTheme("media-playback-start")) # Example icon
        self.start_button.clicked.connect(self.start_processing)
        self.start_button.setEnabled(False) # Disabled until images are added

        control_layout.addWidget(QLabel("Model:"))
        control_layout.addWidget(self.model_combo)
        control_layout.addWidget(self.add_button)
        control_layout.addWidget(self.export_button)
        control_layout.addWidget(self.start_button)
        right_panel.addLayout(control_layout)

        # Gallery Area
        gallery_layout = QVBoxLayout()
        self.image_label = QLabel("Select an image from the list or add images.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(400, 300) # Ensure it has some size
        self.image_label.setStyleSheet("border: 1px solid #555; background-color: #2a2a2a;") # Simple border

        self.caption_output = QTextEdit()
        self.caption_output.setReadOnly(True)
        self.caption_output.setPlaceholderText("Caption will appear here after processing.")
        self.caption_output.setFixedHeight(100) # Limit height

        gallery_layout.addWidget(self.image_label, stretch=1) # Allow image label to expand
        gallery_layout.addWidget(QLabel("Generated Caption:"))
        gallery_layout.addWidget(self.caption_output)
        right_panel.addLayout(gallery_layout, stretch=1) # Allow gallery to expand vertically

        # Navigation Controls
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("<< Previous")
        self.prev_button.setIcon(QIcon.fromTheme("go-previous")) # Example icon
        self.prev_button.clicked.connect(self.show_previous)
        self.prev_button.setEnabled(False)

        self.next_button = QPushButton("Next >>")
        self.next_button.setIcon(QIcon.fromTheme("go-next")) # Example icon
        self.next_button.clicked.connect(self.show_next)
        self.next_button.setEnabled(False)

        nav_layout.addStretch()
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addStretch()
        right_panel.addLayout(nav_layout)

        # Progress Bar and Status Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        right_panel.addWidget(self.progress_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Add images to start.")

        # Add panels to main layout
        main_layout.addLayout(left_panel, stretch=1) # Left panel takes less space
        main_layout.addLayout(right_panel, stretch=3) # Right panel takes more space


    def apply_stylesheet(self):
        """Applies a dark theme stylesheet."""
        style = """
            QMainWindow {
                background-color: #2E2E2E; /* Dark grey background */
            }
            QWidget {
                color: #E0E0E0; /* Light grey text */
                background-color: #3C3C3C; /* Slightly lighter grey for widgets */
                font-size: 10pt;
            }
            QLabel {
                background-color: transparent; /* Labels shouldn't have widget background */
                padding: 2px;
            }
            QPushButton {
                background-color: #555555; /* Medium grey buttons */
                border: 1px solid #777777;
                padding: 5px 10px;
                border-radius: 3px;
                min-width: 80px; /* Ensure buttons have some width */
            }
            QPushButton:hover {
                background-color: #6A6A6A; /* Lighter grey on hover */
                border: 1px solid #888888;
            }
            QPushButton:pressed {
                background-color: #4D4D4D; /* Darker grey when pressed */
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888888;
                border-color: #555555;
            }
            QComboBox {
                background-color: #555555;
                border: 1px solid #777777;
                padding: 3px 5px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #666666;
                width: 15px;
                border-radius: 3px;
            }
            QComboBox::down-arrow {
                 image: url(icons/down_arrow.png); /* Optional: Add custom arrow icon */
            }
            QComboBox QAbstractItemView { /* Style for dropdown list */
                background-color: #444444;
                border: 1px solid #666666;
                selection-background-color: #007ACC; /* Accent color for selection */
            }
            QListWidget {
                background-color: #444444; /* Darker background for list */
                border: 1px solid #555555;
                border-radius: 3px;
                outline: 0; /* Remove focus outline */
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #007ACC; /* Accent color for selected item */
                color: #FFFFFF; /* White text for selected item */
            }
            QTextEdit {
                background-color: #444444;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                background-color: #444444;
            }
            QProgressBar::chunk {
                background-color: #007ACC; /* Accent color for progress */
                border-radius: 3px;
            }
            QStatusBar {
                background-color: #2E2E2E;
            }
            #image_label { /* Specific style for image label if needed */
                 border: 1px solid #666;
                 background-color: #333;
            }
        """
        self.setStyleSheet(style)
        # Adjust palette for text color consistency if needed
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#E0E0E0"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#AAAAAA"))
        self.setPalette(palette)


    def on_model_changed(self, model_name):
        """Handles model selection change."""
        self.status_bar.showMessage(f"Attempting to load {model_name}...")
        QApplication.processEvents() # Update UI
        if not load_model_processor(model_name):
            self.status_bar.showMessage(f"Failed to load {model_name}. Reverting.")
            # Optionally revert to default or previous valid model
            self.model_combo.setCurrentText(DEFAULT_MODEL) # Example: revert to default
        else:
             self.status_bar.showMessage(f"Model {model_name} loaded. Ready.")
        # Reset results if model changes? Or allow reprocessing?
        # self.results = {}
        # self.export_button.setEnabled(False)
        # self.caption_output.clear()
        # self.update_navigation_buttons() # Re-enable nav if items exist


    def add_images(self):
        """Opens a file dialog to add image files to the list."""
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        if file_dialog.exec():
            new_paths = file_dialog.selectedFiles()
            added_count = 0
            for path in new_paths:
                if path not in self.image_paths:
                    self.image_paths.append(path)
                    item = QListWidgetItem(os.path.basename(path))
                    item.setData(Qt.ItemDataRole.UserRole, path) # Store full path
                    self.image_list_widget.addItem(item)
                    added_count += 1

            if added_count > 0:
                self.start_button.setEnabled(True)
                self.status_bar.showMessage(f"Added {added_count} images. Ready to process.")
                if self.image_list_widget.currentRow() == -1:
                    self.image_list_widget.setCurrentRow(0) # Select first item

    def on_list_item_selected(self, current_item, previous_item):
        """Updates the gallery view when a list item is clicked."""
        if current_item:
            filepath = current_item.data(Qt.ItemDataRole.UserRole)
            self.current_index = self.image_paths.index(filepath) # Find index
            self.display_image_and_caption(filepath)
            self.update_navigation_buttons()
        else:
            self.current_index = -1
            self.image_label.setText("No image selected.")
            self.caption_output.clear()
            self.update_navigation_buttons()

    def display_image_and_caption(self, filepath):
        """Loads and displays the image and its caption (if available)."""
        try:
            pixmap = QPixmap(filepath)
            if pixmap.isNull():
                 self.image_label.setText(f"Error loading preview for\n{os.path.basename(filepath)}")
                 self.caption_output.clear()
                 return

            # Scale pixmap to fit label while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.image_label.size() * 0.95, # Scale slightly smaller than label
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)

            # Display caption if already processed
            if filepath in self.results:
                self.caption_output.setText(self.results[filepath])
            else:
                self.caption_output.setPlaceholderText("Caption will appear here after processing.")
                self.caption_output.clear() # Clear any old text

        except Exception as e:
            self.image_label.setText(f"Error displaying image:\n{e}")
            self.caption_output.clear()
            print(f"Error displaying image {filepath}: {e}")

    def update_navigation_buttons(self):
        """Enables/disables Previous/Next buttons based on current index."""
        count = len(self.image_paths)
        if count <= 1 or self.current_index == -1:
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
        else:
            self.prev_button.setEnabled(self.current_index > 0)
            self.next_button.setEnabled(self.current_index < count - 1)

    def show_previous(self):
        """Selects the previous item in the list."""
        if self.current_index > 0:
            self.image_list_widget.setCurrentRow(self.current_index - 1)

    def show_next(self):
        """Selects the next item in the list."""
        if self.current_index < len(self.image_paths) - 1:
            self.image_list_widget.setCurrentRow(self.current_index + 1)

    # --- Processing Logic ---
    def start_processing(self):
        """Starts the batch processing in a separate thread."""
        if not self.image_paths:
            QMessageBox.warning(self, "No Images", "Please add images before processing.")
            return

        if self.processing_thread and self.processing_thread.isRunning():
             # Ask to cancel current processing
             reply = QMessageBox.question(self, "Processing Active",
                                         "Processing is already running. Cancel current process?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.Yes and self.worker:
                 self.worker.cancel()
                 self.status_bar.showMessage("Cancellation requested...")
                 # Re-enable buttons etc. will happen in on_processing_finished
             return # Don't start a new one yet

        self.status_bar.showMessage("Starting processing...")
        self.progress_bar.setValue(0)
        self.set_ui_enabled(False) # Disable UI during processing

        selected_model = self.model_combo.currentText()
        if selected_model not in models: # Double check model loaded
             QMessageBox.critical(self, "Model Error", f"Selected model '{selected_model}' is not loaded.")
             self.set_ui_enabled(True)
             return


        # Create and start thread
        self.processing_thread = QThread()
        self.worker = Worker(list(self.image_paths), selected_model) # Pass a copy
        self.worker.moveToThread(self.processing_thread)

        # Connect signals
        self.processing_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.log_message)
        self.worker.error.connect(self.handle_error) # Connect error signal

        # Clean up after thread finishes
        self.worker.finished.connect(self.processing_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.processing_thread.finished.connect(self.processing_thread.deleteLater)
        self.processing_thread.finished.connect(self.clear_thread_references) # Add cleanup

        self.processing_thread.start()


    def update_progress(self, value):
        """Updates the progress bar."""
        self.progress_bar.setValue(value)

    def log_message(self, message):
        """Displays log messages in the status bar."""
        self.status_bar.showMessage(message)
        print(message) # Also print to console for debugging

    def handle_error(self, error_message):
        """Handles errors reported by the worker thread."""
        QMessageBox.warning(self, "Processing Error", error_message)
        # Keep UI disabled until finished signal is received, or enable partially?
        # For simplicity, wait for finished signal.

    def on_processing_finished(self, results_dict):
        """Handles completion of the processing thread."""
        self.results.update(results_dict) # Update main results
        self.status_bar.showMessage(f"Processing complete. {len(results_dict)} items processed.")
        self.progress_bar.setValue(100)
        self.export_button.setEnabled(len(self.results) > 0)
        self.set_ui_enabled(True) # Re-enable UI

        # Refresh caption for currently selected image
        if self.current_index != -1:
            current_path = self.image_paths[self.current_index]
            if current_path in self.results:
                 self.caption_output.setText(self.results[current_path])

        # Clear thread references
        # self.processing_thread = None # Done in clear_thread_references
        # self.worker = None


    def clear_thread_references(self):
        """Clear worker and thread vars after thread finishes"""
        print("Clearing thread references.")
        self.processing_thread = None
        self.worker = None


    def set_ui_enabled(self, enabled):
        """Enables or disables UI elements during processing."""
        self.image_list_widget.setEnabled(enabled)
        self.model_combo.setEnabled(enabled)
        self.add_button.setEnabled(enabled)
        self.start_button.setEnabled(enabled and len(self.image_paths) > 0)
        # Only enable export if results exist and UI is enabled
        self.export_button.setEnabled(enabled and len(self.results) > 0)
        self.prev_button.setEnabled(enabled and self.current_index > 0)
        self.next_button.setEnabled(enabled and self.current_index < len(self.image_paths) - 1)


    # --- Export Logic ---
    def export_json(self):
        """Exports the results (filename: wrapped_caption) to a JSON file."""
        if not self.results:
            QMessageBox.warning(self, "No Results", "No captions have been generated yet.")
            return

        default_filename = "captions.json"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Captions",
            default_filename,
            "JSON Files (*.json)"
        )

        if filepath:
            export_data = {}
            for img_path, caption in self.results.items():
                filename = os.path.basename(img_path)
                # Wrap text - use textwrap library
                wrapped_lines = textwrap.wrap(caption, width=WRAP_TEXT_WIDTH)
                wrapped_caption = "\n".join(wrapped_lines)
                export_data[filename] = wrapped_caption

            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=4, ensure_ascii=False)
                self.status_bar.showMessage(f"Captions exported successfully to {filepath}")
                QMessageBox.information(self, "Export Successful", f"Captions saved to:\n{filepath}")
            except Exception as e:
                self.status_bar.showMessage(f"Error exporting JSON: {e}")
                QMessageBox.critical(self, "Export Error", f"Could not save JSON file:\n{e}")

    # --- Cleanup on Close ---
    def closeEvent(self, event):
        """Handle closing the window, stopping threads if running."""
        if self.processing_thread and self.processing_thread.isRunning():
             reply = QMessageBox.question(self, "Confirm Exit",
                                         "Processing is still running. Are you sure you want to exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.Yes:
                 if self.worker:
                     self.worker.cancel() # Request cancellation
                 # Optionally wait briefly for thread to finish?
                 # self.processing_thread.quit()
                 # self.processing_thread.wait(1000) # Wait max 1 sec
                 event.accept()
             else:
                 event.ignore()
        else:
             event.accept()


# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Set Fusion style for better cross-platform look before applying custom QSS
    # app.setStyle("Fusion")

    window = CaptioningApp()
    window.show()
    sys.exit(app.exec())