# --- START OF FILE training_enhanced.py ---

import sys
import os
import subprocess
import importlib.util # For checking module installation
from pathlib import Path
import re             # For parsing progress output
import json           # For saving/loading configuration
import platform       # To check OS

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QTextEdit, QMessageBox,
    QFormLayout, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QProgressBar, QDoubleSpinBox, QCheckBox, QGroupBox # Added more widgets
)
from PyQt6.QtCore import QProcess, Qt, QTimer
from PyQt6.QtGui import QPalette, QColor, QFont

# --- Constants ---
DEFAULT_PROJECT_NAME = "runs/train"
DEFAULT_EXP_NAME = "exp"
CONFIG_FILE_FILTER = "JSON Config Files (*.json)"

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
    ULTRALYTICS_INSTALLED = True
except ImportError:
    ULTRALYTICS_INSTALLED = False

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
        self.setWindowTitle("YOLO Trainer GUI (Enhanced)")
        self.setGeometry(100, 100, 950, 850) # Adjusted size

        self.process = None
        self.python_executable = self._find_python_executable()
        self.is_paused = False
        self.total_epochs = 1 # For progress bar calculation

        self._init_ui()
        self.apply_styles()
        self.check_dependencies() # Renamed from check_installation

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
        """Attempts to find a suitable Python executable."""
        # 1. Explicit path from config (will be loaded later if exists)
        # 2. Check common venv paths relative to script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        common_venv_paths = [
            os.path.join(script_dir, "venv", "Scripts", "python.exe"), # Windows
            os.path.join(script_dir, "venv", "bin", "python"),      # Linux/macOS
            os.path.join(script_dir, ".venv", "Scripts", "python.exe"), # Windows (.venv)
            os.path.join(script_dir, ".venv", "bin", "python"),      # Linux/macOS (.venv)
        ]
        for venv_python in common_venv_paths:
            if os.path.exists(venv_python):
                print(f"Found venv Python: {venv_python}")
                return venv_python
        
        # 3. Fallback to the Python that is running this script
        print(f"Venv Python not found in standard locations, falling back to sys.executable: {sys.executable}")
        return sys.executable

    def _create_basic_settings_tab(self):
        basic_tab = QWidget()
        layout = QFormLayout(basic_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow) # Allow fields to expand

        # 1. Dataset YAML
        self.data_yaml_path_edit = QLineEdit()
        self.data_yaml_path_edit.setPlaceholderText("Select dataset configuration file...")
        self.data_yaml_path_edit.setObjectName("data_yaml_path_edit") # For config save/load
        browse_data_button = QPushButton("Browse...")
        browse_data_button.clicked.connect(self.browse_data_yaml)
        data_layout = QHBoxLayout()
        data_layout.addWidget(self.data_yaml_path_edit)
        data_layout.addWidget(browse_data_button)
        layout.addRow("Dataset YAML:", data_layout)

        # 2. Base Model
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True) # Allow pasting paths
        self.model_combo.lineEdit().setPlaceholderText("Select or enter model (e.g., yolov8s.pt or path/to/model.pt)")
        models = [
            "yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt",
            "yolov5nu.pt", "yolov5su.pt", "yolov5mu.pt", "yolov5lu.pt", "yolov5xu.pt"
        ]
        self.model_combo.addItems(models)
        self.model_combo.setCurrentIndex(1) # Default to yolov8s.pt
        self.model_combo.setObjectName("model_combo")
        browse_model_button = QPushButton("Browse...")
        browse_model_button.setToolTip("Browse for a custom .pt model file")
        browse_model_button.clicked.connect(self.browse_model_pt)
        model_layout = QHBoxLayout()
        model_layout.addWidget(self.model_combo, 1) # Give combo box more stretch space
        model_layout.addWidget(browse_model_button)
        layout.addRow("Base Model:", model_layout)

        # 3. Epochs
        self.epochs_spinbox = QSpinBox()
        self.epochs_spinbox.setRange(1, 10000)
        self.epochs_spinbox.setValue(100)
        self.epochs_spinbox.setObjectName("epochs_spinbox")
        layout.addRow("Epochs:", self.epochs_spinbox)

        # 4. Image Size (imgsz)
        self.imgsz_spinbox = QSpinBox()
        self.imgsz_spinbox.setRange(32, 8192)
        self.imgsz_spinbox.setSingleStep(32)
        self.imgsz_spinbox.setValue(640)
        self.imgsz_spinbox.setToolTip("Must be divisible by 32")
        self.imgsz_spinbox.setObjectName("imgsz_spinbox")
        layout.addRow("Image Size (imgsz):", self.imgsz_spinbox)

        # 5. Batch Size
        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(-1, 1024) # -1 for auto-batch
        self.batch_spinbox.setValue(16)
        self.batch_spinbox.setToolTip("Set to -1 for auto-batch (requires Ultralytics >= 8.0.101)")
        self.batch_spinbox.setObjectName("batch_spinbox")
        layout.addRow("Batch Size:", self.batch_spinbox)

        # 6. Project Name
        self.project_edit = QLineEdit(DEFAULT_PROJECT_NAME)
        self.project_edit.setPlaceholderText("Parent folder for all experiments...")
        self.project_edit.setObjectName("project_edit")
        layout.addRow("Project Name:", self.project_edit)

        # 7. Experiment Name
        self.name_edit = QLineEdit(DEFAULT_EXP_NAME)
        self.name_edit.setPlaceholderText("Specific run name (subfolder)...")
        self.name_edit.setObjectName("name_edit")
        layout.addRow("Experiment Name:", self.name_edit)

        self.settings_tabs.addTab(basic_tab, "Basic Settings")

    def _create_advanced_settings_tab(self):
        advanced_tab = QWidget()
        layout = QFormLayout(advanced_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Optimizer
        self.optimizer_combo = QComboBox()
        # Common optimizers used by YOLO. Add more if needed.
        optimizers = ["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp"]
        self.optimizer_combo.addItems(optimizers)
        self.optimizer_combo.setCurrentText("auto")
        self.optimizer_combo.setToolTip("Select the optimizer (or 'auto' for default)")
        self.optimizer_combo.setObjectName("optimizer_combo")
        layout.addRow("Optimizer:", self.optimizer_combo)

        # Learning Rate (lr0)
        self.lr0_spinbox = QDoubleSpinBox()
        self.lr0_spinbox.setRange(0.0, 1.0)
        self.lr0_spinbox.setDecimals(5)
        self.lr0_spinbox.setSingleStep(0.001)
        self.lr0_spinbox.setValue(0.01) # Common default start
        self.lr0_spinbox.setToolTip("Initial learning rate (e.g., 0.01)")
        self.lr0_spinbox.setObjectName("lr0_spinbox")
        layout.addRow("Learning Rate (lr0):", self.lr0_spinbox)

        # Patience (Early Stopping)
        self.patience_spinbox = QSpinBox()
        self.patience_spinbox.setRange(0, 1000)
        self.patience_spinbox.setValue(50) # Ultralytics default might vary (e.g., 100 for v8)
        self.patience_spinbox.setToolTip("Epochs to wait for no improvement before stopping (0 to disable)")
        self.patience_spinbox.setObjectName("patience_spinbox")
        layout.addRow("Patience:", self.patience_spinbox)

        # --- Augmentations Group ---
        aug_group = QGroupBox("Augmentation Parameters (Defaults are usually good)")
        aug_layout = QFormLayout(aug_group)

        # Mosaic (usually boolean or probability) - Let's use a checkbox (on/off using default probability)
        self.mosaic_checkbox = QCheckBox("Enable Mosaic")
        self.mosaic_checkbox.setChecked(True) # Often enabled by default
        self.mosaic_checkbox.setToolTip("Combine 4 images (YOLOv5 default: 1.0, YOLOv8 default: 1.0)")
        self.mosaic_checkbox.setObjectName("mosaic_checkbox")
        aug_layout.addRow(self.mosaic_checkbox)

        # MixUp (usually boolean or probability) - Checkbox
        self.mixup_checkbox = QCheckBox("Enable MixUp")
        self.mixup_checkbox.setChecked(False) # Often disabled by default, but available
        self.mixup_checkbox.setToolTip("Mix two images/labels (YOLOv5 default: 0.0, YOLOv8 default: 0.0)")
        self.mixup_checkbox.setObjectName("mixup_checkbox")
        aug_layout.addRow(self.mixup_checkbox)

        # Degrees (Rotation)
        self.degrees_spinbox = QDoubleSpinBox()
        self.degrees_spinbox.setRange(0.0, 180.0)
        self.degrees_spinbox.setValue(0.0) # Default is often 0
        self.degrees_spinbox.setToolTip("Image rotation (+/- deg)")
        self.degrees_spinbox.setObjectName("degrees_spinbox")
        aug_layout.addRow("Degrees (+/-):", self.degrees_spinbox)

        # Translate
        self.translate_spinbox = QDoubleSpinBox()
        self.translate_spinbox.setRange(0.0, 0.9)
        self.translate_spinbox.setDecimals(3)
        self.translate_spinbox.setValue(0.1) # Default e.g. 0.1
        self.translate_spinbox.setToolTip("Image translation (+/- fraction)")
        self.translate_spinbox.setObjectName("translate_spinbox")
        aug_layout.addRow("Translate (+/-):", self.translate_spinbox)

        # Scale
        self.scale_spinbox = QDoubleSpinBox()
        self.scale_spinbox.setRange(0.0, 1.0) # Scale factor is +/- this value from 1.0
        self.scale_spinbox.setDecimals(3)
        self.scale_spinbox.setValue(0.5) # Default e.g. 0.5
        self.scale_spinbox.setToolTip("Image scale (+/- gain)")
        self.scale_spinbox.setObjectName("scale_spinbox")
        aug_layout.addRow("Scale (+/-):", self.scale_spinbox)

        # Flip Left/Right Probability
        self.fliplr_spinbox = QDoubleSpinBox()
        self.fliplr_spinbox.setRange(0.0, 1.0)
        self.fliplr_spinbox.setDecimals(2)
        self.fliplr_spinbox.setValue(0.5) # Default e.g. 0.5
        self.fliplr_spinbox.setToolTip("Probability of horizontal flip")
        self.fliplr_spinbox.setObjectName("fliplr_spinbox")
        aug_layout.addRow("Flip L/R Prob:", self.fliplr_spinbox)

        # Add more HSV controls if needed (hsv_h, hsv_s, hsv_v)
        layout.addRow(aug_group)
        self.settings_tabs.addTab(advanced_tab, "Advanced Hyperparameters")

    def _create_environment_tab(self):
        env_tab = QWidget()
        layout = QFormLayout(env_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Python Executable Path
        self.python_path_edit = QLineEdit(self.python_executable)
        self.python_path_edit.setPlaceholderText("Path to python.exe or python executable")
        self.python_path_edit.setToolTip("The Python interpreter used to run training")
        self.python_path_edit.setObjectName("python_path_edit")
        self.python_path_edit.textChanged.connect(self._update_python_executable) # Update internal variable
        browse_python_button = QPushButton("Browse...")
        browse_python_button.clicked.connect(self.browse_python_executable)
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_path_edit)
        python_layout.addWidget(browse_python_button)
        layout.addRow("Python Executable:", python_layout)

        # Device Selection
        self.device_label = QLabel("Device:")
        self.device_combo = QComboBox()
        devices = ["cpu"]
        default_device_index = 0
        if CUDA_AVAILABLE:
            try:
                 for i in range(NUM_CUDA_DEVICES):
                     devices.append(f"{i}") # Ultralytics often just needs the index
                 if devices:
                     default_device_index = 1 # Select first GPU
            except Exception as e:
                print(f"Could not enumerate CUDA devices: {e}")

        self.device_combo.addItems(devices)
        self.device_combo.setCurrentIndex(default_device_index)
        self.device_combo.setToolTip("Select training device (CPU or GPU index)")
        self.device_combo.setObjectName("device_combo")
        layout.addRow(self.device_label, self.device_combo)

        # --- Info Section ---
        info_group = QGroupBox("Detected Environment")
        info_layout = QFormLayout(info_group)

        torch_status = f"Available ({torch.__version__})" if TORCH_AVAILABLE else "Not Found"
        cuda_status = "Available" if CUDA_AVAILABLE else ("Not Found" if not TORCH_AVAILABLE else "Unavailable (Check drivers/toolkit)")
        cuda_devices_info = f"{NUM_CUDA_DEVICES} device(s)" if CUDA_AVAILABLE else "N/A"
        ultralytics_status = "Installed" if ULTRALYTICS_INSTALLED else "Not Found (Install required)"

        info_layout.addRow(QLabel("PyTorch Status:"), QLabel(f"<b>{torch_status}</b>"))
        info_layout.addRow(QLabel("CUDA Status:"), QLabel(f"<b>{cuda_status}</b>"))
        info_layout.addRow(QLabel("CUDA Devices:"), QLabel(f"<b>{cuda_devices_info}</b>"))
        info_layout.addRow(QLabel("Ultralytics Status:"), QLabel(f"<b>{ultralytics_status}</b>"))

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
        self.metrics_label = QLabel("Training Progress Metrics:")
        self.metrics_table = QTableWidget()
        # Adjust columns based on typical YOLOv8 output
        self.metrics_table.setColumnCount(10)
        self.metrics_table.setHorizontalHeaderLabels([
            "Epoch", "GPU_Mem", "box_loss", "cls_loss", "dfl_loss", # Train losses
            "Instances", "Size", # Train batch info
            "mAP50", "mAP50-95", # Validation metrics (may appear later)
             "Fitness" # Optional, depends on version/task
             ])
        self.metrics_table.horizontalHeader().setStretchLastSection(False) # Don't stretch last if we have many
        self.metrics_table.resizeColumnsToContents() # Resize initially
        self.metrics_table.setAlternatingRowColors(True)
        self.metrics_tab_layout.addWidget(self.metrics_label)
        self.metrics_tab_layout.addWidget(self.metrics_table)
        self.output_tabs.addTab(self.metrics_tab, "Training Metrics")

    def apply_styles(self):
        self.setStyleSheet(DARK_STYLESHEET)

    def check_dependencies(self):
        """Checks critical dependencies and updates status."""
        if not self.python_executable or not Path(self.python_executable).is_file():
             QMessageBox.critical(self, "Environment Error",
                                     f"Selected Python executable not found or invalid:\n{self.python_executable}\n\nPlease select a valid Python executable in the Environment tab.")
             self.start_button.setEnabled(False)
             self.status_bar.showMessage("Error: Invalid Python executable selected.")
             return False # Indicate failure

        # Note: This checks ultralytics in the *GUI's* environment, not the target.
        # A more robust check would involve running a command with the target python.
        if not ULTRALYTICS_INSTALLED:
            QMessageBox.warning(self, "Dependency Missing",
                                 "The 'ultralytics' package was not found in the environment running this GUI.\n"
                                 f"(Current GUI Env: {sys.executable})\n\n"
                                 "Please ensure it is installed in the Python environment you select for training:\n"
                                 f"Target Env: {self.python_executable}\n\n"
                                 "You might need to run:\n"
                                 f"\"{self.python_executable}\" -m pip install ultralytics\n\n"
                                 "Attempting to start training might fail.")
            self.status_bar.showMessage("Warning: 'ultralytics' potentially missing in target environment.")
            # Don't disable start button - let the user try if they think it's installed there.
        else:
             print(f"'ultralytics' package found in GUI environment: {sys.executable}")

        if not TORCH_AVAILABLE:
             self.device_combo.clear()
             self.device_combo.addItems(["cpu"])
             self.device_combo.setEnabled(False)
             self.status_bar.showMessage("Warning: PyTorch not found. Only CPU available.")
        elif not CUDA_AVAILABLE:
             # Keep CPU option, but maybe warn if GPU was selected
             if self.device_combo.currentText() != 'cpu':
                 QMessageBox.information(self, "CUDA Info", "PyTorch found, but CUDA seems unavailable.\n"
                                          "Check drivers, CUDA toolkit, and PyTorch installation for the target environment.\n"
                                          "Falling back to CPU selection if GPU is chosen.")
        return True # Indicate checks passed (or only warnings issued)

    # --- File Browsing ---
    def browse_data_yaml(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Dataset YAML File", "", "YAML Files (*.yaml *.yml)")
        if filename:
            self.data_yaml_path_edit.setText(filename.replace('/', os.sep))

    def browse_model_pt(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Model File", "", "PyTorch Model Files (*.pt)")
        if filename:
            # Add to combo box if not already there and select it
            if self.model_combo.findText(filename, Qt.MatchFlag.MatchFixedString) == -1:
                 self.model_combo.addItem(filename.replace('/', os.sep))
            self.model_combo.setCurrentText(filename.replace('/', os.sep))

    def browse_python_executable(self):
        # Default filter based on OS
        exe_filter = "Python Executable (python.exe)" if platform.system() == "Windows" else "Python Executable (python)"
        filename, _ = QFileDialog.getOpenFileName(self, "Select Python Executable", "", f"{exe_filter};;All Files (*)")
        if filename:
            self.python_path_edit.setText(filename.replace('/', os.sep))
            # self._update_python_executable() # TextChanged signal handles this

    def _update_python_executable(self):
        """Update the internal python executable path and re-check dependencies."""
        path = self.python_path_edit.text()
        if os.path.isfile(path):
             self.python_executable = path
             self.status_bar.showMessage(f"Using Python: {self.python_executable}")
             # Optionally re-run checks, but be mindful this checks the GUI env for ultralytics
             # self.check_dependencies()
        else:
            # Maybe show a warning if the path becomes invalid?
            self.status_bar.showMessage(f"Warning: Entered Python path is not a valid file: {path}")


    # --- Input Validation ---
    def validate_inputs(self) -> bool:
        if not self.check_dependencies(): # Re-check environment first
             return False

        if not self.data_yaml_path_edit.text() or not Path(self.data_yaml_path_edit.text()).is_file():
            QMessageBox.warning(self, "Input Error", "Please select a valid dataset YAML file.")
            self.settings_tabs.setCurrentIndex(0) # Switch to Basic Settings tab
            self.data_yaml_path_edit.setFocus()
            return False

        model_text = self.model_combo.currentText()
        if not model_text:
            QMessageBox.warning(self, "Input Error", "Please select or enter a base model.")
            self.settings_tabs.setCurrentIndex(0)
            self.model_combo.setFocus()
            return False
        # Basic check if it's a path and doesn't exist (more complex validation is hard)
        if os.sep in model_text and not Path(model_text).is_file():
             QMessageBox.warning(self, "Input Error", f"Specified model path not found:\n{model_text}")
             self.settings_tabs.setCurrentIndex(0)
             self.model_combo.setFocus()
             return False

        if self.imgsz_spinbox.value() % 32 != 0:
             QMessageBox.warning(self, "Input Error", f"Image size ({self.imgsz_spinbox.value()}) must be divisible by 32.")
             self.settings_tabs.setCurrentIndex(0)
             self.imgsz_spinbox.setFocus()
             return False

        # Add more validation for other fields if necessary (e.g., project/name chars)

        return True

    # --- Training Process Management ---
    def start_training(self):
        if not self.validate_inputs():
            return

        self.metrics_table.setRowCount(0) # Clear previous metrics
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")

        # --- Collect all parameters ---
        data_yaml = self.data_yaml_path_edit.text().replace(os.sep, '/')
        model = self.model_combo.currentText().replace(os.sep, '/')
        epochs = self.epochs_spinbox.value()
        self.total_epochs = epochs # Store for progress bar
        imgsz = self.imgsz_spinbox.value()
        batch = self.batch_spinbox.value()
        device = self.device_combo.currentText() # Should be 'cpu' or GPU index '0', '1' etc.
        project = self.project_edit.text().strip().replace(os.sep, '/') or DEFAULT_PROJECT_NAME
        name = self.name_edit.text().strip().replace(os.sep, '/') or DEFAULT_EXP_NAME

        # Advanced parameters
        optimizer = self.optimizer_combo.currentText()
        lr0 = self.lr0_spinbox.value()
        patience = self.patience_spinbox.value()
        degrees = self.degrees_spinbox.value()
        translate = self.translate_spinbox.value()
        scale = self.scale_spinbox.value()
        fliplr = self.fliplr_spinbox.value()
        # Mosaic/Mixup treated differently as they are often just flags or probabilities
        mosaic_prob = 1.0 if self.mosaic_checkbox.isChecked() else 0.0 # Default prob if enabled
        mixup_prob = 0.1 if self.mixup_checkbox.isChecked() else 0.0 # Small default prob if enabled

        # --- Construct the Python command string for model.train() ---
        # Start with mandatory args
        train_args = [
            f"data=r'{data_yaml}'",
            f"epochs={epochs}",
            f"imgsz={imgsz}",
            f"batch={batch}",
            f"device='{device}'",
            f"project=r'{project}'",
            f"name='{name}'"
        ]
        # Add optional args only if they differ from likely defaults or are meaningful
        # Check ultralytics source/docs for actual defaults if precision is needed
        if optimizer.lower() != "auto":
             train_args.append(f"optimizer='{optimizer}'")
        if lr0 != 0.01: # Add if not the common default
             train_args.append(f"lr0={lr0}")
        if patience != 50 and patience != 100: # Add if not a common default
             train_args.append(f"patience={patience}")
        if degrees != 0.0:
             train_args.append(f"degrees={degrees}")
        if translate != 0.1:
             train_args.append(f"translate={translate}")
        if scale != 0.5:
             train_args.append(f"scale={scale}")
        if fliplr != 0.5:
             train_args.append(f"fliplr={fliplr}")
        if not self.mosaic_checkbox.isChecked(): # Only add if disabling (assuming default is True/1.0)
            train_args.append("mosaic=0.0")
        if self.mixup_checkbox.isChecked(): # Only add if enabling (assuming default is False/0.0)
            train_args.append(f"mixup={mixup_prob}") # Use the probability if enabled

        # Join arguments
        train_params_str = ", ".join(train_args)

        # Full Python code to execute
        python_code = f"from ultralytics import YOLO; model = YOLO('{model}'); model.train({train_params_str})"

        # --- Prepare QProcess ---
        arguments = ["-c", python_code]

        command_display_str = f'"{self.python_executable}" -c "{python_code}"'

        self.output_textedit.clear()
        self.output_textedit.append("<b>Starting training with command:</b>")
        self.output_textedit.append(f"<code>{command_display_str}</code><hr>") # Use HTML for mono font and separator

        if self.process is None:
            self.process = QProcess()
            self.process.readyReadStandardOutput.connect(self.handle_stdout)
            self.process.readyReadStandardError.connect(self.handle_stderr)
            self.process.finished.connect(self.process_finished)
            # Set working directory to ensure relative paths in project/name work as expected
            # Use the directory of the script as a sensible default, or make configurable?
            self.process.setWorkingDirectory(os.path.dirname(os.path.abspath(__file__)))

            self.process.setProgram(self.python_executable)
            self.process.setArguments(arguments)

            print(f"Starting process: {self.python_executable}")
            print(f"Arguments: {arguments}")
            print(f"Working Directory: {self.process.workingDirectory()}")

            self.process.start()

            if self.process.waitForStarted(5000):
                 self.output_textedit.append("Process started...\n")
                 self.start_button.setEnabled(False)
                 self.pause_button.setEnabled(True)
                 self.stop_button.setEnabled(True)
                 self.status_bar.showMessage("Training in progress...")
                 self.progress_bar.setFormat("Training - Epoch 0 / ?")
            else:
                 error_text = self.process.errorString()
                 exit_code = self.process.exitCode()
                 self.output_textedit.append(f"<font color='red'><b>Error: Process failed to start.</b></font><br>"
                                            f"QProcess Error: {error_text}<br>"
                                            f"Exit Code: {exit_code}<br>"
                                            f"Python Executable: {self.python_executable}<br>"
                                            "Check if the Python environment is correct and 'ultralytics' is installed properly.")
                 self.handle_stderr() # Attempt to read any error output
                 self.process = None
                 self.status_bar.showMessage("Error: Failed to start training process.")
                 self.progress_bar.setFormat("Error")
                 self.progress_bar.setValue(0)

    def stop_training(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.output_textedit.append("<hr><b>Attempting to stop training...</b>")
            self.status_bar.showMessage("Stopping training...")
            self.process.terminate() # Graceful termination first
            # Give it a moment, then kill if necessary
            QTimer.singleShot(3000, self._kill_if_running)
            self.is_paused = False
            self.pause_button.setText("Pause")
            self.pause_button.setEnabled(False)
            self.progress_bar.setFormat("Stopping...")

    def _kill_if_running(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
             self.output_textedit.append("<font color='orange'>Process did not terminate gracefully, killing...</font>")
             self.process.kill()
             self.progress_bar.setFormat("Killed")

    def process_finished(self):
        if not self.process: return

        exit_code = self.process.exitCode()
        exit_status = self.process.exitStatus()

        self.output_textedit.append("<hr>") # Separator
        final_message = ""
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
             status_message = f"Training finished successfully. (Exit Code: {exit_code})"
             self.status_bar.showMessage("Training finished successfully.")
             final_message = f"<b>{status_message}</b>"
             self.progress_bar.setValue(100)
             self.progress_bar.setFormat("Finished")
        elif exit_status == QProcess.ExitStatus.NormalExit and exit_code != 0:
             status_message = f"Training finished with errors. (Exit Code: {exit_code})"
             self.status_bar.showMessage("Training finished with errors.")
             final_message = f"<font color='orange'><b>{status_message}</b></font>"
             self.progress_bar.setFormat(f"Error (Code: {exit_code})")
        else: # CrashExit or explicit termination
             status_message = f"Training stopped (crashed or terminated). (Exit Code: {exit_code})"
             self.status_bar.showMessage("Training stopped.")
             final_message = f"<font color='red'><b>{status_message}</b></font>"
             # Don't reset progress bar if killed, keep "Stopping..." or "Killed" state

        self.output_textedit.append(final_message)
        self.output_textedit.verticalScrollBar().setValue(self.output_textedit.verticalScrollBar().maximum())

        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(False)
        self.is_paused = False
        self.process = None # Crucial: release the process object

    def handle_stdout(self):
        if not self.process: return
        data = self.process.readAllStandardOutput()
        try:
            text = bytes(data).decode('utf-8', errors='ignore')
            # Parse metrics before appending to log
            self.parse_training_metrics(text)
            self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
            self.output_textedit.insertPlainText(text)
            self.output_textedit.verticalScrollBar().setValue(self.output_textedit.verticalScrollBar().maximum())
        except Exception as e:
            error_msg = f"[Stdout Decode/Parse Error: {e}]" + repr(bytes(data))
            self.output_textedit.append(f"<font color='red'>{error_msg}</font>")

    def handle_stderr(self):
        if not self.process: return
        data = self.process.readAllStandardError()
        try:
            text = bytes(data).decode('utf-8', errors='ignore')
            self.output_textedit.moveCursor(self.output_textedit.textCursor().MoveOperation.End)
            # Use HTML for error color and escaping
            escaped_text = text.replace('&', '&').replace('<', '<').replace('>', '>')
            self.output_textedit.insertHtml(f"<font color='#FF8C00'>{escaped_text}</font>") # Orange-ish red
            self.output_textedit.verticalScrollBar().setValue(self.output_textedit.verticalScrollBar().maximum())
            # Also update status bar for visible errors
            if "error" in text.lower() or "traceback" in text.lower():
                self.status_bar.showMessage("Error occurred during training (see output log).")
        except Exception as e:
             error_msg = f"[Stderr Decode/Display Error: {e}]" + repr(bytes(data))
             self.output_textedit.append(f"<font color='red'>{error_msg}</font>")


    def parse_training_metrics(self, text):
        """
        Parses metrics from stdout and updates the table and progress bar.
        NOTE: This relies on specific stdout formatting from Ultralytics,
              which *can change* between versions, making this potentially fragile.
              Monitoring CSV logs would be more robust if possible.
        """
        # Regex for standard epoch/validation lines (adjust if needed for your YOLO version)
        # Example Train: "     1/100       5.81G    0.7774    0.3329    0.9736       204        640"
        # Example Val:   "     1/100       5.81G    0.7774    0.3329    0.9736       204        640      0.123     0.456"  (mAP50, mAP50-95)
        # Updated regex to capture both train and potentially val metrics on the same line type
        # Groups: 1:Epoch, 2:TotalEpoch, 3:GPU, 4:box, 5:cls, 6:dfl, 7:Instances, 8:Size, [9:mAP50], [10:mAP50-95]
        pattern = r"^\s*(\d+)/(\d+)\s+([0-9.]+[GMBK]?)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+(\d+)\s+(\d+)(?:\s+([0-9.]+)\s+([0-9.]+))?" # Make val metrics optional

        lines = text.split('\n')
        for line in lines:
            match = re.search(pattern, line.strip())
            if match:
                groups = match.groups()
                # Extract mandatory fields
                epoch, total_epochs_str, gpu_mem, box_loss, cls_loss, dfl_loss, instances, size = groups[:8]
                # Extract optional validation metrics
                map50 = groups[8] if len(groups) > 8 and groups[8] else " " # Handle optional group
                map50_95 = groups[9] if len(groups) > 9 and groups[9] else " " # Handle optional group

                # Update total epochs if it changed (unlikely mid-train but good practice)
                try:
                    current_epoch_num = int(epoch)
                    self.total_epochs = int(total_epochs_str)
                except ValueError:
                    current_epoch_num = 0 # Should not happen with pattern match

                # Add row to metrics table
                row_position = self.metrics_table.rowCount()
                self.metrics_table.insertRow(row_position)

                items = [epoch, gpu_mem, box_loss, cls_loss, dfl_loss, instances, size, map50, map50_95, " "] # Placeholder for Fitness
                for col, item_text in enumerate(items):
                    item = QTableWidgetItem(item_text.strip())
                    # Center align numeric-like columns for readability
                    if col > 0: # Skip epoch number for alignment
                       item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.metrics_table.setItem(row_position, col, item)

                self.metrics_table.resizeColumnsToContents() # Adjust column widths
                self.metrics_table.scrollToBottom()

                # Update Progress Bar
                if self.total_epochs > 0:
                    progress_percent = int((current_epoch_num / self.total_epochs) * 100)
                    self.progress_bar.setValue(progress_percent)
                    self.progress_bar.setFormat(f"Training - Epoch {current_epoch_num} / {self.total_epochs} ({progress_percent}%)")

                # Switch to metrics tab on first update
                if row_position == 0:
                    self.output_tabs.setCurrentWidget(self.metrics_tab)

    def toggle_pause(self):
        """Toggles pause/resume (Limited functionality on Windows)."""
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return

        if platform.system() == 'Windows':
            self.output_textedit.append("\n<font color='#FF8C00'><b>Pause/Resume functionality using OS signals is not reliably supported on Windows.</b></font>")
            QMessageBox.information(self, "Pause Not Supported", "Pausing the training process via OS signals is not supported on Windows.")
            return

        # For Linux/macOS:
        pid = self.process.processId()
        if not pid:
            self.output_textedit.append("\n<font color='red'><b>Error: Could not get process ID to pause/resume.</b></font>")
            return

        if not self.is_paused:
            try:
                os.kill(pid, 19)  # SIGSTOP
                self.is_paused = True
                self.pause_button.setText("Resume")
                self.status_bar.showMessage("Training paused")
                self.output_textedit.append("\n<b>Training paused...</b>")
                self.progress_bar.setFormat(self.progress_bar.text() + " [Paused]")
            except OSError as e:
                self.output_textedit.append(f"\n<font color='#FF8C00'><b>Failed to pause training: {e}</b></font>")
        else:
            try:
                os.kill(pid, 18)  # SIGCONT
                self.is_paused = False
                self.pause_button.setText("Pause")
                self.status_bar.showMessage("Training resumed")
                self.output_textedit.append("\n<b>Training resumed...</b>")
                # Remove [Paused] from progress bar format string
                current_format = self.progress_bar.text()
                self.progress_bar.setFormat(current_format.replace(" [Paused]", ""))
            except OSError as e:
                self.output_textedit.append(f"\n<font color='#FF8C00'><b>Failed to resume training: {e}</b></font>")


    # --- Configuration Management ---
    def save_config(self):
        """Saves the current GUI settings to a JSON file."""
        config_data = {
            "version": "1.1", # Add version for future compatibility
            "basic_settings": {
                "data_yaml": self.data_yaml_path_edit.text(),
                "model": self.model_combo.currentText(),
                "epochs": self.epochs_spinbox.value(),
                "imgsz": self.imgsz_spinbox.value(),
                "batch": self.batch_spinbox.value(),
                "project": self.project_edit.text(),
                "name": self.name_edit.text()
            },
            "advanced_settings": {
                "optimizer": self.optimizer_combo.currentText(),
                "lr0": self.lr0_spinbox.value(),
                "patience": self.patience_spinbox.value(),
                "mosaic": self.mosaic_checkbox.isChecked(),
                "mixup": self.mixup_checkbox.isChecked(),
                "degrees": self.degrees_spinbox.value(),
                "translate": self.translate_spinbox.value(),
                "scale": self.scale_spinbox.value(),
                "fliplr": self.fliplr_spinbox.value()
            },
            "environment": {
                "python_executable": self.python_path_edit.text(), # Save the path from the edit box
                "device": self.device_combo.currentText()
            }
        }

        filename, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=4)
                self.status_bar.showMessage(f"Configuration saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save configuration:\n{e}")
                self.status_bar.showMessage("Error saving configuration.")

    def load_config(self):
        """Loads GUI settings from a JSON file."""
        filename, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                # Basic Error Checking
                if not isinstance(config_data, dict):
                    raise ValueError("Configuration file does not contain a valid JSON object.")

                # --- Apply settings with checks for missing keys ---
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

                env = config_data.get("environment", {})
                loaded_python_path = env.get("python_executable", "")
                self.python_path_edit.setText(loaded_python_path)
                # self._update_python_executable() # TextChanged signal handles this
                self.device_combo.setCurrentText(env.get("device", "cpu"))

                self.status_bar.showMessage(f"Configuration loaded from {filename}")

            except json.JSONDecodeError as e:
                 QMessageBox.critical(self, "Load Error", f"Failed to parse configuration file (Invalid JSON):\n{filename}\n\n{e}")
                 self.status_bar.showMessage("Error loading configuration: Invalid JSON.")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load configuration:\n{e}")
                self.status_bar.showMessage("Error loading configuration.")


    # --- Window Close Event ---
    def closeEvent(self, event):
        """Confirm exit if training is in progress."""
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Training is in progress. Stop training and exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_training()
                # Give kill signal a chance to be processed before closing window
                # Note: This might not guarantee the process is fully gone.
                QTimer.singleShot(500, self.close) # Try closing again shortly
                event.ignore() # Ignore the first close request
                # Alternative: event.accept() # Accept immediately, stop_training tries to kill
            else:
                event.ignore() # Don't close
        else:
            event.accept() # Close normally


if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Force dark style if available (useful on some systems)
    # app.setStyle("Fusion")
    window = YoloTrainerApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE training_enhanced.py ---