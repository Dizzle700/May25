import sys
import os
import sqlite3
import numpy as np
import torch
import cv2
from PIL import Image
from facenet_pytorch import MTCNN, InceptionResnetV1
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QLabel, QListWidget, QWidget, QStatusBar, 
                             QGroupBox, QTextEdit, QFileDialog, QInputDialog, QLineEdit,
                             QDialog, QFormLayout, QComboBox, QProgressBar, QMessageBox,
                             QListWidgetItem)
from PyQt5.QtGui import QPixmap, QImage, QFont, QColor, QPalette
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime

class BatchImageProcessor(QThread):
    update_progress = pyqtSignal(int, int)  # current, total
    face_detected = pyqtSignal(np.ndarray, np.ndarray, str)  # face image, embedding, image path
    processing_finished = pyqtSignal()
    
    def __init__(self, mtcnn, facenet):
        super().__init__()
        self.running = True
        self.paused = False
        self.image_paths = []
        self.mtcnn = mtcnn
        self.facenet = facenet
        
    def set_images(self, image_paths):
        self.image_paths = image_paths
        
    def run(self):
        total = len(self.image_paths)
        processed = 0
        
        for img_path in self.image_paths:
            if not self.running:
                break
                
            while self.paused:
                self.msleep(100)
                if not self.running:
                    break
            
            try:
                # Load and process image
                img = Image.open(img_path).convert('RGB')  # Ensure RGB format
                img_rgb = np.array(img)
                
                # Detect faces using MTCNN
                try:
                    # Use detect instead of direct call for more control
                    boxes, _ = self.mtcnn.detect(img)
                    
                    if boxes is not None and len(boxes) > 0:
                        for box in boxes:
                            try:
                                # Get face coordinates with some margin
                                x1, y1, x2, y2 = [int(coord) for coord in box]
                                
                                # Add some margin (10%) to the face box
                                h, w = y2 - y1, x2 - x1
                                margin_h, margin_w = int(h * 0.1), int(w * 0.1)
                                
                                # Ensure coordinates are within image bounds
                                y1_margin = max(0, y1 - margin_h)
                                y2_margin = min(img_rgb.shape[0], y2 + margin_h)
                                x1_margin = max(0, x1 - margin_w)
                                x2_margin = min(img_rgb.shape[1], x2 + margin_w)
                                
                                # Extract face with margin
                                face = img_rgb[y1_margin:y2_margin, x1_margin:x2_margin]
                                
                                # Skip if face is too small
                                if face.shape[0] < 20 or face.shape[1] < 20:
                                    continue
                                
                                # Convert to PIL Image
                                face_img = Image.fromarray(face)
                                
                                # Resize to expected input size for the model
                                face_img = face_img.resize((160, 160))
                                
                                # Convert to tensor directly
                                face_tensor = torch.from_numpy(np.array(face_img)).permute(2, 0, 1).float()
                                face_tensor = face_tensor.unsqueeze(0)  # Add batch dimension
                                
                                # Normalize (similar to what MTCNN would do)
                                face_tensor = face_tensor / 255.0  # Scale to [0, 1]
                                face_tensor = (face_tensor - 0.5) / 0.5  # Scale to [-1, 1]
                                
                                # Move to same device as model
                                if torch.cuda.is_available():
                                    face_tensor = face_tensor.cuda()
                                
                                # Get embedding
                                with torch.no_grad():
                                    embedding = self.facenet(face_tensor).squeeze().cpu().numpy()
                                
                                # Emit signal with face data
                                self.face_detected.emit(face, embedding, img_path)
                            except Exception as e:
                                print(f"Error processing individual face in {img_path}: {str(e)}")
                except Exception as e:
                    print(f"Error detecting faces in {img_path}: {str(e)}")
            except Exception as e:
                print(f"Error opening/processing image {img_path}: {str(e)}")
            
            processed += 1
            self.update_progress.emit(processed, total)
            
        self.processing_finished.emit()
    
    def stop(self):
        self.running = False
        self.wait()
    
    def pause(self):
        self.paused = not self.paused
        return self.paused

class FaceDetailsDialog(QDialog):
    def __init__(self, face_image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Face Details")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # Display face image
        self.face_label = QLabel()
        height, width, channel = face_image.shape
        bytes_per_line = 3 * width
        
        # Convert numpy array to QImage
        face_image_copy = face_image.copy()  # Create a copy to ensure contiguous memory
        q_img = QImage(face_image_copy.data, width, height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        self.face_label.setPixmap(pixmap)
        self.face_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.face_label)
        
        # Form for details
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        form_layout.addRow("Name:", self.name_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Employee", "Visitor", "Contractor", "Other"])
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
        
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
    
    def get_details(self):
        return {
            "name": self.name_input.text(),
            "type": self.type_combo.currentText(),
            "status": self.status_combo.currentText(),
            "description": self.description_input.toPlainText()
        }

class FaceRecognitionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face Recognition System")
        self.setMinimumSize(1000, 700)
        
        # Database path
        self.db_path = None
        
        # Face recognition variables
        self.face_threshold = 0.7  # Similarity threshold
        self.known_faces = {}  # Will store name:embedding pairs
        self.current_face_embedding = None
        self.current_face_name = None
        
        # Image processing variables
        self.image_paths = []
        
        # Setup UI first
        self.setup_ui()
        
        # Initialize models after UI is set up
        self.init_models()
        
        # Initialize BatchImageProcessor but don't start it automatically
        self.batch_processor = BatchImageProcessor(self.mtcnn, self.facenet)
        self.batch_processor.face_detected.connect(self.face_detected)
        self.batch_processor.processing_finished.connect(self.processing_finished)
        # The processor will be started when the user clicks the process_images button
        
        # Recognition timer
        self.recognition_timer = QTimer()
        self.recognition_timer.timeout.connect(self.process_current_frame)
        self.recognition_timer.start(500)  # Process every 500ms to avoid overload
    
    def init_models(self):
        # Initialize face detection and recognition models
        try:
            self.log_message("Initializing face detection model...")
            self.mtcnn = MTCNN(
                image_size=160, margin=0, min_face_size=20,
                thresholds=[0.6, 0.7, 0.7], factor=0.709, post_process=True,
                device='cuda' if torch.cuda.is_available() else 'cpu',
                keep_all=True  # Keep all detected faces
            )
            
            self.log_message("Initializing face recognition model...")
            self.facenet = InceptionResnetV1(pretrained='vggface2').eval()
            
            if torch.cuda.is_available():
                self.facenet = self.facenet.cuda()
                self.log_message("Using GPU acceleration")
            else:
                self.log_message("Using CPU for processing")
                
            self.log_message("Models initialized successfully")
        except Exception as e:
            self.log_message(f"Error initializing models: {str(e)}")
            QMessageBox.critical(self, "Model Initialization Error", 
                                f"Failed to initialize face recognition models: {str(e)}")
    
    def setup_ui(self):
        # Set the application style with a new color scheme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QLabel {
                color: #cdd6f4;
                font-size: 14px;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
            QPushButton:pressed {
                background-color: #89dceb;
            }
            QPushButton:disabled {
                background-color: #6c7086;
                color: #313244;
            }
            QListWidget, QTextEdit {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
            }
            QGroupBox {
                color: #cdd6f4;
                font-weight: bold;
                border: 1px solid #313244;
                border-radius: 4px;
                margin-top: 1em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #181825;
                text-align: center;
                color: #cdd6f4;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                width: 10px;
                margin: 0.5px;
            }
        """)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel - Image processing and controls
        left_panel = QVBoxLayout()
        
        # Image processing
        image_group = QGroupBox("Image Processing")
        image_layout = QVBoxLayout()
        
        self.image_label = QLabel("No image selected - Click 'Select Images' to begin")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #181825; border: 2px solid #313244; border-radius: 4px; color: #cdd6f4; font-size: 16px;")
        self.image_label.setMinimumSize(640, 480)
        
        image_layout.addWidget(self.image_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        image_layout.addWidget(self.progress_bar)
        
        # Image controls
        image_controls = QHBoxLayout()
        
        self.select_images_btn = QPushButton("Select Images")
        self.select_images_btn.clicked.connect(self.select_images)
        
        self.process_images_btn = QPushButton("Process Images")
        self.process_images_btn.clicked.connect(self.process_images)
        self.process_images_btn.setEnabled(False)
        
        self.pause_processing_btn = QPushButton("Pause Processing")
        self.pause_processing_btn.clicked.connect(self.toggle_processing)
        self.pause_processing_btn.setEnabled(False)
        
        image_controls.addWidget(self.select_images_btn)
        image_controls.addWidget(self.process_images_btn)
        image_controls.addWidget(self.pause_processing_btn)
        
        image_layout.addLayout(image_controls)
        image_group.setLayout(image_layout)
        
        # Processing status
        status_group = QGroupBox("Processing Status")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("No images selected")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        
        status_layout.addWidget(self.status_label)
        status_group.setLayout(status_layout)
        
        # Add panels to left layout
        left_panel.addWidget(image_group, 7)
        left_panel.addWidget(status_group, 1)
        
        # Right panel - Database and logs
        right_panel = QVBoxLayout()
        
        # Database controls
        db_group = QGroupBox("Database")
        db_layout = QVBoxLayout()
        
        self.db_path_label = QLabel("No database selected")
        self.db_path_label.setStyleSheet("font-style: italic;")
        
        db_buttons = QHBoxLayout()
        
        select_db_btn = QPushButton("Select Database")
        select_db_btn.clicked.connect(self.select_database)
        
        create_db_btn = QPushButton("Create Database")
        create_db_btn.clicked.connect(self.create_database)
        
        load_faces_btn = QPushButton("Load Known Faces")
        load_faces_btn.clicked.connect(self.load_known_faces)
        
        db_buttons.addWidget(select_db_btn)
        db_buttons.addWidget(create_db_btn)
        db_layout.addWidget(self.db_path_label)
        db_layout.addLayout(db_buttons)
        db_layout.addWidget(load_faces_btn)
        
        db_group.setLayout(db_layout)
        
        # Face management
        face_group = QGroupBox("Face Management")
        face_layout = QVBoxLayout()
        
        self.face_list = QListWidget()
        self.face_list.itemClicked.connect(self.face_selected)
        
        face_buttons = QHBoxLayout()
        
        delete_face_btn = QPushButton("Delete Selected")
        delete_face_btn.clicked.connect(self.delete_face)
        delete_face_btn.setStyleSheet("background-color: #f38ba8;")
        
        face_buttons.addWidget(delete_face_btn)
        
        face_layout.addWidget(QLabel("Known Faces:"))
        face_layout.addWidget(self.face_list)
        face_layout.addLayout(face_buttons)
        
        face_group.setLayout(face_layout)
        
        # Log section
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        
        # Add panels to right layout
        right_panel.addWidget(db_group, 2)
        right_panel.addWidget(face_group, 3)
        right_panel.addWidget(log_group, 3)
        
        # Add both panels to main layout
        main_layout.addLayout(left_panel, 6)
        main_layout.addLayout(right_panel, 4)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Initial log message
        self.log_message("Application started")
        self.log_message("Please select or create a database")
    
    def update_frame(self, frame):
        # Process the frame with MTCNN to get detected faces
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Use detect method instead of direct call
        boxes, _ = self.mtcnn.detect(Image.fromarray(frame_rgb))
        
        # If faces found, draw boxes
        if boxes is not None:
            for box in boxes:
                box = [int(b) for b in box]
                cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
        
        # Convert to QImage and display
        h, w, c = frame.shape
        q_img = QImage(frame.data, w, h, w * c, QImage.Format_RGB888).rgbSwapped()
        self.image_label.setPixmap(QPixmap.fromImage(q_img).scaled(self.image_label.size(), Qt.KeepAspectRatio))
    
    def process_current_frame(self):
        # Get the current frame
        pixmap = self.image_label.pixmap()
        if pixmap is None:
            return
        
        qimg = pixmap.toImage()
        buffer = qimg.bits().asstring(qimg.byteCount())
        image = np.frombuffer(buffer, dtype=np.uint8).reshape((qimg.height(), qimg.width(), 4))
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        
        # Detect faces
        try:
            # Use detect instead of direct call
            boxes, _ = self.mtcnn.detect(Image.fromarray(image_rgb))
            
            if boxes is None or len(boxes) == 0:
                self.status_label.setText("No face detected")
                self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; color: #f38ba8;")
                return
            
            # Process the first detected face
            box = boxes[0]
            x1, y1, x2, y2 = [int(coord) for coord in box]
            
            # Extract face with margin
            h, w = y2 - y1, x2 - x1
            margin_h, margin_w = int(h * 0.1), int(w * 0.1)
            
            # Ensure coordinates are within image bounds
            y1_margin = max(0, y1 - margin_h)
            y2_margin = min(image_rgb.shape[0], y2 + margin_h)
            x1_margin = max(0, x1 - margin_w)
            x2_margin = min(image_rgb.shape[1], x2 + margin_w)
            
            # Extract face
            face = image_rgb[y1_margin:y2_margin, x1_margin:x2_margin]
            
            # Convert to PIL Image and resize
            face_img = Image.fromarray(face).resize((160, 160))
            
            # Convert to tensor directly
            face_tensor = torch.from_numpy(np.array(face_img)).permute(2, 0, 1).float()
            face_tensor = face_tensor.unsqueeze(0)  # Add batch dimension
            
            # Normalize
            face_tensor = face_tensor / 255.0  # Scale to [0, 1]
            face_tensor = (face_tensor - 0.5) / 0.5  # Scale to [-1, 1]
            
            # Move to same device as model
            if torch.cuda.is_available():
                face_tensor = face_tensor.cuda()
            
            # Get embedding
            with torch.no_grad():
                embedding = self.facenet(face_tensor)
                self.current_face_embedding = embedding.cpu().numpy().flatten()
            
            # If we have known faces, compare and find the best match
            if self.known_faces and self.db_path:
                best_match = None
                best_score = 0
                
                for name, stored_embedding in self.known_faces.items():
                    # Calculate cosine similarity
                    similarity = self.cosine_similarity(self.current_face_embedding, stored_embedding)
                    
                    if similarity > best_score:
                        best_score = similarity
                        best_match = name
                
                if best_score > self.face_threshold:
                    self.current_face_name = best_match
                    self.status_label.setText(f"Recognized: {best_match}\nConfidence: {best_score:.2f}")
                    self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; color: #a6e3a1;")
                else:
                    self.current_face_name = None
                    self.status_label.setText(f"Unknown Face\nBest match: {best_match} ({best_score:.2f})")
                    self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; color: #f9e2af;")
            else:
                self.status_label.setText("Face detected\nNo database loaded")
                self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; color: #89b4fa;")
        
        except Exception as e:
            self.log_message(f"Error processing frame: {str(e)}")
    
    def cosine_similarity(self, embedding1, embedding2):
        return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))
    
    def toggle_processing(self):
        # If the processor is not running yet, start it
        if not self.batch_processor.isRunning():
            self.batch_processor.start()
            self.pause_processing_btn.setText("Pause Processing")
            self.status_bar.showMessage("Processing started")
            self.process_images_btn.setEnabled(False)  # Disable process images button when processing
            return
            
        # If already running, toggle pause/resume
        paused = self.batch_processor.pause()
        if paused:
            self.pause_processing_btn.setText("Resume Processing")
            self.status_bar.showMessage("Processing paused")
            self.process_images_btn.setEnabled(True)  # Enable process images button when processing is paused
        else:
            self.pause_processing_btn.setText("Pause Processing")
            self.status_bar.showMessage("Processing resumed")
            self.process_images_btn.setEnabled(False)  # Disable process images button when processing is resumed
    
    def select_database(self):
        db_path, _ = QFileDialog.getOpenFileName(
            self, "Select Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            self.db_path = db_path
            self.db_path_label.setText(os.path.basename(db_path))
            self.status_bar.showMessage(f"Database: {db_path}")
            self.log_message(f"Selected database: {db_path}")
            
            self.ensure_database_structure()
            self.load_known_faces()
    
    def create_database(self):
        db_path, _ = QFileDialog.getSaveFileName(
            self, "Create Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            self.db_path = db_path
            self.db_path_label.setText(os.path.basename(db_path))
            self.status_bar.showMessage(f"Database: {db_path}")
            self.log_message(f"Created database: {db_path}")
            
            self.create_database_structure()
    
    def ensure_database_structure(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                embedding BLOB
            )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            self.log_message(f"Database error: {str(e)}")
    
    def create_database_structure(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                type TEXT,
                status TEXT,
                description TEXT,
                embedding BLOB,
                image_path TEXT
            )
            ''')
            
            conn.commit()
            conn.close()
            
            self.log_message("Database structure created successfully")
        except Exception as e:
            self.log_message(f"Error creating database: {str(e)}")
    
    def load_known_faces(self):
        """Load known faces from the database"""
        if not self.db_path:
            self.log_message("No database selected")
            return
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Clear existing faces
            self.known_faces = {}
            self.face_list.clear()
            
            # Get all faces from database
            cursor.execute("SELECT name, type, status, description, embedding FROM face_embeddings")
            rows = cursor.fetchall()
            
            for row in rows:
                name, face_type, status, description, embedding_bytes = row
                embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
                
                # Store in known_faces dictionary
                self.known_faces[name] = embedding
                
                # Create list item with details
                item = QListWidgetItem(name)
                item.setToolTip(f"Type: {face_type}\nStatus: {status}\nDescription: {description}")
                self.face_list.addItem(item)
            
            conn.close()
            
            self.log_message(f"Loaded {len(self.known_faces)} faces from database")
            self.status_bar.showMessage(f"Loaded {len(self.known_faces)} faces")
        except Exception as e:
            self.log_message(f"Error loading faces: {str(e)}")
    
    def face_selected(self, item):
        self.status_bar.showMessage(f"Selected face: {item.text()}")
    
    def delete_face(self):
        if not self.face_list.currentItem():
            self.log_message("No face selected for deletion")
            return
        
        name = self.face_list.currentItem().text()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM face_embeddings WHERE name = ?", (name,))
            conn.commit()
            conn.close()
            
            # Remove from known faces dictionary
            if name in self.known_faces:
                del self.known_faces[name]
            
            # Update face list
            self.face_list.takeItem(self.face_list.currentRow())
            
            self.log_message(f"Deleted face: {name}")
            self.status_bar.showMessage(f"Deleted face: {name}")
        except Exception as e:
            self.log_message(f"Error deleting face: {str(e)}")
    
    def log_message(self, message):
        self.log_text.append(f"[{QTime.currentTime().toString('hh:mm:ss')}] {message}")
    
    def closeEvent(self, event):
        # Stop the processor before closing
        if hasattr(self, 'batch_processor') and self.batch_processor.isRunning():
            self.batch_processor.stop()
        event.accept()

    def select_images(self):
        """Select multiple images for processing"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.bmp)")
        
        if file_dialog.exec_():
            self.image_paths = file_dialog.selectedFiles()
            self.log_message(f"Selected {len(self.image_paths)} images")
            self.status_label.setText(f"{len(self.image_paths)} images selected")
            self.status_bar.showMessage(f"Selected {len(self.image_paths)} images")
            
            # Enable process button if images are selected
            self.process_images_btn.setEnabled(len(self.image_paths) > 0)
            
            # Show first image as preview if available
            if self.image_paths:
                pixmap = QPixmap(self.image_paths[0])
                self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio))
    
    def process_images(self):
        """Start processing the selected images"""
        if not self.image_paths:
            self.log_message("No images selected")
            return
            
        if not self.db_path:
            self.log_message("No database selected")
            QMessageBox.warning(self, "No Database", "Please select or create a database first.")
            return
            
        # Reset progress bar
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.image_paths))
        
        # Update UI
        self.status_label.setText("Processing images...")
        self.select_images_btn.setEnabled(False)
        self.process_images_btn.setEnabled(False)
        self.pause_processing_btn.setEnabled(True)
        
        # Connect progress signal
        self.batch_processor.update_progress.connect(self.update_progress)
        
        # Set images and start processing
        self.batch_processor.set_images(self.image_paths)
        self.batch_processor.start()
        
        self.log_message(f"Started processing {len(self.image_paths)} images")
    
    def update_progress(self, current, total):
        """Update progress bar and status"""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processing image {current} of {total}")
        
        # Show current image
        if current < len(self.image_paths):
            pixmap = QPixmap(self.image_paths[current-1])
            self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio))
    
    def processing_finished(self):
        """Called when batch processing is complete"""
        self.log_message("Image processing complete")
        self.status_label.setText("Processing complete")
        self.status_bar.showMessage("Processing complete")
        
        # Reset UI
        self.select_images_btn.setEnabled(True)
        self.process_images_btn.setEnabled(True)
        self.pause_processing_btn.setEnabled(False)
    
    def face_detected(self, face_image, embedding, image_path):
        """Handle a detected face from the batch processor"""
        # Ensure the face image is contiguous and in the right format
        face_rgb = np.ascontiguousarray(face_image)
        
        # Check if face already exists in database
        best_match = None
        best_score = 0
        
        if self.known_faces:
            for name, known_embedding in self.known_faces.items():
                score = self.cosine_similarity(embedding, known_embedding)
                if score > best_score:
                    best_score = score
                    best_match = name
        
        # If face is recognized with high confidence, log it
        if best_match and best_score > self.face_threshold:
            self.log_message(f"Recognized face: {best_match} ({best_score:.2f}) in {os.path.basename(image_path)}")
            return
        
        # Otherwise, show dialog to add new face
        dialog = FaceDetailsDialog(face_rgb, self)
        
        if dialog.exec_() == QDialog.Accepted:
            details = dialog.get_details()
            
            if not details["name"]:
                self.log_message("Face skipped - no name provided")
                return
                
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Check if the name already exists
                cursor.execute("SELECT id FROM face_embeddings WHERE name = ?", (details["name"],))
                existing = cursor.fetchone()
                
                if existing:
                    # Ask for confirmation to update
                    confirm = QMessageBox.question(
                        self, 
                        "Update Existing Face", 
                        f"A face with the name '{details['name']}' already exists. Do you want to update it?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    
                    if confirm == QMessageBox.Yes:
                        # Update existing face
                        cursor.execute(
                            "UPDATE face_embeddings SET embedding = ?, type = ?, status = ?, description = ?, image_path = ? WHERE name = ?",
                            (embedding.tobytes(), details["type"], details["status"], details["description"], image_path, details["name"])
                        )
                        self.log_message(f"Updated existing face: {details['name']}")
                    else:
                        self.log_message(f"Skipped updating face: {details['name']}")
                        conn.close()
                        return
                else:
                    # Insert new face
                    cursor.execute(
                        "INSERT INTO face_embeddings (name, type, status, description, embedding, image_path) VALUES (?, ?, ?, ?, ?, ?)",
                        (details["name"], details["type"], details["status"], details["description"], embedding.tobytes(), image_path)
                    )
                    self.log_message(f"Added new face: {details['name']}")
                
                conn.commit()
                conn.close()
                
                # Update known faces
                self.known_faces[details["name"]] = embedding
                
                # Update face list
                self.face_list.clear()
                for face_name in self.known_faces.keys():
                    self.face_list.addItem(face_name)
                
            except Exception as e:
                self.log_message(f"Error adding face: {str(e)}")
        else:
            self.log_message("Face skipped by user")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application-wide dark palette
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(30, 30, 46))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(24, 24, 37))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(137, 180, 250))
    dark_palette.setColor(QPalette.Highlight, QColor(137, 180, 250))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)
    
    window = FaceRecognitionApp()
    window.show()
    sys.exit(app.exec_())