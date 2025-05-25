# main.py - Entry point for the Telegram Downloader application
import sys
import signal
from PyQt6.QtWidgets import QApplication

from utils import SETTINGS_ORGANIZATION, SETTINGS_APPNAME # For QSettings
from config_manager import ConfigManager
from database_manager import DatabaseManager
from ui_components import MainWindow
from dark_theme import DARK_STYLESHEET

def main():
    # Handles Ctrl+C in terminal for graceful exit
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setApplicationName(SETTINGS_APPNAME)

    # Apply Dark Theme
    app.setStyleSheet(DARK_STYLESHEET)

    # Initialize managers
    config_mngr = ConfigManager() # Reads/creates config.ini on init
    db_mngr = DatabaseManager()   # Creates/connects to .db on init

    if not config_mngr.ensure_telegram_config_exists():
        # MainWindow will show a more detailed warning, but this is an early check
        print(f"WARNING: Telegram configuration in '{config_mngr.filename}' is incomplete. Please edit it.")
        # The app will still launch, and MainWindow will guide the user.

    main_window = MainWindow(config_mngr, db_mngr)
    main_window.show()

    exit_code = app.exec()
    
    # db_mngr.close() is called in MainWindow's closeEvent
    sys.exit(exit_code)

if __name__ == "__main__":
    main()