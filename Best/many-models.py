import sys
import os
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QComboBox, QFileDialog, QProgressBar, 
                            QScrollArea, QGridLayout, QMessageBox, QTabWidget, QGroupBox,
                            QFrame, QSizePolicy, QLayout, QTextEdit, QDialog)
from PyQt5.QtGui import QPixmap, QImage, QFont, QPalette, QColor, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint
from PIL import Image
from transformers import pipeline
import torch

# List of supported models - just the model IDs from the original
MODELS = [
    "google/vit-base-patch16-224",
    "nateraw/vit-age-classifier",
    "microsoft/resnet-50",
    "Falconsai/nsfw_image_detection",
    "cafeai/cafe_aesthetic",
    "microsoft/resnet-18",
    "microsoft/resnet-34",
    "microsoft/resnet-101",
    "microsoft/resnet-152",
    "microsoft/swin-tiny-patch4-window7-224",
    "microsoft/beit-base-patch16-224-pt22k-ft22k",
    "facebook/convnext-large-224",
    "timm/resnet50.a1_in1k",
    "timm/mobilenetv3_large_100.ra_in1k",
    "trpakov/vit-face-expression",
    "rizvandwiki/gender-classification",
    "LukeJacob2023/nsfw-image-detector",
    "vit-base-patch16-224-in21k",
    "not-lain/deepfake",
    "carbon225/vit-base-patch16-224-hentai",
    "facebook/convnext-base-224-22k-1k",
    "facebook/convnext-tiny-224",
    "nvidia/mit-b0",
    "microsoft/swinv2-base-patch4-window16-256",
    "andupets/real-estate-image-classification",
    "timm/tf_efficientnetv2_s.in21k",
    "timm/convnext_tiny.fb_in22k",
    "DunnBC22/vit-base-patch16-224-in21k_Human_Activity_Recognition",
    "FatihC/swin-tiny-patch4-window7-224-finetuned-eurosat-watermark",
    "aalonso-developer/vit-base-patch16-224-in21k-clothing-classifier",
    "RickyIG/emotion_face_image_classification",
    "shadowlilac/aesthetic-shadow"
]

MIN_ACCEPTABLE_SCORE = 0.1
MAX_N_LABELS = 5

# Define application colors
COLORS = {
    "primary": "#4a6eb0",  # Primary blue
    "secondary": "#8a56ac",  # Secondary purple
    "accent": "#56aaa8",  # Accent teal
    "background": "#f5f7fa",  # Light gray background
    "text": "#333333",  # Dark text
    "success": "#5cb85c",  # Success green
    "warning": "#f0ad4e",  # Warning yellow
    "error": "#d9534f",  # Error red
    "cached_model": "#d9edf7",  # Light blue for cached models
    "widget_bg": "#ffffff",  # White for widget backgrounds
    "button_hover": "#3d5e94"  # Darker blue for button hover
}

class RoundedProgressBar(QProgressBar):
    """Custom progress bar with rounded corners"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(True)
        self.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #ccc;
                border-radius: 7px;
                text-align: center;
                background-color: {COLORS["widget_bg"]};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS["primary"]};
                border-radius: 7px;
            }}
        """)

class RoundedButton(QPushButton):
    """Custom button with rounded corners"""
    def __init__(self, text, parent=None, color=COLORS["primary"]):
        super().__init__(text, parent)
        self.setMinimumHeight(36)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 18px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS["button_hover"]};
            }}
            QPushButton:disabled {{
                background-color: #cccccc;
            }}
        """)

class RoundedComboBox(QComboBox):
    """Custom combobox with rounded corners"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #ccc;
                border-radius: 18px;
                padding: 0px 10px;
                background-color: {COLORS["widget_bg"]};
                min-width: 6em;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 0px;
                border-top-right-radius: 18px;
                border-bottom-right-radius: 18px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid #ccc;
                border-radius: 5px;
                selection-background-color: {COLORS["primary"]};
            }}
        """)

class RoundedGroupBox(QGroupBox):
    """Custom group box with rounded corners"""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 10px;
                margin-top: 1ex;
                background-color: {COLORS["widget_bg"]};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {COLORS["primary"]};
            }}
        """)

class ImageThumbnail(QFrame):
    """Custom image thumbnail with classification results"""
    def __init__(self, image_path, result, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.result = result
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.setMinimumSize(180, 180)
        self.setMaximumSize(200, 250)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #ccc;
                border-radius: 10px;
                padding: 5px;
                background-color: {COLORS["widget_bg"]};
            }}
            QLabel {{
                color: {COLORS["text"]};
                font-size: 9pt;
            }}
        """)
        
        # Create layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(3, 3, 3, 3)
        self.layout.setSpacing(3)
        
        # Image thumbnail
        self.image_label = QLabel()
        self.update_image(140)  # Default size
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(140)
        self.layout.addWidget(self.image_label)
        
        # Filename
        filename = os.path.basename(image_path)
        if len(filename) > 15:
            filename = filename[:12] + "..."
        self.filename_label = QLabel(filename)
        self.filename_label.setAlignment(Qt.AlignCenter)
        self.filename_label.setWordWrap(True)
        self.layout.addWidget(self.filename_label)
        
        # Top classification
        classifications = result['classifications']
        if classifications:
            top_label = classifications[0]['label']
            top_score = classifications[0]['score']
            if len(top_label) > 20:
                top_label = top_label[:17] + "..."
            self.result_text = QLabel(f"{top_label}\n({top_score:.2f})")
            self.result_text.setAlignment(Qt.AlignCenter)
            self.result_text.setStyleSheet(f"font-weight: bold; color: {COLORS['primary']};")
            self.layout.addWidget(self.result_text)
    
    def update_image(self, size):
        """Update the image with the specified size"""
        pixmap = QPixmap(self.image_path)
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.image_label.setMinimumHeight(size)
    
    def resizeEvent(self, event):
        """Handle resize events to update the image size"""
        super().resizeEvent(event)
        # Adjust image size based on the new widget size
        new_size = min(self.width() - 20, self.height() - 60)
        if new_size > 0:
            self.update_image(new_size)

class ClassificationWorker(QThread):
    """Worker thread to handle image classification to keep UI responsive"""
    progress_update = pyqtSignal(int, int)  # current, total
    result_ready = pyqtSignal(list)
    finished_all = pyqtSignal()
    
    def __init__(self, model_path, image_paths, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.image_paths = image_paths
        self.results = []
        
    def run(self):
        try:
            # Initialize the classifier
            classifier = pipeline("image-classification", model=self.model_path)
            
            for i, img_path in enumerate(self.image_paths):
                try:
                    image = Image.open(img_path)
                    result = classifier(image)
                    
                    # Add filename to results
                    result_with_filename = {
                        'filename': os.path.basename(img_path),
                        'path': img_path,
                        'classifications': result
                    }
                    self.results.append(result_with_filename)
                    
                    # Emit progress
                    self.progress_update.emit(i + 1, len(self.image_paths))
                    
                    # Emit result for display
                    self.result_ready.emit([result_with_filename])
                    
                except Exception as e:
                    print(f"Error processing {img_path}: {str(e)}")
                    
            self.finished_all.emit()
                
        except Exception as e:
            print(f"Error initializing model: {str(e)}")
            self.finished_all.emit()

class FlowLayout(QLayout):
    """Custom flow layout for gallery view"""
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.itemList = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x() + self.contentsMargins().left()
        y = rect.y() + self.contentsMargins().top()
        lineHeight = 0

        for item in self.itemList:
            wid = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x() + self.contentsMargins().left()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y() + self.contentsMargins().bottom()

class ImageClassifierApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Batch Image Classifier")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet(f"background-color: {COLORS['background']};")
        
        self.cached_models = []
        self.refresh_cached_models()
        
        self.init_ui()
        
        # Store classification results for export
        self.all_results = []
        
    def refresh_cached_models(self):
        """Get list of locally cached models"""
        self.cached_models = []
        if os.path.exists("models"):
            for item in os.listdir("models"):
                if os.path.isdir(os.path.join("models", item)):
                    # Convert the directory name back to model ID format
                    model_id = item.replace("_", "/")
                    if model_id in MODELS:
                        self.cached_models.append(model_id)
        
    def init_ui(self):
        # Create a scroll area for the main content
        main_scroll_area = QScrollArea()
        main_scroll_area.setWidgetResizable(True)
        main_scroll_area.setFrameShape(QFrame.NoFrame)
        main_scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {COLORS['background']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {COLORS['background']};
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['primary']};
                min-height: 20px;
                border-radius: 5px;
            }}
        """)
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create a horizontal layout for model selection and log
        top_row_layout = QHBoxLayout()
        top_row_layout.setSpacing(10)
        
        # Add model selection area at the left - more compact
        model_group = RoundedGroupBox("Model")
        model_layout = QHBoxLayout()
        model_layout.setSpacing(5)
        model_layout.setContentsMargins(5, 5, 5, 5)
        
        # Model selector - more compact
        self.model_selector = RoundedComboBox()
        self.model_selector.setMaximumHeight(30)
        
        for model in MODELS:
            self.model_selector.addItem(model)
            # Highlight cached models
            if model in self.cached_models:
                index = self.model_selector.findText(model)
                self.model_selector.setItemData(index, QColor(COLORS['cached_model']), Qt.BackgroundRole)
                # Add a visual indicator to the text
                self.model_selector.setItemText(index, f"✓ {model}")
        
        model_layout.addWidget(self.model_selector, 3)
        
        # Download model button - more compact
        self.download_model_btn = RoundedButton("Download")
        self.download_model_btn.setMaximumHeight(30)
        self.download_model_btn.clicked.connect(self.download_model)
        model_layout.addWidget(self.download_model_btn, 1)
        
        model_group.setLayout(model_layout)
        model_group.setMaximumHeight(60)
        top_row_layout.addWidget(model_group, 2)
        
        # Add log window at the right - more compact
        log_group = RoundedGroupBox("Log")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(5, 5, 5, 5)
        
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setStyleSheet(f"""
            background-color: {COLORS['widget_bg']};
            color: {COLORS['text']};
            border-radius: 5px;
            padding: 5px;
            font-size: 9pt;
        """)
        self.log_window.setMaximumHeight(60)
        log_layout.addWidget(self.log_window)
        
        log_group.setLayout(log_layout)
        log_group.setMaximumHeight(60)
        top_row_layout.addWidget(log_group, 3)
        
        # Add the top row to the main layout
        main_layout.addLayout(top_row_layout)
        
        # Create layout for the batch processing tab
        self.batch_process_tab = QWidget()
        
        # Setup batch processing tab
        self.setup_batch_process_tab()
        
        # Add the batch processing tab directly to the main layout
        main_layout.addWidget(self.batch_process_tab)
        
        # Add initial log message
        self.log("Application started")
        
        main_widget.setLayout(main_layout)
        
        # Set the main widget as the scroll area's widget
        main_scroll_area.setWidget(main_widget)
        
        # Set the scroll area as the central widget
        self.setCentralWidget(main_scroll_area)
        
    def setup_batch_process_tab(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Top controls in a horizontal layout
        top_controls = QHBoxLayout()
        top_controls.setSpacing(5)
        
        # Folder selection
        folder_select_layout = QHBoxLayout()
        folder_select_layout.setSpacing(5)
        folder_select_label = QLabel("Folder:")
        folder_select_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: bold;")
        folder_select_layout.addWidget(folder_select_label)
        
        self.folder_path_label = QLabel("No folder selected")
        self.folder_path_label.setStyleSheet(f"""
            border: 1px solid #ccc;
            border-radius: 10px;
            padding: 5px;
            background-color: {COLORS['widget_bg']};
        """)
        folder_select_layout.addWidget(self.folder_path_label, 1)
        
        self.browse_folder_btn = RoundedButton("Browse")
        self.browse_folder_btn.setMaximumHeight(30)
        self.browse_folder_btn.clicked.connect(self.select_image_folder)
        folder_select_layout.addWidget(self.browse_folder_btn)
        
        top_controls.addLayout(folder_select_layout, 2)
        
        # Batch process buttons
        batch_btn_layout = QHBoxLayout()
        batch_btn_layout.setSpacing(5)
        
        self.process_batch_btn = RoundedButton("Process", color=COLORS["accent"])
        self.process_batch_btn.setMaximumHeight(30)
        self.process_batch_btn.clicked.connect(self.process_image_batch)
        batch_btn_layout.addWidget(self.process_batch_btn)
        
        self.export_excel_btn = RoundedButton("Export", color=COLORS["success"])
        self.export_excel_btn.setMaximumHeight(30)
        self.export_excel_btn.clicked.connect(self.export_to_excel)
        self.export_excel_btn.setEnabled(False)
        batch_btn_layout.addWidget(self.export_excel_btn)
        
        top_controls.addLayout(batch_btn_layout, 1)
        
        layout.addLayout(top_controls)
        
        # Progress bar in a horizontal layout with label
        progress_layout = QHBoxLayout()
        
        self.batch_progress = RoundedProgressBar()
        self.batch_progress.setValue(0)
        self.batch_progress.setMaximumHeight(20)
        progress_layout.addWidget(self.batch_progress, 3)
        
        self.progress_label = QLabel("Ready")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet(f"color: {COLORS['text']};")
        self.progress_label.setMinimumWidth(100)
        progress_layout.addWidget(self.progress_label, 1)
        
        layout.addLayout(progress_layout)
        
        # Batch results area - now using a gallery view
        batch_results_group = RoundedGroupBox("Results Gallery")
        batch_results_layout = QVBoxLayout()
        batch_results_layout.setContentsMargins(5, 5, 5, 5)
        
        # Add a button to enlarge the gallery to full screen
        gallery_controls_layout = QHBoxLayout()
        gallery_controls_layout.setSpacing(5)
        
        self.fullscreen_gallery_btn = RoundedButton("Enlarge Gallery", color=COLORS["secondary"])
        self.fullscreen_gallery_btn.setMaximumHeight(30)
        self.fullscreen_gallery_btn.clicked.connect(self.show_fullscreen_gallery)
        self.fullscreen_gallery_btn.setEnabled(False)  # Initially disabled until there are results
        gallery_controls_layout.addWidget(self.fullscreen_gallery_btn)
        gallery_controls_layout.addStretch()
        batch_results_layout.addLayout(gallery_controls_layout)
        
        self.batch_results_layout = FlowLayout()
        self.batch_results_layout.setSpacing(10)
        
        self.batch_results_widget = QWidget()
        self.batch_results_widget.setLayout(self.batch_results_layout)
        
        self.batch_results_area = QScrollArea()
        self.batch_results_area.setWidgetResizable(True)
        self.batch_results_area.setWidget(self.batch_results_widget)
        self.batch_results_area.setStyleSheet(f"""
            QScrollArea {{
                border-radius: 10px;
                background-color: {COLORS['widget_bg']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {COLORS['background']};
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['primary']};
                min-height: 20px;
                border-radius: 5px;
            }}
        """)
        
        batch_results_layout.addWidget(self.batch_results_area)
        batch_results_group.setLayout(batch_results_layout)
        layout.addWidget(batch_results_group)
        
        self.batch_process_tab.setLayout(layout)
    
    def select_image_folder(self):
        folder_dialog = QFileDialog()
        folder_path = folder_dialog.getExistingDirectory(self, "Select Image Folder")
        
        if folder_path:
            self.folder_path_label.setText(folder_path)
            
            # Count valid image files
            valid_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")
            self.image_files = [
                os.path.join(folder_path, f) for f in os.listdir(folder_path)
                if f.lower().endswith(valid_extensions)
            ]
            
            self.progress_label.setText(f"Found {len(self.image_files)} image(s)")
            self.log(f"Selected folder: {folder_path} - Found {len(self.image_files)} image(s)")
    
    def download_model(self):
        model_id = self.model_selector.currentText()
        # Remove the checkmark if present
        if model_id.startswith("✓ "):
            model_id = model_id[2:]
        
        # Create models directory if it doesn't exist
        if not os.path.exists("models"):
            os.makedirs("models")
        
        model_path = os.path.join("models", model_id.replace("/", "_"))
        
        if os.path.exists(model_path):
            self.log(f"Model {model_id} already exists locally.")
            return
        
        try:
            self.log(f"Downloading model {model_id}. This may take a while depending on model size.")
            self.download_model_btn.setEnabled(False)
            self.download_model_btn.setText("Downloading...")
            
            # Download model 
            # This will save the model to the specified path
            pipeline("image-classification", model=model_id, cache_dir="models")
            
            # Update the cached models
            self.refresh_cached_models()
            
            # Update the combobox to highlight the newly cached model
            current_idx = self.model_selector.currentIndex()
            self.model_selector.setItemData(current_idx, QColor(COLORS['cached_model']), Qt.BackgroundRole)
            self.model_selector.setItemText(current_idx, f"✓ {model_id}")
            
            self.log(f"Model {model_id} has been downloaded successfully.")
            self.download_model_btn.setEnabled(True)
            self.download_model_btn.setText("Download Selected Model")
        
        except Exception as e:
            self.log(f"ERROR: Failed to download model: {str(e)}")
            self.download_model_btn.setEnabled(True)
            self.download_model_btn.setText("Download Selected Model")
    
    def process_image_batch(self):
        if not hasattr(self, 'image_files') or not self.image_files:
            self.log("WARNING: Please select an image folder first.")
            return
        
        model_id = self.model_selector.currentText()
        # Remove the checkmark if present
        if model_id.startswith("✓ "):
            model_id = model_id[2:]
        
        # Check if we have a local version
        model_path = os.path.join("models", model_id.replace("/", "_"))
        if os.path.exists(model_path):
            model_to_use = model_path
        else:
            model_to_use = model_id
        
        try:
            # Clear previous results
            self.clear_layout(self.batch_results_layout)
            self.all_results = []
            
            # Reset progress
            self.batch_progress.setValue(0)
            self.batch_progress.setMaximum(len(self.image_files))
            
            self.log(f"Processing {len(self.image_files)} images with model: {model_id}")
            
            # Create the worker thread
            self.batch_worker = ClassificationWorker(model_to_use, self.image_files)
            self.batch_worker.progress_update.connect(self.update_batch_progress)
            self.batch_worker.result_ready.connect(self.add_batch_result)
            self.batch_worker.finished_all.connect(self.batch_processing_complete)
            
            # Disable the button while processing
            self.process_batch_btn.setEnabled(False)
            self.export_excel_btn.setEnabled(False)
            
            # Start the worker
            self.batch_worker.start()
        
        except Exception as e:
            self.log(f"ERROR: Batch processing failed: {str(e)}")
            self.process_batch_btn.setEnabled(True)
    
    def update_batch_progress(self, current, total):
        """Update the progress bar during batch processing"""
        percentage = int((current / total) * 100)
        self.batch_progress.setValue(percentage)
        self.progress_label.setText(f"Processing {current}/{total} images...")
    
    def add_batch_result(self, results):
        """Add a single result to the batch results area"""
        for result in results:
            # Store for export
            self.all_results.append(result)
            
            # Add to the visual display
            thumbnail = ImageThumbnail(result['path'], result)
            self.batch_results_layout.addWidget(thumbnail)
    
    def batch_processing_complete(self):
        """Called when batch processing is complete"""
        self.process_batch_btn.setEnabled(True)
        self.export_excel_btn.setEnabled(True)
        self.fullscreen_gallery_btn.setEnabled(True)
        self.progress_label.setText(f"Completed processing {len(self.all_results)} images.")
        
        self.log(f"Batch processing complete: Processed {len(self.all_results)} images successfully. You can now export results to Excel.")
    
    def display_classification_results(self, results):
        """Display classification results for a single image"""
        for result in results:
            # Label container
            results_container = QWidget()
            results_container.setStyleSheet(f"""
                background-color: {COLORS['widget_bg']};
                border-radius: 15px;
                padding: 10px;
            """)
            container_layout = QVBoxLayout()
            
            # Add result labels
            heading = QLabel(f"Classification Results for {os.path.basename(result['path'])}")
            heading.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {COLORS['primary']};")
            container_layout.addWidget(heading)
            
            # Log the results
            self.log(f"Classification results for {os.path.basename(result['path'])}:")
            
            for i, classification in enumerate(result['classifications']):
                if i >= MAX_N_LABELS:  # Limit to top N classifications
                    break
                    
                label = classification['label']
                score = classification['score']
                
                # Format the score as a percentage
                score_pct = f"{score * 100:.1f}%"
                
                # Determine color based on score
                if score >= 0.7:
                    color = COLORS['success']
                elif score >= 0.4:
                    color = COLORS['primary']
                else:
                    color = COLORS['warning']
                
                label_text = f"{label}: {score_pct}"
                
                # Log each classification
                self.log(f"  - {label_text}")
                
                label = QLabel(label_text)
                label.setStyleSheet(f"font-size: 13px; color: {color};")
                container_layout.addWidget(label)
            
            results_container.setLayout(container_layout)
            self.batch_results_layout.addWidget(results_container)
    
    def export_to_excel(self):
        """Export batch results to Excel"""
        if not self.all_results:
            self.log("WARNING: No results to export.")
            return
        
        try:
            file_dialog = QFileDialog()
            file_path, _ = file_dialog.getSaveFileName(
                self, "Save Excel File", "", "Excel Files (*.xlsx)"
            )
            
            if not file_path:
                return
                
            if not file_path.endswith('.xlsx'):
                file_path += '.xlsx'
            
            # Create a DataFrame
            data = []
            
            for result in self.all_results:
                # Base row with filename
                row = {'Filename': os.path.basename(result['path'])}
                
                # Add top classifications
                for i, classification in enumerate(result['classifications']):
                    if i >= MAX_N_LABELS:  # Limit to top N classifications
                        break
                    
                    label = classification['label']
                    score = classification['score']
                    
                    row[f'Label {i+1}'] = label
                    row[f'Score {i+1}'] = score
                
                data.append(row)
            
            # Create DataFrame and export
            df = pd.DataFrame(data)
            df.to_excel(file_path, index=False)
            
            self.log(f"Export successful: Results exported to {file_path}")
            
        except Exception as e:
            self.log(f"ERROR: Failed to export results: {str(e)}")
    
    def clear_layout(self, layout):
        """Clear all widgets from a layout"""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self.clear_layout(item.layout())

    def log(self, message):
        """Add a message to the log window"""
        self.log_window.append(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {message}")
        # Scroll to the bottom
        self.log_window.verticalScrollBar().setValue(self.log_window.verticalScrollBar().maximum())

    def show_fullscreen_gallery(self):
        """Show the batch results gallery in a full-screen dialog"""
        if not hasattr(self, 'all_results') or not self.all_results:
            self.log("No gallery items to display in full screen")
            return
            
        # Create a dialog for the full-screen gallery
        gallery_dialog = QDialog(self)
        gallery_dialog.setWindowTitle("Full Screen Gallery")
        gallery_dialog.setWindowState(Qt.WindowMaximized)
        gallery_dialog.setStyleSheet(f"background-color: {COLORS['background']};")
        
        # Create layout for the dialog
        dialog_layout = QVBoxLayout()
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(10)
        
        # Add a header with close button
        header_layout = QHBoxLayout()
        header_layout.setSpacing(5)
        
        title_label = QLabel("Batch Results Gallery")
        title_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {COLORS['primary']};
        """)
        header_layout.addWidget(title_label)
        
        close_btn = RoundedButton("Close", color=COLORS["error"])
        close_btn.setMaximumWidth(80)
        close_btn.setMaximumHeight(30)
        close_btn.clicked.connect(gallery_dialog.close)
        header_layout.addWidget(close_btn)
        
        dialog_layout.addLayout(header_layout)
        
        # Create a new flow layout for the gallery items
        gallery_widget = QWidget()
        gallery_layout = FlowLayout()
        gallery_layout.setSpacing(10)
        
        # Add all thumbnails to the gallery
        for result in self.all_results:
            thumbnail = ImageThumbnail(result['path'], result)
            thumbnail.setMinimumSize(200, 200)  # Make thumbnails larger in full-screen mode
            gallery_layout.addWidget(thumbnail)
        
        gallery_widget.setLayout(gallery_layout)
        
        # Add the gallery to a scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(gallery_widget)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {COLORS['background']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {COLORS['background']};
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['primary']};
                min-height: 20px;
                border-radius: 5px;
            }}
        """)
        
        dialog_layout.addWidget(scroll_area)
        gallery_dialog.setLayout(dialog_layout)
        
        self.log("Showing full-screen gallery")
        gallery_dialog.exec_()

def main():
    app = QApplication(sys.argv)
    
    # Set application font
    app_font = QFont("Segoe UI", 10)
    app.setFont(app_font)
    
    # Set application style
    app.setStyle("Fusion")
    
    window = ImageClassifierApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()