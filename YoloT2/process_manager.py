import os
import re
import logging
from typing import List, Optional
from pathlib import Path

from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtWidgets import QWidget, QMessageBox

class TrainingProcessManager:
    """Manages the YOLO training process."""
    def __init__(self, parent: QWidget, python_executable: str):
        self.parent = parent
        self.python_executable = python_executable
        self.process: Optional[QProcess] = None
        self.is_paused = False
        self.total_epochs = 1

    def start_training(self, train_args: List[str], experiment_path: Optional[Path]) -> None:
        """Start the training process."""
        if self.process:
            return
        self.process = QProcess(self.parent)
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.setWorkingDirectory(str(Path(__file__).parent))
        python_code = f"from ultralytics import YOLO; model = YOLO('{self.parent.ui.model_combo.currentText()}'); model.train({', '.join(train_args)})"
        self.process.setProgram(self.python_executable)
        self.process.setArguments(["-u", "-c", python_code])
        self.process.start()
        if self.process.waitForStarted(5000):
            self.parent.ui.output_textedit.append("Process started...\n")
            self.parent.ui.start_button.setEnabled(False)
            self.parent.ui.pause_button.setEnabled(True)
            self.parent.ui.stop_button.setEnabled(True)
            self.parent.status_bar.showMessage("Training in progress...")
        else:
            self.parent.ui.output_textedit.append(f"<font color='red'>Error: Failed to start process.</font>\n")
            self._process_finished()

    def stop_training(self) -> None:
        """Stop the training process."""
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.parent.ui.output_textedit.append("<hr><b>Stopping training...</b>\n")
            self.process.terminate()
            QTimer.singleShot(3000, self._kill_if_running)
            self.is_paused = False
            self.parent.ui.pause_button.setText("Pause")
            self.parent.ui.pause_button.setEnabled(False)

    def _kill_if_running(self) -> None:
        """Force kill the process if still running."""
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.parent.ui.output_textedit.append("<font color='orange'>Killing process...</font>\n")
            self.process.kill()

    def toggle_pause(self) -> None:
        """Toggle pause/resume for the training process."""
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return
        if os.name == "nt":
            QMessageBox.information(self.parent, "Pause Not Supported", "Pausing is not supported on Windows.")
            return
        pid = self.process.processId()
        if not pid:
            self.parent.ui.output_textedit.append("<font color='red'>Error: No process ID.</font>\n")
            return
        try:
            if not self.is_paused:
                os.kill(pid, 19)  # SIGSTOP
                self.is_paused = True
                self.parent.ui.pause_button.setText("Resume")
                self.parent.status_bar.showMessage("Training paused")
                self.parent.ui.output_textedit.append("<b>Training paused...</b>\n")
            else:
                os.kill(pid, 18)  # SIGCONT
                self.is_paused = False
                self.parent.ui.pause_button.setText("Pause")
                self.parent.status_bar.showMessage("Training resumed")
                self.parent.ui.output_textedit.append("<b>Training resumed...</b>\n")
        except OSError as e:
            self.parent.ui.output_textedit.append(f"<font color='orange'>Failed to pause/resume: {e}</font>\n")
            logging.error("Pause/resume failed: %s", e)

    def _handle_stdout(self) -> None:
        """Handle standard output from the process."""
        if not self.process:
            return
        data = self.process.readAllStandardOutput()
        try:
            text = data.data().decode("utf-8", errors="ignore")
            self._parse_stdout(text)
            self.parent.ui.output_textedit.insertPlainText(text)
        except Exception as e:
            self.parent.ui.output_textedit.append(f"<font color='red'>Stdout error: {e}</font>\n")
            logging.error("Stdout handling error: %s", e)

    def _handle_stderr(self) -> None:
        """Handle standard error from the process."""
        if not self.process:
            return
        data = self.process.readAllStandardError()
        try:
            text = data.data().decode("utf-8", errors="ignore")
            self.parent.ui.output_textedit.insertHtml(f"<font color='#FF8C00'>{text}</font>")
            if "error" in text.lower() or "traceback" in text.lower():
                self.parent.status_bar.showMessage("Error occurred during training.")
        except Exception as e:
            self.parent.ui.output_textedit.append(f"<font color='red'>Stderr error: {e}</font>\n")
            logging.error("Stderr handling error: %s", e)

    def _parse_stdout(self, text: str) -> None:
        """Parse stdout for progress updates."""
        pattern = r"^\s*(\d+)/(\d+)\s+"
        for line in text.splitlines():
            match = re.search(pattern, line.strip())
            if match:
                current_epoch, total_epochs = map(int, match.groups())
                self.total_epochs = total_epochs
                progress = int((current_epoch / total_epochs) * 100)
                self.parent.ui.progress_bar.setValue(progress)
                self.parent.ui.progress_bar.setFormat(f"Epoch {current_epoch}/{total_epochs} ({progress}%)")

    def _process_finished(self) -> None:
        """Handle process completion."""
        if not self.process:
            return
        exit_code = self.process.exitCode()
        if exit_code == 0:
            self.parent.status_bar.showMessage("Training finished successfully.")
            self.parent.ui.progress_bar.setValue(100)
            self.parent.ui.progress_bar.setFormat("Finished")
        else:
            self.parent.status_bar.showMessage(f"Training failed with code {exit_code}.")
            self.parent.ui.progress_bar.setFormat(f"Error (Code: {exit_code})")
        self.parent.ui.start_button.setEnabled(True)
        self.parent.ui.pause_button.setEnabled(False)
        self.parent.ui.stop_button.setEnabled(False)
        self.process = None
        logging.info("Training process finished with code: %s", exit_code)

    def is_running(self) -> bool:
        """Check if the process is running."""
        return self.process and self.process.state() == QProcess.ProcessState.Running
