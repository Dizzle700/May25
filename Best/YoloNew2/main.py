import sys
import os
import qdarkstyle
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Set environment variable for Qt scaling if needed (before QApplication)
# os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
# os.environ["QT_SCALE_FACTOR"] = "1" # Force specific scale
# os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1" # Alternative

from ui.main_window import MainWindow
from core.app_logic import AppLogic

# Ensure the 'core' directory is in the Python path if running from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def main():
    app = QApplication(sys.argv)

    # Enable High DPI support
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling) # Often default now
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)  # For sharper icons/images

    # Apply dark stylesheet
    # Make sure qdarkstyle is installed: pip install qdarkstyle
    try:
        app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt6'))
    except ImportError:
        print("Warning: qdarkstyle not found. Using default style.")
        # You could apply Qt's built-in Fusion style with a dark palette as a fallback
        # from PyQt6.QtGui import QPalette, QColor
        # from PyQt6.QtWidgets import QStyleFactory
        # app.setStyle(QStyleFactory.create('Fusion'))
        # dark_palette = QPalette()
        # # Customize dark_palette colors here... (complex)
        # app.setPalette(dark_palette)

    main_window = MainWindow()
    app_logic = AppLogic(main_window) # Link logic to UI
    main_window.set_app_logic(app_logic) # Allow UI to call logic

    main_window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()