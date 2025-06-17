import sys
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QStatusBar
from PyQt6.QtCore import QFileSystemWatcher

from ui_components import YoloTrainerUI
from process_manager import TrainingProcessManager
from config_manager import ConfigManager
from constants import DEFAULT_PROJECT_NAME, DEFAULT_EXP_NAME, RESULTS_CSV_FILENAME

logging.basicConfig(filename="yolo_trainer.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class YoloTrainerApp(QWidget):
    """Main application window for YOLO training GUI."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO Trainer GUI (Enhanced v3)")
        self.setGeometry(100, 100, 1000, 900)

        self.process_manager: Optional[TrainingProcessManager] = None
        self.config_manager = ConfigManager(self)
        self.current_experiment_path: Optional[Path] = None
        self.results_csv_path: Optional[Path] = None
        self.fs_watcher = QFileSystemWatcher(self)
        self.fs_watcher.fileChanged.connect(self._handle_results_csv_update)

        self._init_ui()
        self._connect_signals()
        self._check_dependencies()
        logging.info("YOLO Trainer GUI initialized.")

    def _init_ui(self) -> None:
        """Initialize the main UI layout."""
        self.main_layout = QVBoxLayout(self)
        self.ui = YoloTrainerUI(self)
        self.main_layout.addWidget(self.ui.settings_tabs)
        self.main_layout.addLayout(self.ui.button_layout)
        self.main_layout.addWidget(self.ui.progress_bar)
        self.main_layout.addWidget(self.ui.output_tabs)
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready.")
        self.main_layout.addWidget(self.status_bar)

    def _connect_signals(self) -> None:
        """Connect UI signals to handlers."""
        self.ui.start_button.clicked.connect(self.start_training)
        self.ui.pause_button.clicked.connect(self.process_manager.toggle_pause if self.process_manager else lambda: None)
        self.ui.stop_button.clicked.connect(self.process_manager.stop_training if self.process_manager else lambda: None)
        self.ui.save_config_button.clicked.connect(self.config_manager.save_config)
        self.ui.load_config_button.clicked.connect(self.config_manager.load_config)
        self.ui.project_edit.textChanged.connect(self._update_experiment_path_display)
        self.ui.name_edit.textChanged.connect(self._update_experiment_path_display)
        self.ui.imgsz_spinbox.valueChanged.connect(self._validate_imgsz)
        self.ui.plot_button.clicked.connect(self._plot_metrics)

    def _check_dependencies(self) -> bool:
        """Check if required dependencies are available."""
        if not self.ui.python_executable or not Path(self.ui.python_executable).is_file():
            self.status_bar.showMessage("Error: Invalid Python executable.")
            self.ui.start_button.setEnabled(False)
            return False
        self.process_manager = TrainingProcessManager(self, self.ui.python_executable)
        self.status_bar.showMessage(f"Using Python: {self.ui.python_executable}")
        return True

    def _validate_imgsz(self, value: int) -> None:
        """Validate image size divisibility by 32."""
        if value % 32 != 0:
            self.status_bar.showMessage(f"Warning: Image size ({value}) must be divisible by 32")
            self.ui.imgsz_spinbox.setStyleSheet("border: 1px solid #FF5555")
        else:
            self.status_bar.clearMessage()
            self.ui.imgsz_spinbox.setStyleSheet("")

    def _update_experiment_path_display(self) -> None:
        """Update the experiment path display."""
        project = self.ui.project_edit.text().strip()
        name = self.ui.name_edit.text().strip()
        if project and name:
            base_dir = Path(__file__).parent
            self.current_experiment_path = base_dir / project / name
            self.ui.exp_path_label.setText(str(self.current_experiment_path.resolve()))
            self.ui.open_exp_folder_button.setEnabled(True)
            self.results_csv_path = self.current_experiment_path / RESULTS_CSV_FILENAME
        else:
            self.current_experiment_path = None
            self.results_csv_path = None
            self.ui.exp_path_label.setText("(Set Project and Experiment Name)")
            self.ui.open_exp_folder_button.setEnabled(False)

    def start_training(self) -> None:
        """Start the YOLO training process."""
        if not self.ui.validate_inputs():
            return
        if self.current_experiment_path:
            self.current_experiment_path.mkdir(parents=True, exist_ok=True)
        self.ui.metrics_table.setRowCount(0)
        self.ui.progress_bar.setValue(0)
        self.ui.progress_bar.setFormat("Starting...")
        self.ui.output_textedit.clear()
        self.process_manager.start_training(self.ui.get_training_args(), self.current_experiment_path)
        if self.results_csv_path:
            if self.results_csv_path.exists():
                self.fs_watcher.addPath(str(self.results_csv_path))
            else:
                self.fs_watcher.addPath(str(self.results_csv_path.parent))
        logging.info("Training started with args: %s", self.ui.get_training_args())

    def _handle_results_csv_update(self, path_str: str) -> None:
        """Handle updates to results.csv file."""
        if not self.results_csv_path or str(self.results_csv_path) != path_str:
            if self.results_csv_path and self.results_csv_path.exists():
                path_str = str(self.results_csv_path)
            else:
                if self.results_csv_path and str(self.results_csv_path) not in self.fs_watcher.files():
                    self.fs_watcher.addPath(str(self.results_csv_path))
                return
        try:
            with open(path_str, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader, None)  # Read headers if available
                for row in reader:
                    if not row:
                        continue
                    row_dict = dict(zip(headers, row)) if headers else {}
                    table_row = [
                        row_dict.get("epoch", row[0] if row else ""),
                        row_dict.get("train/box_loss", row[1] if len(row) > 1 else ""),
                        row_dict.get("train/cls_loss", row[2] if len(row) > 2 else ""),
                        row_dict.get("train/dfl_loss", row[3] if len(row) > 3 else ""),
                        row_dict.get("val/box_loss", row[8] if len(row) > 8 else ""),
                        row_dict.get("val/cls_loss", row[9] if len(row) > 9 else ""),
                        row_dict.get("val/dfl_loss", row[10] if len(row) > 10 else ""),
                        row_dict.get("metrics/mAP50(B)", row[6] if len(row) > 6 else ""),
                        row_dict.get("metrics/mAP50-95(B)", row[7] if len(row) > 7 else ""),
                        row_dict.get("lr/pg0", row[11] if len(row) > 11 else ""),
                    ]
                    row_pos = self.ui.metrics_table.rowCount()
                    self.ui.metrics_table.insertRow(row_pos)
                    for col, item_text in enumerate(table_row):
                        item = QTableWidgetItem(str(item_text).strip())
                        if col > 0:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.ui.metrics_table.setItem(row_pos, col, item)
                self.ui.metrics_table.resizeColumnsToContents()
                self.ui.metrics_table.scrollToBottom()
        except FileNotFoundError:
            self.ui.output_textedit.append(f"<font color='orange'>results.csv not found at: {path_str}</font>\n")
        except csv.Error as e:
            self.ui.output_textedit.append(f"<font color='red'>CSV parsing error: {e}</font>\n")
        except PermissionError:
            self.ui.output_textedit.append(f"<font color='red'>Permission denied accessing results.csv</font>\n")
        except Exception as e:
            self.ui.output_textedit.append(f"<font color='red'>Unexpected error reading results.csv: {e}</font>\n")
        logging.info("Processed results.csv update for path: %s", path_str)

    def _plot_metrics(self) -> None:
        """Generate a line plot for mAP50 metrics using Chart.js."""
        epochs = []
        map50 = []
        for row in range(self.ui.metrics_table.rowCount()):
            epoch = self.ui.metrics_table.item(row, 0)
            map50_val = self.ui.metrics_table.item(row, 7)
            if epoch and map50_val:
                try:
                    epochs.append(int(epoch.text()))
                    map50.append(float(map50_val.text()))
                except ValueError:
                    continue
        if not epochs:
            self.status_bar.showMessage("No valid data to plot.")
            return
        chart_html = f"""
        <canvas id="metricsChart"></canvas>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            new Chart(document.getElementById('metricsChart'), {{
                type: 'line',
                data: {{
                    labels: {epochs},
                    datasets: [{{
                        label: 'mAP50',
                        data: {map50},
                        borderColor: '#0078d7',
                        fill: false
                    }}]
                }},
                options: {{
                    responsive: true,
                    scales: {{
                        x: {{ title: {{ display: true, text: 'Epoch' }} }},
                        y: {{ title: {{ display: true, text: 'mAP50' }} }}
                    }}
                }}
            }});
        </script>
        """
        # TODO: Display chart in a QWebEngineView or save to file and open in browser
        self.status_bar.showMessage("Chart generation not fully implemented. See log for HTML.")
        logging.info("Generated Chart.js HTML: %s", chart_html)

    def closeEvent(self, event) -> None:
        """Handle window close event."""
        if self.process_manager and self.process_manager.is_running():
            reply = QMessageBox.question(
                self, "Confirm Exit", "Training is in progress. Stop and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.process_manager.stop_training()
                QTimer.singleShot(500, self.close)
                event.ignore()
            else:
                event.ignore()
        else:
            if self.fs_watcher.files():
                self.fs_watcher.removePaths(self.fs_watcher.files())
            if self.fs_watcher.directories():
                self.fs_watcher.removePaths(self.fs_watcher.directories())
            event.accept()
            logging.info("Application closed.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YoloTrainerApp()
    window.show()
    sys.exit(app.exec())