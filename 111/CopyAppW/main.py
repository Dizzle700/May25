import sys
from PyQt6.QtWidgets import QApplication
from main_window import FileCopierWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Можно применить стиль, например Fusion для более современного вида
    # app.setStyle("Fusion")
    
    window = FileCopierWindow()
    window.show()
    sys.exit(app.exec())