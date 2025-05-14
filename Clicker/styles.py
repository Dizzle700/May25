# styles.py

DARK_STYLE = """
QWidget {
    background-color: #2E2E2E;
    color: #E0E0E0;
    font-size: 10pt;
}

QMainWindow {
    background-color: #2E2E2E;
}

QMenuBar {
    background-color: #3C3C3C;
    color: #E0E0E0;
}

QMenuBar::item:selected {
    background-color: #5A5A5A;
}

QMenu {
    background-color: #3C3C3C;
    color: #E0E0E0;
}

QMenu::item:selected {
    background-color: #5A5A5A;
}

QLabel {
    color: #E0E0E0;
}

QPushButton {
    background-color: #5A5A5A;
    color: #E0E0E0;
    border: 1px solid #6A6A6A;
    padding: 5px 10px;
    border-radius: 4px;
    min-height: 20px; /* Ensure minimum height */
}

QPushButton:hover {
    background-color: #6A6A6A;
}

QPushButton:pressed {
    background-color: #4A4A4A;
}

QPushButton:disabled {
    background-color: #454545;
    color: #808080;
    border-color: #555555;
}

QPushButton:checked { /* For toggle buttons if used */
    background-color: #007ACC; /* Accent color */
    border: 1px solid #005C99;
}

QRadioButton::indicator {
    width: 12px;
    height: 12px;
}

QRadioButton::indicator::unchecked {
    border: 1px solid #808080;
    background-color: #454545;
    border-radius: 6px;
}

QRadioButton::indicator::checked {
    border: 1px solid #007ACC;
    background-color: #007ACC; /* Accent color */
    border-radius: 6px;
}

QListWidget {
    background-color: #3C3C3C;
    color: #E0E0E0;
    border: 1px solid #6A6A6A;
    border-radius: 4px;
    padding: 5px;
}

QListWidget::item:selected {
    background-color: #5A5A5A; /* Or accent color like #007ACC */
    color: #FFFFFF;
}

QSpinBox, QLineEdit {
    background-color: #3C3C3C;
    color: #E0E0E0;
    border: 1px solid #6A6A6A;
    border-radius: 4px;
    padding: 3px;
    min-height: 20px;
}

QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 16px;
    border: none;
    background-color: #5A5A5A;
}
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }

QSpinBox::up-arrow, QSpinBox::down-arrow {
    width: 10px;
    height: 10px;
    /* Consider using icon fonts or SVG for arrows */
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #6A6A6A;
}

QCheckBox::indicator {
    width: 13px;
    height: 13px;
}
QCheckBox::indicator:unchecked {
    border: 1px solid #808080;
    background-color: #454545;
    border-radius: 3px;
}
QCheckBox::indicator:checked {
    border: 1px solid #007ACC;
    background-color: #007ACC; /* Accent color */
    border-radius: 3px;
    /* Add checkmark image or use char */
    /* image: url(checkmark.png); */
}

QStatusBar {
    background-color: #3C3C3C;
    color: #E0E0E0;
}
"""