import asyncio
import os
import sys
import re
from datetime import datetime, timezone
import pytz  # For timezone handling
import threading
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QStatusBar,
    QMessageBox, QDateEdit, QFormLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSettings, QDate
from PyQt6.QtGui import QPalette, QColor

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    ApiIdInvalidError, ApiIdPublishedFloodError, FloodWaitError, ChannelInvalidError,
    AuthKeyError
)

# --- Configuration ---
MAX_FILENAME_LENGTH = 200 # Adjusted for better compatibility
SETTINGS_ORGANIZATION = "MyCompany" # Or your name/org
SETTINGS_APPNAME = "TelegramImageDownloader"

# --- Helper Functions ---
def sanitize_filename(filename):
    """Sanitizes a string to be used as a filename."""
    # Remove characters that are definitely invalid
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    # Replace multiple consecutive underscores/spaces with a single one
    sanitized = re.sub(r'[_ ]+', '_', sanitized)
    # Remove leading/trailing underscores/spaces
    sanitized = sanitized.strip('_ ')
    # Truncate if too long
    if len(sanitized) > MAX_FILENAME_LENGTH:
        # Try to keep the extension if possible
        base, ext = os.path.splitext(sanitized)
        if len(ext) < 10: # Basic check for a reasonable extension
             max_base_len = MAX_FILENAME_LENGTH - len(ext)
             sanitized = base[:max_base_len] + ext
        else: # If no clear extension or extension is too long, just truncate
             sanitized = sanitized[:MAX_FILENAME_LENGTH]
    # Handle empty filenames after sanitization
    if not sanitized:
        return "downloaded_image"
    return sanitized

# --- Downloader Logic (Worker) ---
class DownloaderWorker(QObject):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str, str) # title, message
    download_finished = pyqtSignal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.client = None
        self._running = False
        self._paused = False
        self._stop_requested = False
        self.loop = None

    def run(self):
        self._running = True
        self._paused = False
        self._stop_requested = False
        self.count = 0

        try:
            # Get a new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.download_images())
        except Exception as e:
            self.status_updated.emit(f"Error: {e}")
            self.error_occurred.emit("Download Error", f"An unexpected error occurred:\n{type(e).__name__}: {e}")
        finally:
            if self.loop and self.loop.is_running():
                self.loop.stop() # Ensure loop stops if interrupted
            self._running = False
            if not self._stop_requested:
                 self.download_finished.emit(f"Finished. Downloaded {self.count} images.")
            else:
                 self.download_finished.emit(f"Stopped. Downloaded {self.count} images.")

    async def download_images(self):
        self.status_updated.emit("Connecting to Telegram...")
        session_name = "telegram_session" # Use a dedicated session file name
        try:
            self.client = TelegramClient(session_name,
                                         int(self.settings['api_id']),
                                         self.settings['api_hash'],
                                         loop=self.loop) # Pass the loop

            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.status_updated.emit("Authorization needed...")
                await self.client.send_code_request(self.settings['phone'])
                # Need GUI interaction for code/password - This part is complex
                # For simplicity, assume user authorizes via console/another client first
                # Or implement dialogs to ask for code/password (more involved)
                # Raising an error for now if not authorized.
                # You might need to run the script once in a terminal to authorize.
                self.error_occurred.emit("Authorization Required",
                                         "Please run the script once in a terminal "
                                         "to log in and authorize the session, "
                                         "or ensure the session file is valid.")
                await self.client.disconnect()
                return # Stop execution if not authorized

            self.status_updated.emit("Fetching channel info...")
            try:
                channel = await self.client.get_entity(self.settings['channel'])
            except ValueError: # Often raised for invalid usernames/IDs
                 raise ChannelInvalidError(request=None) # Raise specific error


            self.status_updated.emit(f"Starting download from {self.settings['channel']}...")

            # Convert QDate to timezone-aware datetime (start of day in local timezone, then UTC)
            start_qdate = self.settings.get('start_date', QDate(2000, 1, 1)) # Default very old date
            local_tz = pytz.timezone(QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME).value("System/Timezone", "UTC")) # Try to get local tz
            start_datetime_local = datetime.combine(start_qdate.toPyDate(), datetime.min.time(), tzinfo=local_tz)
            start_datetime_utc = start_datetime_local.astimezone(timezone.utc)

            self.status_updated.emit(f"Filtering images from: {start_qdate.toString(Qt.DateFormat.ISODate)}")

            # Iterate messages, starting from latest
            async for message in self.client.iter_messages(channel):
                if self._stop_requested:
                    self.status_updated.emit("Stopping...")
                    break

                while self._paused:
                    if self._stop_requested: break # Check stop request during pause
                    self.status_updated.emit("Paused...")
                    await asyncio.sleep(1) # Check pause state every second

                if self._stop_requested: break # Check again after pause loop

                # Date Filtering (compare timezone-aware datetimes)
                if message.date < start_datetime_utc:
                    self.status_updated.emit("Reached start date. Stopping iteration.")
                    break # Stop if message date is older than filter date

                if message.media and isinstance(message.media, MessageMediaPhoto):
                    # Use message text as caption, provide default if empty
                    caption_raw = message.message if message.message else "no_caption"
                    # Format date (local time might be nicer for filenames)
                    message_date_local = message.date.astimezone(local_tz)
                    date_str = message_date_local.strftime("%Y%m%d_%H%M%S")

                    # Create and sanitize filename
                    filename_base = f"{date_str}_{caption_raw}"
                    filename_sanitized = sanitize_filename(filename_base) + ".jpg"
                    full_path = os.path.join(self.settings['save_folder'], filename_sanitized)

                    try:
                        self.status_updated.emit(f"Downloading: {filename_sanitized}")
                        await self.client.download_media(message.media, file=full_path)
                        self.count += 1
                        self.progress_updated.emit(self.count)
                    except Exception as download_err:
                        self.status_updated.emit(f"Skipped download due to error: {download_err}")
                        # Optionally log this error more formally
                        await asyncio.sleep(0.1) # Small delay after error


                await asyncio.sleep(0.05) # Small delay to prevent flooding

        except (ApiIdInvalidError, ApiIdPublishedFloodError):
            self.error_occurred.emit("Telegram Error", "Invalid API ID or Hash.")
        except PhoneNumberInvalidError:
            self.error_occurred.emit("Telegram Error", "Invalid Phone Number format.")
        except PhoneCodeInvalidError:
             self.error_occurred.emit("Telegram Error", "Invalid confirmation code.")
        except SessionPasswordNeededError:
             self.error_occurred.emit("Telegram Error", "Two-factor authentication password needed. Please configure session.")
        except AuthKeyError:
             self.error_occurred.emit("Telegram Error", "Authorization key error. Session might be corrupted or revoked. Try deleting 'telegram_session.session' file.")
        except ChannelInvalidError:
            self.error_occurred.emit("Telegram Error", f"Cannot find channel '{self.settings['channel']}'. Check username/ID.")
        except FloodWaitError as e:
             self.error_occurred.emit("Telegram Error", f"Flood wait requested by Telegram. Please wait {e.seconds} seconds and try again.")
        except ConnectionError:
             self.error_occurred.emit("Network Error", "Could not connect to Telegram. Check your internet connection.")
        except Exception as e:
            # Catch other potential errors during setup or iteration
            self.error_occurred.emit("Download Error", f"An unexpected error occurred:\n{type(e).__name__}: {e}")
            import traceback
            print(f"Unhandled error: {e}") # Log full traceback to console for debugging
            traceback.print_exc()
        finally:
            if self.client and self.client.is_connected():
                await self.client.disconnect()
                self.status_updated.emit("Disconnected.")
            self._running = False


    def stop(self):
        self._stop_requested = True
        self._paused = False # Ensure it's not stuck in paused state if stopped
        # Attempt to cancel the asyncio task if the loop is running
        if self.loop and self.loop.is_running():
             # Finding the task to cancel can be tricky if not stored
             # Setting flag is often sufficient for cooperative cancellation
             pass

    def pause(self):
        if self._running:
            self._paused = True
            self.status_updated.emit("Pausing...")

    def resume(self):
        if self._running:
            self._paused = False
            self.status_updated.emit("Resuming...")

    def toggle_pause(self):
        if not self._running: return
        if self._paused:
            self.resume()
        else:
            self.pause()

    def is_running(self):
        return self._running

    def is_paused(self):
        return self._paused


# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Image Downloader")
        self.setGeometry(100, 100, 600, 450) # x, y, width, height

        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
        self.downloader_thread = None
        self.downloader_worker = None

        self.init_ui()
        self.load_settings()
        self.update_button_states()
        self.apply_stylesheet() # Apply custom styling

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # --- Settings Form ---
        form_layout = QFormLayout()

        load_dotenv() # Load .env file if it exists

        self.api_id_entry = QLineEdit()
        self.api_hash_entry = QLineEdit()
        self.api_hash_entry.setEchoMode(QLineEdit.EchoMode.Password) # Hide hash
        self.phone_entry = QLineEdit()
        self.channel_entry = QLineEdit()

        # Try loading from environment variables first if fields are empty
        self.api_id_entry.setPlaceholderText("Enter API ID (or set TELEGRAM_API_ID in .env)")
        self.api_hash_entry.setPlaceholderText("Enter API Hash (or set TELEGRAM_API_HASH in .env)")
        self.phone_entry.setPlaceholderText("Enter Phone +CountryCode (or set TELEGRAM_PHONE in .env)")
        self.channel_entry.setPlaceholderText("Enter Channel Username (e.g., @channelname) or ID")

        self.api_id_entry.setText(os.getenv("TELEGRAM_API_ID", ""))
        self.api_hash_entry.setText(os.getenv("TELEGRAM_API_HASH", ""))
        self.phone_entry.setText(os.getenv("TELEGRAM_PHONE", ""))

        form_layout.addRow(QLabel("API ID:"), self.api_id_entry)
        form_layout.addRow(QLabel("API Hash:"), self.api_hash_entry)
        form_layout.addRow(QLabel("Phone Number:"), self.phone_entry)
        form_layout.addRow(QLabel("Channel Username/ID:"), self.channel_entry)

        layout.addLayout(form_layout)

        # --- Folder Selection ---
        folder_layout = QHBoxLayout()
        self.folder_button = QPushButton("Select Save Folder")
        self.folder_button.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected.")
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_button)
        folder_layout.addWidget(self.folder_label, 1) # Stretch label
        layout.addLayout(folder_layout)

        # --- Date Filter ---
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("Download images from:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate().addMonths(-1)) # Default to 1 month ago
        date_layout.addWidget(self.date_edit)
        date_layout.addStretch()
        layout.addLayout(date_layout)


        # --- Control Buttons ---
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Download")
        self.pause_resume_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")

        self.start_button.clicked.connect(self.start_download)
        self.pause_resume_button.clicked.connect(self.toggle_pause_resume)
        self.stop_button.clicked.connect(self.stop_download)

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.pause_resume_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        layout.addStretch() # Push status bar to bottom

        # --- Status Bar ---
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.count_label = QLabel("Images saved: 0")
        self.statusBar.addPermanentWidget(self.count_label)
        self.status_label = QLabel("Ready.")
        self.statusBar.addWidget(self.status_label, 1) # Stretch status label

    def apply_stylesheet(self):
        # Basic modern stylesheet (adjust colors as desired)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0; /* Light gray background */
            }
            QWidget {
                font-size: 10pt;
            }
            QLineEdit, QDateEdit {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
            }
            QPushButton {
                padding: 8px 15px;
                border: 1px solid #0078d7; /* Blue border */
                border-radius: 4px;
                background-color: #0078d7; /* Blue background */
                color: white; /* White text */
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #005a9e; /* Darker blue on hover */
                border-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #003a6a; /* Even darker blue when pressed */
                border-color: #003a6a;
            }
            QPushButton:disabled {
                background-color: #d3d3d3; /* Gray when disabled */
                border-color: #b0b0b0;
                color: #808080;
            }
            QLabel {
                padding: 2px;
            }
            QStatusBar {
                background-color: #e0e0e0; /* Slightly darker status bar */
            }
            QStatusBar QLabel { /* Style labels within status bar */
                 padding: 3px 5px;
            }
            QDateEdit::drop-down {
                 subcontrol-origin: padding;
                 subcontrol-position: top right;
                 width: 20px;
                 border-left: 1px solid #cccccc;
            }
            QDateEdit::down-arrow {
                 image: url(path/to/down_arrow.png); /* Optional: add custom arrow icon */
                 width: 12px;
                 height: 12px;
            }
        """)

    def get_current_settings(self):
        """Reads settings from UI fields."""
        return {
            'api_id': self.api_id_entry.text().strip(),
            'api_hash': self.api_hash_entry.text().strip(),
            'phone': self.phone_entry.text().strip(),
            'channel': self.channel_entry.text().strip(),
            'save_folder': getattr(self, 'save_folder', ''), # Use attribute if set
            'start_date': self.date_edit.date()
        }

    def validate_settings(self, settings_dict):
        """Basic validation of required fields."""
        required = ['api_id', 'api_hash', 'phone', 'channel', 'save_folder']
        missing = [field for field in required if not settings_dict.get(field)]
        if missing:
            self.show_error("Missing Information", f"Please fill in or select: {', '.join(missing)}")
            return False
        # Basic check for numeric API ID
        if not settings_dict['api_id'].isdigit():
            self.show_error("Invalid Input", "API ID must be a number.")
            return False
        return True

    def start_download(self):
        current_settings = self.get_current_settings()
        if not self.validate_settings(current_settings):
            return

        self.save_settings() # Save settings before starting

        self.status_label.setText("Starting...")
        self.count_label.setText("Images saved: 0")

        # Create worker and thread
        self.downloader_worker = DownloaderWorker(current_settings)
        self.downloader_thread = QThread()

        # Move worker to the thread
        self.downloader_worker.moveToThread(self.downloader_thread)

        # Connect signals
        self.downloader_thread.started.connect(self.downloader_worker.run)
        self.downloader_worker.progress_updated.connect(self.update_progress)
        self.downloader_worker.status_updated.connect(self.update_status)
        self.downloader_worker.error_occurred.connect(self.show_error)
        self.downloader_worker.download_finished.connect(self.on_download_finished)

        # Cleanup connection
        self.downloader_worker.download_finished.connect(self.downloader_thread.quit)
        self.downloader_worker.download_finished.connect(self.downloader_worker.deleteLater)
        self.downloader_thread.finished.connect(self.downloader_thread.deleteLater)
        self.downloader_thread.finished.connect(self.update_button_states) # Re-enable buttons on finish

        # Start the thread
        self.downloader_thread.start()
        self.update_button_states() # Disable start, enable stop/pause

    def stop_download(self):
        if self.downloader_worker:
            self.status_label.setText("Stopping request sent...")
            self.downloader_worker.stop()
        # Buttons will update when thread actually finishes via download_finished signal

    def toggle_pause_resume(self):
        if self.downloader_worker and self.downloader_worker.is_running():
            self.downloader_worker.toggle_pause()
            self.update_button_states()

    def update_progress(self, count):
        self.count_label.setText(f"Images saved: {count}")

    def update_status(self, status):
        self.status_label.setText(status)

    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)
        self.status_label.setText(f"Error: {title}") # Show short error status
        # Optionally stop the process on certain errors
        # self.stop_download()

    def on_download_finished(self, final_message):
        self.update_status(final_message)
        self.downloader_thread = None # Clear thread references
        self.downloader_worker = None
        self.update_button_states() # Update buttons after cleanup

    def update_button_states(self):
        is_running = self.downloader_worker is not None and self.downloader_worker.is_running()
        is_paused = is_running and self.downloader_worker.is_paused()

        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)
        self.pause_resume_button.setEnabled(is_running)

        if is_running:
            self.pause_resume_button.setText("Resume" if is_paused else "Pause")
        else:
            self.pause_resume_button.setText("Pause") # Default text when not running

        # Disable settings input while running
        self.api_id_entry.setEnabled(not is_running)
        self.api_hash_entry.setEnabled(not is_running)
        self.phone_entry.setEnabled(not is_running)
        self.channel_entry.setEnabled(not is_running)
        self.folder_button.setEnabled(not is_running)
        self.date_edit.setEnabled(not is_running)


    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder")
        if folder:
            self.save_folder = folder # Store path in attribute
            self.folder_label.setText(f"Save to: {folder}")
            self.settings.setValue("downloader/save_folder", folder) # Save immediately

    def load_settings(self):
        # Load text fields, using existing text (from .env) as default if setting not found
        self.api_id_entry.setText(self.settings.value("telegram/api_id", self.api_id_entry.text()))
        self.api_hash_entry.setText(self.settings.value("telegram/api_hash", self.api_hash_entry.text()))
        self.phone_entry.setText(self.settings.value("telegram/phone", self.phone_entry.text()))
        self.channel_entry.setText(self.settings.value("downloader/channel", ""))

        # Load folder
        folder = self.settings.value("downloader/save_folder", "")
        if folder and os.path.isdir(folder): # Check if saved folder still exists
             self.save_folder = folder
             self.folder_label.setText(f"Save to: {folder}")
        else:
             self.folder_label.setText("No folder selected.")

        # Load date
        date_str = self.settings.value("downloader/start_date", "")
        if date_str:
            saved_date = QDate.fromString(date_str, Qt.DateFormat.ISODate)
            if saved_date.isValid():
                self.date_edit.setDate(saved_date)
        # Else keep the default (1 month ago)


    def save_settings(self):
        self.settings.setValue("telegram/api_id", self.api_id_entry.text().strip())
        self.settings.setValue("telegram/api_hash", self.api_hash_entry.text().strip()) # Hash is saved, consider security implications
        self.settings.setValue("telegram/phone", self.phone_entry.text().strip())
        self.settings.setValue("downloader/channel", self.channel_entry.text().strip())
        if hasattr(self, 'save_folder') and self.save_folder:
            self.settings.setValue("downloader/save_folder", self.save_folder)
        self.settings.setValue("downloader/start_date", self.date_edit.date().toString(Qt.DateFormat.ISODate))


    def closeEvent(self, event):
        """Handle window closing."""
        if self.downloader_worker and self.downloader_worker.is_running():
            reply = QMessageBox.question(self, 'Downloader Running',
                                         "A download is in progress. Stop and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_download()
                # Give the thread a moment to stop, though ideally wait properly
                if self.downloader_thread:
                    self.downloader_thread.quit() # Ask thread to quit
                    if not self.downloader_thread.wait(2000): # Wait max 2 seconds
                         self.status_label.setText("Warning: Download thread did not stop gracefully.")
                self.save_settings()
                event.accept() # Close window
            else:
                event.ignore() # Don't close
        else:
            self.save_settings() # Save settings on normal close
            event.accept()


# --- Main Execution ---
if __name__ == "__main__":
    # Allows Ctrl+C in terminal to work smoothly with Qt
    # signal.signal(signal.SIGINT, signal.SIG_DFL) # Removed, can cause issues with threads

    app = QApplication(sys.argv)

    # Optional: Set a specific style like Fusion for cross-platform consistency
    # app.setStyle('Fusion')

    # # Optional: Apply a dark theme palette (basic example)
    # dark_palette = QPalette()
    # dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    # dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    # # ... set other colors for base, text, button, etc. ...
    # app.setPalette(dark_palette)


    mainWin = MainWindow()
    mainWin.show()
    sys.exit(app.exec())