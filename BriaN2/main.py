# main.py

import sys
from PyQt6.QtWidgets import QApplication

from app_window import AppWindow
from image_processor import ImageProcessor
from styles import STYLESHEET

def main():
    # --- Show a loading message in the console ---
    print("Loading BRIA RMBG-2.0 model... Please wait.")
    
    # Initialize the image processor (this can take a few seconds)
    try:
        image_processor = ImageProcessor()
    except Exception as e:
        print(f"Failed to load the model. Please check your internet connection and dependencies.")
        print(f"Error: {e}")
        # Optionally, show a critical error dialog here
        sys.exit(1)

    print("Model loaded successfully. Starting application.")

    app = QApplication(sys.argv)
    
    # Apply the modern stylesheet
    app.setStyleSheet(STYLESHEET)
    
    window = AppWindow(image_processor=image_processor)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()