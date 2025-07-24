import asyncio
import os
import sys
import re
from datetime import datetime, timezone
import pytz  # For timezone handling
import threading
import configparser # For INI file handling
import pandas as pd  # For Excel export

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QStatusBar,
    QMessageBox, QDateEdit, QFormLayout, QSizePolicy, QDialog,
    QCheckBox, QProgressBar, QTextEdit, QDialogButtonBox, QComboBox # Added QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSettings, QDate
from PyQt6.QtGui import QPalette, QColor

import database_handler # For SQLite operations
import gemini_categorizer # For AI categorization
import image_viewer # For the new image viewer window
import new_category_generator # For creating new categories
import message_counter_dialog # Import the new dialog

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
CONFIG_FILE_PATH = "telegram/config.ini" # Path to the INI file

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

def sanitize_caption_text(text):
    """
    Cleans caption text by removing emojis, normalizing whitespace,
    and removing leading/trailing whitespace.
    """
    if not text:
        return ""

    # Remove common emojis - this is a basic range, more comprehensive solutions exist
    # Basic Emoji ranges (includes some symbols, pictographs, transport, regional indicators)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027B0"  # Dingbats
        "\U000024C2-\U0001F251" 
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub('', text)

    # Normalize whitespace (multiple spaces/tabs/newlines to a single space)
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text

def extract_price_from_caption(caption_text):
    """
    Extracts a price from the caption text.
    Looks for patterns like "цена_123", "цена: 123", "цена 123".
    Returns the price as a float, or None if not found.
    """
    if not caption_text:
        return None

    # Regex to find "цена" followed by optional colon/underscore/space and then numbers
    # It will capture the number part.
    # Allows for spaces around the number and optional decimal part.
    price = None

    # Attempt 1: Look for "цена" or "цена и наличие" followed by a number
    match_cena = re.search(
        r'\b(?:цена|цена и наличие)[_:\s]*([\d\s]+[.,]?\d*)\b',
        caption_text,
        re.IGNORECASE
    )
    if match_cena:
        price_str = match_cena.group(1)
        price_str_cleaned = price_str.replace(" ", "").replace(",", ".")
        try:
            price = float(price_str_cleaned)
            return price
        except ValueError:
            pass # Continue to next attempt if conversion fails

    # Attempt 2: Look for any number followed by a currency symbol (тг, тенге, руб)
    match_currency = re.search(
        r'([\d\s]+[.,]?\d*)\s*(?:тг|тенге|руб\.?)\b',
        caption_text,
        re.IGNORECASE
    )
    if match_currency:
        price_str = match_currency.group(1)
        price_str_cleaned = price_str.replace(" ", "").replace(",", ".")
        try:
            price = float(price_str_cleaned)
            return price
        except ValueError:
            pass # Return None if conversion fails

    return None

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
        # auth_info_label.setStyleSheet("font-weight: bold; color: #D32F2F;") # Style via QSS
        auth_info_label.setObjectName("authInfoLabel") # For QSS targeting
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
    worker_started = pyqtSignal() # Signal to indicate worker's run method has started

    def __init__(self, settings):
        super().__init__()
        self.settings_dict = settings # Renamed to avoid confusion with QSettings
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
        self.categories_data = None # To store structured category data (raw_list, id_map, name_map, slug_map)

    def run(self):
        self._running = True
        self._paused = False
        self._stop_requested = False
        self.count = 0
        self.worker_started.emit() # Signal that the worker's run loop is about to start

        try:
            # Get a new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Create and store the task so it can be cancelled
            self._current_task = self.loop.create_task(self.download_images_async()) # Renamed for clarity
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
            asyncio.run_coroutine_threadsafe(self.disconnect_client_async(), self.loop) # Renamed
            self.loop.stop()
            
        self._running = False
        if not self._stop_requested:
             self.download_finished.emit(f"Finished. Downloaded {self.count} images.")
        else:
             self.download_finished.emit(f"Stopped. Downloaded {self.count} images.")
             
    async def disconnect_client_async(self): # Renamed
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.status_updated.emit("Disconnected from Telegram.")

    async def download_images_async(self): # Renamed
        self.status_updated.emit("Connecting to Telegram...")
        session_name = "telegram_session" # Use a dedicated session file name

        # AI Categorization Setup
        ai_enabled = self.settings_dict.get('ai_categorization_enabled', False)
        gemini_api_key = None
        # categories_list will now be a tuple of (raw_list, id_map, name_map, slug_map)
        self.categories_data = ([], {}, {}, {}) # Initialize as empty structured data
        can_categorize_ai = False

        if ai_enabled:
            self.status_updated.emit("AI Categorization enabled. Initializing...")
            gemini_api_key = gemini_categorizer.get_gemini_api_key()
            categories_file_path = self.settings_dict.get('categories_file_path', gemini_categorizer.DEFAULT_CATEGORIES_FILE)
            if not categories_file_path or not os.path.exists(categories_file_path):
                self.status_updated.emit(f"Categories file not found at '{categories_file_path}'. Using default or none.")
                categories_file_path = gemini_categorizer.DEFAULT_CATEGORIES_FILE # Fallback
            
            # Load structured categories data
            self.categories_data = gemini_categorizer.load_categories(categories_file_path)
            raw_categories_list = self.categories_data[0] # Get the raw list for length check

            if gemini_api_key and gemini_api_key != "YOUR_GEMINI_API_KEY" and raw_categories_list:
                can_categorize_ai = True
                self.status_updated.emit(f"AI Categorizer ready with {len(raw_categories_list)} categories.")
            else:
                self.status_updated.emit("AI Categorization cannot proceed: API key or categories missing/invalid.")
        else:
            self.status_updated.emit("AI Categorization disabled.")

        try:
            self.client = TelegramClient(session_name,
                                         int(self.settings_dict['api_id']),
                                         self.settings_dict['api_hash'],
                                         loop=self.loop) # Pass the loop

            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.status_updated.emit("Authorization needed...")
                await self.client.send_code_request(self.settings_dict['phone'])
                
                # Request authentication code from the main GUI thread
                self._waiting_for_auth = True
                self.auth_code_needed.emit(self.settings_dict['phone'])
                
                # Wait for the auth code to be set
                while self._waiting_for_auth and not self._stop_requested:
                    await asyncio.sleep(0.1)
                    
                if self._stop_requested:
                    await self.client.disconnect()
                    return
                    
                try:
                    # Try to sign in with the provided code
                    await self.client.sign_in(self.settings_dict['phone'], self._auth_code)
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
                channel = await self.client.get_entity(self.settings_dict['channel'])
            except ValueError: # Often raised for invalid usernames/IDs
                 raise ChannelInvalidError(request=None) # Raise specific error


            self.status_updated.emit(f"Starting download from {self.settings_dict['channel']}...")

            # Convert QDate to timezone-aware datetime (start of day in local timezone, then UTC)
            start_qdate = self.settings_dict.get('start_date', QDate(2000, 1, 1)) # Default very old date
            # Use QSettings for timezone as it's a system/app level setting, not per-download
            q_settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
            local_tz_name = q_settings.value("System/Timezone", "UTC")
            try:
                local_tz = pytz.timezone(local_tz_name)
            except pytz.exceptions.UnknownTimeZoneError:
                self.status_updated.emit(f"Warning: Unknown timezone '{local_tz_name}', defaulting to UTC.")
                local_tz = pytz.utc
            
            start_datetime_local = datetime.combine(start_qdate.toPyDate(), datetime.min.time(), tzinfo=local_tz)
            start_datetime_utc = start_datetime_local.astimezone(timezone.utc)

            # End Date Handling
            end_qdate = self.settings_dict.get('end_date', QDate.currentDate()) # Default to today if not found
            # To include the entire end_qdate, we filter messages strictly older than the start of the next day.
            end_qdate_next_day = end_qdate.addDays(1)
            end_datetime_local_exclusive = datetime.combine(end_qdate_next_day.toPyDate(), datetime.min.time(), tzinfo=local_tz)
            end_datetime_utc_exclusive = end_datetime_local_exclusive.astimezone(timezone.utc)
            
            self.status_updated.emit(f"Filtering images from: {start_qdate.toString(Qt.DateFormat.ISODate)} until {end_qdate.toString(Qt.DateFormat.ISODate)}")

            # Clear image data list before starting download
            self.image_data = []
            
            # Track the last non-empty caption for each message
            last_caption = "no_caption"
            message_group_counter = 0  # Counter for message groups (for Excel)

            # Get exclusion patterns from settings_dict
            exclusion_patterns = self.settings_dict.get('exclusion_patterns', [])
            if exclusion_patterns:
                self.status_updated.emit(f"Using {len(exclusion_patterns)} exclusion pattern(s)")

            # Iterate messages, starting from latest
            async for message in self.client.iter_messages(channel):
                if self._stop_requested:
                    self.status_updated.emit("Stopping...")
                    break

                while self._paused:
                    if self._stop_requested: break
                    self.status_updated.emit("Paused...")
                    await asyncio.sleep(1)

                if self._stop_requested: break

                if not message.media:
                    continue

                # Date Filtering
                if message.date >= end_datetime_utc_exclusive:
                    continue
                if message.date < start_datetime_utc:
                    self.status_updated.emit("Reached start date. Stopping iteration.")
                    break

                message_group_counter += 1
                caption_raw = message.text if message.text else last_caption
                if message.text:
                    last_caption = message.text

                # This message is a product, collect its data
                message_date_local = message.date.astimezone(local_tz)
                
                product_data = {
                    'message_id': message.id,
                    'channel': self.settings_dict['channel'],
                    'caption': caption_raw,
                    'download_date': message_date_local.strftime("%Y-%m-%d"),
                    'download_time': message_date_local.strftime("%H:%M:%S"),
                    'utc_timestamp': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    'message_group': message_group_counter,
                    'telegram_message_date': message.date.strftime("%Y-%m-%d %H:%M:%S"),
                    'major_category_id': None,
                    'sub_category_id': None,
                    'sanitized_caption': sanitize_caption_text(caption_raw),
                    'price': extract_price_from_caption(caption_raw),
                    'brand_tag': None
                }
                
                images_in_message = []
                if message.grouped_id:
                    # Handle albums (grouped messages)
                    album_messages = await self.client.get_messages(channel, ids=[message.id])
                    for m in album_messages:
                        if m.media:
                            images_in_message.append(m)
                else:
                    # Handle single image message
                    images_in_message.append(message)

                images_data_for_db = []
                first_image_path_for_ai = None
                
                for idx, img_msg in enumerate(images_in_message):
                    message_image_count = idx + 1
                    date_str = message_date_local.strftime("%Y%m%d_%H%M%S")
                    
                    original_filename = None
                    if self.settings_dict.get('preserve_names', False) and hasattr(img_msg.media, 'photo') and img_msg.media.photo:
                        if hasattr(img_msg.media.photo, 'attributes'):
                            for attr in img_msg.media.photo.attributes:
                                if hasattr(attr, 'file_name') and attr.file_name:
                                    original_filename = attr.file_name
                                    break
                    
                    file_base_name_part = ""
<<<<<<< HEAD:Telegram/telegram2.py
                    ext = ".jpg" # Default extension

                    # Determine the base name for the file
                    file_base_name_part = ""
                    ext = ".jpg" # Default extension

                    # Determine the base name for the file
                    file_base_name_part = ""
                    ext = ".jpg" # Default extension

                    # Try to extract original filename if preserve names is enabled
                    original_filename_base = None
                    if self.settings_dict.get('preserve_names', False) and hasattr(message.media, 'photo') and message.media.photo:
                        if hasattr(message.media.photo, 'attributes'):
                            for attr in message.media.photo.attributes:
                                if hasattr(attr, 'file_name') and attr.file_name:
                                    original_filename_base, ext_o = os.path.splitext(attr.file_name)
                                    if ext_o: # Use original extension if present
                                        ext = ext_o
                                    break
                    
                    # Use photo.id for primary uniqueness, and message_image_count for multiple images in one message
                    # Format: telegram_photo_[PHOTO_ID]_[IMAGE_NUMBER_IN_MESSAGE].ext
                    # If original filename is preserved, it will be: telegram_photo_[PHOTO_ID]_[IMAGE_NUMBER_IN_MESSAGE]_original_[ORIGINAL_FILENAME_BASE].ext
                    
                    photo_id = message.media.photo.id if hasattr(message.media.photo, 'id') else "unknown"
                    
                    filename_base_for_sanitization = f"telegram_photo_{photo_id}_{message_image_count}"
                    
                    if original_filename_base:
                        filename_base_for_sanitization += f"_original_{original_filename_base}"

                    # Apply filename sanitization (including exclusions)
=======
                    ext = ".jpg"
                    if original_filename and self.settings_dict.get('preserve_names', False):
                        base_o, ext_o = os.path.splitext(original_filename)
                        if ext_o: ext = ext_o
                        file_base_name_part = base_o
                        filename_base_for_sanitization = f"{date_str}_{file_base_name_part}"
                    else:
                        clean_caption_for_fname = sanitize_caption_text(caption_raw)
                        file_base_name_part = clean_caption_for_fname if clean_caption_for_fname else f"image_{img_msg.id}"
                        filename_base_for_sanitization = f"{date_str}_{file_base_name_part}"
                        if len(images_in_message) > 1:
                            filename_base_for_sanitization += f"_{message_image_count}"

>>>>>>> 93ad71df14476dfafe97e87566f6f4a8d6469e8a:Best/Telegram/telegram2.py
                    filename_sanitized = sanitize_filename(filename_base_for_sanitization, exclusion_patterns) + ext
                    full_path = os.path.join(self.settings_dict['save_folder'], filename_sanitized)

                    # Check if file already exists before downloading
                    if os.path.exists(full_path):
                        self.status_updated.emit(f"Skipped: File already exists at {filename_sanitized}")
                        # Prepare data for SQLite even if not downloaded (for existing files)
                        excel_caption = caption_raw # Start with raw caption for metadata
                        if exclusion_patterns:
                            for pattern in exclusion_patterns:
                                if pattern.startswith("regex:"):
                                    regex_pattern = pattern[6:]
                                    try:
                                        excel_caption = re.sub(regex_pattern, '', excel_caption)
                                    except re.error:
                                        pass
                                else:
                                    excel_caption = excel_caption.replace(pattern, '')

                        image_info = {
                            'Date': message_date_local.strftime("%Y-%m-%d"),
                            'Time': message_date_local.strftime("%H:%M:%S"),
                            'Caption': excel_caption,
                            'Filename': filename_sanitized,
                            'Full Path': full_path,
                            'Channel': self.settings_dict['channel'],
                            'Message ID': message.id,
                            'Image Number': message_image_count,
                            'Message Group': message_group_counter,
                            'Original Filename': original_filename_base if original_filename_base else "N/A",
                            'UTC Date': message.date.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        
                        db_metadata = {
                            'message_id': image_info['Message ID'],
                            'channel': image_info['Channel'],
                            'image_number_in_message': image_info['Image Number'],
                            'caption': image_info['Caption'],
                            'filename': image_info['Filename'],
                            'full_path': image_info['Full Path'],
                            'download_date': image_info['Date'],
                            'download_time': image_info['Time'],
                            'original_filename': image_info['Original Filename'],
                            'utc_timestamp': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                            'message_group': image_info['Message Group'],
                            'telegram_message_date': image_info['UTC Date'],
                            'major_category_id': None,
                            'sub_category_id': None,
                            'sanitized_caption': sanitize_caption_text(caption_raw),
                            'price': extract_price_from_caption(caption_raw),
                            'brand_tag': None
                        }

                        # If AI categorization is enabled, still try to categorize existing files
                        if can_categorize_ai:
                            caption_for_ai = db_metadata['sanitized_caption']
                            if caption_for_ai and caption_for_ai.lower() != "no_caption":
                                self.status_updated.emit(f"Categorizing existing file with AI: {filename_sanitized}...")
                                ai_mode = self.settings_dict.get('ai_mode', 'image_and_text')
                                image_path_for_ai = full_path if ai_mode == 'image_and_text' else None

                                major_id, sub_id, brand_tag = gemini_categorizer.get_category_from_gemini(
                                    image_path_for_ai,
                                    caption_for_ai,
                                    self.categories_data,
                                    gemini_api_key
                                )
                                db_metadata['major_category_id'] = major_id
                                db_metadata['sub_category_id'] = sub_id
                                db_metadata['brand_tag'] = brand_tag

                                if major_id:
                                    major_name = self.categories_data[1].get(major_id, {}).get('name', 'N/A')
                                    sub_name = self.categories_data[1].get(sub_id, {}).get('name', 'N/A') if sub_id else ''
                                    display_cat = f"{major_name} > {sub_name}" if sub_name else major_name
                                    self.status_updated.emit(f"AI Category for {filename_sanitized}: {display_cat}")
                                else:
                                    self.status_updated.emit(f"AI Category for {filename_sanitized}: не определена")
                                
                                if brand_tag:
                                    self.status_updated.emit(f"Brand Tag for {filename_sanitized}: {brand_tag}")
                                else:
                                    self.status_updated.emit(f"Brand Tag for {filename_sanitized}: не определен")
                            else:
                                self.status_updated.emit(f"AI Category for {filename_sanitized}: нет описания для AI")
                                self.status_updated.emit(f"Brand Tag for {filename_sanitized}: нет описания для AI")

                        current_db_path = self.settings_dict.get('db_path')
                        if current_db_path:
                            database_handler.insert_image_metadata(db_metadata, current_db_path)
                        else:
                            self.status_updated.emit("Error: Database path not configured in worker. Skipping DB insert for existing file.")
                        
                        continue # Skip to next message as file already exists and metadata handled

                    try:
                        self.status_updated.emit(f"Downloading: {filename_sanitized}")
                        await self.client.download_media(img_msg.media, file=full_path)
                        self.count += 1
                        self.progress_updated.emit(self.count)
                        
<<<<<<< HEAD:Telegram/telegram2.py
                        # Store image metadata for Excel export
                        if self.settings_dict.get('export_excel', False):
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
                                'Channel': self.settings_dict['channel'],
                                'Message ID': message.id,
                                'Image Number': message_image_count,
                                'Message Group': message_group_counter,
                                'Original Filename': original_filename_base if original_filename_base else "N/A",
                                'UTC Date': message.date.strftime("%Y-%m-%d %H:%M:%S"), # Original message UTC date
                            }
                            self.image_data.append(image_info) # For Excel
=======
                        if idx == 0: # Get path of first image for AI
                            first_image_path_for_ai = full_path
>>>>>>> 93ad71df14476dfafe97e87566f6f4a8d6469e8a:Best/Telegram/telegram2.py

                        image_db_data = {
                            'image_number_in_message': message_image_count,
                            'filename': filename_sanitized,
                            'full_path': full_path,
                            'original_filename': original_filename
                        }
                        images_data_for_db.append(image_db_data)

                    except Exception as download_err:
                        self.status_updated.emit(f"Skipped download for {filename_sanitized} due to error: {download_err}")
                        await asyncio.sleep(0.1)

                # After downloading all images for the product, do AI categorization
                if can_categorize_ai and images_data_for_db:
                    caption_for_ai = product_data['sanitized_caption']
                    if caption_for_ai and caption_for_ai.lower() != "no_caption":
                        self.status_updated.emit(f"Categorizing product (msg id: {message.id})...")
                        ai_mode = self.settings_dict.get('ai_mode', 'image_and_text')
                        image_path_for_ai = first_image_path_for_ai if ai_mode == 'image_and_text' else None

                        major_id, sub_id, brand_tag = gemini_categorizer.get_category_from_gemini(
                            image_path_for_ai, caption_for_ai, self.categories_data, gemini_api_key
                        )
                        product_data['major_category_id'] = major_id
                        product_data['sub_category_id'] = sub_id
                        product_data['brand_tag'] = brand_tag
                        
                        # Status update for category
                        if major_id:
                            major_name = self.categories_data[1].get(major_id, {}).get('name', 'N/A')
                            sub_name = self.categories_data[1].get(sub_id, {}).get('name', 'N/A') if sub_id else ''
                            display_cat = f"{major_name} > {sub_name}" if sub_name else major_name
                            self.status_updated.emit(f"AI Category: {display_cat}")
                        else:
                            self.status_updated.emit("AI Category: не определена")
                        # Status update for brand
                        self.status_updated.emit(f"Brand Tag: {brand_tag if brand_tag else 'не определен'}")
                    else:
                        self.status_updated.emit("AI Category: нет описания для AI")

                # Insert product and its images into DB
                current_db_path = self.settings_dict.get('db_path')
                if current_db_path and images_data_for_db:
                    database_handler.insert_product_with_images(product_data, images_data_for_db, current_db_path)
                elif not current_db_path:
                    self.status_updated.emit("Error: DB path not configured. Skipping DB insert.")

                await asyncio.sleep(0.05)

            # After download completes, export Excel if needed
            if self.settings_dict.get('export_excel', False) and not self._stop_requested and self.image_data:
                await self.export_to_excel_async() # Renamed

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
            self.error_occurred.emit("Telegram Error", f"Cannot find channel '{self.settings_dict['channel']}'. Check username/ID.")
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

    async def export_to_excel_async(self): # Renamed
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
            channel_name = self.settings_dict['channel'].replace('@', '').replace('/', '_')
            excel_filename = f"telegram_images_{channel_name}_{timestamp}.xlsx"
            excel_path = os.path.join(self.settings_dict['save_folder'], excel_filename)
            
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
        self.setMinimumSize(600, 480)  # Increased minimum height for new DB elements

        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
        self.downloader_thread = None
        self.downloader_worker = None
        self.current_db_path = None # To store the currently selected/created DB path

        self.init_ui()
        self.load_settings() # Loads from QSettings and config.ini
        
        # Initialize database (this will now use the loaded or default DB path)
        if self.current_db_path:
            try:
                database_handler.initialize_database(self.current_db_path)
                self.status_label.setText(f"Database initialized: {os.path.basename(self.current_db_path)}")
            except Exception as e:
                self.show_error("Database Error", f"Could not initialize database '{self.current_db_path}': {e}")
        else:
            self.status_label.setText("No database selected. Please choose or create one.")
            
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

        self.api_id_entry = QLineEdit()
        self.api_hash_entry = QLineEdit()
        self.api_hash_entry.setEchoMode(QLineEdit.EchoMode.Password) # Hide hash
        self.phone_entry = QLineEdit()
        self.channel_entry = QLineEdit()

        # Set size policies for better scaling
        for widget in [self.api_id_entry, self.api_hash_entry, self.phone_entry, self.channel_entry]:
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.api_id_entry.setPlaceholderText("API ID (loaded from config.ini)")
        self.api_hash_entry.setPlaceholderText("API Hash (loaded from config.ini)")
        self.phone_entry.setPlaceholderText("Phone +CountryCode (loaded from config.ini)")
        self.channel_entry.setPlaceholderText("Channel Username/ID (loaded from config.ini)")
        
        # These fields will be populated by load_settings from config.ini
        # They are editable so user can change them and save back to config.ini

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

        # --- Database Selection ---
        db_layout = QHBoxLayout()
        self.db_button = QPushButton("Choose/Create Database (.sqlite)")
        self.db_button.clicked.connect(self.select_database_file)
        self.db_label = QLabel("No database selected.")
        self.db_label.setWordWrap(True)
        self.db_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        db_layout.addWidget(self.db_button)
        db_layout.addWidget(self.db_label, 1)
        layout.addLayout(db_layout)

        # --- Date Filter and Options ---
        options_layout = QHBoxLayout()
        
        date_label_start = QLabel("Download from:")
        self.date_edit_start = QDateEdit()
        self.date_edit_start.setCalendarPopup(True)
        self.date_edit_start.setDisplayFormat("yyyy-MM-dd")
        self.date_edit_start.setDate(QDate.currentDate().addMonths(-1)) # Default to 1 month ago
        
        date_label_end = QLabel("Download until:")
        self.date_edit_end = QDateEdit()
        self.date_edit_end.setCalendarPopup(True)
        self.date_edit_end.setDisplayFormat("yyyy-MM-dd")
        self.date_edit_end.setDate(QDate.currentDate()) # Default to today
        
        options_layout.addWidget(date_label_start)
        options_layout.addWidget(self.date_edit_start)
        options_layout.addSpacing(10)
        options_layout.addWidget(date_label_end)
        options_layout.addWidget(self.date_edit_end)
        options_layout.addSpacing(20)

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
        
        # options_layout.addWidget(date_label) # Combined above
        # options_layout.addWidget(self.date_edit) # Combined above
        options_layout.addWidget(self.export_excel_checkbox)
        options_layout.addWidget(self.preserve_names_checkbox)
        options_layout.addWidget(self.exclusion_button)
        options_layout.addStretch() # Add stretch after all main date/file options
        layout.addLayout(options_layout)

        # --- AI Categorization Options ---
        ai_options_layout = QHBoxLayout()
        self.ai_categorization_checkbox = QCheckBox("Enable AI Product Categorization")
        self.ai_categorization_checkbox.setToolTip("Uses Gemini AI to categorize product images based on caption and categories file.")
        ai_options_layout.addWidget(self.ai_categorization_checkbox)
        
        # New AI Mode selection
        self.ai_mode_combo = QComboBox()
        self.ai_mode_combo.addItem("Image and Text (Default)", "image_and_text")
        self.ai_mode_combo.addItem("Text Only", "text_only")
        self.ai_mode_combo.setToolTip("Select how Gemini AI should categorize: using both image and text, or text only.")
        ai_options_layout.addWidget(QLabel("AI Mode:"))
        ai_options_layout.addWidget(self.ai_mode_combo)

        self.auto_create_category_checkbox = QCheckBox("Auto-create new categories")
        self.auto_create_category_checkbox.setToolTip("If AI can't find a match, it will try to create a new category and add it to your file.")
        ai_options_layout.addWidget(self.auto_create_category_checkbox)
        
        self.categories_file_button = QPushButton("Select Categories File (.txt)")
        self.categories_file_button.clicked.connect(self.select_categories_file)
        ai_options_layout.addWidget(self.categories_file_button)
        
        ai_options_layout.addStretch()
        layout.addLayout(ai_options_layout)

        self.categories_file_label = QLabel("Categories file: Not selected")
        self.categories_file_label.setWordWrap(True)
        layout.addWidget(self.categories_file_label)


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
        self.viewer_button = QPushButton("Viewer Mode") # New Viewer Button
        self.viewer_button.setStyleSheet("background-color: #28a745; border-color: #28a745;") # Green color
        self.message_count_button = QPushButton("Count Messages") # New button for message count
        self.message_count_button.setStyleSheet("background-color: #007bff; border-color: #007bff;") # Blue color

        # Set button size policies
        for button in [self.start_button, self.pause_resume_button, self.stop_button, self.viewer_button, self.message_count_button]:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(40)  # Taller buttons for better touch targets

        self.start_button.clicked.connect(self.start_download)
        self.pause_resume_button.clicked.connect(self.toggle_pause_resume)
        self.stop_button.clicked.connect(self.stop_download)
        self.viewer_button.clicked.connect(self.open_image_viewer) # Connect new button
        self.message_count_button.clicked.connect(self.open_message_counter) # Connect new button

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.pause_resume_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.viewer_button) # Add new button to layout
        button_layout.addWidget(self.message_count_button) # Add new button to layout
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
        qss_file = "telegram/dark_theme.qss"
        try:
            with open(qss_file, "r") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            print(f"Stylesheet {qss_file} not found. Using default styles.")
            # Fallback or default styling if QSS is missing
            # For simplicity, we'll let it use Qt's default if file is missing.
            pass
        except Exception as e:
            print(f"Error loading stylesheet: {e}")
            # Optionally, show this in status_label if it's initialized
            # self.status_label.setText(f"Error loading stylesheet: {e}")


    def get_current_settings(self):
        """Reads settings from UI fields and QSettings."""
        # self.settings is the QSettings object
        return {
            'api_id': self.api_id_entry.text().strip(),
            'api_hash': self.api_hash_entry.text().strip(),
            'phone': self.phone_entry.text().strip(),
            'channel': self.channel_entry.text().strip(),
            'save_folder': self.settings.value("downloader/save_folder", ""),
            'db_path': self.current_db_path, # Add db_path to settings
            'start_date': self.date_edit_start.date(),
            'end_date': self.date_edit_end.date(),
            'export_excel': self.export_excel_checkbox.isChecked(),
            'preserve_names': self.preserve_names_checkbox.isChecked(),
            'exclusion_patterns': self.settings.value("downloader/exclusion_patterns_list", [], type=list),
            'ai_categorization_enabled': self.ai_categorization_checkbox.isChecked(),
            'ai_mode': self.ai_mode_combo.currentData(), # Get selected AI mode
            'categories_file_path': self.settings.value("downloader/categories_file_path", ""),
            'auto_create_category_enabled': self.auto_create_category_checkbox.isChecked()
        }

    def validate_settings(self, settings_to_validate):
        """Basic validation of required fields."""
        # Fields from config.ini (via UI)
        required_config_ui = ['api_id', 'api_hash', 'phone', 'channel']
        missing_config_ui = []
        for field in required_config_ui:
            value = settings_to_validate.get(field)
            if not value or value.startswith("YOUR_") or value == "":
                missing_config_ui.append(field)
        
        if missing_config_ui:
            self.show_error("Missing Configuration", 
                            f"Please ensure the following are set correctly in the UI (and saved to '{CONFIG_FILE_PATH}'): "
                            f"{', '.join(missing_config_ui)}")
            return False
        
        # Field from QSettings (GUI selection)
        if not settings_to_validate.get('save_folder'):
            self.show_error("Missing Information", "Please select a save folder.")
            return False

        if not settings_to_validate.get('db_path'):
            self.show_error("Missing Information", "Please select or create a database file.")
            return False
            
        # Basic check for numeric API ID
        if not settings_to_validate['api_id'].isdigit():
            self.show_error("Invalid Input", "API ID must be a number.")
            return False
        return True

    def start_download(self):
        # Save current UI values to config.ini and QSettings before starting
        self.save_settings() 
        
        current_ui_settings = self.get_current_settings()
        if not self.validate_settings(current_ui_settings):
            return

        self.status_label.setText("Starting...")
        self.count_label.setText("Images saved: 0")
        self.progress_bar.setValue(0)  # Reset progress bar

        # Create worker and thread
        self.downloader_worker = DownloaderWorker(current_ui_settings) # Pass combined settings
        self.downloader_thread = QThread()

        # Move worker to the thread
        self.downloader_worker.moveToThread(self.downloader_thread)

        # Connect signals
        self.downloader_thread.started.connect(self.downloader_worker.run) # This starts the worker's run method
        self.downloader_worker.worker_started.connect(self.update_button_states) # Update buttons once worker confirms it's running
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
        if self.downloader_worker and self.downloader_worker.is_running():
            self.status_label.setText("Stopping download...")
            self.downloader_worker.stop()
        # Update button states to reflect that a stop was requested or worker might be gone.
        # The worker finishing will also call update_button_states via on_download_finished.
        self.update_button_states()


    def toggle_pause_resume(self):
        if not self.downloader_worker or not self.downloader_worker.is_running():
            self.update_button_states() # Ensure UI is consistent if worker is gone
            return
            
        is_paused = self.downloader_worker.is_paused()
        if is_paused:
            self.downloader_worker.resume()
            self.status_label.setText("Resuming download...")
        else:
            self.downloader_worker.pause()
            self.status_label.setText("Pausing download...")
        self.update_button_states() # Update UI to reflect new pause/resume state

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
        self.date_edit_start.setEnabled(not is_running)
        self.date_edit_end.setEnabled(not is_running)
        self.export_excel_checkbox.setEnabled(not is_running)
        self.preserve_names_checkbox.setEnabled(not is_running)

        # Disable exclusion patterns button while running
        self.exclusion_button.setEnabled(not is_running)
        
        # Disable AI Categorization options while running
        self.ai_categorization_checkbox.setEnabled(not is_running)
        self.ai_mode_combo.setEnabled(not is_running) # Disable AI mode selection while running
        self.auto_create_category_checkbox.setEnabled(not is_running)
        self.categories_file_button.setEnabled(not is_running)

        # Disable Database selection while running
        self.db_button.setEnabled(not is_running)
        
        # Viewer button should always be enabled.
        self.viewer_button.setEnabled(True)


    def select_folder(self):
        # Use QSettings to remember the last used directory for the dialog
        last_folder = self.settings.value("downloader/last_folder_dialog_path", os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder", last_folder)
        if folder:
            self.folder_label.setText(f"Save to: {folder}")
            self.settings.setValue("downloader/save_folder", folder) # Save immediately to QSettings
            self.settings.setValue("downloader/last_folder_dialog_path", folder) # Remember for next time

    def load_settings(self):
        # --- Load from config.ini ---
        config = configparser.ConfigParser()
        # Create config file with defaults if it doesn't exist
        if not os.path.exists(CONFIG_FILE_PATH):
            self._create_default_config(config) # This also writes the file
        else:
            try:
                config.read(CONFIG_FILE_PATH)
            except configparser.Error as e:
                self.show_error("Config Read Error", f"Error reading {CONFIG_FILE_PATH}: {e}\nUsing default placeholders.")
                self._create_default_config(config) # Recreate with defaults if corrupt

        # Helper to get from config or return default
        def get_config_value(section, key, default=""):
            if config.has_option(section, key):
                return config.get(section, key)
            return default

        self.api_id_entry.setText(get_config_value("Telegram", "api_id", "YOUR_API_ID"))
        self.api_hash_entry.setText(get_config_value("Telegram", "api_hash", "YOUR_API_HASH"))
        self.phone_entry.setText(get_config_value("Telegram", "phone", "YOUR_PHONE_NUMBER"))
        self.channel_entry.setText(get_config_value("Downloader", "channel", "YOUR_CHANNEL_USERNAME_OR_ID"))

        # --- Load from QSettings (GUI specific settings) ---
        # QSettings object is self.settings
        folder = self.settings.value("downloader/save_folder", "")
        if folder and os.path.isdir(folder):
             self.folder_label.setText(f"Save to: {folder}")
        else:
             self.folder_label.setText("No folder selected.")
             if folder: # If it was set but invalid, clear it
                self.settings.remove("downloader/save_folder")
        
        # Load Database Path
        db_path_setting = self.settings.value("downloader/db_path", "")
        default_db_filename = "telegram_images.sqlite"
        # If no path is set, or if the set path doesn't exist, try to default to one in the app's dir or save folder
        if not db_path_setting or not os.path.exists(db_path_setting):
            # Try to find/create a default in the application's directory
            app_dir_default_db = os.path.join(os.path.dirname(__file__), default_db_filename)
            if os.path.exists(app_dir_default_db):
                self.current_db_path = app_dir_default_db
            elif folder and os.path.isdir(folder): # If save folder is set, propose default there
                self.current_db_path = os.path.join(folder, default_db_filename)
            else: # Fallback to app directory even if it doesn't exist yet (will be created)
                self.current_db_path = app_dir_default_db
            
            # If we decided on a path that doesn't exist, it will be created on first init
            # We update the setting if we picked a default
            if self.current_db_path and self.current_db_path != db_path_setting:
                 self.settings.setValue("downloader/db_path", self.current_db_path)
        else:
            self.current_db_path = db_path_setting

        if self.current_db_path:
            self.db_label.setText(f"DB: {self.current_db_path}")
            # Attempt to initialize it here if it's set
            try:
                database_handler.initialize_database(self.current_db_path)
                # self.status_label.setText(f"Using DB: {os.path.basename(self.current_db_path)}") # Status updated later
            except Exception as e:
                self.show_error("DB Init Error", f"Could not initialize DB '{self.current_db_path}': {e}")
                self.current_db_path = None # Invalidate if error
                self.db_label.setText("Error with DB. Select/Create new.")
        else:
            self.db_label.setText("No database selected.")


        date_str_start = self.settings.value("downloader/start_date", "")
        if date_str_start:
            saved_date_start = QDate.fromString(date_str_start, Qt.DateFormat.ISODate)
            if saved_date_start.isValid():
                self.date_edit_start.setDate(saved_date_start)
        # Else keep the default (1 month ago from init_ui)

        date_str_end = self.settings.value("downloader/end_date", "")
        if date_str_end:
            saved_date_end = QDate.fromString(date_str_end, Qt.DateFormat.ISODate)
            if saved_date_end.isValid():
                self.date_edit_end.setDate(saved_date_end)
        else: # Default to current date if not set
            self.date_edit_end.setDate(QDate.currentDate())

        export_excel = self.settings.value("downloader/export_excel", False, type=bool)
        self.export_excel_checkbox.setChecked(export_excel)

        preserve_names = self.settings.value("downloader/preserve_names", False, type=bool)
        self.preserve_names_checkbox.setChecked(preserve_names)

        # Load exclusion patterns (stored as a list of strings in QSettings)
        # self.exclusion_patterns_list is used by get_current_settings and open_exclusion_dialog
        # No need to explicitly set an attribute here, open_exclusion_dialog will load from QSettings
        # and get_current_settings will read from QSettings.

        # Load AI Categorization settings
        ai_enabled = self.settings.value("downloader/ai_categorization_enabled", False, type=bool)
        self.ai_categorization_checkbox.setChecked(ai_enabled)
        
        # Load AI mode selection
        ai_mode = self.settings.value("downloader/ai_mode", "image_and_text", type=str)
        index = self.ai_mode_combo.findData(ai_mode)
        if index != -1:
            self.ai_mode_combo.setCurrentIndex(index)

        auto_create_enabled = self.settings.value("downloader/auto_create_category_enabled", False, type=bool)
        self.auto_create_category_checkbox.setChecked(auto_create_enabled)
        
        categories_path = self.settings.value("downloader/categories_file_path", "")
        if categories_path and os.path.exists(categories_path):
            self.categories_file_label.setText(f"Categories file: {categories_path}")
        else:
            self.categories_file_label.setText("Categories file: Not selected (will use default if AI enabled)")
            if categories_path: # Clear invalid stored path
                 self.settings.remove("downloader/categories_file_path")


    def _create_default_config(self, config_parser_instance):
        """Creates a default config.ini file if it doesn't exist or is needed."""
        self.status_label.setText(f"Creating/Resetting default config: {CONFIG_FILE_PATH}")
        config_parser_instance.remove_section('Telegram') # Clear existing if any
        config_parser_instance.remove_section('Downloader') # Clear existing if any
        config_parser_instance['Telegram'] = {
            'api_id': 'YOUR_API_ID',
            'api_hash': 'YOUR_API_HASH',
            'phone': 'YOUR_PHONE_NUMBER'
        }
        config_parser_instance['Downloader'] = {
            'channel': 'YOUR_CHANNEL_USERNAME_OR_ID'
            # Other downloader settings are in QSettings
        }
        if not config_parser_instance.has_section('Gemini'):
            config_parser_instance.add_section('Gemini')
        config_parser_instance.set('Gemini', 'api_key', 'YOUR_GEMINI_API_KEY')
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
            with open(CONFIG_FILE_PATH, 'w') as configfile:
                config_parser_instance.write(configfile)
            # No pop-up here, message shown if called during initial load_settings
        except IOError as e:
            self.show_error("Config Error", f"Could not create/write config file {CONFIG_FILE_PATH}: {e}")


    def save_settings(self):
        # --- Save to config.ini ---
        config = configparser.ConfigParser()
        # Read existing config to preserve other settings or comments if any
        # This is important if users manually add other sections/keys
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                config.read(CONFIG_FILE_PATH)
            except configparser.Error as e:
                 self.show_error("Config Read Error", f"Could not read {CONFIG_FILE_PATH} before saving, some settings might be lost: {e}")
                 # Proceed to create new sections if they don't exist
        
        if not config.has_section('Telegram'):
            config.add_section('Telegram')
        config.set('Telegram', 'api_id', self.api_id_entry.text().strip())
        config.set('Telegram', 'api_hash', self.api_hash_entry.text().strip())
        config.set('Telegram', 'phone', self.phone_entry.text().strip())

        if not config.has_section('Downloader'):
            config.add_section('Downloader')
        config.set('Downloader', 'channel', self.channel_entry.text().strip())
        
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
            with open(CONFIG_FILE_PATH, 'w') as configfile:
                config.write(configfile)
        except IOError as e:
            self.show_error("Config Save Error", f"Could not save to config file {CONFIG_FILE_PATH}: {e}")

        # --- Save to QSettings (GUI specific settings) ---
        # save_folder is saved directly in select_folder
        # db_path is saved in select_database_file
        if self.current_db_path: # Ensure we save the current_db_path if it's valid
            self.settings.setValue("downloader/db_path", self.current_db_path)
        else: # If somehow it became None, remove the setting
            self.settings.remove("downloader/db_path")
            
        self.settings.setValue("downloader/start_date", self.date_edit_start.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("downloader/end_date", self.date_edit_end.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("downloader/export_excel", self.export_excel_checkbox.isChecked())
        self.settings.setValue("downloader/preserve_names", self.preserve_names_checkbox.isChecked())
        # exclusion_patterns_list is saved in open_exclusion_dialog
        self.settings.setValue("downloader/ai_categorization_enabled", self.ai_categorization_checkbox.isChecked())
        self.settings.setValue("downloader/ai_mode", self.ai_mode_combo.currentData()) # Save selected AI mode
        self.settings.setValue("downloader/auto_create_category_enabled", self.auto_create_category_checkbox.isChecked())
        # categories_file_path is saved in select_categories_file()

    def select_categories_file(self):
        """Opens a dialog to select the categories .txt file."""
        # Use QSettings to remember the last used directory for the dialog
        last_cat_folder = self.settings.value("downloader/last_categories_file_dialog_path", os.path.expanduser("~"))
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Categories File", 
            last_cat_folder,
            "JSON files (*.json);;All files (*)"
        )
        if file_path:
            self.categories_file_label.setText(f"Categories file: {file_path}")
            self.settings.setValue("downloader/categories_file_path", file_path)
            self.settings.setValue("downloader/last_categories_file_dialog_path", os.path.dirname(file_path))


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
        # Check if API credentials in UI (loaded from config.ini) are placeholders
        api_id_is_placeholder = not self.api_id_entry.text() or self.api_id_entry.text().startswith("YOUR_")
        api_hash_is_placeholder = not self.api_hash_entry.text() or self.api_hash_entry.text().startswith("YOUR_")

        if api_id_is_placeholder or api_hash_is_placeholder:
            if not os.path.exists(CONFIG_FILE_PATH):
                 # This message is more for the very first run if config doesn't exist yet
                 QMessageBox.information(
                    self,
                    "Configuration File Created",
                    f"A new configuration file '{CONFIG_FILE_PATH}' has been created.\n\n"
                    "Please edit it with your Telegram API ID, API Hash, Phone Number, and target Channel.\n\n"
                    "You can also enter these details directly in the app's input fields and they will be saved to the config file."
                )
            else:
                # Config exists, but has placeholder values
                QMessageBox.information(
                    self,
                    "Welcome to Telegram Image Downloader",
                    f"To use this app, you need to configure your Telegram API credentials in '{CONFIG_FILE_PATH}' "
                    "or enter them in the fields below (they will be saved to the config file).\n\n"
                    "How to get your API credentials:\n"
                    "1. Visit https://my.telegram.org/ and log in\n"
                    "2. Click on 'API development tools'\n"
                    "3. Create a new application (any name/description)\n"
                    "4. You will receive an 'App api_id' and 'App api_hash'\n"
                    "5. Enter these into '{CONFIG_FILE_PATH}' or the app fields.\n\n"
                    "Your phone number should be in international format (e.g., +1234567890).\n"
                    "The channel should be a public channel username (e.g., @channelname) or a private channel ID.\n\n"
                    "Remember to set your Gemini API Key in config.ini if you wish to use AI categorization."
                )

    def open_image_viewer(self):
        """Opens the image viewer dialog."""
        # Check if a viewer window is already open, if desired, to prevent multiple instances
        # For simplicity, we'll allow multiple for now, or let the dialog be modal.
        # If it's a QDialog, .exec() makes it modal. .show() makes it modeless.
        if not self.current_db_path:
            self.show_error("Viewer Error", "No database selected. Please choose or create a database first.")
            return
            
        try:
            # Check if database exists and is not empty
            if not os.path.exists(self.current_db_path) or os.path.getsize(self.current_db_path) == 0:
                 QMessageBox.information(self, "Viewer Mode", 
                                         f"Database '{os.path.basename(self.current_db_path)}' is empty or not found. "
                                         "Please download images first or select a valid database.")
                 return

            # Pass the current_db_path to the ProductViewerWindow constructor
            self.viewer_window = image_viewer.ProductViewerWindow(self.current_db_path, self) # Pass db_path and parent
            self.viewer_window.show() # Use show() for a modeless dialog
        except Exception as e:
            self.show_error("Viewer Error", f"Could not open image viewer: {e}")
            print(f"Error opening image viewer: {e}")

    def open_message_counter(self):
        """Opens the message counter dialog."""
        if not self.current_db_path:
            self.show_error("Message Counter Error", "No database selected. Please choose or create a database first.")
            return
            
        try:
            # Check if database exists and is not empty
            if not os.path.exists(self.current_db_path) or os.path.getsize(self.current_db_path) == 0:
                 QMessageBox.information(self, "Message Counter", 
                                         f"Database '{os.path.basename(self.current_db_path)}' is empty or not found. "
                                         "Please download images first or select a valid database.")
                 return

            self.message_counter_dialog = message_counter_dialog.MessageCounterDialog(self.current_db_path, self)
            self.message_counter_dialog.exec() # Use exec() for a modal dialog
        except Exception as e:
            self.show_error("Message Counter Error", f"Could not open message counter: {e}")
            print(f"Error opening message counter: {e}")


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

    def select_database_file(self):
        """Opens a dialog to select or create a SQLite database file."""
        last_db_folder = self.settings.value("downloader/last_db_dialog_path", os.path.expanduser("~"))
        
        # QFileDialog.getSaveFileName can be used for both selecting existing and specifying a new file
        db_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select or Create Database File",
            last_db_folder,
            "SQLite Database Files (*.sqlite *.db *.sqlite3);;All Files (*)"
        )
        
        if db_path:
            # Ensure the file has a .sqlite extension if user didn't provide one
            if not db_path.lower().endswith((".sqlite", ".db", ".sqlite3")):
                db_path += ".sqlite"

            self.current_db_path = db_path
            self.db_label.setText(f"DB: {self.current_db_path}")
            self.settings.setValue("downloader/db_path", self.current_db_path)
            self.settings.setValue("downloader/last_db_dialog_path", os.path.dirname(self.current_db_path))
            
            # Initialize the database (creates tables if new, or just connects if existing)
            try:
                database_handler.initialize_database(self.current_db_path)
                self.status_label.setText(f"Using database: {os.path.basename(self.current_db_path)}")
            except Exception as e:
                self.show_error("Database Error", f"Could not initialize or use database '{self.current_db_path}': {e}")
                self.current_db_path = None # Invalidate on error
                self.db_label.setText("Error with DB. Select/Create new.")
                self.status_label.setText("Database error. Please select a valid database.")


    def open_exclusion_dialog(self):
        """Open the dialog to manage exclusion patterns"""
        # Load patterns from QSettings (stored as a list of strings)
        current_patterns_list = self.settings.value("downloader/exclusion_patterns_list", [], type=list)
        current_patterns_text = "\n".join(current_patterns_list) # Convert list to text for editor
        
        # Create and show the dialog
        dialog = ExclusionPatternDialog(self, current_patterns_text)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get active patterns as a list from the dialog
            active_patterns_list = dialog.get_active_patterns() 
            # Save the list of active patterns to QSettings
            self.settings.setValue("downloader/exclusion_patterns_list", active_patterns_list)
            
            # Show confirmation
            count = len(active_patterns_list)
            self.status_label.setText(f"Saved {count} exclusion pattern{'s' if count != 1 else ''}")
            

# --- Exclusion Pattern Dialog ---
class ExclusionPatternDialog(QDialog):
    def __init__(self, parent=None, exclusion_patterns_text=None): # Takes text
        super().__init__(parent)
        self.setWindowTitle("Exclusion Patterns")
        self.setMinimumSize(600, 500)  # Increased size for preview area
        
        # Initialize with existing patterns text or empty string
        self.exclusion_patterns_text = exclusion_patterns_text or ""
        
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
        self.pattern_editor.setText(self.exclusion_patterns_text) # Use text here
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
