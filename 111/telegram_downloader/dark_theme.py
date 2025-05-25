# dark_theme.py - Contains styles for a dark theme
# Basic Dark Theme Stylesheet for PyQt6
DARK_STYLESHEET = """
QMainWindow {
    background-color: #2e2e2e;
    color: #cccccc;
}
QWidget {
    background-color: #2e2e2e;
    color: #cccccc;
    font-size: 10pt;
}
QLineEdit, QDateEdit, QTextEdit {
    padding: 8px;
    border: 1px solid #555555;
    border-radius: 4px;
    background-color: #3c3c3c;
    color: #cccccc;
    min-height: 25px;
}
QLineEdit:disabled, QDateEdit:disabled, QTextEdit:disabled {
    background-color: #333333;
    color: #777777;
}
QPushButton {
    padding: 8px 15px;
    border: 1px solid #0078d7;
    border-radius: 4px;
    background-color: #0078d7;
    color: white;
    min-width: 100px;
    min-height: 30px;
}
QPushButton:hover {
    background-color: #005a9e;
    border-color: #005a9e;
}
QPushButton:pressed {
    background-color: #003a6a;
    border-color: #003a6a;
}
QPushButton:disabled {
    background-color: #4a4a4a;
    border-color: #555555;
    color: #888888;
}
QLabel {
    padding: 2px;
    min-height: 20px;
    color: #cccccc; /* Ensure label text is light */
}
QLabel#auth_info_label { /* Specific styling for AuthCodeDialog label */
    font-weight: bold;
    color: #FFA07A; /* Light Salmon for warning */
}
QStatusBar {
    background-color: #1e1e1e;
    min-height: 25px;
    color: #cccccc;
}
QStatusBar QLabel {
    padding: 3px 5px;
    color: #cccccc;
}
QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #555555;
    background-color: #3c3c3c;
}
QDateEdit::down-arrow {
    image: url(noimg.png); /* Qt might require an image or use default system arrow */
}
QProgressBar {
    border: 1px solid #555555;
    border-radius: 4px;
    text-align: center;
    min-height: 25px;
    background-color: #3c3c3c;
    color: #cccccc;
}
QProgressBar::chunk {
    background-color: #0078d7;
    width: 1px;
    border-radius: 3px; /* Slightly rounded chunk */
}
QCheckBox {
    spacing: 8px; /* Increased spacing */
    color: #cccccc;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #3c3c3c;
}
QCheckBox::indicator:checked {
    background-color: #0078d7;
    border-color: #0078d7;
    /* image: url(:/icons/checkbox_checked.png); Optional: custom checkmark */
}
QCheckBox::indicator:unchecked {
    background-color: #3c3c3c;
}
QDialog {
    background-color: #2e2e2e;
}
QFormLayout QLabel { /* Ensure labels in form layouts are also styled */
    color: #cccccc;
}
QFileDialog { /* Attempt to style file dialog, though often system-dependent */
    background-color: #2e2e2e;
    color: #cccccc;
}
QMessageBox {
    background-color: #3c3c3c;
}
QMessageBox QLabel {
    color: #cccccc;
}
QTextEdit#pattern_editor { /* Specific ID for pattern editor styling */
    font-family: "Courier New", Courier, monospace;
}
"""