"""Constants for the YOLO Trainer GUI."""
CONFIG_FILE_FILTER = "JSON Config Files (*.json)"
DEFAULT_PROJECT_NAME = "runs/train"
DEFAULT_EXP_NAME = "exp"
RESULTS_CSV_FILENAME = "results.csv"

DARK_STYLESHEET = """
QWidget { background-color: #2e2e2e; color: #e0e0e0; font-size: 10pt; }
QPushButton { background-color: #555555; border: 1px solid #777777; padding: 5px 10px; border-radius: 4px; min-width: 80px; }
QPushButton:hover { background-color: #666666; border: 1px solid #888888; }
QLineEdit, QSpinBox, QComboBox, QTextEdit, QDoubleSpinBox { background-color: #3c3c3c; border: 1px solid #555555; padding: 4px; border-radius: 3px; color: #e0e0e0; }
QProgressBar { border: 1px solid #555555; border-radius: 3px; text-align: center; background-color: #3c3c3c; color: #e0e0e0; }
QProgressBar::chunk { background-color: #0078d7; border-radius: 3px; }
QTableWidget { background-color: #3c3c3c; alternate-background-color: #444444; border: 1px solid #555555; color: #e0e0e0; }
"""