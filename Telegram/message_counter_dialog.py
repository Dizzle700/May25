import os
import sqlite3
import asyncio
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDateEdit,
    QMessageBox, QFormLayout, QLineEdit
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal, QObject
from datetime import datetime, timezone
import pytz

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    ApiIdInvalidError, ApiIdPublishedFloodError, FloodWaitError, ChannelInvalidError,
    AuthKeyError
)

# Re-using AuthCodeDialog from telegram2.py for consistency
try:
    from .telegram2 import AuthCodeDialog # For running as part of a package
except ImportError:
    # Fallback for standalone testing or if telegram2 is not a package
    # This is a simplified version, ideally AuthCodeDialog would be in a common_ui module
    class AuthCodeDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Telegram Authentication")
            self.setFixedWidth(400)
            layout = QVBoxLayout(self)
            self.instruction_label = QLabel("Enter the code you received:")
            self.instruction_label.setWordWrap(True)
            layout.addWidget(self.instruction_label)
            self.code_input = QLineEdit()
            self.code_input.setPlaceholderText("Enter code here (e.g. 12345)")
            layout.addWidget(self.code_input)
            self.password_label = QLabel("If you have two-factor authentication enabled, enter your password:")
            self.password_label.setWordWrap(True)
            layout.addWidget(self.password_label)
            self.password_input = QLineEdit()
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.password_input.setPlaceholderText("2FA Password (if needed)")
            layout.addWidget(self.password_input)
            button_layout = QHBoxLayout()
            self.cancel_button = QPushButton("Cancel")
            self.submit_button = QPushButton("Submit")
            self.submit_button.setDefault(True)
            self.cancel_button.clicked.connect(self.reject)
            self.submit_button.clicked.connect(self.accept)
            button_layout.addWidget(self.cancel_button)
            button_layout.addWidget(self.submit_button)
            layout.addLayout(button_layout)
        def get_code(self): return self.code_input.text().strip()
        def get_password(self): return self.password_input.text().strip()


class MessageCounterWorker(QObject):
    """Worker to perform message counting in a separate thread directly from Telegram."""
    count_finished = pyqtSignal(int, str) # count, status_message
    error_occurred = pyqtSignal(str, str) # title, message
    status_updated = pyqtSignal(str) # For general status updates
    auth_code_needed = pyqtSignal(str)  # New signal for requesting auth code
    auth_password_needed = pyqtSignal(str)  # New signal for requesting 2FA password

    def __init__(self, api_id, api_hash, phone, channel_name, start_date_utc, end_date_utc):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.channel_name = channel_name
        self.start_date_utc = start_date_utc # datetime object
        self.end_date_utc = end_date_utc # datetime object (exclusive end)
        
        self.client = None
        self.loop = None
        self._stop_requested = False
        self._auth_code = None
        self._auth_password = None
        self._waiting_for_auth = False

    def run(self):
        self._stop_requested = False
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.count_messages_async())
        except asyncio.CancelledError:
            self.status_updated.emit("Counting cancelled.")
        except Exception as e:
            self.error_occurred.emit("Counting Error", f"An unexpected error occurred: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        if self.client and self.client.is_connected():
            self.loop.run_until_complete(self.client.disconnect())
        if self.loop and self.loop.is_running():
            self.loop.stop()
        self.status_updated.emit("Finished counting.")

    async def count_messages_async(self):
        self.status_updated.emit("Connecting to Telegram...")
        session_name = "telegram_message_counter_session" # Separate session for counter

        try:
            self.client = TelegramClient(session_name, self.api_id, self.api_hash, loop=self.loop)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.status_updated.emit("Authorization needed...")
                await self.client.send_code_request(self.phone)
                
                self._waiting_for_auth = True
                self.auth_code_needed.emit(self.phone)
                while self._waiting_for_auth and not self._stop_requested:
                    await asyncio.sleep(0.1)
                if self._stop_requested: return

                try:
                    await self.client.sign_in(self.phone, self._auth_code)
                except SessionPasswordNeededError:
                    self._waiting_for_auth = True
                    self.auth_password_needed.emit("Two-factor authentication is enabled")
                    while self._waiting_for_auth and not self._stop_requested:
                        await asyncio.sleep(0.1)
                    if self._stop_requested: return
                    await self.client.sign_in(password=self._auth_password)
            
            self.status_updated.emit(f"Fetching channel: {self.channel_name}...")
            try:
                channel = await self.client.get_entity(self.channel_name)
            except ValueError:
                raise ChannelInvalidError(request=None)

            count = 0
            unique_message_ids = set()
            self.status_updated.emit("Counting messages in channel...")

            # Iterate messages from newest to oldest, starting from just before end_datetime_for_offset
            async for message in self.client.iter_messages(channel, offset_date=self.end_date_utc): # self.end_date_utc is now end_datetime_for_offset
                if self._stop_requested:
                    self.status_updated.emit("Stopping counting.")
                    break

                # Stop if message is older than the start date
                if message.date < self.start_date_utc:
                    self.status_updated.emit("Reached start date. Stopping iteration.")
                    break
                
                # No need for the 'if message.date >= self.end_date_utc: continue' check here
                # because offset_date already handles the upper bound correctly.
                # Messages returned by iter_messages with offset_date will be older than offset_date.
                # So, if offset_date is start of next day, all messages will be on or before end_date.

                if message.id not in unique_message_ids:
                    unique_message_ids.add(message.id)
                    count += 1
                    self.status_updated.emit(f"Counting... Found {count} unique messages.")
                
                await asyncio.sleep(0.01) # Small delay to yield control

            self.count_finished.emit(count, f"Count complete: {count} unique messages.")

        except (ApiIdInvalidError, ApiIdPublishedFloodError):
            self.error_occurred.emit("Telegram Error", "Invalid API ID or Hash.")
        except PhoneNumberInvalidError:
            self.error_occurred.emit("Telegram Error", "Invalid Phone Number format.")
        except PhoneCodeInvalidError:
             self.error_occurred.emit("Telegram Error", "Invalid confirmation code.")
        except SessionPasswordNeededError:
             self.error_occurred.emit("Telegram Error", "Two-factor authentication password needed. Please configure session.")
        except AuthKeyError:
             self.error_occurred.emit("Telegram Error", "Authorization key error. Session might be corrupted or revoked. Try deleting 'telegram_message_counter_session.session' file.")
        except ChannelInvalidError:
            self.error_occurred.emit("Telegram Error", f"Cannot find channel '{self.channel_name}'. Check username/ID.")
        except FloodWaitError as e:
             self.error_occurred.emit("Telegram Error", f"Flood wait requested by Telegram. Please wait {e.seconds} seconds and try again.")
        except ConnectionError:
             self.error_occurred.emit("Network Error", "Could not connect to Telegram. Check your internet connection.")
        except Exception as e:
            self.error_occurred.emit("Counting Error", f"An unexpected error occurred:\n{type(e).__name__}: {e}")
            import traceback
            print(f"Unhandled error in MessageCounterWorker: {e}")
            traceback.print_exc()
        finally:
            if self.client and self.client.is_connected():
                await self.client.disconnect()
                self.status_updated.emit("Disconnected.")

    def stop(self):
        self._stop_requested = True
        if self.loop and self.loop.is_running():
            for task in asyncio.all_tasks(self.loop):
                task.cancel()

    def set_auth_code(self, code):
        self._auth_code = code
        self._waiting_for_auth = False
        
    def set_auth_password(self, password):
        self._auth_password = password
        self._waiting_for_auth = False


class MessageCounterDialog(QDialog):
    def __init__(self, db_path, parent=None): # db_path is no longer directly used for counting, but kept for consistency
        super().__init__(parent)
        self.setWindowTitle("Count Channel Messages")
        self.setGeometry(200, 200, 450, 250) # Adjusted size
        self.setMinimumSize(400, 200)

        self.db_path = db_path # Kept for potential future use or context
        self.worker_thread = None
        self.worker = None

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # Date selection
        date_form_layout = QFormLayout()

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1)) # Default to 1 month ago

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit.setDate(QDate.currentDate()) # Default to today

        date_form_layout.addRow("Start Date:", self.start_date_edit)
        date_form_layout.addRow("End Date:", self.end_date_edit)
        main_layout.addLayout(date_form_layout)

        # Count button
        self.count_button = QPushButton("Count Messages")
        self.count_button.clicked.connect(self.start_count)
        main_layout.addWidget(self.count_button)

        # Result display
        self.result_label = QLabel("Total unique messages: 0")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #0078d7;")
        main_layout.addWidget(self.result_label)

        # Status label
        self.status_label = QLabel("Ready to count.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

        main_layout.addStretch() # Push content to top

    def start_count(self):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Counting in Progress", "A message count is already in progress. Please wait.")
            return

        # Get API credentials and channel name from the parent (MainWindow)
        # This assumes the parent is a MainWindow instance and has get_current_settings()
        parent_settings = self.parent().get_current_settings()
        api_id = int(parent_settings['api_id'])
        api_hash = parent_settings['api_hash']
        phone = parent_settings['phone']
        channel_name = parent_settings['channel']

        if not all([api_id, api_hash, phone, channel_name]):
            QMessageBox.critical(self, "Configuration Error", "Telegram API credentials or channel name are not configured in the main window.")
            return

        start_qdate = self.start_date_edit.date()
        end_qdate = self.end_date_edit.date()

        if start_qdate > end_qdate:
            QMessageBox.warning(self, "Invalid Date Range", "Start date cannot be after end date.")
            return

        self.status_label.setText("Connecting to Telegram and counting messages...")
        self.result_label.setText("Total unique messages: Calculating...")
        self.count_button.setEnabled(False)

        # Convert QDate to UTC datetime objects for Telethon
        # Telethon's offset_date is exclusive, so for an inclusive end date, we use the start of the next day.
        start_datetime_utc = datetime.combine(start_qdate.toPyDate(), datetime.min.time(), tzinfo=timezone.utc)
        end_datetime_utc_exclusive = datetime.combine(end_qdate.toPyDate(), datetime.max.time(), tzinfo=timezone.utc) # Use max.time for inclusive end of day

        self.worker = MessageCounterWorker(
            api_id, api_hash, phone, channel_name,
            start_datetime_utc, end_datetime_utc_exclusive
        )
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.count_finished.connect(self.on_count_finished)
        self.worker.error_occurred.connect(self.show_error)
        self.worker.status_updated.connect(self.status_label.setText) # Update status label in dialog

        # Connect authentication signals from worker to dialog's methods
        self.worker.auth_code_needed.connect(self.request_auth_code)
        self.worker.auth_password_needed.connect(self.request_auth_password)
        
        self.worker.count_finished.connect(self.worker_thread.quit)
        self.worker.count_finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(lambda: setattr(self, 'worker_thread', None))
        self.worker_thread.finished.connect(lambda: setattr(self, 'worker', None))

        self.worker_thread.start()

    def on_count_finished(self, count, status_message):
        self.result_label.setText(f"Total unique messages: {count}")
        self.status_label.setText(status_message)
        self.count_button.setEnabled(True)

    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)
        self.status_label.setText(f"Error: {title}")
        self.count_button.setEnabled(True)

    def request_auth_code(self, phone):
        """Show a dialog to request the Telegram authentication code for the worker."""
        dialog = AuthCodeDialog(self)
        dialog.instruction_label.setText(f"Please enter the authentication code sent to {phone}\nvia the Telegram app:")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            code = dialog.get_code()
            if code:
                self.worker.set_auth_code(code)
            else:
                self.worker.stop() # Stop worker if no code provided
                self.status_label.setText("Authentication cancelled - no code provided.")
        else:
            self.worker.stop() # Stop worker if user cancelled
            self.status_label.setText("Authentication cancelled by user.")
            
    def request_auth_password(self, message):
        """Show a dialog to request the Telegram 2FA password for the worker."""
        dialog = AuthCodeDialog(self)
        dialog.setWindowTitle("Two-Factor Authentication")
        dialog.instruction_label.setText("Your account has two-factor authentication enabled.")
        dialog.code_input.hide()
        dialog.password_label.setText("This is the 2FA password you created in your Telegram security settings:")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            password = dialog.get_password()
            if password:
                self.worker.set_auth_password(password)
            else:
                self.worker.stop() # Stop worker if no password provided
                self.status_label.setText("Authentication cancelled - no password provided.")
        else:
            self.worker.stop() # Stop worker if user cancelled
            self.status_label.setText("Authentication cancelled by user.")

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.stop() # Request worker to stop gracefully
            self.worker_thread.quit()
            self.worker_thread.wait(2000) # Give it a moment to finish
        super().closeEvent(event)

if __name__ == '__main__':
    # This block is for standalone testing of the dialog
    import sys
    from PyQt6.QtWidgets import QApplication
    
    # For standalone testing, you would need to provide dummy API credentials
    # and a dummy parent with a get_current_settings method.
    # This is complex for a simple __main__ block.
    # It's better to test this dialog by running telegram2.py.
    
    print("To test MessageCounterDialog, please run telegram2.py and open the dialog from there.")
    print("This standalone __main__ block is primarily for syntax checking.")
    
    # Example of how you might mock a parent for testing purposes (not functional without real API keys)
    class MockMainWindow:
        def get_current_settings(self):
            return {
                'api_id': '1234567', # Replace with dummy or real
                'api_hash': 'your_api_hash', # Replace with dummy or real
                'phone': '+1234567890', # Replace with dummy or real
                'channel': 'telethon_test_channel' # Replace with dummy or real
            }
        def show_error(self, title, message):
            print(f"Mock Error: {title} - {message}")

    app = QApplication(sys.argv)
    # dialog = MessageCounterDialog(db_path="dummy.sqlite", parent=MockMainWindow()) # This would require a QApplication instance
    # dialog.exec()
    sys.exit(0) # Exit immediately as full standalone test is complex
