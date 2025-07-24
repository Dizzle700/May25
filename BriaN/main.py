import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QFile, QTextStream

# Import from other local .py files
from ui_components import MainWindow
from utils import check_dependencies, load_stylesheet, APP_CONFIG

def run_app():
    """
    Initializes and runs the PyQt6 application.
    """
    # 1. Check dependencies
    deps_ok, deps_msg = check_dependencies(APP_CONFIG["required_modules"])
    if not deps_ok:
        # For a GUI app, create a minimal QApplication to show an error box
        temp_app = QApplication.instance()
        if temp_app is None:
            temp_app = QApplication(sys.argv)
        QMessageBox.critical(None, "Dependency Error", deps_msg)
        sys.exit(1)

    app = QApplication(sys.argv)

    # Load stylesheet
    stylesheet_content = load_stylesheet(APP_CONFIG["stylesheet_path"])
    if stylesheet_content:
        app.setStyleSheet(stylesheet_content)
    else:
        print(f"Warning: Stylesheet not found or could not be loaded from {APP_CONFIG['stylesheet_path']}.")
        # Optionally provide a default fallback style or show a warning dialog
        QMessageBox.warning(None, "Styling Error", "Could not load the application theme. Using default system theme.")


    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    print(f"Starting {APP_CONFIG.get('app_name', 'Application')}...")
    run_app()