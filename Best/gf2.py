# --- START OF FILE goodfon_pyqt.py ---

import sys
import os
import requests
from bs4 import BeautifulSoup
import threading
import time
import re
import urllib.parse
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QLineEdit, QPushButton, QProgressBar, QFileDialog, QMessageBox
)
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QMutex, QWaitCondition
from PyQt6.QtGui import QPalette, QColor, QClipboard

# --- Constants ---
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
DEFAULT_BASE_URL = "https://www.goodfon.ru"
DEFAULT_DOWNLOAD_FOLDER = os.path.join(os.getcwd(), "WallpaperDownloads")
LINKS_FILENAME = "links_to_download.txt" # Store intermediate links

# Ensure download folder exists
if not os.path.exists(DEFAULT_DOWNLOAD_FOLDER):
    os.makedirs(DEFAULT_DOWNLOAD_FOLDER)

# --- Utility Functions ---
def sanitize_filename(filename):
    """Removes or replaces characters invalid for filenames."""
    # Remove characters that are explicitly invalid in Windows/Linux/Mac
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace sequences of whitespace with a single underscore
    sanitized = re.sub(r'\s+', '_', sanitized)
    # Limit length if necessary (optional)
    # max_len = 200
    # if len(sanitized) > max_len:
    #     name, ext = os.path.splitext(sanitized)
    #     sanitized = name[:max_len - len(ext)] + ext
    return sanitized

# --- Worker for Scraping and Downloading ---
class DownloadWorker(QObject):
    progress_updated = pyqtSignal(int, int)  # current, total
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, urls, base_url, download_folder):
        super().__init__()
        self.urls = urls
        self.base_url = base_url if base_url.endswith('/') else base_url + '/'
        self.download_folder = download_folder
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self._stop_requested = False
        self._is_paused = False
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()

    def run(self):
        """Main execution method for the worker thread."""
        try:
            self.log_message.emit("Phase 1: Extracting download page links...")
            download_page_links = self._extract_initial_links()

            if not download_page_links:
                self.log_message.emit("No download page links found.")
                self.finished.emit()
                return

            self.log_message.emit(f"Found {len(download_page_links)} potential download pages.")

            self.log_message.emit("Phase 2: Downloading images...")
            self._download_images_from_links(download_page_links)

        except Exception as e:
            self.error_occurred.emit(f"An unexpected error occurred: {e}")
        finally:
            self._session.close()
            self.finished.emit()

    def _extract_initial_links(self):
        """Scrapes the initial list of URLs to find links to wallpaper download pages."""
        all_links = []
        total_pages = len(self.urls)
        for i, page_url in enumerate(self.urls):
            if self._check_stop_pause(): return None # Check for stop/pause

            self.log_message.emit(f"Scraping {page_url} ({i+1}/{total_pages})...")
            try:
                response = self._session.get(page_url.strip(), timeout=20)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                # Find all <a> tags linking to download pages (adjust selector if site changes)
                # Assuming links are relative like /wallpaper/some-name/download/1920x1080/
                link_tags = soup.find_all('a', class_='wallpaper__download__rbut js-size')

                count = 0
                for link_tag in link_tags:
                    href = link_tag.get('href')
                    if href:
                        # Construct absolute URL using the provided base_url
                        full_url = urllib.parse.urljoin(self.base_url, href)
                        all_links.append(full_url)
                        count += 1
                self.log_message.emit(f" > Found {count} links on {page_url}")

            except requests.exceptions.RequestException as e:
                self.log_message.emit(f"Error scraping {page_url}: {e}")
            except Exception as e:
                self.log_message.emit(f"Error processing {page_url}: {e}")
            # Update overall progress based on pages scraped (optional)
            # self.progress_updated.emit(i + 1, total_pages * 2) # Example: phase 1 is half

        return list(set(all_links)) # Remove duplicates

    def _download_images_from_links(self, links):
        """Visits download pages, finds image URLs, and downloads images."""
        total_links = len(links)
        self.progress_updated.emit(0, total_links) # Reset progress for download phase

        for index, link_url in enumerate(links):
            if self._check_stop_pause(): return # Check for stop/pause

            self.log_message.emit(f"Processing {link_url} ({index+1}/{total_links})...")
            try:
                # 1. Get the download page
                response = self._session.get(link_url, timeout=20)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                # 2. Find the actual image tag (adjust selector if site changes)
                # Looking for <img alt="..." src="..."> inside a specific div maybe?
                # Let's assume the main image has an 'alt' attribute as before
                img_tag = soup.find('img', alt=True) # Be more specific if possible!
                                                    # e.g., soup.select_one('div.some_container img[alt]')
                if not img_tag or 'src' not in img_tag.attrs:
                    self.log_message.emit(f" ! Image tag not found on {link_url}")
                    continue

                img_src = img_tag['src']
                # Construct absolute image URL if it's relative
                img_full_url = urllib.parse.urljoin(link_url, img_src) # Use link_url as base

                # 3. Download the image
                img_response = self._session.get(img_full_url, stream=True, timeout=30)
                img_response.raise_for_status()

                # 4. Save the image
                img_name = os.path.basename(urllib.parse.urlparse(img_full_url).path)
                if not img_name: # Handle cases where path ends in /
                    img_name = f"image_{index+1}.jpg" # Fallback name
                
                sanitized_img_name = sanitize_filename(img_name)
                save_path = os.path.join(self.download_folder, sanitized_img_name)

                # Check if file already exists (optional)
                if os.path.exists(save_path):
                    self.log_message.emit(f" > Skipping, already exists: {sanitized_img_name}")
                    self.progress_updated.emit(index + 1, total_links)
                    continue

                with open(save_path, 'wb') as img_file:
                    for chunk in img_response.iter_content(chunk_size=8192):
                        img_file.write(chunk)
                        if self._check_stop_pause(): # Check frequently during download
                             img_file.close()
                             os.remove(save_path) # Clean up partial file
                             self.log_message.emit(f" > Download cancelled for {sanitized_img_name}")
                             return


                self.log_message.emit(f" > Saved: {sanitized_img_name}")
                self.progress_updated.emit(index + 1, total_links)

            except requests.exceptions.RequestException as e:
                self.log_message.emit(f" ! Network error processing {link_url}: {e}")
            except Exception as e:
                self.log_message.emit(f" ! Error processing {link_url}: {e}")

        if not self._stop_requested:
            self.log_message.emit("Image downloading finished.")


    def _check_stop_pause(self):
        """Checks for stop or pause requests."""
        self._pause_mutex.lock()
        while self._is_paused and not self._stop_requested:
             self._pause_mutex.unlock() # Unlock before waiting
             self.log_message.emit("Paused...") # Emit pause status maybe once
             time.sleep(0.5) # Use Qt's wait condition ideally, but sleep is simpler here
             # self._pause_condition.wait(self._pause_mutex) # Proper Qt way
             self._pause_mutex.lock() # Relock after wake-up/sleep
        
        should_stop = self._stop_requested
        self._pause_mutex.unlock() # Ensure unlocked before returning

        if should_stop:
             self.log_message.emit("Stop request received.")
             return True
        return False

    def request_stop(self):
        self._pause_mutex.lock()
        self._stop_requested = True
        if self._is_paused:
            self._is_paused = False # Wake up if paused
            # self._pause_condition.wakeAll() # Proper Qt way
        self._pause_mutex.unlock()


    def toggle_pause(self, pause):
        self._pause_mutex.lock()
        if not self._stop_requested: # Don't pause if already stopping
            self._is_paused = pause
            # if not pause:
            #     self._pause_condition.wakeAll() # Wake up if resuming
        self._pause_mutex.unlock()
        self.log_message.emit("Process paused." if pause else "Process resumed.")


# --- Worker for Clipboard Monitoring ---
class ClipboardWorker(QObject):
    link_captured = pyqtSignal(str)
    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._clipboard = QApplication.clipboard()
        self._stop_requested = False
        self._last_content = self._clipboard.text() # Store initial content

    def run(self):
        self.log_message.emit("Clipboard monitoring started.")
        while not self._stop_requested:
            try:
                current_content = self._clipboard.text()
                if current_content != self._last_content:
                    self._last_content = current_content
                    if current_content.strip().startswith(("http://", "https://")):
                         self.link_captured.emit(current_content.strip())

            except Exception as e:
                 self.log_message.emit(f"Clipboard error: {e}") # Avoid crashing monitor

            # Use QThread's sleep for better integration if needed
            time.sleep(1) # Check every second

        self.log_message.emit("Clipboard monitoring stopped.")
        self.finished.emit()

    def request_stop(self):
        self._stop_requested = True


# --- Main Application Window ---
class WallpaperDownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self._download_thread = None
        self._download_worker = None
        self._clipboard_thread = None
        self._clipboard_worker = None
        self._is_running = False
        self._is_paused = False
        self._capture_mode = False
        self._download_folder = DEFAULT_DOWNLOAD_FOLDER
        self._captured_links_history = set() # Avoid duplicates from clipboard

        self.init_ui()
        self.apply_stylesheet() # Apply the dark theme

    def init_ui(self):
        self.setWindowTitle("GoodFon Wallpaper Downloader (PyQt6)")
        self.setGeometry(100, 100, 700, 600) # x, y, width, height

        # --- Layouts ---
        main_layout = QVBoxLayout(self)
        input_layout = QVBoxLayout()
        folder_layout = QHBoxLayout()
        prefix_layout = QHBoxLayout()
        button_layout = QHBoxLayout()

        # --- Widgets ---
        # URL Input Area
        input_layout.addWidget(QLabel("Enter URLs (one per line):"))
        self.url_text = QTextEdit()
        self.url_text.setPlaceholderText("e.g., https://www.goodfon.ru/catalog/animals/")
        self.url_text.setAcceptRichText(False)
        input_layout.addWidget(self.url_text)

        # Download Folder Selection
        folder_layout.addWidget(QLabel("Save Folder:"))
        self.folder_label = QLineEdit(self._download_folder)
        self.folder_label.setReadOnly(True) # Display only
        folder_layout.addWidget(self.folder_label)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.browse_button)

        # Base URL Prefix Input
        prefix_layout.addWidget(QLabel("Base URL (for relative links):"))
        self.prefix_entry = QLineEdit(DEFAULT_BASE_URL)
        prefix_layout.addWidget(self.prefix_entry)

        # Control Buttons
        self.start_button = QPushButton("Start Download")
        self.start_button.clicked.connect(self.start_process)
        button_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_process)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_process)
        self.pause_button.setEnabled(False)
        button_layout.addWidget(self.pause_button)

        self.capture_button = QPushButton("Enable Clipboard Capture")
        self.capture_button.setCheckable(True)
        self.capture_button.toggled.connect(self.toggle_capture_mode)
        #button_layout.addWidget(self.capture_button) # Add to layout below progress

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%") # Show percentage

        # Log Area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        # --- Assemble Layout ---
        main_layout.addLayout(input_layout)
        main_layout.addLayout(folder_layout)
        main_layout.addLayout(prefix_layout)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.capture_button) # Place capture button here
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_text)

    def apply_stylesheet(self):
        # Simple Dark Theme QSS
        # (For more advanced themes, consider libraries like qdarkstyle or pyqtdarktheme)
        qss = """
            QWidget {
                background-color: #2b2b2b;
                color: #f0f0f0;
                font-size: 10pt;
            }
            QLabel {
                color: #cccccc; /* Lighter gray for labels */
            }
            QLineEdit, QTextEdit {
                background-color: #3c3f41;
                color: #f0f0f0;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
            }
            QLineEdit:read-only {
                 background-color: #4a4d4f; /* Slightly different for read-only */
            }
            QTextEdit:read-only {
                background-color: #252525; /* Darker for log */
            }
            QPushButton {
                background-color: #555555;
                color: #f0f0f0;
                border: 1px solid #666666;
                padding: 5px 10px;
                border-radius: 4px;
                min-height: 20px; /* Ensure buttons have some height */
            }
            QPushButton:hover {
                background-color: #666666;
                border: 1px solid #777777;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888888;
                border-color: #555555;
            }
             QPushButton:checkable:checked {
                 background-color: #4CAF50; /* Green when checked */
                 border-color: #388E3C;
             }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                text-align: center;
                background-color: #3c3f41;
                color: #f0f0f0; /* Color of the percentage text */
            }
            QProgressBar::chunk {
                background-color: #05B8CC; /* Progress bar color */
                border-radius: 3px; /* Slightly smaller radius than the bar */
                margin: 1px; /* Small margin around the chunk */
            }
            QScrollBar:vertical {
                border: 1px solid #555;
                background: #3c3f41;
                width: 12px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #666;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                 border: 1px solid #555;
                background: #3c3f41;
                height: 12px;
                margin: 0px 0px 0px 0px;
            }
             QScrollBar::handle:horizontal {
                background: #666;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """
        self.setStyleSheet(qss)

    # --- Slots (Event Handlers) ---
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self._download_folder)
        if folder:
            self._download_folder = folder
            self.folder_label.setText(folder)
            self.log(f"Download folder set to: {folder}")
             # Ensure new folder exists
            if not os.path.exists(self._download_folder):
                try:
                    os.makedirs(self._download_folder)
                    self.log(f"Created folder: {self._download_folder}")
                except OSError as e:
                    self.show_error(f"Could not create folder: {e}")
                    self._download_folder = DEFAULT_DOWNLOAD_FOLDER # Revert
                    self.folder_label.setText(self._download_folder)


    def start_process(self):
        if self._is_running:
            self.log("Process already running.")
            return

        urls = self.url_text.toPlainText().strip().splitlines()
        urls = [url for url in urls if url.strip()] # Remove empty lines

        if not urls:
            self.show_error("Please enter at least one URL.")
            return

        base_url = self.prefix_entry.text().strip()
        if not base_url:
            self.show_error("Please enter a Base URL.")
            return

        # Ensure download folder exists before starting
        if not os.path.exists(self._download_folder):
            try:
                os.makedirs(self._download_folder)
            except OSError as e:
                 self.show_error(f"Cannot create download folder '{self._download_folder}': {e}")
                 return


        self.log("Starting process...")
        self.log_text.clear() # Clear log for new run
        self._is_running = True
        self._is_paused = False
        self.update_button_states()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")


        # Setup and start the worker thread
        self._download_thread = QThread()
        self._download_worker = DownloadWorker(urls, base_url, self._download_folder)
        self._download_worker.moveToThread(self._download_thread)

        # Connect signals from worker to slots in GUI thread
        self._download_worker.progress_updated.connect(self.update_progress)
        self._download_worker.log_message.connect(self.log)
        self._download_worker.error_occurred.connect(self.handle_error)
        self._download_worker.finished.connect(self.on_worker_finished)

        # Connect thread signals
        self._download_thread.started.connect(self._download_worker.run)
        # self._download_thread.finished.connect(self._download_thread.deleteLater) # Clean up thread
        # self._download_worker.finished.connect(self._download_worker.deleteLater) # Clean up worker


        self._download_thread.start()

    def stop_process(self):
        if self._download_worker:
            self.log("Requesting process stop...")
            self._download_worker.request_stop()
            self.stop_button.setEnabled(False) # Disable stop button once clicked
            self.pause_button.setEnabled(False) # Disable pause too

    def pause_process(self):
        if not self._is_running or not self._download_worker:
            return

        self._is_paused = not self._is_paused
        self._download_worker.toggle_pause(self._is_paused)
        self.pause_button.setText("Resume" if self._is_paused else "Pause")
        # self.log("Process paused." if self._is_paused else "Process resumed.") # Worker logs this

    def toggle_capture_mode(self, checked):
        self._capture_mode = checked
        self.capture_button.setText("Disable Clipboard Capture" if checked else "Enable Clipboard Capture")
        self.log(f"Clipboard capture {'enabled' if checked else 'disabled'}.")

        if checked:
            if self._clipboard_thread is None: # Start only if not already running
                self._clipboard_thread = QThread()
                self._clipboard_worker = ClipboardWorker()
                self._captured_links_history.clear() # Clear history on enable
                # Add links currently in text edit to history to avoid re-adding them
                current_urls = self.url_text.toPlainText().strip().splitlines()
                for url in current_urls:
                    if url.strip(): self._captured_links_history.add(url.strip())

                self._clipboard_worker.moveToThread(self._clipboard_thread)

                self._clipboard_worker.link_captured.connect(self.handle_captured_link)
                self._clipboard_worker.log_message.connect(self.log) # Log monitor status
                self._clipboard_worker.finished.connect(self.on_clipboard_worker_finished)

                self._clipboard_thread.started.connect(self._clipboard_worker.run)
                self._clipboard_thread.start()
            else:
                 self.log("Clipboard monitor already active.") # Should not happen with toggle logic
        else:
            if self._clipboard_worker:
                self._clipboard_worker.request_stop()
            # Thread and worker will be cleaned up in on_clipboard_worker_finished

    def handle_captured_link(self, link):
        if link not in self._captured_links_history:
             self._captured_links_history.add(link)
             self.url_text.append(link) # Add to the end of the text edit
             self.log(f"Clipboard: Captured {link}")

    # --- GUI Update Slots ---
    def update_progress(self, current, total):
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{current}/{total} (%p%)")
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Waiting...")


    def log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum()) # Auto-scroll

    def handle_error(self, error_message):
         self.log(f"ERROR: {error_message}")
         # Optionally show a message box for critical errors
         # self.show_error(error_message)

    def show_error(self, message):
        QMessageBox.warning(self, "Error", message)


    def on_worker_finished(self):
        self.log("Worker thread finished.")
        self._is_running = False
        self._is_paused = False
        self.update_button_states()
        self.progress_bar.setFormat("Finished" if self.progress_bar.value() == 100 else "Stopped")

        # Clean up thread and worker
        if self._download_thread:
            self._download_thread.quit()
            self._download_thread.wait() # Wait for thread to terminate
            # self._download_thread.deleteLater() # Schedule deletion
            # if self._download_worker:
            #     self._download_worker.deleteLater()
            self._download_thread = None
            self._download_worker = None


    def on_clipboard_worker_finished(self):
         self.log("Clipboard monitor thread finished.")
         # Clean up clipboard thread and worker
         if self._clipboard_thread:
             self._clipboard_thread.quit()
             self._clipboard_thread.wait()
            #  self._clipboard_thread.deleteLater()
            #  if self._clipboard_worker:
            #      self._clipboard_worker.deleteLater()
             self._clipboard_thread = None
             self._clipboard_worker = None
             # Ensure button reflects stopped state if finished unexpectedly
             if self.capture_button.isChecked():
                 self.capture_button.setChecked(False)


    def update_button_states(self):
        self.start_button.setEnabled(not self._is_running)
        self.stop_button.setEnabled(self._is_running)
        self.pause_button.setEnabled(self._is_running)
        self.pause_button.setText("Pause") # Reset pause button text

        # Also disable inputs/browse while running
        self.url_text.setReadOnly(self._is_running)
        self.prefix_entry.setReadOnly(self._is_running)
        self.browse_button.setEnabled(not self._is_running)


    # --- Cleanup on Close ---
    def closeEvent(self, event):
        """Ensure threads are stopped cleanly when the window is closed."""
        self.log("Close event triggered. Cleaning up...")

        # Stop clipboard monitor first
        if self._clipboard_worker:
            self._clipboard_worker.request_stop()
            if self._clipboard_thread:
                 self._clipboard_thread.quit()
                 if not self._clipboard_thread.wait(1000): # Wait max 1 sec
                      self.log("Clipboard thread did not terminate gracefully.")
                      # self._clipboard_thread.terminate() # Force terminate if stuck (use cautiously)


        # Then stop download worker
        if self._download_worker:
            self._download_worker.request_stop()
            if self._download_thread:
                 self._download_thread.quit()
                 if not self._download_thread.wait(3000): # Wait max 3 secs
                      self.log("Download thread did not terminate gracefully.")
                      # self._download_thread.terminate() # Force terminate

        self.log("Cleanup finished. Exiting.")
        event.accept()


# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Force the style to be Fusion for a more consistent look across platforms
    # You might need to experiment with styles depending on your OS
    # app.setStyle("Fusion")

    # # Optional: Setup a slightly nicer palette for Fusion style
    # fusion_palette = QPalette()
    # fusion_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    # # ... set other colors ...
    # app.setPalette(fusion_palette)

    window = WallpaperDownloaderApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE goodfon_pyqt.py ---