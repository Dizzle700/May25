from PyQt6.QtCore import QObject, QThreadPool, QRect, QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox # For file dialogs
from typing import List, Dict, Optional, Tuple  # Add typing imports
import cv2
import os
import random
import copy

# Import your core components
from core.models import AppData, ImageAnnotation, BoundingBox
from core.data_handler import DataHandler
from core.yolo_processor import YoloProcessor
from core.image_augmenter import ImageAugmenter
from core.workers import DetectionWorker, AugmentationWorker
from core.state_manager import StateManager
from core.image_resizer import resize_with_letterboxing
from core import utils
from core import formats

class AppLogic(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.app_data = AppData()
        self.data_handler = DataHandler(self.app_data) # Pass shared data object
        self.yolo_processor = YoloProcessor()
        self.image_augmenter = ImageAugmenter()
        
        # Initialize instance variables
        self.current_image_path: str | None = None
        self.selected_box_canvas_index: int = -1 # Track selection in canvas
        
        # Initialize the state manager with a 30-second auto-save interval
        self.state_manager = StateManager(auto_save_interval=30)
        self.state_manager.set_app_data(self.app_data)
        
        # Set up a timer for auto-saving
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self._check_auto_save)
        self.auto_save_timer.start(5000)  # Check every 5 seconds
        
        self.thread_pool = QThreadPool()
        print(f"Using max {self.thread_pool.maxThreadCount()} threads.")

        self._connect_ui_signals()
        
        # Load previous state if available - do this after all initialization
        self._load_previous_state()

    def _connect_ui_signals(self):
        # Connect signals FROM MainWindow TO AppLogic methods
        self.main_window.add_images_requested.connect(self.add_images)
        self.main_window.select_model_requested.connect(self.select_model)
        self.main_window.process_images_requested.connect(self.run_detection)
        self.main_window.save_dataset_requested.connect(self.save_dataset)
        self.main_window.save_state_requested.connect(self._on_save_state_requested)
        self.main_window.clear_state_requested.connect(self._on_clear_state_requested)
        self.main_window.image_selected.connect(self.load_image_and_annotations)
        self.main_window.delete_image_requested.connect(self._on_delete_image_requested)
        self.main_window.clear_images_requested.connect(self._on_clear_images_requested)
        self.main_window.import_classes_requested.connect(self._on_import_classes_requested)
        # Export classes is handled entirely in MainWindow
        self.main_window.class_added_requested.connect(self.add_class)
        self.main_window.class_removed_requested.connect(self.remove_class)
        self.main_window.class_selected_for_assignment.connect(self.assign_class_to_selected_box)
        self.main_window.confidence_threshold_changed.connect(self.on_confidence_threshold_changed)
        self.main_window.resize_enabled_changed.connect(self.on_resize_enabled_changed)
        self.main_window.resize_resolution_changed.connect(self.on_resize_resolution_changed)

    # --- Methods Triggered by UI ---

    def _check_auto_save(self):
        """Called by timer to check if auto-save is needed"""
        if self.state_manager.auto_save_if_needed():
            # Show auto-save indicator if auto-save occurred
            self.main_window.show_auto_save_indicator()
        
    def _load_previous_state(self):
        """Load the previous application state if available"""
        if self.state_manager.load_state():
            print("Previous session state loaded successfully")
            
            # Clean up app_data by removing references to non-existent files and augmented images
            # that we don't want to keep between sessions
            paths_to_remove = []
            for path, annot in self.app_data.images.items():
                # Remove augmented images or images that don't exist on disk
                if annot.augmented_from is not None or not os.path.exists(path):
                    paths_to_remove.append(path)
                    
            # Remove the identified paths
            for path in paths_to_remove:
                del self.app_data.images[path]
                
            print(f"Cleaned up {len(paths_to_remove)} images (augmented or missing from disk)")
            
            # Update UI with loaded state data - already filtered by _get_original_image_paths
            image_paths = self._get_original_image_paths()
            self.main_window.update_image_list(image_paths)
            self.main_window.update_class_list(self.app_data.classes)
            
            # Update model label if a model was loaded
            if self.app_data.model_path:
                self.main_window.set_model_label(self.app_data.model_path)

            # Update resize controls based on loaded data
            self.main_window.resize_checkbox.setChecked(self.app_data.resize_output_enabled)
            self.main_window.resolution_combo.setCurrentText(self.app_data.resize_output_resolution)
            self.main_window.resolution_combo.setEnabled(self.app_data.resize_output_enabled)

            # Apply loaded augmentation settings to the image augmenter
            self._apply_augmentation_settings_to_augmenter()
                
            # Update button states based on loaded data
            self.update_button_states()
            
            # Select first image if available - do this after updating the image list
            if image_paths:
                try:
                    self.main_window.image_list_widget.setCurrentRow(0)
                    # This will trigger load_image_and_annotations via the selection changed signal
                except Exception as e:
                    print(f"Error selecting first image: {e}")
                
            # Show status message
            self.main_window.status_bar.showMessage("Previous session state loaded", 3000)
        else:
            print("No previous session state found or failed to load")
            
    def add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Images",
            "", # Start directory
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if files:
            added = self.data_handler.add_image_paths(files)
            # Only show original images in the UI list, not augmented versions
            self.main_window.update_image_list(self._get_original_image_paths())
            if added and not self.current_image_path:
                # Select the first added image if none is selected
                 self.main_window.image_list_widget.setCurrentRow(0)
                 # load_image_and_annotations will be called by the selection change signal
                 
            # Save state after adding images
            self.state_manager.save_state()

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
            
            # Save state after selecting model
            self.state_manager.save_state()
            
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
            # Clear the canvas if image not found
            self.main_window.get_image_canvas().clear()

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
                model_class_names = self.yolo_processor.load_model(self.app_data.model_path)
                
                # --- Merge model classes with app classes ---
                if model_class_names:
                    newly_added_classes = []
                    for name in model_class_names:
                        if name not in self.app_data.classes:
                            self.app_data.classes.append(name)
                            newly_added_classes.append(name)
                    
                    if newly_added_classes:
                        print(f"Auto-added {len(newly_added_classes)} classes from model: {newly_added_classes}")
                        # Update UI with the new complete list
                        self.main_window.update_class_list(self.app_data.classes)
                        self.state_manager.save_state() # Save state after updating classes

            except Exception as e:
                self.main_window.show_message("Error", f"Failed to load model:\n{e}", QMessageBox.Icon.Critical)
                return

        self.main_window.set_ui_busy(True, f"Running detection on {len(image_paths)} image(s)...")

        # --- Worker Thread ---
        worker = DetectionWorker(self.yolo_processor, image_paths, self.app_data.images, self.app_data.confidence_threshold)
        # Connect signals from worker to AppLogic slots
        worker.signals.result.connect(self._handle_detection_result)
        worker.signals.finished.connect(self._on_detection_finished)
        worker.signals.error.connect(self._handle_worker_error)
        worker.signals.progress.connect(self._update_worker_progress) # TODO: Implement progress update

        self.thread_pool.start(worker)

    def _run_augmentation(self, num_augmentations: int):
        """Run augmentation and return the results (now an internal method)"""
        annotated_images = self.data_handler.get_annotated_image_paths()
        if not annotated_images:
            self.main_window.show_message("Warning", "No annotated images found to augment.", QMessageBox.Icon.Warning)
            return None
        
        # Get original annotations
        original_annotations = {p: self.app_data.images[p] for p in annotated_images}
        
        # Directly call the augmenter instead of using a worker
        try:
            self.main_window.set_ui_busy(True, f"Augmenting {len(annotated_images)} images with {num_augmentations} variations each...")
            
            # Use our enhanced ImageAugmenter to create augmentations
            augmented_data = self.image_augmenter.augment_batch(original_annotations, num_augmentations)
            
            if not augmented_data:
                self.main_window.show_message("Warning", "No augmentations were successfully created.", QMessageBox.Icon.Warning)
                return None
            
            # Update progress
            self.main_window.status_bar.showMessage(f"Created {len(augmented_data)} augmented images", 3000)
            
            # Add the augmented data to the app_data
            self.data_handler.add_augmented_data(augmented_data)

            # Make sure UI only shows original images - no need to update UI here,
            # as this will be handled by _on_augmentation_finished
            
            return augmented_data
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Augmentation error: {str(e)}\n{error_details}")
            self.main_window.show_message("Error", f"Augmentation failed: {str(e)}", QMessageBox.Icon.Critical)
            return None

    def save_dataset(self, format_type: str, do_augment: bool, num_augmentations: int):
        """Combined save dataset and augment functionality"""
        # --- Get Save Options ---
        output_dir = QFileDialog.getExistingDirectory(self.main_window, "Select Output Directory")
        if not output_dir:
            return
            
        if not self.data_handler.has_annotations():
            self.main_window.show_message("Warning", "No annotations found to save.", QMessageBox.Icon.Warning)
            return
            
        # Set UI to busy state
        self.main_window.set_ui_busy(True, "Preparing dataset...")
        
        # Run augmentation if requested, using threaded approach
        if do_augment and num_augmentations > 0:
            self.main_window.set_ui_busy(True, f"Augmenting images with {num_augmentations} variations each...")
            
            # Get all annotated images
            annotated_images = self.data_handler.get_annotated_image_paths()
            if not annotated_images:
                self.main_window.show_message("Warning", "No annotated images found to augment.", QMessageBox.Icon.Warning)
                self.main_window.set_ui_busy(False)
                return
                
            # Pass only necessary data (paths, annotations)
            original_annotations = {p: self.app_data.images[p] for p in annotated_images}
            
            # Create worker for augmentation
            worker = AugmentationWorker(self.image_augmenter, original_annotations, num_augmentations)
            
            # Connect signals
            worker.signals.result.connect(lambda augmented_data: self._continue_save_dataset(augmented_data, format_type, output_dir, num_augmentations))
            worker.signals.error.connect(self._handle_worker_error)
            worker.signals.progress.connect(self._update_worker_progress)
            
            # Start worker
            self.thread_pool.start(worker)
        else:
            # No augmentation, proceed directly to saving
            self._continue_save_dataset(None, format_type, output_dir, num_augmentations)

    def _continue_save_dataset(self, augmented_data, format_type, output_dir, num_augmentations):
        """Continue saving dataset after augmentation is complete or skipped"""
        if augmented_data:
            self.data_handler.add_augmented_data(augmented_data)
            self.main_window.status_bar.showMessage(f"Created {len(augmented_data)} augmented images", 3000)

        self.main_window.set_ui_busy(True, f"Saving dataset in {format_type.upper()} format...")

        try:
            data_to_save = self.app_data
            
            # --- Handle Resizing ---
            if self.app_data.resize_output_enabled:
                self.main_window.set_ui_busy(True, "Resizing images...")
                
                # Create a deep copy of the app_data to modify for saving
                resized_app_data = AppData(classes=copy.deepcopy(self.app_data.classes))
                
                target_res_str = self.app_data.resize_output_resolution
                try:
                    target_w, target_h = map(int, target_res_str.split('x'))
                except ValueError:
                    self.main_window.show_message("Error", f"Invalid resolution format: {target_res_str}", QMessageBox.Icon.Critical)
                    self.main_window.set_ui_busy(False)
                    return

                # Process all images that are about to be saved
                all_paths_to_process = self.data_handler.get_annotated_image_paths()
                
                for i, path in enumerate(all_paths_to_process):
                    self.main_window.update_progress(i, len(all_paths_to_process))
                    
                    annotation = self.app_data.images.get(path)
                    if not annotation:
                        continue

                    # Load image data (either from disk or from temp data for augmented images)
                    if annotation._temp_image_data is not None:
                        image_np = annotation._temp_image_data
                    else:
                        image_np = cv2.imread(path)
                        image_np = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)

                    if image_np is None:
                        print(f"Warning: Could not load image {path}, skipping.")
                        continue

                    # Perform resizing
                    resized_img, adjusted_boxes = resize_with_letterboxing(image_np, (target_h, target_w), annotation.boxes)
                    
                    # Create a new path for the resized image
                    original_filename = os.path.basename(path)
                    # Ensure the output directory for resized images exists
                    resized_images_dir = os.path.join(output_dir, "resized_images")
                    os.makedirs(resized_images_dir, exist_ok=True)
                    new_image_path = os.path.join(resized_images_dir, original_filename)
                    
                    # Save the resized image
                    # Convert back to BGR for saving with OpenCV
                    cv2.imwrite(new_image_path, cv2.cvtColor(resized_img, cv2.COLOR_RGB2BGR))

                    # Create a new annotation for the resized data
                    new_annotation = ImageAnnotation(
                        image_path=new_image_path,
                        width=target_w,
                        height=target_h,
                        boxes=adjusted_boxes,
                        processed=True,
                        augmented_from=annotation.augmented_from
                    )
                    resized_app_data.images[new_image_path] = new_annotation

                # Replace the data to be saved with the resized data
                data_to_save = resized_app_data
                self.main_window.set_ui_busy(True, f"Saving resized dataset...")


            # --- Splitting and Saving ---
            annotated_paths = list(data_to_save.images.keys())
            if not annotated_paths:
                self.main_window.show_message("Warning", "No annotations found to save.", QMessageBox.Icon.Warning)
                self.main_window.set_ui_busy(False)
                return

            train_split = 0.8
            random.shuffle(annotated_paths)
            split_idx = int(len(annotated_paths) * train_split)
            train_paths = annotated_paths[:split_idx]
            val_paths = annotated_paths[split_idx:]

            if not train_paths and val_paths:
                train_paths, val_paths = val_paths, train_paths

            if format_type.lower() == 'yolo':
                formats.save_yolo(data_to_save, output_dir, train_paths, val_paths)
            elif format_type.lower() == 'coco':
                formats.save_coco(data_to_save, output_dir, train_paths, val_paths)
            elif format_type.lower() == 'voc':
                formats.save_voc(data_to_save, output_dir, train_paths, val_paths)
            else:
                raise ValueError(f"Unsupported format: {format_type}")

            message = f"Dataset saved successfully in {format_type.upper()} format"
            if augmented_data:
                message += f" with {len(augmented_data)} augmentations"
            if self.app_data.resize_output_enabled:
                 message += f" (resized to {self.app_data.resize_output_resolution})"
            self.main_window.show_message("Success", f"{message}\nLocation: {output_dir}", QMessageBox.Icon.Information)

        except Exception as e:
            self.main_window.show_message("Error", f"Failed to save dataset: {str(e)}", QMessageBox.Icon.Critical)
            import traceback
            traceback.print_exc()
        finally:
            self.main_window.set_ui_busy(False, "Save completed.")
            self.update_button_states()
            self.main_window.update_image_list(self._get_original_image_paths())

    def add_class(self, class_name: str):
        if class_name in self.app_data.classes:
             self.main_window.show_message("Info", f"Class '{class_name}' already exists.")
             return
        self.app_data.classes.append(class_name)
        self.main_window.update_class_list(self.app_data.classes)
        self.update_button_states()
        
        # Save state after adding a class
        self.state_manager.save_state()

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
             
         # Save state after removing a class
         self.state_manager.save_state()

    def assign_class_to_selected_box(self, class_index: int):
        if self.current_image_path and self.selected_box_canvas_index != -1:
            if 0 <= class_index < len(self.app_data.classes):
                 # Update the specific box in the data model
                 boxes = self.app_data.images[self.current_image_path].boxes
                 if 0 <= self.selected_box_canvas_index < len(boxes):
                     boxes[self.selected_box_canvas_index].class_id = class_index
                     # Tell canvas to redraw
                     self.main_window.get_image_canvas().set_annotations(boxes, self.app_data.classes)
                     
                     # Save state after changing a box's class
                     self.state_manager.save_state()

    def on_confidence_threshold_changed(self, value: int):
        """Handle confidence threshold changes from the UI."""
        self.app_data.confidence_threshold = value / 100.0  # Convert to float
        self.state_manager.save_state()

    def on_resize_enabled_changed(self, enabled: bool):
        """Handle resize checkbox state change."""
        self.app_data.resize_output_enabled = enabled
        self.state_manager.save_state()

    def on_resize_resolution_changed(self, resolution: str):
        """Handle resize resolution dropdown change."""
        self.app_data.resize_output_resolution = resolution
        self.state_manager.save_state()

    # --- Methods Triggered by ImageCanvas ---

    def on_annotations_updated(self):
        """Called when canvas signals a change (move/resize)."""
        # Data is already updated in the canvas's internal list which points
        # to the same BoundingBox objects managed by DataHandler/AppData.
        # May need to mark data as 'dirty' for saving state later.
        self.update_button_states() # Save button might become enabled
        
        # Save state after annotations are updated
        self.state_manager.save_state()

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
             
             # Save state after drawing a new box
             self.state_manager.save_state()

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
            
            # Save state after deleting a box
            self.state_manager.save_state()

    # --- Slots for Worker Signals ---

    def _handle_detection_result(self, result_tuple):
        """Update data model with detection results from worker."""
        image_path, detected_boxes = result_tuple  # Unpack the tuple from the signal
        if image_path in self.app_data.images:
             self.app_data.images[image_path].boxes = detected_boxes
             self.app_data.images[image_path].processed = True
             # If this is the currently viewed image, update the canvas
             if image_path == self.current_image_path:
                 self.load_image_and_annotations(image_path)
                 
             # Save state after processing
             self.state_manager.save_state()

    def _on_detection_finished(self):
        self.main_window.set_ui_busy(False, "Detection finished.")
        self.update_button_states()

    def _handle_augmentation_result(self, augmented_data):
        """Update app data with augmentation results."""
        self.data_handler.add_augmented_data(augmented_data)
        # No need to call update_image_list directly as it's handled in _on_augmentation_finished
        # and will filter out augmented images

    def _on_augmentation_finished(self):
         self.main_window.set_ui_busy(False, "Augmentation finished.")
         self.update_button_states()
         # Only show original images in the UI list, not augmented versions
         self.main_window.update_image_list(self._get_original_image_paths()) # Refresh list after augment

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
        can_process = bool(self.app_data.model_path) and bool(self.current_image_path)
        can_save = self.data_handler.has_annotations()
        # can_augment = self.data_handler.has_annotations() # Can augment if anything is annotated

        self.main_window.process_button.setEnabled(can_process)
        self.main_window.save_button.setEnabled(can_save)
        # self.main_window.augment_button.setEnabled(can_augment)  # This button no longer exists

    def is_ready_to_process(self) -> bool:
        return bool(self.app_data.model_path) and bool(self.current_image_path)

    def is_ready_to_augment(self) -> bool:
        return self.data_handler.has_annotations()
        
    def is_ready_to_save(self) -> bool:
        return self.data_handler.has_annotations()

    def _on_save_state_requested(self):
        """Handle manual save state request"""
        self.state_manager.save_state()
        self.main_window.show_auto_save_indicator()
        self.main_window.status_bar.showMessage("Application state saved manually", 3000)
        
    def _on_clear_state_requested(self):
        """Handle clear state request"""
        # Clear the saved state files
        self.state_manager.clear_state()
        
        # Reset the app data
        self.app_data.images.clear()
        self.app_data.classes.clear()
        self.app_data.model_path = None
        
        # Update UI
        self.main_window.update_image_list([])
        self.main_window.update_class_list([])
        self.main_window.set_model_label(None)
        
        # Clear the canvas
        canvas = self.main_window.get_image_canvas()
        if canvas:
            canvas.clear()
            canvas.update()
            
        self.current_image_path = None
        self.selected_box_canvas_index = -1
        
        # Update button states
        self.update_button_states()
        
        # Show confirmation
        self.main_window.status_bar.showMessage("Application state reset to defaults", 3000)

    def _on_delete_image_requested(self, image_path: str):
        # Implement the logic to delete the image from the app_data and update the UI
        if image_path in self.app_data.images:
            # Check if the image to be deleted is the current image
            is_current_image = (image_path == self.current_image_path)
            
            # Delete the image
            del self.app_data.images[image_path]
            
            # Update UI - only show original images
            self.main_window.update_image_list(self._get_original_image_paths())
            
            # If the current image was deleted, clear canvas and reset current path
            if is_current_image:
                self.current_image_path = None
                self.selected_box_canvas_index = -1
                self.main_window.get_image_canvas().clear()
            
            self.update_button_states()
            
            # Show status message
            image_name = os.path.basename(image_path)
            self.main_window.status_bar.showMessage(f"Deleted image: {image_name}", 3000)
            
            # Save state after deleting an image
            self.state_manager.save_state()
        else:
            print(f"Error: {image_path} not found in app data.")

    def _on_clear_images_requested(self):
        # Implement the logic to clear all images from the app_data and update the UI
        image_count = len(self.app_data.images)
        if image_count > 0:
            self.app_data.images.clear()
            self.main_window.update_image_list([])
            
            # Clear current image state
            self.current_image_path = None
            self.selected_box_canvas_index = -1
            self.main_window.get_image_canvas().clear()
            
            self.update_button_states()
            
            # Show status message
            self.main_window.status_bar.showMessage(f"Cleared {image_count} images", 3000)
            
            # Save state after clearing images
            self.state_manager.save_state()
        else:
            self.main_window.status_bar.showMessage("No images to clear", 3000)

    def _on_import_classes_requested(self, class_names: list):
        """Handle importing class names from a text file"""
        if not class_names:
            return
            
        # Keep track of what was imported
        imported_count = 0
        skipped_count = 0
        imported_classes = []
        skipped_classes = []
        
        # Process each class name
        for class_name in class_names:
            # Skip empty names or whitespace-only strings
            if not class_name.strip():
                continue
                
            # Skip duplicates
            if class_name in self.app_data.classes:
                skipped_classes.append(class_name)
                skipped_count += 1
                continue
                
            # Add valid class name
            self.app_data.classes.append(class_name)
            imported_classes.append(class_name)
            imported_count += 1
        
        # Update UI
        self.main_window.update_class_list(self.app_data.classes)
        
        # Update canvas if open
        if self.current_image_path and self.current_image_path in self.app_data.images:
            canvas = self.main_window.get_image_canvas()
            canvas.class_names = self.app_data.classes
            canvas.update()  # Refresh the canvas
        
        self.update_button_states()
        
        # Save state after importing classes
        self.state_manager.save_state()
        
        # Show detailed report if anything was processed
        if imported_count > 0 or skipped_count > 0:
            # Create detailed report
            report = f"Import Summary:\n\n"
            
            if imported_count > 0:
                report += f"Successfully imported {imported_count} classes:\n"
                report += "- " + "\n- ".join(imported_classes) + "\n\n"
            
            if skipped_count > 0:
                report += f"Skipped {skipped_count} duplicate classes:\n"
                report += "- " + "\n- ".join(skipped_classes)
            
            # Show in a message box for more detailed view
            self.main_window.show_message(
                "Class Import Report", 
                report, 
                QMessageBox.Icon.Information
            )
        
        # Show brief message in status bar
        if imported_count > 0:
            if skipped_count > 0:
                self.main_window.status_bar.showMessage(
                    f"Imported {imported_count} classes, skipped {skipped_count} duplicates", 
                    3000
                )
            else:
                self.main_window.status_bar.showMessage(
                    f"Successfully imported {imported_count} classes", 
                    3000
                )
        else:
            self.main_window.status_bar.showMessage(
                "No new classes imported (all were duplicates or empty)", 
                3000
            )

    def set_augmentation_settings(self, settings: dict):
        """Apply augmentation settings to the image augmenter and save them."""
        try:
            # Update the app_data.augmentation_settings from the dialog
            aug_settings = self.app_data.augmentation_settings
            
            # Update geometric transform settings
            if "geometric" in settings:
                geo = settings["geometric"]
                aug_settings.geometric_transforms_prob = geo.get("probability", 0.5)
                aug_settings.hflip_prob = geo.get("hflip_prob", 0.5)
                aug_settings.vflip_prob = geo.get("vflip_prob", 0.5)
                aug_settings.rotate_prob = geo.get("rotate_prob", 0.3)
                aug_settings.rotate_limit = geo.get("rotate_limit", 30)
                aug_settings.shift_scale_rotate_prob = geo.get("shift_scale_rotate_prob", 0.3)
                aug_settings.elastic_transform_prob = geo.get("elastic_transform_prob", 0.1)
                aug_settings.grid_distortion_prob = geo.get("grid_distortion_prob", 0.1)
                aug_settings.optical_distortion_prob = geo.get("optical_distortion_prob", 0.1)
                aug_settings.enabled_transforms["geometric"] = geo.get("enabled", True)

            # Update color transform settings
            if "color" in settings:
                color = settings["color"]
                aug_settings.color_transforms_prob = color.get("probability", 0.5)
                aug_settings.brightness_contrast_prob = color.get("brightness_contrast_prob", 0.5)
                aug_settings.hue_saturation_prob = color.get("hue_saturation_prob", 0.3)
                aug_settings.rgb_shift_prob = color.get("rgb_shift_prob", 0.3)
                aug_settings.clahe_prob = color.get("clahe_prob", 0.3)
                aug_settings.channel_shuffle_prob = color.get("channel_shuffle_prob", 0.1)
                aug_settings.gamma_prob = color.get("gamma_prob", 0.3)
                aug_settings.enabled_transforms["color"] = color.get("enabled", True)

            # Update other transform settings
            if "weather" in settings:
                weather = settings["weather"]
                aug_settings.weather_transforms_prob = weather.get("probability", 0.3)
                aug_settings.fog_prob = weather.get("fog_prob", 0.3)
                aug_settings.rain_prob = weather.get("rain_prob", 0.2)
                aug_settings.sunflare_prob = weather.get("sunflare_prob", 0.1)
                aug_settings.shadow_prob = weather.get("shadow_prob", 0.2)
                aug_settings.enabled_transforms["weather"] = weather.get("enabled", True)
            if "noise" in settings:
                noise = settings["noise"]
                aug_settings.noise_transforms_prob = noise.get("probability", 0.3)
                aug_settings.gaussian_noise_prob = noise.get("gaussian_noise_prob", 0.3)
                aug_settings.iso_noise_prob = noise.get("iso_noise_prob", 0.3)
                aug_settings.jpeg_compression_prob = noise.get("jpeg_compression_prob", 0.3)
                aug_settings.posterize_prob = noise.get("posterize_prob", 0.2)
                aug_settings.equalize_prob = noise.get("equalize_prob", 0.2)
                aug_settings.enabled_transforms["noise"] = noise.get("enabled", True)
            if "blur" in settings:
                blur = settings["blur"]
                aug_settings.blur_transforms_prob = blur.get("probability", 0.3)
                aug_settings.blur_prob = blur.get("blur_prob", 0.3)
                aug_settings.gaussian_blur_prob = blur.get("gaussian_blur_prob", 0.3)
                aug_settings.motion_blur_prob = blur.get("motion_blur_prob", 0.2)
                aug_settings.median_blur_prob = blur.get("median_blur_prob", 0.2)
                aug_settings.glass_blur_prob = blur.get("glass_blur_prob", 0.1)
                aug_settings.enabled_transforms["blur"] = blur.get("enabled", True)

            # Apply the updated settings to the image augmenter instance
            self._apply_augmentation_settings_to_augmenter()
            
            # Save the updated state
            self.state_manager.save_state()
            
            print("Augmentation settings updated and saved successfully")
            
        except Exception as e:
            print(f"Error updating augmentation settings: {str(e)}")
            self.main_window.show_message("Error", f"Failed to update augmentation settings: {str(e)}", QMessageBox.Icon.Critical)

    def _apply_augmentation_settings_to_augmenter(self):
        """Helper to apply settings from AppData to the ImageAugmenter instance."""
        if not self.app_data or not self.image_augmenter:
            return
            
        # Get the settings from app_data
        settings = self.app_data.augmentation_settings
        config = self.image_augmenter.config
        
        # Apply all settings from the dataclass to the config object
        config.geometric_transforms_prob = settings.geometric_transforms_prob
        config.color_transforms_prob = settings.color_transforms_prob
        config.weather_transforms_prob = settings.weather_transforms_prob
        config.noise_transforms_prob = settings.noise_transforms_prob
        config.blur_transforms_prob = settings.blur_transforms_prob
        config.hflip_prob = settings.hflip_prob
        config.vflip_prob = settings.vflip_prob
        config.rotate_prob = settings.rotate_prob
        config.rotate_limit = settings.rotate_limit
        config.brightness_contrast_prob = settings.brightness_contrast_prob
        config.hue_saturation_prob = settings.hue_saturation_prob
        config.rgb_shift_prob = settings.rgb_shift_prob
        config.blur_prob = settings.blur_prob
        config.gaussian_noise_prob = settings.gaussian_noise_prob

        # Apply the new settings
        config.shift_scale_rotate_prob = settings.shift_scale_rotate_prob
        config.elastic_transform_prob = settings.elastic_transform_prob
        config.grid_distortion_prob = settings.grid_distortion_prob
        config.optical_distortion_prob = settings.optical_distortion_prob
        config.clahe_prob = settings.clahe_prob
        config.channel_shuffle_prob = settings.channel_shuffle_prob
        config.gamma_prob = settings.gamma_prob
        config.fog_prob = settings.fog_prob
        config.rain_prob = settings.rain_prob
        config.sunflare_prob = settings.sunflare_prob
        config.shadow_prob = settings.shadow_prob
        config.iso_noise_prob = settings.iso_noise_prob
        config.jpeg_compression_prob = settings.jpeg_compression_prob
        config.posterize_prob = settings.posterize_prob
        config.equalize_prob = settings.equalize_prob
        config.gaussian_blur_prob = settings.gaussian_blur_prob
        config.motion_blur_prob = settings.motion_blur_prob
        config.median_blur_prob = settings.median_blur_prob
        config.glass_blur_prob = settings.glass_blur_prob
        
        # Apply enabled states
        self.image_augmenter.enabled_transforms = settings.enabled_transforms.copy()
        print("Applied loaded augmentation settings to the augmenter.")

    def get_augmentation_settings(self):
        """Get the current augmentation settings as a dictionary."""
        import dataclasses
        return dataclasses.asdict(self.app_data.augmentation_settings)

    def _get_original_image_paths(self):
        """Returns list of original (non-augmented) image paths that exist on disk."""
        return [path for path, annot in self.app_data.images.items() 
                if annot.augmented_from is None and os.path.exists(path)]
    
    def on_class_assignment_requested(self, box_index: int, class_id: int):
        """Handle class assignment request from drag and drop."""
        if self.current_image_path and 0 <= box_index < len(self.app_data.images[self.current_image_path].boxes):
            # Assign the class to the box
            self.app_data.images[self.current_image_path].boxes[box_index].class_id = class_id
            
            # Update the canvas
            canvas = self.main_window.get_image_canvas()
            canvas.set_annotations(self.app_data.images[self.current_image_path].boxes, self.app_data.classes)
            self.update_button_states()
            
            # Save state after assigning class
            self.state_manager.save_state()
