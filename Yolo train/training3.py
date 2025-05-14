# --- START OF FILE training_enhanced_v2.py ---

import sys
import os
import subprocess
import importlib.util # For checking module installation
from pathlib import Path
import re             # For parsing progress output
import json           # For saving/loading configuration
import platform       # To check OS
import shlex          # For parsing additional arguments (though might not be needed for model.train style)
import csv            # For parsing results.csv

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QTextEdit, QMessageBox,
    QFormLayout, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QProgressBar, QDoubleSpinBox, QCheckBox, QGroupBox
)
from PyQt6.QtCore import QProcess, Qt, QTimer, QFileSystemWatcher, QUrl
from PyQt6.QtGui import QPalette, QColor, QFont, QDesktopServices

# --- Constants ---
DEFAULT_PROJECT_NAME = "runs/train"
DEFAULT_EXP_NAME = "exp"
CONFIG_FILE_FILTER = "JSON Config Files (*.json)"
RESULTS_CSV_FILENAME = "results.csv" # Common name for Ultralytics results

# --- Dependency Checks (Run early) ---
try:
    import torch
    TORCH_AVAILABLE = True
    CUDA_AVAILABLE = torch.cuda.is_available()
    NUM_CUDA_DEVICES = torch.cuda.device_count() if CUDA_AVAILABLE else 0
except ImportError:
    TORCH_AVAILABLE = False
    CUDA_AVAILABLE = False
    NUM_CUDA_DEVICES = 0

try:
    importlib.util.find_spec("ultralytics")
    ULTRALYTICS_INSTALLED_IN_GUI_ENV = True
except ImportError:
    ULTRALYTICS_INSTALLED_IN_GUI_ENV = False

# --- Styling (Keep the existing dark theme) ---
DARK_STYLESHEET = """
QWidget {
    background-color: #2e2e2e;
    color: #e0e0e0;
    font-size: 10pt;
}
QPushButton {
    background-color: #555555;
    border: 1px solid #777777;
    padding: 5px 10px;
    border-radius: 4px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #666666;
    border: 1px solid #888888;
}
QPushButton:pressed {
    background-color: #444444;
}
QPushButton:disabled {
    background-color: #404040;
    color: #777777;
    border: 1px solid #555555;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QDoubleSpinBox {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    padding: 4px;
    border-radius: 3px;
    color: #e0e0e0; /* Ensure text color is light */
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
     width: 16px;
     border-left: 1px solid #555555;
     background-color: #444444;
}
QComboBox::drop-down {
    border: none;
    background-color: #555555;
}
QComboBox::down-arrow {
    /* Можно использовать стандартную или добавить ресурс */
    width: 12px;
    height: 12px;
}
QComboBox:editable { /* Style editable combo box */
    background-color: #3c3c3c;
}
QLabel {
    padding-top: 4px;
}
QTextEdit {
    font-family: Consolas, Courier New, monospace;
    background-color: #252525; /* Slightly darker background for output */
}
QStatusBar {
    font-size: 9pt;
    color: #aaaaaa;
}
QTableWidget {
    background-color: #3c3c3c;
    alternate-background-color: #444444;
    border: 1px solid #555555;
    gridline-color: #555555;
    color: #e0e0e0; /* Ensure text color */
}
QTableWidget QHeaderView::section {
    background-color: #555555;
    padding: 4px;
    border: 1px solid #666666;
    font-weight: bold;
    color: #e0e0e0; /* Ensure text color */
}
QTabWidget::pane {
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 5px;
}
QTabBar::tab {
    background-color: #444444;
    border: 1px solid #555555;
    padding: 6px 10px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #e0e0e0; /* Ensure text color */
}
QTabBar::tab:selected {
    background-color: #555555;
}
QTabBar::tab:hover {
    background-color: #666666;
}
QProgressBar {
    border: 1px solid #555555;
    border-radius: 3px;
    text-align: center;
    background-color: #3c3c3c;
    color: #e0e0e0;
}
QProgressBar::chunk {
    background-color: #0078d7; /* Blue progress */
    border-radius: 3px;
}
QGroupBox {
    border: 1px solid #555555;
    margin-top: 10px; /* Space above the group box */
    padding-top: 10px; /* Space for the title */
    border-radius: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #aaaaaa;
}
QCheckBox {
    padding-top: 3px;
}
QDoubleSpinBox { /* Make sure double spin box uses light text */
    color: #e0e0e0;
}
"""

class YoloTrainerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO Trainer GUI (Enhanced v2)")
        self.setGeometry(100, 100, 1000, 900) # Adjusted size for more info

        self.process = None
        self.python_executable = self._find_python_executable()
        self.is_paused = False
        self.total_epochs = 1 # For progress bar calculation
        self.current_experiment_path = None
        self.results_csv_path = None
        self.last_csv_pos = 0

        self.fs_watcher = QFileSystemWatcher(self)
        self.fs_watcher.fileChanged.connect(self._handle_results_csv_update)

        self._init_ui()
        self.apply_styles()
        self._update_experiment_path_display() # Initialize display
        self.check_dependencies()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- Configuration Buttons ---
        config_button_layout = QHBoxLayout()
        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.setToolTip("Save current settings to a JSON file")
        self.save_config_button.clicked.connect(self.save_config)
        self.load_config_button = QPushButton("Load Config")
        self.load_config_button.setToolTip("Load settings from a JSON file")
        self.load_config_button.clicked.connect(self.load_config)
        config_button_layout.addStretch()
        config_button_layout.addWidget(self.save_config_button)
        config_button_layout.addWidget(self.load_config_button)
        self.main_layout.addLayout(config_button_layout)

        # --- Settings Tabs ---
        self.settings_tabs = QTabWidget()
        self._create_basic_settings_tab()
        self._create_advanced_settings_tab()
        self._create_environment_tab()
        self.main_layout.addWidget(self.settings_tabs)

        # --- Action Buttons ---
        self.button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Training")
        self.start_button.clicked.connect(self.start_training)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        self.stop_button = QPushButton("Stop Training")
        self.stop_button.clicked.connect(self.stop_training)
        self.stop_button.setEnabled(False)

        self.button_layout.addStretch()
        self.button_layout.addWidget(self.start_button)
        self.button_layout.addWidget(self.pause_button)
        self.button_layout.addWidget(self.stop_button)
        self.button_layout.addStretch()
        self.main_layout.addLayout(self.button_layout)

        # --- Progress Bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.main_layout.addWidget(self.progress_bar)

        # --- Output Tabs ---
        self.output_tabs = QTabWidget()
        self._create_output_tab()
        self._create_metrics_tab()
        self.main_layout.addWidget(self.output_tabs)

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.status_bar.showMessage(f"Ready. Using Python: {self.python_executable}")
        self.main_layout.addWidget(self.status_bar)

    def _find_python_executable(self):
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

    def _create_basic_settings_tab(self):
        basic_tab = QWidget()
        layout = QFormLayout(basic_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.data_yaml_path_edit = QLineEdit()
        self.data_yaml_path_edit.setPlaceholderText("Select dataset configuration file...")
        self.data_yaml_path_edit.setObjectName("data_yaml_path_edit")
        browse_data_button = QPushButton("Browse...")
        browse_data_button.clicked.connect(self.browse_data_yaml)
        data_layout = QHBoxLayout()
        data_layout.addWidget(self.data_yaml_path_edit)
        data_layout.addWidget(browse_data_button)
        layout.addRow("Dataset YAML:", data_layout)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.lineEdit().setPlaceholderText("Select or enter model (e.g., yolov8s.pt or path/to/model.pt)")
        models = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt",
                  "yolov5nu.pt", "yolov5su.pt", "yolov5mu.pt", "yolov5lu.pt", "yolov5xu.pt"]
        self.model_combo.addItems(models)
        self.model_combo.setCurrentIndex(1)
        self.model_combo.setObjectName("model_combo")
        browse_model_button = QPushButton("Browse...")
        browse_model_button.setToolTip("Browse for a custom .pt model file")
        browse_model_button.clicked.connect(self.browse_model_pt)
        model_layout = QHBoxLayout()
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(browse_model_button)
        layout.addRow("Base Model:", model_layout)

        self.epochs_spinbox = QSpinBox()
        self.epochs_spinbox.setRange(1, 10000)
        self.epochs_spinbox.setValue(100)
        self.epochs_spinbox.setObjectName("epochs_spinbox")
        layout.addRow("Epochs:", self.epochs_spinbox)

        self.imgsz_spinbox = QSpinBox()
        self.imgsz_spinbox.setRange(32, 8192)
        self.imgsz_spinbox.setSingleStep(32)
        self.imgsz_spinbox.setValue(640)
        self.imgsz_spinbox.setToolTip("Must be divisible by 32")
        self.imgsz_spinbox.setObjectName("imgsz_spinbox")
        layout.addRow("Image Size (imgsz):", self.imgsz_spinbox)

        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(-1, 1024)
        self.batch_spinbox.setValue(16)
        self.batch_spinbox.setToolTip("Set to -1 for auto-batch (requires Ultralytics >= 8.0.101)")
        self.batch_spinbox.setObjectName("batch_spinbox")
        layout.addRow("Batch Size:", self.batch_spinbox)

        self.project_edit = QLineEdit(DEFAULT_PROJECT_NAME)
        self.project_edit.setPlaceholderText("Parent folder for all experiments...")
        self.project_edit.setObjectName("project_edit")
        self.project_edit.textChanged.connect(self._update_experiment_path_display)
        layout.addRow("Project Name:", self.project_edit)

        self.name_edit = QLineEdit(DEFAULT_EXP_NAME)
        self.name_edit.setPlaceholderText("Specific run name (subfolder)...")
        self.name_edit.setObjectName("name_edit")
        self.name_edit.textChanged.connect(self._update_experiment_path_display)
        layout.addRow("Experiment Name:", self.name_edit)

        self.settings_tabs.addTab(basic_tab, "Basic Settings")

    def _create_advanced_settings_tab(self):
        advanced_tab = QWidget()
        layout = QFormLayout(advanced_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.optimizer_combo = QComboBox()
        optimizers = ["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp"]
        self.optimizer_combo.addItems(optimizers)
        self.optimizer_combo.setCurrentText("auto")
        self.optimizer_combo.setToolTip("Select the optimizer (or 'auto' for default)")
        self.optimizer_combo.setObjectName("optimizer_combo")
        layout.addRow("Optimizer:", self.optimizer_combo)

        self.lr0_spinbox = QDoubleSpinBox()
        self.lr0_spinbox.setRange(0.0, 1.0)
        self.lr0_spinbox.setDecimals(5)
        self.lr0_spinbox.setSingleStep(0.001)
        self.lr0_spinbox.setValue(0.01)
        self.lr0_spinbox.setToolTip("Initial learning rate (e.g., 0.01)")
        self.lr0_spinbox.setObjectName("lr0_spinbox")
        layout.addRow("Learning Rate (lr0):", self.lr0_spinbox)

        self.patience_spinbox = QSpinBox()
        self.patience_spinbox.setRange(0, 1000)
        self.patience_spinbox.setValue(50)
        self.patience_spinbox.setToolTip("Epochs to wait for no improvement before stopping (0 to disable)")
        self.patience_spinbox.setObjectName("patience_spinbox")
        layout.addRow("Patience:", self.patience_spinbox)

        aug_group = QGroupBox("Augmentation Parameters")
        aug_layout = QFormLayout(aug_group)
        self.mosaic_checkbox = QCheckBox("Enable Mosaic")
        self.mosaic_checkbox.setChecked(True)
        self.mosaic_checkbox.setToolTip("YOLOv5/v8 default: 1.0 (enabled)")
        self.mosaic_checkbox.setObjectName("mosaic_checkbox")
        aug_layout.addRow(self.mosaic_checkbox)
        self.mixup_checkbox = QCheckBox("Enable MixUp")
        self.mixup_checkbox.setChecked(False)
        self.mixup_checkbox.setToolTip("YOLOv5/v8 default: 0.0 (disabled)")
        self.mixup_checkbox.setObjectName("mixup_checkbox")
        aug_layout.addRow(self.mixup_checkbox)
        self.degrees_spinbox = QDoubleSpinBox(); self.degrees_spinbox.setRange(0.0, 180.0); self.degrees_spinbox.setValue(0.0); self.degrees_spinbox.setObjectName("degrees_spinbox")
        aug_layout.addRow("Degrees (+/-):", self.degrees_spinbox)
        self.translate_spinbox = QDoubleSpinBox(); self.translate_spinbox.setRange(0.0, 0.9); self.translate_spinbox.setDecimals(3); self.translate_spinbox.setValue(0.1); self.translate_spinbox.setObjectName("translate_spinbox")
        aug_layout.addRow("Translate (+/-):", self.translate_spinbox)
        self.scale_spinbox = QDoubleSpinBox(); self.scale_spinbox.setRange(0.0, 1.0); self.scale_spinbox.setDecimals(3); self.scale_spinbox.setValue(0.5); self.scale_spinbox.setObjectName("scale_spinbox")
        aug_layout.addRow("Scale (+/-):", self.scale_spinbox)
        self.fliplr_spinbox = QDoubleSpinBox(); self.fliplr_spinbox.setRange(0.0, 1.0); self.fliplr_spinbox.setDecimals(2); self.fliplr_spinbox.setValue(0.5); self.fliplr_spinbox.setObjectName("fliplr_spinbox")
        aug_layout.addRow("Flip L/R Prob:", self.fliplr_spinbox)
        layout.addRow(aug_group)

        self.additional_args_edit = QLineEdit()
        self.additional_args_edit.setPlaceholderText("e.g., workers=8, save_period=5")
        self.additional_args_edit.setToolTip("Additional key=value arguments for model.train(), comma-separated.")
        self.additional_args_edit.setObjectName("additional_args_edit")
        layout.addRow("Additional Args:", self.additional_args_edit)

        self.settings_tabs.addTab(advanced_tab, "Advanced Hyperparameters")

    def _create_environment_tab(self):
        env_tab = QWidget()
        layout = QFormLayout(env_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.python_path_edit = QLineEdit(self.python_executable)
        self.python_path_edit.setPlaceholderText("Path to python.exe or python executable")
        self.python_path_edit.setObjectName("python_path_edit")
        self.python_path_edit.textChanged.connect(self._update_python_executable)
        browse_python_button = QPushButton("Browse...")
        browse_python_button.clicked.connect(self.browse_python_executable)
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_path_edit)
        python_layout.addWidget(browse_python_button)
        layout.addRow("Python Executable:", python_layout)

        self.device_label = QLabel("Device:")
        self.device_combo = QComboBox()
        devices = ["cpu"]
        default_device_index = 0
        if CUDA_AVAILABLE:
            try:
                 for i in range(NUM_CUDA_DEVICES): devices.append(f"{i}")
                 if devices: default_device_index = 1
            except Exception as e: print(f"Could not enumerate CUDA devices: {e}")
        self.device_combo.addItems(devices)
        self.device_combo.setCurrentIndex(default_device_index)
        self.device_combo.setObjectName("device_combo")
        layout.addRow(self.device_label, self.device_combo)

        # Experiment Path Info
        self.exp_path_label = QLabel("...") # Will be updated
        self.exp_path_label.setWordWrap(True)
        layout.addRow("Expected Exp. Path:", self.exp_path_label)

        self.open_exp_folder_button = QPushButton("Open Experiment Folder")
        self.open_exp_folder_button.clicked.connect(self.open_experiment_folder)
        self.open_exp_folder_button.setEnabled(False)
        layout.addRow(self.open_exp_folder_button)


        info_group = QGroupBox("Detected Environment")
        info_layout = QFormLayout(info_group)
        torch_status = f"Available ({torch.__version__})" if TORCH_AVAILABLE else "Not Found"
        cuda_status = "Available" if CUDA_AVAILABLE else ("Not Found" if not TORCH_AVAILABLE else "Unavailable")
        cuda_devices_info = f"{NUM_CUDA_DEVICES} device(s)" if CUDA_AVAILABLE else "N/A"
        ultralytics_gui_status = "Installed" if ULTRALYTICS_INSTALLED_IN_GUI_ENV else "Not Found (Install in GUI env if issues)"
        info_layout.addRow(QLabel("PyTorch Status:"), QLabel(f"<b>{torch_status}</b>"))
        info_layout.addRow(QLabel("CUDA Status:"), QLabel(f"<b>{cuda_status}</b>"))
        info_layout.addRow(QLabel("CUDA Devices:"), QLabel(f"<b>{cuda_devices_info}</b>"))
        info_layout.addRow(QLabel("Ultralytics (GUI Env):"), QLabel(f"<b>{ultralytics_gui_status}</b>"))
        layout.addRow(info_group)

        self.settings_tabs.addTab(env_tab, "Environment")

    def _create_output_tab(self):
        self.output_tab = QWidget()
        self.output_tab_layout = QVBoxLayout(self.output_tab)
        self.output_label = QLabel("Output Log:")
        self.output_textedit = QTextEdit()
        self.output_textedit.setReadOnly(True)
        self.output_tab_layout.addWidget(self.output_label)
        self.output_tab_layout.addWidget(self.output_textedit)
        self.output_tabs.addTab(self.output_tab, "Output Log")

    def _create_metrics_tab(self):
        self.metrics_tab = QWidget()
        self.metrics_tab_layout = QVBoxLayout(self.metrics_tab)
        self.metrics_label = QLabel("Training Progress Metrics (from results.csv if available):")
        self.metrics_table = QTableWidget()
        # Columns to align with typical Ultralytics results.csv, plus console info
        self.metrics_table_headers = [
            "Epoch", "trn_box", "trn_cls", "trn_dfl", # Train losses from CSV
            "val_box", "val_cls", "val_dfl",          # Val losses from CSV
            "mAP50", "mAP50-95",                     # Val metrics from CSV
            "LR(pg0)"                                # Learning rate from CSV
        ]
        self.metrics_table.setColumnCount(len(self.metrics_table_headers))
        self.metrics_table.setHorizontalHeaderLabels(self.metrics_table_headers)
        self.metrics_table.horizontalHeader().setStretchLastSection(False)
        self.metrics_table.resizeColumnsToContents()
        self.metrics_table.setAlternatingRowColors(True)
        self.metrics_tab_layout.addWidget(self.metrics_label)
        self.metrics_tab_layout.addWidget(self.metrics_table)
        self.output_tabs.addTab(self.metrics_tab, "Training Metrics")

    def apply_styles(self):
        self.setStyleSheet(DARK_STYLESHEET)

    def check_dependencies(self):
        if not self.python_executable or not Path(self.python_executable).is_file():
             QMessageBox.critical(self, "Environment Error",
                                     f"Selected Python executable not found or invalid:\n{self.python_executable}\n\nPlease select a valid Python executable in the Environment tab.")
             self.start_button.setEnabled(False)
             self.status_bar.showMessage("Error: Invalid Python executable selected.")
             return False

        # Check ultralytics in the *target* environment
        if self.python_executable and Path(self.python_executable).is_file():
            # Using `ultralytics.utils.checks` is a good way to see if core components are fine
            # Simpler: check_process.start(self.python_executable, ["-c", "import ultralytics; print(ultralytics.__version__)"])
            # For a more thorough check, YOLO's own check utility is good.
            # Some environments might not have `ultralytics.utils.checks` directly runnable via -m if not a full install
            # A simple import check is often sufficient.
            check_process = QProcess()
            check_process.setProgram(self.python_executable)
            check_process.setArguments(["-c", "import ultralytics; from ultralytics.utils import checks; checks.collect_system_info()"])

            check_process.start()
            check_process.waitForFinished(5000) # 5-second timeout

            if check_process.exitStatus() != QProcess.ExitStatus.NormalExit or check_process.exitCode() != 0:
                stderr_output = check_process.readAllStandardError().data().decode(errors='ignore').strip()
                stdout_output = check_process.readAllStandardOutput().data().decode(errors='ignore').strip()
                msg = (f"Ultralytics might not be installed or functional in the selected Python environment:\n"
                       f"'{self.python_executable}'\n\n"
                       f"Attempt to import and run basic checks failed.\n"
                       f"Exit Code: {check_process.exitCode()}, Status: {check_process.exitStatus()}\n"
                       f"Stderr:\n{stderr_output}\n\nStdout:\n{stdout_output}\n\n"
                       "Please ensure 'ultralytics' and its dependencies (like PyTorch) are correctly installed in this environment.")
                QMessageBox.warning(self, "Target Environment Check Failed", msg)
                self.status_bar.showMessage("Warning: Ultralytics check failed in target environment.")
                # self.start_button.setEnabled(False) # Optional: be stricter
            else:
                self.status_bar.showMessage(f"Ultralytics check OK in target: {self.python_executable}")
        else:
            # This case should be caught by the first check in this method
            pass


        if not TORCH_AVAILABLE:
             self.device_combo.clear(); self.device_combo.addItems(["cpu"]); self.device_combo.setEnabled(False)
             self.status_bar.showMessage("Warning: PyTorch not found in GUI env. Only CPU available.")
        elif not CUDA_AVAILABLE and self.device_combo.currentText() != 'cpu':
             QMessageBox.information(self, "CUDA Info", "PyTorch found (GUI env), but CUDA seems unavailable.\n"
                                          "Training will use CPU if a GPU is selected but not found by the target training script.")
        return True

    def browse_data_yaml(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Dataset YAML File", "", "YAML Files (*.yaml *.yml)")
        if filename: self.data_yaml_path_edit.setText(filename.replace('/', os.sep))

    def browse_model_pt(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Model File", "", "PyTorch Model Files (*.pt)")
        if filename:
            f_norm = filename.replace('/', os.sep)
            if self.model_combo.findText(f_norm, Qt.MatchFlag.MatchFixedString) == -1:
                 self.model_combo.addItem(f_norm)
            self.model_combo.setCurrentText(f_norm)

    def browse_python_executable(self):
        exe_filter = "Python Executable (python.exe)" if platform.system() == "Windows" else "Python Executable (python)"
        filename, _ = QFileDialog.getOpenFileName(self, "Select Python Executable", "", f"{exe_filter};;All Files (*)")
        if filename: self.python_path_edit.setText(filename.replace('/', os.sep))

    def _update_python_executable(self):
        path = self.python_path_edit.text()
        if os.path.isfile(path):
             self.python_executable = path
             self.status_bar.showMessage(f"Using Python: {self.python_executable}")
             self.check_dependencies() # Re-check with new Python
        else:
            self.status_bar.showMessage(f"Warning: Python path is not a valid file: {path}")

    def _update_experiment_path_display(self):
        project = self.project_edit.text().strip()
        name = self.name_edit.text().strip()
        if project and name:
            # Assume CWD for QProcess will be script directory if project/name are relative
            base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            self.current_experiment_path = base_dir / project / name
            self.exp_path_label.setText(str(self.current_experiment_path.resolve()))
            # Enable open folder button if path seems plausible (doesn't check existence yet)
            self.open_exp_folder_button.setEnabled(True)
        else:
            self.current_experiment_path = None
            self.exp_path_label.setText("(Set Project and Experiment Name)")
            self.open_exp_folder_button.setEnabled(False)

    def open_experiment_folder(self):
        if self.current_experiment_path:
            # Ensure the path exists before trying to open
            if self.current_experiment_path.exists() and self.current_experiment_path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_experiment_path.resolve())))
            else:
                # If path doesn't exist, maybe it's from a previous run config. Try parent of project.
                proj_parent = self.current_experiment_path.parent.parent
                if proj_parent.exists() and proj_parent.is_dir():
                     QDesktopServices.openUrl(QUrl.fromLocalFile(str(proj_parent.resolve())))
                     QMessageBox.information(self, "Folder Info", f"Experiment folder '{self.current_experiment_path.name}' not found. Opened project folder '{proj_parent.name}' instead.")
                else:
                     QMessageBox.warning(self, "Folder Not Found", f"Experiment path does not exist:\n{self.current_experiment_path.resolve()}")
        else:
            QMessageBox.information(self, "No Path", "Experiment path is not defined.")

    def validate_inputs(self) -> bool:
        if not self.check_dependencies(): return False # Re-check environment first
        if not self.data_yaml_path_edit.text() or not Path(self.data_yaml_path_edit.text()).is_file():
            QMessageBox.warning(self, "Input Error", "Please select a valid dataset YAML file."); self.settings_tabs.setCurrentIndex(0); self.data_yaml_path_edit.setFocus(); return False
        model_text = self.model_combo.currentText()
        if not model_text:
            QMessageBox.warning(self, "Input Error", "Please select or enter a base model."); self.settings_tabs.setCurrentIndex(0); self.model_combo.setFocus(); return False
        if os.sep in model_text and not Path(model_text).is_file():
             QMessageBox.warning(self, "Input Error", f"Specified model path not found:\n{model_text}"); self.settings_tabs.setCurrentIndex(0); self.model_combo.setFocus(); return False
        if self.imgsz_spinbox.value() % 32 != 0:
             QMessageBox.warning(self, "Input Error", f"Image size ({self.imgsz_spinbox.value()}) must be divisible by 32."); self.settings_tabs.setCurrentIndex(0); self.imgsz_spinbox.setFocus(); return False
        return True

    def start_training(self):
        if not self.validate_inputs(): return

        self.metrics_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")
        self.output_textedit.clear()
        self.last_csv_pos = 0 # Reset CSV reader position

        data_yaml = self.data_yaml_path_edit.text().replace(os.sep, '/')
        model = self.model_combo.currentText().replace(os.sep, '/')
        epochs = self.epochs_spinbox.value()
        self.total_epochs = epochs
        imgsz = self.imgsz_spinbox.value()
        batch = self.batch_spinbox.value()
        device = self.device_combo.currentText()
        project = self.project_edit.text().strip().replace(os.sep, '/') or DEFAULT_PROJECT_NAME
        name = self.name_edit.text().strip().replace(os.sep, '/') or DEFAULT_EXP_NAME

        optimizer = self.optimizer_combo.currentText()
        lr0 = self.lr0_spinbox.value()
        patience = self.patience_spinbox.value()
        degrees = self.degrees_spinbox.value()
        translate = self.translate_spinbox.value()
        scale = self.scale_spinbox.value()
        fliplr = self.fliplr_spinbox.value()
        mosaic_prob = 1.0 if self.mosaic_checkbox.isChecked() else 0.0
        mixup_prob = 0.1 if self.mixup_checkbox.isChecked() else 0.0 # Ultralytics default is 0.0

        train_args = [
            f"data=r'{data_yaml}'", f"epochs={epochs}", f"imgsz={imgsz}", f"batch={batch}",
            f"device='{device}'", f"project=r'{project}'", f"name=r'{name}'"
        ]
        if optimizer.lower() != "auto": train_args.append(f"optimizer='{optimizer}'")
        # Only add if different from common defaults to keep command cleaner
        if lr0 != 0.01: train_args.append(f"lr0={lr0}") # Ultralytics default is 0.01
        if patience != 50 : train_args.append(f"patience={patience}") # Ultralytics default for classification is 50, detection might be different
        if degrees != 0.0: train_args.append(f"degrees={degrees}")
        if translate != 0.1: train_args.append(f"translate={translate}")
        if scale != 0.5: train_args.append(f"scale={scale}") # Ultralytics default for detection is 0.5
        if fliplr != 0.0: train_args.append(f"fliplr={fliplr}") # Ultralytics default for detection is 0.5, if 0.0 means disable.
        # Mosaic default is 1.0, mixup default is 0.0.
        if not self.mosaic_checkbox.isChecked(): train_args.append("mosaic=0.0")
        if self.mixup_checkbox.isChecked(): train_args.append(f"mixup={mixup_prob}")


        additional_args_str = self.additional_args_edit.text().strip()
        if additional_args_str:
            try:
                # Simple split by comma, assumes args are like "key=value" or "key='string value'"
                parsed_additional_args = [arg.strip() for arg in additional_args_str.split(',') if arg.strip()]
                for arg_str in parsed_additional_args:
                    if '=' not in arg_str: # Basic validation
                        raise ValueError(f"Invalid additional argument format: '{arg_str}'. Expected 'key=value'.")
                train_args.extend(parsed_additional_args)
            except ValueError as e:
                QMessageBox.critical(self, "Input Error", f"Error in Additional CLI Arguments:\n{e}")
                return

        train_params_str = ", ".join(train_args)
        python_code = f"from ultralytics import YOLO; model = YOLO('{model}'); model.train({train_params_str})"
        command_display_str = f'"{self.python_executable}" -c "{python_code}"'

        self.output_textedit.append("<b>Starting training with command:</b>")
        self.output_textedit.append(f"<code>{command_display_str}</code><hr>")

        if self.process is None:
            self.process = QProcess()
            self.process.readyReadStandardOutput.connect(self.handle_stdout)
            self.process.readyReadStandardError.connect(self.handle_stderr)
            self.process.finished.connect(self.process_finished)
            
            # Set working directory. Project/name paths are relative to this.
            # Using script's directory ensures consistency if project/name are relative.
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.process.setWorkingDirectory(script_dir)

            # Update current_experiment_path based on final CWD and project/name
            self._update_experiment_path_display() # Recalculate with actual CWD in mind
            if self.current_experiment_path:
                 self.results_csv_path = self.current_experiment_path / RESULTS_CSV_FILENAME
                 self.output_textedit.append(f"Monitoring for results: {self.results_csv_path}\n")
            else: # Should not happen if project/name are always filled
                 self.results_csv_path = None
                 self.output_textedit.append("<font color='orange'>Warning: Could not determine experiment path for CSV monitoring.</font>\n")


            self.process.setProgram(self.python_executable)
            self.process.setArguments(["-u", "-c", python_code]) # -u for unbuffered output

            self.process.start()

            if self.process.waitForStarted(5000):
                 self.output_textedit.append("Process started...\n")
                 self.start_button.setEnabled(False)
                 self.pause_button.setEnabled(True)
                 self.stop_button.setEnabled(True)
                 self.status_bar.showMessage("Training in progress...")
                 self.progress_bar.setFormat("Training - Epoch 0 / ?")
                 if self.results_csv_path:
                     # Add path to watcher. It might not exist yet.
                     # Watcher will trigger if file is created or modified.
                     self.fs_watcher.addPath(str(self.results_csv_path))
                     # Also watch the parent directory for creation of the file
                     self.fs_watcher.addPath(str(self.results_csv_path.parent))


            else:
                 # ... (error handling as before) ...
                 error_text = self.process.errorString(); exit_code = self.process.exitCode()
                 self.output_textedit.append(f"<font color='red'><b>Error: Process failed to start.</b></font><br>"
                                            f"QProcess Error: {error_text}<br>"
                                            f"Exit Code: {exit_code}<br>"
                                            f"Python Executable: {self.python_executable}<br>"
                                            "Check environment and 'ultralytics' installation.")
                 self.handle_stderr()
                 self.process = None; self.status_bar.showMessage("Error: Failed to start training."); self.progress_bar.setFormat("Error"); self.progress_bar.setValue(0)

    def stop_training(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.output_textedit.append("<hr><b>Attempting to stop training...</b>")
            self.status_bar.showMessage("Stopping training...")
            self.process.terminate()
            QTimer.singleShot(3000, self._kill_if_running)
            self.is_paused = False; self.pause_button.setText("Pause"); self.pause_button.setEnabled(False)
            self.progress_bar.setFormat("Stopping...")

    def _kill_if_running(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
             self.output_textedit.append("<font color='orange'>Process did not terminate gracefully, killing...</font>")
             self.process.kill(); self.progress_bar.setFormat("Killed")

    def process_finished(self):
        if not self.process: return
        exit_code = self.process.exitCode(); exit_status = self.process.exitStatus()
        self.output_textedit.append("<hr>")
        final_message = ""
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
             status_msg = f"Training finished successfully. (Code: {exit_code})"; self.status_bar.showMessage(status_msg); final_message = f"<b>{status_msg}</b>"; self.progress_bar.setValue(100); self.progress_bar.setFormat("Finished")
        elif exit_status == QProcess.ExitStatus.NormalExit and exit_code != 0:
             status_msg = f"Training finished with errors. (Code: {exit_code})"; self.status_bar.showMessage(status_msg); final_message = f"<font color='orange'><b>{status_msg}</b></font>"; self.progress_bar.setFormat(f"Error (Code: {exit_code})")
        else:
             status_msg = f"Training stopped (crashed/terminated). (Code: {exit_code})"; self.status_bar.showMessage(status_msg); final_message = f"<font color='red'><b>{status_msg}</b></font>"
        self.output_textedit.append(final_message)
        self.output_textedit.verticalScrollBar().setValue(self.output_textedit.verticalScrollBar().maximum())

        # Try one last CSV read
        if self.results_csv_path and self.results_csv_path.exists():
            self._handle_results_csv_update(str(self.results_csv_path))

        if self.fs_watcher.files(): self.fs_watcher.removePaths(self.fs_watcher.files())
        if self.fs_watcher.directories(): self.fs_watcher.removePaths(self.fs_watcher.directories())


        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False); self.pause_button.setText("Pause")
        self.stop_button.setEnabled(False)
        self.is_paused = False
        self.process = None

        # Enable open folder button if path exists now
        if self.current_experiment_path and self.current_experiment_path.exists():
            self.open_exp_folder_button.setEnabled(True)


    def handle_stdout(self):
        if not self.process: return
        data = self.process.readAllStandardOutput()
        try:
            text = bytes(data).decode('utf-8', errors='ignore')
            self.parse_stdout_for_progress(text) # For progress bar and quick info
            self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
            self.output_textedit.insertPlainText(text)
        except Exception as e: self.output_textedit.append(f"<font color='red'>[Stdout Decode/Parse Error: {e}] {repr(bytes(data))}</font>")

    def handle_stderr(self):
        if not self.process: return
        data = self.process.readAllStandardError()
        try:
            text = bytes(data).decode('utf-8', errors='ignore')
            self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
            escaped_text = text.replace('&', '&').replace('<', '<').replace('>', '>') # Basic HTML escape
            self.output_textedit.insertHtml(f"<font color='#FF8C00'>{escaped_text}</font>")
            if "error" in text.lower() or "traceback" in text.lower():
                self.status_bar.showMessage("Error occurred during training (see output log).")
        except Exception as e: self.output_textedit.append(f"<font color='red'>[Stderr Decode/Display Error: {e}] {repr(bytes(data))}</font>")

    def parse_stdout_for_progress(self, text):
        """Parses stdout primarily for epoch progress to update the progress bar."""
        # Regex for epoch line: "Epoch   gpu_mem box_loss cls_loss dfl_loss  InstancesSize"
        # Or "   1/100 ..."
        # This regex focuses on extracting current_epoch and total_epochs
        pattern = r"^\s*(\d+)/(\d+)\s+" # e.g., "  1/100 "
        lines = text.split('\n')
        for line in lines:
            line_strip = line.strip()
            match = re.search(pattern, line_strip)
            if match:
                current_epoch_str, total_epochs_str = match.groups()
                try:
                    current_epoch_num = int(current_epoch_str)
                    self.total_epochs = int(total_epochs_str) # Update if necessary
                    if self.total_epochs > 0:
                        progress_percent = int((current_epoch_num / self.total_epochs) * 100)
                        self.progress_bar.setValue(progress_percent)
                        self.progress_bar.setFormat(f"Training - Epoch {current_epoch_num} / {self.total_epochs} ({progress_percent}%)")
                except ValueError:
                    pass # Ignore if parsing fails

            # Log GPU memory if found (example)
            # "     Epoch   gpu_mem   box_loss   cls_loss   dfl_loss  Instances       Size"
            # "       1/3     5.82G      1.564      1.213     0.9901         11        640"
            gpu_mem_match = re.search(r"(\d+/\d+)\s+([0-9.]+[GMBK]+)", line_strip) # Look for "epoch/total GGG.GG G"
            if gpu_mem_match:
                 # self.output_textedit.append(f"<font color='cyan'><i>GPU Mem (from stdout): {gpu_mem_match.group(2)}</i></font>")
                 pass # Can log this if desired, but results.csv is better for main metrics

    def _handle_results_csv_update(self, path_str):
        """Handles updates to the results.csv file."""
        if not self.results_csv_path or str(self.results_csv_path) != path_str:
            # If the file created is not the one we expect, or if it's a dir update
            if self.results_csv_path and self.results_csv_path.exists():
                 path_str = str(self.results_csv_path) # Force use our expected path if it now exists
            else:
                 # If results.csv still doesn't exist, maybe the directory was just created.
                 # The watcher on the directory will trigger this. We re-add the specific file path
                 # in case it gets created next.
                 if self.results_csv_path and not self.fs_watcher.files().__contains__(str(self.results_csv_path)):
                     self.fs_watcher.addPath(str(self.results_csv_path))
                 return


        try:
            if not os.path.exists(path_str): return # File might have been deleted or not created yet

            with open(path_str, 'r', newline='', encoding='utf-8') as csvfile:
                csvfile.seek(self.last_csv_pos)
                reader = csv.reader(csvfile)
                new_content = csvfile.read() # Read the new part as text first
                self.last_csv_pos = csvfile.tell() # Update position

                if not new_content.strip(): return # No new data

                # Go back and parse the new_content with csv.reader
                # This is a bit hacky; a more robust way would be to read line by line
                # and track headers, but for simplicity:
                csvfile.seek(self.last_csv_pos - len(new_content.encode('utf-8'))) # Rewind to start of new content
                
                # If it's the first read, capture headers
                current_headers = []
                if self.metrics_table.rowCount() == 0: # Heuristic: if table is empty, first data rows
                    # Try to read header line if available
                    first_line_str = new_content.splitlines()[0]
                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(first_line_str)
                    header_reader = csv.reader([first_line_str], dialect=dialect)
                    potential_headers = next(header_reader)
                    # Basic check if it looks like a header vs data
                    if any(re.match(r"[a-zA-Z/_()-]+", h) for h in potential_headers) and not any(re.match(r"^[0-9.]+$", h) for h in potential_headers):
                        current_headers = [h.strip() for h in potential_headers]
                        # Skip header row for data processing if we just read it
                        reader = csv.reader(new_content.splitlines()[1:])
                    else: # Assume no header in this chunk, use predefined or previously found
                        reader = csv.reader(new_content.splitlines())
                else: # Not first read
                     reader = csv.reader(new_content.splitlines())


                for row_idx, row_data in enumerate(reader):
                    if not row_data or (not current_headers and row_idx == 0 and any(not item.replace('.', '', 1).isdigit() for item in row_data)):
                        # Skip empty rows or if it's a header row identified heuristically
                        if not current_headers and row_idx == 0: # Store headers if found
                            current_headers = [h.strip() for h in row_data]
                        continue

                    # Map CSV data to table columns based on self.metrics_table_headers
                    # This assumes we know the CSV column names or their order is somewhat fixed
                    # For YOLOv8, common headers are:
                    # epoch, train/box_loss, train/cls_loss, train/dfl_loss,
                    # metrics/precision(B), metrics/recall(B), metrics/mAP50(B), metrics/mAP50-95(B),
                    # val/box_loss, val/cls_loss, val/dfl_loss, lr/pg0, lr/pg1, lr/pg2

                    # Create a dictionary from the row data if headers are available
                    row_dict = {}
                    if current_headers:
                        row_dict = {header: value for header, value in zip(current_headers, row_data)}
                    
                    # Fallback to index-based if no headers or specific headers not found
                    def get_val(key_options, index_fallback):
                        for key in key_options:
                            if key in row_dict: return row_dict[key]
                        return row_data[index_fallback] if index_fallback < len(row_data) else " "

                    # This mapping needs to be robust or user-configurable if CSV format varies widely
                    # Assuming a fairly standard Ultralytics CSV output.
                    epoch = get_val(["epoch", "Epoch"],0)
                    trn_box = get_val(["train/box_loss", "train_box_loss"], 1)
                    trn_cls = get_val(["train/cls_loss", "train_cls_loss"], 2)
                    trn_dfl = get_val(["train/dfl_loss", "train_dfl_loss"], 3)
                    map50 = get_val(["metrics/mAP50(B)", "metrics/mAP50", "mAP50"], 6)
                    map50_95 = get_val(["metrics/mAP50-95(B)", "metrics/mAP50-95", "mAP50-95"], 7)
                    val_box = get_val(["val/box_loss", "val_box_loss"], 8)
                    val_cls = get_val(["val/cls_loss", "val_cls_loss"], 9)
                    val_dfl = get_val(["val/dfl_loss", "val_dfl_loss"], 10)
                    lr_pg0 = get_val(["lr/pg0"], 11) # pg0 is usually the main one

                    table_row_data = [epoch, trn_box, trn_cls, trn_dfl, val_box, val_cls, val_dfl, map50, map50_95, lr_pg0]

                    row_position = self.metrics_table.rowCount()
                    self.metrics_table.insertRow(row_position)
                    for col, item_text in enumerate(table_row_data):
                        item = QTableWidgetItem(str(item_text).strip())
                        if col > 0: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.metrics_table.setItem(row_position, col, item)

                self.metrics_table.resizeColumnsToContents()
                self.metrics_table.scrollToBottom()
                if self.metrics_table.rowCount() > 0 and self.output_tabs.currentWidget() != self.metrics_tab:
                    self.output_tabs.setCurrentWidget(self.metrics_tab)

        except FileNotFoundError:
             self.output_textedit.append(f"<font color='orange'><i>results.csv not found yet at: {path_str}</i></font>\n")
        except Exception as e:
            self.output_textedit.append(f"<font color='red'>Error reading/parsing {RESULTS_CSV_FILENAME}: {e}</font>\n")
            # Stop watching if problematic
            # if self.fs_watcher.files().__contains__(path_str):
            #     self.fs_watcher.removePath(path_str)


    def toggle_pause(self):
        if not self.process or self.process.state() != QProcess.ProcessState.Running: return
        if platform.system() == 'Windows':
            QMessageBox.information(self, "Pause Not Supported", "Pausing training via OS signals is not reliably supported on Windows.")
            return
        pid = self.process.processId()
        if not pid: self.output_textedit.append("\n<font color='red'><b>Error: No process ID to pause/resume.</b></font>"); return
        if not self.is_paused:
            try:
                os.kill(pid, 19); self.is_paused = True; self.pause_button.setText("Resume"); self.status_bar.showMessage("Training paused"); self.output_textedit.append("\n<b>Training paused...</b>"); self.progress_bar.setFormat(self.progress_bar.text() + " [Paused]")
            except OSError as e: self.output_textedit.append(f"\n<font color='#FF8C00'><b>Failed to pause: {e}</b></font>")
        else:
            try:
                os.kill(pid, 18); self.is_paused = False; self.pause_button.setText("Pause"); self.status_bar.showMessage("Training resumed"); self.output_textedit.append("\n<b>Training resumed...</b>"); self.progress_bar.setFormat(self.progress_bar.text().replace(" [Paused]", ""))
            except OSError as e: self.output_textedit.append(f"\n<font color='#FF8C00'><b>Failed to resume: {e}</b></font>")

    def save_config(self):
        config_data = {
            "version": "1.2",
            "basic_settings": {
                "data_yaml": self.data_yaml_path_edit.text(), "model": self.model_combo.currentText(),
                "epochs": self.epochs_spinbox.value(), "imgsz": self.imgsz_spinbox.value(),
                "batch": self.batch_spinbox.value(), "project": self.project_edit.text(),
                "name": self.name_edit.text()
            },
            "advanced_settings": {
                "optimizer": self.optimizer_combo.currentText(), "lr0": self.lr0_spinbox.value(),
                "patience": self.patience_spinbox.value(), "mosaic": self.mosaic_checkbox.isChecked(),
                "mixup": self.mixup_checkbox.isChecked(), "degrees": self.degrees_spinbox.value(),
                "translate": self.translate_spinbox.value(), "scale": self.scale_spinbox.value(),
                "fliplr": self.fliplr_spinbox.value(),
                "additional_args": self.additional_args_edit.text()
            },
            "environment": {
                "python_executable": self.python_path_edit.text(),
                "device": self.device_combo.currentText()
            }
        }
        filename, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)
                self.status_bar.showMessage(f"Configuration saved to {filename}")
            except Exception as e: QMessageBox.critical(self, "Save Error", f"Failed to save: {e}"); self.status_bar.showMessage("Error saving.")

    def load_config(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f: config_data = json.load(f)
                if not isinstance(config_data, dict): raise ValueError("Invalid JSON object.")

                bs = config_data.get("basic_settings", {})
                self.data_yaml_path_edit.setText(bs.get("data_yaml", ""))
                self.model_combo.setCurrentText(bs.get("model", "yolov8s.pt"))
                self.epochs_spinbox.setValue(bs.get("epochs", 100))
                self.imgsz_spinbox.setValue(bs.get("imgsz", 640))
                self.batch_spinbox.setValue(bs.get("batch", 16))
                self.project_edit.setText(bs.get("project", DEFAULT_PROJECT_NAME))
                self.name_edit.setText(bs.get("name", DEFAULT_EXP_NAME))

                adv = config_data.get("advanced_settings", {})
                self.optimizer_combo.setCurrentText(adv.get("optimizer", "auto"))
                self.lr0_spinbox.setValue(adv.get("lr0", 0.01))
                self.patience_spinbox.setValue(adv.get("patience", 50))
                self.mosaic_checkbox.setChecked(adv.get("mosaic", True))
                self.mixup_checkbox.setChecked(adv.get("mixup", False))
                self.degrees_spinbox.setValue(adv.get("degrees", 0.0))
                self.translate_spinbox.setValue(adv.get("translate", 0.1))
                self.scale_spinbox.setValue(adv.get("scale", 0.5))
                self.fliplr_spinbox.setValue(adv.get("fliplr", 0.5))
                self.additional_args_edit.setText(adv.get("additional_args", ""))

                env = config_data.get("environment", {})
                self.python_path_edit.setText(env.get("python_executable", self._find_python_executable()))
                self.device_combo.setCurrentText(env.get("device", "cpu"))

                self._update_experiment_path_display() # Update path label after loading
                self.status_bar.showMessage(f"Configuration loaded from {filename}")

            except Exception as e: QMessageBox.critical(self, "Load Error", f"Failed to load/apply: {e}"); self.status_bar.showMessage("Error loading.")

    def closeEvent(self, event):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Training is in progress. Stop training and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_training()
                QTimer.singleShot(500, self.close)
                event.ignore()
            else:
                event.ignore()
        else:
            if self.fs_watcher.files(): self.fs_watcher.removePaths(self.fs_watcher.files())
            if self.fs_watcher.directories(): self.fs_watcher.removePaths(self.fs_watcher.directories())
            event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # app.setStyle("Fusion") # Optional: force a specific style
    window = YoloTrainerApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE training_enhanced_v2.py ---