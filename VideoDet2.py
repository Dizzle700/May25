import sys
import cv2
import numpy as np
import time # Import time for cooldown
from datetime import datetime
from ultralytics import YOLO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QComboBox, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QPixmap, QIcon

# PART 1: STYLESHEET FOR A MODERN LOOK
# ======================================
STYLESHEET = """
QWidget {
    background-color: #2c3e50;
    color: #ecf0f1;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 14px;
}
QMainWindow {
    border-image: none;
}
QPushButton {
    background-color: #3498db;
    color: #ffffff;
    border: none;
    padding: 10px 20px;
    border-radius: 5px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #2980b9;
}
QPushButton:pressed {
    background-color: #1f618d;
}
#StopButton {
    background-color: #e74c3c;
}
#StopButton:hover {
    background-color: #c0392b;
}
#StopButton:pressed {
    background-color: #a93226;
}
QComboBox {
    background-color: #34495e;
    border: 1px solid #7f8c8d;
    padding: 5px;
    border-radius: 3px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #34495e;
    selection-background-color: #3498db;
    color: #ecf0f1;
}
QSlider::groove:horizontal {
    border: 1px solid #7f8c8d;
    height: 8px;
    background: #34495e;
    margin: 2px 0;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #3498db;
    border: 1px solid #3498db;
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}
QLabel {
    color: #ecf0f1;
}
#VideoLabel {
    background-color: #000000;
    border: 2px solid #34495e;
}
QTableWidget {
    background-color: #34495e;
    gridline-color: #7f8c8d;
    border: 1px solid #7f8c8d;
}
QTableWidget::item {
    padding: 5px;
}
QHeaderView::section {
    background-color: #2c3e50;
    color: #ecf0f1;
    padding: 5px;
    border: 1px solid #7f8c8d;
    font-weight: bold;
}
"""


# PART 2: THE VIDEO PROCESSING THREAD
# ===================================
class VideoThread(QThread):
    """
    A QThread for handling the video capture and YOLO processing
    in the background to prevent the GUI from freezing.
    """
    # Signals to send data back to the main GUI thread
    change_pixmap_signal = pyqtSignal(np.ndarray)
    update_results_signal = pyqtSignal(dict)

    def __init__(self, model_path, camera_index, confidence_threshold, cooldown_seconds=1.0):
        super().__init__()
        self.model_path = model_path
        self.camera_index = camera_index
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds
        self._is_running = True
        self.last_detection_times = {} # Stores {class_name: timestamp}

    def run(self):
        """The main loop of the thread."""
        try:
            model = YOLO(self.model_path)
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                print(f"Error: Could not open camera {self.camera_index}")
                return

            while self._is_running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Run YOLO detection
                results = model(frame, conf=self.confidence_threshold, verbose=False)
                annotated_frame = results[0].plot() # YOLOv8 provides this handy method

                # Emit the annotated frame
                self.change_pixmap_signal.emit(annotated_frame)

                # Process and emit detection results with cooldown
                current_time = time.time()
                detections_to_update = {}
                for r in results:
                    for box in r.boxes:
                        class_id = int(box.cls[0])
                        class_name = model.names[class_id]
                        
                        # Check cooldown
                        if (class_name not in self.last_detection_times or 
                            (current_time - self.last_detection_times[class_name]) > self.cooldown_seconds):
                            
                            detections_to_update[class_name] = detections_to_update.get(class_name, 0) + 1
                            self.last_detection_times[class_name] = current_time
                
                if detections_to_update:
                    self.update_results_signal.emit(detections_to_update)

            cap.release()
        except Exception as e:
            print(f"An error occurred in the video thread: {e}")

    def stop(self):
        """Stops the thread's loop."""
        self._is_running = False
        self.wait() # Wait for the thread to finish cleanly


# PART 3: THE MAIN APPLICATION WINDOW
# ===================================
class MainWindow(QMainWindow):
    """The main window of the application."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO Object Recognition App")
        self.setGeometry(100, 100, 1200, 800)

        self.model_path = "yolov8n.pt"  # Default model
        self.detected_objects = {}  # To store counts and timestamps
        self.video_thread = None

        self.setup_ui()
        self.apply_stylesheet()
        self.populate_webcams()

    def setup_ui(self):
        """Creates and arranges all the widgets in the window."""
        # Main container
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # --- Header Section (Settings) ---
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 10)

        self.model_btn = QPushButton("Choose Model")
        self.model_btn.clicked.connect(self.choose_model_file)
        self.model_label = QLabel(f"Model: {self.model_path.split('/')[-1]}")

        self.webcam_combo = QComboBox()
        
        self.threshold_label = QLabel("Confidence Threshold: 50%")
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 100)
        self.threshold_slider.setValue(50)
        self.threshold_slider.valueChanged.connect(
            lambda v: self.threshold_label.setText(f"Confidence Threshold: {v}%")
        )

        self.cooldown_label = QLabel("Cooldown: 1.0s")
        self.cooldown_slider = QSlider(Qt.Orientation.Horizontal)
        self.cooldown_slider.setRange(0, 50) # 0 to 5 seconds, in 0.1s increments
        self.cooldown_slider.setValue(10) # Default to 1.0 seconds
        self.cooldown_slider.valueChanged.connect(
            lambda v: self.cooldown_label.setText(f"Cooldown: {v/10.0:.1f}s")
        )

        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_MediaPlay))
        self.start_btn.clicked.connect(self.start_detection)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("StopButton") # For specific styling
        self.stop_btn.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_MediaStop))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_detection)

        header_layout.addWidget(self.model_btn)
        header_layout.addWidget(self.model_label)
        header_layout.addSpacing(20)
        header_layout.addWidget(QLabel("Webcam:"))
        header_layout.addWidget(self.webcam_combo)
        header_layout.addSpacing(20)
        header_layout.addWidget(self.threshold_label)
        header_layout.addWidget(self.threshold_slider)
        header_layout.addSpacing(20)
        header_layout.addWidget(self.cooldown_label)
        header_layout.addWidget(self.cooldown_slider)
        header_layout.addStretch()
        header_layout.addWidget(self.start_btn)
        header_layout.addWidget(self.stop_btn)

        # --- Body Section (Video and Results) ---
        body_widget = QWidget()
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        
        # Center: Video Livestream
        self.video_label = QLabel("Webcam Livestream will appear here")
        self.video_label.setObjectName("VideoLabel")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(800, 600)

        # Right: List of recognized objects
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Object (Class)", "Total Count", "Last Seen"])
        self.results_table.setFixedWidth(350)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.verticalHeader().setVisible(False)

        body_layout.addWidget(self.video_label, 1) # Add with stretch factor
        body_layout.addWidget(self.results_table)

        # Add all sections to the main layout
        main_layout.addWidget(header_widget)
        main_layout.addWidget(body_widget)

    def apply_stylesheet(self):
        """Applies the QSS stylesheet to the application."""
        self.setStyleSheet(STYLESHEET)

    def populate_webcams(self):
        """Finds available webcams and adds them to the dropdown."""
        self.webcam_combo.clear()
        available_cameras = []
        for i in range(5):  # Check up to 5 camera indices
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available_cameras.append(f"Webcam {i}")
                cap.release()
        
        if available_cameras:
            self.webcam_combo.addItems(available_cameras)
        else:
            self.webcam_combo.addItem("No Webcams Found")
            self.start_btn.setEnabled(False)

    def choose_model_file(self):
        """Opens a dialog to select a YOLO model file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose YOLO Model", "", "PyTorch Model Files (*.pt)")
        if file_path:
            self.model_path = file_path
            self.model_label.setText(f"Model: {self.model_path.split('/')[-1]}")
            print(f"Selected model: {self.model_path}")

    def start_detection(self):
        """Starts the video processing thread."""
        if not self.model_path:
            self.model_label.setText("Model: Please select a model first!")
            return

        camera_text = self.webcam_combo.currentText()
        if "No Webcams" in camera_text:
            return
        
        camera_index = int(camera_text.split()[-1])
        confidence = self.threshold_slider.value() / 100.0

        # Reset results
        self.detected_objects.clear()
        self.update_results_table()

        # Create and start thread
        cooldown = self.cooldown_slider.value() / 10.0
        self.video_thread = VideoThread(self.model_path, camera_index, confidence, cooldown)
        self.video_thread.change_pixmap_signal.connect(self.update_frame)
        self.video_thread.update_results_signal.connect(self.update_detection_results)
        self.video_thread.start()

        # Update UI state
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.model_btn.setEnabled(False)
        self.webcam_combo.setEnabled(False)
        self.threshold_slider.setEnabled(False)
        self.cooldown_slider.setEnabled(False) # Disable cooldown slider

    def stop_detection(self):
        """Stops the video processing thread."""
        if self.video_thread:
            self.video_thread.stop()
        
        # Update UI state
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.model_btn.setEnabled(True)
        self.webcam_combo.setEnabled(True)
        self.threshold_slider.setEnabled(True)
        self.cooldown_slider.setEnabled(True) # Enable cooldown slider
        self.video_label.setText("Webcam Livestream stopped.")
        self.video_label.repaint() # Force repaint to show text

    def update_frame(self, cv_img):
        """Updates the video_label with a new frame from the thread."""
        qt_img = self.convert_cv_to_qt(cv_img)
        self.video_label.setPixmap(qt_img)

    def convert_cv_to_qt(self, cv_img):
        """Convert an OpenCV image to QPixmap."""
        rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        convert_to_qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        p = QPixmap.fromImage(convert_to_qt_format)
        # Scale pixmap to fit the label while maintaining aspect ratio
        return p.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def update_detection_results(self, detections_in_frame):
        """Updates the master dictionary of detected objects."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        for class_name, count in detections_in_frame.items():
            if class_name in self.detected_objects:
                self.detected_objects[class_name]['count'] += count
                self.detected_objects[class_name]['timestamp'] = timestamp
            else:
                self.detected_objects[class_name] = {'count': count, 'timestamp': timestamp}
        
        self.update_results_table()

    def update_results_table(self):
        """Redraws the results table based on the detected_objects dictionary."""
        self.results_table.setRowCount(len(self.detected_objects))
        
        sorted_items = sorted(self.detected_objects.items(), key=lambda item: item[1]['count'], reverse=True)

        for row, (class_name, data) in enumerate(sorted_items):
            self.results_table.setItem(row, 0, QTableWidgetItem(class_name))
            self.results_table.setItem(row, 1, QTableWidgetItem(str(data['count'])))
            self.results_table.setItem(row, 2, QTableWidgetItem(data['timestamp']))
            # Center align text
            for col in range(3):
                self.results_table.item(row, col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    
    def closeEvent(self, event):
        """Ensure the thread is stopped when the window is closed."""
        self.stop_detection()
        event.accept()


# PART 4: APPLICATION EXECUTION
# =============================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
