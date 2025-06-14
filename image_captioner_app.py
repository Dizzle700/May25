import sys
import os
import json
import pandas as pd
from datetime import datetime
from PIL import Image, UnidentifiedImageError

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit, QProgressBar,
    QMessageBox, QComboBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QTextCursor, QPixmap

# --- Google Gemini Imports ---
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions # More specific exception handling

# --- Styling ---
import qdarkstyle

# --- Constants ---
APP_NAME = "Gemini Image Captioner"
ORGANIZATION_NAME = "YourOrg" # Change if desired
DEFAULT_CAPTION_PROMPT = "Please describe this image in detail, focusing on elements that would be useful for recreating it, perhaps in an AI image generator like Midjourney."
SUPPORTED_IMAGE_TYPES = ('.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif') # Common vision model types
SETTINGS_API_KEY = "settings/apiKey"
SETTINGS_INPUT_DIR = "settings/inputDir"
SETTINGS_OUTPUT_PATH = "settings/outputPath"
SETTINGS_OUTPUT_FORMAT = "settings/outputFormat"
SETTINGS_CAPTION_PROMPT = "settings/captionPrompt"


# --- Worker Thread for Background Processing ---
class CaptionWorker(QThread):
    """Handles the background task of processing images and generating captions."""
    progressUpdated = pyqtSignal(int, int)  # current, total
    statusUpdated = pyqtSignal(str)
    errorOccurred = pyqtSignal(str, str) # filename, error message
    captionGenerated = pyqtSignal(str, str) # image_full_path, caption_or_error
    processingFinished = pyqtSignal(bool, str) # success (bool), final message

    def __init__(self, api_key, input_dir, output_path, output_format, prompt, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.input_dir = input_dir
        self.output_path = output_path
        self.output_format = output_format
        self.prompt = prompt
        self._is_running = True
        self.model = None
        self.results = []

    def stop(self):
        """Signals the thread to stop processing."""
        self._is_running = False
        self.statusUpdated.emit("Cancellation requested...")

    def _configure_gemini(self):
        """Configures the Gemini API client."""
        try:
            genai.configure(api_key=self.api_key)
            # Select the vision model
            self.model = genai.GenerativeModel('gemini-2.0-flash')
            self.statusUpdated.emit("Gemini API configured successfully.")
            return True
        except Exception as e:
            self.statusUpdated.emit(f"Error configuring Gemini API: {e}")
            self.processingFinished.emit(False, f"Failed to configure Gemini API: {e}")
            return False

    def _generate_caption(self, image_path):
        """Generates a caption for a single image."""
        try:
            img = Image.open(image_path)
            # Ensure model is ready
            if not self.model:
                self.errorOccurred.emit(os.path.basename(image_path), "Gemini model not initialized.")
                return "Error: Model not initialized"

            # Combine prompt and image for the API call
            response = self.model.generate_content([self.prompt, img], stream=False)
            # Handle potential safety blocks or empty responses explicitly
            if not response.parts:
                 # Check for safety ratings if parts are empty
                if response.prompt_feedback.safety_ratings:
                    blocked_reasons = [rating.category for rating in response.prompt_feedback.safety_ratings if rating.probability != 'NEGLIGIBLE']
                    if blocked_reasons:
                       block_reason_str = ", ".join(map(str,set(blocked_reasons))) # map to string and remove duplicates
                       self.errorOccurred.emit(os.path.basename(image_path), f"Blocked due to safety concerns: {block_reason_str}")
                       return f"Error: Blocked due to safety concerns ({block_reason_str})"
                # If no specific safety block, might be other issue or genuinely empty response
                self.errorOccurred.emit(os.path.basename(image_path), "Received an empty response from API.")
                return "Error: Empty response from API"

            # Assuming the first part contains the text caption
            caption = response.text # Use .text helper
            return caption

        except UnidentifiedImageError:
            self.errorOccurred.emit(os.path.basename(image_path), "Cannot identify image file (possibly corrupt or unsupported format).")
            return "Error: Cannot identify image file"
        except FileNotFoundError:
             self.errorOccurred.emit(os.path.basename(image_path), "Image file not found during processing.")
             return "Error: Image file not found"
        except google_exceptions.PermissionDenied:
            self.errorOccurred.emit(os.path.basename(image_path), "API Permission Denied. Check your API key and permissions.")
            self._is_running = False # Stop further processing on critical auth error
            return "Error: API Permission Denied"
        except google_exceptions.ResourceExhausted:
            self.errorOccurred.emit(os.path.basename(image_path), "API Quota Exceeded. Check your usage limits.")
            self._is_running = False # Stop further processing if quota hit
            return "Error: API Quota Exceeded"
        except google_exceptions.InvalidArgument as e:
            error_msg = f"API Invalid Argument: {e}. Check prompt or image format."
            self.errorOccurred.emit(os.path.basename(image_path), error_msg)
            return f"Error: API Invalid Argument ({e})"
        except google_exceptions.GoogleAPIError as e: # Catch other Google API errors
            error_msg = f"Google API Error: {e}"
            self.errorOccurred.emit(os.path.basename(image_path), error_msg)
            return f"Error: Google API Error ({e})"
        except Exception as e:
            self.errorOccurred.emit(os.path.basename(image_path), f"An unexpected error occurred: {e}")
            return f"Error: Unexpected error ({e})"

    def _save_results(self):
        """Saves the collected results to the specified format."""
        if not self.results:
            self.statusUpdated.emit("No results to save.")
            return True # Technically not an error, just nothing done

        df = pd.DataFrame(self.results)
        try:
            if self.output_format == "JSON":
                with open(self.output_path, 'w', encoding='utf-8') as f:
                    json.dump(self.results, f, ensure_ascii=False, indent=4)
            elif self.output_format == "Excel":
                # Ensure the directory exists for Excel saving
                output_dir = os.path.dirname(self.output_path)
                if output_dir: # Handle case where output is in current dir
                    os.makedirs(output_dir, exist_ok=True)
                df.to_excel(self.output_path, index=False, engine='openpyxl')
            else:
                 self.statusUpdated.emit(f"Error: Unknown output format '{self.output_format}'")
                 return False

            self.statusUpdated.emit(f"Results successfully saved to: {self.output_path}")
            return True
        except IOError as e:
            self.statusUpdated.emit(f"Error saving file: {e}")
            return False
        except Exception as e:
             self.statusUpdated.emit(f"An unexpected error occurred during saving: {e}")
             return False

    def run(self):
        """Main execution method for the thread."""
        self.statusUpdated.emit("Starting caption generation process...")
        if not self._configure_gemini():
            # processingFinished already emitted in _configure_gemini on error
            return

        if not os.path.isdir(self.input_dir):
            self.processingFinished.emit(False, f"Input directory not found: {self.input_dir}")
            return

        image_files = []
        self.statusUpdated.emit(f"Scanning input directory: {self.input_dir}")
        try:
            for filename in os.listdir(self.input_dir):
                if not self._is_running: break # Check for cancellation
                if filename.lower().endswith(SUPPORTED_IMAGE_TYPES):
                    image_files.append(os.path.join(self.input_dir, filename))
        except Exception as e:
             self.processingFinished.emit(False, f"Error scanning input directory: {e}")
             return

        if not image_files:
            self.processingFinished.emit(True, "No supported image files found in the input directory.")
            return

        total_files = len(image_files)
        self.progressUpdated.emit(0, total_files)
        self.statusUpdated.emit(f"Found {total_files} images to process.")
        self.results = [] # Reset results for this run

        for i, image_path in enumerate(image_files):
            if not self._is_running:
                self.statusUpdated.emit("Processing cancelled by user.")
                break # Exit loop if stopped

            self.statusUpdated.emit(f"Processing ({i + 1}/{total_files}): {os.path.basename(image_path)}")
            caption = self._generate_caption(image_path)

            # Check running status again *after* potentially blocking API call
            if not self._is_running:
                self.statusUpdated.emit("Processing cancelled by user during API call.")
                break

            # Emit caption as soon as it's generated
            self.captionGenerated.emit(image_path, caption)

            self.results.append({
                "image_path": image_path,
                "timestamp": datetime.now().isoformat(),
                "caption_or_error": caption
            })
            self.progressUpdated.emit(i + 1, total_files)
            # Optional: Add a small delay to avoid hitting rate limits too quickly
            # time.sleep(0.5)

        # --- End of loop ---

        if not self._is_running:
            # Don't save if cancelled
             self.processingFinished.emit(True, "Processing cancelled. Results not saved.")
        elif self.results:
             self.statusUpdated.emit("Saving results...")
             save_success = self._save_results()
             if save_success:
                 final_message = f"Processing finished. {len(self.results)} results saved to {self.output_path}"
                 self.processingFinished.emit(True, final_message)
             else:
                  final_message = f"Processing finished, but failed to save results. See log for details."
                  self.processingFinished.emit(False, final_message)
        else:
            # Ran to completion but generated no results (e.g., all errors, or cancelled before first success)
             self.processingFinished.emit(True, "Processing finished. No results were successfully generated or saved.")


# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setGeometry(100, 100, 900, 700) # Increased width to accommodate new layout

        self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self.worker = None # Placeholder for the worker thread
        self.processed_captions = {} # To store captions as they are generated

        self._initUI()
        self._loadSettings()
        self._updateControlsState() # Set initial button states

    def _initUI(self):
        """Initialize the graphical user interface elements."""
        centralWidget = QWidget(self)
        self.setCentralWidget(centralWidget)
        # Outermost layout for the central widget
        main_layout = QVBoxLayout(centralWidget)

        # Top area for the three panels
        top_panels_layout = QHBoxLayout()

        # --- Left Panel (Inputs, Controls, Progress) ---
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)

        # API Key
        apiLayout = QHBoxLayout()
        self.apiKeyLabel = QLabel("Google Gemini API Key:")
        self.apiKeyInput = QLineEdit()
        self.apiKeyInput.setEchoMode(QLineEdit.EchoMode.Password)
        self.apiKeyInput.setPlaceholderText("Enter your API key here")
        apiLayout.addWidget(self.apiKeyLabel)
        apiLayout.addWidget(self.apiKeyInput)
        left_panel_layout.addLayout(apiLayout)
        self.apiKeyWarningLabel = QLabel("<font color='yellow'>Warning: Saving API key is convenient but less secure.</font>")
        left_panel_layout.addWidget(self.apiKeyWarningLabel)

        # Input Folder
        inputLayout = QHBoxLayout()
        self.inputFolderLabel = QLabel("Input Image Folder:")
        self.inputFolderInput = QLineEdit()
        self.inputFolderInput.setReadOnly(True)
        self.inputFolderButton = QPushButton("Browse...")
        self.inputFolderButton.clicked.connect(self._browseInputFolder)
        inputLayout.addWidget(self.inputFolderLabel)
        inputLayout.addWidget(self.inputFolderInput)
        inputLayout.addWidget(self.inputFolderButton)
        left_panel_layout.addLayout(inputLayout)

        # Output File
        outputLayout = QHBoxLayout()
        self.outputFileLabel = QLabel("Output File:")
        self.outputFileInput = QLineEdit()
        self.outputFileInput.setPlaceholderText("Select output file path and format")
        self.outputFormatCombo = QComboBox()
        self.outputFormatCombo.addItems(["JSON", "Excel"])
        self.outputFileButton = QPushButton("Save As...")
        self.outputFileButton.clicked.connect(self._browseOutputFile)
        outputLayout.addWidget(self.outputFileLabel)
        outputLayout.addWidget(self.outputFileInput)
        outputLayout.addWidget(self.outputFormatCombo)
        outputLayout.addWidget(self.outputFileButton)
        left_panel_layout.addLayout(outputLayout)

        # Caption Prompt
        self.promptLabel = QLabel("Caption Prompt/Question:")
        left_panel_layout.addWidget(self.promptLabel)
        self.promptInput = QTextEdit()
        self.promptInput.setAcceptRichText(False)
        self.promptInput.setPlaceholderText(DEFAULT_CAPTION_PROMPT)
        self.promptInput.setFixedHeight(80)
        left_panel_layout.addWidget(self.promptInput)

        # Controls
        controlLayout = QHBoxLayout()
        self.startButton = QPushButton("Generate Captions")
        self.startButton.setStyleSheet("background-color: #4CAF50; color: white;")
        self.startButton.clicked.connect(self._startProcessing)
        self.cancelButton = QPushButton("Cancel Processing")
        self.cancelButton.setStyleSheet("background-color: #f44336; color: white;")
        self.cancelButton.setEnabled(False)
        self.cancelButton.clicked.connect(self._cancelProcessing)
        controlLayout.addWidget(self.startButton)
        controlLayout.addWidget(self.cancelButton)
        left_panel_layout.addLayout(controlLayout)

        # Progress Bar
        self.progressBar = QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(True)
        self.progressBar.setFormat("%p%")
        left_panel_layout.addWidget(self.progressBar)

        left_panel_layout.addStretch(1) # Add stretch to push content to the top
        top_panels_layout.addWidget(left_panel_widget, 1) # Stretch factor 1 for left panel

        # --- Center Panel (Image Display & Caption Display) ---
        center_panel_widget = QWidget()
        center_panel_layout = QVBoxLayout(center_panel_widget)

        self.image_display_label = QLabel("Image Display Area")
        self.image_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_display_label.setMinimumSize(300, 200) # Example size
        self.image_display_label.setStyleSheet("border: 1px solid gray;") # Placeholder border
        center_panel_layout.addWidget(self.image_display_label, 3) # Stretch factor for image area

        self.caption_display_text = QTextEdit("Caption for selected image will appear here.")
        self.caption_display_text.setReadOnly(True)
        self.caption_display_text.setFixedHeight(100) # Example size
        center_panel_layout.addWidget(self.caption_display_text, 1) # Stretch factor for caption area

        top_panels_layout.addWidget(center_panel_widget, 2) # Stretch factor 2 for center panel

        # --- Right Panel (Image List) ---
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)

        self.image_list_label = QLabel("Image List:")
        right_panel_layout.addWidget(self.image_list_label)
        self.image_list_widget = QListWidget()
        self.image_list_widget.setStyleSheet("border: 1px solid gray;") # Placeholder border
        self.image_list_widget.currentItemChanged.connect(self._onImageSelectionChanged) # Connect signal
        right_panel_layout.addWidget(self.image_list_widget)

        top_panels_layout.addWidget(right_panel_widget, 1) # Stretch factor 1 for right panel

        # Add the three-panel layout to the main vertical layout
        main_layout.addLayout(top_panels_layout)

        # --- Status Log (at the bottom) ---
        self.statusLabel = QLabel("Status Log:")
        main_layout.addWidget(self.statusLabel)
        self.statusLog = QTextEdit()
        self.statusLog.setReadOnly(True)
        self.statusLog.setFixedHeight(100) # Adjusted height for the new layout
        main_layout.addWidget(self.statusLog)

        # Connect signals for enabling/disabling start button
        self.apiKeyInput.textChanged.connect(lambda: self._updateControlsState())
        self.inputFolderInput.textChanged.connect(lambda: self._updateControlsState())
        self.outputFileInput.textChanged.connect(lambda: self._updateControlsState())

    def _loadSettings(self):
        """Load settings from QSettings."""
        self.apiKeyInput.setText(self.settings.value(SETTINGS_API_KEY, ""))
        loaded_input_dir = self.settings.value(SETTINGS_INPUT_DIR, "")
        self.inputFolderInput.setText(loaded_input_dir)
        self.outputFileInput.setText(self.settings.value(SETTINGS_OUTPUT_PATH, ""))
        self.promptInput.setText(self.settings.value(SETTINGS_CAPTION_PROMPT, DEFAULT_CAPTION_PROMPT))

        saved_format = self.settings.value(SETTINGS_OUTPUT_FORMAT, "JSON")
        index = self.outputFormatCombo.findText(saved_format, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self.outputFormatCombo.setCurrentIndex(index)

        self._logMessage("Settings loaded.")
        if loaded_input_dir and os.path.isdir(loaded_input_dir): # Populate image list if dir is valid
            self._populateImageList(loaded_input_dir)

    def _saveSettings(self):
        """Save current settings to QSettings."""
        self.settings.setValue(SETTINGS_API_KEY, self.apiKeyInput.text())
        self.settings.setValue(SETTINGS_INPUT_DIR, self.inputFolderInput.text())
        self.settings.setValue(SETTINGS_OUTPUT_PATH, self.outputFileInput.text())
        self.settings.setValue(SETTINGS_OUTPUT_FORMAT, self.outputFormatCombo.currentText())
        self.settings.setValue(SETTINGS_CAPTION_PROMPT, self.promptInput.toPlainText())
        self._logMessage("Settings saved.")

    def closeEvent(self, event):
        """Save settings when the application is closed."""
        self._saveSettings()
        # Ensure worker thread is stopped if running
        if self.worker and self.worker.isRunning():
             self._logMessage("Attempting to stop worker thread on close...")
             self.worker.stop()
             # Give the thread a moment to finish cleanly if possible
             if not self.worker.wait(1000): # Wait 1 second
                 self._logMessage("Worker thread did not stop gracefully. Forcing termination.")
                 # Force termination if it doesn't stop (less ideal)
                 self.worker.terminate()
                 self.worker.wait() # Wait for termination

        super().closeEvent(event)

    def _browseInputFolder(self):
        """Open dialog to select input folder."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Input Image Folder",
            self.inputFolderInput.text() or os.path.expanduser("~") # Start from previous or home
        )
        if directory:
            self.inputFolderInput.setText(directory)
            self._logMessage(f"Input folder selected: {directory}")
            self._populateImageList(directory) # Populate the list

    def _browseOutputFile(self):
        """Open dialog to select output file path and type."""
        current_path = self.outputFileInput.text()
        default_dir = os.path.dirname(current_path) if current_path else os.path.expanduser("~")
        selected_format = self.outputFormatCombo.currentText()
        file_filter = ""
        default_suffix = ""

        if selected_format == "JSON":
            file_filter = "JSON files (*.json)"
            default_suffix = ".json"
        elif selected_format == "Excel":
            file_filter = "Excel files (*.xlsx)"
            default_suffix = ".xlsx"

        filePath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output File As",
            os.path.join(default_dir, f"captions_output{default_suffix}"), # Suggest a filename
            file_filter
        )
        if filePath:
             # Ensure correct extension if user didn't type one
            if selected_format == "JSON" and not filePath.lower().endswith(".json"):
                filePath += ".json"
            elif selected_format == "Excel" and not filePath.lower().endswith(".xlsx"):
                filePath += ".xlsx"

            self.outputFileInput.setText(filePath)
            self._logMessage(f"Output file selected: {filePath}")

    def _populateImageList(self, directory_path):
        """Populate the image list widget with images from the given directory."""
        self.image_list_widget.clear()
        self.processed_captions.clear() # Clear old captions when list is repopulated
        self.image_display_label.setText("Image Display Area") # Reset image display
        self.image_display_label.setPixmap(QPixmap())        # Clear any existing pixmap
        self.caption_display_text.setText("Caption for selected image will appear here.") # Reset caption display

        self._logMessage(f"Scanning for images in: {directory_path}")
        found_count = 0
        try:
            if not os.path.isdir(directory_path):
                self._logMessage(f"Error: '{directory_path}' is not a valid directory.")
                return

            for filename in os.listdir(directory_path):
                if filename.lower().endswith(SUPPORTED_IMAGE_TYPES):
                    # Add full path as item data, display basename
                    item = QListWidgetItem(os.path.basename(filename))
                    item.setData(Qt.ItemDataRole.UserRole, os.path.join(directory_path, filename)) # Store full path
                    self.image_list_widget.addItem(item)
                    found_count += 1
            if found_count > 0:
                self._logMessage(f"Found {found_count} images in '{os.path.basename(directory_path)}'.")
            else:
                self._logMessage(f"No supported image files found in '{os.path.basename(directory_path)}'.")
        except Exception as e:
            self._logMessage(f"Error scanning directory '{directory_path}': {e}")

    def _onImageSelectionChanged(self, current_item, previous_item):
        """Handle selection change in the image list."""
        if current_item:
            full_path = current_item.data(Qt.ItemDataRole.UserRole)
            if full_path and os.path.exists(full_path):
                self._logMessage(f"Displaying image: {os.path.basename(full_path)}")
                try:
                    pixmap = QPixmap(full_path)
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(
                            self.image_display_label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        self.image_display_label.setPixmap(scaled_pixmap)
                        # Check for existing caption
                        if full_path in self.processed_captions:
                            self.caption_display_text.setText(self.processed_captions[full_path])
                        else:
                            self.caption_display_text.setText(f"Caption for {os.path.basename(full_path)} will appear here once processed.")
                    else:
                        self.image_display_label.setText(f"Error: Could not load image\n{os.path.basename(full_path)}")
                        self.caption_display_text.setText("Caption for selected image will appear here.")
                        self._logMessage(f"Error: QPixmap was null for {full_path}. Check image format/integrity.")
                except Exception as e:
                    self.image_display_label.setText(f"Error displaying image:\n{e}")
                    self.caption_display_text.setText("Caption for selected image will appear here.")
                    self._logMessage(f"Exception displaying image {full_path}: {e}")
            else:
                self.image_display_label.setText("Image file not found.")
                self.caption_display_text.setText("Caption for selected image will appear here.")
                if full_path:
                     self._logMessage(f"Error: Image path not found: {full_path}")
                else:
                    self._logMessage(f"Error: Current item has no valid path data.")

        else:
            self._logMessage("Image selection cleared.")
            self.image_display_label.setText("Image Display Area")
            self.image_display_label.setPixmap(QPixmap())
            self.caption_display_text.setText("Caption for selected image will appear here.")

    def _logMessage(self, message):
        """Append a message to the status log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.statusLog.append(f"[{timestamp}] {message}")
        self.statusLog.ensureCursorVisible() # Auto-scroll

    def _updateControlsState(self, processing=False):
        """Enable/disable controls based on input validity and processing state."""
        has_api_key = bool(self.apiKeyInput.text())
        has_input_dir = bool(self.inputFolderInput.text())
        has_output_path = bool(self.outputFileInput.text())
        can_start = has_api_key and has_input_dir and has_output_path

        self.startButton.setEnabled(can_start and not processing)
        self.cancelButton.setEnabled(processing)

        # Disable inputs while processing
        self.apiKeyInput.setEnabled(not processing)
        self.inputFolderButton.setEnabled(not processing)
        self.outputFileButton.setEnabled(not processing)
        self.outputFormatCombo.setEnabled(not processing)
        self.promptInput.setEnabled(not processing)


    def _validateInputs(self):
        """Perform basic validation before starting."""
        api_key = self.apiKeyInput.text()
        input_dir = self.inputFolderInput.text()
        output_path = self.outputFileInput.text()

        if not api_key:
            QMessageBox.warning(self, "Missing Input", "Please enter your Gemini API Key.")
            return False
        if not input_dir or not os.path.isdir(input_dir):
             QMessageBox.warning(self, "Invalid Input", "Please select a valid input folder.")
             return False
        if not output_path:
             QMessageBox.warning(self, "Missing Input", "Please specify an output file path.")
             return False

        # Check if output directory exists (if specified)
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            reply = QMessageBox.question(self, "Create Directory?",
                                         f"The output directory '{output_dir}' does not exist. Create it?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    self._logMessage(f"Created output directory: {output_dir}")
                except OSError as e:
                    QMessageBox.critical(self, "Error", f"Could not create output directory:\n{e}")
                    return False
            else:
                return False # User chose not to create directory

        return True

    def _startProcessing(self):
        """Start the image captioning process in a background thread."""
        if not self._validateInputs():
            return

        self._logMessage("Starting processing...")
        self._updateControlsState(processing=True) # Disable controls
        self.progressBar.setValue(0) # Reset progress bar
        self._saveSettings() # Save settings before starting
        self.processed_captions.clear() # Clear previous run's captions

        api_key = self.apiKeyInput.text()
        input_dir = self.inputFolderInput.text()
        output_path = self.outputFileInput.text()
        output_format = self.outputFormatCombo.currentText()
        prompt = self.promptInput.toPlainText() or DEFAULT_CAPTION_PROMPT

        # Create and start the worker thread
        self.worker = CaptionWorker(api_key, input_dir, output_path, output_format, prompt)

        # Connect worker signals to main thread slots
        self.worker.progressUpdated.connect(self._updateProgress)
        self.worker.statusUpdated.connect(self._logMessage)
        self.worker.errorOccurred.connect(self._handleWorkerError)
        self.worker.processingFinished.connect(self._handleProcessingFinished)
        self.worker.captionGenerated.connect(self._handleSingleCaptionGenerated) # Connect new signal
        self.worker.finished.connect(self._workerFinishedCleanup) # Optional: Signal when thread object itself finishes

        self.worker.start()

    def _cancelProcessing(self):
        """Request cancellation of the running worker thread."""
        if self.worker and self.worker.isRunning():
            self._logMessage("Sending stop signal to worker...")
            self.worker.stop()
            self.cancelButton.setEnabled(False) # Disable cancel button immediately
            # UI will be fully re-enabled in _handleProcessingFinished or _workerFinishedCleanup
        else:
             self._logMessage("No active process to cancel.")


    # --- Slots for Worker Signals ---

    def _updateProgress(self, current, total):
        """Update the progress bar."""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progressBar.setValue(percentage)
            self.progressBar.setFormat(f"%p% ({current}/{total})")
        else:
            self.progressBar.setValue(0)
            self.progressBar.setFormat("%p%")


    def _handleWorkerError(self, filename, error_message):
        """Log errors reported by the worker."""
        self._logMessage(f"ERROR processing '{filename}': {error_message}")

    def _handleProcessingFinished(self, success, message):
        """Handle the completion signal from the worker."""
        self._logMessage(message)
        if success:
            QMessageBox.information(self, "Processing Complete", message)
        else:
            QMessageBox.warning(self, "Processing Error", f"Processing encountered errors or failed.\nDetails: {message}\nCheck the status log for more information.")

        self.progressBar.setValue(100 if success else self.progressBar.value()) # Show 100% on success
        self.progressBar.setFormat("Finished" if success else "Finished with Errors")
        # Note: _workerFinishedCleanup will re-enable controls

    def _workerFinishedCleanup(self):
        """Slot connected to QThread.finished signal. Runs after run() exits."""
        self._logMessage("Worker thread finished execution.")
        # self.worker = None # Clear the worker reference - DO NOT DO THIS YET if results are needed
        self._updateControlsState(processing=False) # Re-enable controls

    def _handleSingleCaptionGenerated(self, image_path, caption_text):
        """Handles a caption generated for a single image by the worker."""
        self.processed_captions[image_path] = caption_text
        self._logMessage(f"Caption received for: {os.path.basename(image_path)}")

        # Check if this is the currently selected image
        current_list_item = self.image_list_widget.currentItem()
        if current_list_item:
            selected_image_path = current_list_item.data(Qt.ItemDataRole.UserRole)
            if selected_image_path == image_path:
                self.caption_display_text.setText(caption_text)


# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Apply dark style
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt6'))

    mainWindow = MainWindow()
    mainWindow.show()

    sys.exit(app.exec())