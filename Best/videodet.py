import sys
import cv2
from ultralytics import YOLO
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import os
import torch
import time

class ObjectDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO11 Object Detection (TensorRT)")
        self.setGeometry(100, 100, 1200, 800)
    
        # Check CUDA availability
        self.cuda_available = torch.cuda.is_available()
        if self.cuda_available:
            self.device = "cuda:0"
            device_name = torch.cuda.get_device_name(0)
        else:
            self.device = "cpu"
            device_name = "CPU"

        # Initialize variables
        self.cap = None
        self.video_path = None
        self.model = None
        self.is_detecting = False
        self.frame_times = []
        self.max_frame_times = 30
    
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Create control layout
        control_layout = QHBoxLayout()

        # Create video display label
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.video_label)

        # Create info labels
        self.info_label = QLabel("No model loaded")
        self.fps_label = QLabel("FPS: 0.0")
        control_layout.addWidget(self.info_label)
        control_layout.addWidget(self.fps_label)

        # Create model selection combo box
        self.model_combo = QComboBox()
        self.model_combo.addItems(["YOLOv11n", "YOLOv11s", "YOLOv11m", "YOLOv11l", "YOLOv11x"])
        control_layout.addWidget(QLabel("Model:"))
        control_layout.addWidget(self.model_combo)

        # Create file selection button
        self.file_button = QPushButton("Select Video")
        self.file_button.clicked.connect(self.select_file)
        control_layout.addWidget(self.file_button)

        # Create file path label
        self.file_label = QLabel("No file selected")
        control_layout.addWidget(self.file_label)

        # Add slider for video
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.slider_moved)
        control_layout.addWidget(self.slider)

        # Create control buttons
        self.start_button = QPushButton("Play")
        self.start_button.clicked.connect(self.start_detection)
        self.start_button.setEnabled(False)
        control_layout.addWidget(self.start_button)
        
        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        control_layout.addWidget(self.fullscreen_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_detection)
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button)

        layout.addLayout(control_layout)

        # Initialize timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        
        # Initialize status bar
        self.status_bar = self.statusBar()

        # Initialize model
        self.load_model()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText("Fullscreen")
            # Show all controls
            self.file_button.show()
            self.file_label.show()
            self.slider.show()
            self.start_button.show()
            self.stop_button.show()
            self.model_combo.show()
            self.fps_label.show()
            self.info_label.show()
            self.statusBar().show()
            # Reset video label size
            self.video_label.setAlignment(Qt.AlignCenter)
        else:
            self.showFullScreen()
            self.fullscreen_button.setText("Exit Fullscreen")
            # Hide all controls except fullscreen button
            self.file_button.hide()
            self.file_label.hide()
            self.slider.hide()
            self.start_button.hide()
            self.stop_button.hide()
            self.model_combo.hide()
            self.fps_label.hide()
            self.info_label.hide()
            self.statusBar().hide()
            # Maximize video label
            self.video_label.setGeometry(0, 0, self.width(), self.height())

    def mouseDoubleClickEvent(self, event):
        if self.video_label.underMouse():
            self.toggle_fullscreen()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        super().keyPressEvent(event)

    def slider_moved(self, position):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, position)

    def load_model(self):
        try:
            model_name = self.model_combo.currentText().lower()
            model_path = f"yolo11n.pt"  # Adjust path according to your model naming
            
            # Load model with TensorRT optimization
            self.model = YOLO(model_path)
            
            if self.cuda_available:
                # Export and load TensorRT model
                self.info_label.setText("Optimizing model for TensorRT... Please wait.")
                QApplication.processEvents()
                
                # Export to TensorRT
                try:
                    self.model.export(format='engine', device=self.device)
                    self.info_label.setText(f"Model loaded with TensorRT on {torch.cuda.get_device_name(0)}")
                except Exception as e:
                    self.info_label.setText(f"TensorRT export failed, using CUDA: {str(e)}")
                    self.model = self.model.to(self.device)
            else:
                self.info_label.setText("Model loaded on CPU (Warning: Performance will be limited)")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load model: {str(e)}")
            self.info_label.setText("Error loading model!")

    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*.*)"
        )
        
        if file_name:
            self.video_path = file_name
            self.file_label.setText(os.path.basename(file_name))
            self.start_button.setEnabled(True)
            
            # Initialize video capture to get video properties
            temp_cap = cv2.VideoCapture(self.video_path)
            self.total_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.slider.setRange(0, self.total_frames - 1)
            self.slider.setEnabled(True)
            temp_cap.release()

    def update_fps(self, frame_time):
        self.frame_times.append(frame_time)
        if len(self.frame_times) > self.max_frame_times:
            self.frame_times.pop(0)
        
        avg_frame_time = sum(self.frame_times) / len(self.frame_times)
        fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
        self.fps_label.setText(f"FPS: {fps:.1f}")

    def process_frame(self, frame):
        start_time = time.time()
        
        # Convert frame to RGB for YOLO
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Perform detection
        results = self.model(frame_rgb, verbose=False)
        
        # Draw detection results
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = f"{result.names[cls]} {conf:.2f}"
                
                # Draw rectangle and label
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Update FPS
        self.update_fps(time.time() - start_time)
        
        return frame

    def update_frame(self):
        if self.cap is None:
            return

        ret, frame = self.cap.read()
        if ret:
            try:
                current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.slider.setValue(current_frame)
                
                self.status_bar.showMessage(f"Frame: {current_frame}/{self.total_frames}")

                processed_frame = self.process_frame(frame)

                rgb_frame = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                scaled_image = qt_image.scaled(self.video_label.size(), 
                                            Qt.KeepAspectRatio, 
                                            Qt.SmoothTransformation)
                
                self.video_label.setPixmap(QPixmap.fromImage(scaled_image))
            except Exception as e:
                print(f"Error processing frame: {str(e)}")
                self.stop_detection()
        else:
            self.stop_detection()
    
    def start_detection(self):
        if self.video_path:
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                QMessageBox.critical(self, "Error", "Could not open video file!")
                return

            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.file_button.setEnabled(False)
            self.is_detecting = True
            self.timer.start(30)  # Update every 30ms
        
    def stop_detection(self):
        self.timer.stop()
        self.is_detecting = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.file_button.setEnabled(True)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_label.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isFullScreen():
            # In fullscreen, make video label take up entire window
            self.video_label.setGeometry(0, 0, self.width(), self.height())
            # Position fullscreen button in top-right corner
            button_width = 100
            button_height = 30
            self.fullscreen_button.setGeometry(
                self.width() - button_width - 10,
                10,
                button_width,
                button_height
            )
        else:
            # Reset video label to normal layout
            if hasattr(self, 'video_label') and self.video_label.pixmap() and not self.video_label.pixmap().isNull():
                current_pixmap = self.video_label.pixmap()
                scaled_pixmap = current_pixmap.scaled(
                    self.video_label.size(), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                self.video_label.setPixmap(scaled_pixmap)

    def closeEvent(self, event):
        self.stop_detection()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set fusion style for better looking interface
    app.setStyle("Fusion")
    
    # Set dark palette
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
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
    
    window = ObjectDetectionApp()
    window.show()
    sys.exit(app.exec_())