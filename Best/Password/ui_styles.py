# ui_styles.py
DARK_STYLE_SHEET = """
QWidget {
    background-color: #2b2b2b;
    color: #f0f0f0;
    font-size: 10pt; /* Adjust as needed */
}

QMainWindow {
    background-color: #2b2b2b;
}

QToolBar {
    background-color: #3c3f41;
    border: none;
    padding: 3px;
}
QToolBar QToolButton {
    color: #f0f0f0;
    padding: 5px;
}
QToolBar QToolButton:hover {
    background-color: #4f5254;
}

/* --- Left Pane --- */
QListWidget {
    background-color: #3c3f41;
    border: 1px solid #4f5254;
    padding: 5px;
    outline: 0px; /* Remove focus outline */
}
QListWidget::item {
    padding: 5px;
}
QListWidget::item:selected {
    background-color: #4a6987; /* Selection color */
    color: #ffffff;
}
QListWidget::item:hover {
    background-color: #4f5254;
}

/* --- Right Pane --- */
QLineEdit, QTextEdit {
    background-color: #3c3f41;
    border: 1px solid #4f5254;
    padding: 5px;
    border-radius: 3px;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #4a6987;
}
QLineEdit[readOnly="true"] {
    background-color: #353535; /* Slightly different for read-only */
}

QLabel {
    color: #c0c0c0; /* Lighter grey for labels */
    padding-top: 5px;
}

QPushButton {
    background-color: #4a6987;
    color: #ffffff;
    border: none;
    padding: 8px 15px;
    border-radius: 3px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #5a7fa8;
}
QPushButton:pressed {
    background-color: #3a536b;
}
QPushButton#copyButton { /* Example of specific button ID */
    min-width: 50px;
    padding: 5px 8px;
}

QSplitter::handle {
    background-color: #4f5254;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}

QDialog {
    background-color: #2b2b2b;
}

/* Style for specific widgets if needed */
#searchLineEdit {
    padding: 5px;
}
"""