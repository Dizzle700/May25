import sys
import subprocess
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QFileDialog, QVBoxLayout, QCheckBox,
    QWidget, QMessageBox, QFrame, QTextEdit, QLineEdit, QHBoxLayout, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFontDatabase

# --- Worker Thread for Running PyInstaller ---
class BuildThread(QThread):
    """
    Runs the PyInstaller command in a separate thread to keep the UI responsive.
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # Signal for completion: success (bool), message (str)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            # Start the subprocess
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            # Read output in real-time
            for line in iter(process.stdout.readline, ''):
                self.progress.emit(line.strip())

            process.stdout.close()
            return_code = process.wait()

            if return_code == 0:
                self.finished.emit(True, "Build successful!")
            else:
                self.finished.emit(False, f"Build failed with return code {return_code}.")

        except FileNotFoundError:
            self.finished.emit(False, "Error: 'pyinstaller' not found. Is it installed and in your system's PATH?")
        except Exception as e:
            self.finished.emit(False, f"An unexpected error occurred: {e}")


# --- Main Application Window ---
class PyInstallerWrapper(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyInstaller GUI")
        self.setWindowIcon(QIcon("app_icon.ico")) # Suggest adding an icon for the app itself

        self.file_path = ""
        self.icon_path = ""
        self.output_dir = ""

        # --- UI Elements ---
        self.create_widgets()
        self.setup_layout()
        self.apply_modern_dark_theme()

        # --- Connections ---
        self.btn_select_file.clicked.connect(self.select_file)
        self.btn_select_icon.clicked.connect(self.select_icon)
        self.btn_select_output.clicked.connect(self.select_output_dir)
        self.btn_build.clicked.connect(self.build_exe)

        self.update_build_button_state()

    def create_widgets(self):
        """Initializes all UI widgets."""
        # File Selection
        self.file_group = QGroupBox("Input File")
        self.label_file = QLabel("No Python script selected.")
        self.btn_select_file = QPushButton("Select Script")

        # Build Options
        self.options_group = QGroupBox("Build Options")
        self.checkbox_onefile = QCheckBox("Single File Executable (--onefile)")
        self.checkbox_noconsole = QCheckBox("Windowed Application (--noconsole)")
        self.checkbox_clean = QCheckBox("Clean Build (--clean)")
        self.checkbox_onefile.setChecked(True)
        self.checkbox_noconsole.setChecked(True)
        
        # Naming and Icon
        self.naming_group = QGroupBox("Branding")
        self.label_app_name = QLabel("Executable Name:")
        self.edit_app_name = QLineEdit()
        self.edit_app_name.setPlaceholderText("Leave empty to use script name")
        self.label_icon = QLabel("No icon selected.")
        self.btn_select_icon = QPushButton("Select Icon (.ico)")
        
        # Output
        self.output_group = QGroupBox("Output")
        self.label_output_dir = QLabel("Default (dist/)")
        self.btn_select_output = QPushButton("Select Output Folder")
        self.btn_open_output = QPushButton("Open Output Folder")
        self.btn_open_output.setEnabled(False)
        self.btn_open_output.clicked.connect(self.open_output_folder)


        # Build & Log
        self.build_group = QGroupBox("Build")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Build logs will appear here...")
        self.btn_build = QPushButton("Build Executable")

    def setup_layout(self):
        """Creates the layout and adds widgets."""
        # --- Layouts ---
        main_layout = QVBoxLayout()
        file_layout = QHBoxLayout()
        options_layout = QVBoxLayout()
        naming_layout = QVBoxLayout()
        icon_layout = QHBoxLayout()
        output_layout = QVBoxLayout()
        output_buttons_layout = QHBoxLayout()
        build_layout = QVBoxLayout()
        
        # --- File Selection ---
        file_layout.addWidget(self.label_file, 1)
        file_layout.addWidget(self.btn_select_file)
        self.file_group.setLayout(file_layout)
        
        # --- Build Options ---
        options_layout.addWidget(self.checkbox_onefile)
        options_layout.addWidget(self.checkbox_noconsole)
        options_layout.addWidget(self.checkbox_clean)
        self.options_group.setLayout(options_layout)
        
        # --- Naming and Icon ---
        icon_layout.addWidget(self.label_icon, 1)
        icon_layout.addWidget(self.btn_select_icon)
        naming_layout.addWidget(self.label_app_name)
        naming_layout.addWidget(self.edit_app_name)
        naming_layout.addLayout(icon_layout)
        self.naming_group.setLayout(naming_layout)
        
        # --- Output ---
        output_buttons_layout.addWidget(self.label_output_dir, 1)
        output_buttons_layout.addWidget(self.btn_select_output)
        output_layout.addLayout(output_buttons_layout)
        output_layout.addWidget(self.btn_open_output)
        self.output_group.setLayout(output_layout)

        # --- Build & Log ---
        build_layout.addWidget(self.log_output)
        build_layout.addWidget(self.btn_build)
        self.build_group.setLayout(build_layout)
        
        # --- Add groups to main layout ---
        main_layout.addWidget(self.file_group)
        main_layout.addWidget(self.options_group)
        main_layout.addWidget(self.naming_group)
        main_layout.addWidget(self.output_group)
        main_layout.addWidget(self.build_group, 1) # Give log area more space

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def apply_modern_dark_theme(self):
        """Applies a refined dark theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2f;
            }
            QWidget {
                background-color: #1e1e2f;
                color: #dcdce0;
                font-family: 'Segoe UI', 'Roboto', 'Helvetica', sans-serif;
                font-size: 10pt;
            }
            QGroupBox {
                background-color: #28283f;
                border: 1px solid #44475a;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
                background-color: #44475a;
                border-radius: 4px;
                color: #f8f8f2;
            }
            QLabel {
                background-color: transparent;
                padding: 4px;
            }
            QPushButton {
                background-color: #44475a;
                color: #f8f8f2;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #5a5d72;
            }
            QPushButton:pressed {
                background-color: #3a3d52;
            }
            QPushButton:disabled {
                background-color: #2a2d42;
                color: #777;
            }
            QCheckBox {
                spacing: 10px;
                padding: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QLineEdit, QTextEdit {
                background-color: #28283f;
                border: 1px solid #44475a;
                border-radius: 6px;
                padding: 6px;
                color: #f8f8f2;
            }
            QScrollBar:vertical {
                border: none;
                background: #28283f;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #5a5d72;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def update_build_button_state(self):
        """Disables the build button if no Python script is selected."""
        self.btn_build.setEnabled(bool(self.file_path))

    def select_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Python Script", "", "Python Files (*.py *.pyw)")
        if file:
            self.file_path = file
            self.label_file.setText(os.path.basename(file))
        self.update_build_button_state()

    def select_icon(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Icon", "", "Icon Files (*.ico)")
        if file:
            self.icon_path = file
            self.label_icon.setText(os.path.basename(file))

    def select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir = directory
            self.label_output_dir.setText(os.path.basename(directory))
            self.btn_open_output.setEnabled(True)

    def open_output_folder(self):
        """Opens the specified output folder in the file explorer."""
        if self.output_dir and os.path.isdir(self.output_dir):
            os.startfile(self.output_dir)
        else:
            QMessageBox.warning(self, "Warning", "Output directory does not exist.")

    def build_exe(self):
        if not self.file_path:
            QMessageBox.warning(self, "Error", "Please select a Python script first!")
            return

        # --- Construct the PyInstaller command ---
        cmd = ["pyinstaller", "--noconfirm"]

        if self.checkbox_onefile.isChecked():
            cmd.append("--onefile")
        if self.checkbox_noconsole.isChecked():
            cmd.append("--noconsole")
        if self.checkbox_clean.isChecked():
            cmd.append("--clean")

        if self.edit_app_name.text():
            cmd.extend(["--name", self.edit_app_name.text()])
        
        if self.icon_path:
            cmd.extend(["--icon", self.icon_path])
        
        if self.output_dir:
            cmd.extend(["--distpath", self.output_dir])
            cmd.extend(["--specpath", os.path.join(self.output_dir, "spec")]) # Keep spec files tidy
            
        cmd.append(self.file_path)

        # --- Run the build in a separate thread ---
        self.log_output.clear()
        self.log_output.append("Starting build...\n")
        self.log_output.append(f"Command: {' '.join(cmd)}\n" + "="*40)
        
        self.btn_build.setEnabled(False)
        self.btn_build.setText("Building...")
        
        self.build_thread = BuildThread(cmd)
        self.build_thread.progress.connect(self.log_output.append)
        self.build_thread.finished.connect(self.on_build_finished)
        self.build_thread.start()

    def on_build_finished(self, success, message):
        """Handles the completion of the build process."""
        self.log_output.append("\n" + "="*40 + f"\n{message}")
        self.btn_build.setEnabled(True)
        self.btn_build.setText("Build Executable")

        if success:
            QMessageBox.information(self, "Success", "The build completed successfully!")
            self.btn_open_output.setEnabled(bool(self.output_dir))
        else:
            QMessageBox.critical(self, "Build Failed", f"The build process failed.\n\nDetails: {message}\n\nCheck the log for more information.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # It's good practice to check if a font exists before using it
    # QFontDatabase.addApplicationFont("path/to/your/font.ttf") 
    window = PyInstallerWrapper()
    window.resize(600, 700)
    window.show()
    sys.exit(app.exec())