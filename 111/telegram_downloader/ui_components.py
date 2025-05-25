# ui_components.py - Contains UI-related components and dialogs
import os
import sys
import re
from datetime import datetime
import pytz

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QStatusBar,
    QMessageBox, QDateEdit, QFormLayout, QSizePolicy, QDialog,
    QCheckBox, QProgressBar, QTextEdit, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QDate
from PyQt6.QtGui import QPalette, QColor

from utils import SETTINGS_ORGANIZATION, SETTINGS_APPNAME, sanitize_filename
from downloader_worker import DownloaderWorker # Import from the new file
# No direct ConfigManager import here, MainWindow gets credentials passed or calls it.
# Let's have MainWindow instantiate ConfigManager.

class AuthCodeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Telegram Authentication")
        self.setFixedWidth(450) # Wider for more text
        layout = QVBoxLayout(self)

        auth_info_label = QLabel(
            "IMPORTANT: Telegram has sent a verification code to your Telegram app. "
            "Look for a message from the official 'Telegram' service account in your chats.")
        auth_info_label.setObjectName("auth_info_label") # For specific styling
        auth_info_label.setWordWrap(True)
        layout.addWidget(auth_info_label)

        self.instruction_label = QLabel("Enter the code received:")
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Enter code here")
        layout.addWidget(self.code_input)

        self.password_label = QLabel("If 2FA is enabled, enter your password:")
        self.password_label.setWordWrap(True)
        layout.addWidget(self.password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("2FA Password (if set)")
        layout.addWidget(self.password_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # Make OK default
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)

        layout.addWidget(buttons)

    def get_code(self): return self.code_input.text().strip()
    def get_password(self): return self.password_input.text().strip()


class ExclusionPatternDialog(QDialog):
    def __init__(self, parent=None, current_patterns_text=""):
        super().__init__(parent)
        self.setWindowTitle("Exclusion Patterns")
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        
        instruction_label = QLabel(
            "Enter patterns (one per line) to exclude from filenames and Excel exports.\n"
            "- Simple text matches anywhere.\n"
            "- Use # for comments.\n"
            "- Start with 'regex:' for regular expressions (e.g., regex:\\d+).\n"
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)
        
        editor_layout = QHBoxLayout()
        pattern_editor_layout = QVBoxLayout()
        pattern_editor_layout.addWidget(QLabel("Exclusion Patterns:"))
        self.pattern_editor = QTextEdit()
        self.pattern_editor.setObjectName("pattern_editor") # For specific styling
        self.pattern_editor.setPlaceholderText("Enter patterns, one per line...")
        self.pattern_editor.setText(current_patterns_text)
        self.pattern_editor.textChanged.connect(self.update_preview) # Connect signal
        pattern_editor_layout.addWidget(self.pattern_editor)
        editor_layout.addLayout(pattern_editor_layout)
        
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(QLabel("Preview Test:"))
        self.test_input = QLineEdit("Sample text with numbers 123 and #hashtag")
        self.test_input.textChanged.connect(self.update_preview)
        preview_layout.addWidget(self.test_input)
        self.preview_output = QLineEdit()
        self.preview_output.setReadOnly(True)
        preview_layout.addWidget(self.preview_output)
        editor_layout.addLayout(preview_layout)
        layout.addLayout(editor_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_preview() # Initial preview

    def get_patterns_text(self): return self.pattern_editor.toPlainText()
    
    def get_active_patterns_list(self):
        patterns = []
        for line in self.get_patterns_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.append(line)
        return patterns

    def update_preview(self):
        test_text = self.test_input.text()
        active_patterns = self.get_active_patterns_list()
        # Preview sanitization for filename (which also uses exclusions)
        preview_filename = sanitize_filename(test_text, active_patterns)
        
        # Preview just text replacement for things like Excel caption
        preview_text_replaced = test_text
        for p in active_patterns:
            if p.startswith("regex:"):
                try:
                    preview_text_replaced = re.sub(p[6:], '', preview_text_replaced)
                except re.error: pass
            else:
                preview_text_replaced = preview_text_replaced.replace(p, '')
        self.preview_output.setText(f"Filename: {preview_filename} | Text: {preview_text_replaced.strip()}")


class MainWindow(QMainWindow):
    def __init__(self, config_manager, db_manager):
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager # Store db_manager instance
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPNAME)
        
        self.setWindowTitle("Telegram Image Downloader")
        self.setGeometry(100, 100, 750, 600)
        self.setMinimumSize(650, 500)

        self.downloader_thread = None
        self.downloader_worker = None
        self.api_id, self.api_hash, self.phone_number = None, None, None # Store credentials

        self.init_ui()
        self.load_app_settings() # Loads QSettings
        self.update_button_states()
        # Dark theme applied in main.py
        
        self.check_telegram_config() # Check INI config and guide user

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Info label for config.ini
        self.config_info_label = QLabel("API ID, Hash, and Phone are configured in config.ini.")
        self.config_info_label.setWordWrap(True)
        layout.addWidget(self.config_info_label)

        form_layout = QFormLayout()
        self.channel_entry = QLineEdit()
        self.channel_entry.setPlaceholderText("Channel Username (e.g., @channel) or ID")
        form_layout.addRow(QLabel("Channel Username/ID:"), self.channel_entry)
        layout.addLayout(form_layout)

        folder_layout = QHBoxLayout()
        self.folder_button = QPushButton("Select Save Folder")
        self.folder_button.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected.")
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_button)
        folder_layout.addWidget(self.folder_label, 1)
        layout.addLayout(folder_layout)

        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("Download images from:"))
        self.date_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        options_layout.addWidget(self.date_edit)
        
        self.export_excel_checkbox = QCheckBox("Export data to Excel")
        self.preserve_names_checkbox = QCheckBox("Preserve original filenames")
        self.exclusion_button = QPushButton("Exclusion Patterns")
        self.exclusion_button.clicked.connect(self.open_exclusion_dialog)
        
        options_layout.addWidget(self.export_excel_checkbox)
        options_layout.addWidget(self.preserve_names_checkbox)
        options_layout.addWidget(self.exclusion_button)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0,0) # Indeterminate initially, or 0,100
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v files")
        progress_layout.addWidget(QLabel("Progress:"))
        progress_layout.addWidget(self.progress_bar, 1)
        layout.addLayout(progress_layout)

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

        layout.addStretch()
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.count_label = QLabel("Saved: 0")
        self.status_label = QLabel("Ready.")
        self.statusBar.addPermanentWidget(self.count_label)
        self.statusBar.addWidget(self.status_label, 1)

    def check_telegram_config(self):
        self.api_id, self.api_hash, self.phone_number = self.config_manager.get_telegram_credentials()
        if not self.api_id or not self.api_hash or not self.phone_number:
            QMessageBox.warning(self, "Configuration Incomplete",
                                f"Telegram API credentials (API ID, API Hash, Phone Number) are missing or incomplete in '{self.config_manager.filename}'.\n\n"
                                "Please create or edit this file with your details.\n"
                                "The application may not function correctly until this is done.")
            self.start_button.setEnabled(False) # Disable start if config is bad
            self.status_label.setText(f"Error: Missing credentials in {self.config_manager.filename}")
            return False
        self.status_label.setText(f"Credentials loaded from {self.config_manager.filename}.")
        return True

    def get_current_run_settings(self):
        """Reads settings from UI fields for the current download run."""
        # Crucially, API creds come from self.api_id etc. loaded from config_manager
        if not self.check_telegram_config(): # Re-check and load if necessary
             return None

        return {
            'api_id': self.api_id,
            'api_hash': self.api_hash,
            'phone': self.phone_number,
            'channel': self.channel_entry.text().strip(),
            'save_folder': getattr(self, 'save_folder_path', ''),
            'start_date': self.date_edit.date(),
            'export_excel': self.export_excel_checkbox.isChecked(),
            'preserve_names': self.preserve_names_checkbox.isChecked(),
            'exclusion_patterns': getattr(self, 'current_exclusion_patterns_list', [])
        }

    def validate_run_settings(self, settings_dict):
        if not settings_dict: return False # If get_current_run_settings returned None

        required_ui = ['channel', 'save_folder']
        missing = [field for field in required_ui if not settings_dict.get(field)]
        if missing:
            self.show_error("Missing Information", f"Please fill in/select: {', '.join(missing)}")
            return False
        if not settings_dict['api_id'].isdigit(): # API ID already checked by check_telegram_config but good to have
            self.show_error("Invalid API ID", "API ID from config.ini must be a number.")
            return False
        return True

    def start_download(self):
        if not self.check_telegram_config(): # Ensure config is still valid
            return

        current_run_settings = self.get_current_run_settings()
        if not self.validate_run_settings(current_run_settings):
            return

        self.save_app_settings() # Save QSettings (UI preferences)

        self.status_label.setText("Starting...")
        self.count_label.setText("Saved: 0")
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0,100) # Or keep 0,0 for indeterminate for a bit

        self.downloader_worker = DownloaderWorker(current_run_settings, self.db_manager)
        self.downloader_thread = QThread()
        self.downloader_worker.moveToThread(self.downloader_thread)

        self.downloader_thread.started.connect(self.downloader_worker.run)
        self.downloader_worker.progress_updated.connect(self.update_progress)
        self.downloader_worker.status_updated.connect(self.update_status)
        self.downloader_worker.error_occurred.connect(self.show_error)
        self.downloader_worker.download_finished.connect(self.on_download_finished)
        self.downloader_worker.auth_code_needed.connect(self.request_auth_code)
        self.downloader_worker.auth_password_needed.connect(self.request_auth_password)
        self.downloader_worker.excel_exported.connect(self.on_excel_exported)

        # Proper thread cleanup
        self.downloader_worker.download_finished.connect(self.downloader_thread.quit)
        # self.downloader_thread.finished.connect(self.downloader_worker.deleteLater) # deleteLater can be problematic if worker is accessed after
        self.downloader_thread.finished.connect(self.clear_worker_references) # Custom cleanup
        self.downloader_thread.finished.connect(self.update_button_states)

        self.downloader_thread.start()
        self.update_button_states()

    def clear_worker_references(self):
        if self.downloader_worker:
            self.downloader_worker.deleteLater() # Schedule for deletion
        if self.downloader_thread:
             self.downloader_thread.deleteLater()
        self.downloader_worker = None
        self.downloader_thread = None


    def stop_download(self):
        if self.downloader_worker:
            self.status_label.setText("Stopping download...")
            self.downloader_worker.stop()
            self.stop_button.setEnabled(False)
            self.stop_button.setText("Stopping...")
            # Remainder of cleanup and button updates handled by download_finished signal

    def toggle_pause_resume(self):
        if not (self.downloader_worker and self.downloader_worker.is_running()): return
        self.downloader_worker.toggle_pause()
        is_paused = self.downloader_worker.is_paused()
        self.pause_resume_button.setText("Resume" if is_paused else "Pause")
        self.status_label.setText("Paused." if is_paused else "Resuming...")


    def update_progress(self, count):
        self.count_label.setText(f"Saved: {count}")
        self.progress_bar.setValue(count)
        # If total is unknown, keep range 0,0 or set max very high.
        # If we knew total messages, we could set range 0, total_messages.
        # For now, just count up.
        if self.progress_bar.maximum() == 0 or count > self.progress_bar.maximum() : # make it a growing bar
             self.progress_bar.setRange(0, count + 10) # extend max if needed
        self.progress_bar.setFormat(f"{count} files")


    def update_status(self, status_text): self.status_label.setText(status_text)
    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)
        self.status_label.setText(f"Error: {title}")

    def on_download_finished(self, final_message):
        self.update_status(final_message)
        # Thread and worker cleanup is handled by clear_worker_references via finished signal
        self.update_button_states() # Ensure buttons are correctly set
        self.progress_bar.setRange(0,100) # Reset progress bar range

    def update_button_states(self):
        is_running = bool(self.downloader_worker and self.downloader_worker.is_running())
        is_paused = is_running and self.downloader_worker.is_paused()

        self.start_button.setEnabled(not is_running and self.check_telegram_config()) # Check config too
        self.stop_button.setEnabled(is_running)
        self.pause_resume_button.setEnabled(is_running)
        
        if not is_running: self.stop_button.setText("Stop")
        self.pause_resume_button.setText("Resume" if is_paused else "Pause")
        if not is_running: self.pause_resume_button.setText("Pause")


        self.channel_entry.setEnabled(not is_running)
        self.folder_button.setEnabled(not is_running)
        self.date_edit.setEnabled(not is_running)
        self.export_excel_checkbox.setEnabled(not is_running)
        self.preserve_names_checkbox.setEnabled(not is_running)
        self.exclusion_button.setEnabled(not is_running)


    def select_folder(self):
        # Use last used folder from QSettings as starting point
        last_folder = self.settings.value("downloader/save_folder", QDir.homePath())
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder", last_folder)
        if folder:
            self.save_folder_path = folder # Store path in attribute
            self.folder_label.setText(f"Save to: {folder}")
            # self.settings.setValue("downloader/save_folder", folder) # Saved in save_app_settings

    def load_app_settings(self): # For QSettings
        self.channel_entry.setText(self.settings.value("downloader/channel", ""))
        
        folder = self.settings.value("downloader/save_folder", "")
        if folder and os.path.isdir(folder):
             self.save_folder_path = folder
             self.folder_label.setText(f"Save to: {folder}")
        else:
             self.save_folder_path = "" # Ensure it's initialized
             self.folder_label.setText("No folder selected.")

        date_str = self.settings.value("downloader/start_date", "")
        if date_str:
            self.date_edit.setDate(QDate.fromString(date_str, Qt.DateFormat.ISODate))
        # else default (currentDate - 1 month) is fine

        self.export_excel_checkbox.setChecked(self.settings.value("downloader/export_excel", False, type=bool))
        self.preserve_names_checkbox.setChecked(self.settings.value("downloader/preserve_names", False, type=bool))

        patterns_text = self.settings.value("downloader/exclusion_patterns_text", "")
        self.current_exclusion_patterns_list = []
        for line in patterns_text.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                self.current_exclusion_patterns_list.append(line)
        
        # Try to get system timezone and save it for the worker
        try:
            system_tz = pytz.timezone(datetime.now(pytz.timezone('UTC').astimezone().tzinfo).tzname())
            self.settings.setValue("System/Timezone", system_tz.zone)
        except Exception: # Fallback if timezone name is weird
            self.settings.setValue("System/Timezone", "UTC")


    def save_app_settings(self): # For QSettings
        self.settings.setValue("downloader/channel", self.channel_entry.text().strip())
        if hasattr(self, 'save_folder_path') and self.save_folder_path:
            self.settings.setValue("downloader/save_folder", self.save_folder_path)
        self.settings.setValue("downloader/start_date", self.date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("downloader/export_excel", self.export_excel_checkbox.isChecked())
        self.settings.setValue("downloader/preserve_names", self.preserve_names_checkbox.isChecked())
        # Exclusion patterns text is saved from its dialog's accept.

    def request_auth_code(self, phone):
        QMessageBox.information(self, "Telegram Auth Code",
            f"Telegram is sending a code to your number: {phone} via the Telegram app.\n"
            "Check messages from the official 'Telegram' account.")
        
        dialog = AuthCodeDialog(self)
        dialog.instruction_label.setText(f"Enter code sent to {phone} via Telegram app:")
        dialog.password_input.hide()
        dialog.password_label.hide()
        
        if dialog.exec():
            code = dialog.get_code()
            if code and self.downloader_worker:
                self.status_label.setText("Submitting auth code...")
                self.downloader_worker.set_auth_code(code)
            else:
                self.stop_download() # Or emit error
                self.status_label.setText("Auth cancelled: No code.")
        else:
            self.stop_download() # Or emit error
            self.status_label.setText("Auth cancelled by user.")
            
    def request_auth_password(self, message):
        QMessageBox.information(self, "Telegram 2FA Password",
            "Your account has Two-Factor Authentication enabled.\n"
            "Enter your 2FA password (this is NOT your phone login code).")

        dialog = AuthCodeDialog(self)
        dialog.setWindowTitle("Two-Factor Authentication")
        dialog.instruction_label.setText("Enter your 2FA password:")
        dialog.code_input.hide() # Hide code input field
        # Adjust visibility or text of password label if needed
        dialog.password_label.setText("This is the 2FA password for your Telegram account:")
        
        if dialog.exec():
            password = dialog.get_password()
            if password and self.downloader_worker:
                self.status_label.setText("Submitting 2FA password...")
                self.downloader_worker.set_auth_password(password)
            else:
                self.stop_download()
                self.status_label.setText("2FA cancelled: No password.")
        else:
            self.stop_download()
            self.status_label.setText("2FA cancelled by user.")

    def on_excel_exported(self, excel_path):
        reply = QMessageBox.information(self, "Excel Exported",
            f"Data exported to:\n{excel_path}\n\nOpen it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if sys.platform == "win32": os.startfile(excel_path)
                elif sys.platform == "darwin": os.system(f"open '{excel_path}'")
                else: os.system(f"xdg-open '{excel_path}'")
            except Exception as e:
                QMessageBox.warning(self, "Error Opening File", f"Could not open Excel: {e}")

    def open_exclusion_dialog(self):
        current_text = self.settings.value("downloader/exclusion_patterns_text", "")
        dialog = ExclusionPatternDialog(self, current_text)
        if dialog.exec():
            new_text = dialog.get_patterns_text()
            self.settings.setValue("downloader/exclusion_patterns_text", new_text)
            self.current_exclusion_patterns_list = dialog.get_active_patterns_list() # Update runtime list
            count = len(self.current_exclusion_patterns_list)
            self.status_label.setText(f"Saved {count} exclusion pattern(s).")

    def closeEvent(self, event):
        if self.downloader_worker and self.downloader_worker.is_running():
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Download in progress. Stop and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_download()
                # Wait for thread to finish (optional, can be tricky)
                if self.downloader_thread and self.downloader_thread.isRunning():
                    self.downloader_thread.wait(3000) # Wait up to 3s
                self.save_app_settings()
                self.db_manager.close() # Close DB connection
                event.accept()
            else:
                event.ignore()
        else:
            self.save_app_settings()
            self.db_manager.close() # Close DB connection
            event.accept()

# For QDir.homePath()
from PyQt6.QtCore import QDir