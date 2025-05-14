# --- START OF FILE videosurv_v2.py ---

import sys
import cv2
import numpy as np
import time
import datetime
import os
import traceback
import json  # Using json for simple settings persistence alternative
from threading import Thread, Lock
from queue import Queue, Empty
import multiprocessing as mp
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QHBoxLayout, QWidget, QPushButton, QCheckBox, QComboBox,
                             QGridLayout, QScrollArea, QDialog, QFormLayout,
                             QSpinBox, QLineEdit, QFileDialog, QDialogButtonBox, QMessageBox)
from PyQt6.QtGui import QImage, QPixmap, QFont
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSettings

# --- Constants ---
CONFIG_FILE = "videosurv_settings.json"
DEFAULT_SETTINGS = {
    "recording_duration": 30,
    "recording_dir": "recordings",
    "recording_codec": "XVID",
    "recording_resolution": "1280x720",
    "preview_resolution": "640x480",
    "sensitivity_thresholds": [10000, 5000, 2000], # Low, Medium, High
    "available_codecs": ["XVID", "MJPG", "MP4V", "DIVX"],
    "available_resolutions": ["640x480", "800x600", "1280x720", "1920x1080"]
}

# --- Utility Functions ---
def parse_resolution(res_str):
    """Parses 'WxH' string into (width, height) tuple."""
    try:
        w, h = map(int, res_str.split('x'))
        return w, h
    except ValueError:
        print(f"Warning: Invalid resolution format '{res_str}'. Using default.")
        return 640, 480 # Default fallback

def load_settings():
    """Loads settings from JSON file or returns defaults."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = json.load(f)
                # Ensure all keys exist, merge with defaults
                settings = DEFAULT_SETTINGS.copy()
                settings.update(loaded)
                # Basic validation (could be more robust)
                if not isinstance(settings.get("sensitivity_thresholds"), list) or len(settings.get("sensitivity_thresholds")) != 3:
                    settings["sensitivity_thresholds"] = DEFAULT_SETTINGS["sensitivity_thresholds"]
                return settings
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Error loading settings file '{CONFIG_FILE}': {e}. Using defaults.")
            return DEFAULT_SETTINGS.copy()
    else:
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Saves settings to JSON file."""
    try:
        # Don't save dynamic lists fetched from defaults
        settings_to_save = settings.copy()
        settings_to_save.pop("available_codecs", None)
        settings_to_save.pop("available_resolutions", None)
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings_to_save, f, indent=4)
    except IOError as e:
        print(f"Error saving settings file '{CONFIG_FILE}': {e}")

# --- Custom Widgets ---

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

class SensitivityButton(QPushButton):
    def __init__(self, thresholds, parent=None):
        super().__init__("Sensitivity: Medium", parent)
        self.levels = ["Low", "Medium", "High"]
        self.current_level = 1 # Default to Medium, initialize this BEFORE calling update_thresholds
        self.colors = ["#4B8BF5", "#FFD700", "#FF3B30"]  # Blue, Yellow, Red
        self.update_thresholds(thresholds) # Initial thresholds
        self.clicked.connect(self.cycle_level)
        self.updateStyle()
        
    def cycle_level(self):
        self.current_level = (self.current_level + 1) % len(self.levels)
        self.updateStyle()
        
    def updateStyle(self):
        level_name = self.levels[self.current_level]
        color = self.colors[self.current_level]
        self.setText(f"Sensitivity: {level_name}")
        self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")
        
    def get_threshold(self):
        try:
            return self.thresholds[self.current_level]
        except IndexError:
            print("Warning: Sensitivity level out of sync with thresholds. Using medium.")
            return self.thresholds[1] if len(self.thresholds) > 1 else 5000
    
    def get_level(self):
        return self.current_level

    def update_thresholds(self, thresholds):
        """Allows updating thresholds from settings."""
        if isinstance(thresholds, list) and len(thresholds) == 3:
             # Ensure thresholds are in descending order (Low=High val, High=Low val)
            self.thresholds = sorted(thresholds, reverse=True)
        else:
            print("Warning: Invalid thresholds provided to SensitivityButton. Using defaults.")
            self.thresholds = sorted(DEFAULT_SETTINGS["sensitivity_thresholds"], reverse=True)
        # Ensure current_level is valid after update
        self.current_level = min(self.current_level, len(self.levels) - 1)
        self.updateStyle()


class CountdownButton(QPushButton):
    def __init__(self, initial_duration=30, parent=None):
        super().__init__(f"Countdown: {initial_duration}s", parent)
        self.initial_duration = initial_duration
        self.countdown = initial_duration
        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(500)
        self.flash_timer.timeout.connect(self.toggle_flash)
        self.flash_count = 0
        self.max_flashes = 6
        self.flash_message = ""
        self.is_flashing = False
        self.normal_style = "background-color: #4B4B4B; color: white; padding: 5px; border-radius: 3px;"
        self.setMinimumWidth(150)
        self._update_countdown_style(initial_duration) # Initial style

    def update_duration(self, new_duration):
        """Update the base duration for the countdown."""
        self.initial_duration = new_duration
        if not self.is_flashing and self.countdown == self.initial_duration: # Only update if not actively counting down/flashing
             self._update_countdown_style(new_duration)

    def update_countdown(self, seconds):
        """Update display during countdown."""
        if not self.is_flashing:
            self.countdown = seconds
            self._update_countdown_style(seconds)

    def _update_countdown_style(self, seconds):
        """Internal method to set text and style based on seconds."""
        self.setText(f"Countdown: {seconds}s")
        total_duration = self.initial_duration # Use initial duration for color scale
        if seconds > total_duration * 0.66: color = "#4CD964"  # Green
        elif seconds > total_duration * 0.33: color = "#FFD700"  # Yellow
        else: color = "#FF3B30" # Red
        self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")

    def flash_notification(self, message):
        if self.flash_timer.isActive():
            self.flash_timer.stop()
        
        self.flash_message = message
        self.flash_count = 0
        self.is_flashing = True
        self.toggle_flash()
        self.flash_timer.start()
    
    def toggle_flash(self):
        self.flash_count += 1
        
        if self.flash_count > self.max_flashes:
            self.flash_timer.stop()
            self.is_flashing = False
            self._update_countdown_style(self.countdown) # Revert to current countdown state
            return
        
        if self.flash_count % 2 == 1:
            # Show notification
            self.setText(self.flash_message)
            if "Motion" in self.flash_message: color = "#36A8E0" # Blue
            elif "Face" in self.flash_message: color = "#FF9500" # Orange
            elif "Sensitivity" in self.flash_message: color = "#9B59B6" # Purple
            else: color = "#E74C3C" # Red as default flash
            self.setStyleSheet(f"background-color: {color}; color: white; padding: 5px; border-radius: 3px; font-weight: bold;")
        else:
            # Show countdown in between flashes
            self._update_countdown_style(self.countdown)

# --- Settings Dialog ---
class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.settings = current_settings.copy() # Work on a copy
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        # Recording Duration
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 300) # 5 seconds to 5 minutes
        self.duration_spin.setValue(self.settings.get("recording_duration", 30))
        self.duration_spin.setSuffix(" seconds")
        layout.addRow("Recording Duration:", self.duration_spin)

        # Recording Directory
        dir_layout = QHBoxLayout()
        self.dir_edit = QLineEdit(self.settings.get("recording_dir", "recordings"))
        self.dir_button = QPushButton("Browse...")
        self.dir_button.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(self.dir_button)
        layout.addRow("Recording Directory:", dir_layout)

        # Recording Codec
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(self.settings.get("available_codecs", ["XVID"]))
        self.codec_combo.setCurrentText(self.settings.get("recording_codec", "XVID"))
        layout.addRow("Recording Codec:", self.codec_combo)

        # Recording Resolution
        self.rec_res_combo = QComboBox()
        self.rec_res_combo.addItems(self.settings.get("available_resolutions", ["1280x720"]))
        self.rec_res_combo.setCurrentText(self.settings.get("recording_resolution", "1280x720"))
        layout.addRow("Recording Resolution:", self.rec_res_combo)

        # Preview Resolution
        self.prev_res_combo = QComboBox()
        self.prev_res_combo.addItems(self.settings.get("available_resolutions", ["640x480"]))
        self.prev_res_combo.setCurrentText(self.settings.get("preview_resolution", "640x480"))
        layout.addRow("Preview Resolution:", self.prev_res_combo)
        # Note: Changing resolution might require camera restart

        # Sensitivity Thresholds
        thresh_layout = QHBoxLayout()
        self.low_thresh_spin = QSpinBox()
        self.low_thresh_spin.setRange(500, 50000)
        self.low_thresh_spin.setValue(self.settings.get("sensitivity_thresholds", [10000, 5000, 2000])[0])
        self.med_thresh_spin = QSpinBox()
        self.med_thresh_spin.setRange(500, 50000)
        self.med_thresh_spin.setValue(self.settings.get("sensitivity_thresholds", [10000, 5000, 2000])[1])
        self.high_thresh_spin = QSpinBox()
        self.high_thresh_spin.setRange(100, 20000) # High sensitivity = lower threshold
        self.high_thresh_spin.setValue(self.settings.get("sensitivity_thresholds", [10000, 5000, 2000])[2])
        thresh_layout.addWidget(QLabel("Low:"))
        thresh_layout.addWidget(self.low_thresh_spin)
        thresh_layout.addWidget(QLabel("Medium:"))
        thresh_layout.addWidget(self.med_thresh_spin)
        thresh_layout.addWidget(QLabel("High:"))
        thresh_layout.addWidget(self.high_thresh_spin)
        layout.addRow("Motion Thresholds:", thresh_layout)

        # Dialog Buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        layout.addRow(self.buttonBox)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Recording Directory", self.dir_edit.text())
        if directory:
            self.dir_edit.setText(directory)

    def get_settings(self):
        """Returns the updated settings dictionary."""
        updated_settings = self.settings.copy() # Start with original to keep codec/res lists
        updated_settings["recording_duration"] = self.duration_spin.value()
        updated_settings["recording_dir"] = self.dir_edit.text()
        updated_settings["recording_codec"] = self.codec_combo.currentText()
        updated_settings["recording_resolution"] = self.rec_res_combo.currentText()
        updated_settings["preview_resolution"] = self.prev_res_combo.currentText()
        updated_settings["sensitivity_thresholds"] = [
            self.low_thresh_spin.value(),
            self.med_thresh_spin.value(),
            self.high_thresh_spin.value()
        ]
        return updated_settings

# --- Worker Processes Functions (Modified for graceful shutdown) ---

def detect_motion_process(frame_queue, result_queue, threshold_value, stop_event):
    prev_frame_gray = None
    print(f"[MotionProc {os.getpid()}] Started")
    while not stop_event.is_set():
        try:
            frame_data = frame_queue.get(timeout=0.2) # Add timeout
            if frame_data is None: # Sentinel check
                print(f"[MotionProc {os.getpid()}] Sentinel received, exiting.")
                break 
                
            camera_id, frame = frame_data
            
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_gray = cv2.GaussianBlur(frame_gray, (21, 21), 0) # Added blur

            if prev_frame_gray is None:
                prev_frame_gray = frame_gray
                continue
            
            frame_delta = cv2.absdiff(prev_frame_gray, frame_gray)
            thresh = cv2.threshold(frame_delta, 30, 255, cv2.THRESH_BINARY)[1] # Slightly higher threshold on diff
            thresh = cv2.dilate(thresh, None, iterations=2)
            
            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            motion_detected = False
            contour_frame = frame.copy() # Work on copy for drawing
            current_threshold = threshold_value.value # Read shared value

            for contour in contours:
                if cv2.contourArea(contour) > current_threshold:
                    (x, y, w, h) = cv2.boundingRect(contour)
                    cv2.rectangle(contour_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    motion_detected = True
            
            if motion_detected:
                result_queue.put((camera_id, "motion", contour_frame))
            
            prev_frame_gray = frame_gray # Update previous frame

        except Empty:
            continue # Queue was empty, loop again
        except Exception as e:
            print(f"[MotionProc {os.getpid()}] Error: {e}")
            traceback.print_exc()
            time.sleep(0.1) # Avoid tight loop on error
    print(f"[MotionProc {os.getpid()}] Exited.")


def detect_faces_process(frame_queue, result_queue, stop_event):
    try:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if face_cascade.empty():
           raise IOError("Could not load face cascade classifier!")
        print(f"[FaceProc {os.getpid()}] Started")
    except Exception as e:
        print(f"[FaceProc {os.getpid()}] Initialization Error: {e}")
        stop_event.set() # Signal process cannot run

    while not stop_event.is_set():
        try:
            frame_data = frame_queue.get(timeout=0.2) # Add timeout
            if frame_data is None: # Sentinel check
                print(f"[FaceProc {os.getpid()}] Sentinel received, exiting.")
                break
                
            camera_id, frame = frame_data
            
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Consider adding equalizeHist for varying lighting
            # frame_gray = cv2.equalizeHist(frame_gray) 
            
            # Adjust parameters for performance/accuracy trade-off
            faces = face_cascade.detectMultiScale(frame_gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)) 
            
            if len(faces) > 0:
                face_frame = frame.copy()
                for (x, y, w, h) in faces:
                    cv2.rectangle(face_frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                result_queue.put((camera_id, "face", face_frame))

        except Empty:
            continue # Queue was empty, loop again
        except Exception as e:
            print(f"[FaceProc {os.getpid()}] Error: {e}")
            traceback.print_exc()
            time.sleep(0.1) # Avoid tight loop on error
    print(f"[FaceProc {os.getpid()}] Exited.")

# --- Frame Processor (Modified for graceful shutdown) ---
class FrameProcessor(QObject):
    motion_detected = pyqtSignal(int, str)
    face_detected = pyqtSignal(int, str)
    processed_frame = pyqtSignal(np.ndarray, int)
    
    def __init__(self, camera_id, initial_thresholds, preview_width, preview_height):
        super().__init__()
        self.camera_id = camera_id
        self.preview_width = preview_width
        self.preview_height = preview_height
        self.running = False
        self.detect_motion = True
        self.detect_faces = True
        
        # Use the middle threshold (Medium) as the initial default
        initial_thresh_val = initial_thresholds[1] if len(initial_thresholds) == 3 else 5000
        self.motion_threshold = mp.Value('i', initial_thresh_val) 

        self.motion_frame_queue = mp.Queue(maxsize=5)
        self.face_frame_queue = mp.Queue(maxsize=5)
        self.result_queue = mp.Queue(maxsize=10)
        self.stop_event = mp.Event() # Use Event for signaling stop
        
        self.result_timer = QTimer(self)
        self.result_timer.setInterval(33) # ~30 FPS check
        self.result_timer.timeout.connect(self.process_results)
        
        self.latest_frame = None
        self.motion_process = None
        self.face_process = None
        
    def start(self):
        if self.running: return
        self.running = True
        self.stop_event.clear() # Ensure event is not set initially
        
        self.motion_process = mp.Process(
            target=detect_motion_process,
            args=(self.motion_frame_queue, self.result_queue, self.motion_threshold, self.stop_event),
            daemon=True
        )
        self.motion_process.start()
        
        self.face_process = mp.Process(
            target=detect_faces_process,
            args=(self.face_frame_queue, self.result_queue, self.stop_event),
            daemon=True
        )
        self.face_process.start()
        
        self.result_timer.start()
        print(f"Processor {self.camera_id}: Started processes.")
        
    def stop(self):
        if not self.running: return
        print(f"Processor {self.camera_id}: Stopping...")
        self.running = False
        self.result_timer.stop()
        self.stop_event.set() # Signal processes to stop

        # Send sentinel values to unblock queues
        try: self.motion_frame_queue.put_nowait(None)
        except Exception: pass
        try: self.face_frame_queue.put_nowait(None)
        except Exception: pass
        
        # Wait for processes to finish (with timeout)
        join_timeout = 2.0 # seconds
        if self.motion_process and self.motion_process.is_alive():
            print(f"Processor {self.camera_id}: Joining motion process...")
            self.motion_process.join(timeout=join_timeout)
            if self.motion_process.is_alive():
                print(f"Processor {self.camera_id}: Motion process did not join, terminating.")
                self.motion_process.terminate() # Force terminate if stuck
                self.motion_process.join() # Ensure termination completes
        
        if self.face_process and self.face_process.is_alive():
            print(f"Processor {self.camera_id}: Joining face process...")
            self.face_process.join(timeout=join_timeout)
            if self.face_process.is_alive():
                print(f"Processor {self.camera_id}: Face process did not join, terminating.")
                self.face_process.terminate()
                self.face_process.join()

        # Clear queues after stopping
        self._clear_queue(self.motion_frame_queue)
        self._clear_queue(self.face_frame_queue)
        self._clear_queue(self.result_queue)

        print(f"Processor {self.camera_id}: Stopped.")

    def _clear_queue(self, q):
        while not q.empty():
            try: q.get_nowait()
            except Empty: break
            except Exception as e: 
                print(f"Error clearing queue: {e}")
                break

    def add_frame(self, frame):
        if not self.running: return
            
        self.latest_frame = frame.copy() # Keep original for display
        
        # Use configured preview resolution for processing
        processing_frame = cv2.resize(frame, (self.preview_width, self.preview_height))
        
        if self.detect_motion:
            if not self.motion_frame_queue.full():
                self.motion_frame_queue.put((self.camera_id, processing_frame))
        
        if self.detect_faces:
            if not self.face_frame_queue.full():
                self.face_frame_queue.put((self.camera_id, processing_frame))
        
        # Always emit the latest raw frame for immediate display
        self.processed_frame.emit(self.latest_frame, self.camera_id)
    
    def process_results(self):
        try:
            while not self.result_queue.empty():
                result = self.result_queue.get_nowait()
                if result is None: continue # Skip potential None if queue cleared during stop

                camera_id, detection_type, processed_sub_frame = result
                
                if camera_id != self.camera_id: continue # Should not happen with separate queues per cam
                
                # Resize processed frame (with overlays) back to original preview size for merging
                # This assumes detection was done on preview_width/height
                display_frame_with_overlay = cv2.resize(processed_sub_frame, (self.latest_frame.shape[1], self.latest_frame.shape[0]))
                                
                # Update the latest frame with detection markings for display
                self.latest_frame = display_frame_with_overlay # Overwrite latest raw frame with processed one
                
                # Emit the frame with overlays
                self.processed_frame.emit(self.latest_frame, self.camera_id)
                
                # Emit detection signals
                if detection_type == "motion" and self.detect_motion:
                    self.motion_detected.emit(self.camera_id, "motion")
                elif detection_type == "face" and self.detect_faces:
                    self.face_detected.emit(self.camera_id, "face")
                
        except Empty:
            pass # No results available
        except Exception as e:
            print(f"Processor {self.camera_id}: Error processing results: {e}")
            traceback.print_exc()
    
    def set_motion_detection(self, enabled):
        self.detect_motion = enabled
    
    def set_face_detection(self, enabled):
        self.detect_faces = enabled
    
    def set_motion_threshold(self, value):
        if self.running: # Only update if process is running
            self.motion_threshold.value = value
        else: # Store it if process not running yet
             self.motion_threshold = mp.Value('i', value) # Recreate if needed

# --- Camera Thread (Uses configured resolutions) ---
class CameraThread(QObject):
    frame_ready = pyqtSignal(np.ndarray, int)
    camera_error = pyqtSignal(int, str)
    
    def __init__(self, camera_id, preview_res, recording_res):
        super().__init__()
        self.camera_id = camera_id
        self.running = False
        self.lock = Lock()
        self.cap = None
        
        self.preview_width, self.preview_height = preview_res
        self.recording_width, self.recording_height = recording_res
        
        self.current_frame = None # Only store one frame (the preview one)
        
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.thread = None
        
    def update_resolutions(self, preview_res, recording_res):
        """Update resolutions - requires camera restart."""
        with self.lock:
            self.preview_width, self.preview_height = preview_res
            self.recording_width, self.recording_height = recording_res
            # Force reconnect on next loop iteration
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            print(f"Camera {self.camera_id}: Resolutions updated. Will reconnect.")

    def start(self):
        if self.running: return
        self.running = True
        self.thread = Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
        print(f"Camera {self.camera_id}: Stopped.")
    
    def run(self):
        print(f"Camera {self.camera_id}: Thread started.")
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    print(f"Camera {self.camera_id}: Attempting to open...")
                    self.cap = cv2.VideoCapture(self.camera_id)
                    
                    if not self.cap.isOpened():
                        self.reconnect_attempts += 1
                        print(f"Camera {self.camera_id}: Failed to open (Attempt {self.reconnect_attempts}).")
                        if self.reconnect_attempts >= self.max_reconnect_attempts:
                            error_msg = "Failed to open camera after multiple attempts"
                            self.camera_error.emit(self.camera_id, error_msg)
                            self.running = False # Stop trying
                            break
                        time.sleep(2.0**self.reconnect_attempts) # Exponential backoff
                        continue
                    
                    # Set preferred resolutions (camera might ignore or choose closest)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.recording_width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.recording_height)
                    actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    print(f"Camera {self.camera_id}: Opened. Requested {self.recording_width}x{self.recording_height}, Got {actual_w}x{actual_h}")
                    self.reconnect_attempts = 0 # Reset on success
                
                ret, frame = self.cap.read()
                
                if not ret:
                    print(f"Camera {self.camera_id}: Failed to grab frame. Reconnecting...")
                    self.cap.release()
                    self.cap = None
                    time.sleep(1.0)
                    continue
                
                # Create preview frame by resizing
                preview_frame = cv2.resize(frame, (self.preview_width, self.preview_height))

                with self.lock:
                    self.current_frame = preview_frame.copy() # Store preview frame

                # Emit the preview frame immediately for display/processing
                self.frame_ready.emit(preview_frame, self.camera_id)
                
                time.sleep(0.01) # Small sleep to prevent excessive CPU usage if camera is fast
                
            except Exception as e:
                print(f"Camera {self.camera_id}: Error in run loop: {e}")
                traceback.print_exc()
                self.camera_error.emit(self.camera_id, str(e))
                # Attempt reconnect after error
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
                time.sleep(2.0) 
    
    def get_current_frame_for_recording(self, target_width, target_height):
        """Gets the latest frame and resizes for recording."""
        # This is problematic as it requires reading again or storing hi-res.
        # For simplicity, we'll use the stored preview frame and resize it up.
        # A better approach would store the original 'frame' from run loop.
        # Let's modify run to store the original frame.
        
        # Re-reading approach (might miss frames or cause delays):
        if self.cap and self.cap.isOpened():
             ret, frame = self.cap.read()
             if ret:
                 try:
                     return cv2.resize(frame, (target_width, target_height))
                 except Exception as e:
                     print(f"Camera {self.camera_id}: Error resizing frame for recording: {e}")
                     return None
        return None # Return None if camera not ready


# --- Video Recorder (Uses configured settings) ---
class VideoRecorder(QObject):
    recording_started = pyqtSignal(int)
    recording_stopped = pyqtSignal(int)
    recording_stats_updated = pyqtSignal(int, int, int) # camera_id, total_time, countdown
    
    def __init__(self, camera_id, settings):
        super().__init__()
        self.camera_id = camera_id
        self.settings = settings # Store reference to settings dict
        self.update_local_settings() # Apply initial settings

        self.recording = False
        self.out = None
        self.start_time = 0
        self.last_reset_time = 0
        self.lock = Lock() # Protects self.recording, self.out
        self.frame_queue = Queue(maxsize=60) # ~2 seconds buffer at 30fps
        self.thread = None
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.setInterval(1000)
        self.camera_thread_ref = None # Reference to get frames

    def set_camera_thread(self, camera_thread):
        self.camera_thread_ref = camera_thread

    def update_local_settings(self):
        """Update recorder parameters from the settings dictionary."""
        self.duration = self.settings.get("recording_duration", 30)
        self.codec_str = self.settings.get("recording_codec", "XVID")
        self.output_dir = self.settings.get("recording_dir", "recordings")
        rec_w, rec_h = parse_resolution(self.settings.get("recording_resolution", "1280x720"))
        self.recording_width = rec_w
        self.recording_height = rec_h
        # Inform countdown button about duration change
        # This requires a signal back to the main app or direct reference, handled in main app

    def update_settings(self, new_settings):
        """Update settings dynamically."""
        self.settings = new_settings
        self.update_local_settings()
        print(f"Recorder {self.camera_id}: Settings updated.")
        # Note: Codec/Resolution changes only apply on next recording start.
        # Duration change affects current countdown logic via self.duration.

    def start_recording(self):
        with self.lock:
            if self.recording: return True # Already recording

            os.makedirs(self.output_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.output_dir, f"cam{self.camera_id}_{timestamp}.avi") # Consider configurable extension based on codec?
            
            try:
                fourcc = cv2.VideoWriter_fourcc(*self.codec_str)
                # Using configured recording resolution
                self.out = cv2.VideoWriter(filename, fourcc, 20.0, (self.recording_width, self.recording_height)) 
                
                if not self.out.isOpened():
                    print(f"!!! Error: Could not open VideoWriter for {filename} with codec {self.codec_str} and resolution {self.recording_width}x{self.recording_height}")
                    self.out = None
                    return False # Failed to start

                self.recording = True
                self.start_time = time.time()
                self.last_reset_time = time.time()
                
                # Clear queue before starting
                while not self.frame_queue.empty():
                    try: self.frame_queue.get_nowait()
                    except Empty: break

                if self.thread is None or not self.thread.is_alive():
                    self.thread = Thread(target=self.recording_thread_loop)
                    self.thread.daemon = True
                    self.thread.start()
                
                self.stats_timer.start()
                self.recording_started.emit(self.camera_id)
                print(f"Recorder {self.camera_id}: Started recording to {filename}")
                return True

            except Exception as e:
                print(f"Recorder {self.camera_id}: Failed to start recording - {e}")
                traceback.print_exc()
                if self.out: self.out.release()
                self.out = None
                self.recording = False
                return False
    
    def add_frame_task(self):
        """Gets frame from camera thread and adds to queue."""
        if self.recording and self.camera_thread_ref:
            # Get frame resized for recording
            frame = self.camera_thread_ref.get_current_frame_for_recording(
                self.recording_width, self.recording_height
            )
            if frame is not None:
                 if not self.frame_queue.full():
                     self.frame_queue.put(frame)
                 # else: print(f"Warning: Recorder {self.camera_id} frame queue full.") # Optional warning

    def reset_countdown(self):
        with self.lock:
            if self.recording:
                self.last_reset_time = time.time()
                # Update countdown immediately for responsiveness (stats timer catches up later)
                self.recording_stats_updated.emit(self.camera_id, int(time.time() - self.start_time), self.duration)
    
    def update_stats(self):
        if self.recording:
            current_time = time.time()
            total_time = int(current_time - self.start_time)
            time_since_reset = int(current_time - self.last_reset_time)
            countdown = max(0, self.duration - time_since_reset)
            
            self.recording_stats_updated.emit(self.camera_id, total_time, countdown)
            
            if countdown <= 0:
                self.stop_recording() # Stop automatically when countdown finishes
    
    def recording_thread_loop(self):
        print(f"Recorder {self.camera_id}: Writer thread started.")
        while self.recording: # Check recording flag
            try:
                # Get frame directly from camera thread in this loop
                if self.camera_thread_ref:
                    frame = self.camera_thread_ref.get_current_frame_for_recording(
                        self.recording_width, self.recording_height
                    )
                    if frame is not None:
                        with self.lock: # Protect self.out
                            if self.out and self.recording:
                                self.out.write(frame)
                    else:
                        # If get_current_frame returns None (e.g., camera error), wait briefly
                        time.sleep(0.1)
                else:
                    # No camera ref, wait
                     time.sleep(0.1)

                # Control write rate roughly (adjust as needed)
                time.sleep(1.0 / 25.0) # Target ~25 FPS writing

            except Exception as e:
                print(f"Recorder {self.camera_id}: Error in writer thread: {e}")
                traceback.print_exc()
                time.sleep(0.5) # Wait after error
        
        print(f"Recorder {self.camera_id}: Writer thread finished.")
        # Release writer outside the loop after self.recording is false
        with self.lock:
            if self.out:
                print(f"Recorder {self.camera_id}: Releasing video writer.")
                self.out.release()
                self.out = None


    def stop_recording(self):
        should_emit = False
        with self.lock:
            if self.recording:
                print(f"Recorder {self.camera_id}: Stopping recording...")
                self.recording = False # Signal thread to stop
                should_emit = True
        
        # Stop stats timer outside lock
        self.stats_timer.stop() 

        # Wait for writer thread to finish processing queue and release file
        if self.thread and self.thread.is_alive():
            print(f"Recorder {self.camera_id}: Joining writer thread...")
            self.thread.join(timeout=2.0) # Wait for graceful finish
            if self.thread.is_alive():
                 print(f"Recorder {self.camera_id}: Writer thread join timed out.")
                 # self.out might still be locked, potential resource leak if forced

        # Emit signal after stopping is complete
        if should_emit:
            self.recording_stopped.emit(self.camera_id)
            print(f"Recorder {self.camera_id}: Stopped recording signal emitted.")

# --- Main Application ---
class SurveillanceApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.settings = load_settings()

        self.setWindowTitle("Video Surveillance System v2")
        self.setGeometry(100, 100, 1350, 750) # Slightly larger window
        self.setStyleSheet("background-color: #2D2D30; color: white;")
        
        self.available_cameras = self.detect_cameras()
        print(f"Found {len(self.available_cameras)} cameras: {self.available_cameras}")
        
        self.cameras = {}
        self.processors = {}
        self.recorders = {}
        self.record_buttons = {}
        self.countdown_buttons = {}
        self.sensitivity_button = None
        self.camera_labels = {}
        self.info_labels = {}
        self.motion_buttons = {}
        self.face_buttons = {}
        
        # Parse resolutions from settings once
        self.preview_res = parse_resolution(self.settings.get("preview_resolution", "640x480"))
        self.recording_res = parse_resolution(self.settings.get("recording_resolution", "1280x720"))

        for camera_id in self.available_cameras:
            # Camera thread
            camera = CameraThread(camera_id, self.preview_res, self.recording_res)
            camera.frame_ready.connect(self.on_frame_ready)
            camera.camera_error.connect(self.on_camera_error)
            self.cameras[camera_id] = camera
            
            # Frame processor
            processor = FrameProcessor(camera_id, self.settings["sensitivity_thresholds"], self.preview_res[0], self.preview_res[1])
            processor.motion_detected.connect(self.on_detection)
            processor.face_detected.connect(self.on_detection)
            processor.processed_frame.connect(self.update_frame_display)
            self.processors[camera_id] = processor
            
            # Video recorder
            recorder = VideoRecorder(camera_id, self.settings)
            recorder.set_camera_thread(camera) # Give recorder access to camera
            recorder.recording_started.connect(self.on_recording_started)
            recorder.recording_stopped.connect(self.on_recording_stopped)
            recorder.recording_stats_updated.connect(self.update_recording_stats)
            self.recorders[camera_id] = recorder
        
        self.init_ui()
        
        # Start components
        for cam_id in self.available_cameras:
            self.cameras[cam_id].start()
            self.processors[cam_id].start()
    
    def detect_cameras(self):
        available_cameras = []
        max_to_check = 8 
        print("Detecting cameras...")
        for i in range(max_to_check):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                print(f"  Camera {i}: Found")
                available_cameras.append(i)
                cap.release()
            else:
                print(f"  Camera {i}: Not found or cannot open")
        
        if not available_cameras:
            print("Warning: No cameras detected automatically. Adding camera 0 as default.")
            # Check if camera 0 can be opened at all, even if detect failed
            cap_test = cv2.VideoCapture(0)
            if cap_test.isOpened():
                 available_cameras = [0]
                 cap_test.release()
            else:
                 print("ERROR: Default camera 0 cannot be opened either.")
                 # Optionally show an error message box
                 msgBox = QMessageBox()
                 msgBox.setIcon(QMessageBox.Icon.Critical)
                 msgBox.setText("No cameras found or camera 0 cannot be opened. The application may not function correctly.")
                 msgBox.setWindowTitle("Camera Error")
                 msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
                 msgBox.exec()

        return available_cameras
    
    def on_frame_ready(self, frame, camera_id):
        if camera_id in self.processors:
            self.processors[camera_id].add_frame(frame)
        # Removed recorder frame adding here, recorder pulls directly now

    def on_camera_error(self, camera_id, error_message):
        print(f"!!! Camera {camera_id} error reported: {error_message}")
        if camera_id in self.camera_labels:
            label = self.camera_labels[camera_id]
            # Simplified error display
            label.setText(f"CAM {camera_id}\nERROR")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: white; background-color: red; font-weight: bold; border: 2px solid darkred;")
            # Optionally disable controls for this camera
            if camera_id in self.motion_buttons: self.motion_buttons[camera_id].setEnabled(False)
            if camera_id in self.face_buttons: self.face_buttons[camera_id].setEnabled(False)
            if camera_id in self.record_buttons: self.record_buttons[camera_id].setEnabled(False)

    def on_detection(self, camera_id, detection_type):
        if camera_id not in self.recorders: return

        recorder = self.recorders[camera_id]
        button = self.countdown_buttons.get(camera_id)
        
        if button:
            message = f"{detection_type.capitalize()} Detected!"
            button.flash_notification(message)
            
        # Start recording if inactive, otherwise reset countdown
        if not recorder.recording:
            # Use QTimer.singleShot to avoid potential GUI freezes if start takes time
             QTimer.singleShot(0, recorder.start_recording)
        else:
            recorder.reset_countdown()
    
    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        
        num_cameras = len(self.available_cameras)
        cols = min(3, max(1, num_cameras)) # Ensure at least 1 column
        
        grid_layout = QGridLayout(scroll_content)
        grid_layout.setSpacing(15)
        
        # Get initial duration for countdown button setup
        initial_duration = self.settings.get("recording_duration", 30)

        for i, camera_id in enumerate(self.available_cameras):
            row, col = divmod(i, cols)
            
            camera_widget = QWidget()
            camera_widget.setStyleSheet("background-color: #1E1E1E; border-radius: 10px; padding: 5px;")
            camera_layout_single = QVBoxLayout(camera_widget)
            
            # Header
            info_layout = QHBoxLayout()
            camera_title = QLabel(f"Camera {camera_id}")
            camera_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            recording_info = QLabel(f"REC: -- | Countdown: {initial_duration}s") # Placeholder
            recording_info.setStyleSheet("color: #CCCCCC;")
            self.info_labels[camera_id] = recording_info
            info_layout.addWidget(camera_title)
            info_layout.addStretch()
            info_layout.addWidget(recording_info)
            
            # Camera View
            label = QLabel()
            # Fixed size display label, actual processing uses configured preview res
            label.setFixedSize(480, 360) 
            label.setStyleSheet("border: 1px solid #444; background-color: black; border-radius: 5px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setText(f"Connecting to Cam {camera_id}...")
            self.camera_labels[camera_id] = label
            
            # Controls
            controls_layout = QHBoxLayout()
            motion_button = ToggleButton("Motion")
            motion_button.clicked.connect(lambda checked, cid=camera_id: self.toggle_motion_detection(checked, cid))
            self.motion_buttons[camera_id] = motion_button
            
            face_button = ToggleButton("Face")
            face_button.clicked.connect(lambda checked, cid=camera_id: self.toggle_face_detection(checked, cid))
            self.face_buttons[camera_id] = face_button
            
            record_button = QPushButton("Record")
            record_button.setStyleSheet("background-color: #555; color: white; padding: 5px;")
            record_button.clicked.connect(lambda _, cid=camera_id: self.toggle_recording(cid))
            self.record_buttons[camera_id] = record_button
            
            countdown_button = CountdownButton(initial_duration=initial_duration)
            # Allow clicking countdown to also toggle recording
            countdown_button.clicked.connect(lambda _, cid=camera_id: self.toggle_recording(cid))
            self.countdown_buttons[camera_id] = countdown_button
            
            controls_layout.addWidget(motion_button)
            controls_layout.addWidget(face_button)
            controls_layout.addStretch()
            controls_layout.addWidget(record_button)
            controls_layout.addWidget(countdown_button)
            
            camera_layout_single.addLayout(info_layout)
            camera_layout_single.addWidget(label)
            camera_layout_single.addLayout(controls_layout)
            
            grid_layout.addWidget(camera_widget, row, col)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1) # Give scroll area stretch factor
        
        # Global Controls
        global_controls_widget = QWidget()
        global_controls_widget.setStyleSheet("background-color: #1E1E1E; border-radius: 5px; padding: 8px;")
        global_controls = QHBoxLayout(global_controls_widget)
        
        settings_button = QPushButton("Settings")
        settings_button.setStyleSheet("background-color: #007AFF; color: white; padding: 8px;")
        settings_button.clicked.connect(self.open_settings_dialog)

        sensitivity_label = QLabel("Motion Sensitivity:")
        self.sensitivity_button = SensitivityButton(self.settings["sensitivity_thresholds"])
        self.sensitivity_button.clicked.connect(self.change_sensitivity)
        
        self.status_label = QLabel(f"Monitoring {len(self.available_cameras)} cameras")
        self.status_label.setStyleSheet("color: #AAA;")
        
        exit_button = QPushButton("Exit")
        exit_button.setStyleSheet("background-color: #E74C3C; color: white; padding: 8px; font-weight: bold;")
        exit_button.clicked.connect(self.close)
        
        global_controls.addWidget(settings_button)
        global_controls.addSpacing(20)
        global_controls.addWidget(sensitivity_label)
        global_controls.addWidget(self.sensitivity_button)
        global_controls.addStretch()
        global_controls.addWidget(self.status_label)
        global_controls.addStretch()
        global_controls.addWidget(exit_button)
        
        main_layout.addWidget(global_controls_widget)
        
        self.setCentralWidget(central_widget)

    def update_frame_display(self, frame, camera_id):
        """Updates the QLabel for a specific camera."""
        if camera_id in self.camera_labels:
            label = self.camera_labels[camera_id]
            try:
                # Ensure frame is in RGB format for QImage
                if len(frame.shape) == 3:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                else: # Grayscale frame? Handle appropriately
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # Scale pixmap to fit the fixed-size label
                pixmap = QPixmap.fromImage(q_img)
                label.setPixmap(pixmap.scaled(label.width(), label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            except Exception as e:
                print(f"Error updating display for camera {camera_id}: {e}")
                # traceback.print_exc() # Optional: for debugging display issues
                label.setText(f"Display Error Cam {camera_id}") # Show error on label

    def update_recording_stats(self, camera_id, total_seconds, countdown):
        if camera_id in self.info_labels and camera_id in self.recorders:
            total_time_str = f"{total_seconds // 60}:{total_seconds % 60:02d}"
            self.info_labels[camera_id].setText(f"REC: {total_time_str} | Countdown: {countdown}s")
            
            if camera_id in self.record_buttons:
                 if self.recorders[camera_id].recording:
                     self.record_buttons[camera_id].setText(f"Rec: {total_time_str}")
                 # else: handled by on_recording_stopped
            
            if camera_id in self.countdown_buttons:
                self.countdown_buttons[camera_id].update_countdown(countdown)
    
    def on_recording_started(self, camera_id):
        if camera_id in self.record_buttons:
            self.record_buttons[camera_id].setStyleSheet("background-color: #FF3B30; color: white; padding: 5px; font-weight: bold;") # Red when recording
            self.record_buttons[camera_id].setText("Rec: 0:00")
        if camera_id in self.countdown_buttons and camera_id in self.recorders:
             # Reset countdown button visual state when recording starts
             self.countdown_buttons[camera_id].update_duration(self.recorders[camera_id].duration)
             self.countdown_buttons[camera_id].update_countdown(self.recorders[camera_id].duration)
    
    def on_recording_stopped(self, camera_id):
        if camera_id in self.record_buttons:
            self.record_buttons[camera_id].setStyleSheet("background-color: #555; color: white; padding: 5px;")
            self.record_buttons[camera_id].setText("Record")
        if camera_id in self.info_labels and camera_id in self.recorders:
             # Reset info label countdown part
             current_text = self.info_labels[camera_id].text().split('|')[0].strip() # Keep REC time part if needed
             self.info_labels[camera_id].setText(f"{current_text} | Countdown: {self.recorders[camera_id].duration}s")
        if camera_id in self.countdown_buttons and camera_id in self.recorders:
             # Reset countdown button to initial duration display
             self.countdown_buttons[camera_id].update_duration(self.recorders[camera_id].duration)
             self.countdown_buttons[camera_id].update_countdown(self.recorders[camera_id].duration)

    def toggle_recording(self, camera_id):
        if camera_id in self.recorders:
            recorder = self.recorders[camera_id]
            if recorder.recording:
                recorder.stop_recording()
            else:
                recorder.start_recording() # Returns bool indicating success
    
    def toggle_motion_detection(self, checked, camera_id):
        if camera_id in self.processors:
            self.processors[camera_id].set_motion_detection(checked)
            if camera_id in self.countdown_buttons:
                self.countdown_buttons[camera_id].flash_notification("Motion: " + ("On" if checked else "Off"))
    
    def toggle_face_detection(self, checked, camera_id):
         if camera_id in self.processors:
            self.processors[camera_id].set_face_detection(checked)
            if camera_id in self.countdown_buttons:
                self.countdown_buttons[camera_id].flash_notification("Face: " + ("On" if checked else "Off"))
    
    def change_sensitivity(self):
        threshold = self.sensitivity_button.get_threshold()
        level_name = self.sensitivity_button.levels[self.sensitivity_button.get_level()]
        
        for processor in self.processors.values():
            processor.set_motion_threshold(threshold)
        
        # Flash notification on all countdown buttons
        for button in self.countdown_buttons.values():
            button.flash_notification(f"Sensitivity: {level_name}")
    
    def open_settings_dialog(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec(): # True if user clicked OK
            new_settings = dialog.get_settings()
            # Basic check if resolutions changed
            res_changed = (new_settings["preview_resolution"] != self.settings["preview_resolution"] or
                           new_settings["recording_resolution"] != self.settings["recording_resolution"])
            
            self.settings.update(new_settings) # Update main settings dict
            save_settings(self.settings) # Persist changes
            print("Settings updated and saved.")

            # Apply settings dynamically
            self.apply_settings(res_changed)

    def apply_settings(self, resolution_changed=False):
        """Applies current self.settings to components."""
        new_thresholds = self.settings.get("sensitivity_thresholds", DEFAULT_SETTINGS["sensitivity_thresholds"])
        new_duration = self.settings.get("recording_duration", DEFAULT_SETTINGS["recording_duration"])

        # Update sensitivity button visuals and thresholds it provides
        self.sensitivity_button.update_thresholds(new_thresholds)
        # Re-apply current sensitivity level's threshold to processors
        current_threshold = self.sensitivity_button.get_threshold()
        for proc in self.processors.values():
            proc.set_motion_threshold(current_threshold)

        # Update recorders and countdown buttons
        for cam_id, recorder in self.recorders.items():
            recorder.update_settings(self.settings) # Pass the whole updated dict
            if cam_id in self.countdown_buttons:
                self.countdown_buttons[cam_id].update_duration(new_duration)
                # Also update info label if not currently recording
                if not recorder.recording:
                    self.on_recording_stopped(cam_id) # Reuse this to reset label/button text

        # Handle resolution changes (requires camera restart)
        if resolution_changed:
            QMessageBox.information(self, "Resolution Changed", 
                                    "Preview or Recording resolution changed. "+
                                    "Please restart the application for these changes to fully take effect on camera capture.")
            # For a partial update (affects processing size immediately, capture later):
            new_preview_res = parse_resolution(self.settings["preview_resolution"])
            new_recording_res = parse_resolution(self.settings["recording_resolution"])
            for cam_id, proc in self.processors.items():
                proc.preview_width, proc.preview_height = new_preview_res
            # CameraThread update requires restart or more complex handling
            print("Resolution settings updated. Restart recommended for camera capture changes.")


    def closeEvent(self, event):
        print("Closing application...")
        save_settings(self.settings) # Save settings on exit

        # Stop recorders first (they might need frames from camera)
        print("Stopping recorders...")
        for recorder in self.recorders.values():
            recorder.stop_recording()
        
        # Stop processors (they might need frames from camera)
        print("Stopping processors...")
        all_proc_stopped = True
        proc_list = list(self.processors.values()) # Copy list
        for processor in proc_list:
             try:
                 processor.stop()
             except Exception as e:
                 print(f"Error stopping processor {processor.camera_id}: {e}")
                 all_proc_stopped = False
        if all_proc_stopped: print("All processors stopped.")
        else: print("Some processors may not have stopped cleanly.")

        # Stop cameras last
        print("Stopping cameras...")
        for camera in self.cameras.values():
            camera.stop()
        
        print("Shutdown complete.")
        event.accept()

if __name__ == "__main__":
    # Force 'spawn' start method for multiprocessing with GUI libs, especially on macOS/Windows
    try:
        mp.set_start_method('spawn', force=True)
        print("Multiprocessing start method set to 'spawn'.")
    except RuntimeError as e:
        print(f"Warning: Could not set multiprocessing start method ('{e}'). Using default.")

    
    app = QApplication(sys.argv)
    # Set application info for QSettings (optional but good practice)
    app.setOrganizationName("YourOrg")
    app.setApplicationName("VideoSurvApp")

    surveillance_app = SurveillanceApp()
    surveillance_app.show()
    sys.exit(app.exec())

# --- END OF FILE videosurv_v2.py ---