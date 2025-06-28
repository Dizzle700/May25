import sys
import google.generativeai as genai
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextEdit, QMessageBox, QFileDialog
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QSettings

# 1. --- STYLESHEET FOR A MODERN DARK THEME ---
# A custom QSS (similar to CSS) for styling the application.
DARK_STYLE = """
QWidget {
    background-color: #2b2b2b;
    color: #f0f0f0;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 15px;
}
QMainWindow {
    background-color: #2b2b2b;
}
QLabel {
    font-weight: bold;
}
QLineEdit {
    background-color: #3c3f41;
    border: 1px solid #555;
    border-radius: 5px;
    padding: 8px;
}
QLineEdit:focus {
    border: 1px solid #007bff;
}
QTextEdit {
    background-color: #3c3f41;
    border: 1px solid #555;
    border-radius: 5px;
    padding: 8px;
}
QPushButton {
    background-color: #007bff;
    color: white;
    border: none;
    border-radius: 5px;
    padding: 10px 15px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #0056b3;
}
QPushButton:pressed {
    background-color: #004494;
}
QPushButton:disabled {
    background-color: #555;
    color: #aaa;
}
QMessageBox {
    background-color: #3c3f41;
}
"""

class GeminiModelFetcherApp(QMainWindow):
    """
    A PyQt6 application to fetch and display available Google Gemini models.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gemini Model Fetcher")
        self.setGeometry(100, 100, 700, 600)
        
        # This will hold the successfully fetched models list
        self.models_list = None
        
        # Initialize QSettings for remembering state
        self.settings = QSettings("MyCompany", "GeminiModelFetcherApp") # Use your company/app name

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        """Set up the user interface."""
        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # --- API Key Input Section ---
        api_key_layout = QHBoxLayout()
        api_key_label = QLabel("Gemini API Key:")
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter your API key here...")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(api_key_label)
        api_key_layout.addWidget(self.api_key_input)

        # --- Action Buttons Section ---
        buttons_layout = QHBoxLayout()
        self.fetch_button = QPushButton("Fetch Available Models")
        self.fetch_button.clicked.connect(self.fetch_models)
        
        self.save_button = QPushButton("Save to TXT")
        self.save_button.clicked.connect(self.save_to_txt)
        self.save_button.setEnabled(False) # Disabled until models are fetched

        buttons_layout.addWidget(self.fetch_button)
        buttons_layout.addStretch() # Add a spacer
        buttons_layout.addWidget(self.save_button)

        # --- Results Display Section ---
        results_label = QLabel("Available Models:")
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.setPlaceholderText("Models will be listed here after fetching...")

        # --- Add all widgets to the main layout ---
        main_layout.addLayout(api_key_layout)
        main_layout.addLayout(buttons_layout)
        main_layout.addWidget(results_label)
        main_layout.addWidget(self.results_display)

    def load_settings(self):
        """Loads application settings."""
        api_key = self.settings.value("api_key", "")
        self.api_key_input.setText(api_key)

    def save_settings(self):
        """Saves application settings."""
        self.settings.setValue("api_key", self.api_key_input.text().strip())

    def closeEvent(self, event):
        """Overrides the close event to save settings."""
        self.save_settings()
        event.accept()

    def fetch_models(self):
        """Handles the 'Fetch Models' button click."""
        api_key = self.api_key_input.text().strip()

        if not api_key:
            QMessageBox.warning(self, "API Key Missing", "Please enter your Gemini API key.")
            return

        # Provide feedback to the user that something is happening
        self.results_display.setText("Fetching, please wait...")
        QApplication.processEvents() # Update the GUI immediately

        try:
            # Configure the Gemini client with the provided API key
            genai.configure(api_key=api_key)

            # Fetch the list of models
            self.models_list = genai.list_models()
            
            # Format the output for display
            display_text = ""
            for model in self.models_list:
                # We'll focus on models that support 'generateContent'
                if 'generateContent' in model.supported_generation_methods:
                    display_text += f"Model Name: {model.name}\n"
                    display_text += f"Display Name: {model.display_name}\n"
                    display_text += f"Description: {model.description}\n"
                    display_text += f"Input Tokens: {model.input_token_limit} | Output Tokens: {model.output_token_limit}\n"
                    display_text += "-" * 60 + "\n\n"
            
            if not display_text:
                self.results_display.setText("No models supporting 'generateContent' found.")
                self.save_button.setEnabled(False)
            else:
                self.results_display.setText(display_text)
                self.save_button.setEnabled(True) # Enable saving
                QMessageBox.information(self, "Success", f"Successfully fetched models.")

        except Exception as e:
            # Handle potential errors (e.g., invalid key, network issues)
            self.results_display.setText(f"An error occurred:\n\n{str(e)}")
            self.save_button.setEnabled(False) # Disable saving on error
            QMessageBox.critical(self, "Error", f"Failed to fetch models. Please check your API key and network connection.\n\nDetails: {e}")

    def save_to_txt(self):
        """Handles the 'Save to TXT' button click."""
        text_to_save = self.results_display.toPlainText()
        if not text_to_save or not self.models_list:
            QMessageBox.warning(self, "No Data", "There is no data to save.")
            return

        # Open a file dialog to choose where to save the file
        file_path, _ = QFileDialog.getSaveFileName(self, 
                                                   "Save Models List", 
                                                   "gemini_models.txt",
                                                   "Text Files (*.txt);;All Files (*)", 
                                                   options=QFileDialog.Option.DontUseNativeDialog)

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"--- Available Gemini Models ---\n\n")
                    f.write(text_to_save)
                QMessageBox.information(self, "Success", f"Model list saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save the file.\n\nError: {e}")

# 2. --- MAIN EXECUTION BLOCK ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Apply the dark stylesheet to the entire application
    app.setStyleSheet(DARK_STYLE)
    
    # Set an application icon (optional, but good practice)
    # You would need an 'icon.png' file in the same directory for this to work.
    # app.setWindowIcon(QIcon('icon.png'))

    window = GeminiModelFetcherApp()
    window.show()
    sys.exit(app.exec())
