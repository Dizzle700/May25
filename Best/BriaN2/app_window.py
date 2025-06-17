# app_window.py

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QLabel, QFileDialog, QStatusBar, QProgressBar, QCheckBox,
    QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
from PIL import Image

from worker import Worker
from image_processor import ImageProcessor
from utils import get_default_output_dir, pil_to_qpixmap

class AppWindow(QMainWindow):
    def __init__(self, image_processor: ImageProcessor):
        super().__init__()
        self.setWindowTitle("BRIA Background Remover 2.0")
        self.setGeometry(100, 100, 1200, 700)

        self.image_processor = image_processor
        self.input_dir = ""
        self.output_dir = ""
        self.current_file_path = None
        self.view_mode = "before"  # or "after"
        self.processed_files = {}  # Maps input path to output path

        # Threading
        self.thread = None
        self.worker = None

        self._setup_ui()
        self._connect_signals()
        self._update_button_states()

    def _setup_ui(self):
        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Bar ---
        top_bar_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("PauseButton") # For styling
        self.pause_btn.setProperty("paused", False)
        
        self.select_folder_btn = QPushButton("Select Input Folder")
        self.select_output_btn = QPushButton("Select Output Folder")
        
        self.bbox_checkbox = QCheckBox("Create Bounding Boxes")
        
        self.before_after_btn = QPushButton("View After")

        top_bar_layout.addWidget(self.start_btn)
        top_bar_layout.addWidget(self.stop_btn)
        top_bar_layout.addWidget(self.pause_btn)
        top_bar_layout.addStretch(1)
        top_bar_layout.addWidget(self.select_folder_btn)
        top_bar_layout.addWidget(self.select_output_btn)
        top_bar_layout.addWidget(self.bbox_checkbox)
        top_bar_layout.addWidget(self.before_after_btn)
        
        main_layout.addLayout(top_bar_layout)

        # --- Main Content Area ---
        content_layout = QHBoxLayout()
        
        # Image display
        self.image_label = QLabel("Select a folder and an image to display")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 400)
        
        # Image list
        self.image_list_widget = QListWidget()
        self.image_list_widget.setMinimumWidth(250)
        
        content_layout.addWidget(self.image_label, 3) # 3/4 of the space
        content_layout.addWidget(self.image_list_widget, 1) # 1/4 of the space
        
        main_layout.addLayout(content_layout)

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _connect_signals(self):
        self.select_folder_btn.clicked.connect(self.select_input_folder)
        self.select_output_btn.clicked.connect(self.select_output_folder)
        self.image_list_widget.currentItemChanged.connect(self.on_image_selection_changed)
        self.before_after_btn.clicked.connect(self.toggle_view_mode)
        
        self.start_btn.clicked.connect(self.start_processing)
        self.stop_btn.clicked.connect(self.stop_processing)
        self.pause_btn.clicked.connect(self.toggle_pause_processing)

    # --- UI Logic Methods ---
    
    def select_input_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if dir_path:
            self.input_dir = dir_path
            self.status_bar.showMessage(f"Input folder: {self.input_dir}")
            self.populate_image_list()
            # Set default output dir if not already set
            if not self.output_dir:
                self.output_dir = get_default_output_dir(self.input_dir)
                self.status_bar.showMessage(f"Input: {self.input_dir} | Output: {self.output_dir}")
        self._update_button_states()

    def select_output_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if dir_path:
            self.output_dir = dir_path
            self.status_bar.showMessage(f"Input: {self.input_dir} | Output: {self.output_dir}")
        self._update_button_states()

    def populate_image_list(self):
        self.image_list_widget.clear()
        self.processed_files.clear()
        if not self.input_dir:
            return
        
        valid_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        for filename in os.listdir(self.input_dir):
            if os.path.splitext(filename)[1].lower() in valid_extensions:
                item = QListWidgetItem(filename)
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(self.input_dir, filename))
                self.image_list_widget.addItem(item)
    
    def on_image_selection_changed(self, current, previous):
        if current:
            self.current_file_path = current.data(Qt.ItemDataRole.UserRole)
            self.display_image()

    def display_image(self):
        if not self.current_file_path:
            return

        display_path = self.current_file_path
        
        # Check if we should show the "after" image
        if self.view_mode == "after" and self.current_file_path in self.processed_files:
            display_path = self.processed_files[self.current_file_path]

        try:
            pixmap = QPixmap(display_path)
            scaled_pixmap = pixmap.scaled(
                self.image_label.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
        except Exception as e:
            self.image_label.setText(f"Cannot load image:\n{os.path.basename(display_path)}")
            print(f"Error displaying image: {e}")

    def toggle_view_mode(self):
        if self.view_mode == "before":
            self.view_mode = "after"
            self.before_after_btn.setText("View Before")
        else:
            self.view_mode = "before"
            self.before_after_btn.setText("View After")
        self.display_image() # Refresh the view

    def _update_button_states(self, is_processing=False):
        self.start_btn.setEnabled(not is_processing and bool(self.input_dir) and bool(self.output_dir))
        self.stop_btn.setEnabled(is_processing)
        self.pause_btn.setEnabled(is_processing)
        self.select_folder_btn.setEnabled(not is_processing)
        self.select_output_btn.setEnabled(not is_processing)
        self.bbox_checkbox.setEnabled(not is_processing)

    # --- Processing Methods ---

    def start_processing(self):
        files_to_process = [self.image_list_widget.item(i).data(Qt.ItemDataRole.UserRole) 
                            for i in range(self.image_list_widget.count())]
        
        if not files_to_process:
            self.status_bar.showMessage("No images to process.")
            return

        self._update_button_states(is_processing=True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.thread = QThread()
        self.worker = Worker(self.image_processor)
        
        self.worker.files_to_process = files_to_process
        self.worker.output_dir = self.output_dir
        self.worker.create_bbox = self.bbox_checkbox.isChecked()

        self.worker.moveToThread(self.thread)

        # Connect signals from worker to slots in this class
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.progress.connect(self.update_progress)
        self.worker.image_processed.connect(self.on_image_processed)
        self.worker.error.connect(lambda msg: self.status_bar.showMessage(msg, 5000))

        self.thread.start()

    def stop_processing(self):
        if self.worker:
            self.worker.stop()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        self.on_processing_finished(stopped=True)

    def toggle_pause_processing(self):
        if self.worker:
            is_paused = self.worker.toggle_pause()
            if is_paused:
                self.pause_btn.setText("Resume")
                self.pause_btn.setProperty("paused", True)
                self.status_bar.showMessage("Processing paused.")
            else:
                self.pause_btn.setText("Pause")
                self.pause_btn.setProperty("paused", False)
                self.status_bar.showMessage("Processing resumed.")
            # This is to update the stylesheet
            self.pause_btn.style().polish(self.pause_btn)

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(f"Processing image {current} of {total}...")
        
    def on_image_processed(self, input_path, output_path):
        self.processed_files[input_path] = output_path
        # Find the list item and mark it as done
        for i in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == input_path:
                item.setBackground(QColor("#2E7D32")) # Dark green
                break
        
        # If the processed image is the one currently selected, refresh view
        if input_path == self.current_file_path:
            self.display_image()

    def on_processing_finished(self, stopped=False):
        if stopped:
            self.status_bar.showMessage("Processing stopped by user.", 5000)
        else:
            self.status_bar.showMessage("Batch processing complete.", 5000)
            
        self.progress_bar.setVisible(False)
        self._update_button_states(is_processing=False)
        
        # Cleanup thread and worker
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread.deleteLater()
            self.worker.deleteLater()
        self.thread = None
        self.worker = None

    def closeEvent(self, event):
        """Ensure the processing thread is stopped when closing the app."""
        self.stop_processing()
        event.accept()