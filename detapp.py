import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QComboBox, 
                             QSlider, QScrollArea, QFrame, QSpacerItem, 
                             QSizePolicy)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QFont, QPalette, QColor
import threading
from datetime import datetime
from collections import defaultdict
import time
from ultralytics import YOLO # Import YOLO

# YOLO Detection Thread
class YOLOThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    detection_ready = pyqtSignal(list) # List of detected objects (class_name, confidence)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.cap = None
        self.model = None # Actual YOLO model
        self.model_path = "yolov8n.pt" # Default model path
        self.classes = []
        self.confidence_threshold = 0.5
        self.webcam_index = 0
        self.load_yolo()
        
    def load_yolo(self):
        """Load actual YOLO model"""
        try:
            self.model = YOLO(self.model_path)
            self.classes = self.model.names
            print(f"YOLO model '{self.model_path}' loaded successfully.")
        except Exception as e:
            print(f"Error loading YOLO model: {e}")
            self.model = None # Ensure model is None if loading fails
        
    def set_webcam(self, index):
        self.webcam_index = index
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(index)
        
    def set_confidence_threshold(self, threshold):
        self.confidence_threshold = threshold / 100.0
        
    def run(self):
        self.running = True
        if not self.cap:
            self.cap = cv2.VideoCapture(self.webcam_index)
            
        if not self.cap.isOpened():
            print(f"Error: Could not open camera {self.webcam_index}")
            self.running = False
            return

        if not self.model:
            print("Error: YOLO model not loaded. Cannot start detection.")
            self.running = False
            return
            
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("Failed to grab frame.")
                break

            # Perform actual YOLO inference
            results = self.model(frame, conf=self.confidence_threshold, verbose=False)
            annotated_frame = results[0].plot() # YOLOv8 provides this handy method

            self.frame_ready.emit(annotated_frame)

            detected_objects_in_frame = []
            for r in results:
                for box in r.boxes:
                    class_id = int(box.cls[0])
                    class_name = self.classes[class_id]
                    confidence = float(box.conf[0])
                    
                    detected_objects_in_frame.append({
                        'class': class_name,
                        'confidence': confidence,
                        'timestamp': datetime.now() # Add timestamp for potential cooldown
                    })
            
            if detected_objects_in_frame:
                self.detection_ready.emit(detected_objects_in_frame)
                
        self.cap.release()
        
    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
        self.wait()


# Detection List Widget
class DetectionWidget(QWidget):
    def __init__(self, cooldown_seconds=1.0): # Add cooldown parameter
        super().__init__()
        self.detections = defaultdict(int)
        self.detection_history = []
        self.last_detection_times = {} # Stores {class_name: timestamp}
        self.cooldown_seconds = cooldown_seconds
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("Detected Objects")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Scroll area for detections
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.addStretch()
        
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)
        
        self.setLayout(layout)
        
    def add_detection(self, detection):
        class_name = detection['class']
        confidence = detection['confidence']
        timestamp = detection['timestamp']
        
        current_time = time.time() # Get current time for cooldown check
        
        # Check cooldown before adding detection
        if (class_name not in self.last_detection_times or 
            (current_time - self.last_detection_times[class_name].timestamp()) > self.cooldown_seconds):
            
            self.detections[class_name] += 1
            self.detection_history.append(detection)
            self.last_detection_times[class_name] = timestamp # Update last detection time
            
            # Keep only last 50 detections
            if len(self.detection_history) > 50:
                self.detection_history = self.detection_history[-50:]
            
            self.update_display()
        
    def update_display(self):
        # Clear existing widgets
        for i in reversed(range(self.scroll_layout.count())):
            item = self.scroll_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
                
        # Add detection items
        for class_name, count in sorted(self.detections.items(), key=lambda x: x[1], reverse=True):
            item_widget = QFrame()
            item_widget.setFixedHeight(60)
            item_widget.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                stop:0 #3498db, stop:1 #2980b9);
                    border-radius: 8px;
                    margin: 2px;
                }
            """)
            
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(15, 10, 15, 10)
            
            # Class name
            class_label = QLabel(class_name.title())
            class_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            class_label.setStyleSheet("color: white;")
            
            # Count
            count_label = QLabel(f"{count}x")
            count_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            count_label.setStyleSheet("color: #ecf0f1;")
            count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            
            item_layout.addWidget(class_label)
            item_layout.addWidget(count_label)
            
            self.scroll_layout.insertWidget(0, item_widget)
            
        self.scroll_layout.addStretch()


# Main Application Window
class YOLOWebcamApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.yolo_thread = YOLOThread()
        self.setup_ui()
        self.setup_connections()
        
    def setup_ui(self):
        self.setWindowTitle("YOLO Webcam Object Detection")
        self.setGeometry(100, 100, 1400, 800)
        
        # Set modern color scheme
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #ecf0f1, stop:1 #bdc3c7);
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Header (Settings)
        header_layout = self.create_header()
        main_layout.addLayout(header_layout)
        
        # Main content area
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)
        
        # Left spacer
        content_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum))
        
        # Webcam livestream (center)
        self.video_label = QLabel()
        self.video_label.setMinimumSize(800, 600)
        self.video_label.setStyleSheet("""
            QLabel {
                background-color: #2c3e50;
                border: 3px solid #34495e;
                border-radius: 15px;
                color: white;
                font-size: 18px;
            }
        """)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText("Webcam Livestream\nwith YOLO Detection")
        content_layout.addWidget(self.video_label, 2)
        
        # Detection panel (right)
        # Initialize with default cooldown, will be updated by slider
        self.detection_widget = DetectionWidget(cooldown_seconds=1.0) 
        self.detection_widget.setFixedWidth(300)
        self.detection_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #ffffff, stop:1 #f8f9fa);
                border: 2px solid #dee2e6;
                border-radius: 15px;
            }
        """)
        content_layout.addWidget(self.detection_widget)
        
        main_layout.addLayout(content_layout)
        
    def create_header(self):
        header_layout = QHBoxLayout()
        header_layout.setSpacing(20)
        
        # Model selection
        model_label = QLabel("Model:")
        model_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["YOLOv8n", "YOLOv8s", "YOLOv8m", "YOLOv8l"])
        self.model_combo.setStyleSheet(self.get_combo_style())
        
        # Webcam selection
        webcam_label = QLabel("Webcam:")
        webcam_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.webcam_combo = QComboBox()
        self.webcam_combo.addItems(["Camera 0", "Camera 1", "Camera 2"])
        self.webcam_combo.setStyleSheet(self.get_combo_style())
        
        # Confidence threshold
        threshold_label = QLabel("Recognition Threshold:")
        threshold_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(10, 90)
        self.threshold_slider.setValue(50)
        self.threshold_slider.setFixedWidth(150)
        self.threshold_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #bdc3c7;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #3498db;
                border: 2px solid #2980b9;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #3498db;
                border-radius: 4px;
            }
        """)

        # Cooldown slider
        cooldown_label = QLabel("Cooldown (s):")
        cooldown_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.cooldown_slider = QSlider(Qt.Orientation.Horizontal)
        self.cooldown_slider.setRange(0, 50) # 0 to 5 seconds, in 0.1s increments
        self.cooldown_slider.setValue(10) # Default to 1.0 seconds
        self.cooldown_slider.setFixedWidth(150)
        self.cooldown_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #bdc3c7;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #3498db;
                border: 2px solid #2980b9;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #3498db;
                border-radius: 4px;
            }
        """)
        
        # Control buttons
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(100, 40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #27ae60, stop:1 #229954);
                color: white;
                border: none;
                border-radius: 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #2ecc71, stop:1 #27ae60);
            }
            QPushButton:pressed {
                background: #229954;
            }
        """)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedSize(100, 40)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #e74c3c, stop:1 #c0392b);
                color: white;
                border: none;
                border-radius: 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                           stop:0 #ec7063, stop:1 #e74c3c);
            }
            QPushButton:pressed {
                background: #c0392b;
            }
        """)
        
        # Add widgets to header
        header_layout.addWidget(model_label)
        header_layout.addWidget(self.model_combo)
        header_layout.addWidget(webcam_label)
        header_layout.addWidget(self.webcam_combo)
        header_layout.addWidget(threshold_label)
        header_layout.addWidget(self.threshold_slider)
        header_layout.addWidget(cooldown_label) # Add cooldown label
        header_layout.addWidget(self.cooldown_slider) # Add cooldown slider
        header_layout.addStretch()
        header_layout.addWidget(self.start_btn)
        header_layout.addWidget(self.stop_btn)
        
        return header_layout
        
    def get_combo_style(self):
        return """
            QComboBox {
                background: white;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #3498db;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #7f8c8d;
                margin-right: 10px;
            }
        """
        
    def setup_connections(self):
        self.start_btn.clicked.connect(self.start_detection)
        self.stop_btn.clicked.connect(self.stop_detection)
        self.webcam_combo.currentIndexChanged.connect(self.change_webcam)
        self.threshold_slider.valueChanged.connect(self.change_threshold)
        self.cooldown_slider.valueChanged.connect(self.change_cooldown) # Connect cooldown slider
        
        self.yolo_thread.frame_ready.connect(self.update_frame)
        self.yolo_thread.detection_ready.connect(self.update_detections)
        
    def start_detection(self):
        self.yolo_thread.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.model_combo.setEnabled(False) # Disable model combo
        self.webcam_combo.setEnabled(False) # Disable webcam combo
        self.threshold_slider.setEnabled(False) # Disable threshold slider
        self.cooldown_slider.setEnabled(False) # Disable cooldown slider
        
    def stop_detection(self):
        self.yolo_thread.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.model_combo.setEnabled(True) # Enable model combo
        self.webcam_combo.setEnabled(True) # Enable webcam combo
        self.threshold_slider.setEnabled(True) # Enable threshold slider
        self.cooldown_slider.setEnabled(True) # Enable cooldown slider
        self.video_label.clear()
        self.video_label.setText("Webcam Livestream\nwith YOLO Detection")
        
    def change_webcam(self, index):
        self.yolo_thread.set_webcam(index)
        
    def change_threshold(self, value):
        self.yolo_thread.set_confidence_threshold(value)
        
    def change_cooldown(self, value):
        self.detection_widget.cooldown_seconds = value / 10.0 # Update cooldown in DetectionWidget
        
    def update_frame(self, frame):
        # Convert frame to QImage and display
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        # Scale image to fit label while maintaining aspect ratio
        pixmap = QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.video_label.setPixmap(scaled_pixmap)
        
    def update_detections(self, detections):
        for detection in detections:
            self.detection_widget.add_detection(detection)
            
    def closeEvent(self, event):
        self.yolo_thread.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    window = YOLOWebcamApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
