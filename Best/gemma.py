import sys
import os
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListWidget, QProgressBar, QLabel,
    QScrollArea, QGridLayout, QMessageBox, QDialog, QSizePolicy,
    QDialogButtonBox
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QFont, QColor, QPalette
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QEvent
import torch
from transformers import AutoProcessor, Gemma3ForConditionalGeneration
from PIL import Image
import requests
from io import BytesIO
import time

# --- Constants ---
MODEL_ID = "google/gemma-3-1b-it"
DEFAULT_PROMPT = "Describe this image in detail."
THUMBNAIL_SIZE = 150
POPUP_MAX_WIDTH = 800
POPUP_MAX_HEIGHT = 600

# --- Gemma Model Loading (Consider doing this only once) ---
# Global scope might be okay for simpler apps, or manage within the MainWindow
# Note: Loading large models can take time and memory.
print("Loading model... This might take a while.")
try:
    model = Gemma3ForConditionalGeneration.from_pretrained(
        MODEL_ID,
        device_map="auto",  # Automatically uses GPU if available
        torch_dtype=torch.bfloat16 # Use bfloat16 for efficiency
    ).eval()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    print("Model loaded successfully.")
    MODEL_LOADED = True
except Exception as e:
    print(f"Error loading model: {e}")
    model = None
    processor = None
    MODEL_LOADED = False

# --- Worker Thread for Model Inference ---
class ProcessingThread(QThread):
    progress_update = pyqtSignal(int)
    status_update = pyqtSignal(str)
    result_ready = pyqtSignal(str, str) # image_path, caption
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, image_paths, model_ref, processor_ref, prompt):
        super().__init__()
        self.image_paths = image_paths
        self.model = model_ref
        self.processor = processor_ref
        self.prompt = prompt
        self.is_running = True

    def run(self):
        if not self.model or not self.processor:
            self.error_occurred.emit("Model is not loaded. Cannot process images.")
            self.finished.emit()
            return

        total_images = len(self.image_paths)
        for i, img_path in enumerate(self.image_paths):
            if not self.is_running:
                self.status_update.emit("Processing cancelled.")
                break

            self.status_update.emit(f"Processing {os.path.basename(img_path)} ({i+1}/{total_images})...")
            try:
                # --- Load Image ---
                # Handle both local paths and potential URLs (though UI focuses on local)
                if img_path.startswith(('http://', 'https://')):
                    response = requests.get(img_path, stream=True)
                    response.raise_for_status()
                    pil_image = Image.open(BytesIO(response.content)).convert("RGB")
                else:
                    pil_image = Image.open(img_path).convert("RGB")

                # --- Prepare Input for Gemma ---
                messages = [
                    {"role": "user", "content": [
                        {"type": "image", "image": pil_image},
                        {"type": "text", "text": self.prompt}
                    ]}
                ]
                # Use apply_chat_template for Gemma-3 vision
                inputs = self.processor.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=True,
                    return_dict=True, return_tensors="pt"
                ).to(self.model.device)

                input_len = inputs["input_ids"].shape[-1]

                # --- Generate Caption ---
                with torch.inference_mode():
                    generation_output = self.model.generate(
                        **inputs,
                        max_new_tokens=150, # Increased token limit for better descriptions
                        do_sample=False # Use greedy decoding for deterministic output
                    )

                # Decode only the newly generated tokens
                generation = generation_output[0][input_len:]
                decoded_caption = self.processor.decode(generation, skip_special_tokens=True).strip()

                self.result_ready.emit(img_path, decoded_caption)
                self.progress_update.emit(int(((i + 1) / total_images) * 100))

            except FileNotFoundError:
                self.error_occurred.emit(f"Error: File not found - {img_path}")
                self.progress_update.emit(int(((i + 1) / total_images) * 100)) # Still update progress
            except requests.exceptions.RequestException as e:
                self.error_occurred.emit(f"Error fetching URL {img_path}: {e}")
                self.progress_update.emit(int(((i + 1) / total_images) * 100))
            except Exception as e:
                self.error_occurred.emit(f"Error processing {os.path.basename(img_path)}: {e}")
                # Optionally add more specific error handling for model/CUDA errors
                self.progress_update.emit(int(((i + 1) / total_images) * 100))
            finally:
                # Clear CUDA cache potentially if memory issues arise frequently
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            time.sleep(0.05) # Small sleep to allow GUI updates

        if self.is_running:
            self.status_update.emit("Processing complete.")
        self.finished.emit()

    def stop(self):
        self.is_running = False

# --- Custom Widget for Gallery Item ---
class GalleryItemWidget(QWidget):
    clicked = pyqtSignal(str, str) # image_path, caption

    def __init__(self, image_path, caption, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.caption = caption
        self.setToolTip(f"{os.path.basename(image_path)}\nClick to view larger")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        self.thumbnail_label.setStyleSheet("border: 1px solid #CCCCCC; background-color: #FAFAFA;")

        # Load thumbnail - use QImage for better format support than QPixmap directly
        img = QImage(image_path)
        if not img.isNull():
            pixmap = QPixmap.fromImage(img.scaled(THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                                                  Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
            self.thumbnail_label.setPixmap(pixmap)
        else:
             self.thumbnail_label.setText("Invalid\nImage") # Placeholder

        layout.addWidget(self.thumbnail_label)

        # Optional: Add a short caption preview below thumbnail
        # self.caption_preview = QLabel(self.caption[:30] + "..." if len(self.caption) > 30 else self.caption)
        # self.caption_preview.setWordWrap(True)
        # self.caption_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # layout.addWidget(self.caption_preview)

        self.setAutoFillBackground(True) # Important for hover effect
        self.installEventFilter(self) # To handle hover and click

    def eventFilter(self, obj, event):
        if obj == self:
            if event.type() == QEvent.Type.Enter:
                pal = self.palette()
                pal.setColor(QPalette.ColorRole.Window, QColor("#E0E0FF")) # Light lavender hover
                self.setPalette(pal)
                return True
            elif event.type() == QEvent.Type.Leave:
                pal = self.palette()
                pal.setColor(QPalette.ColorRole.Window, QColor("transparent")) # Back to transparent
                self.setPalette(pal)
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit(self.image_path, self.caption)
                    return True
        return super().eventFilter(obj, event)

# --- Popup Dialog for Image and Caption ---
class ImagePopupDialog(QDialog):
    def __init__(self, image_path, caption, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Image Viewer - {os.path.basename(image_path)}")
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)

        self.image_label = QLabel("Loading image...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored) # Allow shrinking/expanding

        # Load full image
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            # Scale pixmap to fit within reasonable bounds while keeping aspect ratio
            scaled_pixmap = pixmap.scaled(POPUP_MAX_WIDTH, POPUP_MAX_HEIGHT,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
            # Adjust dialog size hint based on image, but allow resizing
            self.resize(max(400, scaled_pixmap.width() + 40), max(300, scaled_pixmap.height() + 150))
        else:
            self.image_label.setText("Could not load image.")

        layout.addWidget(self.image_label)

        self.caption_label = QLabel("<b>Caption:</b>")
        layout.addWidget(self.caption_label)

        # Scroll area for potentially long captions
        caption_scroll = QScrollArea()
        caption_scroll.setWidgetResizable(True)
        caption_scroll.setFixedHeight(100) # Limit height
        self.caption_text = QLabel(caption)
        self.caption_text.setWordWrap(True)
        self.caption_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        caption_scroll.setWidget(self.caption_text)
        layout.addWidget(caption_scroll)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Batch Image Recognizer (Gemma-3)")
        self.setGeometry(100, 100, 1000, 700) # X, Y, Width, Height

        self.image_files = []
        self.results_data = {} # Store results: {image_path: caption}
        self.processing_thread = None

        # Apply a colorful comfy style
        self.apply_stylesheet()

        # --- Central Widget and Main Layout ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget) # Main layout: Left controls, Right gallery

        # --- Left Panel (Controls) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(250) # Fixed width for the control panel

        # File Selection
        self.select_button = QPushButton(QIcon.fromTheme("document-open", QIcon("icons/folder.png")), " Select Images") # Add icon fallback
        self.select_button.clicked.connect(self.select_images)
        self.select_button.setIconSize(QSize(16, 16))
        left_layout.addWidget(self.select_button)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setToolTip("Selected image files")
        left_layout.addWidget(self.file_list_widget)

        # Processing Controls
        self.process_button = QPushButton(QIcon.fromTheme("system-run", QIcon("icons/play.png")), " Start Processing")
        self.process_button.clicked.connect(self.start_processing)
        self.process_button.setEnabled(False) # Disabled initially
        self.process_button.setIconSize(QSize(16, 16))
        left_layout.addWidget(self.process_button)

        self.cancel_button = QPushButton(QIcon.fromTheme("process-stop", QIcon("icons/stop.png")), " Cancel")
        self.cancel_button.clicked.connect(self.cancel_processing)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setIconSize(QSize(16, 16))
        left_layout.addWidget(self.cancel_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        left_layout.addStretch() # Pushes widgets to the top

        # Save Results
        self.save_button = QPushButton(QIcon.fromTheme("document-save", QIcon("icons/save.png")), " Save Captions to Excel")
        self.save_button.clicked.connect(self.save_results)
        self.save_button.setEnabled(False) # Disabled until results are available
        self.save_button.setIconSize(QSize(16, 16))
        left_layout.addWidget(self.save_button)

        main_layout.addWidget(left_panel)

        # --- Right Panel (Gallery) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        gallery_label = QLabel("Image Gallery")
        gallery_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        right_layout.addWidget(gallery_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Hide horizontal bar initially
        self.scroll_area.setWidget(QWidget()) # Placeholder for gallery content

        self.gallery_layout = QGridLayout(self.scroll_area.widget()) # Use GridLayout
        self.gallery_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft) # Align items top-left
        self.gallery_layout.setSpacing(10) # Spacing between items

        right_layout.addWidget(self.scroll_area)
        main_layout.addWidget(right_panel)

        # Check Model Status
        if not MODEL_LOADED:
            self.status_label.setText("Status: Error loading model!")
            self.process_button.setEnabled(False)
            self.select_button.setEnabled(False)
            QMessageBox.critical(self, "Model Load Error",
                                 "Failed to load the Gemma-3 model. Please check your internet connection, "
                                 "dependencies (transformers, torch, accelerate), and GPU setup (if applicable).\n"
                                 "The application cannot process images.")
        else:
             self.status_label.setText(f"Status: Model '{MODEL_ID}' loaded. Ready.")


    def apply_stylesheet(self):
        # Basic "colorful comfy" theme - adjust colors as desired
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F0F0F8; /* Light lavender background */
            }
            QWidget { /* Default for child widgets */
                font-size: 10pt;
            }
            QPushButton {
                background-color: #4A90E2; /* Nice blue */
                color: white;
                border: 1px solid #357ABD;
                padding: 8px 12px;
                border-radius: 4px;
                min-height: 20px; /* Ensure button height */
            }
            QPushButton:hover {
                background-color: #357ABD; /* Darker blue on hover */
            }
            QPushButton:pressed {
                background-color: #2A5C9A;
            }
            QPushButton:disabled {
                background-color: #B0C4DE; /* Lighter blue-grey when disabled */
                color: #777777;
                border-color: #A0B4CE;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
            }
            QProgressBar {
                border: 1px solid #AAAAAA;
                border-radius: 3px;
                text-align: center;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #67C23A; /* Green progress */
                width: 10px; /* Width of the progress segments */
                margin: 1px;
            }
            QLabel {
                color: #333333; /* Dark grey text */
            }
            QScrollArea {
                border: 1px solid #D0D0D0;
                background-color: #FFFFFF; /* White background for gallery */
            }
            #GalleryItemWidget { /* Target custom widget by object name if needed */
                 background-color: transparent; /* Ensure transparency for hover */
            }
            QDialog {
                 background-color: #F8F8FF; /* Slightly different background for dialogs */
            }
        """)


    def select_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Images",
            "", # Start directory (empty means default/last)
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )
        if files:
            self.image_files = files
            self.file_list_widget.clear()
            self.file_list_widget.addItems([os.path.basename(f) for f in files])
            self.process_button.setEnabled(MODEL_LOADED and len(self.image_files) > 0)
            self.save_button.setEnabled(False) # Disable save until new results
            self.results_data = {} # Clear previous results
            # Clear gallery
            self.clear_gallery()
            self.status_label.setText(f"Status: Selected {len(self.image_files)} images.")
            self.progress_bar.setValue(0)

    def start_processing(self):
        if not self.image_files:
            QMessageBox.warning(self, "No Images", "Please select images first.")
            return
        if not MODEL_LOADED:
             QMessageBox.critical(self, "Model Error", "Model is not loaded. Cannot process.")
             return
        if self.processing_thread and self.processing_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Processing is already in progress.")
            return

        self.clear_gallery() # Clear gallery before starting
        self.results_data = {} # Clear results data
        self.progress_bar.setValue(0)
        self.set_controls_enabled(False)
        self.save_button.setEnabled(False)

        self.processing_thread = ProcessingThread(self.image_files, model, processor, DEFAULT_PROMPT) # Pass model refs
        self.processing_thread.progress_update.connect(self.update_progress)
        self.processing_thread.status_update.connect(self.update_status)
        self.processing_thread.result_ready.connect(self.add_result_to_gallery)
        self.processing_thread.finished.connect(self.processing_finished)
        self.processing_thread.error_occurred.connect(self.show_processing_error)
        self.processing_thread.start()

    def cancel_processing(self):
        if self.processing_thread and self.processing_thread.isRunning():
            self.status_label.setText("Status: Attempting to cancel...")
            self.processing_thread.stop()
            # Don't immediately re-enable controls, wait for the 'finished' signal
            self.cancel_button.setEnabled(False) # Prevent multiple clicks
        else:
             self.status_label.setText("Status: No active process to cancel.")


    def set_controls_enabled(self, enabled):
        self.select_button.setEnabled(enabled)
        # Only enable process button if files are selected and model is loaded
        self.process_button.setEnabled(enabled and MODEL_LOADED and len(self.image_files) > 0)
        self.cancel_button.setEnabled(not enabled) # Cancel is active when processing starts


    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(f"Status: {message}")

    def show_processing_error(self, error_message):
        # Log error or show a less intrusive notification
        print(f"Processing Error: {error_message}")
        # Maybe add to a log window later, for now just update status bar briefly
        current_status = self.status_label.text()
        self.status_label.setText(f"Status: Error occurred! Check console.")
        # Optionally popup critical errors
        # QMessageBox.warning(self, "Processing Error", error_message)
        # Restore status after a delay? No, keep error indication until next status update.


    def add_result_to_gallery(self, image_path, caption):
        if not os.path.exists(image_path) and not image_path.startswith(('http://', 'https://')):
             print(f"Skipping gallery add, image not found: {image_path}")
             return

        self.results_data[image_path] = caption

        gallery_item = GalleryItemWidget(image_path, caption)
        gallery_item.clicked.connect(self.show_image_popup)

        # --- Add to GridLayout ---
        current_item_count = self.gallery_layout.count()
        # Calculate available width, considering scrollbar possibility
        scroll_area_width = self.scroll_area.viewport().width() - 20 # Approx scrollbar width + margins
        items_per_row = max(1, scroll_area_width // (THUMBNAIL_SIZE + self.gallery_layout.spacing()))

        row = current_item_count // items_per_row
        col = current_item_count % items_per_row

        self.gallery_layout.addWidget(gallery_item, row, col)
        QApplication.processEvents() # Allow GUI to update during batch processing


    def clear_gallery(self):
         # Remove widgets from layout properly
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        # Reset internal results data if needed (done in select_images/start_processing)

    def processing_finished(self):
        self.set_controls_enabled(True)
        self.cancel_button.setEnabled(False) # Disable cancel when finished/cancelled
        if self.results_data: # Only enable save if there are results
             self.save_button.setEnabled(True)
        if self.processing_thread and not self.processing_thread.is_running: # Check if cancelled
             self.update_status("Processing cancelled by user.")
        # else: The status should already be "Processing complete." or an error state
        self.processing_thread = None # Clean up thread reference


    def show_image_popup(self, image_path, caption):
        dialog = ImagePopupDialog(image_path, caption, self)
        dialog.exec()


    def save_results(self):
        if not self.results_data:
            QMessageBox.information(self, "No Results", "No captions generated yet to save.")
            return

        default_filename = "image_captions.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Captions to Excel",
            default_filename,
            "Excel Files (*.xlsx);;All Files (*)"
        )

        if filepath:
            try:
                # Ensure correct file extension
                if not filepath.lower().endswith(".xlsx"):
                    filepath += ".xlsx"

                df_data = [{"Image Path": path, "Generated Caption": caption}
                           for path, caption in self.results_data.items()]
                df = pd.DataFrame(df_data)
                df.to_excel(filepath, index=False, engine='openpyxl') # Specify engine
                QMessageBox.information(self, "Save Successful", f"Captions saved to:\n{filepath}")
                self.status_label.setText(f"Status: Results saved to {os.path.basename(filepath)}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save Excel file:\n{e}")
                self.status_label.setText("Status: Error saving results.")


    def closeEvent(self, event):
        # Ensure thread is stopped if window is closed during processing
        if self.processing_thread and self.processing_thread.isRunning():
            reply = QMessageBox.question(self, 'Confirm Close',
                                         "Processing is in progress. Are you sure you want to quit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.cancel_processing()
                # Give the thread a moment to acknowledge the stop request
                self.processing_thread.wait(1000) # Wait up to 1 second
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# --- Application Entry Point ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Optional: Set application icon (create an 'icons' folder with 'app_icon.png')
    app_icon = QIcon("icons/app_icon.png")
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())