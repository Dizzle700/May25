"""
YOLO Dataset Creator - Main Entry Point (PyQt6)
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal, QSize

# Use local imports due to flat structure
from main_window import MainWindow
from app_logic import AppLogic

def main():
    # Set application information (optional but good practice)
    QCoreApplication.setApplicationName("YoloDatasetCreator")
    QCoreApplication.setOrganizationName("YoloCreatorOrg") # Replace as needed
    QCoreApplication.setApplicationVersion("0.2.0")

    # Create the Qt Application
    app = QApplication(sys.argv)

    # Apply a style (optional, Fusion often looks consistent)
    app.setStyle("Fusion")

    # Create the main window and application logic
    main_window = MainWindow()
    app_logic = AppLogic(main_window) # Pass main window instance to logic
    main_window.set_app_logic(app_logic) # Give main window a reference back to logic

    # Show the main window
    main_window.show()

    # Start the Qt event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    # Set environment variable for Qt scaling (optional, can help on high-DPI)
    # os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    # os.environ["QT_SCALE_FACTOR"] = "1" # Explicit scale factor

    main()

