import sys
import os
import hashlib
import zlib
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QProgressBar, QSizePolicy,
    QStyleFactory
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPalette, QColor, QIcon, QFont

# --- Configuration ---
CHUNK_SIZE = 65536  # 64KB chunks for reading files
WINDOW_TITLE = "Hash Compare Tool"
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600

# --- Hashing Functions ---

def calculate_hashes(filepath):
    """Calculates CRC32, MD5, and SHA256 hashes for a file."""
    hashes = {'crc32': None, 'md5': None, 'sha256': None}
    crc32_val = 0
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()

    try:
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                crc32_val = zlib.crc32(chunk, crc32_val)
                md5_hash.update(chunk)
                sha256_hash.update(chunk)

        # Format CRC32 as 8-digit hex
        hashes['crc32'] = format(crc32_val & 0xFFFFFFFF, '08x')
        hashes['md5'] = md5_hash.hexdigest()
        hashes['sha256'] = sha256_hash.hexdigest()
        return hashes
    except (IOError, OSError, PermissionError) as e:
        print(f"Error reading file {filepath}: {e}")
        return None # Indicate error

# --- Worker Thread for Background Processing ---

class CompareWorker(QObject):
    """Worker object to perform comparison in a separate thread."""
    progress_update = pyqtSignal(int, str)  # percentage, status_message
    comparison_finished = pyqtSignal(list)  # List of formatted result strings
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()  # Signal to indicate the worker has finished

    def __init__(self, path1, path2):
        super().__init__()
        self.path1 = path1
        self.path2 = path2
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run_comparison(self):
        """Main comparison logic."""
        results = []
        try:
            is_file1 = os.path.isfile(self.path1)
            is_dir1 = os.path.isdir(self.path1)
            is_file2 = os.path.isfile(self.path2)
            is_dir2 = os.path.isdir(self.path2)

            start_time = time.time()

            if is_file1 and is_file2:
                results = self._compare_files(self.path1, self.path2)
            elif is_dir1 and is_dir2:
                results = self._compare_folders(self.path1, self.path2)
            elif (is_file1 and is_dir2) or (is_dir1 and is_file2):
                results.append(f'<font color="#FFA500">Type Mismatch:</font> Cannot compare a file with a directory.')
                results.append(f'Item 1: {"File" if is_file1 else "Directory"}')
                results.append(f'Item 2: {"File" if is_file2 else "Directory"}')
            else:
                results.append(f'<font color="red">Error:</font> One or both paths are invalid or inaccessible.')

            end_time = time.time()
            results.append(f"<br><i>Comparison finished in {end_time - start_time:.2f} seconds.</i>")

            self.comparison_finished.emit(results)

        except Exception as e:
            self.error_occurred.emit(f"An unexpected error occurred: {e}")
        finally:
            self.finished.emit()  # Signal that the worker has finished

    def _compare_files(self, file1, file2):
        """Compares two individual files."""
        results = []
        self.progress_update.emit(10, f"Hashing {os.path.basename(file1)}...")
        hashes1 = calculate_hashes(file1)
        if not hashes1:
             results.append(f'<font color="red">Error hashing {os.path.basename(file1)}</font>')
             return results

        self.progress_update.emit(50, f"Hashing {os.path.basename(file2)}...")
        hashes2 = calculate_hashes(file2)
        if not hashes2:
             results.append(f'<font color="red">Error hashing {os.path.basename(file2)}</font>')
             return results

        self.progress_update.emit(90, "Comparing hashes...")
        results.append(f"--- Comparing Files ---")
        results.append(f"<b>File 1:</b> {file1}")
        results.append(f"<b>File 2:</b> {file2}")
        results.append("<br>")

        match = True
        for HASH_TYPE in ['crc32', 'md5', 'sha256']:
            h1 = hashes1.get(HASH_TYPE, 'N/A')
            h2 = hashes2.get(HASH_TYPE, 'N/A')
            if h1 != h2:
                match = False
                results.append(f'<font color="red"><b>{HASH_TYPE.upper()} Mismatch:</b></font>')
                results.append(f'  File 1: {h1}')
                results.append(f'  File 2: {h2}')
            else:
                results.append(f'<font color="green"><b>{HASH_TYPE.upper()} Match:</b></font> {h1}')

        results.append("<br>")
        if match:
            results.append('<font color="green" size="+1"><b>Overall Result: Files are identical.</b></font>')
        else:
            results.append('<font color="red" size="+1"><b>Overall Result: Files differ.</b></font>')

        self.progress_update.emit(100, "Comparison complete.")
        return results

    def _get_folder_contents(self, folder_path):
        """Recursively gets relative paths and hashes of files in a folder."""
        contents = {}
        base_path = Path(folder_path)
        all_files = []
        try:
            for root, _, files in os.walk(folder_path):
                 if not self._is_running: return None # Check for cancellation
                 for filename in files:
                    full_path = Path(root) / filename
                    relative_path = str(full_path.relative_to(base_path)).replace('\\', '/') # Consistent slashes
                    all_files.append((relative_path, str(full_path)))
        except OSError as e:
            self.error_occurred.emit(f"Error walking directory {folder_path}: {e}")
            return None

        total_files = len(all_files)
        processed_files = 0

        for relative_path, full_path_str in all_files:
            if not self._is_running: return None # Check for cancellation

            processed_files += 1
            percentage = int((processed_files / total_files) * 100) if total_files > 0 else 0
            self.progress_update.emit(percentage, f"Hashing {relative_path} ({processed_files}/{total_files})...")

            hashes = calculate_hashes(full_path_str)
            if hashes:
                contents[relative_path] = hashes
            else:
                contents[relative_path] = {'error': f'Could not hash {full_path_str}'} # Mark error

        return contents

    def _compare_folders(self, dir1, dir2):
        """Compares two directories."""
        results = []
        results.append("--- Comparing Folders ---")
        results.append(f"<b>Folder 1:</b> {dir1}")
        results.append(f"<b>Folder 2:</b> {dir2}")
        results.append("<br>")

        self.progress_update.emit(0, "Scanning Folder 1...")
        contents1 = self._get_folder_contents(dir1)
        if contents1 is None: # Check if stopped or error occurred
             if not self._is_running:
                 results.append('<font color="orange">Comparison cancelled.</font>')
                 return results
             else:
                 results.append(f'<font color="red">Error processing Folder 1.</font>')
                 return results


        self.progress_update.emit(0, "Scanning Folder 2...") # Reset progress for second folder scan
        contents2 = self._get_folder_contents(dir2)
        if contents2 is None: # Check if stopped or error occurred
             if not self._is_running:
                 results.append('<font color="orange">Comparison cancelled.</font>')
                 return results
             else:
                 results.append(f'<font color="red">Error processing Folder 2.</font>')
                 return results

        self.progress_update.emit(0, "Comparing folder structures and file hashes...")

        all_files = set(contents1.keys()) | set(contents2.keys())
        if not all_files:
             results.append('<font color="green">Both folders are empty or contain no processable files.</font>')
             self.progress_update.emit(100, "Comparison complete.")
             return results

        only_in_1 = []
        only_in_2 = []
        mismatched = []
        matched = []
        errors = []

        total_comparisons = len(all_files)
        processed_comparisons = 0

        for rel_path in sorted(list(all_files)):
            if not self._is_running:
                 results.append('<font color="orange">Comparison cancelled during analysis.</font>')
                 return results

            processed_comparisons += 1
            percentage = int((processed_comparisons / total_comparisons) * 100)
            self.progress_update.emit(percentage, f"Comparing: {rel_path}")

            hashes1 = contents1.get(rel_path)
            hashes2 = contents2.get(rel_path)

            if hashes1 and 'error' in hashes1:
                errors.append(f'Error hashing "{rel_path}" in Folder 1: {hashes1["error"]}')
            if hashes2 and 'error' in hashes2:
                errors.append(f'Error hashing "{rel_path}" in Folder 2: {hashes2["error"]}')

            if hashes1 and hashes2 and 'error' not in hashes1 and 'error' not in hashes2:
                # Compare hashes only if both files were hashed successfully
                if hashes1 == hashes2:
                    matched.append(rel_path)
                else:
                    diff_details = []
                    for HASH_TYPE in ['crc32', 'md5', 'sha256']:
                        h1 = hashes1.get(HASH_TYPE, 'N/A')
                        h2 = hashes2.get(HASH_TYPE, 'N/A')
                        if h1 != h2:
                            diff_details.append(f'{HASH_TYPE.upper()} differs')
                    mismatched.append(f'{rel_path} ({", ".join(diff_details)})')

            elif hashes1 and not hashes2:
                if 'error' not in hashes1: # Only report as unique if not an error case
                    only_in_1.append(rel_path)
            elif hashes2 and not hashes1:
                if 'error' not in hashes2: # Only report as unique if not an error case
                 only_in_2.append(rel_path)
            # If one or both had errors, they are already added to the 'errors' list

        # --- Format Results ---
        if errors:
            results.append(f'<font color="red"><b>--- Hashing Errors Encountered ---</b></font>')
            results.extend([f'- {e}' for e in errors])
            results.append("<br>")

        if only_in_1:
            results.append(f'<font color="#CCCC00"><b>--- Unique to Folder 1 ({len(only_in_1)}) ---</b></font>')
            results.extend([f'- {f}' for f in only_in_1])
            results.append("<br>")

        if only_in_2:
            results.append(f'<font color="#CCCC00"><b>--- Unique to Folder 2 ({len(only_in_2)}) ---</b></font>')
            results.extend([f'- {f}' for f in only_in_2])
            results.append("<br>")

        if mismatched:
            results.append(f'<font color="red"><b>--- Mismatched Files ({len(mismatched)}) ---</b></font>')
            results.extend([f'- {f}' for f in mismatched])
            results.append("<br>")

        if matched:
            results.append(f'<font color="green"><b>--- Matched Files ({len(matched)}) ---</b></font>')
            # Optionally list matched files - can be very long
            # results.extend([f'- {f}' for f in matched])
            results.append(f'({len(matched)} files are identical)')
            results.append("<br>")

        if not errors and not only_in_1 and not only_in_2 and not mismatched and matched:
             results.append('<font color="green" size="+1"><b>Overall Result: Folders are identical.</b></font>')
        elif not errors and not only_in_1 and not only_in_2 and not mismatched and not matched and (contents1 or contents2):
             results.append('<font color="orange">Folders compared, but only errors occurred or structure prevented comparison.</font>')
        else:
             results.append('<font color="red" size="+1"><b>Overall Result: Folders differ.</b></font>')


        self.progress_update.emit(100, "Comparison complete.")
        return results

# --- Main GUI Application ---

class FileComparerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.path1 = ""
        self.path2 = ""
        self.worker = None
        self.thread = None
        self.initUI()
        self.apply_stylesheet()

    def initUI(self):
        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT) # x, y, width, height

        # Layouts
        main_layout = QVBoxLayout(self)
        input_layout = QHBoxLayout()
        path1_layout = QVBoxLayout()
        path2_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        status_layout = QHBoxLayout()

        # --- Input Area 1 ---
        lbl1 = QLabel("Item 1:")
        self.le_path1 = QLineEdit()
        self.le_path1.setPlaceholderText("Select file or folder...")
        self.le_path1.setReadOnly(True)
        self.btn_browse1 = QPushButton("Browse...")
        self.btn_browse1.clicked.connect(self.browse_item1)
        path1_layout.addWidget(lbl1)
        path1_layout.addWidget(self.le_path1)
        path1_layout.addWidget(self.btn_browse1)

        # --- Input Area 2 ---
        lbl2 = QLabel("Item 2:")
        self.le_path2 = QLineEdit()
        self.le_path2.setPlaceholderText("Select file or folder...")
        self.le_path2.setReadOnly(True)
        self.btn_browse2 = QPushButton("Browse...")
        self.btn_browse2.clicked.connect(self.browse_item2)
        path2_layout.addWidget(lbl2)
        path2_layout.addWidget(self.le_path2)
        path2_layout.addWidget(self.btn_browse2)

        input_layout.addLayout(path1_layout)
        input_layout.addLayout(path2_layout)

        # --- Control Buttons ---
        self.btn_compare = QPushButton("Compare")
        self.btn_compare.setIcon(QIcon.fromTheme("edit-find-replace", QIcon(":/qt-project.org/styles/commonstyle/images/standardbutton-ok-16.png"))) # Example icon
        self.btn_compare.clicked.connect(self.start_comparison)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setIcon(QIcon.fromTheme("edit-clear", QIcon(":/qt-project.org/styles/commonstyle/images/standardbutton-cancel-16.png"))) # Example icon
        self.btn_clear.clicked.connect(self.clear_all)

        button_layout.addStretch()
        button_layout.addWidget(self.btn_compare)
        button_layout.addWidget(self.btn_clear)
        button_layout.addStretch()

        # --- Results Area ---
        self.txt_results = QTextEdit()
        self.txt_results.setReadOnly(True)
        self.txt_results.setFont(QFont("Courier New", 10)) # Monospaced font is good for hashes

        # --- Status Bar ---
        self.lbl_status = QLabel("Status: Idle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(15)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        status_layout.addWidget(self.lbl_status, 1) # Add stretch factor
        status_layout.addWidget(self.progress_bar)

        # --- Assemble Main Layout ---
        main_layout.addLayout(input_layout)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(QLabel("Comparison Results:"))
        main_layout.addWidget(self.txt_results, 1) # Add stretch factor for results area
        main_layout.addLayout(status_layout)

        self.setLayout(main_layout)

    def apply_stylesheet(self):
        """Applies a modern dark theme stylesheet."""
        self.setStyleSheet("""
            QWidget {
                background-color: #2E2E2E;
                color: #E0E0E0;
                font-size: 10pt;
                font-family: 'Segoe UI', Arial, sans-serif; /* Common modern font */
            }
            QLineEdit {
                background-color: #3C3C3C;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 3px;
            }
            QLineEdit:read-only {
                background-color: #333333;
            }
            QPushButton {
                background-color: #555555;
                color: #FFFFFF;
                border: 1px solid #666666;
                padding: 6px 12px;
                border-radius: 4px;
                min-width: 80px; /* Ensure buttons have some width */
            }
            QPushButton:hover {
                background-color: #6A6A6A;
                border: 1px solid #777777;
            }
            QPushButton:pressed {
                background-color: #4A4A4A;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888888;
            }
            QTextEdit {
                background-color: #252525;
                border: 1px solid #555555;
                border-radius: 3px;
                font-family: 'Consolas', 'Courier New', monospace; /* Better for code/hashes */
            }
            QLabel {
                color: #C0C0C0; /* Slightly lighter labels */
                padding-bottom: 3px; /* Add space below labels */
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center; /* Although text is hidden, good practice */
                background-color: #3C3C3C;
            }
            QProgressBar::chunk {
                background-color: #007ACC; /* A nice blue */
                border-radius: 3px;
            }
        """)


    def browse_item(self, line_edit_target, path_attr):
        """Opens a dialog to select either a file or a folder."""
        # Start in the directory of the currently selected path, if any
        current_path = getattr(self, path_attr)
        start_dir = os.path.dirname(current_path) if current_path and os.path.exists(os.path.dirname(current_path)) else os.path.expanduser("~")

        # Use QFileDialog.getOpenFileUrl for more flexibility? No, simpler is better.
        # We allow selecting EITHER a file OR a directory.
        # We can't use getExistingDirectory and getOpenFileName together easily.
        # So, we use a file dialog that *can* select directories, though it's non-standard on some platforms.
        # A better approach might be separate buttons, but this keeps UI cleaner.
        # Let's try getExistingDirectory first, then maybe getOpenFileName if user wants a file.
        # *Correction*: The easiest way is to just let the user pick something and check after.

        # We'll use a different approach - ask the user if they want to select a file or directory
        options = QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        
        # First try to select a file
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", start_dir
        )
        
        # If user didn't select a file, try to select a directory
        if not file_path:
            dir_path = QFileDialog.getExistingDirectory(
                self, "Select Folder", start_dir, options=options
            )
            if dir_path:  # User selected a directory
                line_edit_target.setText(dir_path)
                setattr(self, path_attr, dir_path)
        else:  # User selected a file
            line_edit_target.setText(file_path)
            setattr(self, path_attr, file_path)


    def browse_item1(self):
        self.browse_item(self.le_path1, "path1")

    def browse_item2(self):
        self.browse_item(self.le_path2, "path2")

    def start_comparison(self):
        """Initiates the comparison process in a background thread."""
        if not self.path1 or not self.path2:
            self.update_status("Error: Please select two items to compare.", error=True)
            self.txt_results.setHtml('<font color="red">Please select two files or folders first.</font>')
            return

        if not os.path.exists(self.path1):
             self.update_status(f"Error: Path does not exist: {self.path1}", error=True)
             self.txt_results.setHtml(f'<font color="red">Path does not exist: {self.path1}</font>')
             return
        if not os.path.exists(self.path2):
             self.update_status(f"Error: Path does not exist: {self.path2}", error=True)
             self.txt_results.setHtml(f'<font color="red">Path does not exist: {self.path2}</font>')
             return

        self.set_controls_enabled(False)
        self.txt_results.clear()
        self.progress_bar.setValue(0)
        self.update_status("Starting comparison...")

        # Setup and start the thread
        self.thread = QThread()
        self.worker = CompareWorker(self.path1, self.path2)
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.thread.started.connect(self.worker.run_comparison)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.comparison_finished.connect(self.display_results)
        self.worker.error_occurred.connect(self.show_error)

        # Clean up after thread finishes
        self.worker.finished.connect(self.thread.quit) # Signal worker is done
        self.worker.finished.connect(self.worker.deleteLater) # Schedule worker deletion
        self.thread.finished.connect(self.thread.deleteLater) # Schedule thread deletion
        self.thread.finished.connect(lambda: self.set_controls_enabled(True)) # Re-enable controls

        self.thread.start()

    def update_progress(self, percentage, message):
        """Updates the progress bar and status label."""
        self.progress_bar.setValue(percentage)
        self.lbl_status.setText(f"Status: {message}")

    def display_results(self, results_html_list):
        """Displays the formatted results in the text edit."""
        self.txt_results.setHtml("<br>".join(results_html_list))
        self.update_progress(100, "Comparison complete.") # Ensure status shows complete

    def show_error(self, error_message):
        """Displays an error message in the status bar and results."""
        self.update_status(f"Error: {error_message}", error=True)
        self.txt_results.setHtml(f'<font color="red"><b>Error during comparison:</b><br>{error_message}</font>')
        self.progress_bar.setValue(0) # Reset progress on error
        self.set_controls_enabled(True) # Re-enable controls on error

    def update_status(self, message, error=False):
        """Updates the status label, optionally styling for errors."""
        self.lbl_status.setText(f"Status: {message}")
        # Optionally change status label color for errors (requires adjusting stylesheet or palette)
        # For simplicity, keeping color consistent but could be enhanced.

    def set_controls_enabled(self, enabled):
        """Enables or disables input controls during processing."""
        self.btn_browse1.setEnabled(enabled)
        self.btn_browse2.setEnabled(enabled)
        self.btn_compare.setEnabled(enabled)
        self.btn_clear.setEnabled(enabled)
        # Indicate busy state on line edits (optional)
        self.le_path1.setReadOnly(not enabled)
        self.le_path2.setReadOnly(not enabled)


    def clear_all(self):
        """Clears inputs, results, and status."""
        self.path1 = ""
        self.path2 = ""
        self.le_path1.clear()
        self.le_path2.clear()
        self.txt_results.clear()
        self.progress_bar.setValue(0)
        self.update_status("Idle")
        if self.thread and self.thread.isRunning():
             # Simple cancellation attempt if needed in future
             if hasattr(self.worker, 'stop'):
                 self.worker.stop()
             print("Attempted to stop running comparison.")
             # Proper cancellation requires checks within the worker loops

    def closeEvent(self, event):
        """Ensure worker thread is stopped on window close."""
        if self.thread and self.thread.isRunning():
            if hasattr(self.worker, 'stop'):
                self.worker.stop() # Signal worker to stop
            self.thread.quit() # Ask thread to exit event loop
            if not self.thread.wait(1000): # Wait max 1 sec for thread to finish
                print("Warning: Comparison thread did not stop gracefully.")
        event.accept()


# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Force a style that might look more modern if available
    # app.setStyle(QStyleFactory.create('Fusion'))

    # Apply a dark palette globally (alternative/complement to stylesheet)
    # palette = QPalette()
    # palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    # palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    # # ... set other colors ...
    # app.setPalette(palette)

    main_window = FileComparerApp()
    main_window.show()
    sys.exit(app.exec())