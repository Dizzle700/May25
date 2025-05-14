import asyncio
import os
import sys
import re
from datetime import datetime, timezone
import pytz  # For timezone handling
import threading
from dotenv import load_dotenv
import pandas as pd  # For Excel export

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QStatusBar,
    QMessageBox, QDateEdit, QFormLayout, QSizePolicy, QDialog,
    QCheckBox, QProgressBar, QTextEdit, QDialogButtonBox
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
def sanitize_filename(filename, exclusion_patterns=None):
    """
    Sanitizes a string to be used as a filename.
    If exclusion_patterns is provided, will remove any matching patterns from the filename.
    """
    # Apply exclusions if provided
    if exclusion_patterns:
        for pattern in exclusion_patterns:
            if pattern.startswith("regex:"):
                # Handle regex pattern
                regex_pattern = pattern[6:]  # Remove "regex:" prefix
                try:
                    filename = re.sub(regex_pattern, '', filename)
                except re.error:
                    # If regex is invalid, just skip it
                    pass
            else:
                # Handle normal pattern
                filename = filename.replace(pattern, '')
    
    # Original sanitization code
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
class AuthCodeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Telegram Authentication")
        self.setFixedWidth(400)
        layout = QVBoxLayout(self)

        # Instructions
        auth_info_label = QLabel(
            "IMPORTANT: Please check your Telegram app on your phone. "
            "Telegram has sent you a verification code through the app. "
            "Look for a message from 'Telegram' in your chats.")
        auth_info_label.setWordWrap(True)
        auth_info_label.setStyleSheet("font-weight: bold; color: #D32F2F;")
        layout.addWidget(auth_info_label)

        # Instructions
        self.instruction_label = QLabel("Enter the code you received:")
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        # Code input
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Enter code here (e.g. 12345)")
        self.code_input.setMaxLength(10)  # Telegram codes are typically 5 digits
        layout.addWidget(self.code_input)

        # Password field (for 2FA)
        self.password_label = QLabel("If you have two-factor authentication enabled, enter your password:")
        self.password_label.setWordWrap(True)
        layout.addWidget(self.password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("2FA Password (if needed)")
        layout.addWidget(self.password_input)

        # Buttons
        button_layout = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.submit_button = QPushButton("Submit")
        self.submit_button.setDefault(True)
        
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.submit_button)
        layout.addLayout(button_layout)

    def get_code(self):
        return self.code_input.text().strip()
        
    def get_password(self):
        return self.password_input.text().strip()

class DownloaderWorker(QObject):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str, str) # title, message
    download_finished = pyqtSignal(str)
    auth_code_needed = pyqtSignal(str)  # New signal for requesting auth code
    auth_password_needed = pyqtSignal(str)  # New signal for requesting 2FA password
    excel_exported = pyqtSignal(str)  # Signal for when Excel is exported

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.client = None
        self._running = False
        self._paused = False
        self._stop_requested = False
        self.loop = None
        self._auth_code = None
        self._auth_password = None
        self._waiting_for_auth = False
        self._current_task = None
        self.image_data = []  # List to store image metadata for Excel export

    def run(self):
        self._running = True
        self._paused = False
        self._stop_requested = False
        self.count = 0

        try:
            # Get a new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Create and store the task so it can be cancelled
            self._current_task = self.loop.create_task(self.download_images())
            self.loop.run_until_complete(self._current_task)
        except asyncio.CancelledError:
            self.status_updated.emit("Task was cancelled.")
        except Exception as e:
            self.status_updated.emit(f"Error: {e}")
            self.error_occurred.emit("Download Error", f"An unexpected error occurred:\n{type(e).__name__}: {e}")
        finally:
            self.cleanup()
            
    def cleanup(self):
        # Clean up resources
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.disconnect_client(), self.loop)
            self.loop.stop()
            
        self._running = False
        if not self._stop_requested:
             self.download_finished.emit(f"Finished. Downloaded {self.count} images.")
        else:
             self.download_finished.emit(f"Stopped. Downloaded {self.count} images.")
             
    async def disconnect_client(self):
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.status_updated.emit("Disconnected from Telegram.")

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
                
                # Request authentication code from the main GUI thread
                self._waiting_for_auth = True
                self.auth_code_needed.emit(self.settings['phone'])
                
                # Wait for the auth code to be set
                while self._waiting_for_auth and not self._stop_requested:
                    await asyncio.sleep(0.1)
                    
                if self._stop_requested:
                    await self.client.disconnect()
                    return
                    
                try:
                    # Try to sign in with the provided code
                    await self.client.sign_in(self.settings['phone'], self._auth_code)
                except SessionPasswordNeededError:
                    # 2FA is enabled, request password
                    self._waiting_for_auth = True
                    self.auth_password_needed.emit("Two-factor authentication is enabled")
                    
                    # Wait for password
                    while self._waiting_for_auth and not self._stop_requested:
                        await asyncio.sleep(0.1)
                        
                    if self._stop_requested:
                        await self.client.disconnect()
                        return
                        
                    # Submit password
                    await self.client.sign_in(password=self._auth_password)

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

            # Clear image data list before starting download
            self.image_data = []
            
            # Track the last non-empty caption for each message
            last_caption = "no_caption"
            current_message_id = None
            message_image_count = 0  # Counter for images in the current message
            message_group_counter = 0  # Counter for message groups (for Excel)

            # Get exclusion patterns from settings
            exclusion_patterns = self.settings.get('exclusion_patterns', [])
            if exclusion_patterns:
                self.status_updated.emit(f"Using {len(exclusion_patterns)} exclusion pattern(s)")

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

                # Check if we're on a new message
                if current_message_id != message.id:
                    current_message_id = message.id
                    message_image_count = 0  # Reset image counter for the new message
                    message_group_counter += 1  # Increment group counter for each new message
                    # Reset the caption only when we move to a new message
                    if message.message and message.message.strip():
                        last_caption = message.message.strip()
                    # else keep the previous caption if the new one is empty

                if message.media and isinstance(message.media, MessageMediaPhoto):
                    # Increment image counter for this message
                    message_image_count += 1
                    
                    # Use message text as caption, or the last known caption if empty
                    caption_raw = message.message if message.message else last_caption
                    
                    # Format date (local time might be nicer for filenames)
                    message_date_local = message.date.astimezone(local_tz)
                    date_str = message_date_local.strftime("%Y%m%d_%H%M%S")

                    # Try to extract original filename if preserve names is enabled
                    original_filename = None
                    if self.settings.get('preserve_names', False) and hasattr(message.media, 'photo') and message.media.photo:
                        # Try to get original filename from attributes
                        if hasattr(message.media.photo, 'attributes'):
                            for attr in message.media.photo.attributes:
                                if hasattr(attr, 'file_name') and attr.file_name:
                                    original_filename = attr.file_name
                                    break

                    # Create and sanitize filename, add sequence number if multiple images in message
                    if original_filename and self.settings.get('preserve_names', False):
                        # Use original filename but add date prefix for uniqueness
                        base_name, ext = os.path.splitext(original_filename)
                        if not ext:
                            ext = ".jpg"  # Default to jpg if no extension
                        filename_base = f"{date_str}_{base_name}"
                    else:
                        # Use caption-based filename
                        filename_base = f"{date_str}_{caption_raw}"
                        if message_image_count > 1:
                            filename_base = f"{filename_base}_{message_image_count}"
                        ext = ".jpg"
                    
                    # Apply exclusion patterns to the filename
                    filename_sanitized = sanitize_filename(filename_base, exclusion_patterns) + ext
                    full_path = os.path.join(self.settings['save_folder'], filename_sanitized)

                    try:
                        self.status_updated.emit(f"Downloading: {filename_sanitized}")
                        await self.client.download_media(message.media, file=full_path)
                        self.count += 1
                        self.progress_updated.emit(self.count)
                        
                        # Store image metadata for Excel export
                        if self.settings.get('export_excel', False):
                            # Prepare caption for Excel, applying exclusions
                            excel_caption = caption_raw
                            if exclusion_patterns:
                                for pattern in exclusion_patterns:
                                    if pattern.startswith("regex:"):
                                        # Handle regex pattern
                                        regex_pattern = pattern[6:]  # Remove "regex:" prefix
                                        try:
                                            excel_caption = re.sub(regex_pattern, '', excel_caption)
                                        except re.error:
                                            # If regex is invalid, just skip it
                                            pass
                                    else:
                                        # Handle normal pattern
                                        excel_caption = excel_caption.replace(pattern, '')
                        
                            # Collect metadata
                            image_info = {
                                'Date': message_date_local.strftime("%Y-%m-%d"),
                                'Time': message_date_local.strftime("%H:%M:%S"),
                                'Caption': excel_caption,
                                'Filename': filename_sanitized,
                                'Full Path': full_path,
                                'Channel': self.settings['channel'],
                                'Message ID': message.id,
                                'Image Number': message_image_count,
                                'Message Group': message_group_counter,
                                'Original Filename': original_filename if original_filename else "N/A",
                                'UTC Date': message.date.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            self.image_data.append(image_info)
                            
                    except Exception as download_err:
                        self.status_updated.emit(f"Skipped download due to error: {download_err}")
                        # Optionally log this error more formally
                        await asyncio.sleep(0.1) # Small delay after error

                await asyncio.sleep(0.05) # Small delay to prevent flooding

            # After download completes, export Excel if needed
            if self.settings.get('export_excel', False) and not self._stop_requested and self.image_data:
                await self.export_to_excel()

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

    async def export_to_excel(self):
        """Export the downloaded image metadata to Excel"""
        if not self.image_data:
            self.status_updated.emit("No image data to export.")
            return
            
        try:
            self.status_updated.emit("Exporting data to Excel...")
            
            # Create a pandas DataFrame from the image data
            df = pd.DataFrame(self.image_data)
            
            # Generate Excel filename based on channel and date
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            channel_name = self.settings['channel'].replace('@', '').replace('/', '_')
            excel_filename = f"telegram_images_{channel_name}_{timestamp}.xlsx"
            excel_path = os.path.join(self.settings['save_folder'], excel_filename)
            
            # Create Excel writer
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Image Data', index=False)
                
                # Auto-adjust column widths
                worksheet = writer.sheets['Image Data']
                for i, col in enumerate(df.columns):
                    max_length = max(df[col].astype(str).map(len).max(), len(col))
                    # Add a little extra space
                    adjusted_width = max_length + 2
                    # Excel column width is in characters, but it's approximate
                    worksheet.column_dimensions[chr(65 + i)].width = adjusted_width
            
            self.status_updated.emit(f"Excel file exported: {excel_filename}")
            self.excel_exported.emit(excel_path)
            
        except Exception as e:
            self.status_updated.emit(f"Error exporting to Excel: {e}")
            self.error_occurred.emit("Excel Export Error", f"Failed to export data to Excel:\n{str(e)}")

    def stop(self):
        self._stop_requested = True
        self._paused = False # Ensure it's not stuck in paused state if stopped
        
        # Cancel the task if it's running
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        
        # Attempt to cancel the asyncio task if the loop is running
        if self.loop and self.loop.is_running():
            # Cancel all running tasks in the loop
            for task in asyncio.all_tasks(self.loop):
                task.cancel()

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

    def set_auth_code(self, code):
        self._auth_code = code
        self._waiting_for_auth = False
        
    def set_auth_password(self, password):
        self._auth_password = password
        self._waiting_for_auth = False


# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Image Downloader")
        self.setGeometry(100, 100, 700, 550)  # Increased default size for better appearance
        self.setMinimumSize(600, 450)  # Set minimum size

        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
        self.downloader_thread = None
        self.downloader_worker = None

        self.init_ui()
        self.load_settings()
        self.update_button_states()
        self.apply_stylesheet() # Apply custom styling
        
        # Show welcome/help message if first run or missing API credentials
        self.show_welcome_message()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Set margins and spacing for better appearance
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # --- Settings Form ---
        form_layout = QFormLayout()

        load_dotenv() # Load .env file if it exists

        self.api_id_entry = QLineEdit()
        self.api_hash_entry = QLineEdit()
        self.api_hash_entry.setEchoMode(QLineEdit.EchoMode.Password) # Hide hash
        self.phone_entry = QLineEdit()
        self.channel_entry = QLineEdit()

        # Set size policies for better scaling
        for widget in [self.api_id_entry, self.api_hash_entry, self.phone_entry, self.channel_entry]:
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
        self.folder_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        folder_layout.addWidget(self.folder_button)
        folder_layout.addWidget(self.folder_label, 1) # Stretch label
        layout.addLayout(folder_layout)

        # --- Date Filter and Options ---
        options_layout = QHBoxLayout()
        date_label = QLabel("Download images from:")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate().addMonths(-1)) # Default to 1 month ago
        
        # Add Excel export option
        self.export_excel_checkbox = QCheckBox("Export data to Excel")
        self.export_excel_checkbox.setToolTip("When checked, image metadata will be exported to Excel")
        
        # Add preserve original filename option
        self.preserve_names_checkbox = QCheckBox("Preserve original filenames")
        self.preserve_names_checkbox.setToolTip("When checked, tries to use the original filename from Telegram if available")
        
        # Add exclusion patterns button
        self.exclusion_button = QPushButton("Exclusion Patterns")
        self.exclusion_button.setToolTip("Set patterns to exclude from filenames and Excel")
        self.exclusion_button.clicked.connect(self.open_exclusion_dialog)
        
        options_layout.addWidget(date_label)
        options_layout.addWidget(self.date_edit)
        options_layout.addWidget(self.export_excel_checkbox)
        options_layout.addWidget(self.preserve_names_checkbox)
        options_layout.addWidget(self.exclusion_button)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # --- Progress Bar ---
        progress_layout = QHBoxLayout()
        progress_label = QLabel("Download Progress:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v files downloaded")
        progress_layout.addWidget(progress_label)
        progress_layout.addWidget(self.progress_bar, 1)
        layout.addLayout(progress_layout)

        # --- Control Buttons ---
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Download")
        self.pause_resume_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")

        # Set button size policies
        for button in [self.start_button, self.pause_resume_button, self.stop_button]:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(40)  # Taller buttons for better touch targets

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
        
        # Initialize buttons state
        self.update_button_states()

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
                padding: 8px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                min-height: 25px;
            }
            QPushButton {
                padding: 8px 15px;
                border: 1px solid #0078d7; /* Blue border */
                border-radius: 4px;
                background-color: #0078d7; /* Blue background */
                color: white; /* White text */
                min-width: 100px;
                min-height: 30px;
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
                min-height: 20px;
            }
            QStatusBar {
                background-color: #e0e0e0; /* Slightly darker status bar */
                min-height: 25px;
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
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                min-height: 25px;
            }
            QProgressBar::chunk {
                background-color: #0078d7;
                width: 1px;
            }
            QCheckBox {
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
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
            'start_date': self.date_edit.date(),
            'export_excel': self.export_excel_checkbox.isChecked(),
            'preserve_names': self.preserve_names_checkbox.isChecked(),
            'exclusion_patterns': getattr(self, 'exclusion_patterns', [])  # Use attribute if set
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
        self.progress_bar.setValue(0)  # Reset progress bar

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
        
        # Connect authentication signals
        self.downloader_worker.auth_code_needed.connect(self.request_auth_code)
        self.downloader_worker.auth_password_needed.connect(self.request_auth_password)

        # Connect Excel exported signal
        self.downloader_worker.excel_exported.connect(self.on_excel_exported)

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
            self.status_label.setText("Stopping download...")
            self.downloader_worker.stop()
            # Update button states immediately to provide feedback
            self.stop_button.setEnabled(False)
            self.stop_button.setText("Stopping...")

    def toggle_pause_resume(self):
        if not self.downloader_worker or not self.downloader_worker.is_running():
            return
            
        is_paused = self.downloader_worker.is_paused()
        if is_paused:
            self.downloader_worker.resume()
            self.pause_resume_button.setText("Pause")
            self.status_label.setText("Resuming download...")
        else:
            self.downloader_worker.pause()
            self.pause_resume_button.setText("Resume")
            self.status_label.setText("Pausing download...")

    def update_progress(self, count):
        self.count_label.setText(f"Images saved: {count}")
        # Update progress bar but don't change the maximum (it shows raw count)
        self.progress_bar.setValue(count)
        self.progress_bar.setFormat(f"{count} files downloaded")
        
    def update_status(self, status):
        self.status_label.setText(status)

    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)
        self.status_label.setText(f"Error: {title}") # Show short error status
        # Optionally stop the process on certain errors
        # self.stop_download()

    def on_download_finished(self, final_message):
        self.update_status(final_message)
        
        # Proper cleanup of thread
        if self.downloader_thread and self.downloader_thread.isRunning():
            self.downloader_thread.quit()
            self.downloader_thread.wait(1000)  # Wait up to 1 second
            
        self.downloader_thread = None
        self.downloader_worker = None
        self.update_button_states()

    def update_button_states(self):
        is_running = self.downloader_worker is not None and self.downloader_worker.is_running()
        is_paused = is_running and self.downloader_worker.is_paused()

        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)
        self.pause_resume_button.setEnabled(is_running)
        
        # Reset stop button text if needed
        if not is_running:
            self.stop_button.setText("Stop")

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
        self.export_excel_checkbox.setEnabled(not is_running)
        self.preserve_names_checkbox.setEnabled(not is_running)

        # Disable exclusion patterns button while running
        self.exclusion_button.setEnabled(not is_running)

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
        
        # Load export Excel preference
        export_excel = self.settings.value("downloader/export_excel", False)
        # Convert to bool (QSettings may store as string)
        if isinstance(export_excel, str):
            export_excel = export_excel.lower() == 'true'
        self.export_excel_checkbox.setChecked(bool(export_excel))

        # Load preserve names preference
        preserve_names = self.settings.value("downloader/preserve_names", False)
        # Convert to bool (QSettings may store as string)
        if isinstance(preserve_names, str):
            preserve_names = preserve_names.lower() == 'true'
        self.preserve_names_checkbox.setChecked(bool(preserve_names))

        # Load exclusion patterns
        pattern_text = self.settings.value("downloader/exclusion_patterns", "")
        self.exclusion_patterns = []
        if pattern_text:
            for line in pattern_text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    self.exclusion_patterns.append(line)

    def save_settings(self):
        self.settings.setValue("telegram/api_id", self.api_id_entry.text().strip())
        self.settings.setValue("telegram/api_hash", self.api_hash_entry.text().strip()) # Hash is saved, consider security implications
        self.settings.setValue("telegram/phone", self.phone_entry.text().strip())
        self.settings.setValue("downloader/channel", self.channel_entry.text().strip())
        if hasattr(self, 'save_folder') and self.save_folder:
            self.settings.setValue("downloader/save_folder", self.save_folder)
        self.settings.setValue("downloader/start_date", self.date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("downloader/export_excel", self.export_excel_checkbox.isChecked())
        self.settings.setValue("downloader/preserve_names", self.preserve_names_checkbox.isChecked())

        # Exclusion patterns are saved directly in the open_exclusion_dialog method

    def request_auth_code(self, phone):
        """Show a dialog to request the Telegram authentication code"""
        # First show an informational message box to make sure user understands the process
        QMessageBox.information(
            self, 
            "Telegram Authentication Required",
            f"Telegram will now send a verification code to your phone number: {phone}\n\n"
            f"Please check your Telegram app for a message containing this code.\n"
            f"This code will be sent to you as a message from the official 'Telegram' service."
        )
        
        dialog = AuthCodeDialog(self)
        dialog.instruction_label.setText(f"Please enter the authentication code sent to {phone}\nvia the Telegram app:")
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            code = dialog.get_code()
            if code:
                self.status_label.setText(f"Submitting authentication code...")
                # Send code to worker thread
                self.downloader_worker.set_auth_code(code)
            else:
                self.stop_download()
                self.status_label.setText("Authentication cancelled - no code provided.")
        else:
            # User cancelled
            self.stop_download()
            self.status_label.setText("Authentication cancelled by user.")
            
    def request_auth_password(self, message):
        """Show a dialog to request the Telegram 2FA password"""
        # Show informational message first
        QMessageBox.information(
            self,
            "Two-Factor Authentication Required",
            "Your Telegram account has two-factor authentication enabled.\n\n"
            "You will need to enter your two-factor authentication password (not your Telegram password).\n"
            "This is the password you set up specifically for two-factor authentication."
        )
        
        dialog = AuthCodeDialog(self)
        dialog.setWindowTitle("Two-Factor Authentication")
        dialog.instruction_label.setText("Your account has two-factor authentication enabled.")
        dialog.code_input.hide()
        dialog.instruction_label.setStyleSheet("font-weight: bold;")
        dialog.password_label.setText("This is the 2FA password you created in your Telegram security settings:")
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            password = dialog.get_password()
            if password:
                self.status_label.setText(f"Submitting two-factor authentication...")
                # Send password to worker thread
                self.downloader_worker.set_auth_password(password)
            else:
                self.stop_download()
                self.status_label.setText("Authentication cancelled - no password provided.")
        else:
            # User cancelled
            self.stop_download()
            self.status_label.setText("Authentication cancelled by user.")

    def on_excel_exported(self, excel_path):
        """Handle when Excel file is exported"""
        reply = QMessageBox.information(
            self,
            "Excel Export Complete",
            f"Image data has been exported to Excel:\n{excel_path}\n\nDo you want to open it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Open the Excel file with the default application
            import subprocess
            try:
                os.startfile(excel_path)  # Windows specific
            except AttributeError:
                # For non-Windows platforms
                try:
                    subprocess.call(['open', excel_path])  # macOS
                except:
                    subprocess.call(['xdg-open', excel_path])  # Linux
            except Exception as e:
                QMessageBox.warning(self, "Error Opening File", f"Could not open Excel file: {str(e)}")

    def closeEvent(self, event):
        """Handle window closing."""
        if self.downloader_worker and self.downloader_worker.is_running():
            reply = QMessageBox.question(self, 'Downloader Running',
                                         "A download is in progress. Stop and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                # Stop the worker and wait for it to complete
                self.stop_download()
                
                # Wait for the thread to finish
                if self.downloader_thread:
                    # Wait for thread to finish naturally
                    if not self.downloader_thread.wait(3000):  # Wait up to 3 seconds
                        self.status_label.setText("Warning: Download thread did not stop gracefully, forcing termination.")
                        # Force thread termination if it's still running after timeout
                        if self.downloader_thread.isRunning():
                            self.downloader_thread.terminate()
                            self.downloader_thread.wait(1000)  # Give it a moment to terminate
                
                self.save_settings()
                event.accept()
            else:
                event.ignore()
        else:
            self.save_settings()
            event.accept()

    def show_welcome_message(self):
        """Show a welcome message with setup instructions if needed"""
        # Check if API credentials are missing
        if not self.api_id_entry.text() or not self.api_hash_entry.text():
            QMessageBox.information(
                self,
                "Welcome to Telegram Image Downloader",
                "To use this app, you need Telegram API credentials.\n\n"
                "How to get your API credentials:\n"
                "1. Visit https://my.telegram.org/ and log in\n"
                "2. Click on 'API development tools'\n"
                "3. Create a new application with any name and description\n"
                "4. You will receive an 'App api_id' and 'App api_hash'\n"
                "5. Enter these values in the appropriate fields in this app\n\n"
                "Your phone number should be in international format (e.g., +1234567890)\n\n"
                "The channel should be a public channel username (e.g., @channelname) or a private channel ID\n\n"
                "Your credentials will be saved for future use."
            )

    def resizeEvent(self, event):
        """Handle window resize event"""
        super().resizeEvent(event)
        # Optional: Add any special handling for resize events
        
        # We could adjust UI elements based on new size if needed
        new_width = event.size().width()
        new_height = event.size().height()
        
        # For example, we could adjust progress bar format based on width:
        if hasattr(self, 'progress_bar'):
            if new_width < 500:
                self.progress_bar.setFormat("%v")  # Simpler format for small widths
            else:
                self.progress_bar.setFormat("%v files downloaded")

    def open_exclusion_dialog(self):
        """Open the dialog to manage exclusion patterns"""
        # Get current patterns from settings
        current_patterns = self.settings.value("downloader/exclusion_patterns", "")
        
        # Create and show the dialog
        dialog = ExclusionPatternDialog(self, current_patterns)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Save the patterns
            self.exclusion_patterns = dialog.get_active_patterns()
            pattern_text = dialog.get_patterns()
            self.settings.setValue("downloader/exclusion_patterns", pattern_text)
            
            # Show confirmation
            count = len(self.exclusion_patterns)
            self.status_label.setText(f"Saved {count} exclusion pattern{'s' if count != 1 else ''}")
            

# --- Exclusion Pattern Dialog ---
class ExclusionPatternDialog(QDialog):
    def __init__(self, parent=None, exclusion_patterns=None):
        super().__init__(parent)
        self.setWindowTitle("Exclusion Patterns")
        self.setMinimumSize(600, 500)  # Increased size for preview area
        
        # Initialize with existing patterns or empty string
        self.exclusion_patterns = exclusion_patterns or ""
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instruction_label = QLabel(
            "Enter patterns (one per line) to exclude from filenames and Excel exports.\n"
            "These patterns work similar to .gitignore rules:\n"
            "- Simple text patterns will match anywhere in the caption\n"
            "- Use # for comments\n"
            "- Start a line with 'regex:' to use regular expressions (e.g., regex:\\d+)\n"
            "- Blank lines are ignored\n\n"
            "Examples:\n"
            "# Exclude swear words\n"
            "badword\n"
            "# Exclude specific phrases\n"
            "unwanted phrase\n"
            "# Exclude all numbers\n"
            "regex:\\d+\n"
            "# Exclude emojis or symbols by typing them directly"
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)
        
        # Pattern editor section
        editor_layout = QHBoxLayout()
        
        # Text editor for patterns
        pattern_editor_layout = QVBoxLayout()
        pattern_editor_layout.addWidget(QLabel("Exclusion Patterns:"))
        self.pattern_editor = QTextEdit()
        self.pattern_editor.setPlaceholderText("Enter exclusion patterns here, one per line...")
        self.pattern_editor.setText(self.exclusion_patterns)
        self.pattern_editor.textChanged.connect(self.update_preview)
        pattern_editor_layout.addWidget(self.pattern_editor)
        editor_layout.addLayout(pattern_editor_layout)
        
        # Preview section
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(QLabel("Preview:"))
        
        # Sample input for testing
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("Enter test text to see how exclusions will affect it...")
        self.test_input.setText("This is a sample text with numbers 12345 and symbols @#$%")
        self.test_input.textChanged.connect(self.update_preview)
        preview_layout.addWidget(self.test_input)
        
        # Preview output
        self.preview_output = QLineEdit()
        self.preview_output.setReadOnly(True)
        self.preview_output.setPlaceholderText("Preview will appear here")
        preview_layout.addWidget(self.preview_output)
        
        editor_layout.addLayout(preview_layout)
        layout.addLayout(editor_layout)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # Initialize preview
        self.update_preview()
    
    def get_patterns(self):
        """Return the edited patterns text"""
        return self.pattern_editor.toPlainText()

    def get_active_patterns(self):
        """Return a list of non-empty, non-comment patterns"""
        patterns = []
        for line in self.get_patterns().splitlines():
            # Skip empty lines and comments
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.append(line)
        return patterns
    
    def update_preview(self):
        """Update the preview based on current patterns and test input"""
        test_text = self.test_input.text()
        if not test_text:
            self.preview_output.setText("")
            return
            
        # Apply exclusions
        result = test_text
        for pattern in self.get_active_patterns():
            if pattern.startswith("regex:"):
                # Handle regex pattern
                regex_pattern = pattern[6:]  # Remove "regex:" prefix
                try:
                    result = re.sub(regex_pattern, '', result)
                except re.error:
                    # If regex is invalid, just skip it
                    pass
            else:
                # Handle normal pattern
                result = result.replace(pattern, '')
        
        # Show sanitized result (apply basic filename sanitization)
        sanitized = sanitize_filename(result)
        self.preview_output.setText(sanitized)

# --- Main Execution ---
if __name__ == "__main__":
    # Handles Ctrl+C in terminal and prevents thread related issues
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    # Properly handle application exit
    app.aboutToQuit.connect(lambda: print("Application exiting..."))
    
    mainWin = MainWindow()
    mainWin.show()
    sys.exit(app.exec())