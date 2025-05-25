# downloader_worker.py - Handles Telegram API interactions and downloading
import asyncio
import os
import re
from datetime import datetime, timezone
import pytz
import pandas as pd

from PyQt6.QtCore import QObject, pyqtSignal, QDate, Qt

from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    ApiIdInvalidError, ApiIdPublishedFloodError, FloodWaitError, ChannelInvalidError,
    AuthKeyError
)

from utils import sanitize_filename, SETTINGS_ORGANIZATION, SETTINGS_APPNAME
from PyQt6.QtCore import QSettings # For getting timezone, though can be passed

class DownloaderWorker(QObject):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str, str)
    download_finished = pyqtSignal(str)
    auth_code_needed = pyqtSignal(str)
    auth_password_needed = pyqtSignal(str)
    excel_exported = pyqtSignal(str)

    def __init__(self, settings_dict, db_manager):
        super().__init__()
        self.settings = settings_dict # This now includes API ID/Hash/Phone from config
        self.db_manager = db_manager
        self.client = None
        self._running = False
        self._paused = False
        self._stop_requested = False
        self.loop = None
        self._auth_code = None
        self._auth_password = None
        self._waiting_for_auth = False
        self._current_task = None
        self.image_data_for_excel = [] # For current session's Excel export

    def run(self):
        self._running = True
        self._paused = False
        self._stop_requested = False
        self.count = 0
        self.image_data_for_excel.clear() # Clear for new session

        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._current_task = self.loop.create_task(self.download_images_async())
            self.loop.run_until_complete(self._current_task)
        except asyncio.CancelledError:
            self.status_updated.emit("Task was cancelled.")
        except Exception as e:
            self.status_updated.emit(f"Error in worker run: {e}")
            self.error_occurred.emit("Download Error", f"An unexpected error occurred in worker:\n{type(e).__name__}: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        
        # Ensure client disconnection happens in the event loop if possible
        if self.client and self.loop and self.loop.is_running():
            if self.client.is_connected():
                 asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop).result(timeout=5) # Wait for disconnect
        elif self.client and self.client.is_connected() and not self.loop.is_running():
             # If loop is not running, try to run disconnect in a new temp loop
             temp_loop = asyncio.new_event_loop()
             try:
                 temp_loop.run_until_complete(self.client.disconnect())
             finally:
                 temp_loop.close()


        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            # self.loop.close() # Closing loop here can cause issues if tasks are still pending clean up by asyncio
            
        self._running = False
        msg_prefix = "Stopped" if self._stop_requested else "Finished"
        self.download_finished.emit(f"{msg_prefix}. Downloaded {self.count} images.")

    async def download_images_async(self):
        self.status_updated.emit("Connecting to Telegram...")
        session_name = "telegram_session" 
        
        # Ensure API ID is int
        try:
            api_id = int(self.settings['api_id'])
        except ValueError:
            self.error_occurred.emit("Configuration Error", "API ID must be a number.")
            return

        try:
            self.client = TelegramClient(session_name,
                                         api_id,
                                         self.settings['api_hash'],
                                         loop=self.loop)

            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.status_updated.emit("Authorization needed...")
                phone_number = self.settings['phone']
                await self.client.send_code_request(phone_number)
                
                self._waiting_for_auth = True
                self.auth_code_needed.emit(phone_number)
                
                while self._waiting_for_auth and not self._stop_requested:
                    await asyncio.sleep(0.1)
                if self._stop_requested: return
                    
                try:
                    await self.client.sign_in(phone_number, self._auth_code)
                except SessionPasswordNeededError:
                    self._waiting_for_auth = True
                    self.auth_password_needed.emit("Two-factor authentication is enabled")
                    while self._waiting_for_auth and not self._stop_requested:
                        await asyncio.sleep(0.1)
                    if self._stop_requested: return
                    await self.client.sign_in(password=self._auth_password)

            self.status_updated.emit("Fetching channel info...")
            try:
                channel_entity = await self.client.get_entity(self.settings['channel'])
            except ValueError:
                 raise ChannelInvalidError(request=None)

            self.status_updated.emit(f"Starting download from {self.settings['channel']}...")
            
            # Date handling
            start_qdate = self.settings.get('start_date', QDate(2000, 1, 1))
            # Use QSettings to get system timezone if available, else default to UTC
            # This part might be better if MainWindow passes the timezone string
            q_settings_access = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
            system_timezone_name = q_settings_access.value("System/Timezone", "UTC")
            try:
                local_tz = pytz.timezone(system_timezone_name)
            except pytz.UnknownTimeZoneError:
                local_tz = pytz.utc
            
            start_datetime_local = datetime.combine(start_qdate.toPyDate(), datetime.min.time(), tzinfo=local_tz)
            start_datetime_utc = start_datetime_local.astimezone(timezone.utc)

            self.status_updated.emit(f"Filtering images from: {start_qdate.toString(Qt.DateFormat.ISODate)}")
            
            last_caption = "no_caption"
            current_message_id = None
            message_image_count = 0
            message_group_counter = 0 # This is a UI/session-level grouping

            exclusion_patterns = self.settings.get('exclusion_patterns', [])

            async for message in self.client.iter_messages(channel_entity, limit=None): # Consider adding a limit for safety during testing
                if self._stop_requested: break
                while self._paused:
                    if self._stop_requested: break
                    self.status_updated.emit("Paused...")
                    await asyncio.sleep(1)
                if self._stop_requested: break

                if message.date < start_datetime_utc:
                    self.status_updated.emit("Reached start date. Stopping iteration.")
                    break

                if current_message_id != message.id:
                    current_message_id = message.id
                    message_image_count = 0
                    message_group_counter += 1
                    if message.message and message.message.strip():
                        last_caption = message.message.strip()
                    # else, keep last_caption from previous message if current is empty

                if message.media and isinstance(message.media, MessageMediaPhoto):
                    message_image_count += 1
                    caption_raw = message.message if message.message else last_caption
                    message_date_local = message.date.astimezone(local_tz)
                    date_str = message_date_local.strftime("%Y%m%d_%H%M%S")

                    original_filename = None
                    if self.settings.get('preserve_names', False) and hasattr(message.media, 'photo') and message.media.photo:
                        if hasattr(message.media.photo, 'attributes'):
                            for attr in message.media.photo.attributes:
                                if hasattr(attr, 'file_name') and attr.file_name:
                                    original_filename = attr.file_name
                                    break
                    
                    filename_base = f"{date_str}_{caption_raw}"
                    if original_filename and self.settings.get('preserve_names', False):
                        base_name, ext = os.path.splitext(original_filename)
                        if not ext: ext = ".jpg"
                        filename_base = f"{date_str}_{base_name}"
                    else:
                        if message_image_count > 1:
                            filename_base = f"{filename_base}_{message_image_count}"
                        ext = ".jpg" # Default extension
                    
                    # Ensure filename_base doesn't have extension before sanitize_filename adds it
                    if original_filename and self.settings.get('preserve_names', False):
                         filename_sanitized_base = sanitize_filename(filename_base, exclusion_patterns)
                         filename_sanitized = filename_sanitized_base + ext
                    else: # caption based
                         filename_sanitized = sanitize_filename(filename_base, exclusion_patterns) + ".jpg"


                    full_path = os.path.join(self.settings['save_folder'], filename_sanitized)

                    try:
                        self.status_updated.emit(f"Downloading: {filename_sanitized}")
                        await self.client.download_media(message.media, file=full_path)
                        self.count += 1
                        self.progress_updated.emit(self.count)
                        
                        # Prepare caption for DB/Excel, applying exclusions
                        caption_for_export = caption_raw
                        if exclusion_patterns:
                            for pattern in exclusion_patterns:
                                if pattern.startswith("regex:"):
                                    try:
                                        caption_for_export = re.sub(pattern[6:], '', caption_for_export)
                                    except re.error: pass
                                else:
                                    caption_for_export = caption_for_export.replace(pattern, '')
                        
                        image_metadata_db = {
                            'download_timestamp': datetime.now(timezone.utc).isoformat(),
                            'message_id': message.id,
                            'message_date_utc': message.date.isoformat(),
                            'message_date_local': message_date_local.isoformat(),
                            'channel': self.settings['channel'],
                            'caption_original': caption_raw,
                            'caption_processed': caption_for_export.strip(),
                            'filename': filename_sanitized,
                            'file_path': full_path,
                            'original_telegram_filename': original_filename,
                            'image_number_in_message': message_image_count,
                            'message_group_id': message_group_counter
                        }
                        if not self.db_manager.save_image_metadata(image_metadata_db):
                            self.status_updated.emit(f"Warning: Failed to save metadata to DB for {filename_sanitized}")

                        if self.settings.get('export_excel', False):
                            # For Excel, use a slightly different format if needed, or same as DB
                            image_info_excel = {
                                'Date': message_date_local.strftime("%Y-%m-%d"),
                                'Time': message_date_local.strftime("%H:%M:%S"),
                                'Caption': caption_for_export.strip(),
                                'Filename': filename_sanitized,
                                'Full Path': full_path,
                                'Channel': self.settings['channel'],
                                'Message ID': message.id,
                                'Image Number': message_image_count,
                                'Message Group': message_group_counter,
                                'Original Filename': original_filename if original_filename else "N/A",
                                'UTC Date': message.date.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            self.image_data_for_excel.append(image_info_excel)
                            
                    except Exception as download_err:
                        self.status_updated.emit(f"Skipped download ({filename_sanitized}): {download_err}")
                        await asyncio.sleep(0.1)

                await asyncio.sleep(0.05)

            if self.settings.get('export_excel', False) and not self._stop_requested and self.image_data_for_excel:
                await self.export_to_excel_async()

        except (ApiIdInvalidError, ApiIdPublishedFloodError):
            self.error_occurred.emit("Telegram Error", "Invalid API ID or Hash. Check config.ini.")
        except PhoneNumberInvalidError:
            self.error_occurred.emit("Telegram Error", "Invalid Phone Number format in config.ini.")
        except PhoneCodeInvalidError:
             self.error_occurred.emit("Telegram Error", "Invalid confirmation code.")
        except SessionPasswordNeededError: # Should be caught by specific flow, but as fallback
             self.error_occurred.emit("Telegram Error", "Two-factor authentication password needed.")
        except AuthKeyError:
             self.error_occurred.emit("Telegram Error", "Authorization key error. Session might be corrupted. Try deleting 'telegram_session.session' file and 'telegram_session.session-journal' if it exists.")
        except ChannelInvalidError:
            self.error_occurred.emit("Telegram Error", f"Cannot find channel '{self.settings['channel']}'. Check username/ID.")
        except FloodWaitError as e:
             self.error_occurred.emit("Telegram Error", f"Flood wait: Please wait {e.seconds}s and try again.")
        except ConnectionError:
             self.error_occurred.emit("Network Error", "Could not connect to Telegram. Check internet.")
        except Exception as e:
            self.error_occurred.emit("Download Error", f"Unexpected error during download:\n{type(e).__name__}: {e}")
            import traceback
            traceback.print_exc() # For dev console
        # No finally block for client disconnect here, it's in the outer cleanup

    async def export_to_excel_async(self):
        if not self.image_data_for_excel:
            self.status_updated.emit("No image data from this session to export to Excel.")
            return
        try:
            self.status_updated.emit("Exporting session data to Excel...")
            df = pd.DataFrame(self.image_data_for_excel)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            channel_name_safe = re.sub(r'[^a-zA-Z0-9_-]', '_', self.settings['channel'])
            excel_filename = f"telegram_images_{channel_name_safe}_{timestamp}.xlsx"
            excel_path = os.path.join(self.settings['save_folder'], excel_filename)
            
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='ImageData', index=False)
                worksheet = writer.sheets['ImageData']
                for i, col in enumerate(df.columns):
                    max_length = max(df[col].astype(str).map(len).max(), len(col))
                    adjusted_width = min(max_length + 2, 70) # Cap width
                    worksheet.column_dimensions[chr(65 + i)].width = adjusted_width
            
            self.status_updated.emit(f"Excel file exported: {excel_filename}")
            self.excel_exported.emit(excel_path)
        except Exception as e:
            self.status_updated.emit(f"Error exporting to Excel: {e}")
            self.error_occurred.emit("Excel Export Error", f"Failed to export data to Excel:\n{str(e)}")

    def stop(self):
        self._stop_requested = True
        self._paused = False 
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        if self.loop and self.loop.is_running():
            for task in asyncio.all_tasks(self.loop):
                task.cancel()

    def pause(self):
        if self._running: self._paused = True
    def resume(self):
        if self._running: self._paused = False
    def toggle_pause(self):
        if not self._running: return
        if self._paused: self.resume()
        else: self.pause()
    def is_running(self): return self._running
    def is_paused(self): return self._paused
    def set_auth_code(self, code):
        self._auth_code = code
        self._waiting_for_auth = False
    def set_auth_password(self, password):
        self._auth_password = password
        self._waiting_for_auth = False