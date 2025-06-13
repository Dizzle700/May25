from PyQt6.QtCore import QThread, pyqtSignal
import os
import time # For sleep if pausing

class BackgroundRemovalWorker(QThread):
    """Worker thread for batch background removal."""
    progress_updated = pyqtSignal(int, int)  # current_value, total_value
    status_updated = pyqtSignal(str)
    image_processed = pyqtSignal(str, object) # image_path, thumbnail_pixmap (or None)
    processing_finished = pyqtSignal(str) # Completion message

    def __init__(self, remover_core, input_dir, output_dir, output_format, parent=None):
        super().__init__(parent)
        self.remover_core = remover_core
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.output_format = output_format
        self._is_running = True
        self._is_paused = False

    def run(self):
        self.status_updated.emit("Starting batch processing...")
        try:
            image_files = [
                f for f in os.listdir(self.input_dir)
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))
            ]
            total_images = len(image_files)
            if total_images == 0:
                self.processing_finished.emit("No images found in the input folder.")
                return

            self.progress_updated.emit(0, total_images)
            processed_count = 0

            for i, filename in enumerate(image_files):
                if not self._is_running:
                    break
                while self._is_paused:
                    if not self._is_running: # Check again in case stop was called during pause
                        break
                    time.sleep(0.1) # Sleep briefly to avoid busy-waiting

                if not self._is_running: # Final check before processing
                    break

                image_path = os.path.join(self.input_dir, filename)
                self.status_updated.emit(f"Processing images: {i+1}/{total_images}")

                try:
                    # The core processing logic
                    saved_path = self.remover_core.process_single_image(
                        image_path, self.output_dir, self.output_format
                    )
                    if saved_path:
                        processed_count += 1
                        # For thumbnail, we can pass the path and let UI create it, or create here
                        # from PyQt6.QtGui import QPixmap # Avoid direct Qt GUI in worker if possible
                        # thumb_pixmap = QPixmap(saved_path) # This would be better done in UI thread via signal
                        self.image_processed.emit(saved_path, None) # Pass None for pixmap, UI will load
                except Exception as e:
                    self.status_updated.emit(f"Error processing {filename}: {str(e)[:100]}...") # Truncate long errors
                    print(f"Full error for {filename}: {e}")


                self.progress_updated.emit(i + 1, total_images)

            if self._is_running: # Not stopped prematurely
                self.processing_finished.emit(f"completed {processed_count}/{total_images}")
            else:
                self.processing_finished.emit(f"stopped {processed_count}/{total_images}")

        except Exception as e:
            self.status_updated.emit(f"Critical error during batch processing: {e}")
            self.processing_finished.emit(f"Batch processing failed: {e}")
            print(f"Critical worker error: {e}")
            import traceback
            traceback.print_exc()


    def stop(self):
        self._is_running = False
        self._is_paused = False # Ensure it doesn't stay paused if stopped

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def is_paused(self):
        return self._is_paused
