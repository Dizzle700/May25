# styles.py

STYLESHEET = """
QWidget {
    background-color: #2E2E2E;
    color: #E0E0E0;
    font-family: Arial, sans-serif;
    font-size: 11pt;
}

QMainWindow {
    border-image: none;
}

QPushButton {
    background-color: #4CAF50; /* Green */
    border: none;
    color: white;
    padding: 8px 16px;
    text-align: center;
    text-decoration: none;
    font-size: 12pt;
    margin: 4px 2px;
    border-radius: 8px;
}

QPushButton:hover {
    background-color: #45a049;
}

QPushButton:pressed {
    background-color: #3e8e41;
}

QPushButton:disabled {
    background-color: #555555;
    color: #888888;
}

#PauseButton[paused="true"] {
    background-color: #f44336; /* Red for Paused state */
}

#PauseButton[paused="true"]:hover {
    background-color: #e53935;
}

QListWidget {
    background-color: #3C3C3C;
    border: 1px solid #555555;
    padding: 5px;
    border-radius: 5px;
}

QListWidget::item {
    padding: 5px;
}

QListWidget::item:selected {
    background-color: #4CAF50;
    color: white;
}

QListWidget::item:hover {
    background-color: #4A4A4A;
}

QLabel {
    color: #E0E0E0;
    padding: 10px;
    background-color: #3C3C3C;
    border: 1px solid #555555;
    border-radius: 5px;
}

QStatusBar {
    font-size: 10pt;
}

QStatusBar::item {
    border: 0px solid black;
}

QProgressBar {
    border: 1px solid #555555;
    border-radius: 5px;
    text-align: center;
    background-color: #3C3C3C;
    color: #E0E0E0;
}

QProgressBar::chunk {
    background-color: #4CAF50;
    width: 10px;
    margin: 1px;
}

QCheckBox {
    spacing: 5px;
}

QCheckBox::indicator {
    width: 13px;
    height: 13px;
}

QCheckBox::indicator:unchecked {
    border: 1px solid #555555;
    background-color: #3C3C3C;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    background-color: #4CAF50;
    border: 1px solid #4CAF50;
    border-radius: 3px;
}
"""