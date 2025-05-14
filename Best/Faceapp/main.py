# main.py
import sys
import cv2
import numpy as np
import face_recognition # type: ignore # Often has typing issues
import sqlite3
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox
)
from PyQt6.QtGui import QImage, QPixmap, QFont
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize

from database import init_db, save_blueprint, load_all_blueprints
from crypto_utils import load_key # Ensure key is loaded/generated on start

# --- Face Processing Worker ---
# Run face detection/encoding in a separate thread to avoid freezing the GUI
class FaceWorker(QThread):
    # Signals
    # result: pixmap_with_boxes, num_faces, list_of_encodings, original_frame
    result_ready = pyqtSignal(QPixmap, int, list, object)
    no_camera = pyqtSignal()

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.running = False
        self.process_this_frame = True # Flag to control processing frequency
        self.frame_counter = 0

    def run(self):
        self.running = True
        print("Attempting to open camera...")
        cap = cv2.VideoCapture(self.camera_index)

        if not cap.isOpened():
            print(f"Error: Could not open camera {self.camera_index}.")
            self.no_camera.emit()
            self.running = False
            return

        print("Camera opened successfully.")
        while self.running:
            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to grab frame.")
                # Maybe wait a bit before trying again or stopping
                self.msleep(50)
                continue

            # 1. Convert to RGB (face_recognition uses RGB)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            face_locations = []
            face_encodings = []
            num_faces = 0

            # 2. Process every Nth frame to save CPU
            self.frame_counter += 1
            if self.frame_counter % 2 == 0: # Process every other frame
                # Find face locations (fast)
                face_locations = face_recognition.face_locations(rgb_frame, model="hog") # Use "cnn" for more accuracy but much slower
                num_faces = len(face_locations)

                # Generate encodings ONLY if faces are found (slower)
                if num_faces > 0:
                    # Pass locations to speed up encoding
                    face_encodings = face_recognition.face_encodings(rgb_frame, known_face_locations=face_locations)

                self.process_this_frame = False # Reset flag if needed

            # 3. Draw rectangles on the *original* BGR frame for display
            display_frame = frame.copy()
            for (top, right, bottom, left) in face_locations:
                 # Make bounding box slightly bigger/more visible
                 pad = 10
                 cv2.rectangle(display_frame,
                               (left - pad, top - pad),
                               (right + pad, bottom + pad),
                               (0, 255, 0), # Green box
                               2) # Thickness

            # 4. Convert display frame to QPixmap
            h, w, ch = display_frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(display_frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
            # Keep aspect ratio for display
            pixmap = QPixmap.fromImage(qt_image).scaled(640, 480, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            # 5. Emit results (pass original RGB frame too if needed for capture)
            # Pass the *original* frame (before drawing boxes) if needed later?
            # Let's pass the rgb_frame used for encoding
            self.result_ready.emit(pixmap, num_faces, face_encodings, rgb_frame)

            # Small delay to control frame rate and yield CPU
            self.msleep(30) # ~33 FPS target for capture loop

        cap.release()
        print("Camera released.")

    def stop(self):
        self.running = False
        self.wait() # Wait for the thread to finish cleanly


# --- Main Application Window ---
class FaceBlueprintApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face Blueprint Capture")
        self.setGeometry(100, 100, 700, 700) # x, y, width, height

        # --- State Variables ---
        self.current_pixmap = None
        self.last_detected_faces = 0
        self.last_face_encodings = []
        self.last_rgb_frame = None # Store the frame used for last detection
        self.db_conn = None
        self.face_worker = None

        # --- Load Encryption Key and Init DB ---
        try:
            load_key() # Ensure key exists or is generated
            self.db_conn = init_db() # Initialize database connection
        except Exception as e:
             QMessageBox.critical(self, "Initialization Error", f"Could not initialize crypto key or database:\n{e}\n\nPlease check permissions and file access. The application might not function correctly.")
             # Optionally exit: sys.exit()
             # Or allow to continue but disable DB features

        # --- UI Elements ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(20, 20, 20, 20) # Add padding

        # Video Display Label
        self.video_label = QLabel("Connecting to camera...")
        self.video_label.setObjectName("VideoLabel") # For CSS styling
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setFont(QFont("Arial", 14))
        self.layout.addWidget(self.video_label)

        # Controls Layout (Horizontal)
        self.controls_layout = QHBoxLayout()

        # Name Input
        self.name_label = QLabel("Name:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter name for blueprint")
        self.controls_layout.addWidget(self.name_label)
        self.controls_layout.addWidget(self.name_input)

        # Capture Button
        self.capture_button = QPushButton("Capture & Save Blueprint")
        self.capture_button.setObjectName("CaptureButton")
        self.capture_button.setMinimumWidth(200)
        self.capture_button.clicked.connect(self.capture_and_save)
        self.capture_button.setEnabled(False) # Disabled until a face is detected
        self.controls_layout.addWidget(self.capture_button)

        self.layout.addLayout(self.controls_layout)

        # Status Label
        self.status_label = QLabel("Status: Initializing...")
        self.status_label.setObjectName("StatusLabel") # For CSS styling
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.status_label)

        # Apply Stylesheet (Optional)
        try:
            with open("style.qss", "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print("Stylesheet 'style.qss' not found. Using default styles.")
        except Exception as e:
            print(f"Error loading stylesheet: {e}")


        # --- Start Camera Worker ---
        self.start_camera_worker()

    def start_camera_worker(self):
        if self.face_worker and self.face_worker.isRunning():
            return # Already running

        print("Starting face worker thread...")
        self.face_worker = FaceWorker(camera_index=0) # Use camera 0
        self.face_worker.result_ready.connect(self.update_frame)
        self.face_worker.no_camera.connect(self.handle_no_camera)
        self.face_worker.finished.connect(self.worker_finished) # Optional cleanup
        self.face_worker.start()
        self.update_status("Connecting to camera...", "warning")


    def stop_camera_worker(self):
        if self.face_worker and self.face_worker.isRunning():
            print("Stopping face worker thread...")
            self.face_worker.stop() # Signal thread to stop
            self.face_worker = None # Allow garbage collection
            self.video_label.setText("Camera stopped.")
            self.video_label.setPixmap(QPixmap()) # Clear image
            self.capture_button.setEnabled(False)


    @property # Use property for easier status updates with styling
    def status(self):
        return self.status_label.text()

    @status.setter
    def status(self, value_tuple):
        message, level = value_tuple # Expect ('message', 'success'/'error'/'warning'/'info')
        self.status_label.setText(f"Status: {message}")
        self.status_label.setProperty("status", level) # For CSS selector
        # Re-apply style to update background/color based on property
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def update_status(self, message, level="info"):
         self.status = (message, level)


    def update_frame(self, pixmap, num_faces, face_encodings, rgb_frame):
        """Receives processed frame data from the worker thread."""
        self.current_pixmap = pixmap
        self.video_label.setPixmap(self.current_pixmap)
        self.last_detected_faces = num_faces
        self.last_face_encodings = face_encodings
        self.last_rgb_frame = rgb_frame # Store the frame associated with these encodings

        if num_faces == 1:
            self.update_status("Face detected. Ready to capture.", "success")
            self.capture_button.setEnabled(True)
        elif num_faces > 1:
            self.update_status("Multiple faces detected. Please ensure only one face is visible.", "warning")
            self.capture_button.setEnabled(False)
        else:
            self.update_status("No face detected.", "warning")
            self.capture_button.setEnabled(False)


    def capture_and_save(self):
        """Captures the current face encoding and saves it to the database."""
        name = self.name_input.text().strip()
        if not name:
            self.update_status("Please enter a name.", "error")
            QMessageBox.warning(self, "Input Required", "Please enter a name for the blueprint.")
            self.name_input.setFocus()
            return

        if self.last_detected_faces == 1 and self.last_face_encodings:
            # Use the encoding calculated by the worker thread
            blueprint_to_save = self.last_face_encodings[0] # Get the first (and only) encoding

            # Disable button during save
            self.capture_button.setEnabled(False)
            self.update_status(f"Saving blueprint for {name}...", "info")
            QApplication.processEvents() # Update UI immediately

            if self.db_conn:
                success = save_blueprint(self.db_conn, name, blueprint_to_save)
                if success:
                    self.update_status(f"Blueprint for '{name}' saved successfully!", "success")
                    self.name_input.clear() # Clear name field on success
                    # Optionally, reload known faces if using for comparison later
                else:
                    # save_blueprint prints specific errors (duplicate, db error)
                    self.update_status(f"Failed to save blueprint for '{name}'. See console/log.", "error")
                    QMessageBox.critical(self, "Save Failed", "Could not save the blueprint. It might already exist or there was a database error.")
            else:
                self.update_status("Database connection is not available.", "error")
                QMessageBox.critical(self, "Error", "Database connection is not available.")

            # Re-enable button based on current detection status (might have changed)
            # This happens automatically in the next update_frame call
        elif self.last_detected_faces > 1:
             self.update_status("Cannot capture: Multiple faces detected.", "error")
             QMessageBox.warning(self, "Capture Error", "Multiple faces detected. Please ensure only one face is clearly visible.")
        else:
             self.update_status("Cannot capture: No face detected.", "error")
             QMessageBox.warning(self, "Capture Error", "No face detected. Please position your face in the camera view.")
             self.capture_button.setEnabled(False)


    def handle_no_camera(self):
        """Called by worker if camera fails to open."""
        self.update_status("Failed to open camera.", "error")
        self.video_label.setText("ERROR: Camera not accessible!")
        self.capture_button.setEnabled(False)
        QMessageBox.critical(self, "Camera Error", "Could not access the webcam. Please ensure it is connected and not in use by another application.")

    def worker_finished(self):
        """Optional slot called when the worker thread finishes."""
        print("Face worker thread has finished.")
        # Can perform cleanup here if needed, though stop_camera_worker handles most

    def closeEvent(self, event):
        """Ensure resources are released on closing the window."""
        print("Closing application...")
        self.stop_camera_worker() # Stop the thread cleanly
        if self.db_conn:
            print("Closing database connection.")
            self.db_conn.close()
        event.accept() # Proceed with closing


# --- Run the Application ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # You might want to set application name and version for better OS integration
    # app.setApplicationName("FaceBlueprintApp")
    # app.setOrganizationName("YourCompany") # Optional

    main_window = FaceBlueprintApp()
    main_window.show()
    sys.exit(app.exec())