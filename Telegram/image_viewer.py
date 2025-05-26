import sys
import os
import sqlite3
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
    QLabel, QTextEdit, QSplitter, QSizePolicy, QListWidgetItem, QWidget
)
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt, QSize

# Assuming database_handler.py is in the same directory
try:
    from . import database_handler # For running as part of a package
except ImportError:
    import database_handler # For running script directly or if sys.path is set up

class ImageViewerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Telegram Image Viewer")
        self.setGeometry(150, 150, 1000, 700) # Initial size, can be adjusted
        self.db_path = database_handler.DATABASE_PATH

        self.init_ui()
        self.load_image_list()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # --- Left Pane: Image List ---
        self.image_list_widget = QListWidget()
        self.image_list_widget.currentItemChanged.connect(self.display_selected_image_info)
        self.image_list_widget.setFixedWidth(250) # Adjust as needed

        # --- Right Pane: Info and Image ---
        right_pane_widget = QWidget()
        right_layout = QVBoxLayout(right_pane_widget)

        # Top Right: Info Area
        self.info_display_area = QTextEdit()
        self.info_display_area.setReadOnly(True)
        self.info_display_area.setFixedHeight(200) # Adjust as needed

        # Bottom Right: Image Display
        self.image_display_label = QLabel("Select an image from the list")
        self.image_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_display_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_display_label.setMinimumSize(400, 300)


        right_layout.addWidget(self.info_display_area)
        right_layout.addWidget(self.image_display_label, 1) # Give image display more stretch factor

        # --- Splitter for resizable panes ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.image_list_widget)
        splitter.addWidget(right_pane_widget)
        splitter.setStretchFactor(0, 1) # Image list
        splitter.setStretchFactor(1, 3) # Info and image display area

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def load_image_list(self):
        self.image_list_widget.clear()
        try:
            conn = database_handler.get_db_connection()
            cursor = conn.cursor()
            # Fetch id, filename, and sanitized_caption for the list
            cursor.execute("SELECT id, filename, sanitized_caption FROM images ORDER BY id DESC")
            images = cursor.fetchall()
            conn.close()

            if not images:
                self.image_list_widget.addItem("No images found in database.")
                return

            for img_row in images:
                display_text = ""
                if img_row['sanitized_caption'] and len(img_row['sanitized_caption'].strip()) > 3:
                    display_text = img_row['sanitized_caption'][:80] # Show first 80 chars of sanitized caption
                    if len(img_row['sanitized_caption']) > 80:
                        display_text += "..."
                elif img_row['filename']:
                    display_text = img_row['filename']
                else:
                    display_text = f"Image ID: {img_row['id']}"
                
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.ItemDataRole.UserRole, img_row['id']) # Store DB id
                self.image_list_widget.addItem(list_item)
        except Exception as e:
            self.image_list_widget.addItem("Error loading images from DB.")
            print(f"Error loading image list: {e}")
            if self.info_display_area:
                self.info_display_area.setText(f"Error loading image list: {e}")


    def display_selected_image_info(self, current_item, previous_item):
        if not current_item:
            self.info_display_area.clear()
            self.image_display_label.clear()
            self.image_display_label.setText("Select an image")
            return

        image_db_id = current_item.data(Qt.ItemDataRole.UserRole)
        if not image_db_id:
            return

        try:
            conn = database_handler.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM images WHERE id = ?", (image_db_id,))
            img_data = cursor.fetchone()
            conn.close()

            if not img_data:
                self.info_display_area.setText(f"Image with ID {image_db_id} not found.")
                self.image_display_label.clear()
                self.image_display_label.setText("Image data not found")
                return

            # Display metadata - only specific fields
            info_text = []
            fields_to_display = {
                "sanitized_caption": "Sanitized Caption",
                "ai_category": "AI Category",
                "price": "Price",
                "channel": "Channel",
                "telegram_message_date": "Message Date (UTC)"
            }
            
            for db_key, display_label in fields_to_display.items():
                value = img_data[db_key] if img_data[db_key] is not None else "N/A"
                info_text.append(f"<b>{display_label}:</b> {value}")
            
            self.info_display_area.setHtml("<br>".join(info_text))

            # Display image
            image_path = img_data['full_path']
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    self.image_display_label.setText(f"Error loading image:\n{image_path}\n(File might be corrupted or not an image)")
                else:
                    # Scale pixmap to fit label while maintaining aspect ratio
                    scaled_pixmap = pixmap.scaled(
                        self.image_display_label.size(), 
                        Qt.AspectRatioMode.KeepAspectRatio, 
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.image_display_label.setPixmap(scaled_pixmap)
            else:
                self.image_display_label.setText(f"Image file not found at:\n{image_path}")

        except Exception as e:
            self.info_display_area.setText(f"Error displaying image info: {e}")
            self.image_display_label.clear()
            self.image_display_label.setText("Error displaying image")
            print(f"Error displaying image info: {e}")
            
    def resizeEvent(self, event):
        """Handle window resize to rescale the displayed image."""
        super().resizeEvent(event)
        # If an image is displayed, rescale it
        if self.image_list_widget.currentItem() and self.image_display_label.pixmap() and not self.image_display_label.pixmap().isNull():
            self.display_selected_image_info(self.image_list_widget.currentItem(), None)


if __name__ == '__main__':
    # This allows testing the viewer independently
    # Ensure database_handler.py is in the same directory or accessible via PYTHONPATH
    
    # First, ensure the database exists and has some data for testing
    # You might need to run telegram2.py first to populate the DB
    if not os.path.exists(database_handler.DATABASE_PATH):
        print(f"Database not found at {database_handler.DATABASE_PATH}. Initializing...")
        database_handler.initialize_database()
        print("Please run the main application (telegram2.py) to download images and populate the database first.")
        # sys.exit() # Exit if DB is empty, or let it show "No images"

    app = QApplication(sys.argv)
    # Apply a basic style for standalone testing if dark_theme.qss is available
    try:
        qss_file = "dark_theme.qss" # Assumes it's in the same dir when running this directly
        if os.path.exists(qss_file):
            with open(qss_file, "r") as f:
                app.setStyleSheet(f.read())
    except Exception as e:
        print(f"Could not load stylesheet for standalone viewer: {e}")

    viewer = ImageViewerWindow()
    viewer.show()
    sys.exit(app.exec())
