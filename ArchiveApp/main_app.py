# main_app.py
import sys
import os
import shutil
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QListWidget, QLineEdit, QLabel,
    QRadioButton, QProgressBar, QMessageBox, QGroupBox, QComboBox, QListWidgetItem
)
from PyQt6.QtCore import QThread, QSettings, QSize

from custom_widgets import FileItemWidget
from worker import ArchiveWorker

# Modern Dark Theme Stylesheet
DARK_STYLESHEET = """
QWidget {
    background-color: #1e1f22;
    color: #e0e0e0;
    font-size: 10pt;
    font-family: Segoe UI, sans-serif;
}
QMainWindow, QGroupBox {
    background-color: #2b2d30;
}
QPushButton {
    background-color: #4f545c;
    border: 1px solid #4f545c;
    padding: 8px;
    border-radius: 4px;
}
QPushButton:hover {
    background-color: #5c626b;
}
QPushButton:pressed {
    background-color: #3f434a;
}
QPushButton:disabled {
    background-color: #3a3c40;
    color: #8e8e8e;
}
QLineEdit, QComboBox {
    background-color: #2b2d30;
    border: 1px solid #4f545c;
    padding: 6px;
    border-radius: 4px;
}
QListWidget {
    background-color: #9c9c9c; /* Light grey background */
    color: #1e1f22; /* Dark text for contrast */
    border: 1px solid #4f545c;
    border-radius: 4px;
    outline: 0;
}
QListWidget::item {
    padding: 2px;
}
QProgressBar {
    border: 1px solid #4f545c;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
}
QProgressBar::chunk {
    background-color: #007acc;
    border-radius: 3px;
}
QStatusBar {
    background-color: #1e1f22;
    color: #a0a0a0;
}
QMessageBox {
    background-color: #2b2d30;
}
"""

class ArchiverApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern Archiver")
        
        # Member variables
        self.source_dir = ""
        self.output_dir = ""
        self.archive_thread = None
        self.archive_worker = None
        self.file_data_cache = []

        self.setup_ui()
        self.setup_connections()
        self.check_rar_availability()
        self.load_settings()

    def setup_ui(self):
        self.setStyleSheet(DARK_STYLESHEET)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # --- Left Pane (File Browser) ---
        left_pane_layout = QVBoxLayout()
        
        # Sorting and selection controls
        browser_controls_layout = QHBoxLayout()
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Name (A-Z)", "Name (Z-A)", "Size (Largest)",
            "Size (Smallest)", "Date (Newest)", "Date (Oldest)"
        ])
        
        self.select_all_btn = QPushButton("Select All")
        self.deselect_all_btn = QPushButton("Deselect All")
        
        browser_controls_layout.addWidget(QLabel("Sort by:"))
        browser_controls_layout.addWidget(self.sort_combo)
        browser_controls_layout.addStretch()
        browser_controls_layout.addWidget(self.select_all_btn)
        browser_controls_layout.addWidget(self.deselect_all_btn)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setSpacing(3)

        left_pane_layout.addLayout(browser_controls_layout)
        left_pane_layout.addWidget(self.file_list_widget)

        # --- Right Pane (Controls) ---
        right_pane_layout = QVBoxLayout()
        right_pane_layout.setSpacing(10)

        # Folder selection
        self.folder_choose_btn = QPushButton("Choose Source Folder...")
        self.folder_path_label = QLabel("No folder selected.")
        self.folder_path_label.setWordWrap(True)

        self.output_loc_btn = QPushButton("Choose Output Location...")
        self.output_path_label = QLabel("No output location selected.")
        self.output_path_label.setWordWrap(True)

        self.user_message_input = QLineEdit()
        self.user_message_input.setPlaceholderText("e.g., ProjectBackup, Photos, etc.")

        format_group = QGroupBox("Archive Format")
        format_layout = QHBoxLayout()
        self.zip_radio = QRadioButton("ZIP")
        self.rar_radio = QRadioButton("RAR")
        self.zip_radio.setChecked(True)
        format_layout.addWidget(self.zip_radio)
        format_layout.addWidget(self.rar_radio)
        format_group.setLayout(format_layout)

        self.start_btn = QPushButton("Start Archiving")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        right_pane_layout.addWidget(self.folder_choose_btn)
        right_pane_layout.addWidget(self.folder_path_label)
        right_pane_layout.addSpacing(15)
        right_pane_layout.addWidget(self.output_loc_btn)
        right_pane_layout.addWidget(self.output_path_label)
        right_pane_layout.addSpacing(15)
        right_pane_layout.addWidget(QLabel("User Message (for filename):"))
        right_pane_layout.addWidget(self.user_message_input)
        right_pane_layout.addSpacing(15)
        right_pane_layout.addWidget(format_group)
        right_pane_layout.addStretch()
        right_pane_layout.addWidget(self.progress_bar)
        right_pane_layout.addWidget(self.start_btn)
        
        self.statusBar().showMessage("Ready. Please select a source folder.")
        
        main_layout.addLayout(left_pane_layout, 2)
        main_layout.addLayout(right_pane_layout, 1)

    def setup_connections(self):
        self.folder_choose_btn.clicked.connect(self.choose_source_folder)
        self.output_loc_btn.clicked.connect(self.choose_output_location)
        self.sort_combo.currentIndexChanged.connect(self.sort_and_display_files)
        self.select_all_btn.clicked.connect(lambda: self.set_all_states(True))
        self.deselect_all_btn.clicked.connect(lambda: self.set_all_states(False))
        self.start_btn.clicked.connect(self.start_archiving)

    def choose_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder", self.source_dir)
        if folder:
            self.set_source_folder(folder)

    def set_source_folder(self, folder):
        self.source_dir = folder
        self.folder_path_label.setText(f"<b>Source:</b> {folder}")
        self.statusBar().showMessage(f"Folder selected. Ready to configure.")
        self.gather_file_data()
        self.sort_and_display_files()

    def choose_output_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Location", self.output_dir)
        if folder:
            self.set_output_location(folder)

    def set_output_location(self, folder):
        self.output_dir = folder
        self.output_path_label.setText(f"<b>Output:</b> {folder}")

    def gather_file_data(self):
        self.file_data_cache = []
        if not self.source_dir or not os.path.isdir(self.source_dir):
            return
        try:
            for item_name in os.listdir(self.source_dir):
                full_path = os.path.join(self.source_dir, item_name)
                stat = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                self.file_data_cache.append({
                    "path": full_path,
                    "name": item_name,
                    "size": stat.st_size,
                    "m_time": datetime.fromtimestamp(stat.st_mtime),
                    "is_dir": is_dir
                })
        except OSError as e:
            self.show_error_message("Error Reading Folder", f"Could not read folder contents.\nError: {e}")

    def sort_and_display_files(self):
        sort_key = self.sort_combo.currentText()
        
        # Primary sort: directories first (is_dir=True comes before is_dir=False)
        # Secondary sort: based on user selection
        
        if "Name" in sort_key:
            self.file_data_cache.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), 
                                      reverse=sort_key == "Name (Z-A)")
        elif "Size" in sort_key:
            self.file_data_cache.sort(key=lambda x: (not x["is_dir"], x["size"]), 
                                      reverse=sort_key == "Size (Largest)")
        elif "Date" in sort_key:
            self.file_data_cache.sort(key=lambda x: (not x["is_dir"], x["m_time"]), 
                                      reverse=sort_key == "Date (Newest)")

        self.file_list_widget.clear()
        for item_data in self.file_data_cache:
            list_item = QListWidgetItem(self.file_list_widget)
            custom_widget = FileItemWidget(
                item_data["path"], item_data["size"], item_data["m_time"], item_data["is_dir"]
            )
            list_item.setSizeHint(custom_widget.sizeHint())
            self.file_list_widget.addItem(list_item)
            self.file_list_widget.setItemWidget(list_item, custom_widget)

    def set_all_states(self, included: bool):
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            widget = self.file_list_widget.itemWidget(item)
            if isinstance(widget, FileItemWidget):
                widget.set_state(included)

    def start_archiving(self):
        if not self.source_dir: self.show_error_message("Missing Source", "Please select a source folder."); return
        if not self.output_dir: self.show_error_message("Missing Output", "Please select an output location."); return

        included_items = []
        for i in range(self.file_list_widget.count()):
            widget = self.file_list_widget.itemWidget(self.file_list_widget.item(i))
            if widget and widget.is_included:
                included_items.append(widget.full_path)

        if not included_items: self.show_error_message("No Files", "Please select at least one file to archive."); return

        user_msg = self.user_message_input.text().strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_format = "rar" if self.rar_radio.isChecked() else "zip"
        filename = f"{timestamp}_{user_msg}.{archive_format}" if user_msg else f"{timestamp}.{archive_format}"
        archive_path = os.path.join(self.output_dir, filename)

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Archiving... please wait.")

        self.archive_thread = QThread()
        self.archive_worker = ArchiveWorker(included_items, archive_path, archive_format, self.source_dir)
        self.archive_worker.moveToThread(self.archive_thread)
        self.archive_thread.started.connect(self.archive_worker.run)
        self.archive_worker.finished.connect(self.on_archiving_finished)
        self.archive_worker.error.connect(self.on_archiving_error)
        self.archive_worker.progress.connect(self.update_progress)
        self.archive_thread.finished.connect(self.archive_thread.deleteLater)
        self.archive_worker.finished.connect(self.archive_thread.quit)
        self.archive_worker.error.connect(self.archive_thread.quit)
        self.archive_thread.finished.connect(self._cleanup_archive_thread) # Connect for final cleanup
        self.archive_thread.start()

    def on_archiving_finished(self, message):
        self.statusBar().showMessage(message, 5000)
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        # self.archive_thread = None # Let deleteLater handle cleanup

    def on_archiving_error(self, error_message):
        self.show_error_message("Archiving Failed", error_message)
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Archiving failed.", 5000)
        # self.archive_thread = None # Let deleteLater handle cleanup

    def update_progress(self, value): self.progress_bar.setValue(value)

    def set_ui_enabled(self, enabled: bool):
        self.start_btn.setEnabled(enabled)
        self.folder_choose_btn.setEnabled(enabled)
        self.output_loc_btn.setEnabled(enabled)
        self.file_list_widget.setEnabled(enabled)
        self.sort_combo.setEnabled(enabled)

    def _cleanup_archive_thread(self):
        """Cleans up thread and worker references after the thread has finished."""
        if self.archive_thread:
            self.archive_thread.deleteLater() # Ensure C++ object is deleted
        self.archive_thread = None
        self.archive_worker = None

    def check_rar_availability(self):
        if not shutil.which("rar"):
            self.rar_radio.setEnabled(False)
            self.rar_radio.setToolTip("RAR command not found in system PATH.")

    def show_error_message(self, title, message): QMessageBox.critical(self, title, message)

    def load_settings(self):
        settings = QSettings("MyCompany", "ModernArchiver")
        self.restoreGeometry(settings.value("geometry", self.saveGeometry()))
        self.restoreState(settings.value("windowState", self.saveState()))
        
        last_source = settings.value("source_dir", "")
        if last_source and os.path.isdir(last_source):
            self.set_source_folder(last_source)
            
        last_output = settings.value("output_dir", "")
        if last_output and os.path.isdir(last_output):
            self.set_output_location(last_output)
            
        self.user_message_input.setText(settings.value("user_message", ""))
        
        if settings.value("format", "zip") == "rar" and self.rar_radio.isEnabled():
            self.rar_radio.setChecked(True)
        else:
            self.zip_radio.setChecked(True)

        # Restore sort order
        sort_index = settings.value("sort_index", 0, type=int)
        if 0 <= sort_index < self.sort_combo.count():
            self.sort_combo.setCurrentIndex(sort_index)

        # Restore included files state
        # This needs to happen after set_source_folder has populated the list
        # set_source_folder is called above if last_source is valid
        # If last_source was not valid, the list will be empty, so no need to restore states
        if last_source and os.path.isdir(last_source):
            included_paths = settings.value("included_files", [], type=list)
            included_paths_set = set(included_paths) # For faster lookup

            for i in range(self.file_list_widget.count()):
                item = self.file_list_widget.item(i)
                widget = self.file_list_widget.itemWidget(item)
                if isinstance(widget, FileItemWidget):
                    widget.set_state(widget.full_path in included_paths_set)

    def save_settings(self):
        settings = QSettings("MyCompany", "ModernArchiver")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("source_dir", self.source_dir)
        settings.setValue("output_dir", self.output_dir)
        settings.setValue("user_message", self.user_message_input.text())
        settings.setValue("format", "rar" if self.rar_radio.isChecked() else "zip")
        settings.setValue("sort_index", self.sort_combo.currentIndex())
        
        # Save included files
        included_paths = []
        for i in range(self.file_list_widget.count()):
            widget = self.file_list_widget.itemWidget(self.file_list_widget.item(i))
            if widget and widget.is_included:
                included_paths.append(widget.full_path)
        settings.setValue("included_files", included_paths)

    def closeEvent(self, event):
        self.save_settings()
        if self.archive_thread and self.archive_thread.isRunning():
            reply = QMessageBox.question(self, "Exit Confirmation", "An archiving process is running. Are you sure you want to exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if self.archive_worker: self.archive_worker.stop()
                self.archive_thread.quit()
                self.archive_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ArchiverApp()
    window.resize(1000, 700)
    window.show()
    sys.exit(app.exec())
