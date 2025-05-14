import sys
import subprocess
import torch
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtCore import Qt


def get_driver_version():
    try:
        output = subprocess.check_output(["nvidia-smi"], encoding="utf-8")
        for line in output.split("\n"):
            if "Driver Version" in line:
                return line.strip()
        return "Driver version not found."
    except Exception as e:
        return f"nvidia-smi error: {e}"


def get_cuda_info():
    cuda_available = torch.cuda.is_available()
    result = f"CUDA Available: {cuda_available}\n"
    if cuda_available:
        result += f"GPU Name: {torch.cuda.get_device_name(0)}\n"
        result += f"CUDA Version (from torch): {torch.version.cuda}\n"
    else:
        result += "No CUDA-compatible GPU found.\n"
    return result


def get_torch_info():
    return f"PyTorch version: {torch.__version__}\n"


class InfoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CUDA & PyTorch Info")
        self.resize(500, 300)
        self.set_dark_theme()

        layout = QVBoxLayout()

        info = ""
        info += get_torch_info()
        info += get_cuda_info()
        info += get_driver_version()

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Consolas", 10))
        text_edit.setText(info)

        layout.addWidget(QLabel("System Info:"))
        layout.addWidget(text_edit)

        self.setLayout(layout)

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#121212"))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor("#2c2c2c"))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        self.setPalette(palette)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InfoWindow()
    window.show()
    sys.exit(app.exec())
