import json
from typing import Dict
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QFileDialog, QMessageBox
from constants import CONFIG_FILE_FILTER

class ConfigManager:
    """Manages saving and loading of configuration files."""
    def __init__(self, parent: QWidget):
        self.parent = parent

    def save_config(self) -> None:
        """Save the current configuration to a JSON file."""
        config_data = {
            "version": "1.3",
            "basic_settings": {
                "data_yaml": self.parent.ui.data_yaml_path_edit.text(),
                "model": self.parent.ui.model_combo.currentText(),
                "epochs": self.parent.ui.epochs_spinbox.value(),
                "imgsz": self.parent.ui.imgsz_spinbox.value(),
                "batch": self.parent.ui.batch_spinbox.value(),
                "project": self.parent.ui.project_edit.text(),
                "name": self.parent.ui.name_edit.text(),
            },
            "advanced_settings": {
                "optimizer": self.parent.ui.optimizer_combo.currentText(),
                "lr0": self.parent.ui.lr0_spinbox.value(),
                "patience": self.parent.ui.patience_spinbox.value(),
                "mosaic": self.parent.ui.mosaic_checkbox.isChecked(),
                "mixup": self.parent.ui.mixup_checkbox.isChecked(),
                "degrees": self.parent.ui.degrees_spinbox.value(),
                "translate": self.parent.ui.translate_spinbox.value(),
                "scale": self.parent.ui.scale_spinbox.value(),
                "fliplr": self.parent.ui.fliplr_spinbox.value(),
                "additional_args": self.parent.ui.additional_args_edit.text(),
            },
            "environment": {
                "python_executable": self.parent.ui.python_path_edit.text(),
                "device": self.parent.ui.device_combo.currentText(),
            },
        }
        filename, _ = QFileDialog.getSaveFileName(self.parent, "Save Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4)
                self.parent.status_bar.showMessage(f"Configuration saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self.parent, "Save Error", f"Failed to save: {e}")
                self.parent.status_bar.showMessage("Error saving configuration.")

    def load_config(self) -> None:
        """Load a configuration from a JSON file."""
        filename, _ = QFileDialog.getOpenFileName(self.parent, "Load Configuration", "", CONFIG_FILE_FILTER)
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                if not isinstance(config_data, Dict):
                    raise ValueError("Invalid JSON format.")
                bs = config_data.get("basic_settings", {})
                self.parent.ui.data_yaml_path_edit.setText(bs.get("data_yaml", ""))
                self.parent.ui.model_combo.setCurrentText(bs.get("model", "yolov8s.pt"))
                self.parent.ui.epochs_spinbox.setValue(bs.get("epochs", 100))
                self.parent.ui.imgsz_spinbox.setValue(bs.get("imgsz", 640))
                self.parent.ui.batch_spinbox.setValue(bs.get("batch", 16))
                self.parent.ui.project_edit.setText(bs.get("project", ""))
                self.parent.ui.name_edit.setText(bs.get("name", ""))
                adv = config_data.get("advanced_settings", {})
                self.parent.ui.optimizer_combo.setCurrentText(adv.get("optimizer", "auto"))
                self.parent.ui.lr0_spinbox.setValue(adv.get("lr0", 0.01))
                self.parent.ui.patience_spinbox.setValue(adv.get("patience", 50))
                self.parent.ui.mosaic_checkbox.setChecked(adv.get("mosaic", True))
                self.parent.ui.mixup_checkbox.setChecked(adv.get("mixup", False))
                self.parent.ui.degrees_spinbox.setValue(adv.get("degrees", 0.0))
                self.parent.ui.translate_spinbox.setValue(adv.get("translate", 0.1))
                self.parent.ui.scale_spinbox.setValue(adv.get("scale", 0.5))
                self.parent.ui.fliplr_spinbox.setValue(adv.get("fliplr", 0.5))
                self.parent.ui.additional_args_edit.setText(adv.get("additional_args", ""))
                env = config_data.get("environment", {})
                self.parent.ui.python_path_edit.setText(env.get("python_executable", ""))
                self.parent.ui.device_combo.setCurrentText(env.get("device", "cpu"))
                self.parent._update_experiment_path_display()
                self.parent.status_bar.showMessage(f"Configuration loaded from {filename}")
            except Exception as e:
                QMessageBox.critical(self.parent, "Load Error", f"Failed to load: {e}")
                self.parent.status_bar.showMessage("Error loading configuration.")
