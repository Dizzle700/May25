# --- training_modular_v3.py ---
# This version refactors the original script into a modular, single-file structure
# for better readability, maintainability, and functionality.

import sys
import os
import subprocess
import importlib.util
from pathlib import Path
import re
import json
import platform
import shlex
import csv
from enum import Enum, auto
from dataclasses import dataclass, field

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QTextEdit, QMessageBox,
    QFormLayout, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QProgressBar, QDoubleSpinBox, QCheckBox, QGroupBox
)
from PyQt6.QtCore import QProcess, Qt, QTimer, QFileSystemWatcher, QUrl, QObject, pyqtSignal
from PyQt6.QtGui import QDesktopServices

# --- Constants and Configuration ---

DARK_STYLESHEET = """
QWidget { background-color: #2e2e2e; color: #e0e0e0; font-size: 10pt; }
QPushButton { background-color: #555555; border: 1px solid #777777; padding: 5px 10px; border-radius: 4px; min-width: 80px; }
QPushButton:hover { background-color: #666666; border: 1px solid #888888; }
QPushButton:pressed { background-color: #444444; }
QPushButton:disabled { background-color: #404040; color: #777777; border: 1px solid #555555; }
QLineEdit, QSpinBox, QComboBox, QTextEdit, QDoubleSpinBox { background-color: #3c3c3c; border: 1px solid #555555; padding: 4px; border-radius: 3px; color: #e0e0e0; }
QLineEdit[invalid="true"] { background-color: #583333; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; border-left: 1px solid #555555; background-color: #444444; }
QComboBox::drop-down { border: none; background-color: #555555; }
QComboBox::down-arrow { width: 12px; height: 12px; }
QComboBox:editable { background-color: #3c3c3c; }
QLabel { padding-top: 4px; }
QTextEdit { font-family: Consolas, Courier New, monospace; background-color: #252525; }
QStatusBar { font-size: 9pt; color: #aaaaaa; }
QTableWidget { background-color: #3c3c3c; alternate-background-color: #444444; border: 1px solid #555555; gridline-color: #555555; color: #e0e0e0; }
QTableWidget QHeaderView::section { background-color: #555555; padding: 4px; border: 1px solid #666666; font-weight: bold; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #555555; border-radius: 3px; padding: 5px; }
QTabBar::tab { background-color: #444444; border: 1px solid #555555; padding: 6px 10px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; color: #e0e0e0; }
QTabBar::tab:selected { background-color: #555555; }
QTabBar::tab:hover { background-color: #666666; }
QProgressBar { border: 1px solid #555555; border-radius: 3px; text-align: center; background-color: #3c3c3c; color: #e0e0e0; }
QProgressBar::chunk { background-color: #0078d7; border-radius: 3px; }
QGroupBox { border: 1px solid #555555; margin-top: 10px; padding-top: 10px; border-radius: 4px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; color: #aaaaaa; }
QCheckBox { padding-top: 3px; }
"""

DEFAULT_PROJECT_NAME = "runs/train"
DEFAULT_EXP_NAME = "exp"
CONFIG_FILE_FILTER = "JSON Config Files (*.json)"
RESULTS_CSV_FILENAME = "results.csv"

# --- State Management ---

class AppState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()

@dataclass
class AppSettings:
    """Dataclass to hold all training configuration from the GUI."""
    # Basic
    data_yaml: str = ""
    model: str = "yolov8s.pt"
    resume: bool = False
    epochs: int = 100
    imgsz: int = 640
    batch: int = 16
    project: str = DEFAULT_PROJECT_NAME
    name: str = DEFAULT_EXP_NAME
    # Advanced
    optimizer: str = "auto"
    lr0: float = 0.01
    patience: int = 50
    mosaic: bool = True
    mixup: bool = False
    degrees: float = 0.0
    translate: float = 0.1
    scale: float = 0.5
    fliplr: float = 0.5
    additional_args: str = ""
    # Environment
    python_executable: str = ""
    device: str = "cpu"

# --- Helper Functions and Classes ---

def find_python_executable():
    """Finds a suitable Python executable, prioritizing virtual environments."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    common_venv_paths = [
        os.path.join(script_dir, "venv", "Scripts", "python.exe"),
        os.path.join(script_dir, "venv", "bin", "python"),
        os.path.join(script_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(script_dir, ".venv", "bin", "python"),
    ]
    for venv_python in common_venv_paths:
        if os.path.exists(venv_python):
            return venv_python
    return sys.executable

def check_ultralytics_install(python_exe: str) -> tuple[bool, str]:
    """Checks if ultralytics is installed and runnable in the target environment."""
    if not python_exe or not Path(python_exe).is_file():
        return False, "Python executable not found."

    check_process = QProcess()
    check_process.setProgram(python_exe)
    check_process.setArguments(["-c", "import ultralytics; from ultralytics.utils import checks; checks.collect_system_info()"])
    check_process.start()
    check_process.waitForFinished(5000)

    if check_process.exitStatus() != QProcess.ExitStatus.NormalExit or check_process.exitCode() != 0:
        err = check_process.readAllStandardError().data().decode(errors='ignore').strip()
        return False, f"Check failed. Stderr: {err}"
    return True, "Ultralytics check OK."

# --- Backend Logic: CSV Parser and Process Handler ---

class ResultsCsvParser(QObject):
    """Parses results.csv incrementally and robustly."""
    new_rows_parsed = pyqtSignal(list) # Emits a list of dictionaries

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reset()

    def reset(self):
        self.headers = []
        self.processed_row_count = 0

    def parse_file(self, filepath: Path):
        """Parses the given CSV file from the last known position."""
        if not filepath.exists():
            return

        new_rows_data = []
        try:
            with open(filepath, 'r', newline='', encoding='utf-8') as f:
                # Skip rows we've already processed
                for _ in range(self.processed_row_count):
                    next(f, None)

                # Use DictReader for robust, header-based parsing
                reader = csv.DictReader(f)
                if not self.headers:
                    self.headers = reader.fieldnames or []

                for row in reader:
                    new_rows_data.append(row)

                if new_rows_data:
                    self.processed_row_count += len(new_rows_data)
                    self.new_rows_parsed.emit(new_rows_data)

        except Exception as e:
            print(f"[CSV Parser Error] Failed to parse {filepath}: {e}")

class TrainingProcessHandler(QObject):
    """Manages the lifecycle of the YOLO training QProcess."""
    process_started = pyqtSignal()
    process_finished = pyqtSignal(int, QProcess.ExitStatus)
    std_out_received = pyqtSignal(str)
    std_err_received = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.finished.connect(lambda: self.process_finished.emit(self.process.exitCode(), self.process.exitStatus()))
        self.is_paused = False

    def start(self, settings: AppSettings):
        """Builds the command and starts the training process."""
        model_path = settings.model.replace(os.sep, '/')
        train_args = [
            f"data=r'{settings.data_yaml.replace(os.sep, '/')}'",
            f"epochs={settings.epochs}", f"imgsz={settings.imgsz}", f"batch={settings.batch}",
            f"device='{settings.device}'", f"project=r'{settings.project}'", f"name=r'{settings.name}'",
            f"patience={settings.patience}", f"lr0={settings.lr0}", f"degrees={settings.degrees}",
            f"translate={settings.translate}", f"scale={settings.scale}", f"fliplr={settings.fliplr}",
            f"mosaic={1.0 if settings.mosaic else 0.0}", f"mixup={0.1 if settings.mixup else 0.0}"
        ]
        if settings.resume:
            train_args.append("resume=True")
        if settings.optimizer.lower() != "auto":
            train_args.append(f"optimizer='{settings.optimizer}'")
        
        if settings.additional_args:
            try:
                # Use shlex for robust parsing of args like workers=8, cache='ram'
                parsed_additional_args = shlex.split(settings.additional_args.replace(',', ' '))
                train_args.extend(parsed_additional_args)
            except ValueError as e:
                # This should be caught by a pre-flight check in the main app
                self.std_err_received.emit(f"Error parsing Additional Args: {e}")
                return

        train_params_str = ", ".join(train_args)
        python_code = f"from ultralytics import YOLO; model = YOLO('{model_path}'); model.train({train_params_str})"
        
        self.std_out_received.emit("<b>Starting training with generated code:</b>\n")
        self.std_out_received.emit(f"<code>{python_code}</code>\n<hr>")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.process.setWorkingDirectory(script_dir)
        self.process.setProgram(settings.python_executable)
        self.process.setArguments(["-u", "-c", python_code]) # -u for unbuffered output
        
        self.process.start()
        if self.process.waitForStarted(5000):
            self.process_started.emit()
        else:
            self.std_err_received.emit(f"<b>Process failed to start.</b> Error: {self.process.errorString()}")

    def stop(self):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
            QTimer.singleShot(3000, self._kill_if_running)
    
    def _kill_if_running(self):
        if self.process.state() == QProcess.ProcessState.Running:
            self.std_err_received.emit("Process did not terminate gracefully, killing...")
            self.process.kill()

    def _handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        self.std_out_received.emit(data)

    def _handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        self.std_err_received.emit(data)

# --- GUI Components: Tabs and Widgets ---

class BasicSettingsTab(QWidget):
    """Widget for the 'Basic Settings' tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Data YAML
        self.data_yaml_path_edit = QLineEdit()
        self.data_yaml_path_edit.setPlaceholderText("Select dataset configuration file...")
        self.data_yaml_path_edit.editingFinished.connect(lambda: self._validate_path(self.data_yaml_path_edit))
        browse_data_button = QPushButton("Browse...")
        browse_data_button.clicked.connect(self._browse_data_yaml)
        data_layout = QHBoxLayout()
        data_layout.addWidget(self.data_yaml_path_edit)
        data_layout.addWidget(browse_data_button)
        layout.addRow("Dataset YAML:", data_layout)

        # Model
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.lineEdit().setPlaceholderText("e.g., yolov8s.pt or path/to/model.pt")
        models = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"]
        self.model_combo.addItems(models)
        self.model_combo.setCurrentIndex(1)
        browse_model_button = QPushButton("Browse...")
        browse_model_button.clicked.connect(self._browse_model_pt)
        model_layout = QHBoxLayout()
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(browse_model_button)
        layout.addRow("Base Model:", model_layout)
        
        # Resume Checkbox
        self.resume_checkbox = QCheckBox("Resume from last checkpoint")
        self.resume_checkbox.setToolTip("If checked, training will resume from 'last.pt' in the experiment folder.")
        layout.addRow("", self.resume_checkbox)

        # Other settings
        self.epochs_spinbox = QSpinBox()
        self.epochs_spinbox.setRange(1, 10000); self.epochs_spinbox.setValue(100)
        layout.addRow("Epochs:", self.epochs_spinbox)

        self.imgsz_spinbox = QSpinBox()
        self.imgsz_spinbox.setRange(32, 8192); self.imgsz_spinbox.setSingleStep(32); self.imgsz_spinbox.setValue(640)
        self.imgsz_spinbox.setToolTip("Must be divisible by 32")
        layout.addRow("Image Size (imgsz):", self.imgsz_spinbox)

        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(-1, 1024); self.batch_spinbox.setValue(16)
        self.batch_spinbox.setToolTip("Set to -1 for auto-batch")
        layout.addRow("Batch Size:", self.batch_spinbox)

        self.project_edit = QLineEdit(DEFAULT_PROJECT_NAME)
        layout.addRow("Project Name:", self.project_edit)

        self.name_edit = QLineEdit(DEFAULT_EXP_NAME)
        layout.addRow("Experiment Name:", self.name_edit)
        
    def _validate_path(self, line_edit: QLineEdit):
        path_str = line_edit.text()
        is_valid = not path_str or Path(path_str).exists()
        line_edit.setProperty("invalid", not is_valid)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)

    def _browse_data_yaml(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Dataset YAML File", "", "YAML Files (*.yaml *.yml)")
        if filename: self.data_yaml_path_edit.setText(filename); self._validate_path(self.data_yaml_path_edit)

    def _browse_model_pt(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Model File", "", "PyTorch Model Files (*.pt)")
        if filename: self.model_combo.setCurrentText(filename)

    def get_settings(self) -> dict:
        return {
            "data_yaml": self.data_yaml_path_edit.text(),
            "model": self.model_combo.currentText(),
            "resume": self.resume_checkbox.isChecked(),
            "epochs": self.epochs_spinbox.value(),
            "imgsz": self.imgsz_spinbox.value(),
            "batch": self.batch_spinbox.value(),
            "project": self.project_edit.text(),
            "name": self.name_edit.text()
        }
    
    def set_settings(self, settings: dict):
        self.data_yaml_path_edit.setText(settings.get("data_yaml", ""))
        self.model_combo.setCurrentText(settings.get("model", "yolov8s.pt"))
        self.resume_checkbox.setChecked(settings.get("resume", False))
        self.epochs_spinbox.setValue(settings.get("epochs", 100))
        self.imgsz_spinbox.setValue(settings.get("imgsz", 640))
        self.batch_spinbox.setValue(settings.get("batch", 16))
        self.project_edit.setText(settings.get("project", DEFAULT_PROJECT_NAME))
        self.name_edit.setText(settings.get("name", DEFAULT_EXP_NAME))
        self._validate_path(self.data_yaml_path_edit)


class AdvancedSettingsTab(QWidget):
    """Widget for the 'Advanced Hyperparameters' tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.optimizer_combo = QComboBox()
        self.optimizer_combo.addItems(["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp"])
        layout.addRow("Optimizer:", self.optimizer_combo)

        self.lr0_spinbox = QDoubleSpinBox()
        self.lr0_spinbox.setRange(0.0, 1.0); self.lr0_spinbox.setDecimals(5); self.lr0_spinbox.setSingleStep(0.001); self.lr0_spinbox.setValue(0.01)
        layout.addRow("Learning Rate (lr0):", self.lr0_spinbox)

        self.patience_spinbox = QSpinBox()
        self.patience_spinbox.setRange(0, 1000); self.patience_spinbox.setValue(50)
        self.patience_spinbox.setToolTip("Epochs to wait for no improvement before stopping (0 to disable)")
        layout.addRow("Patience:", self.patience_spinbox)

        aug_group = QGroupBox("Augmentation Parameters")
        aug_layout = QFormLayout(aug_group)
        self.mosaic_checkbox = QCheckBox("Enable Mosaic"); self.mosaic_checkbox.setChecked(True)
        aug_layout.addRow(self.mosaic_checkbox)
        self.mixup_checkbox = QCheckBox("Enable MixUp"); self.mixup_checkbox.setChecked(False)
        aug_layout.addRow(self.mixup_checkbox)
        self.degrees_spinbox = QDoubleSpinBox(); self.degrees_spinbox.setRange(0.0, 180.0); self.degrees_spinbox.setValue(0.0)
        aug_layout.addRow("Degrees (+/-):", self.degrees_spinbox)
        self.translate_spinbox = QDoubleSpinBox(); self.translate_spinbox.setRange(0.0, 0.9); self.translate_spinbox.setDecimals(3); self.translate_spinbox.setValue(0.1)
        aug_layout.addRow("Translate (+/-):", self.translate_spinbox)
        self.scale_spinbox = QDoubleSpinBox(); self.scale_spinbox.setRange(0.0, 1.0); self.scale_spinbox.setDecimals(3); self.scale_spinbox.setValue(0.5)
        aug_layout.addRow("Scale (+/-):", self.scale_spinbox)
        self.fliplr_spinbox = QDoubleSpinBox(); self.fliplr_spinbox.setRange(0.0, 1.0); self.fliplr_spinbox.setDecimals(2); self.fliplr_spinbox.setValue(0.5)
        aug_layout.addRow("Flip L/R Prob:", self.fliplr_spinbox)
        layout.addRow(aug_group)

        self.additional_args_edit = QLineEdit()
        self.additional_args_edit.setPlaceholderText("e.g., workers=8 cache='ram'")
        self.additional_args_edit.setToolTip("Space-separated args for model.train(). Use quotes for values with spaces.")
        layout.addRow("Additional Args:", self.additional_args_edit)

    def get_settings(self) -> dict:
        return {
            "optimizer": self.optimizer_combo.currentText(),
            "lr0": self.lr0_spinbox.value(), "patience": self.patience_spinbox.value(),
            "mosaic": self.mosaic_checkbox.isChecked(), "mixup": self.mixup_checkbox.isChecked(),
            "degrees": self.degrees_spinbox.value(), "translate": self.translate_spinbox.value(),
            "scale": self.scale_spinbox.value(), "fliplr": self.fliplr_spinbox.value(),
            "additional_args": self.additional_args_edit.text()
        }

    def set_settings(self, settings: dict):
        self.optimizer_combo.setCurrentText(settings.get("optimizer", "auto"))
        self.lr0_spinbox.setValue(settings.get("lr0", 0.01))
        self.patience_spinbox.setValue(settings.get("patience", 50))
        self.mosaic_checkbox.setChecked(settings.get("mosaic", True))
        self.mixup_checkbox.setChecked(settings.get("mixup", False))
        self.degrees_spinbox.setValue(settings.get("degrees", 0.0))
        self.translate_spinbox.setValue(settings.get("translate", 0.1))
        self.scale_spinbox.setValue(settings.get("scale", 0.5))
        self.fliplr_spinbox.setValue(settings.get("fliplr", 0.5))
        self.additional_args_edit.setText(settings.get("additional_args", ""))

class EnvironmentTab(QWidget):
    """Widget for the 'Environment' tab."""
    def __init__(self, initial_python_path: str, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Python Path
        self.python_path_edit = QLineEdit(initial_python_path)
        self.python_path_edit.editingFinished.connect(lambda: self._validate_path(self.python_path_edit))
        browse_python_button = QPushButton("Browse...")
        browse_python_button.clicked.connect(self._browse_python)
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_path_edit)
        python_layout.addWidget(browse_python_button)
        layout.addRow("Python Executable:", python_layout)

        # Device
        self.device_combo = QComboBox()
        devices = ["cpu"]
        default_device_index = 0
        try:
            if importlib.util.find_spec("torch") and __import__("torch").cuda.is_available():
                for i in range(__import__("torch").cuda.device_count()): devices.append(f"{i}")
                if len(devices) > 1: default_device_index = 1
        except Exception: pass
        self.device_combo.addItems(devices)
        self.device_combo.setCurrentIndex(default_device_index)
        layout.addRow("Device:", self.device_combo)

        # Exp Path
        self.exp_path_label = QLabel("...")
        self.exp_path_label.setWordWrap(True)
        layout.addRow("Expected Exp. Path:", self.exp_path_label)

        self.open_exp_folder_button = QPushButton("Open Experiment Folder")
        self.open_exp_folder_button.setEnabled(False)
        layout.addRow(self.open_exp_folder_button)

    def _validate_path(self, line_edit: QLineEdit):
        path_str = line_edit.text()
        is_valid = not path_str or Path(path_str).is_file()
        line_edit.setProperty("invalid", not is_valid)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)
        
    def _browse_python(self):
        exe_filter = "Python Executable (python.exe)" if platform.system() == "Windows" else "Python Executable (python)"
        filename, _ = QFileDialog.getOpenFileName(self, "Select Python Executable", "", f"{exe_filter};;All Files (*)")
        if filename: self.python_path_edit.setText(filename); self._validate_path(self.python_path_edit)

    def get_settings(self) -> dict:
        return {
            "python_executable": self.python_path_edit.text(),
            "device": self.device_combo.currentText()
        }

    def set_settings(self, settings: dict):
        self.python_path_edit.setText(settings.get("python_executable", find_python_executable()))
        self.device_combo.setCurrentText(settings.get("device", "cpu"))
        self._validate_path(self.python_path_edit)
        
# --- Main Application Window ---

class YoloTrainerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO Trainer GUI (Modular v3)")
        self.setGeometry(100, 100, 1000, 900)

        # State and Backend
        self.app_state = AppState.IDLE
        self.settings = AppSettings()
        self.current_experiment_path = None
        self.total_epochs = 1

        self.process_handler = TrainingProcessHandler(self)
        self.csv_parser = ResultsCsvParser(self)
        self.fs_watcher = QFileSystemWatcher(self)

        # UI
        self._init_ui()
        self._connect_signals()
        self._set_state(AppState.IDLE)
        
        self.setStyleSheet(DARK_STYLESHEET)
        self.check_initial_dependencies()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # Config Buttons
        config_button_layout = QHBoxLayout()
        self.save_config_button = QPushButton("Save Config")
        self.load_config_button = QPushButton("Load Config")
        config_button_layout.addStretch()
        config_button_layout.addWidget(self.save_config_button)
        config_button_layout.addWidget(self.load_config_button)
        self.main_layout.addLayout(config_button_layout)

        # Settings Tabs
        self.settings_tabs = QTabWidget()
        self.basic_tab = BasicSettingsTab()
        self.advanced_tab = AdvancedSettingsTab()
        self.env_tab = EnvironmentTab(initial_python_path=find_python_executable())
        self.settings_tabs.addTab(self.basic_tab, "Basic Settings")
        self.settings_tabs.addTab(self.advanced_tab, "Advanced Hyperparameters")
        self.settings_tabs.addTab(self.env_tab, "Environment")
        self.main_layout.addWidget(self.settings_tabs)

        # Action Buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Training")
        self.stop_button = QPushButton("Stop Training")
        button_layout.addStretch(); button_layout.addWidget(self.start_button); button_layout.addWidget(self.stop_button); button_layout.addStretch()
        self.main_layout.addLayout(button_layout)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.main_layout.addWidget(self.progress_bar)

        # Output Tabs
        self.output_tabs = QTabWidget()
        self.output_textedit = QTextEdit(); self.output_textedit.setReadOnly(True)
        self.metrics_table = QTableWidget(); self.metrics_table.setAlternatingRowColors(True)
        self.output_tabs.addTab(self.output_textedit, "Output Log")
        self.output_tabs.addTab(self.metrics_table, "Training Metrics")
        self.main_layout.addWidget(self.output_tabs)

        # Status Bar
        self.status_bar = QStatusBar()
        self.main_layout.addWidget(self.status_bar)

    def _connect_signals(self):
        # UI -> Logic
        self.save_config_button.clicked.connect(self.save_config)
        self.load_config_button.clicked.connect(self.load_config)
        self.start_button.clicked.connect(self.start_training)
        self.stop_button.clicked.connect(self.stop_training)
        self.env_tab.open_exp_folder_button.clicked.connect(self.open_experiment_folder)
        
        # Update experiment path display when project/name changes
        self.basic_tab.project_edit.textChanged.connect(self._update_experiment_path_display)
        self.basic_tab.name_edit.textChanged.connect(self._update_experiment_path_display)

        # Logic -> UI
        self.process_handler.process_started.connect(self._on_process_started)
        self.process_handler.process_finished.connect(self._on_process_finished)
        self.process_handler.std_out_received.connect(self._on_stdout)
        self.process_handler.std_err_received.connect(self._on_stderr)
        
        self.fs_watcher.fileChanged.connect(self._on_results_csv_changed)
        self.csv_parser.new_rows_parsed.connect(self._on_new_metrics_data)
        
    def _set_state(self, state: AppState):
        self.app_state = state
        is_idle = state == AppState.IDLE
        is_running = state == AppState.RUNNING
        
        self.settings_tabs.setEnabled(is_idle)
        self.save_config_button.setEnabled(is_idle)
        self.load_config_button.setEnabled(is_idle)
        
        self.start_button.setEnabled(is_idle)
        self.stop_button.setEnabled(not is_idle)
        
        if is_idle:
            self.stop_button.setText("Stop Training")
        elif is_running:
            self.start_button.setText("Running...")

    def check_initial_dependencies(self):
        python_exe = self.env_tab.get_settings()["python_executable"]
        ok, msg = check_ultralytics_install(python_exe)
        self.status_bar.showMessage(msg)
        if not ok:
            QMessageBox.warning(self, "Dependency Check Failed", f"Could not verify Ultralytics installation for:\n{python_exe}\n\n{msg}\nPlease ensure it is installed in the target environment.")

    def _gather_settings(self):
        """Collects all settings from UI tabs into the AppSettings dataclass."""
        basic = self.basic_tab.get_settings()
        adv = self.advanced_tab.get_settings()
        env = self.env_tab.get_settings()
        self.settings = AppSettings(**basic, **adv, **env)
        
    def _validate_inputs(self) -> bool:
        """Performs pre-flight checks before starting training."""
        self._gather_settings()
        s = self.settings
        
        if not s.data_yaml or not Path(s.data_yaml).is_file():
            QMessageBox.warning(self, "Input Error", "Please select a valid dataset YAML file."); return False
        if s.imgsz % 32 != 0:
            QMessageBox.warning(self, "Input Error", f"Image size ({s.imgsz}) must be divisible by 32."); return False
        
        ok, msg = check_ultralytics_install(s.python_executable)
        if not ok:
            QMessageBox.critical(self, "Environment Error", f"Ultralytics check failed for Python executable:\n{s.python_executable}\n\n{msg}"); return False
            
        return True

    def start_training(self):
        if not self._validate_inputs():
            return
            
        # Reset UI for new run
        self.output_textedit.clear()
        self.metrics_table.setRowCount(0)
        self.metrics_table.setColumnCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")
        
        # Reset backend handlers
        self.csv_parser.reset()
        
        # Setup CSV monitoring
        self._update_experiment_path_display()
        if self.current_experiment_path:
            results_csv_path = self.current_experiment_path / RESULTS_CSV_FILENAME
            # Watch the parent directory for file creation
            self.fs_watcher.addPath(str(results_csv_path.parent))
            self.output_textedit.append(f"Monitoring for results in: {results_csv_path.parent}\n")

        # Go!
        self.process_handler.start(self.settings)

    def stop_training(self):
        self._set_state(AppState.STOPPING)
        self.status_bar.showMessage("Stopping training...")
        self.process_handler.stop()

    def _on_process_started(self):
        self._set_state(AppState.RUNNING)
        self.status_bar.showMessage("Training in progress...")
        self.output_tabs.setCurrentWidget(self.output_textedit)
        self.output_textedit.append("Process started successfully...\n")

    def _on_process_finished(self, exit_code, exit_status):
        self._set_state(AppState.IDLE)
        # Final CSV parse
        self._on_results_csv_changed("") 
        
        final_message = ""
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            status_msg = f"Training finished successfully."
            final_message = f"<b>{status_msg}</b>"
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Finished")
            
            # Show path to best model
            best_model_path = self.current_experiment_path / 'weights' / 'best.pt'
            if best_model_path.exists():
                final_message += f"<br>Best model saved to: <code>{best_model_path.resolve()}</code>"
        else:
            status_msg = f"Training stopped or failed (Code: {exit_code})."
            final_message = f"<font color='red'><b>{status_msg}</b></font>"
            self.progress_bar.setFormat(f"Error (Code: {exit_code})")
        
        self.status_bar.showMessage(status_msg)
        self.output_textedit.append(f"<hr>{final_message}")
        
        # Clean up watcher
        if self.fs_watcher.files(): self.fs_watcher.removePaths(self.fs_watcher.files())
        if self.fs_watcher.directories(): self.fs_watcher.removePaths(self.fs_watcher.directories())
        
        # Update UI
        if self.current_experiment_path and self.current_experiment_path.exists():
            self.env_tab.open_exp_folder_button.setEnabled(True)

    def _on_stdout(self, text: str):
        self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
        self.output_textedit.insertPlainText(text)
        self._parse_stdout_for_progress(text)
    
    def _on_stderr(self, text: str):
        self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
        escaped = text.replace('&', '&').replace('<', '<').replace('>', '>')
        self.output_textedit.insertHtml(f"<font color='#FF8C00'>{escaped}</font>")
        if "error" in text.lower() or "traceback" in text.lower():
            self.status_bar.showMessage("Error occurred during training (see output log).")

    def _parse_stdout_for_progress(self, text: str):
        pattern = r"^\s*(\d+)/(\d+)\s+" # e.g., "  1/100 "
        for line in text.split('\n'):
            match = re.search(pattern, line.strip())
            if match:
                current_epoch, total_epochs = map(int, match.groups())
                self.total_epochs = total_epochs
                progress = int((current_epoch / total_epochs) * 100) if total_epochs > 0 else 0
                self.progress_bar.setValue(progress)
                self.progress_bar.setFormat(f"Training - Epoch {current_epoch} / {total_epochs} ({progress}%)")
                return

    def _on_results_csv_changed(self, path_str: str):
        """Triggered by QFileSystemWatcher."""
        if self.current_experiment_path:
            results_csv_path = self.current_experiment_path / RESULTS_CSV_FILENAME
            self.csv_parser.parse_file(results_csv_path)

    def _on_new_metrics_data(self, rows: list[dict]):
        """Updates the metrics table with new data from the CSV parser."""
        if not rows: return

        if self.metrics_table.columnCount() == 0:
            headers = list(rows[0].keys())
            self.metrics_table.setColumnCount(len(headers))
            self.metrics_table.setHorizontalHeaderLabels([h.strip() for h in headers])

        for row_dict in rows:
            row_pos = self.metrics_table.rowCount()
            self.metrics_table.insertRow(row_pos)
            headers = [self.metrics_table.horizontalHeaderItem(i).text() for i in range(self.metrics_table.columnCount())]
            for col, header in enumerate(headers):
                value = row_dict.get(header, "").strip()
                item = QTableWidgetItem(value)
                if col > 0: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.metrics_table.setItem(row_pos, col, item)
        
        self.metrics_table.resizeColumnsToContents()
        self.metrics_table.scrollToBottom()
        
        # Switch to metrics tab and update status bar
        if self.output_tabs.currentWidget() != self.metrics_table:
            self.output_tabs.setCurrentWidget(self.metrics_table)
            
        last_row = rows[-1]
        map50_95 = last_row.get('metrics/mAP50-95(B)')
        if map50_95:
            self.status_bar.showMessage(f"Training... Last mAP50-95: {float(map50_95):.4f}")

    def _update_experiment_path_display(self):
        project = self.basic_tab.project_edit.text().strip()
        name = self.basic_tab.name_edit.text().strip()
        if project and name:
            base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            self.current_experiment_path = base_dir / project / name
            self.env_tab.exp_path_label.setText(str(self.current_experiment_path.resolve()))
            self.env_tab.open_exp_folder_button.setEnabled(True)
        else:
            self.current_experiment_path = None
            self.env_tab.exp_path_label.setText("(Set Project and Experiment Name)")
            self.env_tab.open_exp_folder_button.setEnabled(False)

    def open_experiment_folder(self):
        if self.current_experiment_path:
            if self.current_experiment_path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_experiment_path.resolve())))
            else:
                QMessageBox.warning(self, "Folder Not Found", f"Path does not exist yet:\n{self.current_experiment_path}")

    def save_config(self):
        self._gather_settings()
        filename, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    # Use dataclasses.asdict for easy serialization
                    from dataclasses import asdict
                    json.dump(asdict(self.settings), f, indent=4)
                self.status_bar.showMessage(f"Configuration saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save: {e}")

    def load_config(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                self.basic_tab.set_settings(config_data)
                self.advanced_tab.set_settings(config_data)
                self.env_tab.set_settings(config_data)
                self._update_experiment_path_display()
                self.status_bar.showMessage(f"Configuration loaded from {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load/apply: {e}")

    def closeEvent(self, event):
        if self.app_state != AppState.IDLE:
            reply = QMessageBox.question(self, 'Confirm Exit', "Training is in progress. Stop and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_training()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = YoloTrainerApp()
    window.show()
    sys.exit(app.exec())