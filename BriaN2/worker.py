# worker.py

import time
import os
from PyQt6.QtCore import QObject, pyqtSignal
from PIL import Image
from image_processor import ImageProcessor

class Worker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(int, int) # current, total
    image_processed = pyqtSignal(str, str) # input_path, output_path
    error = pyqtSignal(str)

    def __init__(self, image_processor: ImageProcessor):
        super().__init__()
        self.image_processor = image_processor
        self._is_running = True
        self._is_paused = False
        self.files_to_process = []
        self.output_dir = ""
        self.create_bbox = False

    def run(self):
        """Main processing loop."""
        total_files = len(self.files_to_process)
        for i, file_path in enumerate(self.files_to_process):
            while self._is_paused:
                time.sleep(0.5)
            
            if not self._is_running:
                break
            
            try:
                base_name = os.path.basename(file_path)
                name, ext = os.path.splitext(base_name)
                output_path_rembg = os.path.join(self.output_dir, f"{name}_rembg.png")
                output_path_bbox = os.path.join(self.output_dir, f"{name}_bbox.png")

                with Image.open(file_path) as img:
                    original_img = img.copy()
                    
                    # Remove background
                    processed_img, mask = self.image_processor.remove_background(original_img)
                    processed_img.save(output_path_rembg, "PNG")

                    # Create bounding box if requested
                    if self.create_bbox:
                        bbox_img = self.image_processor.create_bounding_box_image(original_img, mask)
                        bbox_img.save(output_path_bbox, "PNG")

                self.image_processed.emit(file_path, output_path_rembg)

            except Exception as e:
                self.error.emit(f"Error processing {file_path}: {e}")
            
            self.progress.emit(i + 1, total_files)
        
        self.finished.emit()

    def stop(self):
        self._is_running = False

    def toggle_pause(self):
        self._is_paused = not self._is_paused
        return self._is_paused