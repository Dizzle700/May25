# --- START OF FILE videodet_pyqt6.py ---

import sys
import cv2
import os
import torch
import time
from ultralytics import YOLO
from pathlib import Path

# Import PyQt6 components
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSlider, QComboBox, QMessageBox,
    QProgressDialog, QStyleFactory, QSizePolicy, QStyle
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QObject, QSize
)
from PyQt6.QtGui import QImage, QPixmap, QPalette, QColor, QIcon, QFont, QPixmapCache

# --- Constants ---
# MAX_FPS_AVERAGE = 30 # Number of frames to average FPS over # This constant is defined later, let's keep it there for now. Will remove if truly unused after changes.
MAX_FPS_AVERAGE = 30 # Number of frames to average FPS over

# --- Worker for Model Loading ---
class ModelLoader(QObject):
    modelReady = pyqtSignal(object, str) # emits loaded model object and info text
    errorOccurred = pyqtSignal(str)

    def __init__(self, model_file_path, device):
        super().__init__()
        self.model_file_path = model_file_path
        self.device = device
        self.model = None

    def run(self):
        try:
            if not self.model_file_path:
                raise ValueError("Model file path cannot be empty.")

            model_pt_path = Path(self.model_file_path)

            if not model_pt_path.exists() or not model_pt_path.is_file():
                raise FileNotFoundError(f"Model file not found or is not a file: {self.model_file_path}")

            # --- TensorRT Engine Handling ---
            engine_dir = Path("engines")
            engine_dir.mkdir(exist_ok=True)
            # Use model name for engine filename
            model_name = model_pt_path.stem
            engine_filename = f"{model_name}_{self.device.replace(':', '')}.engine"
            engine_path = engine_dir / engine_filename

            info_text = ""
            use_engine = False

            if self.device != "cpu":
                if engine_path.exists():
                    print(f"Found existing TensorRT engine: {engine_path}")
                    try:
                        self.model = YOLO(engine_path, task='detect') # Assuming detection task
                        info_text = f"Loaded TensorRT engine: {engine_path.name}"
                        use_engine = True
                    except Exception as e:
                        print(f"Failed to load engine {engine_path}: {e}. Falling back to PT.")
                        self.model = None # Ensure we load PT if engine fails
                        engine_path.unlink(missing_ok=True) # Remove corrupted engine
                else:
                    print(f"No TensorRT engine found at {engine_path}. Exporting...")
                    info_text = "Optimizing model for TensorRT... Please wait."
                    # Emit signal to update UI before long export
                    self.modelReady.emit(None, info_text) # Emit None for model to indicate processing

            # --- Load PyTorch or Export Engine ---
            if not use_engine:
                self.model = YOLO(model_pt_path) # Load directly from the provided path
                self.model.to(self.device)
                info_text = f"Loaded model '{model_pt_path.name}' on {self.device}"

                if self.device != "cpu" and not engine_path.exists(): # Export if not CPU and engine wasn't found/loaded
                    try:
                        # Export arguments might need adjustment based on Ultralytics version
                        engine_path_dir = engine_path.parent
                        self.model.export(format='engine', device=self.device, half=True, workspace=4)
                        # Verify the engine was created where expected
                        # Ultralytics typically saves the .engine file in the same directory as the .pt file,
                        # or in a 'weights' subdirectory, with the same stem.
                        # Let's assume it's created with the same stem in the CWD or near the original model.
                        # The export function often returns the path or modifies the model object.
                        # For robustness, we'll look for <model_name>.engine.
                        
                        # The export path might be relative to the CWD or the model path.
                        # ultralytics seems to save it as <model_name>.engine in the CWD if not specified.
                        # Let's check the current working directory or the model's directory.
                        
                        # Default export location by Ultralytics is often '<model_name>.engine' in CWD
                        # or a path relative to the original model if it's part of a project structure.
                        # Let's try a common pattern.
                        exported_engine_name = f"{model_name}.engine"
                        
                        # Check CWD first
                        potential_engine_path_cwd = Path(exported_engine_name)
                        # Check original model's directory
                        potential_engine_path_model_dir = model_pt_path.parent / exported_engine_name

                        exported_engine_found_path = None
                        if engine_path.exists(): # If export created it directly at our target path
                            exported_engine_found_path = engine_path
                        elif potential_engine_path_cwd.exists():
                            exported_engine_found_path = potential_engine_path_cwd
                        elif potential_engine_path_model_dir.exists():
                            exported_engine_found_path = potential_engine_path_model_dir
                        
                        if exported_engine_found_path and exported_engine_found_path != engine_path:
                            exported_engine_found_path.rename(engine_path) # Move to our engines dir
                            print(f"TensorRT engine exported and moved to: {engine_path}")
                            self.model = YOLO(engine_path, task='detect') # Reload using the engine
                            info_text = f"TensorRT engine created: {engine_path.name}"
                        elif exported_engine_found_path == engine_path: # Already at the target
                             self.model = YOLO(engine_path, task='detect') # Reload using the engine
                             info_text = f"TensorRT engine created: {engine_path.name}"
                        else:
                             info_text += " (Engine export succeeded, but file not found at expected common locations for moving)"
                             print(f"Engine export seems to have run, but {exported_engine_name} not found in CWD or model dir for moving to {engine_path}")
                             # The model is already on the device, so it's usable without the engine for now.

                    except Exception as e:
                        info_text = f"TensorRT export failed: {e}. Using PyTorch on {self.device}."
                        print(f"TensorRT export failed: {e}")
                        # Model is already loaded on the correct device

            # Perform a dummy inference to warm up
            if self.model:
                 _ = self.model(torch.zeros(1, 3, 640, 640).to(self.device), verbose=False)
                 print("Model warm-up complete.")

            self.modelReady.emit(self.model, info_text)

        except Exception as e:
            print(f"Error in ModelLoader: {e}")
            self.errorOccurred.emit(f"Failed to load model: {str(e)}")

# --- Worker for Video Processing ---
class VideoProcessor(QObject):
    frameProcessed = pyqtSignal(QImage)
    updateProgress = pyqtSignal(int, int) # current_frame, total_frames
    processingFinished = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, video_path, model, start_frame=0):
        super().__init__()
        self.video_path = video_path
        self.model = model
        self.start_frame = start_frame
        self._running = False
        self._paused = False
        self.cap = None
        self.total_frames = 0
        self.frame_times = []

    def run(self):
        self._running = True
        self._paused = False
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            self.errorOccurred.emit(f"Error opening video file: {self.video_path}")
            self._running = False
            return

        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.start_frame > 0 and self.start_frame < self.total_frames:
             self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
        else:
            self.start_frame = 0 # Ensure start frame is valid

        fps = self.cap.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps > 0 else 33 # ms per frame

        current_frame_num = self.start_frame
        self.frame_times = []

        while self._running:
            if self._paused:
                time.sleep(0.1) # Sleep briefly when paused
                continue

            ret, frame = self.cap.read()
            if not ret:
                print("End of video reached.")
                break

            current_frame_num = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            self.updateProgress.emit(current_frame_num, self.total_frames)

            try:
                start_time = time.time()
                processed_frame = self.process_frame(frame)
                self.update_fps(time.time() - start_time) # Calculate processing time

                # Convert processed frame (BGR) to QImage (RGB)
                rgb_frame = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.frameProcessed.emit(qt_image.copy()) # Emit a copy

            except Exception as e:
                print(f"Error processing frame {current_frame_num}: {e}")
                self.errorOccurred.emit(f"Error processing frame {current_frame_num}: {str(e)}")
                # Optionally stop processing on error: self._running = False

            # Crude delay - consider QTimer for smoother playback if needed
            time.sleep(max(0, delay / 1000.0 - (time.time() - start_time)))

        if self.cap:
            self.cap.release()
        self._running = False
        self.processingFinished.emit()
        print("Video processing thread finished.")

    def process_frame(self, frame):
        # Perform detection
        results = self.model(frame, verbose=False) # Input is BGR frame directly

        # Draw detection results (assuming results[0] contains detections for the frame)
        if results and results[0]:
            boxes = results[0].boxes
            names = results[0].names # Class names

            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = f"{names[cls_id]} {conf:.2f}"

                # Draw rectangle and label
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # No mask processing here for standard detection models

        return frame

    def update_fps(self, frame_time):
        self.frame_times.append(frame_time)
        if len(self.frame_times) > MAX_FPS_AVERAGE:
            self.frame_times.pop(0)

        avg_frame_time = sum(self.frame_times) / len(self.frame_times) if self.frame_times else 0
        fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
        # Note: FPS display is handled in the main window now, based on processing time

    def stop(self):
        print("Stopping video processing thread...")
        self._running = False

    def pause(self):
        print("Pausing video processing.")
        self._paused = True

    def resume(self):
        print("Resuming video processing.")
        self._paused = False

    def seek(self, frame_number):
        if self.cap and 0 <= frame_number < self.total_frames:
             self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
             print(f"Seeked to frame {frame_number}")
             return True
        return False


# --- Worker for Video Saving ---
class VideoSaver(QObject):
    saveProgress = pyqtSignal(int) # Percentage complete
    saveFinished = pyqtSignal(str) # Output path
    errorOccurred = pyqtSignal(str)

    def __init__(self, input_path, output_path, model):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.model = model
        self._running = False

    def run(self):
        self._running = True
        cap = cv2.VideoCapture(self.input_path)
        if not cap.isOpened():
            self.errorOccurred.emit(f"Error opening input video for saving: {self.input_path}")
            return

        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Choose codec based on output file extension
        fourcc = cv2.VideoWriter_fourcc(*'mp4v') # Default for MP4
        if self.output_path.lower().endswith(".avi"):
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
        elif self.output_path.lower().endswith(".mkv"):
             fourcc = cv2.VideoWriter_fourcc(*'X264') # Requires appropriate backend

        writer = cv2.VideoWriter(self.output_path, fourcc, fps, (frame_width, frame_height))
        if not writer.isOpened():
            self.errorOccurred.emit(f"Error opening video writer for: {self.output_path}")
            cap.release()
            return

        print(f"Starting video save process to {self.output_path}...")
        frame_count = 0
        while self._running:
            ret, frame = cap.read()
            if not ret:
                break

            try:
                # Re-use the processing logic (or could have a separate one if needed)
                processed_frame = self.process_frame(frame)
                writer.write(processed_frame)
                frame_count += 1

                if total_frames > 0:
                    progress = int((frame_count / total_frames) * 100)
                    self.saveProgress.emit(progress)

            except Exception as e:
                error_msg = f"Error processing frame {frame_count} during save: {e}"
                print(error_msg)
                self.errorOccurred.emit(error_msg)
                # Decide whether to continue or stop on error
                # self._running = False # Uncomment to stop saving on error

        cap.release()
        writer.release()
        if self._running: # Finished normally
            self.saveProgress.emit(100)
            self.saveFinished.emit(self.output_path)
        else: # Stopped prematurely
            self.errorOccurred.emit("Video saving cancelled.")
        print("Video saving thread finished.")

    def process_frame(self, frame):
         # Perform detection (same as VideoProcessor - could be refactored)
        results = self.model(frame, verbose=False)

        if results and results[0]:
            boxes = results[0].boxes
            names = results[0].names

            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = f"{names[cls_id]} {conf:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return frame

    def stop(self):
        print("Stopping video saving thread...")
        self._running = False

# --- Main Application Window ---
class ObjectDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO Object Detection (PyQt6 + TensorRT)")
        self.setGeometry(100, 100, 1200, 800)

        # --- State Variables ---
        self.model = None
        self.model_info = "No model loaded"
        self.video_path = None
        self.total_frames = 0
        self.current_frame_num = 0
        self.is_playing = False
        self.is_paused = False
        self.frame_times = [] # For FPS calculation

        # --- Threading ---
        self.model_loader_thread = None
        self.model_loader_worker = None
        self.video_processor_thread = None
        self.video_processor_worker = None
        self.video_saver_thread = None
        self.video_saver_worker = None
        self.save_progress_dialog = None

        # --- CUDA Check ---
        self.cuda_available = torch.cuda.is_available()
        if self.cuda_available:
            self.device = "cuda:0"
            try:
                device_name = torch.cuda.get_device_name(0)
            except Exception as e:
                print(f"Could not get CUDA device name: {e}")
                device_name = "CUDA Device" # Fallback name
            print(f"CUDA available: {device_name}")
        else:
            self.device = "cpu"
            device_name = "CPU"
            print("CUDA not available, using CPU.")

        # --- UI Elements ---
        self.setup_ui()
        
        # --- Display Model Information in Status Bar ---
        self.status_bar.showMessage("No model loaded. Please load a model file.")

        # --- Load Initial Model ---
        # self.load_model() # No model loaded on startup anymore

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Video Display Area
        self.video_label = QLabel("Select a video file to start")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored) # Allow stretching
        self.video_label.setBackgroundRole(QPalette.ColorRole.Dark)
        self.video_label.setAutoFillBackground(True)
        font = self.video_label.font()
        font.setPointSize(16)
        self.video_label.setFont(font)
        layout.addWidget(self.video_label, 1) # Add stretch factor

        # Controls Area
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        layout.addWidget(controls_widget)

        # Model Selection
        self.load_model_button = QPushButton(icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DirLinkIcon), text=" Load Model File")
        self.load_model_button.setToolTip("Load a .pt model file from your computer")
        self.load_model_button.clicked.connect(self.select_and_load_model)
        controls_layout.addWidget(self.load_model_button)

        # Info Label (Model Status)
        self.info_label = QLabel(self.model_info)
        controls_layout.addWidget(self.info_label, 1) # Stretch

        # FPS Label
        self.fps_label = QLabel("FPS: 0.0")
        self.fps_label.setFixedWidth(80)
        controls_layout.addWidget(self.fps_label)

        # File Selection
        self.file_button = QPushButton(icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), text=" Video")
        self.file_button.clicked.connect(self.select_file)
        controls_layout.addWidget(self.file_button)

        self.file_label = QLabel("No file selected")
        self.file_label.setMinimumWidth(150)
        controls_layout.addWidget(self.file_label)

        # Buttons
        self.play_pause_button = QPushButton(icon=self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), text=" Play")
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.play_pause_button.setEnabled(False)
        controls_layout.addWidget(self.play_pause_button)

        self.stop_button = QPushButton(icon=self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop), text=" Stop")
        self.stop_button.clicked.connect(self.stop_detection)
        self.stop_button.setEnabled(False)
        controls_layout.addWidget(self.stop_button)

        self.save_button = QPushButton(icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), text=" Save")
        self.save_button.clicked.connect(self.save_video)
        self.save_button.setEnabled(False)
        controls_layout.addWidget(self.save_button)

        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self.toggle_fullscreen)
        controls_layout.addWidget(self.fullscreen_button)


        # Slider Area
        slider_layout = QHBoxLayout()
        layout.addLayout(slider_layout)

        self.current_time_label = QLabel("00:00")
        slider_layout.addWidget(self.current_time_label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.slider_seek) # User dragging
        self.slider.valueChanged.connect(self.update_time_labels) # Update time on any change
        slider_layout.addWidget(self.slider, 1) # Stretch

        self.total_time_label = QLabel("00:00")
        slider_layout.addWidget(self.total_time_label)

        # Status Bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready. Load a model and a video file.")

    # --- Model Handling ---
    def select_and_load_model(self):
        if self.is_playing or self.is_paused:
            QMessageBox.warning(self, "Playback Active",
                                "Please stop video playback before loading a new model.")
            return
        if self.model_loader_thread and self.model_loader_thread.isRunning():
            QMessageBox.information(self, "Model Loading",
                                    "A model is already being loaded. Please wait.")
            return

        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select YOLO Model File",
            "", # Start in the current directory or last visited
            "PyTorch Model Files (*.pt)"
        )
        if file_name:
            self.load_model(file_name)

    def load_model(self, model_file_path=None): # model_file_path is now mandatory if called directly
        if not model_file_path:
            # This case should ideally not be hit if triggered by select_and_load_model
            self.status_bar.showMessage("No model file specified.", 5000)
            self.info_label.setText("No model selected.")
            return

        if self.model_loader_thread and self.model_loader_thread.isRunning():
            print("Model loading already in progress.")
            return

        model_name_display = Path(model_file_path).name
        self.status_bar.showMessage(f"Loading model: {model_name_display}...")
        self.info_label.setText(f"Loading {model_name_display}...")
        self.play_pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.load_model_button.setEnabled(False) # Disable model load button
        self.file_button.setEnabled(False)

        self.model = None # Clear previous model

        if self.model_loader_thread:
            self.model_loader_thread.quit()
            self.model_loader_thread.wait()

        self.model_loader_thread = QThread(self)
        # Pass the file path directly to ModelLoader
        self.model_loader_worker = ModelLoader(model_file_path, self.device)
        self.model_loader_worker.moveToThread(self.model_loader_thread)

        self.model_loader_thread.started.connect(self.model_loader_worker.run)
        self.model_loader_worker.modelReady.connect(self.on_model_ready)
        self.model_loader_worker.errorOccurred.connect(self.on_model_load_error)
        self.model_loader_worker.modelReady.connect(self.model_loader_thread.quit)
        self.model_loader_worker.errorOccurred.connect(self.model_loader_thread.quit)
        self.model_loader_thread.finished.connect(self.model_loader_worker.deleteLater)
        self.model_loader_thread.finished.connect(self.model_loader_thread.deleteLater)
        self.model_loader_thread.finished.connect(self.reset_controls_after_load)

        self.model_loader_thread.start()

    def on_model_ready(self, loaded_model, info_text):
        self.model = loaded_model
        # Update model_info to reflect the file name if possible, or use the info_text
        if self.model and hasattr(self.model_loader_worker, 'model_file_path'):
            model_file_name = Path(self.model_loader_worker.model_file_path).name
            self.model_info = f"Loaded: {model_file_name} ({info_text.split(': ')[-1]})" # Extract details from info_text
            if "TensorRT engine" in info_text:
                 self.model_info = f"Active: {Path(info_text.split(': ')[-1]).name} (TensorRT)"
            elif "Loaded model" in info_text:
                 self.model_info = f"Active: {model_file_name} (PyTorch)"

        else:
            self.model_info = info_text # Fallback or intermediate message

        self.info_label.setText(self.model_info)

        if self.model:
             self.status_bar.showMessage("Model loaded successfully.", 5000)
             print(f"Model ready: {self.model_info}")
             if self.video_path:
                 self.play_pause_button.setEnabled(True)
                 self.save_button.setEnabled(True)
                 self.slider.setEnabled(True)
        else:
            # This might happen if TensorRT export started but didn't finish/fail yet
            # The info_text from ModelLoader would be "Optimizing model for TensorRT..."
            self.status_bar.showMessage(info_text) 
            print(f"Model update: {info_text}")


    def on_model_load_error(self, error_message):
        self.model = None
        self.model_info = "Error loading model!"
        self.info_label.setText(self.model_info)
        QMessageBox.critical(self, "Model Load Error", error_message)
        self.status_bar.showMessage("Model loading failed.", 5000)
        print(f"Model load error signal received: {error_message}")


    def reset_controls_after_load(self):
        """Called when the model loader thread finishes (success or error)."""
        print("Model loader thread finished.")
        self.load_model_button.setEnabled(True) # Re-enable model load button
        self.file_button.setEnabled(True)
        # Play/Save buttons are enabled in on_model_ready if successful AND video is loaded
        self.model_loader_thread = None 
        self.model_loader_worker = None


    # --- File Handling ---
    def select_file(self):
        if self.is_playing or self.is_paused:
             self.stop_detection() # Stop playback before changing file

        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*.*)"
        )

        if file_name:
            self.video_path = file_name
            self.file_label.setText(os.path.basename(file_name))
            self.status_bar.showMessage(f"Selected video: {file_name}", 5000)

            # Get video properties for slider
            temp_cap = cv2.VideoCapture(self.video_path)
            if temp_cap.isOpened():
                self.total_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = temp_cap.get(cv2.CAP_PROP_FPS)
                self.video_duration = self.total_frames / fps if fps > 0 else 0
                self.slider.setRange(0, self.total_frames - 1 if self.total_frames > 0 else 0)
                self.update_time_labels(0) # Set initial time labels
                self.slider.setEnabled(self.model is not None) # Enable slider if model is ready
                self.play_pause_button.setEnabled(self.model is not None)
                self.save_button.setEnabled(self.model is not None)
                self.stop_button.setEnabled(False) # Stop is only enabled when playing
                self.video_label.clear() # Clear previous frame/message
                self.video_label.setText("Press Play to start detection")
                temp_cap.release()
            else:
                QMessageBox.warning(self, "Video Error", f"Could not open video file: {file_name}")
                self.video_path = None
                self.file_label.setText("No file selected")
                self.total_frames = 0
                self.slider.setEnabled(False)
                self.play_pause_button.setEnabled(False)
                self.save_button.setEnabled(False)
                self.stop_button.setEnabled(False)

    # --- Playback Control ---
    def toggle_play_pause(self):
        if not self.video_path or not self.model:
            QMessageBox.warning(self, "Cannot Play", "Please select a video file and ensure a model is loaded.")
            return

        if not self.is_playing: # Start playing or resume
            if self.is_paused: # Resume
                 if self.video_processor_worker:
                     self.video_processor_worker.resume()
                 self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
                 self.play_pause_button.setText(" Pause")
                 self.status_bar.showMessage("Resumed", 2000)
                 self.is_paused = False
                 self.is_playing = True # It was paused, now it's playing
            else: # Start new playback
                 self.start_detection(start_frame=self.slider.value())

        else: # Pause
            if self.video_processor_worker:
                 self.video_processor_worker.pause()
            self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.play_pause_button.setText(" Resume")
            self.status_bar.showMessage("Paused", 2000)
            self.is_paused = True
            self.is_playing = False # Mark as not actively playing (paused)


    def start_detection(self, start_frame=0):
        if not self.video_path or not self.model: return
        if self.video_processor_thread and self.video_processor_thread.isRunning(): return # Already running

        print(f"Starting detection from frame {start_frame}...")
        self.is_playing = True
        self.is_paused = False

        # --- Setup Worker Thread ---
        self.video_processor_thread = QThread(self)
        self.video_processor_worker = VideoProcessor(self.video_path, self.model, start_frame)
        self.video_processor_worker.moveToThread(self.video_processor_thread)

        # --- Connect Signals ---
        self.video_processor_thread.started.connect(self.video_processor_worker.run)
        self.video_processor_worker.frameProcessed.connect(self.update_display)
        self.video_processor_worker.updateProgress.connect(self.update_slider_progress)
        self.video_processor_worker.processingFinished.connect(self.on_processing_finished)
        self.video_processor_worker.errorOccurred.connect(self.on_processing_error)

        # Cleanup connections
        self.video_processor_worker.processingFinished.connect(self.video_processor_thread.quit)
        self.video_processor_worker.errorOccurred.connect(self.video_processor_thread.quit) # Quit on error too
        self.video_processor_thread.finished.connect(self.video_processor_worker.deleteLater)
        self.video_processor_thread.finished.connect(self.video_processor_thread.deleteLater)
        self.video_processor_thread.finished.connect(self.cleanup_after_processing)

        # --- Update UI ---
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.play_pause_button.setText(" Pause")
        self.stop_button.setEnabled(True)
        self.file_button.setEnabled(False) # Prevent changing file while playing
        self.load_model_button.setEnabled(False) # Prevent changing model while playing
        self.save_button.setEnabled(False) # Disable save during playback (separate op)
        self.slider.setEnabled(True) # Ensure slider is enabled
        self.status_bar.showMessage("Playing...")

        self.video_processor_thread.start()

    def stop_detection(self):
        print("Stop button clicked.")
        if self.video_processor_worker:
            self.video_processor_worker.stop() # Signal the worker to stop

        # Wait for thread to finish might be needed here, but cleanup_after_processing handles UI reset
        # If immediate UI reset is desired before thread fully exits:
        self.reset_playback_ui()


    def on_processing_finished(self):
        print("Video processing finished signal received.")
        self.status_bar.showMessage("Playback finished.", 5000)
        # UI reset is handled by cleanup_after_processing via thread.finished


    def on_processing_error(self, error_message):
        print(f"Video processing error signal received: {error_message}")
        QMessageBox.warning(self, "Processing Error", error_message)
        self.status_bar.showMessage(f"Error: {error_message}", 5000)
        # UI reset is handled by cleanup_after_processing via thread.finished


    def cleanup_after_processing(self):
        """Called when the video processor thread finishes (normally or via error/stop)."""
        print("Cleaning up after video processing thread.")
        self.reset_playback_ui()
        self.video_processor_thread = None # Allow garbage collection
        self.video_processor_worker = None


    def reset_playback_ui(self):
        """Resets UI elements related to playback to their default state."""
        self.is_playing = False
        self.is_paused = False
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_pause_button.setText(" Play")
        self.stop_button.setEnabled(False)
        # Enable file/model selection only if not currently loading a model
        if not (self.model_loader_thread and self.model_loader_thread.isRunning()):
            self.file_button.setEnabled(True)
            self.load_model_button.setEnabled(True) # Enable model load button
        # Enable save button only if model and video are ready
        self.save_button.setEnabled(self.model is not None and self.video_path is not None)
        # Optionally reset slider to start, or leave it at the end position
        # self.slider.setValue(0)
        self.fps_label.setText("FPS: 0.0")


    # --- Frame Display and Progress ---
    def update_display(self, qt_image):
        """Updates the video label with a new QImage."""
        pixmap = QPixmap.fromImage(qt_image)
        # Scale pixmap maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(self.video_label.size(),
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.video_label.setPixmap(scaled_pixmap)

    def update_slider_progress(self, current_frame, total_frames):
        """Updates the slider position and time labels."""
        if total_frames > 0 and current_frame <= total_frames:
             self.slider.blockSignals(True) # Prevent triggering seek
             self.slider.setValue(current_frame -1) # Slider is 0-based
             self.slider.blockSignals(False)
             self.current_frame_num = current_frame
             self.update_time_labels(current_frame -1)
        # Update FPS based on processing time from worker
        if self.video_processor_worker and self.video_processor_worker.frame_times:
            avg_frame_time = sum(self.video_processor_worker.frame_times) / len(self.video_processor_worker.frame_times)
            fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
            self.fps_label.setText(f"FPS: {fps:.1f}")


    def update_time_labels(self, frame_value):
        """ Updates the current/total time labels based on slider/frame value """
        fps = 30 # Assume 30 fps if video not loaded yet
        if self.video_processor_worker and self.video_processor_worker.cap:
            worker_fps = self.video_processor_worker.cap.get(cv2.CAP_PROP_FPS)
            if worker_fps > 0:
                fps = worker_fps
        elif self.total_frames > 0 and self.video_duration > 0:
            fps = self.total_frames / self.video_duration


        current_seconds = int(frame_value / fps) if fps > 0 else 0
        total_seconds = int(self.video_duration) # Use pre-calculated duration

        current_time_str = time.strftime('%M:%S', time.gmtime(current_seconds))
        total_time_str = time.strftime('%M:%S', time.gmtime(total_seconds))

        self.current_time_label.setText(current_time_str)
        self.total_time_label.setText(total_time_str)


    def slider_seek(self, position):
        """Handles user interaction with the slider."""
        if not self.video_path or not self.model:
            return

        print(f"Slider moved to position (frame index): {position}")
        self.update_time_labels(position) # Update time display immediately

        # Stop current playback if running/paused, then restart from new position
        if self.is_playing or self.is_paused:
             print("Slider seek: Stopping current playback first...")
             if self.video_processor_worker:
                 self.video_processor_worker.stop()
             # Need to wait briefly for thread to potentially stop before restarting
             # A better approach might use signals to confirm stop before restarting
             # For simplicity now, we restart directly, potentially overlapping slightly
             # Let cleanup_after_processing handle UI reset before starting new one
             QTimer.singleShot(100, lambda: self.start_detection(start_frame=position))
        else:
            # If stopped, just update the current frame number for the next play
            self.current_frame_num = position + 1



    # --- Video Saving ---
    def save_video(self):
        if not self.model or not self.video_path:
            QMessageBox.warning(self, "Cannot Save", "Model and video file must be loaded.")
            return
        if self.video_saver_thread and self.video_saver_thread.isRunning():
            QMessageBox.information(self, "Already Saving", "Video saving process is already running.")
            return
        if self.is_playing or self.is_paused:
            QMessageBox.warning(self, "Cannot Save", "Please stop video playback before saving.")
            return


        # Open file dialog to select save location
        default_filename = Path(self.video_path).stem + "_processed.mp4"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Processed Video As",
            default_filename,
            "Video Files (*.mp4 *.avi *.mkv);;All Files (*.*)"
        )

        if save_path:
            print(f"Starting background video save to: {save_path}")
            self.status_bar.showMessage(f"Saving video to {os.path.basename(save_path)}...")

            # --- Setup Saver Thread ---
            self.video_saver_thread = QThread(self)
            self.video_saver_worker = VideoSaver(self.video_path, save_path, self.model)
            self.video_saver_worker.moveToThread(self.video_saver_thread)

            # --- Setup Progress Dialog ---
            self.save_progress_dialog = QProgressDialog("Saving Video...", "Cancel", 0, 100, self)
            self.save_progress_dialog.setWindowTitle("Processing Video")
            self.save_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.save_progress_dialog.setAutoClose(False) # We'll close it manually
            self.save_progress_dialog.setAutoReset(False)
            self.save_progress_dialog.canceled.connect(self.cancel_save) # Connect cancel signal

            # --- Connect Signals ---
            self.video_saver_thread.started.connect(self.video_saver_worker.run)
            self.video_saver_worker.saveProgress.connect(self.update_save_progress)
            self.video_saver_worker.saveFinished.connect(self.on_save_finished)
            self.video_saver_worker.errorOccurred.connect(self.on_save_error)

            # Cleanup connections
            self.video_saver_worker.saveFinished.connect(self.video_saver_thread.quit)
            self.video_saver_worker.errorOccurred.connect(self.video_saver_thread.quit)
            self.video_saver_thread.finished.connect(self.video_saver_worker.deleteLater)
            self.video_saver_thread.finished.connect(self.video_saver_thread.deleteLater)
            self.video_saver_thread.finished.connect(self.cleanup_after_save)

            self.set_controls_enabled(False) # Disable controls during save
            self.video_saver_thread.start()
            self.save_progress_dialog.setValue(0)
            self.save_progress_dialog.show()

    def update_save_progress(self, value):
        if self.save_progress_dialog:
            self.save_progress_dialog.setValue(value)

    def cancel_save(self):
        print("Cancel save requested by user.")
        if self.video_saver_worker:
            self.video_saver_worker.stop()
        if self.save_progress_dialog:
            self.save_progress_dialog.setLabelText("Cancelling...")

    def on_save_finished(self, output_path):
        print(f"Video saving finished signal received: {output_path}")
        if self.save_progress_dialog:
            self.save_progress_dialog.close()
        QMessageBox.information(self, "Save Complete", f"Video successfully saved to:\n{output_path}")
        self.status_bar.showMessage("Video saved successfully.", 5000)

    def on_save_error(self, error_message):
        print(f"Video saving error signal received: {error_message}")
        if self.save_progress_dialog:
            self.save_progress_dialog.close()
        if "cancelled" not in error_message.lower(): # Don't show critical error if user cancelled
             QMessageBox.critical(self, "Save Error", f"Failed to save video:\n{error_message}")
        self.status_bar.showMessage(f"Video saving failed or cancelled.", 5000)

    def cleanup_after_save(self):
        print("Cleaning up after video saving thread.")
        self.set_controls_enabled(True) # Re-enable controls
        if self.save_progress_dialog:
            self.save_progress_dialog.deleteLater() # Ensure dialog is destroyed
            self.save_progress_dialog = None
        self.video_saver_thread = None # Allow garbage collection
        self.video_saver_worker = None

    def set_controls_enabled(self, enabled):
         """ Helper to enable/disable main controls """
         self.load_model_button.setEnabled(enabled) # Manage load model button
         self.file_button.setEnabled(enabled)
         self.play_pause_button.setEnabled(enabled and self.video_path is not None and self.model is not None)
         # Stop button state depends on playback, handled separately
         self.save_button.setEnabled(enabled and self.video_path is not None and self.model is not None)
         self.slider.setEnabled(enabled and self.video_path is not None and self.model is not None)


    # --- Window Events ---
    def toggle_fullscreen(self, checked):
        if checked:
            self.showFullScreen()
            # Hide controls widget if it exists
            controls = self.centralWidget().layout().itemAt(1)
            if controls and controls.widget():
                controls.widget().hide()
            # Hide slider layout if it exists
            slider = self.centralWidget().layout().itemAt(2)
            if slider and slider.widget():
                slider.widget().hide()
            # Hide status bar if it exists
            status_bar = self.statusBar()
            if status_bar:
                status_bar.hide()
            self.fullscreen_button.setText("Exit Fullscreen")
            self.fullscreen_button.setParent(self)
            self.fullscreen_button.move(self.width() - self.fullscreen_button.width() - 10, 10)
            self.fullscreen_button.show()
        else:
            self.showNormal()
            controls = self.centralWidget().layout().itemAt(1)
            if controls and controls.widget():
                controls.widget().show()
            slider = self.centralWidget().layout().itemAt(2)
            if slider and slider.widget():
                slider.widget().show()
            status_bar = self.statusBar()
            if status_bar:
                status_bar.show()
            self.fullscreen_button.setText("Fullscreen")
            QTimer.singleShot(0, lambda: self.resize_video_label())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_video_label()
        if self.isFullScreen():
             # Reposition button if needed
             if hasattr(self, 'fullscreen_button'):
                 self.fullscreen_button.move(self.width() - self.fullscreen_button.width() - 10, 10)

    def resize_video_label(self):
         if hasattr(self, 'video_label') and self.video_label.pixmap() and not self.video_label.pixmap().isNull():
             # Rescale pixmap when window resizes
             current_pixmap = self.video_label.pixmap()
             # Use the actual pixmap size, not label size for scaling source
             original_pixmap = QPixmapCache.find("original_frame") # Get original if stored
             if not original_pixmap: original_pixmap = current_pixmap # Fallback

             scaled_pixmap = original_pixmap.scaled(self.video_label.size(),
                                                  Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation)
             self.video_label.setPixmap(scaled_pixmap)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.fullscreen_button.setChecked(False) # Trigger toggle_fullscreen(False)
        elif event.key() == Qt.Key.Key_Space and self.play_pause_button.isEnabled():
             self.toggle_play_pause() # Allow spacebar for play/pause
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.video_label.geometry().contains(event.pos()):
             self.fullscreen_button.toggle() # Toggle fullscreen on double-click
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event):
        print("Close event triggered.")
        # Stop all threads gracefully
        if self.video_processor_worker:
            self.video_processor_worker.stop()
        if self.model_loader_worker:
             # Model loading is usually fast, but handle if it's mid-export
             pass # Let it finish or handle cancellation if needed
        if self.video_saver_worker:
            reply = QMessageBox.question(self, "Save in Progress",
                                         "A video save operation is running. Quit anyway?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                 self.video_saver_worker.stop()
            else:
                 event.ignore() # Don't close
                 return

        # Wait briefly for threads to acknowledge stop signals if necessary
        if self.video_processor_thread and self.video_processor_thread.isRunning():
             print("Waiting for video processor thread to finish...")
             self.video_processor_thread.quit()
             self.video_processor_thread.wait(2000) # Wait max 2 secs
        if self.model_loader_thread and self.model_loader_thread.isRunning():
             print("Waiting for model loader thread to finish...")
             self.model_loader_thread.quit()
             self.model_loader_thread.wait(5000) # Wait longer for potential export
        if self.video_saver_thread and self.video_saver_thread.isRunning():
             print("Waiting for video saver thread to finish...")
             self.video_saver_thread.quit()
             self.video_saver_thread.wait(2000)

        print("Exiting application.")
        event.accept() # Proceed with closing


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # --- Apply Dark Theme ---
    app.setStyle(QStyleFactory.create('Fusion')) # Fusion style often works well with palettes
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35)) # Darker base for inputs
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.black) # Tooltip background
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218)) # Selection highlight
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black) # Text on highlight

    # Set colors for disabled state
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))

    app.setPalette(dark_palette)
    app.setStyleSheet("QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }") # Style tooltips

    # --- Run Application ---
    window = ObjectDetectionApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE videodet_pyqt6.py ---