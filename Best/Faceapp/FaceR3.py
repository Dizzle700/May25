import sys
import os
import sqlite3
import numpy as np
import torch
import cv2
from PIL import Image, UnidentifiedImageError
from facenet_pytorch import MTCNN, InceptionResnetV1
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                             QHBoxLayout, QLabel, QListWidget, QWidget, QStatusBar,
                             QGroupBox, QTextEdit, QFileDialog, QInputDialog, QLineEdit,
                             QDialog, QFormLayout, QComboBox, QProgressBar, QMessageBox,
                             QListWidgetItem, QDoubleSpinBox, QSizePolicy)
from PyQt5.QtGui import QPixmap, QImage, QFont, QColor, QPalette
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime
from typing import List, Dict, Optional, Tuple, Any

# --- Constants ---
DEFAULT_FACE_THRESHOLD = 0.7
DB_TABLE_NAME = "face_embeddings"
MODEL_IMAGE_SIZE = 160
MIN_FACE_SIZE = 20
FACE_MARGIN_PERCENT = 0.1 # 10% margin


# --- Helper Functions ---
def numpy_to_qimage(np_image: np.ndarray) -> Optional[QImage]:
    """Converts a NumPy array (RGB) to QImage."""
    if np_image is None or np_image.size == 0:
        return None
    # Ensure it's contiguous
    if not np_image.flags['C_CONTIGUOUS']:
        np_image = np.ascontiguousarray(np_image)

    if np_image.ndim == 3 and np_image.shape[2] == 3: # RGB
        height, width, channel = np_image.shape
        bytes_per_line = 3 * width
        return QImage(np_image.data, width, height, bytes_per_line, QImage.Format_RGB888)
    elif np_image.ndim == 2: # Grayscale maybe? Handle if needed, currently expecting RGB
        # Handle grayscale if necessary
        pass
    return None

# --- Processing Thread ---
class BatchImageProcessor(QThread):
    """Processes a batch of images to detect and embed faces in a separate thread."""
    update_progress = pyqtSignal(int, int, str)  # current, total, current_image_path
    face_detected = pyqtSignal(np.ndarray, np.ndarray, str)  # face_image (rgb numpy), embedding, image_path
    processing_finished = pyqtSignal(str) # Completion message
    log_message = pyqtSignal(str) # Signal to log messages from the thread

    def __init__(self, mtcnn: MTCNN, facenet: InceptionResnetV1, device: torch.device):
        super().__init__()
        self._running = True
        self._paused = False
        self._image_paths: List[str] = []
        self.mtcnn = mtcnn
        self.facenet = facenet
        self.device = device

    def set_images(self, image_paths: List[str]):
        """Sets the list of image paths to process."""
        self._image_paths = image_paths
        self._running = True
        self._paused = False

    def run(self):
        """The main processing loop."""
        total = len(self._image_paths)
        processed = 0
        self.log_message.emit(f"Starting batch processing of {total} images.")

        for img_path in self._image_paths:
            if not self._running:
                self.log_message.emit("Processing stopped by user.")
                break

            while self._paused:
                if not self._running: # Check again in case stop was called while paused
                     self.log_message.emit("Processing stopped by user while paused.")
                     break
                self.msleep(100) # Wait while paused

            if not self._running: # Final check after pause loop
                break

            processed += 1
            self.update_progress.emit(processed, total, img_path)

            try:
                # Load image using PIL
                img = Image.open(img_path).convert('RGB') # Ensure RGB
            except FileNotFoundError:
                self.log_message.emit(f"Error: Image file not found: {img_path}")
                continue
            except UnidentifiedImageError:
                self.log_message.emit(f"Error: Cannot identify image file (corrupted or unsupported format): {img_path}")
                continue
            except Exception as e:
                self.log_message.emit(f"Error opening image {img_path}: {str(e)}")
                continue

            img_rgb = np.array(img)

            try:
                # Detect faces using MTCNN
                # Use detect method for boxes and probabilities
                boxes, probs = self.mtcnn.detect(img)

                if boxes is not None and len(boxes) > 0:
                    self.log_message.emit(f"Detected {len(boxes)} face(s) in {os.path.basename(img_path)}")
                    for i, box in enumerate(boxes):
                        if not self._running: break # Check running flag frequently

                        try:
                            # Get face coordinates
                            x1, y1, x2, y2 = [int(coord) for coord in box]

                            # Add margin
                            h, w = y2 - y1, x2 - x1
                            margin_h, margin_w = int(h * FACE_MARGIN_PERCENT), int(w * FACE_MARGIN_PERCENT)

                            # Ensure coordinates are within image bounds after margin
                            y1_margin = max(0, y1 - margin_h)
                            y2_margin = min(img_rgb.shape[0], y2 + margin_h)
                            x1_margin = max(0, x1 - margin_w)
                            x2_margin = min(img_rgb.shape[1], x2 + margin_w)

                            # Extract face with margin
                            face_crop_np = img_rgb[y1_margin:y2_margin, x1_margin:x2_margin]

                            # Skip if face crop is too small or invalid
                            if face_crop_np.shape[0] < MIN_FACE_SIZE or face_crop_np.shape[1] < MIN_FACE_SIZE:
                                self.log_message.emit(f"Skipping tiny face ({face_crop_np.shape[0]}x{face_crop_np.shape[1]}) in {os.path.basename(img_path)}")
                                continue

                            # Convert face crop back to PIL Image for potential resizing/processing
                            face_pil = Image.fromarray(face_crop_np)

                            # Resize to the size expected by the embedding model
                            face_resized_pil = face_pil.resize((MODEL_IMAGE_SIZE, MODEL_IMAGE_SIZE))

                            # Convert resized face to tensor
                            face_tensor = self._pil_to_tensor(face_resized_pil)

                            # Get embedding
                            with torch.no_grad():
                                embedding = self.facenet(face_tensor.to(self.device)).squeeze().cpu().numpy()

                            # Ensure embedding is a flat 1D array
                            embedding = embedding.flatten()

                            # Emit signal with the original *cropped* face (numpy array) and embedding
                            self.face_detected.emit(np.array(face_resized_pil), embedding, img_path) # Emit resized face for dialog

                        except Exception as e:
                            self.log_message.emit(f"Error processing face {i+1} in {os.path.basename(img_path)}: {str(e)}")
                            # Optionally: print traceback for debugging
                            # import traceback
                            # traceback.print_exc()
                else:
                     self.log_message.emit(f"No faces detected in {os.path.basename(img_path)}")

            except Exception as e:
                self.log_message.emit(f"Error during face detection in {img_path}: {str(e)}")
                # import traceback
                # traceback.print_exc()

        completion_msg = "Processing finished." if self._running else "Processing stopped."
        self.processing_finished.emit(completion_msg)
        self._running = False # Ensure state is consistent

    def _pil_to_tensor(self, pil_image: Image.Image) -> torch.Tensor:
        """Converts a PIL Image (RGB) to a PyTorch Tensor for Facenet."""
        np_image = np.array(pil_image, dtype=np.float32) # HWC
        tensor = torch.from_numpy(np_image)
        tensor = tensor.permute(2, 0, 1) # CHW
        tensor = (tensor / 255.0 - 0.5) * 2.0 # Normalize to [-1, 1]
        return tensor.unsqueeze(0) # Add batch dimension NCHW

    def stop(self):
        """Requests the processing thread to stop."""
        self.log_message.emit("Stop requested.")
        self._running = False
        self._paused = False # Ensure it doesn't stay paused if stopped

    def pause(self):
        """Toggles the paused state of the processing thread."""
        self._paused = not self._paused
        state = "paused" if self._paused else "resumed"
        self.log_message.emit(f"Processing {state}.")
        return self._paused

    def is_running(self):
        return self._running and self.isRunning()

# --- Face Details Dialog ---
class FaceDetailsDialog(QDialog):
    """Dialog to enter or edit details for a detected face."""
    def __init__(self, face_image_np: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Face Details")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Display face image
        self.face_label = QLabel()
        q_img = numpy_to_qimage(face_image_np)
        if q_img:
            pixmap = QPixmap.fromImage(q_img)
            # Scale pixmap slightly smaller for display if needed
            scaled_pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.face_label.setPixmap(scaled_pixmap)
        else:
            self.face_label.setText("Image Error") # Placeholder if conversion fails
        self.face_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.face_label)

        # Form for details
        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        form_layout.addRow("Name:", self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Employee", "Visitor", "Contractor", "Watchlist", "Other"])
        form_layout.addRow("Type:", self.type_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active", "Inactive", "Pending", "Blocked"])
        form_layout.addRow("Status:", self.status_combo)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        form_layout.addRow("Description:", self.description_input)

        layout.addLayout(form_layout)

        # Buttons
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

    def get_details(self) -> Dict[str, str]:
        """Returns the entered details as a dictionary."""
        return {
            "name": self.name_input.text().strip(),
            "type": self.type_combo.currentText(),
            "status": self.status_combo.currentText(),
            "description": self.description_input.toPlainText().strip()
        }

    def set_details(self, details: Dict[str, str]):
        """Populates the dialog fields with existing details (for editing)."""
        self.name_input.setText(details.get("name", ""))
        self.type_combo.setCurrentText(details.get("type", "Other"))
        self.status_combo.setCurrentText(details.get("status", "Pending"))
        self.description_input.setPlainText(details.get("description", ""))
        # Prevent editing name if it's an existing record? Optional.
        # self.name_input.setReadOnly(True)


# --- Main Application Window ---
class FaceRecognitionApp(QMainWindow):
    """Main application window for the Face Recognition System."""

    # Signal to safely update log from other threads - define as class attribute
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face Recognition System")
        self.setMinimumSize(1200, 750) # Increased size slightly

        # --- Configuration ---
        self.db_path: Optional[str] = None
        self.face_threshold: float = DEFAULT_FACE_THRESHOLD

        # --- State Variables ---
        self.known_faces: Dict[str, np.ndarray] = {}  # name: embedding
        self.image_paths: List[str] = []
        self.current_displayed_image_path: Optional[str] = None
        self.current_displayed_face_image: Optional[np.ndarray] = None # The cropped face currently shown
        self.current_displayed_embedding: Optional[np.ndarray] = None # Embedding of the face shown

        # --- Model Initialization ---
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.mtcnn: Optional[MTCNN] = None
        self.facenet: Optional[InceptionResnetV1] = None
        self._init_models() # Initialize models early

        # --- UI Setup ---
        self._apply_stylesheet()
        self._setup_ui()

        # --- Background Processor ---
        self.batch_processor = BatchImageProcessor(self.mtcnn, self.facenet, self.device)
        self.batch_processor.update_progress.connect(self.update_progress)
        self.batch_processor.face_detected.connect(self.handle_detected_face)
        self.batch_processor.processing_finished.connect(self.processing_finished)
        self.batch_processor.log_message.connect(self.log_message) # Connect thread log signal

        # --- Connect log signal ---
        self.log_signal.connect(self._append_log_message)

        # --- Initial Status ---
        self.log_message("Application started.")
        if not self.mtcnn or not self.facenet:
             self.log_message("Models failed to initialize. Functionality limited.")
             QMessageBox.critical(self, "Model Error", "Failed to initialize MTCNN or Facenet models. Check logs and dependencies.")
        else:
            self.log_message(f"Using {self.device} for processing.")
        self.log_message("Please select or create a database.")
        self._update_button_states()

    def _init_models(self):
        """Initializes MTCNN and Facenet models."""
        try:
            self.log_signal.emit("Initializing face detection model (MTCNN)...")
            # Keep all detected faces, use selected device
            self.mtcnn = MTCNN(
                image_size=MODEL_IMAGE_SIZE, margin=0, min_face_size=MIN_FACE_SIZE,
                thresholds=[0.6, 0.7, 0.7], factor=0.709, post_process=True, # Use default post_process
                device=self.device,
                keep_all=True
            )
            self.log_signal.emit("MTCNN initialized.")

            self.log_signal.emit("Initializing face recognition model (InceptionResnetV1)...")
            self.facenet = InceptionResnetV1(pretrained='vggface2', device=self.device).eval()
            self.log_signal.emit("InceptionResnetV1 initialized.")

        except Exception as e:
            self.log_signal.emit(f"FATAL: Error initializing models: {str(e)}")
            # Further handling in __init__ based on whether models are None

    def _apply_stylesheet(self):
        """Applies the Catppuccin-like stylesheet."""
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QWidget { color: #cdd6f4; font-size: 11pt; } /* Default font size */
            QLabel { color: #cdd6f4; }
            QPushButton {
                background-color: #89b4fa; /* Blue */
                color: #1e1e2e; /* Base */
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #74c7ec; } /* Sky */
            QPushButton:pressed { background-color: #94e2d5; } /* Teal */
            QPushButton:disabled { background-color: #6c7086; color: #a6adc8; } /* Surface2 / Text */

            /* Specific button colors */
            QPushButton#deleteButton { background-color: #f38ba8; } /* Red */
            QPushButton#deleteButton:hover { background-color: #eba0ac; } /* Pink */
            QPushButton#deleteButton:pressed { background-color: #fab387; } /* Peach */

            QPushButton#pauseButton { background-color: #fab387; } /* Peach */
            QPushButton#pauseButton:hover { background-color: #f9e2af; } /* Yellow */

            QListWidget, QTextEdit, QLineEdit, QComboBox, QDoubleSpinBox {
                background-color: #181825; /* Mantle */
                color: #cdd6f4; /* Text */
                border: 1px solid #313244; /* Surface0 */
                border-radius: 5px;
                padding: 4px;
            }
            QTextEdit { font-family: Consolas, monospace; font-size: 10pt; } /* Monospace for logs */
            QListWidget::item:selected { background-color: #89b4fa; color: #1e1e2e; } /* Blue / Base */
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(:/qt-project.org/styles/commonstyle/images/downarraow-disabled.png); } /* Placeholder, maybe style later */

            QGroupBox {
                color: #cdd6f4; /* Text */
                font-weight: bold;
                border: 1px solid #313244; /* Surface0 */
                border-radius: 5px;
                margin-top: 1em;
                padding-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #89b4fa; /* Blue for titles */
            }
            QProgressBar {
                border: 1px solid #313244; /* Surface0 */
                border-radius: 5px;
                background-color: #181825; /* Mantle */
                text-align: center;
                color: #cdd6f4; /* Text */
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #a6e3a1; /* Green */
                border-radius: 4px; /* Slightly smaller radius for chunk */
                margin: 1px;
            }
            QStatusBar { background-color: #181825; color: #cdd6f4; font-weight: bold; }
            QMessageBox { background-color: #1e1e2e; } /* Ensure message boxes match */
            QDialog { background-color: #1e1e2e; } /* Ensure dialogs match */
        """)

    def _setup_ui(self):
        """Creates and arranges the UI elements."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- Left Panel ---
        left_panel_layout = self._create_left_panel()

        # --- Right Panel ---
        right_panel_layout = self._create_right_panel()

        # --- Add panels to main layout ---
        main_layout.addLayout(left_panel_layout, 65) # 65% width
        main_layout.addLayout(right_panel_layout, 35) # 35% width

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _create_left_panel(self) -> QVBoxLayout:
        """Creates the left panel containing image display and controls."""
        layout = QVBoxLayout()

        # Image Display Group
        image_group = QGroupBox("Image Display & Processing")
        image_layout = QVBoxLayout()

        self.image_label = QLabel("Select images using 'Select Images' button")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(480, 360) # Adjusted minimum size
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored) # Allow scaling
        self.image_label.setStyleSheet("background-color: #181825; border: 2px solid #313244; border-radius: 5px; color: #a6adc8;")
        image_layout.addWidget(self.image_label, 1) # Give it stretch factor

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        image_layout.addWidget(self.progress_bar)

        # Image Controls
        image_controls_layout = QHBoxLayout()
        self.select_images_btn = QPushButton("Select Images")
        self.select_images_btn.clicked.connect(self.select_images)
        self.process_images_btn = QPushButton("Process Images")
        self.process_images_btn.clicked.connect(self.process_images)
        self.pause_processing_btn = QPushButton("Pause")
        self.pause_processing_btn.setObjectName("pauseButton") # For specific styling
        self.pause_processing_btn.setCheckable(True) # Make it behave like a toggle
        self.pause_processing_btn.clicked.connect(self.toggle_processing_pause)

        image_controls_layout.addWidget(self.select_images_btn)
        image_controls_layout.addWidget(self.process_images_btn)
        image_controls_layout.addWidget(self.pause_processing_btn)
        image_layout.addLayout(image_controls_layout)

        image_group.setLayout(image_layout)

        # Status/Identification Group
        status_group = QGroupBox("Identification Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Status: Idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #313244;")
        self.status_label.setWordWrap(True)

        self.identify_btn = QPushButton("Identify Displayed Face")
        self.identify_btn.clicked.connect(self.identify_displayed_face)

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.identify_btn)
        status_group.setLayout(status_layout)

        layout.addWidget(image_group, 7) # 70% height
        layout.addWidget(status_group, 3) # 30% height
        return layout

    def _create_right_panel(self) -> QVBoxLayout:
        """Creates the right panel containing DB, Face Mgmt, Threshold, and Logs."""
        layout = QVBoxLayout()

        # Database Group
        db_group = QGroupBox("Database Management")
        db_layout = QVBoxLayout()
        self.db_path_label = QLabel("No database selected.")
        self.db_path_label.setStyleSheet("font-style: italic; color: #a6adc8;")
        self.db_path_label.setWordWrap(True)

        db_buttons_layout = QHBoxLayout()
        select_db_btn = QPushButton("Select DB")
        select_db_btn.clicked.connect(self.select_database)
        create_db_btn = QPushButton("Create DB")
        create_db_btn.clicked.connect(self.create_database)
        db_buttons_layout.addWidget(select_db_btn)
        db_buttons_layout.addWidget(create_db_btn)

        db_layout.addWidget(self.db_path_label)
        db_layout.addLayout(db_buttons_layout)
        db_group.setLayout(db_layout)

        # Face Management Group
        face_group = QGroupBox("Known Faces")
        face_layout = QVBoxLayout()

        # Threshold setting
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Recognition Threshold:"))
        self.threshold_spinbox = QDoubleSpinBox()
        self.threshold_spinbox.setRange(0.1, 1.0)
        self.threshold_spinbox.setSingleStep(0.05)
        self.threshold_spinbox.setValue(DEFAULT_FACE_THRESHOLD)
        self.threshold_spinbox.valueChanged.connect(self.update_threshold)
        threshold_layout.addWidget(self.threshold_spinbox)
        threshold_layout.addStretch()
        face_layout.addLayout(threshold_layout)


        self.face_list = QListWidget()
        self.face_list.itemClicked.connect(self.face_selected_in_list)
        self.face_list.itemDoubleClicked.connect(self.edit_face_details) # Double click to edit
        face_layout.addWidget(self.face_list)

        face_buttons_layout = QHBoxLayout()
        self.load_faces_btn = QPushButton("Reload Faces")
        self.load_faces_btn.clicked.connect(self.load_known_faces)
        self.edit_face_btn = QPushButton("Edit Selected")
        self.edit_face_btn.clicked.connect(self.edit_face_details)
        self.delete_face_btn = QPushButton("Delete Selected")
        self.delete_face_btn.setObjectName("deleteButton") # For specific styling
        self.delete_face_btn.clicked.connect(self.delete_face)

        face_buttons_layout.addWidget(self.load_faces_btn)
        face_buttons_layout.addWidget(self.edit_face_btn)
        face_buttons_layout.addWidget(self.delete_face_btn)
        face_layout.addLayout(face_buttons_layout)
        face_group.setLayout(face_layout)

        # Log Group
        log_group = QGroupBox("Log Messages")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)

        layout.addWidget(db_group, 1)
        layout.addWidget(face_group, 4)
        layout.addWidget(log_group, 3)
        return layout

    # --- Logging ---
    def _append_log_message(self, message: str):
        """Appends a message to the log text area in a thread-safe way."""
        timestamp = QTime.currentTime().toString("hh:mm:ss.zzz")
        self.log_text.append(f"[{timestamp}] {message}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum()) # Auto-scroll

    def log_message(self, message: str):
        """Logs a message (can be called from main thread or use signal)."""
        # If called from a different thread, emit the signal
        if QThread.currentThread() != self.thread():
            self.log_signal.emit(message)
        else:
            self._append_log_message(message) # Call directly if in main thread


    # --- Database Operations ---
    def _get_db_connection(self) -> Optional[sqlite3.Connection]:
        """Gets a database connection, returning None if db_path is not set."""
        if not self.db_path:
            self.log_message("Error: Database path not set.")
            QMessageBox.warning(self, "Database Error", "No database file selected or created.")
            return None
        try:
            # Using check_same_thread=False is generally okay for simple desktop apps
            # where access is sequential, but be mindful if concurrency increases.
            # Consider a dedicated DB thread or connection pooling for complex scenarios.
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row # Access columns by name
            return conn
        except sqlite3.Error as e:
            self.log_message(f"Database connection error: {str(e)}")
            QMessageBox.critical(self, "Database Error", f"Failed to connect to database:\n{str(e)}")
            return None

    def select_database(self):
        """Opens a dialog to select an existing SQLite database file."""
        db_path, _ = QFileDialog.getOpenFileName(
            self, "Select Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            self.db_path = db_path
            self.db_path_label.setText(f"DB: {os.path.basename(db_path)}")
            self.status_bar.showMessage(f"Database selected: {os.path.basename(db_path)}")
            self.log_message(f"Selected database: {db_path}")
            self.ensure_database_structure() # Check/create table if needed
            self.load_known_faces() # Load faces from the selected DB
            self._update_button_states()

    def create_database(self):
        """Opens a dialog to create a new SQLite database file."""
        db_path, _ = QFileDialog.getSaveFileName(
            self, "Create New Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            # Ensure the file has a .db extension if none provided
            if not db_path.lower().endswith(('.db', '.sqlite')):
                db_path += '.db'
            self.db_path = db_path
            self.db_path_label.setText(f"DB: {os.path.basename(db_path)}")
            self.status_bar.showMessage(f"Database created: {os.path.basename(db_path)}")
            self.log_message(f"Attempting to create database: {db_path}")
            if self.ensure_database_structure(): # Create table in the new DB
                self.log_message("New database and table created successfully.")
                self.load_known_faces() # Should load an empty list
            else:
                 self.log_message("Failed to create database structure.")
                 self.db_path = None # Reset if creation failed
                 self.db_path_label.setText("No database selected.")
            self._update_button_states()

    def ensure_database_structure(self) -> bool:
        """Creates the face_embeddings table if it doesn't exist. Returns success status."""
        conn = self._get_db_connection()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {DB_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                type TEXT,
                status TEXT,
                description TEXT,
                embedding BLOB NOT NULL,
                image_path TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            # Consider adding an index on 'name' for faster lookups if the DB grows
            cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_face_name ON {DB_TABLE_NAME}(name)')
            conn.commit()
            return True
        except sqlite3.Error as e:
            self.log_message(f"Database error (ensure_structure): {str(e)}")
            QMessageBox.critical(self, "Database Error", f"Failed to create/verify database table:\n{str(e)}")
            return False
        finally:
            if conn:
                conn.close()

    def load_known_faces(self):
        """Loads face embeddings and names from the database into memory."""
        conn = self._get_db_connection()
        if not conn:
            self.log_message("Cannot load faces, no database connection.")
            return

        self.log_message("Loading known faces from database...")
        loaded_count = 0
        try:
            cursor = conn.cursor()
            # Select all necessary fields
            cursor.execute(f"SELECT name, type, status, description, embedding FROM {DB_TABLE_NAME}")
            rows = cursor.fetchall()

            # Clear existing in-memory data and UI list
            self.known_faces.clear()
            self.face_list.clear()

            for row in rows:
                try:
                    name = row['name']
                    embedding_bytes = row['embedding']
                    embedding = np.frombuffer(embedding_bytes, dtype=np.float32)

                    # Basic validation
                    if not name or embedding.size != 512: # InceptionResnetV1 outputs 512 features
                        self.log_message(f"Warning: Skipping invalid record for '{name}' (embedding size: {embedding.size})")
                        continue

                    # Store embedding in memory
                    self.known_faces[name] = embedding

                    # Add to UI list with tooltip
                    item = QListWidgetItem(name)
                    tooltip = (f"Type: {row['type'] or 'N/A'}\n"
                               f"Status: {row['status'] or 'N/A'}\n"
                               f"Desc: {row['description'] or 'N/A'}")
                    item.setToolTip(tooltip)
                    self.face_list.addItem(item)
                    loaded_count += 1

                except Exception as e: # Catch errors during row processing
                     self.log_message(f"Error processing row for '{row['name']}': {str(e)}")


            self.log_message(f"Successfully loaded {loaded_count} known faces.")
            self.status_bar.showMessage(f"Loaded {loaded_count} faces from DB.")

        except sqlite3.Error as e:
            self.log_message(f"Database error loading faces: {str(e)}")
            QMessageBox.warning(self, "Database Load Error", f"Could not load faces from database:\n{str(e)}")
        finally:
            if conn:
                conn.close()
        self._update_button_states()


    # --- Image Processing ---
    def select_images(self):
        """Opens a dialog to select multiple image files."""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.bmp *.webp)") # Added webp

        if file_dialog.exec_():
            self.image_paths = file_dialog.selectedFiles()
            count = len(self.image_paths)
            self.log_message(f"Selected {count} image(s).")
            self.status_bar.showMessage(f"Selected {count} image(s).")
            self.status_label.setText(f"{count} image(s) ready for processing.")
            self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #313244;") # Reset style

            # Reset display and progress
            self.progress_bar.setValue(0)
            self.current_displayed_image_path = None
            self.current_displayed_face_image = None
            self.current_displayed_embedding = None

            # Show preview of the first image
            if self.image_paths:
                self._display_image(self.image_paths[0])
            else:
                self.image_label.setText("No images selected.")

        self._update_button_states()

    def process_images(self):
        """Starts the batch image processing thread."""
        if self.batch_processor and self.batch_processor.is_running():
             self.log_message("Processing is already in progress.")
             return

        if not self.image_paths:
            self.log_message("No images selected to process.")
            QMessageBox.information(self, "No Images", "Please select images first using the 'Select Images' button.")
            return

        if not self.db_path:
            self.log_message("Database not selected. Cannot save new faces.")
            QMessageBox.warning(self, "No Database", "Please select or create a database before processing images if you intend to save new faces.")
            # Allow processing even without DB, but new faces won't be saved automatically

        # Reset progress bar range
        self.progress_bar.setMaximum(len(self.image_paths))
        self.progress_bar.setValue(0)

        # Set images in processor and start
        self.batch_processor.set_images(self.image_paths)
        self.batch_processor.start() # Starts the run() method in a new thread

        self.status_label.setText("Processing started...")
        self.log_message(f"Starting processing for {len(self.image_paths)} images.")
        self._update_button_states()

    def update_progress(self, current: int, total: int, current_image_path: str):
        """Updates the progress bar and displays the currently processed image."""
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"Processing: {current}/{total} (%p%)")
        self.status_label.setText(f"Processing {os.path.basename(current_image_path)} ({current}/{total})")

        # Display the image being processed
        self._display_image(current_image_path)
        self.current_displayed_image_path = current_image_path # Keep track

    def _display_image(self, image_path: str):
        """Loads and displays an image in the image_label."""
        try:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                self.log_message(f"Warning: Could not load image preview for {image_path}")
                self.image_label.setText(f"Cannot display:\n{os.path.basename(image_path)}")
                return

            # Scale pixmap to fit the label while keeping aspect ratio
            scaled_pixmap = pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)

        except Exception as e:
            self.log_message(f"Error displaying image {image_path}: {str(e)}")
            self.image_label.setText(f"Error displaying:\n{os.path.basename(image_path)}")

    def processing_finished(self, message: str):
        """Handles the completion of the batch processing thread."""
        self.log_message(f"Batch processing finished: {message}")
        self.status_label.setText(message)
        self.status_bar.showMessage(message, 5000) # Show for 5 seconds
        self.progress_bar.setFormat("Processing Complete")
        # Reset pause button state if it was active
        self.pause_processing_btn.setChecked(False)
        self.pause_processing_btn.setText("Pause")
        self._update_button_states()

    def toggle_processing_pause(self):
        """Pauses or resumes the background processing thread."""
        if not self.batch_processor or not self.batch_processor.is_running():
            self.log_message("Cannot pause/resume: No active processing.")
            self.pause_processing_btn.setChecked(False) # Reset toggle state
            return

        paused = self.batch_processor.pause()
        if paused:
            self.pause_processing_btn.setText("Resume")
            self.status_bar.showMessage("Processing paused.")
            self.status_label.setText("Processing Paused...")
        else:
            self.pause_processing_btn.setText("Pause")
            self.status_bar.showMessage("Processing resumed.")
            self.status_label.setText("Processing resumed...")
        self._update_button_states()


    # --- Face Handling & Identification ---
    def handle_detected_face(self, face_image_np: np.ndarray, embedding: np.ndarray, image_path: str):
        """
        Handles a face detected by the BatchImageProcessor.
        Checks if known, otherwise prompts user to add.
        Updates the display to show the *cropped face*.
        """
        # Display the *cropped* face that was detected and embedded
        q_img = numpy_to_qimage(face_image_np)
        if q_img:
            pixmap = QPixmap.fromImage(q_img)
            # Scale to fit, maybe smaller than main image label
            scaled_pixmap = pixmap.scaled(self.image_label.size() * 0.8, Qt.KeepAspectRatio, Qt.SmoothTransformation) # Display smaller
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.log_message("Error creating QImage from detected face numpy array.")
            # Optionally keep the full image displayed or show an error placeholder

        # Store details of the currently displayed face for potential identification/saving
        self.current_displayed_face_image = face_image_np
        self.current_displayed_embedding = embedding
        # self.current_displayed_image_path = image_path # Path of the *source* image

        # Identify this specific face immediately
        found_match, name, score = self._find_best_match(embedding)

        if found_match:
            self.log_message(f"Recognized: {name} (Score: {score:.3f}) in {os.path.basename(image_path)}")
            self.status_label.setText(f"Recognized: {name}\n(Score: {score:.3f})")
            self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #a6e3a1; color: #1e1e2e;") # Green
            self._highlight_face_in_list(name)
        else:
            # Only prompt to add if a DB is selected
            if self.db_path:
                self.log_message(f"Unknown face detected in {os.path.basename(image_path)}. Prompting user...")
                self.status_label.setText(f"Unknown Face\n(Best guess: {name} Score: {score:.3f})" if name else "Unknown Face")
                self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #f9e2af; color: #1e1e2e;") # Yellow
                self._prompt_add_new_face(face_image_np, embedding, image_path)
            else:
                self.log_message(f"Unknown face detected in {os.path.basename(image_path)}, but no DB selected to save.")
                self.status_label.setText(f"Unknown Face (No DB)\n(Best guess: {name} Score: {score:.3f})" if name else "Unknown Face (No DB)")
                self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #fab387; color: #1e1e2e;") # Peach

        self._update_button_states() # Enable identify button etc.


    def _find_best_match(self, current_embedding: np.ndarray) -> Tuple[bool, Optional[str], float]:
        """Compares the current embedding against known faces."""
        if current_embedding is None or not self.known_faces:
            return False, None, 0.0

        best_match_name: Optional[str] = None
        best_score: float = -1.0 # Initialize lower than any possible cosine similarity

        for name, known_embedding in self.known_faces.items():
            try:
                # Ensure embeddings are 1D arrays for dot product
                similarity = self.cosine_similarity(current_embedding.flatten(), known_embedding.flatten())

                if similarity > best_score:
                    best_score = similarity
                    best_match_name = name
            except Exception as e:
                self.log_message(f"Error comparing embedding for {name}: {str(e)}")
                continue # Skip this comparison

        # Check if the best score meets the threshold
        if best_match_name is not None and best_score >= self.face_threshold:
            return True, best_match_name, best_score
        else:
            # Return the best guess even if below threshold, for informational purposes
            return False, best_match_name, best_score

    def identify_displayed_face(self):
        """Identifies the face currently displayed (uses stored embedding)."""
        if self.current_displayed_embedding is None:
            self.log_message("No face embedding available for identification.")
            QMessageBox.information(self, "Identify", "No face is currently displayed or its embedding is not available.")
            return

        if not self.known_faces:
            self.log_message("No known faces loaded to compare against.")
            QMessageBox.information(self, "Identify", "No known faces are loaded in the database.")
            self.status_label.setText("Face Detected\n(No Known Faces)")
            self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #89b4fa; color: #1e1e2e;") # Blue
            return

        self.log_message("Attempting identification of displayed face...")
        found_match, name, score = self._find_best_match(self.current_displayed_embedding)

        if found_match:
            self.log_message(f"Identification Result: {name} (Score: {score:.3f})")
            self.status_label.setText(f"Identified: {name}\n(Score: {score:.3f})")
            self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #a6e3a1; color: #1e1e2e;") # Green
            self._highlight_face_in_list(name)
        else:
            best_guess_text = f"\n(Best guess: {name} Score: {score:.3f})" if name else ""
            self.log_message(f"Identification Result: Unknown. Best guess: {name} (Score: {score:.3f})")
            self.status_label.setText(f"Result: Unknown{best_guess_text}")
            self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #f9e2af; color: #1e1e2e;") # Yellow
            self.face_list.clearSelection() # Clear selection if unknown

    def _highlight_face_in_list(self, name: str):
        """Selects the item corresponding to the name in the face_list."""
        items = self.face_list.findItems(name, Qt.MatchExactly)
        if items:
            self.face_list.setCurrentItem(items[0])
            self.face_list.scrollToItem(items[0], QListWidget.ScrollHint.PositionAtCenter)
        else:
             self.face_list.clearSelection()


    def _prompt_add_new_face(self, face_image_np: np.ndarray, embedding: np.ndarray, image_path: str):
        """Shows a dialog prompting the user to add details for a new face."""
        dialog = FaceDetailsDialog(face_image_np, self)
        if dialog.exec_() == QDialog.Accepted:
            details = dialog.get_details()
            name = details.get("name")

            if not name:
                self.log_message("Face add skipped - no name provided.")
                return

            self._save_face_to_db(name, embedding, details, image_path)
        else:
            self.log_message("User cancelled adding new face.")

    def _save_face_to_db(self, name: str, embedding: np.ndarray, details: Dict[str, str], image_path: str, update_existing=False):
        """Saves or updates face details and embedding in the database."""
        conn = self._get_db_connection()
        if not conn:
            self.log_message("Cannot save face, no database connection.")
            return

        try:
            cursor = conn.cursor()
            embedding_bytes = embedding.tobytes() # Convert numpy array to bytes

            if update_existing:
                # Update existing record
                cursor.execute(
                    f"UPDATE {DB_TABLE_NAME} SET type = ?, status = ?, description = ?, embedding = ?, image_path = ?, timestamp = CURRENT_TIMESTAMP WHERE name = ?",
                    (details["type"], details["status"], details["description"], embedding_bytes, image_path, name)
                )
                conn.commit()
                self.log_message(f"Successfully updated face details for '{name}'.")
            else:
                # Insert new record - check for existing name first
                cursor.execute(f"SELECT id FROM {DB_TABLE_NAME} WHERE name = ?", (name,))
                existing = cursor.fetchone()

                if existing:
                    # Name already exists, ask user whether to update
                    reply = QMessageBox.question(
                        self,
                        "Name Exists",
                        f"A face named '{name}' already exists in the database.\nDo you want to overwrite it with the new data?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No # Default to No
                    )
                    if reply == QMessageBox.Yes:
                        # Call recursively to perform the update
                        self._save_face_to_db(name, embedding, details, image_path, update_existing=True)
                    else:
                        self.log_message(f"Skipped adding face '{name}' because it already exists and user chose not to update.")
                else:
                    # Insert the new face record
                    cursor.execute(
                        f"INSERT INTO {DB_TABLE_NAME} (name, type, status, description, embedding, image_path) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, details["type"], details["status"], details["description"], embedding_bytes, image_path)
                    )
                    conn.commit()
                    self.log_message(f"Successfully added new face '{name}' to the database.")

            # Reload faces into memory and UI list after any change
            self.load_known_faces()

        except sqlite3.Error as e:
            self.log_message(f"Database error saving face '{name}': {str(e)}")
            QMessageBox.critical(self, "Database Save Error", f"Failed to save face '{name}' to database:\n{str(e)}")
        except Exception as e: # Catch other potential errors like embedding conversion
             self.log_message(f"Unexpected error saving face '{name}': {str(e)}")
        finally:
            if conn:
                conn.close()


    # --- Face List Management ---
    def face_selected_in_list(self, item: QListWidgetItem):
        """Handles selection changes in the known faces list."""
        name = item.text()
        self.status_bar.showMessage(f"Selected: {name}. Double-click or use 'Edit' to modify.")
        # Optionally display details or associated image if stored/needed
        self._update_button_states()

    def edit_face_details(self):
        """Opens the detail dialog to edit the selected face."""
        selected_item = self.face_list.currentItem()
        if not selected_item:
            self.log_message("Edit requested, but no face selected.")
            QMessageBox.information(self, "Edit Face", "Please select a face from the list to edit.")
            return

        name = selected_item.text()
        self.log_message(f"Editing details for face: {name}")

        # Fetch current details from DB
        conn = self._get_db_connection()
        if not conn: return
        details: Dict[str, Any] = {}
        face_image_np : Optional[np.ndarray] = None # We don't store face image, maybe load from image_path?

        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT name, type, status, description, embedding FROM {DB_TABLE_NAME} WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                details = dict(row) # Convert sqlite3.Row to dict
                # We need an image for the dialog. Since we don't store it,
                # we can't show the original cropped face easily.
                # For now, we pass a placeholder or None.
                # A better approach might be to reconstruct a dummy image or load from image_path if available.
                # Let's create a dummy placeholder image.
                face_image_np = np.zeros((MODEL_IMAGE_SIZE, MODEL_IMAGE_SIZE, 3), dtype=np.uint8) # Black square
                face_image_np[:,:,0] = 60 # Dark blueish placeholder
                face_image_np[:,:,2] = 80

                embedding = np.frombuffer(row['embedding'], dtype=np.float32) # Get embedding too
            else:
                self.log_message(f"Error: Could not find details for '{name}' in DB for editing.")
                QMessageBox.warning(self, "Edit Error", f"Could not retrieve details for '{name}'.")
                return
        except sqlite3.Error as e:
             self.log_message(f"DB error fetching details for '{name}': {str(e)}")
             return
        finally:
             if conn: conn.close()

        if face_image_np is None: # Should not happen with placeholder logic
            self.log_message("Error: Could not prepare face image for edit dialog.")
            return

        # Show dialog pre-filled with details
        dialog = FaceDetailsDialog(face_image_np, self)
        dialog.setWindowTitle(f"Edit Details: {name}")
        dialog.set_details(details)
        dialog.name_input.setReadOnly(True) # Prevent changing the unique name during edit

        if dialog.exec_() == QDialog.Accepted:
            new_details = dialog.get_details()
            # Use the stored embedding, only update other details
            self._save_face_to_db(name, embedding, new_details, details.get('image_path', ''), update_existing=True)


    def delete_face(self):
        """Deletes the selected face from the database and memory."""
        selected_item = self.face_list.currentItem()
        if not selected_item:
            self.log_message("Delete requested, but no face selected.")
            QMessageBox.information(self, "Delete Face", "Please select a face from the list to delete.")
            return

        name = selected_item.text()

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to permanently delete the face record for '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.log_message(f"Attempting to delete face: {name}")
            conn = self._get_db_connection()
            if not conn: return

            try:
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {DB_TABLE_NAME} WHERE name = ?", (name,))
                conn.commit()

                if cursor.rowcount > 0:
                    self.log_message(f"Successfully deleted face '{name}' from database.")
                    # Remove from memory and UI
                    if name in self.known_faces:
                        del self.known_faces[name]
                    self.face_list.takeItem(self.face_list.row(selected_item))
                    self.status_bar.showMessage(f"Deleted face: {name}", 5000)
                    # Clear display if the deleted face was shown
                    if self.status_label.text().startswith(f"Identified: {name}") or \
                       self.status_label.text().startswith(f"Recognized: {name}"):
                        self.status_label.setText("Status: Idle")
                        self.status_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px; border-radius: 5px; background-color: #313244;")
                        self.current_displayed_embedding = None # Clear embedding if it was the deleted one
                else:
                    self.log_message(f"Warning: Face '{name}' not found in database for deletion.")

            except sqlite3.Error as e:
                self.log_message(f"Database error deleting face '{name}': {str(e)}")
                QMessageBox.critical(self, "Delete Error", f"Failed to delete face '{name}':\n{str(e)}")
            finally:
                if conn: conn.close()
        else:
            self.log_message(f"Deletion of face '{name}' cancelled by user.")

        self._update_button_states()


    # --- Misc ---
    def update_threshold(self, value: float):
        """Updates the face recognition threshold."""
        self.face_threshold = value
        self.log_message(f"Recognition threshold set to: {self.face_threshold:.2f}")
        # Re-identify the displayed face if any with the new threshold
        if self.current_displayed_embedding is not None:
            self.identify_displayed_face()


    def cosine_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Calculates the cosine similarity between two embeddings."""
        if embedding1 is None or embedding2 is None: return 0.0
        # Ensure input embeddings are numpy arrays
        embedding1 = np.asarray(embedding1)
        embedding2 = np.asarray(embedding2)
        dot = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        if norm1 == 0 or norm2 == 0: # Avoid division by zero
            return 0.0
        return dot / (norm1 * norm2)

    def _update_button_states(self):
        """Enables or disables buttons based on the application state."""
        # Processing buttons
        is_processing = self.batch_processor and self.batch_processor.is_running()
        is_paused = is_processing and self.pause_processing_btn.isChecked()

        self.select_images_btn.setEnabled(not is_processing or is_paused)
        self.process_images_btn.setEnabled(bool(self.image_paths) and (not is_processing or is_paused))
        self.pause_processing_btn.setEnabled(is_processing) # Enable only when running

        # Database buttons are always enabled (select/create)

        # Face list buttons
        has_db = bool(self.db_path)
        item_selected = bool(self.face_list.currentItem())
        self.load_faces_btn.setEnabled(has_db)
        self.edit_face_btn.setEnabled(has_db and item_selected)
        self.delete_face_btn.setEnabled(has_db and item_selected)

        # Identification button
        self.identify_btn.setEnabled(self.current_displayed_embedding is not None and bool(self.known_faces))

    def closeEvent(self, event):
        """Handles the window closing event."""
        self.log_message("Close event triggered.")
        # Stop the processing thread if it's running
        if self.batch_processor and self.batch_processor.is_running():
            self.log_message("Stopping batch processor thread...")
            self.batch_processor.stop()
            if not self.batch_processor.wait(3000): # Wait up to 3 seconds
                 self.log_message("Warning: Batch processor did not stop gracefully.")

        self.log_message("Exiting application.")
        event.accept()


# --- Main Execution ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Optional: More sophisticated palette setup if needed
    # For now, the stylesheet handles the main look

    # Ensure models are available before showing window (or handle gracefully)
    window = FaceRecognitionApp()
    if not window.mtcnn or not window.facenet:
        # Models failed to load, maybe exit or show limited functionality
        QMessageBox.critical(window, "Initialization Error",
                             "Critical models (MTCNN/Facenet) failed to load.\n"
                             "Please check console logs and dependencies.\n"
                             "Application will exit.")
        sys.exit(1) # Exit if models aren't ready

    window.show()
    sys.exit(app.exec_())