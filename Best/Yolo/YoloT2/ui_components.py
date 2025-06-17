import sys
from typing import Dict, List
from pathlib import Path
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QTextEdit, QMessageBox,
    QProgressBar, QDoubleSpinBox, QCheckBox, QGroupBox, QTabWidget,
    QTableWidget, QTableWidgetItem
)
from PyQt6.QtCore import Qt
from constants import DARK_STYLESHEET, CONFIG_FILE_FILTER, DEFAULT_PROJECT_NAME, DEFAULT_EXP_NAME

class YoloTrainerUI:
    """Handles creation and management of UI components."""
    def __init__(self, parent: QWidget):
        self.parent = parent
        self.python_executable = self._find_python_executable()
        self.settings_tabs = QTabWidget()
        self.output_tabs = QTabWidget()
        self.button_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self._create_ui()
        self.apply_styles()

    def _find_python_executable(self) -> str:
        """Find the Python executable in virtual environments or system."""
        script_dir = Path(__file__).parent
        common_venv_paths = [
            script_dir / "venv" / "Scripts" / "python.exe",
            script_dir / "venv" / "bin" / "python",
            script_dir / ".venv" / "Scripts" / "python.exe",
            script_dir / ".venv" / "bin" / "python",
        ]
        for path in common_venv_paths:
            if path.is_file():
                return str(path)
        return sys.executable

    def _create_ui(self) -> None:
        """Create all UI components."""
        self._create_config_buttons()
        self._create_basic_settings_tab()
        self._create_advanced_settings_tab()
        self._create_environment_tab()
        self._create_action_buttons()
        self._create_progress_bar()
        self._create_output_tabs()

    def _create_config_buttons(self) -> None:
        """Create save/load config buttons."""
        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.setToolTip("Save current settings to a JSON file")
        self.load_config_button = QPushButton("Load Config")
        self.load_config_button.setToolTip("Load settings from a JSON file")
        config_layout = QHBoxLayout()
        config_layout.addStretch()
        config_layout.addWidget(self.save_config_button)
        config_layout.addWidget(self.load_config_button)
        self.button_layout.addLayout(config_layout)

    def _create_basic_settings_tab(self) -> None:
        """Create the Basic Settings tab."""
        basic_tab = QWidget()
        layout = QFormLayout(basic_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.data_yaml_path_edit = QLineEdit()
        self.data_yaml_path_edit.setPlaceholderText("Select dataset configuration file...")
        browse_data_button = QPushButton("Browse...")
        browse_data_button.clicked.connect(self._browse_data_yaml)
        data_layout = QHBoxLayout()
        data_layout.addWidget(self.data_yaml_path_edit)
        data_layout.addWidget(browse_data_button)
        layout.addRow("Dataset YAML:", data_layout)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.lineEdit().setPlaceholderText("Select or enter model (e.g., yolov8s.pt)")
        models = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"]
        self.model_combo.addItems(models)
        self.model_combo.setCurrentIndex(1)
        browse_model_button = QPushButton("Browse...")
        browse_model_button.clicked.connect(self._browse_model_pt)
        model_layout = QHBoxLayout()
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(browse_model_button)
        layout.addRow("Base Model:", model_layout)

        self.epochs_spinbox = QSpinBox()
        self.epochs_spinbox.setRange(1, 10000)
        self.epochs_spinbox.setValue(100)
        layout.addRow("Epochs:", self.epochs_spinbox)

        self.imgsz_spinbox = QSpinBox()
        self.imgsz_spinbox.setRange(32, 8192)
        self.imgsz_spinbox.setSingleStep(32)
        self.imgsz_spinbox.setValue(640)
        self.imgsz_spinbox.setToolTip("Image size must be divisible by 32")
        layout.addRow("Image Size (imgsz):", self.imgsz_spinbox)

        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(-1, 1024)
        self.batch_spinbox.setValue(16)
        self.batch_spinbox.setToolTip("Set to -1 for auto-batch")
        layout.addRow("Batch Size:", self.batch_spinbox)

        self.project_edit = QLineEdit(DEFAULT_PROJECT_NAME)
        self.project_edit.setPlaceholderText("Parent folder for experiments...")
        layout.addRow("Project Name:", self.project_edit)

        self.name_edit = QLineEdit(DEFAULT_EXP_NAME)
        self.name_edit.setPlaceholderText("Specific run name (subfolder)...")
        layout.addRow("Experiment Name:", self.name_edit)

        self.settings_tabs.addTab(basic_tab, "Basic Settings")

    def _create_advanced_settings_tab(self) -> None:
        """Create the Advanced Settings tab."""
        advanced_tab = QWidget()
        layout = QFormLayout(advanced_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.optimizer_combo = QComboBox()
        self.optimizer_combo.addItems(["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp"])
        self.optimizer_combo.setCurrentText("auto")
        self.optimizer_combo.setToolTip("Optimizer for training; 'auto' uses default")
        layout.addRow("Optimizer:", self.optimizer_combo)

        self.lr0_spinbox = QDoubleSpinBox()
        self.lr0_spinbox.setRange(0.0, 1.0)
        self.lr0_spinbox.setDecimals(5)
        self.lr0_spinbox.setSingleStep(0.001)
        self.lr0_spinbox.setValue(0.01)
        self.lr0_spinbox.setToolTip("Initial learning rate")
        layout.addRow("Learning Rate (lr0):", self.lr0_spinbox)

        self.patience_spinbox = QSpinBox()
        self.patience_spinbox.setRange(0, 1000)
        self.patience_spinbox.setValue(50)
        self.patience_spinbox.setToolTip("Epochs to wait without improvement before stopping (0 to disable)")
        layout.addRow("Patience:", self.patience_spinbox)

        aug_group = QGroupBox("Augmentation Parameters")
        aug_layout = QFormLayout(aug_group)
        self.mosaic_checkbox = QCheckBox("Enable Mosaic")
        self.mosaic_checkbox.setChecked(True)
        aug_layout.addRow(self.mosaic_checkbox)
        self.mixup_checkbox = QCheckBox("Enable MixUp")
        aug_layout.addRow(self.mixup_checkbox)
        self.degrees_spinbox = QDoubleSpinBox()
        self.degrees_spinbox.setRange(0.0, 180.0)
        self.degrees_spinbox.setValue(0.0)
        aug_layout.addRow("Degrees (+/-):", self.degrees_spinbox)
        self.translate_spinbox = QDoubleSpinBox()
        self.translate_spinbox.setRange(0.0, 0.9)
        self.translate_spinbox.setDecimals(3)
        self.translate_spinbox.setValue(0.1)
        aug_layout.addRow("Translate (+/-):", self.translate_spinbox)
        self.scale_spinbox = QDoubleSpinBox()
        self.scale_spinbox.setRange(0.0, 1.0)
        self.scale_spinbox.setDecimals(3)
        self.scale_spinbox.setValue(0.5)
        aug_layout.addRow("Scale (+/-):", self.scale_spinbox)
        self.fliplr_spinbox = QDoubleSpinBox()
        self.fliplr_spinbox.setRange(0.0, 1.0)
        self.fliplr_spinbox.setDecimals(2)
        self.fliplr_spinbox.setValue(0.5)
        aug_layout.addRow("Flip L/R Prob:", self.fliplr_spinbox)
        layout.addRow(aug_group)

        self.additional_args_edit = QLineEdit()
        self.additional_args_edit.setPlaceholderText("e.g., workers=8, save_period=5")
        self.additional_args_edit.setToolTip("Additional arguments as key=value, comma-separated")
        layout.addRow("Additional Args:", self.additional_args_edit)

        self.settings_tabs.addTab(advanced_tab, "Advanced Hyperparameters")

    def _create_environment_tab(self) -> None:
        """Create the Environment tab."""
        env_tab = QWidget()
        layout = QFormLayout(env_tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.python_path_edit = QLineEdit(self.python_executable)
        browse_python_button = QPushButton("Browse...")
        browse_python_button.clicked.connect(self._browse_python_executable)
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_path_edit)
        python_layout.addWidget(browse_python_button)
        layout.addRow("Python Executable:", python_layout)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu"])  # TODO: Dynamically populate with CUDA devices
        layout.addRow("Device:", self.device_combo)

        self.exp_path_label = QLabel("(Set Project and Experiment Name)")
        self.exp_path_label.setWordWrap(True)
        layout.addRow("Expected Exp. Path:", self.exp_path_label)

        self.open_exp_folder_button = QPushButton("Open Experiment Folder")
        self.open_exp_folder_button.setEnabled(False)
        layout.addRow(self.open_exp_folder_button)

        self.settings_tabs.addTab(env_tab, "Environment")

    def _create_action_buttons(self) -> None:
        """Create action buttons (Start, Pause, Stop)."""
        self.start_button = QPushButton("Start Training")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.stop_button = QPushButton("Stop Training")
        self.stop_button.setEnabled(False)
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.start_button)
        self.button_layout.addWidget(self.pause_button)
        self.button_layout.addWidget(self.stop_button)
        self.button_layout.addStretch()

    def _create_progress_bar(self) -> None:
        """Create the progress bar."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

    def _create_output_tabs(self) -> None:
        """Create output and metrics tabs."""
        self.output_tab = QWidget()
        output_layout = QVBoxLayout(self.output_tab)
        self.output_textedit = QTextEdit()
        self.output_textedit.setReadOnly(True)
        output_layout.addWidget(QLabel("Output Log:"))
        output_layout.addWidget(self.output_textedit)
        self.output_tabs.addTab(self.output_tab, "Output Log")

        self.metrics_tab = QWidget()
        metrics_layout = QVBoxLayout(self.metrics_tab)
        self.metrics_table = QTableWidget()
        headers = ["Epoch", "trn_box", "trn_cls", "trn_dfl", "val_box", "val_cls", "val_dfl", "mAP50", "mAP50-95", "LR(pg0)"]
        self.metrics_table.setColumnCount(len(headers))
        self.metrics_table.setHorizontalHeaderLabels(headers)
        self.metrics_table.setAlternatingRowColors(True)
        self.plot_button = QPushButton("Plot Metrics")
        metrics_layout.addWidget(QLabel("Training Metrics:"))
        metrics_layout.addWidget(self.metrics_table)
        metrics_layout.addWidget(self.plot_button)
        self.output_tabs.addTab(self.metrics_tab, "Training Metrics")

    def apply_styles(self) -> None:
        """Apply the stylesheet to the UI."""
        self.parent.setStyleSheet(DARK_STYLESHEET)

    def _browse_data_yaml(self) -> None:
        """Browse for dataset YAML file."""
        filename, _ = QFileDialog.getOpenFileName(self.parent, "Select Dataset YAML File", "", "YAML Files (*.yaml *.yml)")
        if filename:
            self.data_yaml_path_edit.setText(str(Path(filename)))

    def _browse_model_pt(self) -> None:
        """Browse for model .pt file."""
        filename, _ = QFileDialog.getOpenFileName(self.parent, "Select Model File", "", "PyTorch Model Files (*.pt)")
        if filename:
            filename = str(Path(filename))
            if self.model_combo.findText(filename) == -1:
                self.model_combo.addItem(filename)
            self.model_combo.setCurrentText(filename)

    def _browse_python_executable(self) -> None:
        """Browse for Python executable."""
        filename, _ = QFileDialog.getOpenFileName(self.parent, "Select Python Executable", "", "Python Executable (*)")
        if filename:
            self.python_path_edit.setText(str(Path(filename)))
            self.python_executable = filename

    def validate_inputs(self) -> bool:
        """Validate user inputs before starting training."""
        if not Path(self.data_yaml_path_edit.text()).is_file():
            QMessageBox.warning(self.parent, "Input Error", "Select a valid dataset YAML file.")
            self.settings_tabs.setCurrentIndex(0)
            self.data_yaml_path_edit.setFocus()
            return False
        model_text = self.model_combo.currentText()
        if not model_text:
            QMessageBox.warning(self.parent, "Input Error", "Select or enter a base model.")
            self.settings_tabs.setCurrentIndex(0)
            self.model_combo.setFocus()
            return False
        if "/" in model_text and not Path(model_text).is_file():
            QMessageBox.warning(self.parent, "Input Error", f"Model path not found: {model_text}")
            self.settings_tabs.setCurrentIndex(0)
            self.model_combo.setFocus()
            return False
        if self.imgsz_spinbox.value() % 32 != 0:
            QMessageBox.warning(self.parent, "Input Error", f"Image size must be divisible by 32.")
            self.settings_tabs.setCurrentIndex(0)
            self.imgsz_spinbox.setFocus()
            return False
        return True

    def get_training_args(self) -> List[str]:
        """Collect training arguments."""
        args = [
            f"data=r'{self.data_yaml_path_edit.text()}'",
            f"epochs={self.epochs_spinbox.value()}",
            f"imgsz={self.imgsz_spinbox.value()}",
            f"batch={self.batch_spinbox.value()}",
            f"device='{self.device_combo.currentText()}'",
            f"project=r'{self.project_edit.text().strip() or DEFAULT_PROJECT_NAME}'",
            f"name=r'{self.name_edit.text().strip() or DEFAULT_EXP_NAME}'",
        ]
        if self.optimizer_combo.currentText().lower() != "auto":
            args.append(f"optimizer='{self.optimizer_combo.currentText()}'")
        if self.lr0_spinbox.value() != 0.01:
            args.append(f"lr0={self.lr0_spinbox.value()}")
        if self.patience_spinbox.value() != 50:
            args.append(f"patience={self.patience_spinbox.value()}")
        if self.degrees_spinbox.value() != 0.0:
            args.append(f"degrees={self.degrees_spinbox.value()}")
        if self.translate_spinbox.value() != 0.1:
            args.append(f"translate={self.translate_spinbox.value()}")
        if self.scale_spinbox.value() != 0.5:
            args.append(f"scale={self.scale_spinbox.value()}")
        if self.fliplr_spinbox.value() != 0.5:
            args.append(f"fliplr={self.fliplr_spinbox.value()}")
        if not self.mosaic_checkbox.isChecked():
            args.append("mosaic=0.0")
        if self.mixup_checkbox.isChecked():
            args.append("mixup=0.1")
        additional_args = self.additional_args_edit.text().strip()
        if additional_args:
            arg_pattern = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*('[^']*'|[^'\s]+)\s*$")
            for arg in additional_args.split(","):
                arg = arg.strip()
                if arg and not arg_pattern.match(arg):
                    raise ValueError(f"Invalid argument format: '{arg}'. Expected 'key=value'.")
                args.append(arg)
        return args
