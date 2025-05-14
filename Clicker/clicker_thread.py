# clicker_thread.py

import time
import random
import pyautogui
import threading
from PyQt6.QtCore import QThread, pyqtSignal

# Disable pyautogui fail-safes if absolutely necessary (use with caution)
# pyautogui.FAILSAFE = False
# pyautogui.PAUSE = 0.01 # Small pause between pyautogui actions

class ClickerThread(QThread):
    """
    Runs the automated clicking loop in a separate thread.
    """
    # Signals
    status_update = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, coordinates, settings, parent=None):
        super().__init__(parent)
        if not coordinates:
            raise ValueError("Coordinates list cannot be empty for ClickerThread")

        self.coordinates = coordinates
        self.settings = settings # Expects a dict: {'min_delay', 'max_delay', 'speed_factor'}
        self._is_running = False
        self.is_paused = False
        self._pause_cond = threading.Condition()

    def run(self):
        """Main execution method for the thread."""
        self.status_update.emit("Clicking thread started.")
        self._is_running = True
        self.is_paused = False
        click_count = 0

        while self._is_running:
            with self._pause_cond:
                while self.is_paused:
                    self.status_update.emit("Clicking paused.")
                    self._pause_cond.wait()

            try:
                if not self.coordinates:
                    self.status_update.emit("Error: No coordinates left.")
                    break

                # 1. Select random coordinate
                target_coord = random.choice(self.coordinates)
                self.status_update.emit(f"Targeting ({target_coord[0]}, {target_coord[1]})...")

                # 2. Simulate human-like movement
                moved = self._human_like_move(target_coord[0], target_coord[1])
                if not moved: # Check if movement was interrupted/stopped
                    break

                if not self._is_running: break # Check again after move

                # 3. Perform Click
                self.status_update.emit(f"Clicking at ({target_coord[0]}, {target_coord[1]})")
                pyautogui.click(button='left')
                click_count += 1

                if not self._is_running: break # Check again after click

                # 4. Wait random delay
                min_d = self.settings.get('min_delay', 2000) / 1000.0
                max_d = self.settings.get('max_delay', 7000) / 1000.0
                delay = random.uniform(min_d, max_d)
                self.status_update.emit(f"Waiting for {delay:.2f} seconds... (Click {click_count})")
                # Use a loop for sleeping to check stop flag frequently
                end_time = time.time() + delay
                while time.time() < end_time and self._is_running:
                    time.sleep(0.05) # Check stop flag every 50ms

            except pyautogui.FailSafeException:
                self.status_update.emit("Fail-Safe triggered! Stopping.")
                self._is_running = False
            except Exception as e:
                self.status_update.emit(f"Error during click loop: {e}")
                # Decide whether to stop or continue based on error type
                # For now, stop on any error
                self._is_running = False

        self.status_update.emit(f"Clicking thread finished. Total clicks: {click_count}")
        self.finished.emit() # Signal that the thread has finished

    def _human_like_move(self, target_x, target_y):
        """Simulates more human-like mouse movement."""
        try:
            speed_factor = self.settings.get('speed_factor', 1.0)
            if speed_factor <= 0: speed_factor = 1.0 # Avoid division by zero / infinite time

            # 1. Pre-move delay
            pre_move_delay = random.uniform(0.05, 0.2)
            time.sleep(pre_move_delay)
            if not self._is_running: return False

            # 2. Target Inaccuracy
            offset_x = random.randint(-3, 3)
            offset_y = random.randint(-3, 3)
            final_x = target_x + offset_x
            final_y = target_y + offset_y

            # 3. Calculate Duration & Tween
            start_x, start_y = pyautogui.position()
            distance = ((final_x - start_x)**2 + (final_y - start_y)**2)**0.5
            # Base duration: e.g., 0.1s per 100 pixels (adjust as needed)
            base_duration = max(0.1, (distance / 100.0) * 0.1)
            # Apply speed factor (inversely) and randomness
            duration = (base_duration / speed_factor) * random.uniform(0.8, 1.2)
            duration = max(0.05, duration) # Ensure minimum duration

            tween_options = [
                pyautogui.linear, # Included for variety, less human
                pyautogui.easeInQuad, pyautogui.easeOutQuad, pyautogui.easeInOutQuad,
                pyautogui.easeInSine, pyautogui.easeOutSine, pyautogui.easeInOutSine
            ]
            tween = random.choice(tween_options)

            # 4. Perform Move
            pyautogui.moveTo(final_x, final_y, duration=duration, tween=tween)
            if not self._is_running: return False

            # 5. Pre-click delay
            pre_click_delay = random.uniform(0.05, 0.15)
            time.sleep(pre_click_delay)
            if not self._is_running: return False

            return True # Movement successful

        except pyautogui.FailSafeException:
            self.status_update.emit("Fail-Safe triggered during move! Stopping.")
            self._is_running = False
            return False
        except Exception as e:
            self.status_update.emit(f"Error during move simulation: {e}")
            self._is_running = False
            return False

    def stop(self):
        """Signals the thread to stop running."""
        self.status_update.emit("Stop signal received.")
        self._is_running = False

    def pause(self):
        """Pauses the clicking thread."""
        with self._pause_cond:
            self.is_paused = True

    def resume(self):
        """Resumes the clicking thread from pause."""
        with self._pause_cond:
            self.is_paused = False
            self._pause_cond.notify()