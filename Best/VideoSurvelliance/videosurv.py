import sys
import cv2
import numpy as np
import time
import datetime
import os
from threading import Thread, Lock
from queue import Queue
import multiprocessing as mp
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QHBoxLayout, QWidget, QPushButton, QCheckBox, QComboBox,
                             QGridLayout, QScrollArea)
from PyQt6.QtGui import QImage, QPixmap, QFont
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

class ToggleButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.updateStyle()
        self.clicked.connect(self.updateStyle)
        
    def updateStyle(self):
        if self.isChecked():
            self.setStyleSheet("background-color: #4CD964; color: white; padding: 5px;")
        else:
            self.setStyleSheet("background-color: #E74C3C; color: white; padding: 5px;")
            
    def isActive(self):
        return self.isChecked()

class SensitivityButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("Sensitivity: Medium", parent)
        self.current_level = 1  # 0=Low, 1=Medium, 2=High
        self.levels = ["Low", "Medium", "High"]
        self.thresholds = [10000, 5000, 2000]  # Corresponding thresholds
        self.colors = ["#4B8BF5", "#FFD700", "#FF3B30"]  # Blue, Yellow, Red
        self.clicked.connect(self.cycle_level)
        self.updateStyle()
        
    def cycle_level(self):
        self.current_level = (self.current_level + 1) % 3
        self.updateStyle()
        
    def updateStyle(self):
        level_name = self.levels[self.current_level]
        color = self.colors[self.current_level]
        self.setText(f"Sensitivity: {level_name}")
        self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")
        
    def get_threshold(self):
        return self.thresholds[self.current_level]
    
    def get_level(self):
        return self.current_level

class CountdownButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("Countdown: 30s", parent)
        self.countdown = 30
        self.flash_timer = QTimer()
        self.flash_timer.setInterval(500)  # 500ms flash rate
        self.flash_timer.timeout.connect(self.toggle_flash)
        self.flash_count = 0
        self.max_flashes = 6  # 3 seconds total (6 * 500ms)
        self.flash_message = ""
        self.is_flashing = False
        self.normal_style = "background-color: #4B4B4B; color: white; padding: 5px; border-radius: 3px;"
        self.setStyleSheet(self.normal_style)
        self.setMinimumWidth(150)
        
    def update_countdown(self, seconds):
        if not self.is_flashing:
            self.countdown = seconds
            self.setText(f"Countdown: {seconds}s")
            # Color gradient from green to red as countdown decreases
            if seconds > 20:
                color = "#4CD964"  # Green
            elif seconds > 10:
                color = "#FFD700"  # Yellow
            else:
                color = "#FF3B30"  # Red
                
            self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")
    
    def flash_notification(self, message):
        # Cancel any current flashing
        if self.flash_timer.isActive():
            self.flash_timer.stop()
        
        self.flash_message = message
        self.flash_count = 0
        self.is_flashing = True
        self.toggle_flash()  # Start with showing the message
        self.flash_timer.start()
    
    def toggle_flash(self):
        self.flash_count += 1
        
        if self.flash_count > self.max_flashes:
            # Stop flashing and revert to countdown
            self.flash_timer.stop()
            self.is_flashing = False
            self.update_countdown(self.countdown)
            return
        
        if self.flash_count % 2 == 1:
            # Show notification
            self.setText(self.flash_message)
            if "Motion" in self.flash_message:
                self.setStyleSheet("background-color: #36A8E0; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")  # Blue for motion
            else:
                self.setStyleSheet("background-color: #FF9500; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")  # Orange for face
        else:
            # Show countdown in between flashes
            self.setText(f"Countdown: {self.countdown}s")
            if self.countdown > 20:
                color = "#4CD964"  # Green
            elif self.countdown > 10:
                color = "#FFD700"  # Yellow
            else:
                color = "#FF3B30"  # Red
            self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")

# Define process-safe detection functions for multiprocessing
def detect_motion_process(frame_queue, result_queue, threshold_value, running_flag):
    prev_frame = None
    
    while running_flag.value:
        try:
            if not frame_queue.empty():
                frame_data = frame_queue.get(timeout=0.1)
                if frame_data is None:
                    continue
                    
                camera_id, frame = frame_data
                
                if prev_frame is None:
                    prev_frame = frame.copy()
                    continue
                
                # Motion detection logic
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
                
                # Calculate difference and threshold
                frame_diff = cv2.absdiff(frame_gray, prev_gray)
                _, thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)
                
                # Find contours
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Check for significant motion
                motion_detected = False
                contour_frame = frame.copy()
                for contour in contours:
                    if cv2.contourArea(contour) > threshold_value.value:
                        cv2.drawContours(contour_frame, [contour], 0, (0, 255, 0), 2)
                        motion_detected = True
                
                # If motion detected, send result
                if motion_detected:
                    result_queue.put((camera_id, "motion", contour_frame))
                
                prev_frame = frame.copy()
            else:
                time.sleep(0.01)
        except Exception as e:
            print(f"Motion detection process error: {e}")
            time.sleep(0.1)

def detect_faces_process(frame_queue, result_queue, running_flag):
    # Load face cascade classifier
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    
    while running_flag.value:
        try:
            if not frame_queue.empty():
                frame_data = frame_queue.get(timeout=0.1)
                if frame_data is None:
                    continue
                    
                camera_id, frame = frame_data
                
                # Face detection logic
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(frame_gray, 1.3, 5)
                
                # If faces detected, draw rectangles and send result
                if len(faces) > 0:
                    face_frame = frame.copy()
                    for (x, y, w, h) in faces:
                        cv2.rectangle(face_frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                    result_queue.put((camera_id, "face", face_frame))
            else:
                time.sleep(0.01)
        except Exception as e:
            print(f"Face detection process error: {e}")
            time.sleep(0.1)

class FrameProcessor(QObject):
    motion_detected = pyqtSignal(int)
    face_detected = pyqtSignal(int)
    processed_frame = pyqtSignal(np.ndarray, int)
    
    def __init__(self, camera_id):
        super().__init__()
        self.camera_id = camera_id
        self.running = False
        self.lock = Lock()
        self.detect_motion = True
        self.detect_faces = True
        self.motion_threshold = mp.Value('i', 5000)  # Shared value for multiprocessing
        
        # Multiprocessing queues
        self.motion_frame_queue = mp.Queue(maxsize=5)
        self.face_frame_queue = mp.Queue(maxsize=5)
        self.result_queue = mp.Queue(maxsize=10)
        
        # Running flags for processes
        self.running_flag = mp.Value('i', 0)
        
        # Result processing timer
        self.result_timer = QTimer()
        self.result_timer.setInterval(30)  # Check for results 30 times per second
        self.result_timer.timeout.connect(self.process_results)
        
        # Frame cache for visualization
        self.latest_frame = None
        
    def start(self):
        self.running = True
        self.running_flag.value = 1
        
        # Start the motion detection process
        self.motion_process = mp.Process(
            target=detect_motion_process,
            args=(self.motion_frame_queue, self.result_queue, self.motion_threshold, self.running_flag)
        )
        self.motion_process.daemon = True
        self.motion_process.start()
        
        # Start the face detection process
        self.face_process = mp.Process(
            target=detect_faces_process,
            args=(self.face_frame_queue, self.result_queue, self.running_flag)
        )
        self.face_process.daemon = True
        self.face_process.start()
        
        # Start result processing timer
        self.result_timer.start()
        
    def stop(self):
        self.running = False
        self.running_flag.value = 0
        self.result_timer.stop()
        
        # Give processes time to clean up
        time.sleep(0.2)
        
        # Force terminate if necessary
        if self.motion_process.is_alive():
            self.motion_process.terminate()
        
        if self.face_process.is_alive():
            self.face_process.terminate()
    
    def add_frame(self, frame):
        if not self.running:
            return
            
        # Store latest frame for display
        self.latest_frame = frame.copy()
        
        # Send to processing queues if needed
        if self.detect_motion:
            # Use lower resolution for motion detection to improve performance
            small_frame = cv2.resize(frame, (320, 240))
            if not self.motion_frame_queue.full():
                self.motion_frame_queue.put((self.camera_id, small_frame))
        
        if self.detect_faces:
            # Use lower resolution for face detection to improve performance
            small_frame = cv2.resize(frame, (320, 240))
            if not self.face_frame_queue.full():
                self.face_frame_queue.put((self.camera_id, small_frame))
        
        # Always emit the latest frame for display
        self.processed_frame.emit(self.latest_frame, self.camera_id)
    
    def process_results(self):
        try:
            # Process all available results
            while not self.result_queue.empty():
                camera_id, detection_type, processed_frame = self.result_queue.get_nowait()
                
                # Skip if this isn't our camera
                if camera_id != self.camera_id:
                    continue
                
                # Scale the processed frame back to original size
                if processed_frame.shape[:2] != (480, 640):
                    processed_frame = cv2.resize(processed_frame, (640, 480))
                
                # Update the latest frame with detection markings
                self.latest_frame = processed_frame
                
                # Emit the processed frame
                self.processed_frame.emit(self.latest_frame, self.camera_id)
                
                # Emit detection signals
                if detection_type == "motion" and self.detect_motion:
                    self.motion_detected.emit(self.camera_id)
                elif detection_type == "face" and self.detect_faces:
                    self.face_detected.emit(self.camera_id)
                
        except Exception as e:
            print(f"Error processing detection results: {e}")
    
    def set_motion_detection(self, enabled):
        with self.lock:
            self.detect_motion = enabled
    
    def set_face_detection(self, enabled):
        with self.lock:
            self.detect_faces = enabled
    
    def set_motion_threshold(self, value):
        with self.lock:
            self.motion_threshold.value = value

class CameraThread(QObject):
    frame_ready = pyqtSignal(np.ndarray, int)
    camera_error = pyqtSignal(int, str)
    
    def __init__(self, camera_id=0):
        super().__init__()
        self.camera_id = camera_id
        self.running = False
        self.lock = Lock()
        self.cap = None
        self.preview_width = 640
        self.preview_height = 480
        self.recording_width = 1280
        self.recording_height = 720
        self.low_res_frame = None
        self.hi_res_frame = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        
    def start(self):
        self.running = True
        self.thread = Thread(target=self.update)
        self.thread.daemon = True
        self.thread.start()
        
    def stop(self):
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
    
    def update(self):
        while self.running:
            try:
                # Try to open the camera if not already open
                if self.cap is None or not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.camera_id)
                    
                    # Try to set high resolution for recording
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.recording_width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.recording_height)
                    
                    # Check if camera opened successfully
                    if not self.cap.isOpened():
                        self.reconnect_attempts += 1
                        if self.reconnect_attempts >= self.max_reconnect_attempts:
                            self.camera_error.emit(self.camera_id, "Failed to open camera after multiple attempts")
                            self.running = False
                            return
                        time.sleep(1.0)  # Wait before retry
                        continue
                    
                    # Reset reconnect counter on successful connection
                    self.reconnect_attempts = 0
                
                # Read frame
                ret, frame = self.cap.read()
                if not ret:
                    print(f"Failed to grab frame from camera {self.camera_id}")
                    # Try to reconnect
                    self.cap.release()
                    self.cap = None
                    time.sleep(0.5)
                    continue
                
                # Store both high-res and low-res versions
                with self.lock:
                    self.hi_res_frame = frame.copy()
                    self.low_res_frame = cv2.resize(frame, (self.preview_width, self.preview_height))
                
                # Send low-res frame for preview
                self.frame_ready.emit(self.low_res_frame, self.camera_id)
                
                # Control frame rate to reduce CPU usage
                time.sleep(0.033)  # ~30 FPS
                
            except Exception as e:
                print(f"Error in camera thread {self.camera_id}: {e}")
                self.camera_error.emit(self.camera_id, str(e))
                time.sleep(1.0)  # Wait before retry
    
    def get_hi_res_frame(self):
        with self.lock:
            if self.hi_res_frame is not None:
                return self.hi_res_frame.copy()
        return None

class VideoRecorder(QObject):
    recording_started = pyqtSignal(int)
    recording_stopped = pyqtSignal(int)
    recording_stats_updated = pyqtSignal(int, int, int)  # camera_id, total_time, countdown
    
    def __init__(self, camera_id, duration=30):
        super().__init__()
        self.camera_id = camera_id
        self.duration = duration
        self.recording = False
        self.out = None
        self.start_time = 0
        self.total_recording_time = 0
        self.countdown_time = duration
        self.last_reset_time = 0
        self.lock = Lock()
        self.frame_queue = Queue(maxsize=100)
        self.thread = None
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.setInterval(1000)  # Update every second
        
        # Create output directory if it doesn't exist
        os.makedirs('recordings', exist_ok=True)
    
    def start_recording(self):
        with self.lock:
            if not self.recording:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"recordings/cam{self.camera_id}_{timestamp}.avi"
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                self.out = cv2.VideoWriter(filename, fourcc, 20.0, (1280, 720))
                self.recording = True
                self.start_time = time.time()
                self.last_reset_time = time.time()
                self.countdown_time = self.duration
                
                # Start recording thread
                if self.thread is None or not self.thread.is_alive():
                    self.thread = Thread(target=self.recording_thread)
                    self.thread.daemon = True
                    self.thread.start()
                
                # Start the stats timer
                self.stats_timer.start()
                
                self.recording_started.emit(self.camera_id)
                print(f"Started recording camera {self.camera_id} to {filename}")
    
    def add_frame(self, frame):
        if self.recording:
            if not self.frame_queue.full():
                self.frame_queue.put(frame)
    
    def reset_countdown(self):
        with self.lock:
            if self.recording:
                self.last_reset_time = time.time()
                self.countdown_time = self.duration
    
    def update_stats(self):
        if self.recording:
            # Calculate total recording time
            current_time = time.time()
            total_time = int(current_time - self.start_time)
            
            # Calculate countdown
            time_since_reset = int(current_time - self.last_reset_time)
            countdown = max(0, self.duration - time_since_reset)
            self.countdown_time = countdown
            
            # Emit the updated stats
            self.recording_stats_updated.emit(self.camera_id, total_time, countdown)
            
            # If countdown reaches zero, stop recording
            if countdown <= 0:
                self.stop_recording()
    
    def recording_thread(self):
        while self.recording:
            try:
                if not self.frame_queue.empty():
                    frame = self.frame_queue.get(timeout=0.1)
                    with self.lock:
                        if self.recording and self.out is not None:
                            # Ensure frame is at recording resolution
                            if frame.shape[:2] != (720, 1280):
                                frame_resized = cv2.resize(frame, (1280, 720))
                            else:
                                frame_resized = frame
                            self.out.write(frame_resized)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"Error in recording thread: {e}")
                time.sleep(0.1)
    
    def stop_recording(self):
        with self.lock:
            if self.recording:
                self.recording = False
                self.stats_timer.stop()
                if self.out is not None:
                    self.out.release()
                    self.out = None
                self.recording_stopped.emit(self.camera_id)
                print(f"Stopped recording camera {self.camera_id}")

class SurveillanceApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Video Surveillance System")
        self.setGeometry(100, 100, 1300, 700)
        self.setStyleSheet("background-color: #2D2D30; color: white;")
        
        # Detect available cameras
        self.available_cameras = self.detect_cameras()
        print(f"Found {len(self.available_cameras)} cameras")
        
        # Create the cameras, processors and recorders
        self.cameras = []
        self.processors = []
        self.recorders = []
        self.record_buttons = []
        self.countdown_buttons = []
        self.sensitivity_button = None
        
        for camera_id in self.available_cameras:
            # Camera thread
            camera = CameraThread(camera_id=camera_id)
            camera.frame_ready.connect(self.on_frame_ready)
            camera.camera_error.connect(self.on_camera_error)
            self.cameras.append(camera)
            
            # Frame processor
            processor = FrameProcessor(camera_id=camera_id)
            processor.motion_detected.connect(lambda cam_id=camera_id: self.on_detection(cam_id, "motion"))
            processor.face_detected.connect(lambda cam_id=camera_id: self.on_detection(cam_id, "face"))
            processor.processed_frame.connect(self.update_frame)
            self.processors.append(processor)
            
            # Video recorder
            recorder = VideoRecorder(camera_id=camera_id)
            recorder.recording_started.connect(lambda cam=camera_id: self.on_recording_started(cam))
            recorder.recording_stopped.connect(lambda cam=camera_id: self.on_recording_stopped(cam))
            recorder.recording_stats_updated.connect(self.update_recording_stats)
            self.recorders.append(recorder)
        
        # Create the UI
        self.init_ui()
        
        # Start the cameras and processors
        for i in range(len(self.cameras)):
            self.cameras[i].start()
            self.processors[i].start()
    
    def detect_cameras(self):
        available_cameras = []
        max_to_check = 8  # Check cameras 0-7
        
        for i in range(max_to_check):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available_cameras.append(i)
                cap.release()
        
        # If no cameras found, at least add index 0
        if not available_cameras:
            available_cameras = [0]
            
        return available_cameras
    
    def on_frame_ready(self, frame, camera_id):
        # Find the index for this camera_id
        try:
            index = self.available_cameras.index(camera_id)
            # Send preview frame to processor
            self.processors[index].add_frame(frame)
            # Send high-res frame to recorder if recording
            if self.recorders[index].recording:
                hi_res_frame = self.cameras[index].get_hi_res_frame()
                if hi_res_frame is not None:
                    self.recorders[index].add_frame(hi_res_frame)
        except ValueError:
            # Camera ID not found in our list
            pass
    
    def on_camera_error(self, camera_id, error_message):
        try:
            index = self.available_cameras.index(camera_id)
            print(f"Camera {camera_id} error: {error_message}")
            # Update UI to show error
            if index < len(self.camera_labels):
                error_pixmap = QPixmap(640, 480)
                error_pixmap.fill(Qt.GlobalColor.black)
                self.camera_labels[index].setPixmap(error_pixmap)
                # Create error message overlay
                self.camera_labels[index].setText(f"Camera {camera_id} Error: {error_message}")
                self.camera_labels[index].setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.camera_labels[index].setStyleSheet("color: #FF3B30; background-color: rgba(0,0,0,0.7); font-weight: bold;")
        except ValueError:
            pass
    
    def on_detection(self, camera_id, detection_type):
        try:
            index = self.available_cameras.index(camera_id)
            # Flash notification on countdown button
            message = f"{detection_type.capitalize()} Detected!"
            self.countdown_buttons[index].flash_notification(message)
            
            # Start recording if not already recording or reset countdown if already recording
            if not self.recorders[index].recording:
                QTimer.singleShot(0, lambda: self.recorders[index].start_recording())
            else:
                self.recorders[index].reset_countdown()
        except ValueError:
            pass
    
    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Create scrollable area for camera grid
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        
        # Calculate grid layout dimensions
        num_cameras = len(self.available_cameras)
        cols = min(3, num_cameras)  # Maximum 3 cameras per row
        rows = (num_cameras + cols - 1) // cols  # Ceiling division
        
        # Camera grid
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        self.camera_labels = []
        self.info_labels = []
        self.motion_buttons = []
        self.face_buttons = []
        
        for i, camera_id in enumerate(self.available_cameras):
            row = i // cols
            col = i % cols
            
            camera_widget = QWidget()
            camera_widget.setStyleSheet("background-color: #1E1E1E; border-radius: 10px;")
            camera_layout_single = QVBoxLayout()
            
            # Camera header with info
            info_layout = QHBoxLayout()
            
            camera_title = QLabel(f"Camera {camera_id}")
            camera_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            
            recording_info = QLabel("Record: 0s | Countdown: 30s")
            recording_info.setStyleSheet("color: #CCCCCC;")
            self.info_labels.append(recording_info)
            
            info_layout.addWidget(camera_title)
            info_layout.addStretch()
            info_layout.addWidget(recording_info)
            
            # Camera view
            label = QLabel()
            label.setFixedSize(480, 360)  # Smaller size for better performance with multiple cameras
            label.setStyleSheet("border: 2px solid #3E3E42; border-radius: 5px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.camera_labels.append(label)
            
            # Camera controls
            controls_layout = QHBoxLayout()
            
            # Motion detection button
            motion_button = ToggleButton("Motion")
            motion_button.clicked.connect(lambda checked, cam_id=camera_id: 
                                          self.toggle_motion_detection(checked, self.available_cameras.index(cam_id)))
            self.motion_buttons.append(motion_button)
            
            # Face detection button
            face_button = ToggleButton("Face")
            face_button.clicked.connect(lambda checked, cam_id=camera_id: 
                                       self.toggle_face_detection(checked, self.available_cameras.index(cam_id)))
            self.face_buttons.append(face_button)
            
            # Record button
            record_button = QPushButton("Record")
            record_button.setStyleSheet("background-color: #888888; color: white; padding: 5px;")
            record_button.clicked.connect(lambda _, cam_id=camera_id: 
                                         self.toggle_recording(self.available_cameras.index(cam_id)))
            self.record_buttons.append(record_button)
            
            # Countdown button
            countdown_button = CountdownButton()
            countdown_button.clicked.connect(lambda _, cam_id=camera_id: 
                                            self.toggle_recording(self.available_cameras.index(cam_id)))
            self.countdown_buttons.append(countdown_button)
            
            controls_layout.addWidget(motion_button)
            controls_layout.addWidget(face_button)
            controls_layout.addWidget(record_button)
            controls_layout.addWidget(countdown_button)
            
            camera_layout_single.addLayout(info_layout)
            camera_layout_single.addWidget(label)
            camera_layout_single.addLayout(controls_layout)
            
            camera_widget.setLayout(camera_layout_single)
            grid_layout.addWidget(camera_widget, row, col)
        
        scroll_content.setLayout(grid_layout)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # Global controls
        global_controls = QHBoxLayout()
        
        # Create sensitivity button to replace dropdown
        sensitivity_label = QLabel("Motion Sensitivity:")
        self.sensitivity_button = SensitivityButton()
        self.sensitivity_button.clicked.connect(self.change_sensitivity)
        
        # Status label
        self.status_label = QLabel(f"Monitoring {len(self.available_cameras)} cameras")
        
        exit_button = QPushButton("Exit")
        exit_button.setStyleSheet("background-color: #E74C3C; color: white; padding: 8px;")
        exit_button.clicked.connect(self.close)
        
        global_controls.addWidget(sensitivity_label)
        global_controls.addWidget(self.sensitivity_button)
        global_controls.addStretch()
        global_controls.addWidget(self.status_label)
        global_controls.addStretch()
        global_controls.addWidget(exit_button)
        
        main_layout.addLayout(global_controls)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def update_frame(self, frame, camera_id):
        try:
            index = self.available_cameras.index(camera_id)
            if 0 <= index < len(self.camera_labels):
                # Convert frame to QImage for display
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # Scale to fit the label
                pixmap = QPixmap.fromImage(q_img)
                label = self.camera_labels[index]
                pixmap = pixmap.scaled(label.width(), label.height(), Qt.AspectRatioMode.KeepAspectRatio)
                label.setPixmap(pixmap)
        except ValueError:
            pass
    
    def update_recording_stats(self, camera_id, total_seconds, countdown):
        try:
            index = self.available_cameras.index(camera_id)
            if 0 <= index < len(self.info_labels):
                # Format time as minutes:seconds
                total_time = f"{total_seconds // 60}:{total_seconds % 60:02d}"
                self.info_labels[index].setText(f"Record: {total_time} | Countdown: {countdown}s")
                
                # Update the record button text and color
                if self.recorders[index].recording:
                    self.record_buttons[index].setText(f"Recording: {total_time}")
                
                # Update the countdown button
                self.countdown_buttons[index].update_countdown(countdown)
        except ValueError:
            pass
    
    def on_recording_started(self, camera_id):
        try:
            index = self.available_cameras.index(camera_id)
            if 0 <= index < len(self.record_buttons):
                # Update button appearance
                self.record_buttons[index].setStyleSheet("background-color: #FFD700; color: black; padding: 5px; font-weight: bold;")
                self.record_buttons[index].setText("Recording: 0:00")
                self.countdown_buttons[index].update_countdown(30)
        except ValueError:
            pass
    
    def on_recording_stopped(self, camera_id):
        try:
            index = self.available_cameras.index(camera_id)
            if 0 <= index < len(self.record_buttons):
                # Reset button appearance
                self.record_buttons[index].setStyleSheet("background-color: #888888; color: white; padding: 5px;")
                self.record_buttons[index].setText("Record")
                self.countdown_buttons[index].update_countdown(30)
        except ValueError:
            pass
    
    def toggle_recording(self, index):
        if 0 <= index < len(self.recorders):
            if self.recorders[index].recording:
                self.recorders[index].stop_recording()
            else:
                self.recorders[index].start_recording()
    
    def toggle_motion_detection(self, checked, index):
        if 0 <= index < len(self.processors):
            self.processors[index].set_motion_detection(checked)
            if checked:
                self.countdown_buttons[index].flash_notification("Motion Detection On")
            else:
                self.countdown_buttons[index].flash_notification("Motion Detection Off")
    
    def toggle_face_detection(self, checked, index):
        if 0 <= index < len(self.processors):
            self.processors[index].set_face_detection(checked)
            if checked:
                self.countdown_buttons[index].flash_notification("Face Detection On")
            else:
                self.countdown_buttons[index].flash_notification("Face Detection Off")
    
    def change_sensitivity(self):
        # Get threshold from the sensitivity button
        threshold = self.sensitivity_button.get_threshold()
        level_name = self.sensitivity_button.levels[self.sensitivity_button.get_level()]
        
        # Apply threshold to all processors
        for processor in self.processors:
            processor.set_motion_threshold(threshold)
        
        # Flash a notification on all countdown buttons
        for button in self.countdown_buttons:
            button.flash_notification(f"Sensitivity: {level_name}")
    
    def closeEvent(self, event):
        # Stop cameras, processors and recorders when closing the app
        for camera in self.cameras:
            camera.stop()
        for processor in self.processors:
            processor.stop()
        for recorder in self.recorders:
            recorder.stop_recording()
            
        # Wait for all processes to clean up
        time.sleep(0.5)
        event.accept()

if __name__ == "__main__":
    # Enable multiprocessing support for PyQt
    mp.set_start_method('spawn', force=True)
    
    app = QApplication(sys.argv)
    surveillance_app = SurveillanceApp()
    surveillance_app.show()
    sys.exit(app.exec())