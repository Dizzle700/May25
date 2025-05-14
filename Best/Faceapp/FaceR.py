import sys
import os
import sqlite3
import numpy as np
from PIL import Image
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QFileDialog, 
                            QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, 
                            QListWidget, QWidget, QStatusBar, QGroupBox, QTextEdit, QScrollArea)
from PyQt5.QtGui import QPixmap, QFont, QColor, QPalette
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class FaceProcessor(QThread):
    update_progress = pyqtSignal(int)
    update_status = pyqtSignal(str)
    
    def __init__(self, image_paths, db_path, vector_extension_available=False):
        super().__init__()
        self.image_paths = image_paths
        self.db_path = db_path
        self.vector_extension_available = vector_extension_available
        
        # Control flags
        self.paused = False
        self.stopped = False
        
        # Initialize face detection and recognition models
        self.mtcnn = MTCNN(
            image_size=160, margin=0, min_face_size=20,
            thresholds=[0.6, 0.7, 0.7], factor=0.709, post_process=True,
            device='cuda' if torch.cuda.is_available() else 'cpu'
        )
        
        self.facenet = InceptionResnetV1(pretrained='vggface2').eval()
        if torch.cuda.is_available():
            self.facenet = self.facenet.cuda()
    
    def pause(self):
        self.paused = True
        self.update_status.emit("Processing paused")
    
    def resume(self):
        self.paused = False
        self.update_status.emit("Processing resumed")
    
    def stop(self):
        self.stopped = True
        self.update_status.emit("Processing stopped")
    
    def run(self):
        # Connect to SQLite database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS face_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            embedding BLOB
        )
        ''')
        
        # Enable the SQLite vector extension if available
        vector_search_enabled = False
        if self.vector_extension_available:
            try:
                conn.enable_load_extension(True)
                cursor.execute("SELECT load_extension('sqlite3-vss')")
                
                # Create vector index if it doesn't exist
                cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS face_vectors USING vss0(embedding(128))")
                vector_search_enabled = True
                self.update_status.emit("Vector search enabled")
            except sqlite3.Error as e:
                self.update_status.emit(f"Warning: Could not enable vector extension: {str(e)}")
                self.update_status.emit("Continuing without vector search capabilities")
        
        total_images = len(self.image_paths)
        processed = 0
        
        for img_path in self.image_paths:
            # Check if processing should stop
            if self.stopped:
                break
                
            # Handle pause
            while self.paused and not self.stopped:
                self.msleep(100)  # Sleep for 100ms while paused
                
            # If stopped during pause
            if self.stopped:
                break
                
            try:
                # Update status
                self.update_status.emit(f"Processing: {os.path.basename(img_path)}")
                
                # Load and process image
                img = Image.open(img_path).convert('RGB')
                
                # Detect face
                face = self.mtcnn(img)
                
                if face is not None:
                    # Get embedding
                    with torch.no_grad():
                        embedding = self.facenet(face.unsqueeze(0))
                        embedding_np = embedding.cpu().numpy().flatten()
                    
                    # Store file path and embedding in the database
                    cursor.execute("INSERT INTO face_embeddings (file_path, embedding) VALUES (?, ?)",
                                  (img_path, embedding_np.tobytes()))
                    
                    # Get the ID of the inserted row
                    last_id = cursor.lastrowid
                    
                    # Insert into vector table if vector search is enabled
                    if vector_search_enabled:
                        embedding_list = embedding_np.tolist()
                        cursor.execute(f"INSERT INTO face_vectors(rowid, embedding) VALUES (?, ?)",
                                     (last_id, embedding_list))
                else:
                    self.update_status.emit(f"No face detected in: {os.path.basename(img_path)}")
            
            except Exception as e:
                self.update_status.emit(f"Error processing {os.path.basename(img_path)}: {str(e)}")
            
            processed += 1
            progress = int((processed / total_images) * 100)
            self.update_progress.emit(progress)
            
            # Commit every 10 images or at the end
            if processed % 10 == 0 or processed == total_images:
                conn.commit()
        
        # Commit and close connection
        conn.commit()
        conn.close()
        
        if self.stopped:
            self.update_status.emit("Processing was stopped by user")
        elif not self.paused:
            self.update_status.emit("Processing complete!")

class FaceEmbeddingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FaceNet Embedding Processor")
        self.setMinimumSize(800, 600)
        
        # Initialize variables
        self.image_paths = []
        self.db_path = ""
        self.processor = None
        self.vector_extension_available = False
        
        # Set up the UI
        self.setup_ui()
        
        # Check if vector extension is available
        self.vector_extension_available = self.check_vector_extension()
    
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
            QProgressBar {
                border: 2px solid #313244;
                border-radius: 5px;
                text-align: center;
                background-color: #181825;
                color: #cdd6f4;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                width: 10px;
                margin: 0.5px;
            }
            QListWidget, QTextEdit, QScrollArea {
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
            QScrollBar:vertical {
                border: none;
                background: #313244;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #6c7086;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Create central widget with scroll area
        central_widget = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(central_widget)
        self.setCentralWidget(scroll_area)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Input section
        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout()
        
        select_files_btn = QPushButton("Select Image Files")
        select_files_btn.clicked.connect(self.select_files)
        
        select_folder_btn = QPushButton("Select Image Folder")
        select_folder_btn.clicked.connect(self.select_folder)
        
        files_buttons_layout = QHBoxLayout()
        files_buttons_layout.addWidget(select_files_btn)
        files_buttons_layout.addWidget(select_folder_btn)
        
        self.file_list = QListWidget()
        
        input_layout.addLayout(files_buttons_layout)
        input_layout.addWidget(QLabel("Selected Files:"))
        input_layout.addWidget(self.file_list)
        input_group.setLayout(input_layout)
        
        # Database section
        db_group = QGroupBox("Database")
        db_layout = QVBoxLayout()
        
        db_buttons_layout = QHBoxLayout()
        self.db_path_label = QLabel("No database selected")
        self.db_path_label.setStyleSheet("font-style: italic;")
        
        select_db_btn = QPushButton("Select Existing Database")
        select_db_btn.clicked.connect(self.select_database)
        
        create_db_btn = QPushButton("Create New Database")
        create_db_btn.clicked.connect(self.create_new_database)
        
        db_buttons_layout.addWidget(select_db_btn)
        db_buttons_layout.addWidget(create_db_btn)
        
        db_layout.addWidget(self.db_path_label)
        db_layout.addLayout(db_buttons_layout)
        db_group.setLayout(db_layout)
        
        # Process section
        process_group = QGroupBox("Processing")
        process_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        
        # Control buttons layout
        control_buttons_layout = QHBoxLayout()
        
        self.process_btn = QPushButton("Process Images")
        self.process_btn.clicked.connect(self.process_images)
        self.process_btn.setStyleSheet("font-size: 16px; padding: 10px;")
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_processing)
        self.pause_btn.setEnabled(False)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_processing)
        self.stop_btn.setEnabled(False)
        
        control_buttons_layout.addWidget(self.process_btn)
        control_buttons_layout.addWidget(self.pause_btn)
        control_buttons_layout.addWidget(self.stop_btn)
        
        process_layout.addWidget(self.progress_bar)
        process_layout.addWidget(QLabel("Status Log:"))
        process_layout.addWidget(self.status_log)
        process_layout.addLayout(control_buttons_layout)
        process_group.setLayout(process_layout)
        
        # Add sections to main layout
        main_layout.addWidget(input_group)
        main_layout.addWidget(db_group)
        main_layout.addWidget(process_group)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Images", "", "Image Files (*.png *.jpg *.jpeg *.bmp)"
        )
        if files:
            self.add_files(files)
    
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            image_extensions = ['.jpg', '.jpeg', '.png', '.bmp']
            files = []
            
            for root, _, filenames in os.walk(folder):
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in image_extensions:
                        files.append(os.path.join(root, filename))
            
            if files:
                self.add_files(files)
                self.log_message(f"Added {len(files)} images from folder: {folder}")
            else:
                self.log_message(f"No image files found in folder: {folder}")
    
    def add_files(self, files):
        self.image_paths.extend(files)
        self.file_list.clear()
        for path in self.image_paths:
            self.file_list.addItem(os.path.basename(path))
        
        self.status_bar.showMessage(f"{len(self.image_paths)} files selected")
    
    def select_database(self):
        db_path, _ = QFileDialog.getOpenFileName(
            self, "Select Existing Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            # Validate the database structure
            if self.validate_database(db_path):
                self.db_path = db_path
                self.db_path_label.setText(os.path.basename(db_path))
                self.log_message(f"Selected database: {db_path}")
                self.status_bar.showMessage(f"Database: {db_path}")
            else:
                self.log_message(f"Warning: The selected database does not have the required structure.")
                self.log_message("Creating required tables...")
                self.create_database(db_path)
                self.db_path = db_path
                self.db_path_label.setText(os.path.basename(db_path))
    
    def validate_database(self, db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if the face_embeddings table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='face_embeddings'")
            table_exists = cursor.fetchone() is not None
            
            conn.close()
            return table_exists
        except Exception as e:
            self.log_message(f"Error validating database: {str(e)}")
            return False
    
    def create_new_database(self):
        db_path, _ = QFileDialog.getSaveFileName(
            self, "Create New Database", "", "SQLite Database (*.db *.sqlite)"
        )
        if db_path:
            self.db_path = db_path
            self.db_path_label.setText(os.path.basename(db_path))
            self.status_bar.showMessage(f"Database: {db_path}")
            self.create_database(db_path)
    
    def check_vector_extension(self):
        """Check if the SQLite vector extension is available"""
        try:
            # Create a temporary connection
            conn = sqlite3.connect(":memory:")
            conn.enable_load_extension(True)
            cursor = conn.cursor()
            
            # Try to load the extension
            cursor.execute("SELECT load_extension('sqlite3-vss')")
            
            # If we get here, the extension is available
            conn.close()
            self.log_message("SQLite vector extension is available")
            return True
        except Exception as e:
            self.log_message(f"SQLite vector extension is not available: {str(e)}")
            self.log_message("Face embeddings will be stored, but vector search will be disabled")
            self.log_message("To enable vector search, install the sqlite3-vss extension")
            return False
    
    def create_database(self, db_path):
        try:
            self.log_message(f"Creating new database: {os.path.basename(db_path)}")
            
            # Connect to SQLite database (this will create it if it doesn't exist)
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Create table for face embeddings
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                embedding BLOB
            )
            ''')
            
            # Try to enable the SQLite vector extension if available
            if self.vector_extension_available:
                try:
                    conn.enable_load_extension(True)
                    cursor.execute("SELECT load_extension('sqlite3-vss')")
                    
                    # Create vector index
                    cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS face_vectors USING vss0(embedding(128))")
                    self.log_message("Vector search enabled for this database")
                except sqlite3.Error as e:
                    self.log_message(f"Warning: Could not enable vector extension for this database: {str(e)}")
            else:
                self.log_message("Database created without vector search capabilities")
            
            # Commit and close connection
            conn.commit()
            conn.close()
            
            self.log_message("Database created successfully")
        except Exception as e:
            self.log_message(f"Error creating database: {str(e)}")
    
    def process_images(self):
        if not self.image_paths:
            self.log_message("No images selected!")
            return
        
        if not self.db_path:
            self.log_message("No database selected!")
            return
        
        self.progress_bar.setValue(0)
        self.log_message(f"Starting to process {len(self.image_paths)} images...")
        
        # Create and start the processor thread
        self.processor = FaceProcessor(self.image_paths, self.db_path, self.vector_extension_available)
        self.processor.update_progress.connect(self.update_progress)
        self.processor.update_status.connect(self.log_message)
        self.processor.start()
        
        # Update button states
        self.process_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
    
    def pause_processing(self):
        if not hasattr(self, 'processor') or not self.processor:
            return
            
        if self.processor.paused:
            self.processor.resume()
            self.pause_btn.setText("Pause")
            self.log_message("Processing resumed")
        else:
            self.processor.pause()
            self.pause_btn.setText("Resume")
            self.log_message("Processing paused")
    
    def stop_processing(self):
        if not hasattr(self, 'processor') or not self.processor:
            return
            
        self.processor.stop()
        self.log_message("Stopping processing...")
        
        # Wait for the thread to finish
        self.processor.wait()
        
        # Reset button states
        self.process_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(False)
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
        
        # If processing is complete, reset button states
        if value == 100:
            self.process_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("Pause")
            self.stop_btn.setEnabled(False)
    
    def log_message(self, message):
        self.status_log.append(message)
        self.status_bar.showMessage(message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application-wide dark palette
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(33, 38, 45))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)
    
    window = FaceEmbeddingApp()
    window.show()
    sys.exit(app.exec_())