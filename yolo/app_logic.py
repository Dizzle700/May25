"""
AppLogic module - Connects UI events to backend logic (PyQt6 version)
"""

import os
import cv2
from PyQt6.QtCore import QObject, pyqtSignal, QThread, pyqtSlot, QMutex, QMutexLocker, QRect, QSettings, QCoreApplication, QDir
from PyQt6.QtWidgets import QMessageBox # Use directly for icons
import numpy as np
from typing import List, Dict, Any, Optional

# Use local imports due to flat structure
from data_handler import DataHandler
from yolo_processor import YoloProcessor
from image_augmenter import ImageAugmenter
from main_window import MainWindow # Need main window type hint

# --- Worker Threads ---

class WorkerSignals(QObject):
    """Defines signals available from worker threads."""
    progress = pyqtSignal(int, int, str)  # current, total, status_message
    result = pyqtSignal(object)           # Emit results (type depends on worker)
    error = pyqtSignal(str)               # Emit error message
    finished = pyqtSignal()               # Emit when finished

class DetectionWorker(QThread):
    """Worker thread for running object detection."""
    def __init__(self, yolo_processor: YoloProcessor, image_path: str, config: dict):
        super().__init__()
        self.signals = WorkerSignals()
        self.yolo_processor = yolo_processor
        self.image_path = image_path
        self.conf_threshold = config.get('conf_threshold', 0.25)
        self.iou_threshold = config.get('iou_threshold', 0.45)
        self._is_running = True

    def run(self):
        try:
            if not self._is_running: return
            self.signals.progress.emit(0, 1, f"Detecting: {os.path.basename(self.image_path)}...")

            detections = self.yolo_processor.detect(
                self.image_path,
                conf_threshold=self.conf_threshold,
                iou_threshold=self.iou_threshold
            )

            if not self._is_running: return # Check again after potentially long detection

            if detections is None:
                self.signals.error.emit(f"Detection failed for {os.path.basename(self.image_path)}")
            else:
                self.signals.progress.emit(1, 1, f"Detected {len(detections)} objects")
                self.signals.result.emit({'image_path': self.image_path, 'detections': detections})

        except Exception as e:
            self.signals.error.emit(f"Detection Error: {e}")
        finally:
            self.signals.finished.emit()

    def stop(self):
        self._is_running = False


class SaveDatasetWorker(QThread):
    """Worker thread for augmenting (optional) and saving the dataset."""
    def __init__(self, data_handler: DataHandler, image_augmenter: ImageAugmenter,
                 output_dir: str, config: dict):
        super().__init__()
        self.signals = WorkerSignals()
        self.data_handler = data_handler
        self.image_augmenter = image_augmenter
        self.output_dir = output_dir
        self.train_split = config.get('train_split', 0.8)
        self.num_augmentations = config.get('augment_count', 0) # Get count from config
        self._is_running = True
        self.signals._error_emitted = False # Helper flag for progress callback

    def run(self):
        total_steps = 1 # Start with 1 step for saving
        current_step = 0
        annotated_image_paths = []

        try:
            # --- Step 0: Setup --- #
            def progress_callback(current, total, message):
                if not self._is_running: raise InterruptedError("Operation cancelled")
                # Adjust progress based on overall steps (augmentation + saving)
                save_progress_fraction = total / total_steps
                overall_progress = (current_step + current * save_progress_fraction)
                self.signals.progress.emit(int(overall_progress), total_steps * 100, message) # Scale total for percentage

            # --- Step 1 (Optional): Augmentation --- #
            if self.num_augmentations > 0:
                self.data_handler.clear_augmented_images() # Clear previous augmentations
                annotated_image_paths = [
                    path for path, annotations in self.data_handler.annotations.items()
                    if any(ann.get('class_id', -1) >= 0 for ann in annotations)
                ]
                if not annotated_image_paths:
                    self.signals.error.emit("No images with assigned annotations to augment.")
                    self.signals._error_emitted = True # Prevent double error messages
                    return # Stop if nothing to augment

                total_aug_images = len(annotated_image_paths)
                total_steps += total_aug_images # Add augmentation steps
                self.signals.progress.emit(0, total_steps * 100, f"Starting augmentation ({self.num_augmentations} per image)...")

                for i, image_path in enumerate(annotated_image_paths):
                    if not self._is_running: return
                    current_step = i + 1 # Current overall step
                    self.signals.progress.emit(current_step * 100, total_steps * 100, f"Augmenting {i+1}/{total_aug_images}: {os.path.basename(image_path)}")

                    annotations = self.data_handler.annotations[image_path]
                    img_bgr = cv2.imread(image_path)

                    if img_bgr is None or not annotations:
                        print(f"Warning: Skipping augmentation for {image_path} (load fail or no annotations).")
                        continue

                    augmented_data = self.image_augmenter.augment_image(
                        img_bgr, annotations, self.num_augmentations
                    )

                    # Store results directly in data_handler
                    if augmented_data:
                        self.data_handler.add_augmented_images(image_path, augmented_data)

            # --- Step 2: Save Dataset --- #
            current_step = total_steps -1 # Saving is the last step
            if not self._is_running: return
            self.signals.progress.emit(current_step * 100, total_steps * 100, "Starting dataset save...")

            success = self.data_handler.save_yolo_dataset(
                self.output_dir,
                train_split=self.train_split,
                progress_callback=progress_callback
            )

            if not self._is_running: return

            if success:
                final_path = os.path.join(self.output_dir, 'yolo_dataset')
                self.signals.result.emit(final_path)
            else:
                 if not self.signals._error_emitted:
                      self.signals.error.emit("Failed to save dataset (unknown reason).")

        except InterruptedError:
             self.signals.error.emit("Dataset save cancelled.")
        except Exception as e:
            # Ensure the error flag is set if an exception occurs before the standard emit
            if not self.signals._error_emitted:
                 self.signals.error.emit(f"Save Dataset Error: {e}")
                 self.signals._error_emitted = True
            import traceback
            traceback.print_exc() # Print full traceback for debugging
        finally:
            self.signals.finished.emit()

    def stop(self):
        self._is_running = False # Stop loop / allow progress callback to raise InterruptedError
        # Don't reset _error_emitted here, let it be handled by the main logic


# --- App Logic Controller ---

class AppLogic(QObject):
    """Application logic controller connecting UI and backend."""

    # Signals to update UI (more specific than before)
    statusChanged = pyqtSignal(str, int) # message, timeout (0=persistent)
    progressChanged = pyqtSignal(int, int) # current, total
    imageDisplayRequested = pyqtSignal(str) # image_path
    annotationsChanged = pyqtSignal(list) # New annotations for current image
    classListChanged = pyqtSignal(list) # Full list of class names
    uiStateUpdated = pyqtSignal(dict) # Send dict of enabled states for buttons etc.
    configUpdateRequest = pyqtSignal(dict) # Request UI update config values (e.g., after load)
    projectStateChanged = pyqtSignal(str, bool) # project_path, is_dirty

    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        self.data_handler = DataHandler()
        self.yolo_processor = YoloProcessor()
        self.image_augmenter = ImageAugmenter()

        # State
        self.current_image_path: Optional[str] = None
        self.current_config: Dict = self.main_window.get_config() # Initial config
        self._is_processing: bool = False # Flag for background tasks
        self._current_worker: Optional[QThread] = None
        self.current_project_path: Optional[str] = None

        # Get initial/default aug options and populate menu
        initial_aug_options = self.image_augmenter.get_augmentation_options()
        self.main_window.populate_augment_menu(initial_aug_options)
        # Note: MainWindow._read_augmentation_settings will override defaults if settings exist
        # Now read the *actual* initial state from the UI (which includes loaded settings)
        self._update_augmenter_from_ui()

        self._connect_signals()
        self._update_ui_state() # Initial UI state

        # Attempt to load last project on startup
        self._load_last_project()

    def _connect_signals(self):
        """Connect signals from UI and workers to logic slots."""
        mw = self.main_window
        mw.addImagesClicked.connect(self._on_add_images)
        mw.selectModelClicked.connect(self._on_select_model)
        mw.processImageClicked.connect(self._on_process_image)
        mw.saveDatasetClicked.connect(self._on_save_dataset)
        mw.addClassClicked.connect(self._on_add_class)
        mw.removeClassClicked.connect(self._on_remove_class)
        mw.imageSelected.connect(self._on_image_selected_in_list)
        mw.classSelected.connect(self._on_class_selected_in_list)
        mw.configChanged.connect(self._on_config_changed)
        mw.drawBoxClicked.connect(self._on_draw_box_toggled)
        mw.deleteSelectedBoxClicked.connect(self._on_delete_selected_box)
        mw.image_canvas.newBoxDrawn.connect(self._on_new_box_drawn)
        mw.image_canvas.boxSelected.connect(self._on_box_selected_in_canvas)
        mw.augmentationOptionsChanged.connect(self._on_augmentation_options_changed) # Connect new signal

        # Add connections for project file operations (assuming MainWindow emits these)
        mw.openProjectRequested.connect(self.open_project)
        mw.saveProjectRequested.connect(self.save_project)
        mw.saveProjectAsRequested.connect(self.save_project_as)

        # Logic -> UI
        self.statusChanged.connect(mw.set_status)
        self.progressChanged.connect(mw.set_progress)
        self.imageDisplayRequested.connect(mw.display_image)
        self.annotationsChanged.connect(mw.update_annotations)
        self.classListChanged.connect(mw.update_class_names_display)
        self.projectStateChanged.connect(mw._update_window_title) # Connect to update window title
        # self.uiStateUpdated.connect(mw._update_buttons_state) # UI updates itself based on state

    # --- Project Operations ---
    def _load_last_project(self):
        settings = QSettings()
        last_project = settings.value("project/lastProjectPath", "", type=str)
        if last_project and os.path.isfile(last_project):
            print(f"Attempting to load last project: {last_project}")
            self.open_project(last_project)
        else:
            self._update_project_state() # Emit initial state (no project, not dirty)

    def _update_project_state(self):
        """Updates state variables and emits signal based on current project."""
        is_dirty = self.data_handler.is_dirty()
        project_path = self.current_project_path if self.current_project_path else "Unsaved Project"
        self.projectStateChanged.emit(project_path, is_dirty)
        self._update_ui_state() # Update button enabled states etc.

    @pyqtSlot(str)
    def open_project(self, file_path: str):
        if self._check_save_before_proceed():
            if self.data_handler.load_project(file_path):
                self.current_project_path = file_path
                settings = QSettings()
                settings.setValue("project/lastProjectPath", file_path)
                # Trigger UI refresh
                self._reload_ui_from_data()
                self.statusChanged.emit(f"Project '{os.path.basename(file_path)}' loaded.", 3000)
            else:
                self.statusChanged.emit(f"Failed to load project: {file_path}", 5000)
                # Clear potentially partially loaded state
                self.new_project()
            self._update_project_state()

    @pyqtSlot()
    def save_project(self):
        if self.current_project_path:
            if self.data_handler.save_project(self.current_project_path):
                self.statusChanged.emit(f"Project saved to '{os.path.basename(self.current_project_path)}'.", 3000)
                self._update_project_state()
                return True # Indicate success
            else:
                self.statusChanged.emit("Error saving project.", 5000)
                return False # Indicate failure
        else:
            # If no current path, treat as Save As
            return self.main_window._prompt_save_project_as() # Ask MainWindow to trigger the dialog

    @pyqtSlot(str)
    def save_project_as(self, file_path: str):
        if self.data_handler.save_project(file_path):
            self.current_project_path = file_path
            settings = QSettings()
            settings.setValue("project/lastProjectPath", file_path)
            self.statusChanged.emit(f"Project saved as '{os.path.basename(file_path)}'.", 3000)
            self._update_project_state()
            return True # Indicate success
        else:
            self.statusChanged.emit("Error saving project.", 5000)
            return False # Indicate failure

    def new_project(self):
        """Resets the application state for a new project."""
        if self._check_save_before_proceed():
            self.data_handler = DataHandler() # Create a fresh data handler
            self.current_project_path = None
            self.current_image_path = None
            # Reset UI elements
            self._reload_ui_from_data()
            self.statusChanged.emit("New project started.", 3000)
            self._update_project_state()
            return True
        return False

    def _check_save_before_proceed(self) -> bool:
        """Checks if the project is dirty and prompts the user to save. Returns False if cancelled."""
        if not self.data_handler.is_dirty():
            return True # Nothing to save

        project_name = os.path.basename(self.current_project_path) if self.current_project_path else "Unsaved Project"
        reply = QMessageBox.question(self.main_window,
                                     "Unsaved Changes",
                                     f"Project '{project_name}' has unsaved changes.\nDo you want to save them?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Save)

        if reply == QMessageBox.StandardButton.Save:
            return self.save_project() # Returns True on success, False on failure/cancel
        elif reply == QMessageBox.StandardButton.Cancel:
            return False
        else: # Discard
            return True

    def _reload_ui_from_data(self):
        """Refreshes the UI completely based on the current DataHandler state."""
        # Clear existing UI elements
        self.main_window.images_list.clear()
        self.main_window.classes_list.clear()
        self.main_window.image_canvas.set_image(None) # Clear canvas
        self.main_window.update_annotations([]) # Correct: Call the update method directly

        # Load new data
        self.main_window.add_images_to_list(self.data_handler.image_paths)
        self.main_window.update_class_names_display(self.data_handler.class_names)
        self.main_window.set_model_path(self.data_handler.model_path)

        # Select first image if available
        if self.data_handler.image_paths:
            first_image = self.data_handler.image_paths[0]
            self.main_window.images_list.setCurrentRow(0) # This should trigger _on_image_selected_in_list
            # self._on_image_selected_in_list(first_image) # Call directly if setCurrentRow doesn't trigger
        else:
            self.current_image_path = None
            self.imageDisplayRequested.emit(None)
            self.main_window.update_annotations([]) # Correct: Call the update method directly

        # Maybe update config display if loaded from project? (Future enhancement)
        self._update_project_state() # Update title/dirty status


    def _start_worker(self, worker_class, *args):
        """Helper to start a worker thread and manage state."""
        if self._is_processing:
            self.statusChanged.emit("Busy: Another process is running.", 3000)
            return

        self._is_processing = True
        self._update_ui_state(processing=True) # Disable controls

        self._current_worker = worker_class(*args)
        # Connect worker signals dynamically
        self._current_worker.signals.progress.connect(self._handle_worker_progress)
        self._current_worker.signals.result.connect(self._handle_worker_result)
        self._current_worker.signals.error.connect(self._handle_worker_error)
        self._current_worker.signals.finished.connect(self._handle_worker_finished)

        self._current_worker.start()

    # --- UI Action Slots ---

    @pyqtSlot(list)
    def _on_add_images(self, file_paths: List[str]):
        """Handles adding images triggered by the UI."""
        if file_paths:
            added_count = self.data_handler.add_images(file_paths)
            self.main_window.add_images_to_list(file_paths) # Update UI list
            self.statusChanged.emit(f"Added {added_count} new images.", 3000)
            if self.data_handler.is_dirty(): self._update_project_state()
            # Optionally select the first added image
            if added_count > 0 and self.main_window.images_list.count() == added_count:
                 self.main_window.images_list.setCurrentRow(0)

    @pyqtSlot(str)
    def _on_select_model(self, model_path: str):
        """Handles selecting a model triggered by the UI."""
        if self.data_handler.set_model_path(model_path):
            self.yolo_processor.load_model(model_path)
            self.main_window.set_model_path(model_path) # Update UI label
            self.statusChanged.emit(f"Model selected: {os.path.basename(model_path)}", 3000)
            if self.data_handler.is_dirty(): self._update_project_state()
        elif model_path: # Only show error if a path was actually provided but failed
            self.statusChanged.emit(f"Failed to set model path: {model_path}", 5000)
            self.main_window.show_message("Model Error", f"Could not load model file: {model_path}", level="warning")
            # Optionally clear model path in UI if load failed
            # self.main_window.set_model_path(None)
        # If model_path was None (clearing), no error message needed.


    @pyqtSlot()
    def _on_process_image(self):
        """Initiates object detection on the currently selected image."""
        if not self.current_image_path:
            self.statusChanged.emit("No image selected.", 3000)
            return
        if not self.yolo_processor.is_model_loaded():
            self.statusChanged.emit("No model selected or loaded.", 3000)
            self.main_window.show_message("Processing Error", "Please select a valid YOLO model file first.", level="warning")
            return

        config = self.main_window.get_config() # Get current conf/iou
        self._start_worker(DetectionWorker, self.yolo_processor, self.current_image_path, config)

    @pyqtSlot(str)
    def _on_save_dataset(self, output_dir: str):
        """Initiates augmenting (if count > 0) and saving the dataset."""
        if not self.data_handler.class_names:
             self.main_window.show_message("Save Error", "Cannot save dataset without defined classes.", level="warning")
             self.statusChanged.emit("Define classes before saving.", 3000)
             return

        config = self.main_window.get_config()
        num_augmentations = config.get('augment_count', 0)

        # Warn if trying to augment without base annotations
        if num_augmentations > 0 and not any(any(ann.get('class_id', -1) >= 0 for ann in anns) for anns in self.data_handler.annotations.values()):
             self.main_window.show_message("Augmentation Warning", "No annotations with assigned classes found. Augmentation will be skipped.", level="warning")
             # Allow save to proceed, but augmentation won't happen in worker

        # Warn if saving with no annotations at all (original or augmented - worker handles check)
        elif num_augmentations == 0 and not any(any(ann.get('class_id', -1) >= 0 for ann in anns) for anns in self.data_handler.annotations.values()):
             self.main_window.show_message("Save Warning", "No annotations with assigned classes found. The dataset might be empty or incomplete.", level="info")

        self.statusChanged.emit("Starting dataset save...", 0)
        self._start_worker(SaveDatasetWorker, self.data_handler, self.image_augmenter, output_dir, config)

    @pyqtSlot(str)
    def _on_add_class(self, class_name: str):
        """Handles adding a class triggered by the UI."""
        if self.data_handler.add_class(class_name):
            self.classListChanged.emit(self.data_handler.class_names)
            self.statusChanged.emit(f"Class '{class_name}' added.", 2000)
            if self.data_handler.is_dirty(): self._update_project_state()
        else:
            self.statusChanged.emit(f"Class '{class_name}' already exists or is invalid.", 3000)

    @pyqtSlot(str)
    def _on_remove_class(self, class_name: str):
        """Handles removing a class triggered by the UI."""
        # Add confirmation dialog?
        if self.data_handler.remove_class(class_name):
            self.classListChanged.emit(self.data_handler.class_names)
            # Need to update current annotations if a class ID changed
            if self.current_image_path:
                 current_annotations = self.data_handler.annotations.get(self.current_image_path, [])
                 self.annotationsChanged.emit(current_annotations)
            self.statusChanged.emit(f"Class '{class_name}' removed.", 2000)
            if self.data_handler.is_dirty(): self._update_project_state()
        else:
            self.statusChanged.emit(f"Failed to remove class '{class_name}'.", 3000)

    @pyqtSlot(str)
    def _on_image_selected_in_list(self, image_path: str):
        """Handles selecting an image in the UI list."""
        if image_path and image_path != self.current_image_path:
            self.current_image_path = image_path
            self.imageDisplayRequested.emit(image_path)
            current_annotations = self.data_handler.annotations.get(image_path, [])
            self.annotationsChanged.emit(current_annotations)
            # Reset canvas selection when image changes
            self.main_window.image_canvas.select_box(-1)
            self._update_ui_state() # Update process button state etc.
            self.statusChanged.emit(f"Selected: {os.path.basename(image_path)}", 0)
        elif not image_path:
             # Handle case where selection is cleared
             self.current_image_path = None
             self.imageDisplayRequested.emit(None)
             self.main_window.update_annotations([]) # Correct: Call the update method directly
             self._update_ui_state()
             self.statusChanged.emit("No image selected.", 0)


    @pyqtSlot(str)
    def _on_class_selected_in_list(self, class_name: str):
        """Handles selecting a class in the UI list."""
        # If a box is already selected in the canvas, assign this class
        selected_box_index = self.main_window.image_canvas.selected_box_idx
        if self.current_image_path and selected_box_index != -1 and class_name:
            try:
                class_id = self.data_handler.class_names.index(class_name)
                if self.data_handler.assign_class_to_box(self.current_image_path, selected_box_index, class_id):
                    # Update display immediately
                    current_annotations = self.data_handler.annotations.get(self.current_image_path, [])
                    self.annotationsChanged.emit(current_annotations)
                    self.statusChanged.emit(f"Assigned class '{class_name}' to selected box.", 2000)
                    if self.data_handler.is_dirty(): self._update_project_state()
                else:
                     self.statusChanged.emit(f"Failed to assign class '{class_name}'.", 3000)
            except ValueError:
                self.statusChanged.emit(f"Class '{class_name}' not found.", 3000)
        elif class_name:
             # Just selecting the class, no box selected - maybe highlight it?
             self.statusChanged.emit(f"Selected class: {class_name}", 0)
        else:
             # Selection cleared
             pass


    @pyqtSlot(int)
    def _on_box_selected_in_canvas(self, box_index: int):
         """Handles selecting a box directly on the canvas."""
         # If a class is already selected in the list, assign it
         selected_class_item = self.main_window.classes_list.currentItem()
         if self.current_image_path and box_index != -1 and selected_class_item:
             class_name = selected_class_item.text()
             try:
                 class_id = self.data_handler.class_names.index(class_name)
                 if self.data_handler.assign_class_to_box(self.current_image_path, box_index, class_id):
                     # Update display immediately
                     current_annotations = self.data_handler.annotations.get(self.current_image_path, [])
                     self.annotationsChanged.emit(current_annotations)
                     self.statusChanged.emit(f"Assigned class '{class_name}' to selected box.", 2000)
                     if self.data_handler.is_dirty(): self._update_project_state()
                 else:
                      self.statusChanged.emit(f"Failed to assign class '{class_name}'.", 3000)
             except ValueError:
                 self.statusChanged.emit(f"Class '{class_name}' not found.", 3000)
         elif box_index != -1:
             # Box selected, but no class selected. Update status?
             self.statusChanged.emit(f"Box {box_index} selected.", 0)
         else:
             # Selection cleared
             pass


    @pyqtSlot(dict)
    def _on_config_changed(self, config: dict):
        """Handles changes in configuration (confidence, IoU, etc.)."""
        self.current_config = config
        # Potentially re-process if config changes significantly? Or just use for next process.
        # For now, just store it.
        self.statusChanged.emit(f"Config updated: Conf={config['conf_threshold']:.2f}, IoU={config['iou_threshold']:.2f}", 2000)
        # Config changes don't dirty the *project file* itself, but maybe UI settings?

    @pyqtSlot(bool)
    def _on_draw_box_toggled(self, enabled: bool):
        """Handles toggling the draw box mode in the canvas."""
        self.main_window.image_canvas.set_drawing_enabled(enabled)
        status = "Draw Box mode enabled." if enabled else "Draw Box mode disabled."
        self.statusChanged.emit(status, 2000)
        if enabled:
            self.main_window.image_canvas.select_box(-1) # Ensure no box is selected when drawing
            self.main_window.classes_list.clearSelection() # Clear class selection too

    @pyqtSlot(QRect)
    def _on_new_box_drawn(self, box_rect_img: QRect):
        """Handles a new box being drawn on the canvas."""
        if self.current_image_path:
            new_box_index = self.data_handler.add_manual_box(self.current_image_path, box_rect_img)
            if new_box_index != -1:
                current_annotations = self.data_handler.annotations.get(self.current_image_path, [])
                self.annotationsChanged.emit(current_annotations)
                # Automatically select the new box
                self.main_window.image_canvas.select_box(new_box_index)
                self.statusChanged.emit("New box added.", 2000)
                if self.data_handler.is_dirty(): self._update_project_state()
            else:
                 self.statusChanged.emit("Failed to add new box.", 3000)
        else:
             self.statusChanged.emit("Select an image before drawing boxes.", 3000)


    @pyqtSlot()
    def _on_delete_selected_box(self):
        """Handles deleting the currently selected box."""
        selected_box_index = self.main_window.image_canvas.selected_box_idx
        if self.current_image_path and selected_box_index != -1:
            if self.data_handler.delete_box(self.current_image_path, selected_box_index):
                current_annotations = self.data_handler.annotations.get(self.current_image_path, [])
                self.annotationsChanged.emit(current_annotations)
                self.main_window.image_canvas.select_box(-1) # Deselect after delete
                self.statusChanged.emit("Selected box deleted.", 2000)
                if self.data_handler.is_dirty(): self._update_project_state()
            else:
                 self.statusChanged.emit("Failed to delete selected box.", 3000)
        else:
             self.statusChanged.emit("No box selected to delete.", 3000)

    @pyqtSlot(dict)
    def _on_augmentation_options_changed(self, options: dict):
        """Updates the image augmenter when UI options change."""
        self.image_augmenter.update_transform(options)
        # Maybe mark project dirty if aug options should be saved with project?
        # For now, treating them as UI settings saved separately.

    def _update_augmenter_from_ui(self):
         """Ensures the augmenter's state matches the UI's initial state (after settings load)."""
         if hasattr(self.main_window, 'augment_actions'): # Check if menu populated
              current_ui_options = {name: action.isChecked()
                                    for name, action in self.main_window.augment_actions.items()}
              if current_ui_options:
                  self.image_augmenter.update_transform(current_ui_options)

    # --- Worker Signal Handlers ---

    @pyqtSlot(int, int, str)
    def _handle_worker_progress(self, current: int, total: int, message: str):
        """Updates the progress bar and status bar."""
        self.progressChanged.emit(current, total)
        self.statusChanged.emit(message, 0) # Persistent status during operation

    @pyqtSlot(object)
    def _handle_worker_result(self, result):
        """Handles results from worker threads."""
        worker_type = type(self._current_worker)

        if worker_type is DetectionWorker:
            image_path = result['image_path']
            detections = result['detections']
            # Update data handler - this also sets dirty flag if needed
            self.data_handler.update_annotations_from_detections(image_path, detections)
            # If the processed image is the currently viewed one, update display
            if image_path == self.current_image_path:
                self.annotationsChanged.emit(self.data_handler.annotations[image_path])
            self.statusChanged.emit(f"Processing finished for {os.path.basename(image_path)}. {len(detections)} boxes found.", 3000)
            if self.data_handler.is_dirty(): self._update_project_state()

        elif worker_type is SaveDatasetWorker:
             dataset_path = result
             num_aug = self.current_config.get('augment_count', 0) # Get count used for save
             msg = f"Dataset saved successfully to {dataset_path}"
             if num_aug > 0:
                  msg += f" (including {num_aug} augmentation(s) per image)."
             else:
                  msg += "."
             self.statusChanged.emit(msg, 5000)
             self.main_window.show_message("Save Successful", f"YOLO dataset saved to:\n{dataset_path}", level="info")
             # Saving dataset doesn't dirty the project file
        else:
             print(f"Warning: Received result from unknown worker type: {worker_type}")


    @pyqtSlot(str)
    def _handle_worker_error(self, error_msg: str):
        """Displays errors from worker threads."""
        print(f"Worker Error: {error_msg}")
        self.statusChanged.emit(f"Error: {error_msg}", 5000)
        self.main_window.show_message("Worker Error", error_msg, level="error")

    @pyqtSlot()
    def _handle_worker_finished(self):
        """Cleans up after a worker thread finishes."""
        self.statusChanged.emit("Ready", 0) # Reset status to Ready
        self.progressChanged.emit(0, 100) # Reset progress bar
        self._is_processing = False
        self._current_worker = None
        self._update_ui_state(processing=False) # Re-enable controls

    def _update_ui_state(self, processing: Optional[bool] = None):
        """Updates the enabled/disabled state of UI elements based on app state."""
        if processing is None:
            processing = self._is_processing

        has_images = bool(self.data_handler.image_paths)
        has_model = self.yolo_processor.is_model_loaded()
        image_selected = self.current_image_path is not None
        box_selected = image_selected and self.main_window.image_canvas.selected_box_idx != -1
        has_classes = bool(self.data_handler.class_names)
        class_selected = self.main_window.classes_list.currentItem() is not None
        is_drawing = self.main_window.image_canvas._is_drawing_enabled
        is_dirty = self.data_handler.is_dirty()

        state = {
            # Base operations
            'enable_add_images': not processing,
            'enable_select_model': not processing,
            # Processing actions
            'enable_process': not processing and has_model and image_selected,
            'enable_save_dataset': not processing and has_images and has_classes,
            # Class management
            'enable_add_class': not processing,
            'enable_remove_class': not processing and class_selected,
            # Canvas interactions
            'enable_canvas_interaction': not processing and image_selected,
            'enable_delete_box': not processing and box_selected and not is_drawing,
            'enable_draw_box': not processing and image_selected,
            # Project operations
            'enable_save_project': not processing and (is_dirty or not self.current_project_path),
            'enable_save_project_as': not processing and has_images,
            'enable_close_project': not processing,
        }
        self.main_window._update_buttons_state(state) # Send comprehensive state to MainWindow

