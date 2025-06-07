# core/workers.py
import traceback
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot
from typing import List, Dict, Tuple, Any, TYPE_CHECKING
import os

# Import core components used by workers
from .models import ImageAnnotation, BoundingBox, AppData
from .yolo_processor import YoloProcessor
from .image_augmenter import ImageAugmenter
from . import utils  # Add the missing utils import

# Use TYPE_CHECKING for imports only needed for type checking
# This prevents circular imports at runtime
if TYPE_CHECKING:
    from .data_handler import DataHandler

class WorkerSignals(QObject):
    ''' Defines signals available from a running worker thread. '''
    finished = pyqtSignal() # Signal when work is done (no data)
    finished_str = pyqtSignal(str) # Signal when work is done (with success message)
    error = pyqtSignal(object) # Signal when an error occurs (e.g., tuple(type, value, tb))
    progress = pyqtSignal(int, int) # Signal progress (current, total)
    result = pyqtSignal(object) # Signal returning results (type depends on worker)


class BaseWorker(QRunnable):
    """Inheritable worker class."""
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.signals = WorkerSignals()
        # Store args/kwargs or process them in subclass __init__

    @pyqtSlot()
    def run(self):
        # Generic run method - subclasses should implement their logic
        try:
            self._run_task()
        except Exception as e:
            tb_str = traceback.format_exc()
            self.signals.error.emit((type(e), e, tb_str))
        # Note: 'finished' signal should be emitted by the subclass's _run_task
        # or here if the structure guarantees _run_task completion implies finished.


class DetectionWorker(BaseWorker):
    """Worker for running YOLO detection."""
    def __init__(self, processor: YoloProcessor, image_paths: List[str], image_data_dict: Dict[str, ImageAnnotation]):
        super().__init__()
        self.processor = processor
        self.image_paths = image_paths
        self.image_data_dict = image_data_dict # Reference to update dimensions if needed

    # Override run or implement _run_task used by BaseWorker.run
    @pyqtSlot()
    def run(self):
        total_images = len(self.image_paths)
        try:
            for i, image_path in enumerate(self.image_paths):
                self.signals.progress.emit(i, total_images)
                if not image_path in self.image_data_dict: continue # Should not happen normally

                # Ensure dimensions are known before detection
                img_annot = self.image_data_dict[image_path]
                if img_annot.width == 0 or img_annot.height == 0:
                     dims = utils.get_image_dimensions(image_path)
                     if dims:
                         img_annot.width, img_annot.height = dims
                     else:
                         print(f"Skipping detection for {image_path}, cannot get dimensions.")
                         continue # Skip if dimensions are unknown

                # Run detection
                detected_boxes : List[BoundingBox] = self.processor.detect(image_path) # YoloProcessor handles image loading

                # Emit result for this image
                # The AppLogic will handle updating the main AppData structure
                self.signals.result.emit((image_path, detected_boxes))

            self.signals.progress.emit(total_images, total_images) # Final progress
        except Exception as e:
            tb_str = traceback.format_exc()
            self.signals.error.emit((type(e), e, tb_str))
        finally:
            self.signals.finished.emit()


class AugmentationWorker(BaseWorker):
    """Worker for augmenting images and annotations."""
    def __init__(self, augmenter: ImageAugmenter, original_annotations: Dict[str, ImageAnnotation], num_augmentations: int):
        super().__init__()
        self.augmenter = augmenter
        self.original_annotations = original_annotations
        self.num_augmentations = num_augmentations

    @pyqtSlot()
    def run(self):
        all_augmented_data = {}
        total_originals = len(self.original_annotations)
        total_augmentations = total_originals * self.num_augmentations
        current_progress = 0
        
        try:
            # Calculate the total number of augmentations to be created
            self.signals.progress.emit(0, total_augmentations)
            
            # Process each original image
            for i, (image_path, annotation_data) in enumerate(self.original_annotations.items()):
                # Report progress by image
                img_name = os.path.basename(image_path)
                self.signals.progress.emit(current_progress, total_augmentations)
                
                # Augment the current image
                augmented_for_image = self.augmenter.augment(annotation_data, self.num_augmentations)
                
                # Update the overall progress
                if augmented_for_image:
                    all_augmented_data.update(augmented_for_image)
                    # Increment progress based on actual augmentations created
                    current_progress += len(augmented_for_image)
                else:
                    # Skip to next image if no augmentations were created for this one
                    current_progress += self.num_augmentations
                
                # Report progress after each image
                self.signals.progress.emit(current_progress, total_augmentations)
            
            # Final progress update
            self.signals.progress.emit(total_augmentations, total_augmentations)
            
            # Emit all results at once
            self.signals.result.emit(all_augmented_data)
            
        except Exception as e:
            tb_str = traceback.format_exc()
            self.signals.error.emit((type(e), e, tb_str))
        finally:
            self.signals.finished.emit()


class SaveWorker(BaseWorker):
    """Worker for saving the dataset."""
    def __init__(self, data_handler: 'DataHandler', output_dir: str, save_format: str):
        super().__init__()
        self.data_handler = data_handler
        self.output_dir = output_dir
        self.save_format = save_format

    @pyqtSlot()
    def run(self):
        try:
            # The save_dataset method in DataHandler should contain all logic
            # including calling the correct format saver from core.formats
            # and handling train/val splits.
            # It should return a success message.
            # TODO: Implement progress reporting within DataHandler.save_dataset if needed
            # For now, we don't have progress from the DataHandler.
            self.signals.progress.emit(0, 1) # Indicate start
            success_message = self.data_handler.save_dataset(self.output_dir, self.save_format)
            self.signals.progress.emit(1, 1) # Indicate end
            # Use finished_str signal to pass back the success message
            self.signals.finished_str.emit(success_message)

        except Exception as e:
            tb_str = traceback.format_exc()
            self.signals.error.emit((type(e), e, tb_str))
        # finally:
            # Finished signal is emitted via finished_str in the success case now