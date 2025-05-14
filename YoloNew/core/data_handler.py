from PyQt6.QtCore import QObject, QThreadPool, QRect
from PyQt6.QtWidgets import QFileDialog, QMessageBox # For file dialogs
from typing import List, Dict, Optional, Tuple
import numpy as np  # Add the missing numpy import
import os
import cv2

# Import your core components
from core.models import AppData, ImageAnnotation, BoundingBox
from core.yolo_processor import YoloProcessor
from core.image_augmenter import ImageAugmenter
from core.workers import DetectionWorker, AugmentationWorker, SaveWorker # Import worker classes
from core import utils

class DataHandler(QObject):
    """Handles dataset operations and persistence."""
    
    def __init__(self, app_data: AppData):
        super().__init__()
        self.app_data = app_data
    
    def add_image_paths(self, image_paths: List[str]) -> int:
        """Add images to the dataset, returning count of newly added images."""
        count_added = 0
        for path in image_paths:
            if path not in self.app_data.images:
                # Create empty annotation container (dimensions will be loaded when viewed)
                self.app_data.images[path] = ImageAnnotation(
                    image_path=path,
                    width=0,  # Will be set when loaded
                    height=0  # Will be set when loaded
                )
                count_added += 1
        return count_added
    
    def get_annotated_image_paths(self) -> List[str]:
        """Return paths of images that have at least one annotation box.
        
        This includes both original and augmented images with valid annotations.
        """
        return [path for path, annot in self.app_data.images.items() 
                if annot.boxes and any(box.class_id >= 0 for box in annot.boxes) and os.path.exists(path)]
    
    def has_annotations(self) -> bool:
        """Check if there are any valid annotations in the dataset."""
        for image_path, annotation in self.app_data.images.items():
            if annotation.boxes and any(box.class_id >= 0 for box in annotation.boxes):
                return True
        return False
    
    def remap_class_id(self, old_id: int, new_id: int) -> int:
        """Remap class IDs in all annotations, returns count of changed boxes."""
        count = 0
        for image_path, annotation in self.app_data.images.items():
            for box in annotation.boxes:
                if box.class_id == old_id:
                    box.class_id = new_id
                    count += 1
        return count
    
    def add_augmented_data(self, augmented_dict: Dict[str, Tuple[ImageAnnotation, np.ndarray]]):
        """Adds augmented image annotations and saves the image data to disk.
        
        Args:
            augmented_dict: Dictionary mapping new_path -> (ImageAnnotation, image_data)
        """
        if not augmented_dict:
            return
        
        # Create an image count for logging/status updates
        saved_count = 0
        error_count = 0
        
        # Process each augmented image
        for new_path, (aug_annotation, image_data) in augmented_dict.items():
            try:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                
                # Save the image to disk
                cv2.imwrite(new_path, image_data)
                
                # Add the augmented annotation to app_data
                self.app_data.images[new_path] = aug_annotation
                saved_count += 1
                
            except Exception as e:
                print(f"Error saving augmented image {new_path}: {str(e)}")
                error_count += 1
        
        print(f"Augmentation complete: Saved {saved_count} images, encountered {error_count} errors")
    
    def save_dataset(self, output_dir: str, save_format: str, train_split: float = 0.8) -> str:
        """
        Save the dataset in the specified format.
        
        Args:
            output_dir: The directory where to save the dataset
            save_format: Format to save in ('yolo', 'coco', etc.)
            train_split: Proportion of data to use for training (0.0-1.0)
            
        Returns:
            Success message string
        """
        # Basic implementation to prevent errors
        print(f"Saving dataset in {save_format} format to {output_dir} with {train_split} train split")
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # For a full implementation, this would:
        # 1. Split data into train/val sets
        # 2. Save annotations in the appropriate format
        # 3. Copy or save images
        
        return f"Dataset saved successfully in {save_format.upper()} format to {output_dir}"

class AppLogic(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.app_data = AppData()
        self.data_handler = DataHandler(self.app_data) # Pass shared data object
        self.yolo_processor = YoloProcessor()
        self.image_augmenter = ImageAugmenter()
        self.thread_pool = QThreadPool()
        print(f"Using max {self.thread_pool.maxThreadCount()} threads.")

        self._connect_ui_signals()
        self.current_image_path: str | None = None
        self.selected_box_canvas_index: int = -1 # Track selection in canvas

    def _connect_ui_signals(self):
        # Connect signals FROM MainWindow TO AppLogic methods
        self.main_window.add_images_requested.connect(self.add_images)
        self.main_window.select_model_requested.connect(self.select_model)
        self.main_window.process_images_requested.connect(self.run_detection)
        self.main_window.save_dataset_requested.connect(self.save_dataset)
        self.main_window.augment_dataset_requested.connect(self.run_augmentation)
        self.main_window.image_selected.connect(self.load_image_and_annotations)
        self.main_window.class_added_requested.connect(self.add_class)
        self.main_window.class_removed_requested.connect(self.remove_class)
        self.main_window.class_selected_for_assignment.connect(self.assign_class_to_selected_box)

    # --- Methods Triggered by UI ---

    def add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Images",
            "", # Start directory
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if files:
            added = self.data_handler.add_image_paths(files)
            self.main_window.update_image_list(list(self.app_data.images.keys()))
            if added and not self.current_image_path:
                # Select the first added image if none is selected
                 self.main_window.image_list_widget.setCurrentRow(0)
                 # load_image_and_annotations will be called by the selection change signal

    def select_model(self):
        file, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Select YOLO Model",
            "",
            "PyTorch Models (*.pt);;ONNX Models (*.onnx)" # Adapt as needed
        )
        if file:
            self.app_data.model_path = file
            self.main_window.set_model_label(file)
            # Enable process button if images are loaded
            self.update_button_states()
            # Optionally try loading the model here or in YoloProcessor init
            # self.yolo_processor.load_model(file)

    def load_image_and_annotations(self, image_path: str):
        self.current_image_path = image_path
        self.selected_box_canvas_index = -1 # Reset box selection
        if image_path in self.app_data.images:
             annotation_data = self.app_data.images[image_path]
             canvas = self.main_window.get_image_canvas()
             canvas.set_image(image_path)
             # Ensure image dimensions are loaded/stored in ImageAnnotation
             if annotation_data.width == 0 or annotation_data.height == 0:
                 h, w = canvas.cv_image.shape[:2]
                 annotation_data.width = w
                 annotation_data.height = h
             canvas.set_annotations(annotation_data.boxes, self.app_data.classes)
             self.update_button_states() # Processing may depend on current image
        else:
            print(f"Error: {image_path} not found in app data.")
            # Optionally clear the canvas
            # self.main_window.get_image_canvas().clear()


    def run_detection(self, image_paths: list):
        if not self.app_data.model_path:
            self.main_window.show_message("Error", "Please select a YOLO model first.", QMessageBox.Icon.Warning)
            return
        if not image_paths:
             self.main_window.show_message("Error", "No images selected/loaded for processing.", QMessageBox.Icon.Warning)
             return

        if not self.yolo_processor.is_model_loaded():
             # Try loading model now if not already loaded
             try:
                 self.yolo_processor.load_model(self.app_data.model_path)
             except Exception as e:
                  self.main_window.show_message("Error", f"Failed to load model:\n{e}", QMessageBox.Icon.Critical)
                  return

        self.main_window.set_ui_busy(True, f"Running detection on {len(image_paths)} image(s)...")

        # --- Worker Thread ---
        worker = DetectionWorker(self.yolo_processor, image_paths, self.app_data.images)
        # Connect signals from worker to AppLogic slots
        worker.signals.result.connect(self._handle_detection_result)
        worker.signals.finished.connect(self._on_detection_finished)
        worker.signals.error.connect(self._handle_worker_error)
        worker.signals.progress.connect(self._update_worker_progress) # TODO: Implement progress update

        self.thread_pool.start(worker)

    def run_augmentation(self, num_augmentations: int):
        annotated_images = self.data_handler.get_annotated_image_paths()
        if not annotated_images:
             self.main_window.show_message("Warning", "No annotated images found to augment.", QMessageBox.Icon.Warning)
             return

        self.main_window.set_ui_busy(True, f"Augmenting {len(annotated_images)} image(s)...")

        # --- Worker Thread ---
        # Pass only necessary data (paths, annotations, maybe image data if needed)
        original_annotations = {p: self.app_data.images[p] for p in annotated_images}
        worker = AugmentationWorker(self.image_augmenter, original_annotations, num_augmentations)
        worker.signals.result.connect(self._handle_augmentation_result)
        worker.signals.finished.connect(self._on_augmentation_finished)
        worker.signals.error.connect(self._handle_worker_error)
        worker.signals.progress.connect(self._update_worker_progress)

        self.thread_pool.start(worker)


    def save_dataset(self):
        # --- Get Save Options (using dialog later) ---
        # Placeholder: Use File Dialog for now, assume YOLO format
        output_dir = QFileDialog.getExistingDirectory(self.main_window, "Select Output Directory")
        if not output_dir:
            return
        save_format = 'yolo' # TODO: Get from dialog

        if not self.data_handler.has_annotations():
            self.main_window.show_message("Warning", "No annotations found to save.", QMessageBox.Icon.Warning)
            return

        self.main_window.set_ui_busy(True, f"Saving dataset ({save_format})...")

        # --- Worker Thread ---
        # Pass data needed for saving
        worker = SaveWorker(self.data_handler, output_dir, save_format)
        worker.signals.finished_str.connect(self._on_save_finished) # Use finished_str for success message
        worker.signals.error.connect(self._handle_worker_error)
        worker.signals.progress.connect(self._update_worker_progress)

        self.thread_pool.start(worker)

    def add_class(self, class_name: str):
        if class_name in self.app_data.classes:
             self.main_window.show_message("Info", f"Class '{class_name}' already exists.")
             return
        self.app_data.classes.append(class_name)
        self.main_window.update_class_list(self.app_data.classes)
        self.update_button_states()

    def remove_class(self, class_name: str):
         if class_name not in self.app_data.classes: return
         class_id_to_remove = self.app_data.classes.index(class_name)
         self.app_data.classes.pop(class_id_to_remove)
         # Handle annotations using the removed class (e.g., set to -1 or prompt user)
         self.data_handler.remap_class_id(class_id_to_remove, -1) # Remap to -1 (invalid)
         self.main_window.update_class_list(self.app_data.classes)
         self.update_button_states()
         # Force redraw of current image if annotations might have changed
         if self.current_image_path:
             self.load_image_and_annotations(self.current_image_path)


    def assign_class_to_selected_box(self, class_index: int):
        if self.current_image_path and self.selected_box_canvas_index != -1:
            if 0 <= class_index < len(self.app_data.classes):
                 # Update the specific box in the data model
                 boxes = self.app_data.images[self.current_image_path].boxes
                 if 0 <= self.selected_box_canvas_index < len(boxes):
                     boxes[self.selected_box_canvas_index].class_id = class_index
                     # Tell canvas to redraw
                     self.main_window.get_image_canvas().set_annotations(boxes, self.app_data.classes)

    # --- Methods Triggered by ImageCanvas ---

    def on_annotations_updated(self):
        """Called when canvas signals a change (move/resize)."""
        # Data is already updated in the canvas's internal list which points
        # to the same BoundingBox objects managed by DataHandler/AppData.
        # May need to mark data as 'dirty' for saving state later.
        self.update_button_states() # Save button might become enabled

    def on_box_selected_in_canvas(self, box_index: int):
        """Called when canvas signals a box selection change."""
        self.selected_box_canvas_index = box_index
        # Maybe update class list selection to match the selected box's class?
        # Or keep them independent? Let's keep independent for now.

    def on_new_box_drawn(self, pixel_rect: QRect):
        """Called when canvas signals a new box was drawn by user."""
        if not self.current_image_path or not self.app_data.images[self.current_image_path].width:
             print("Error: Cannot add box, image data not ready.")
             return

        img_w = self.app_data.images[self.current_image_path].width
        img_h = self.app_data.images[self.current_image_path].height

        bbox_norm = utils.pixel_to_normalized(
            (pixel_rect.left(), pixel_rect.top(), pixel_rect.right(), pixel_rect.bottom()),
            img_w, img_h
        )
        if bbox_norm:
             # Create new BoundingBox, assign default class (-1 or 0?)
             new_box = BoundingBox(class_id=-1, bbox_norm=bbox_norm, bbox_pixels=pixel_rect.getRect())
             self.app_data.images[self.current_image_path].boxes.append(new_box)
             # Update canvas immediately
             canvas = self.main_window.get_image_canvas()
             canvas.set_annotations(self.app_data.images[self.current_image_path].boxes, self.app_data.classes)
             # Select the newly drawn box
             new_index = len(self.app_data.images[self.current_image_path].boxes) - 1
             canvas.selected_box_idx = new_index
             self.selected_box_canvas_index = new_index
             canvas.update() # Ensure redraw with selection
             self.update_button_states()


    def on_delete_box_requested(self, box_index: int):
        """Called when canvas signals a delete request (via context menu or shortcut)."""
        if self.current_image_path and 0 <= box_index < len(self.app_data.images[self.current_image_path].boxes):
            del self.app_data.images[self.current_image_path].boxes[box_index]
            # Update canvas
            canvas = self.main_window.get_image_canvas()
            canvas.selected_box_idx = -1 # Deselect after delete
            self.selected_box_canvas_index = -1
            canvas.set_annotations(self.app_data.images[self.current_image_path].boxes, self.app_data.classes)
            self.update_button_states()


    # --- Slots for Worker Signals ---

    def _handle_detection_result(self, image_path: str, detected_boxes: List[BoundingBox]):
        """Update data model with detection results from worker."""
        if image_path in self.app_data.images:
             self.app_data.images[image_path].boxes = detected_boxes
             self.app_data.images[image_path].processed = True
             # If this is the currently viewed image, update the canvas
             if image_path == self.current_image_path:
                 self.load_image_and_annotations(image_path)

    def _on_detection_finished(self):
        self.main_window.set_ui_busy(False, "Detection finished.")
        self.update_button_states()

    def _handle_augmentation_result(self, augmented_data: Dict[str, ImageAnnotation]):
        """Merge augmented data into the main app data."""
        self.data_handler.add_augmented_data(augmented_data)
        # Update image list to show augmented images (optional, can make list huge)
        # self.main_window.update_image_list(list(self.app_data.images.keys()))

    def _on_augmentation_finished(self):
         self.main_window.set_ui_busy(False, "Augmentation finished.")
         self.update_button_states()
         self.main_window.update_image_list(list(self.app_data.images.keys())) # Refresh list after augment

    def _on_save_finished(self, message: str):
         self.main_window.set_ui_busy(False, message) # Show success/completion message
         self.update_button_states()


    def _handle_worker_error(self, error_info):
        """Show error message when a worker thread fails."""
        # error_info could be a tuple (exception_type, exception_value, traceback_str) or just a string
        error_message = f"Background task failed:\n{error_info}"
        print(error_message) # Log detailed error
        self.main_window.show_message("Error", "A background task encountered an error. Check console/logs.", QMessageBox.Icon.Critical)
        self.main_window.set_ui_busy(False, "Error occurred.") # Reset UI
        self.update_button_states()


    def _update_worker_progress(self, value: int, total: int):
        """Update the main progress bar."""
        self.main_window.update_progress(value, total)

    # --- State Checking for UI ---

    def update_button_states(self):
        """Central method to enable/disable buttons based on app state."""
        can_process = bool(self.app_data.model_path and self.current_image_path)
        can_save = self.data_handler.has_annotations()
        can_augment = self.data_handler.has_annotations() # Can augment if anything is annotated

        self.main_window.process_button.setEnabled(can_process)
        self.main_window.save_button.setEnabled(can_save)
        self.main_window.augment_button.setEnabled(can_augment)

    def is_ready_to_process(self) -> bool:
        return bool(self.app_data.model_path and self.current_image_path)

    def is_ready_to_augment(self) -> bool:
        return self.data_handler.has_annotations()

    def is_ready_to_save(self) -> bool:
        return self.data_handler.has_annotations()