# --- START OF FILE ftpc_pyqt.py ---

import sys
import os
import ftplib
import socket
import ipaddress
import time
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QSplitter, QProgressBar, QFileDialog, QMessageBox, QStatusBar, QMenu,
    QDialog, QInputDialog, QFormLayout, QComboBox, QDialogButtonBox, QProgressDialog,
    QStyle
)
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, pyqtSlot, QSize, QTimer
from PyQt6.QtGui import QIcon, QFont, QAction, QPixmap, QColor

# --- Configuration ---
APP_NAME = "Comfy FTP Client (PyQt6)"
DEFAULT_HOST = "192.168.1.10"
DEFAULT_PORT = "21"  # Standard FTP port
DEFAULT_USER = "pc"
DEFAULT_NETWORK = "192.168.1.0/24"

# --- Icons (Placeholder - requires icon files or use built-in styles) ---
# For a real app, replace these with paths to actual icon files or use QStyle standard icons
ICON_CONNECT = "icons/connect.png"
ICON_DISCONNECT = "icons/disconnect.png"
ICON_UPLOAD = "icons/upload.png"
ICON_DOWNLOAD = "icons/download.png"
ICON_REFRESH = "icons/refresh.png"
ICON_FOLDER = "icons/folder.png"
ICON_FILE = "icons/file.png"
ICON_SCAN = "icons/scan.png"
ICON_APP = "icons/app.png" # App icon for window

# --- Style Sheet (Nord-like Theme) ---
STYLESHEET = """
QWidget {
    background-color: #2E3440;
    color: #ECEFF4;
    font-size: 10pt;
}
QMainWindow {
    background-color: #2E3440;
}
QStatusBar {
    background-color: #3B4252;
    color: #ECEFF4;
}
QMenuBar {
    background-color: #3B4252;
    color: #ECEFF4;
}
QMenuBar::item:selected {
    background-color: #4C566A;
}
QMenu {
    background-color: #3B4252;
    color: #ECEFF4;
    border: 1px solid #4C566A;
}
QMenu::item:selected {
    background-color: #5E81AC;
}
QLabel {
    color: #D8DEE9;
}
QLineEdit {
    background-color: #434C5E;
    color: #ECEFF4;
    border: 1px solid #4C566A;
    border-radius: 3px;
    padding: 3px;
}
QPushButton {
    background-color: #5E81AC;
    color: #ECEFF4;
    border: none;
    padding: 5px 10px;
    border-radius: 3px;
    min-width: 60px;
}
QPushButton:hover {
    background-color: #81A1C1;
}
QPushButton:pressed {
    background-color: #88C0D0;
}
QPushButton:disabled {
    background-color: #4C566A;
    color: #6a7385;
}
QTreeWidget {
    background-color: #3B4252;
    color: #ECEFF4;
    border: 1px solid #4C566A;
    alternate-background-color: #434C5E;
}
QHeaderView::section {
    background-color: #434C5E;
    color: #ECEFF4;
    padding: 4px;
    border: 1px solid #4C566A;
}
QTreeWidget::item:selected {
    background-color: #5E81AC;
    color: #ECEFF4;
}
QTreeWidget::item:hover {
    background-color: #4C566A;
}
QProgressBar {
    border: 1px solid #4C566A;
    border-radius: 3px;
    text-align: center;
    color: #ECEFF4; /* Color of the percentage text */
}
QProgressBar::chunk {
    background-color: #88C0D0; /* Color of the progress bar fill */
    width: 10px; /* Smoothness */
    margin: 0.5px;
}
QComboBox {
    background-color: #434C5E;
    border: 1px solid #4C566A;
    padding: 3px 5px;
    border-radius: 3px;
}
QComboBox::drop-down {
    border: none;
    background-color: #5E81AC;
    width: 15px;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}
QComboBox QAbstractItemView { /* Style for the dropdown list */
    background-color: #3B4252;
    border: 1px solid #4C566A;
    selection-background-color: #5E81AC;
}
QSplitter::handle {
    background-color: #4C566A;
    /* image: url(icons/splitter_handle.png); Optional custom handle image */
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QToolTip {
    background-color: #4C566A;
    color: #ECEFF4;
    border: 1px solid #5E81AC;
}
/* Style for QMessageBox */
QMessageBox {
    background-color: #3B4252;
}
QMessageBox QLabel { /* Text label */
    color: #ECEFF4;
}
QMessageBox QPushButton { /* Buttons */
    min-width: 80px; /* Ensure buttons are reasonably sized */
}
/* Style for QInputDialog */
QInputDialog {
    background-color: #3B4252;
    color: #ECEFF4;
}
QInputDialog QLineEdit {
    background-color: #434C5E; /* Keep consistency */
}
QInputDialog QPushButton {
     min-width: 80px;
}
"""

# --- Helper Functions ---
def format_size(size_bytes):
    """ Formats bytes into a human-readable string (KB, MB, GB). """
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes/1024**2:.1f} MB"
    else:
        return f"{size_bytes/1024**3:.1f} GB"

def get_qicon(icon_path, fallback_style=None):
    """ Safely loads a QIcon, falling back to a standard icon if path fails. """
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    elif fallback_style:
        return QApplication.style().standardIcon(fallback_style)
    else:
        # Return an empty icon or a simple placeholder pixmap
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor("gray"))
        return QIcon(pixmap)


# --- Worker Objects for Threading ---

class ConnectWorker(QObject):
    """ Worker for handling FTP connection in a separate thread. """
    connected = pyqtSignal(object, str) # ftp object, welcome message
    error = pyqtSignal(str)
    log_message = pyqtSignal(str, str) # message, level

    def __init__(self, host, port, user, password, use_tls):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.use_tls = use_tls
        self.ftp = None

    @pyqtSlot()
    def run(self):
        try:
            self.log_message.emit(f"Connecting to {self.host}:{self.port}...", "info")
            if self.use_tls:
                self.ftp = ftplib.FTP_TLS(timeout=10)
            else:
                self.ftp = ftplib.FTP(timeout=10)

            self.ftp.connect(self.host, self.port)
            welcome = self.ftp.getwelcome()
            self.log_message.emit(f"Server Welcome: {welcome}", "info")

            if self.use_tls:
                 # Needed for AUTH TLS, secure control connection first
                 # Some servers require login *before* prot_p, some after. Try after first.
                 # self.ftp.auth() # Secure control connection (optional, often implicit with login)
                 pass # Often login handles AUTH TLS implicitly

            login_msg = self.ftp.login(self.user, self.password)
            self.log_message.emit(f"Login successful: {login_msg}", "success")

            if self.use_tls:
                self.ftp.prot_p() # Secure data connection
                self.log_message.emit("Using secure data connection (PROT P).", "info")

            # Check features after login
            try:
                 self.ftp.features = self.ftp.sendcmd('FEAT')
                 self.log_message.emit(f"Server Features:\n{self.ftp.features}", "debug") # Use debug level
                 # Simple check if MLSD is advertised
                 self.ftp.supports_mlsd = 'MLSD' in self.ftp.features
            except Exception:
                 self.log_message.emit("FEAT command not supported or failed.", "warning")
                 self.ftp.supports_mlsd = False


            self.connected.emit(self.ftp, welcome)

        except ftplib.all_errors as e:
            self.error.emit(f"FTP Connection Error: {str(e)}")
            if self.ftp:
                try: self.ftp.close()
                except: pass
        except socket.error as e:
            self.error.emit(f"Socket Error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Unexpected Error during connection: {str(e)}")


class TransferWorker(QObject):
    """ Worker for handling file transfers (upload/download). """
    progress = pyqtSignal(int) # Percentage
    finished = pyqtSignal(str) # Success message
    error = pyqtSignal(str)    # Error message
    log_message = pyqtSignal(str, str) # message, level

    def __init__(self, ftp, action, local_path, remote_path):
        super().__init__()
        self.ftp = ftp
        self.action = action # 'upload' or 'download'
        self.local_path = local_path
        self.remote_path = remote_path
        self._is_running = True
        self.total_size = 0
        self.transferred = 0

    def report_progress(self, block):
        if not self._is_running:
            # This is a bit tricky, ftplib callbacks don't easily support stopping.
            # This won't immediately stop it, but prevents further progress updates.
            # A more robust stop requires interrupting the socket transfer, which is complex.
            raise InterruptedError("Transfer cancelled by user") # Try to raise an error

        block_len = len(block)
        self.transferred += block_len

        # Handle potential write for download callback
        if self.action == 'download' and self.file_handle:
            try:
                self.file_handle.write(block)
            except Exception as e:
                 self.error.emit(f"Error writing to local file {self.local_path}: {e}")
                 self._is_running = False # Signal stop
                 raise # Propagate error to stop retrbinary

        if self.total_size > 0:
            percent = int((self.transferred / self.total_size) * 100)
            self.progress.emit(percent)
        # else: No size info, maybe emit -1 or use indeterminate bar?

    @pyqtSlot()
    def run(self):
        self._is_running = True
        self.transferred = 0
        self.file_handle = None # For downloads

        try:
            filename = os.path.basename(self.local_path if self.action == 'upload' else self.remote_path)
            self.log_message.emit(f"{self.action.capitalize()}ing {filename}...", "info")

            if self.action == 'upload':
                if not os.path.exists(self.local_path):
                    raise FileNotFoundError(f"Local file not found: {self.local_path}")
                self.total_size = os.path.getsize(self.local_path)
                self.progress.emit(0) # Start at 0%
                with open(self.local_path, 'rb') as f:
                    # Use storbinary for upload
                    self.ftp.storbinary(f'STOR {self.remote_path}', f, callback=self.report_progress)

            elif self.action == 'download':
                # Try to get size for progress bar (might fail)
                try:
                    self.total_size = self.ftp.size(self.remote_path)
                except ftplib.all_errors:
                    self.log_message.emit(f"Could not determine size of {filename}. Progress may be inaccurate.", "warning")
                    self.total_size = 0 # Indicate unknown size

                self.progress.emit(0) # Start at 0%
                # Open local file *before* starting transfer
                self.file_handle = open(self.local_path, 'wb')
                # Use retrbinary for download, lambda combines writing and progress reporting
                self.ftp.retrbinary(f'RETR {self.remote_path}', self.report_progress)

            if self._is_running: # Check if cancelled during transfer
                 self.finished.emit(f"{filename} {self.action}ed successfully.")

        except FileNotFoundError as e:
            self.error.emit(str(e))
        except ftplib.all_errors as e:
            self.error.emit(f"FTP Error during {self.action}: {str(e)}")
        except InterruptedError: # Catch our custom cancel signal
             self.error.emit(f"{self.action.capitalize()} cancelled.")
        except Exception as e:
            self.error.emit(f"Unexpected Error during {self.action}: {str(e)}")
        finally:
            if self.file_handle:
                try:
                    self.file_handle.close()
                except Exception as e:
                    self.log_message.emit(f"Error closing file handle for {self.local_path}: {e}", "error")
            if not self._is_running: # Ensure progress resets if cancelled
                 self.progress.emit(0)


    @pyqtSlot()
    def stop(self):
        self.log_message.emit("Stopping transfer...", "info")
        self._is_running = False
        # Note: Stopping ongoing ftplib transfer precisely is hard.
        # This relies on the callback check or errors during the process.

# --- Scan Worker ---
class ScanWorker(QObject):
    found = pyqtSignal(str, int, str) # host, port, banner
    progress = pyqtSignal(int, int) # current, total
    finished = pyqtSignal(int) # count
    log_message = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, network_range, ports_to_scan=(21,)):
        super().__init__()
        self.network_range = network_range
        self.ports_to_scan = ports_to_scan
        self._is_running = True

    @pyqtSlot()
    def run(self):
        self._is_running = True
        count = 0
        scanned_count = 0
        try:
            network = ipaddress.ip_network(self.network_range, strict=False)
            # Generators can't be easily len()'d without iterating, so estimate or count first
            # For potentially large networks, counting first might be slow.
            # Compromise: Count first for reasonable sizes.
            try:
                total_hosts = sum(1 for _ in network.hosts())
            except MemoryError: # Network too large to count easily
                 self.log_message.emit("Network range is very large, progress total might be inaccurate.", "warning")
                 total_hosts = 0 # Or some large estimate

            self.progress.emit(0, total_hosts)

            for host in network.hosts():
                if not self._is_running:
                    self.log_message.emit("Scan cancelled.", "info")
                    break
                host_str = str(host)
                for port in self.ports_to_scan:
                    if not self._is_running: break
                    try:
                        # Short timeout for initial connection check
                        with socket.create_connection((host_str, port), timeout=0.5) as sock:
                            # If connection succeeds, try to get banner
                            banner = "N/A"
                            if port == 21: # Only try FTP banner grab on port 21
                                try:
                                    ftp = ftplib.FTP()
                                    # Use a slightly longer timeout for banner grab
                                    ftp.connect(host_str, port, timeout=2)
                                    banner = ftp.getwelcome().strip()
                                    ftp.close()
                                except Exception:
                                    banner = "(Failed to get banner)" # Indicate connection worked but banner failed
                            else:
                                banner = "(Port Open)" # Generic for other ports

                            self.found.emit(host_str, port, banner)
                            count += 1
                            # Short delay to avoid overwhelming network/target
                            time.sleep(0.01)

                    except (socket.timeout, ConnectionRefusedError, OSError):
                        pass # Host not responding on this port
                    except Exception as e_inner:
                        # Log unexpected errors during individual host scan
                        self.log_message.emit(f"Error scanning {host_str}:{port} - {e_inner}", "warning")

                scanned_count += 1
                self.progress.emit(scanned_count, total_hosts)

            self.finished.emit(count)

        except ValueError as e:
            self.error.emit(f"Invalid network range '{self.network_range}': {e}")
        except Exception as e:
            self.error.emit(f"Network Scan Error: {str(e)}")

    @pyqtSlot()
    def stop(self):
        self._is_running = False


# --- Scan Results Dialog ---
class ScanDialog(QDialog):
    host_selected = pyqtSignal(str, str) # host, port

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Scan Results")
        self.setMinimumSize(500, 400)
        self.setStyleSheet(parent.styleSheet() if parent else "") # Inherit style

        layout = QVBoxLayout(self)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Host", "Port", "Banner"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.tree)

        self.status_label = QLabel("Scanning...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100) # Initial range
        layout.addWidget(self.progress_bar)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Select Host")
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False) # Disabled until item selected
        layout.addWidget(self.button_box)

        self.tree.itemSelectionChanged.connect(
            lambda: self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.tree.selectedItems()))
        )

    def add_result(self, host, port, banner):
        item = QTreeWidgetItem([host, str(port), banner])
        self.tree.addTopLevelItem(item)

    def update_progress(self, current, total):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.status_label.setText(f"Scanning... ({current}/{total})")
        else: # Unknown total
             self.progress_bar.setRange(0, 0) # Indeterminate
             self.status_label.setText(f"Scanning... (Host {current})")


    def set_finished(self, count):
        self.status_label.setText(f"Scan Finished. Found {count} potential FTP server(s).")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100) # Show as complete
        # Maybe auto-enable OK if results found?
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.tree.topLevelItemCount() > 0))


    def accept_selection(self):
        selected = self.tree.selectedItems()
        if selected:
            host = selected[0].text(0)
            port = selected[0].text(1)
            self.host_selected.emit(host, port)
            self.accept() # Close dialog
        else:
             QMessageBox.warning(self, "No Selection", "Please select a host from the list.")


# --- Main Application Window ---
class FTPClientWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        try:
            self.setWindowIcon(get_qicon(ICON_APP))
        except Exception as e:
             print(f"Warning: Could not load app icon: {e}")
        self.setGeometry(100, 100, 1100, 700) # Increased size slightly

        self.ftp = None
        self.current_local_dir = os.path.expanduser("~")
        self.current_remote_dir = "/"
        self.transfer_thread = None
        self.transfer_worker = None
        self.connect_thread = None
        self.connect_worker = None
        self.scan_thread = None
        self.scan_worker = None

        # Icons (load safely)
        self.icon_folder = get_qicon(ICON_FOLDER, QStyle.StandardPixmap.SP_DirIcon)
        self.icon_file = get_qicon(ICON_FILE, QStyle.StandardPixmap.SP_FileIcon)

        self.setup_ui()
        self.apply_styles()
        self.connect_signals()

        self.refresh_local()
        self.update_ui_state() # Set initial button states etc.

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)  # Reduce margins to give more space to file managers

        # --- Connection Bar (COMPACT VERSION) ---
        conn_widget = QWidget()
        conn_layout = QVBoxLayout(conn_widget)  # Use vertical layout for the two rows
        conn_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins
        conn_layout.setSpacing(5)  # Reduce spacing between rows

        # Row 1: Host, Port, User, Password
        top_row_layout = QHBoxLayout()
        top_row_layout.addWidget(QLabel("Host:"))
        self.host_entry = QLineEdit(DEFAULT_HOST)
        top_row_layout.addWidget(self.host_entry, 2)  # Give host more space
        
        top_row_layout.addWidget(QLabel("Port:"))
        self.port_entry = QLineEdit(DEFAULT_PORT)
        self.port_entry.setMaximumWidth(60)
        top_row_layout.addWidget(self.port_entry)
        
        top_row_layout.addWidget(QLabel("User:"))
        self.username_entry = QLineEdit(DEFAULT_USER)
        top_row_layout.addWidget(self.username_entry, 1)
        
        top_row_layout.addWidget(QLabel("Password:"))
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        top_row_layout.addWidget(self.password_entry, 1)
        
        # Add connect/disconnect buttons to first row
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setIcon(get_qicon(ICON_CONNECT, QStyle.StandardPixmap.SP_DialogYesButton))
        top_row_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setIcon(get_qicon(ICON_DISCONNECT, QStyle.StandardPixmap.SP_DialogNoButton))
        top_row_layout.addWidget(self.disconnect_btn)
        
        conn_layout.addLayout(top_row_layout)

        # Row 2: Encryption and Network Scan
        bottom_row_layout = QHBoxLayout()
        
        bottom_row_layout.addWidget(QLabel("Encryption:"))
        self.tls_combo = QComboBox()
        self.tls_combo.addItems(["None (Insecure)", "Explicit TLS"])
        bottom_row_layout.addWidget(self.tls_combo)
        
        bottom_row_layout.addStretch(1)  # Add space between encryption and network scan
        
        bottom_row_layout.addWidget(QLabel("Network:"))
        self.network_entry = QLineEdit(DEFAULT_NETWORK)
        self.network_entry.setToolTip("Enter network range (e.g., 192.168.1.0/24)")
        bottom_row_layout.addWidget(self.network_entry, 2)  # Give network field more space
        
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setIcon(get_qicon(ICON_SCAN, QStyle.StandardPixmap.SP_ComputerIcon))
        self.scan_btn.setToolTip("Scan network for FTP servers (port 21)")
        bottom_row_layout.addWidget(self.scan_btn)
        
        conn_layout.addLayout(bottom_row_layout)
        main_layout.addWidget(conn_widget)

        # --- File Browser Panes ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)  # Don't allow complete collapse of panels

        # Local Files
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)  # Reduce margins to maximize space
        local_path_layout = QHBoxLayout()
        local_layout.addWidget(QLabel("Local Files"))
        self.local_path_entry = QLineEdit(self.current_local_dir)
        self.local_path_entry.setReadOnly(True)
        self.browse_local_btn = QPushButton("Browse")
        local_path_layout.addWidget(self.local_path_entry)
        local_path_layout.addWidget(self.browse_local_btn)
        local_layout.addLayout(local_path_layout)
        self.local_tree = QTreeWidget()
        self.local_tree.setColumnCount(3)
        self.local_tree.setHeaderLabels(["Name", "Size", "Modified"])
        self.local_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.local_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_tree.setAlternatingRowColors(True)
        self.local_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        local_layout.addWidget(self.local_tree)
        self.splitter.addWidget(local_widget)

        # Remote Files
        remote_widget = QWidget()
        remote_layout = QVBoxLayout(remote_widget)
        remote_layout.setContentsMargins(0, 0, 0, 0)  # Reduce margins to maximize space
        remote_path_layout = QHBoxLayout()
        remote_layout.addWidget(QLabel("Remote Files"))
        self.remote_path_entry = QLineEdit(self.current_remote_dir)
        self.remote_path_entry.setReadOnly(True)
        self.refresh_remote_btn = QPushButton("Refresh")
        self.refresh_remote_btn.setIcon(get_qicon(ICON_REFRESH, QStyle.StandardPixmap.SP_BrowserReload))
        remote_path_layout.addWidget(self.remote_path_entry)
        remote_path_layout.addWidget(self.refresh_remote_btn)
        remote_layout.addLayout(remote_path_layout)
        self.remote_tree = QTreeWidget()
        self.remote_tree.setColumnCount(4)
        self.remote_tree.setHeaderLabels(["Name", "Size", "Modified", "Type"])
        self.remote_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.remote_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.remote_tree.setAlternatingRowColors(True)
        self.remote_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        remote_layout.addWidget(self.remote_tree)
        self.splitter.addWidget(remote_widget)

        # Give file views more space in the main layout
        main_layout.addWidget(self.splitter, 1)  # Add stretch factor of 1 to make file views expand

        # --- Transfer Controls ---
        transfer_widget = QWidget()
        transfer_layout = QHBoxLayout(transfer_widget)
        transfer_layout.setContentsMargins(0, 5, 0, 0)  # Reduce top margin to save space
        self.upload_btn = QPushButton("Upload")
        self.upload_btn.setIcon(get_qicon(ICON_UPLOAD, QStyle.StandardPixmap.SP_ArrowUp))
        self.download_btn = QPushButton("Download")
        self.download_btn.setIcon(get_qicon(ICON_DOWNLOAD, QStyle.StandardPixmap.SP_ArrowDown))
        self.transfer_progress = QProgressBar()
        self.transfer_progress.setTextVisible(True)
        self.transfer_progress.setValue(0)
        self.transfer_label = QLabel("Idle")
        self.cancel_transfer_btn = QPushButton("Cancel")
        self.cancel_transfer_btn.setVisible(False)

        transfer_layout.addWidget(self.upload_btn)
        transfer_layout.addWidget(self.download_btn)
        transfer_layout.addWidget(QLabel("Progress:"))
        transfer_layout.addWidget(self.transfer_progress, 1)
        transfer_layout.addWidget(self.transfer_label, 1)
        transfer_layout.addWidget(self.cancel_transfer_btn)

        main_layout.addWidget(transfer_widget)

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)
        # Potentially set fixed sizes for icons if needed
        icon_size = QSize(16, 16)
        self.connect_btn.setIconSize(icon_size)
        self.disconnect_btn.setIconSize(icon_size)
        self.refresh_remote_btn.setIconSize(icon_size)
        self.upload_btn.setIconSize(icon_size)
        self.download_btn.setIconSize(icon_size)
        self.scan_btn.setIconSize(icon_size)


    def connect_signals(self):
        # Connection
        self.connect_btn.clicked.connect(self.connect_ftp)
        self.disconnect_btn.clicked.connect(self.disconnect_ftp)
        self.scan_btn.clicked.connect(self.scan_network)

        # File Browsing
        self.browse_local_btn.clicked.connect(self.browse_local_directory)
        self.local_tree.itemDoubleClicked.connect(self.on_local_item_double_clicked)
        self.local_tree.customContextMenuRequested.connect(self.show_local_context_menu)
        self.remote_tree.itemDoubleClicked.connect(self.on_remote_item_double_clicked)
        self.remote_tree.customContextMenuRequested.connect(self.show_remote_context_menu)
        self.refresh_remote_btn.clicked.connect(self.refresh_remote)

        # Transfers
        self.upload_btn.clicked.connect(self.upload_selected)
        self.download_btn.clicked.connect(self.download_selected)
        self.cancel_transfer_btn.clicked.connect(self.cancel_transfer)

    # --- Logging and Status ---
    def log(self, message, level="info"):
        """ Logs to status bar (briefly) and potentially a log window/file later. """
        # Simple status bar logging for now
        print(f"[{level.upper()}] {message}") # Also print to console for debugging
        if level == "error":
            self.status_bar.showMessage(f"Error: {message}", 5000) # Show for 5 seconds
            # Maybe use QMessageBox for critical errors
        elif level == "warning":
            self.status_bar.showMessage(f"Warning: {message}", 3000)
        elif level == "success":
            self.status_bar.showMessage(f"Success: {message}", 3000)
        else:
             self.status_bar.showMessage(message, 2000)

        # Log to QTextEdit if it were present:
        # timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # self.log_text.append(f"[{timestamp}][{level.upper()}] {message}")

    # --- UI State Management ---
    def update_ui_state(self):
        """ Enables/disables buttons based on connection and transfer state. """
        connected = self.ftp is not None
        transferring = self.transfer_thread is not None and self.transfer_thread.isRunning()

        # Connection controls
        self.host_entry.setEnabled(not connected and not transferring)
        self.port_entry.setEnabled(not connected and not transferring)
        self.username_entry.setEnabled(not connected and not transferring)
        self.password_entry.setEnabled(not connected and not transferring)
        self.tls_combo.setEnabled(not connected and not transferring)
        self.connect_btn.setEnabled(not connected and not transferring)
        self.disconnect_btn.setEnabled(connected and not transferring)
        self.scan_btn.setEnabled(not connected and not transferring) # Allow scanning when disconnected

        # Remote controls
        self.refresh_remote_btn.setEnabled(connected and not transferring)
        # Context menus handle their own state based on selection

        # Transfer controls
        self.upload_btn.setEnabled(connected and not transferring)
        self.download_btn.setEnabled(connected and not transferring)
        self.cancel_transfer_btn.setVisible(transferring)
        self.transfer_progress.setVisible(transferring) # Show progress only when active
        self.transfer_label.setVisible(transferring)

        if not transferring:
             self.transfer_progress.setValue(0)
             self.transfer_label.setText("Idle")


    # --- Connection Handling ---
    def connect_ftp(self):
        host = self.host_entry.text().strip()
        port_str = self.port_entry.text().strip()
        user = self.username_entry.text().strip()
        password = self.password_entry.text() # Keep password as is
        use_tls = self.tls_combo.currentIndex() == 1 # 0 is None, 1 is TLS

        if not host:
            QMessageBox.warning(self, "Input Error", "Host cannot be empty.")
            return
        try:
            port = int(port_str)
            if not 0 < port < 65536:
                raise ValueError("Port out of range")
        except ValueError:
            QMessageBox.warning(self, "Input Error", f"Invalid port number: {port_str}")
            return

        self.status_bar.showMessage(f"Connecting to {host}:{port}...")
        self.connect_btn.setEnabled(False) # Disable while attempting

        # Setup worker and thread
        self.connect_thread = QThread(self)
        self.connect_worker = ConnectWorker(host, port, user, password, use_tls)
        self.connect_worker.moveToThread(self.connect_thread)

        # Connect signals
        self.connect_worker.connected.connect(self.on_connected)
        self.connect_worker.error.connect(self.on_connection_error)
        self.connect_worker.log_message.connect(self.log) # Log messages from worker
        self.connect_thread.started.connect(self.connect_worker.run)
        self.connect_thread.finished.connect(self.on_connect_thread_finished)

        self.connect_thread.start()
        self.update_ui_state() # Reflect connecting state


    @pyqtSlot(object, str)
    def on_connected(self, ftp_instance, welcome_message):
        self.ftp = ftp_instance
        self.log(f"Connected! Welcome: {welcome_message}", "success")
        try:
            self.current_remote_dir = self.ftp.pwd()
        except ftplib.all_errors as e:
             self.log(f"Could not get initial remote directory: {e}", "warning")
             self.current_remote_dir = "/" # Fallback
        self.remote_path_entry.setText(self.current_remote_dir)
        self.refresh_remote() # Load initial remote listing
        self.status_bar.showMessage(f"Connected to {self.ftp.host}:{self.ftp.port}", 5000)

    @pyqtSlot(str)
    def on_connection_error(self, error_message):
        self.log(error_message, "error")
        QMessageBox.critical(self, "Connection Failed", error_message)
        self.ftp = None # Ensure FTP object is cleared

    @pyqtSlot()
    def on_connect_thread_finished(self):
        self.log("Connect attempt finished.", "debug")
        if self.connect_thread:
             self.connect_thread.deleteLater() # Schedule thread cleanup
             self.connect_worker.deleteLater() # Schedule worker cleanup
        self.connect_thread = None
        self.connect_worker = None
        self.update_ui_state() # Re-enable buttons etc.


    def disconnect_ftp(self):
        if self.transfer_thread and self.transfer_thread.isRunning():
            # Prevent disconnect during active transfer
            QMessageBox.warning(self, "Transfer Active", "Please cancel or wait for the current transfer to complete before disconnecting.")
            return

        if self.ftp:
            self.log(f"Disconnecting from {self.ftp.host}...", "info")
            try:
                # Run disconnect in a small timer to allow UI update
                # Sometimes quit() can block briefly
                QTimer.singleShot(10, self._perform_disconnect)
            except Exception as e:
                self.log(f"Error during disconnect: {e}", "error")
                self.ftp = None # Force clear
                self.remote_tree.clear()
                self.update_ui_state()
        else:
            self.update_ui_state() # Should already be disconnected state


    def _perform_disconnect(self):
         if self.ftp:
             try:
                  self.ftp.quit()
             except ftplib.all_errors as e:
                  self.log(f"Error sending QUIT command (closing connection anyway): {e}", "warning")
             except socket.error as e:
                  self.log(f"Socket error during QUIT (closing connection anyway): {e}", "warning")
             finally:
                  # ftplib doesn't always guarantee close() after quit() error
                  try:
                      if self.ftp.sock: self.ftp.sock.close()
                  except: pass
                  self.ftp = None
                  self.remote_tree.clear()
                  self.remote_path_entry.setText("/")
                  self.log("Disconnected.", "info")
                  self.status_bar.showMessage("Disconnected", 3000)
         self.update_ui_state()

    # --- Local File Handling ---
    def browse_local_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Local Directory",
            self.current_local_dir
        )
        if directory:
            self.current_local_dir = directory
            self.local_path_entry.setText(self.current_local_dir)
            self.refresh_local()

    def refresh_local(self):
        self.local_tree.clear()
        path = self.current_local_dir
        try:
            # Add ".." item for navigating up, unless already at root
            parent_dir = os.path.dirname(path)
            if path != parent_dir and path != os.path.abspath(os.sep): # Check if not root
                up_item = QTreeWidgetItem(["..", "", ""])
                up_item.setIcon(0, self.icon_folder)
                up_item.setData(0, Qt.ItemDataRole.UserRole, {"is_dir": True, "is_up": True})
                self.local_tree.addTopLevelItem(up_item)

            for item_name in sorted(os.listdir(path), key=str.lower):
                full_path = os.path.join(path, item_name)
                try:
                    stat_info = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    size_str = format_size(stat_info.st_size) if not is_dir else ""
                    mod_time = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')

                    tree_item = QTreeWidgetItem([item_name, size_str, mod_time])
                    tree_item.setIcon(0, self.icon_folder if is_dir else self.icon_file)
                    # Store metadata in the item using UserRole
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, {"is_dir": is_dir, "is_up": False, "full_path": full_path})

                    self.local_tree.addTopLevelItem(tree_item)

                except OSError as e:
                    self.log(f"Skipping item {item_name}: {e}", "warning") # Permissions error likely

        except Exception as e:
            self.log(f"Error listing local directory {path}: {e}", "error")
            QMessageBox.critical(self, "Local Error", f"Could not access directory:\n{path}\n\n{e}")

    def on_local_item_double_clicked(self, item, column):
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if item_data and item_data.get("is_dir"):
            item_name = item.text(0)
            if item_data.get("is_up"):
                new_path = os.path.dirname(self.current_local_dir)
            else:
                new_path = os.path.join(self.current_local_dir, item_name)

            # Basic check to prevent going above user's home in some cases? Optional.
            # new_path = os.path.abspath(new_path)

            self.current_local_dir = new_path
            self.local_path_entry.setText(self.current_local_dir)
            self.refresh_local()

    def show_local_context_menu(self, position):
        menu = QMenu()
        selected_items = self.local_tree.selectedItems()
        item_under_cursor = self.local_tree.itemAt(position) # Might be None

        # Determine selection type
        has_selection = bool(selected_items)
        is_single_selection = len(selected_items) == 1
        selected_file = False
        selected_dir = False
        if is_single_selection:
            data = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if data:
                 selected_file = not data.get("is_dir", False)
                 selected_dir = data.get("is_dir", False) and not data.get("is_up", False)


        # Upload Action
        upload_action = QAction("Upload", self)
        upload_action.setEnabled(has_selection and self.ftp is not None) # Enable if anything selected & connected
        upload_action.triggered.connect(self.upload_selected)
        menu.addAction(upload_action)

        menu.addSeparator()

        # Other local actions (Future: Delete, Rename, etc.)
        # delete_local_action = QAction("Delete", self)
        # delete_local_action.setEnabled(has_selection)
        # delete_local_action.triggered.connect(self.delete_local_selected)
        # menu.addAction(delete_local_action)

        refresh_local_action = QAction("Refresh", self)
        refresh_local_action.triggered.connect(self.refresh_local)
        menu.addAction(refresh_local_action)

        menu.exec(self.local_tree.viewport().mapToGlobal(position))


    # --- Remote File Handling ---
    def refresh_remote(self):
        if not self.ftp:
            self.remote_tree.clear() # Clear if disconnected
            return
        if self.transfer_thread and self.transfer_thread.isRunning():
             self.log("Cannot refresh during transfer.", "warning")
             return

        self.log(f"Listing remote directory: {self.current_remote_dir}...", "info")
        self.remote_tree.clear()
        self.refresh_remote_btn.setEnabled(False) # Disable while refreshing

        try:
            # Add ".." item
            if self.current_remote_dir != "/":
                up_item = QTreeWidgetItem(["..", "", "", "dir"])
                up_item.setIcon(0, self.icon_folder)
                up_item.setData(0, Qt.ItemDataRole.UserRole, {"is_dir": True, "is_up": True})
                self.remote_tree.addTopLevelItem(up_item)

            # Prefer MLSD if supported
            lines = []
            use_mlsd = getattr(self.ftp, 'supports_mlsd', False)
            if use_mlsd:
                 try:
                      self.log("Using MLSD for directory listing.", "debug")
                      # mlsd() yields lines directly
                      lines = list(self.ftp.mlsd(self.current_remote_dir, facts=["type", "size", "modify"]))
                 except ftplib.all_errors as mlsd_err:
                      self.log(f"MLSD failed ({mlsd_err}), falling back to LIST.", "warning")
                      use_mlsd = False # Fallback to LIST

            if not use_mlsd:
                 self.log("Using LIST for directory listing.", "debug")
                 # LIST requires callback to collect lines
                 self.ftp.dir(self.current_remote_dir, lines.append)

            # Process the collected lines
            for line in lines:
                 # self.log(f"Raw line: {line}", "debug") # Verbose debug
                 parsed_info = self.parse_ftp_line(line, use_mlsd)
                 if parsed_info:
                     tree_item = QTreeWidgetItem([
                         parsed_info["name"],
                         parsed_info["size_str"],
                         parsed_info["modified"],
                         parsed_info["type"]
                     ])
                     is_dir = parsed_info["type"] == "dir"
                     tree_item.setIcon(0, self.icon_folder if is_dir else self.icon_file)
                     tree_item.setData(0, Qt.ItemDataRole.UserRole, {
                         "is_dir": is_dir,
                         "is_up": False,
                         "name": parsed_info["name"],
                         "raw_size": parsed_info.get("raw_size") # Store raw size if available
                     })
                     self.remote_tree.addTopLevelItem(tree_item)

            self.remote_tree.sortItems(0, Qt.SortOrder.AscendingOrder) # Sort by name

        except ftplib.all_errors as e:
            self.log(f"Error listing remote directory: {e}", "error")
            QMessageBox.critical(self, "Remote Error", f"Could not list directory:\n{self.current_remote_dir}\n\n{e}")
            # Maybe disconnect or clear tree?
            # self.disconnect_ftp() # Drastic
            self.remote_tree.clear()
        finally:
            self.update_ui_state() # Re-enable refresh button


    def parse_ftp_line(self, line, using_mlsd):
        """ Parses a line from MLSD or LIST output. Very basic. """
        if not line: return None
        name = ""
        size_str = ""
        raw_size = None
        modified = ""
        type_ = "unknown" # file, dir, link, unknown

        try:
            if using_mlsd:
                # MLSD format: "fact=value; fact=value; ... filename"
                parts = line.split(";")
                if len(parts) < 2: return None # Need at least one fact and filename

                filename_part = parts[-1].strip()
                name = filename_part
                facts = {}
                for fact_part in parts[:-1]:
                     if '=' in fact_part:
                          key, value = fact_part.strip().split("=", 1)
                          facts[key.lower()] = value

                type_ = facts.get("type", "unknown") # type can be file, dir, cdir, pdir, etc.
                if type_ in ["dir", "cdir", "pdir"]:
                    type_ = "dir"
                elif type_ == "file":
                     type_ = "file"
                # Add more types if needed (link, etc.)

                if "size" in facts:
                    try:
                         raw_size = int(facts["size"])
                         size_str = format_size(raw_size)
                    except ValueError: pass # Size not an integer
                if "modify" in facts:
                    # MLSD modify format: YYYYMMDDHHMMSS
                    ts = facts["modify"]
                    try:
                         dt = datetime.datetime.strptime(ts, '%Y%m%d%H%M%S')
                         modified = dt.strftime('%Y-%m-%d %H:%M')
                    except ValueError: pass # Invalid date format
            else:
                # Extremely basic LIST parsing (assumes Unix-like format)
                # drwxr-xr-x    1 ftp      ftp          4096 Mar 17 14:42 folder
                # -rw-r--r--    1 ftp      ftp       1024000 Mar 17 14:43 file.zip
                parts = line.split(maxsplit=8)
                if len(parts) < 9: return None # Skip lines that don't fit the pattern

                perms = parts[0]
                size_maybe = parts[4]
                name = parts[8]

                if name in (".", ".."): return None # Skip current/parent dir entries here

                if perms.startswith('d'):
                    type_ = "dir"
                    size_str = "" # Dirs often show size of listing, not content size
                elif perms.startswith('l'):
                    type_ = "link"
                    # Link names often look like 'linkname -> target'
                    if " -> " in name:
                         name = name.split(" -> ")[0]
                    try:
                         raw_size = int(size_maybe)
                         size_str = format_size(raw_size) # Links can have size 0 or size of target
                    except ValueError: size_str = ""
                elif perms.startswith('-'):
                    type_ = "file"
                    try:
                         raw_size = int(size_maybe)
                         size_str = format_size(raw_size)
                    except ValueError:
                        size_str = "?" # Indicate parse error
                        raw_size = None
                else:
                    type_ = "unknown" # Could be block device, char device, etc.
                    size_str = ""

                # Try to parse date (can be complex: 'MMM DD HH:MM' or 'MMM DD YYYY')
                try:
                    month, day, time_or_year = parts[5], parts[6], parts[7]
                    if ":" in time_or_year: # Format: MMM DD HH:MM
                        year = datetime.datetime.now().year # Assume current year
                        dt_str = f"{month} {day} {year} {time_or_year}"
                        dt = datetime.datetime.strptime(dt_str, '%b %d %Y %H:%M')
                    else: # Format: MMM DD YYYY
                        year = time_or_year
                        dt_str = f"{month} {day} {year}"
                        dt = datetime.datetime.strptime(dt_str, '%b %d %Y')
                    modified = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    modified = ' '.join(parts[5:8]) # Fallback to raw string

            return {
                "name": name,
                "size_str": size_str,
                "raw_size": raw_size,
                "modified": modified,
                "type": type_
            }
        except Exception as e:
            self.log(f"Failed to parse FTP line '{line}': {e}", "warning")
            return None


    def on_remote_item_double_clicked(self, item, column):
        if not self.ftp: return
        item_data = item.data(0, Qt.ItemDataRole.UserRole)

        if item_data and item_data.get("is_dir"):
            item_name = item.text(0)
            try:
                if item_data.get("is_up"):
                    self.ftp.cwd("..")
                else:
                    # Need to handle names with spaces correctly.
                    # ftplib's cwd usually handles this, but ensure item_name is correct.
                    self.ftp.cwd(item_name)

                self.current_remote_dir = self.ftp.pwd()
                self.remote_path_entry.setText(self.current_remote_dir)
                self.refresh_remote()
            except ftplib.all_errors as e:
                self.log(f"Error changing remote directory to '{item_name}': {e}", "error")
                QMessageBox.critical(self, "Remote Error", f"Could not change directory:\n{e}")


    def show_remote_context_menu(self, position):
        if not self.ftp: return
        menu = QMenu()
        selected_items = self.remote_tree.selectedItems()
        item_under_cursor = self.remote_tree.itemAt(position)

        has_selection = bool(selected_items)
        is_single_selection = len(selected_items) == 1
        selected_file = False
        selected_dir = False
        selected_name = ""
        if is_single_selection:
            data = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if data and not data.get("is_up", False): # Exclude ".."
                 selected_file = not data.get("is_dir", False)
                 selected_dir = data.get("is_dir", False)
                 selected_name = data.get("name", "")

        # Download Action
        download_action = QAction("Download", self)
        # Enable only if one or more files/dirs are selected (recursive download not yet implemented for dirs)
        can_download = has_selection and not self.transfer_thread # Add check for only files if dirs not supported
        download_action.setEnabled(can_download)
        download_action.triggered.connect(self.download_selected)
        menu.addAction(download_action)

        menu.addSeparator()

        # Delete Action
        delete_action = QAction("Delete", self)
        # Enable if one or more files/dirs selected (excluding '..')
        can_delete = has_selection and not self.transfer_thread and \
                     all(not it.data(0, Qt.ItemDataRole.UserRole).get("is_up", False) for it in selected_items)
        delete_action.setEnabled(can_delete)
        delete_action.triggered.connect(self.delete_remote_selected)
        menu.addAction(delete_action)

        # Rename Action
        rename_action = QAction("Rename", self)
        # Enable only for single file/dir selection (excluding '..')
        can_rename = is_single_selection and (selected_file or selected_dir) and not self.transfer_thread
        rename_action.setEnabled(can_rename)
        rename_action.triggered.connect(self.rename_remote_selected)
        menu.addAction(rename_action)

        menu.addSeparator()

        # Create Directory Action
        create_dir_action = QAction("Create Directory...", self)
        create_dir_action.setEnabled(not self.transfer_thread) # Can always attempt to create dir
        create_dir_action.triggered.connect(self.create_remote_directory)
        menu.addAction(create_dir_action)

        menu.addSeparator()

        # Refresh Action
        refresh_action = QAction("Refresh", self)
        refresh_action.setEnabled(not self.transfer_thread)
        refresh_action.triggered.connect(self.refresh_remote)
        menu.addAction(refresh_action)

        menu.exec(self.remote_tree.viewport().mapToGlobal(position))


    # --- Remote Actions Implementation ---

    def delete_remote_selected(self):
        if not self.ftp: return
        selected_items = self.remote_tree.selectedItems()
        if not selected_items: return

        items_to_delete = []
        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and not data.get("is_up"):
                items_to_delete.append((data["name"], data["is_dir"]))

        if not items_to_delete: return

        item_names = "\n - ".join([name for name, is_dir in items_to_delete])
        reply = QMessageBox.question(self, "Confirm Deletion",
                                     f"Are you sure you want to permanently delete:\n - {item_names}\n\nThis action cannot be undone.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Yes:
            # Disable UI during operation? Maybe not needed for quick ops.
            success_count = 0
            fail_count = 0
            for name, is_dir in items_to_delete:
                try:
                    if is_dir:
                        self.log(f"Deleting remote directory: {name}", "info")
                        self.ftp.rmd(name)
                    else:
                        self.log(f"Deleting remote file: {name}", "info")
                        self.ftp.delete(name)
                    success_count += 1
                except ftplib.all_errors as e:
                    self.log(f"Failed to delete {name}: {e}", "error")
                    fail_count += 1

            self.log(f"Deletion finished. Success: {success_count}, Failed: {fail_count}",
                     "info" if fail_count == 0 else "warning")
            if success_count > 0:
                self.refresh_remote() # Update list if anything was deleted
            if fail_count > 0:
                 QMessageBox.warning(self, "Deletion Errors", f"{fail_count} item(s) could not be deleted. Check log for details.")


    def rename_remote_selected(self):
        if not self.ftp: return
        selected_items = self.remote_tree.selectedItems()
        if len(selected_items) != 1: return # Only single rename supported

        item = selected_items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("is_up"): return # Cannot rename ".."

        old_name = data["name"]

        new_name, ok = QInputDialog.getText(self, "Rename Item",
                                            f"Enter new name for '{old_name}':",
                                            QLineEdit.EchoMode.Normal,
                                            old_name) # Pre-fill with old name

        if ok and new_name and new_name != old_name:
            new_name = new_name.strip()
            if not new_name:
                QMessageBox.warning(self,"Rename Error", "New name cannot be empty.")
                return
            if "/" in new_name or "\\" in new_name: # Basic check for invalid chars
                 QMessageBox.warning(self,"Rename Error", "New name cannot contain slashes.")
                 return

            try:
                self.log(f"Renaming '{old_name}' to '{new_name}'...", "info")
                self.ftp.rename(old_name, new_name)
                self.log("Rename successful.", "success")
                self.refresh_remote()
            except ftplib.all_errors as e:
                self.log(f"Failed to rename '{old_name}': {e}", "error")
                QMessageBox.critical(self, "Rename Failed", f"Could not rename item:\n{e}")


    def create_remote_directory(self):
        if not self.ftp: return

        dir_name, ok = QInputDialog.getText(self, "Create Directory",
                                            "Enter name for the new directory:")

        if ok and dir_name:
            dir_name = dir_name.strip()
            if not dir_name:
                QMessageBox.warning(self,"Input Error", "Directory name cannot be empty.")
                return
            if "/" in dir_name or "\\" in dir_name:
                 QMessageBox.warning(self,"Input Error", "Directory name cannot contain slashes.")
                 return

            try:
                self.log(f"Creating remote directory: {dir_name}", "info")
                self.ftp.mkd(dir_name)
                self.log("Directory created successfully.", "success")
                self.refresh_remote()
            except ftplib.all_errors as e:
                self.log(f"Failed to create directory '{dir_name}': {e}", "error")
                QMessageBox.critical(self, "Creation Failed", f"Could not create directory:\n{e}")


    # --- Transfer Handling ---
    def start_transfer(self, action, local_item, remote_item_name):
         """Initiates upload or download worker."""
         if self.transfer_thread and self.transfer_thread.isRunning():
             QMessageBox.warning(self, "Busy", "Another transfer is already in progress.")
             return

         if not self.ftp:
             self.log("Cannot transfer: Not connected.", "warning")
             return

         local_data = local_item.data(0, Qt.ItemDataRole.UserRole) if local_item else None

         if action == 'upload':
             if not local_data or local_data.get("is_dir") or local_data.get("is_up"):
                 self.log("Invalid item selected for upload.", "warning")
                 return
             local_path = local_data["full_path"]
             remote_path = remote_item_name # Use name directly for remote path in current dir
             filename = os.path.basename(local_path)
         elif action == 'download':
             # For download, local_item is the *target* directory, remote_item_name is the file
             remote_data = None
             # Find the remote item to get its data (e.g., is_dir)
             for i in range(self.remote_tree.topLevelItemCount()):
                 item = self.remote_tree.topLevelItem(i)
                 if item.text(0) == remote_item_name:
                     remote_data = item.data(0, Qt.ItemDataRole.UserRole)
                     break

             if not remote_data or remote_data.get("is_dir") or remote_data.get("is_up"):
                 self.log("Invalid item selected for download.", "warning")
                 return
             local_path = os.path.join(self.current_local_dir, remote_item_name)
             remote_path = remote_item_name
             filename = remote_item_name
         else:
             self.log(f"Unknown transfer action: {action}", "error")
             return

         # Check if local file exists for download and ask to overwrite
         if action == 'download' and os.path.exists(local_path):
             reply = QMessageBox.question(self, "Confirm Overwrite",
                                          f"The file '{filename}' already exists locally.\nOverwrite?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
             if reply == QMessageBox.StandardButton.Cancel:
                 self.log("Download cancelled by user.", "info")
                 return

         self.transfer_label.setText(f"{action.capitalize()}ing {filename}...")
         self.transfer_progress.setValue(0)

         # Setup worker and thread
         self.transfer_thread = QThread(self)
         self.transfer_worker = TransferWorker(self.ftp, action, local_path, remote_path)
         self.transfer_worker.moveToThread(self.transfer_thread)

         # Connect signals
         self.transfer_worker.progress.connect(self.on_transfer_progress)
         self.transfer_worker.finished.connect(self.on_transfer_finished)
         self.transfer_worker.error.connect(self.on_transfer_error)
         self.transfer_worker.log_message.connect(self.log)
         self.transfer_thread.started.connect(self.transfer_worker.run)
         self.transfer_thread.finished.connect(self.on_transfer_thread_finished)

         # Start
         self.transfer_thread.start()
         self.update_ui_state()


    def upload_selected(self):
        selected_locals = self.local_tree.selectedItems()
        if not selected_locals:
            QMessageBox.information(self, "Upload", "Please select one or more local files to upload.")
            return
        if not self.ftp:
             QMessageBox.warning(self, "Not Connected", "Please connect to an FTP server first.")
             return

        # Rudimentary queue: process first selected item for now
        # TODO: Implement a proper transfer queue for multiple items
        first_item = selected_locals[0]
        data = first_item.data(0, Qt.ItemDataRole.UserRole)
        if data and not data.get("is_dir") and not data.get("is_up"):
            remote_name = first_item.text(0) # Upload with the same name
            self.start_transfer('upload', first_item, remote_name)
        else:
            self.log("Please select a valid file to upload.", "warning")


    def download_selected(self):
        selected_remotes = self.remote_tree.selectedItems()
        if not selected_remotes:
            QMessageBox.information(self, "Download", "Please select one or more remote files to download.")
            return
        if not self.ftp:
             QMessageBox.warning(self, "Not Connected", "Please connect to an FTP server first.")
             return

        # Rudimentary queue: process first selected item for now
        # TODO: Implement a proper transfer queue for multiple items
        first_item = selected_remotes[0]
        data = first_item.data(0, Qt.ItemDataRole.UserRole)
        if data and not data.get("is_dir") and not data.get("is_up"):
            remote_name = first_item.text(0)
            # Pass None for local item, the function constructs the target path
            self.start_transfer('download', None, remote_name)
        else:
            self.log("Please select a valid file to download.", "warning")

    @pyqtSlot(int)
    def on_transfer_progress(self, percent):
        self.transfer_progress.setValue(percent)

    @pyqtSlot(str)
    def on_transfer_finished(self, message):
        self.log(message, "success")
        action = "upload" if "uploaded" in message.lower() else "download"
        if action == 'upload':
            self.refresh_remote() # Update remote list after successful upload
        elif action == 'download':
            self.refresh_local() # Update local list after successful download
        # Transfer completes implicitly via thread finish signal


    @pyqtSlot(str)
    def on_transfer_error(self, error_message):
        self.log(error_message, "error")
        QMessageBox.critical(self, "Transfer Failed", error_message)
        # Reset progress on error, thread finish signal handles cleanup
        self.transfer_progress.setValue(0)
        self.transfer_label.setText("Transfer Failed")

    @pyqtSlot()
    def on_transfer_thread_finished(self):
        self.log("Transfer operation finished.", "debug")
        if self.transfer_thread:
             self.transfer_thread.deleteLater()
             self.transfer_worker.deleteLater()
        self.transfer_thread = None
        self.transfer_worker = None
        self.update_ui_state() # Re-enable buttons, hide progress etc.


    def cancel_transfer(self):
        if self.transfer_worker and self.transfer_thread and self.transfer_thread.isRunning():
            self.log("Attempting to cancel transfer...", "info")
            self.transfer_worker.stop() # Signal the worker to stop
            # Give it a moment, then try quitting thread if needed? Less safe.
            # self.transfer_thread.quit() # Request thread termination
            # self.transfer_thread.wait(1000) # Wait briefly for cleanup
            self.cancel_transfer_btn.setEnabled(False) # Prevent multiple clicks
            # State will update fully when thread finishes


    # --- Network Scan ---
    def scan_network(self):
        if self.scan_thread and self.scan_thread.isRunning():
             QMessageBox.information(self, "Scan in Progress", "A network scan is already running.")
             return

        network_range = self.network_entry.text().strip()
        if not network_range:
            QMessageBox.warning(self, "Input Error", "Please enter a network range (e.g., 192.168.1.0/24).")
            return

        self.scan_dialog = ScanDialog(self)
        self.scan_dialog.host_selected.connect(self.on_scan_host_selected)

        # Setup worker and thread
        self.scan_thread = QThread(self)
        # Scan common FTP ports: 21 (FTP), 990 (Implicit FTPS - though we only connect Explicit)
        # Add more if needed, e.g., 2121
        ports_to_scan = (21, 990, 2121)
        self.scan_worker = ScanWorker(network_range, ports_to_scan)
        self.scan_worker.moveToThread(self.scan_thread)

        # Connect signals
        self.scan_worker.found.connect(self.scan_dialog.add_result)
        self.scan_worker.progress.connect(self.scan_dialog.update_progress)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_scan_error)
        self.scan_worker.log_message.connect(self.log)
        # Connect cancel button in dialog to worker's stop slot
        self.scan_dialog.button_box.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.scan_worker.stop)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_thread.finished.connect(self.on_scan_thread_finished)

        self.log(f"Starting network scan for {network_range} on ports {ports_to_scan}...", "info")
        self.scan_btn.setEnabled(False) # Disable scan button while scan runs
        self.scan_thread.start()
        self.scan_dialog.exec() # Show dialog modally

        # Dialog closed, ensure thread cleanup if it's still running (e.g., user hit Cancel)
        if self.scan_thread and self.scan_thread.isRunning():
             self.log("Scan dialog closed, requesting scan thread stop...", "debug")
             self.scan_worker.stop()
             # Don't delete thread here, wait for finished signal


    @pyqtSlot(str, str)
    def on_scan_host_selected(self, host, port):
        self.host_entry.setText(host)
        self.port_entry.setText(port)
        self.log(f"Selected {host}:{port} from scan results.", "info")
        # Set TLS based on port? (e.g., default to TLS if port 990 selected - though we dont support implicit)
        # if port == '990': self.tls_combo.setCurrentIndex(1) # Example

    @pyqtSlot(int)
    def on_scan_finished(self, count):
        self.log(f"Network scan finished. Found {count} potential server(s).", "info")
        if self.scan_dialog:
            self.scan_dialog.set_finished(count)


    @pyqtSlot(str)
    def on_scan_error(self, error_message):
        self.log(error_message, "error")
        if self.scan_dialog:
             # Show error in dialog or main window
             QMessageBox.critical(self.scan_dialog, "Scan Error", error_message)
        else:
             QMessageBox.critical(self, "Scan Error", error_message)


    @pyqtSlot()
    def on_scan_thread_finished(self):
        self.log("Scan thread finished.", "debug")
        if self.scan_dialog and self.scan_dialog.isVisible():
             # If the thread finished but dialog is still open (e.g. completed naturally)
             # ensure OK button state is correct.
             self.scan_dialog.set_finished(self.scan_dialog.tree.topLevelItemCount())
             # Don't close it automatically here, user might still want to select.
             pass

        if self.scan_thread:
             self.scan_thread.deleteLater()
             self.scan_worker.deleteLater()
        self.scan_thread = None
        self.scan_worker = None
        self.scan_btn.setEnabled(True) # Re-enable scan button


    # --- Window Closing ---
    def closeEvent(self, event):
        """ Handle window close: disconnect, stop threads. """
        if self.transfer_thread and self.transfer_thread.isRunning():
            reply = QMessageBox.question(self, "Transfer Active",
                                         "A file transfer is in progress. Quit anyway?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                         QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            else:
                 # Try to stop worker gracefully
                 if self.transfer_worker: self.transfer_worker.stop()

        if self.scan_thread and self.scan_thread.isRunning():
            # Stop scan worker too
            if self.scan_worker: self.scan_worker.stop()
            # Maybe wait briefly? Or just proceed with disconnect.

        # Disconnect if connected
        if self.ftp:
            self.disconnect_ftp() # This uses a timer, might not finish immediately
            # Force clear ftp object here for safety on close
            self.ftp = None

        # Clean up any remaining thread objects (should be handled by finished signals ideally)
        for thread in [self.connect_thread, self.transfer_thread, self.scan_thread]:
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(500) # Wait briefly

        event.accept()


# --- Main Execution ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Apply the stylesheet globally
    # app.setStyleSheet(STYLESHEET) # Applied within window for better inheritance control

    # Increase default font size slightly if desired
    # font = QFont()
    # font.setPointSize(10)
    # app.setFont(font)

    window = FTPClientWindow()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE ftpc_pyqt.py ---