import sys
import os
import sqlite3
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QLabel, QTextEdit, QSplitter, QSizePolicy, QListWidgetItem, QWidget,
    QPushButton, QScrollArea
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QTimer

try:
    from . import database_handler
except ImportError:
    import database_handler
    import gemini_categorizer

class ProductViewerWindow(QDialog):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Telegram Product Viewer")
        self.setGeometry(150, 150, 1200, 800)
        
        if not db_path:
            raise ValueError("ProductViewerWindow requires a valid database path.")
            
        self.db_path = db_path
        self.current_selected_product_id = None

        self.categories_data = gemini_categorizer.load_categories()
        self.id_to_category_map = self.categories_data[1]

        self.init_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(15000)
        self.refresh_timer.timeout.connect(self.auto_refresh_list)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        left_pane_widget = QWidget()
        left_pane_layout = QVBoxLayout(left_pane_widget)
        left_pane_layout.setContentsMargins(0,0,0,0)

        self.refresh_button = QPushButton("Refresh List")
        self.refresh_button.clicked.connect(self.load_product_list)
        left_pane_layout.addWidget(self.refresh_button)
        
        self.product_list_widget = QListWidget()
        self.product_list_widget.currentItemChanged.connect(self.display_selected_product_info)
        left_pane_layout.addWidget(self.product_list_widget)
        
        left_pane_widget.setMinimumWidth(250)
        left_pane_widget.setMaximumWidth(450)

        right_pane_widget = QWidget()
        right_layout = QVBoxLayout(right_pane_widget)

        self.info_display_area = QTextEdit()
        self.info_display_area.setReadOnly(True)
        self.info_display_area.setFixedHeight(250)

        # Image display area with scrolling
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.image_container = QWidget()
        self.image_layout = QHBoxLayout(self.image_container)
        self.scroll_area.setWidget(self.image_container)

        right_layout.addWidget(self.info_display_area)
        right_layout.addWidget(self.scroll_area, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_pane_widget)
        splitter.addWidget(right_pane_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([300, 900])

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def auto_refresh_list(self):
        self.load_product_list()

    def load_product_list(self):
        previously_selected_db_id = None
        current_item = self.product_list_widget.currentItem()
        if current_item:
            previously_selected_db_id = current_item.data(Qt.ItemDataRole.UserRole)

        self.product_list_widget.clear()
        if not self.db_path:
            self.product_list_widget.addItem("Database path not set.")
            return
            
        try:
            conn = database_handler.get_db_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, sanitized_caption FROM products ORDER BY id DESC")
            products = cursor.fetchall()
            conn.close()

            if not products:
                self.product_list_widget.addItem("No products found in database.")
                self.info_display_area.clear()
                self.clear_image_layout()
                return

            item_to_reselect = None
            for prod_row in products:
                display_text = f"ID: {prod_row['id']} - {prod_row['sanitized_caption'][:80]}"
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.ItemDataRole.UserRole, prod_row['id'])
                self.product_list_widget.addItem(list_item)
                
                if previously_selected_db_id is not None and prod_row['id'] == previously_selected_db_id:
                    item_to_reselect = list_item
            
            if item_to_reselect:
                self.product_list_widget.setCurrentItem(item_to_reselect)
            elif self.product_list_widget.count() > 0:
                self.product_list_widget.setCurrentRow(0)
            else:
                 self.info_display_area.clear()
                 self.clear_image_layout()

        except Exception as e:
            self.product_list_widget.addItem("Error loading products from DB.")
            print(f"Error loading product list: {e}")
            self.info_display_area.setText(f"Error loading product list: {e}")

    def display_selected_product_info(self, current_item, previous_item):
        if not current_item:
            self.info_display_area.clear()
            self.clear_image_layout()
            return

        product_db_id = current_item.data(Qt.ItemDataRole.UserRole)
        if not product_db_id:
            return
        
        self.current_selected_product_id = product_db_id
        
        try:
            product_details = database_handler.get_product_details(product_db_id, self.db_path)

            if not product_details:
                self.info_display_area.setText(f"Product with ID {product_db_id} not found.")
                self.clear_image_layout()
                return

            info_text = []
            major_cat_id = product_details.get('major_category_id')
            sub_cat_id = product_details.get('sub_category_id')
            
            major_cat_name = self.id_to_category_map.get(major_cat_id, {}).get('name', 'N/A') if major_cat_id else "N/A"
            sub_cat_name = self.id_to_category_map.get(sub_cat_id, {}).get('name', 'N/A') if sub_cat_id else "N/A"

            display_category = f"{major_cat_name} > {sub_cat_name}" if sub_cat_name != "N/A" else major_cat_name
            if display_category == "N/A": display_category = "не определена"

            info_text.append(f"<b>AI Category:</b> {display_category}")
            info_text.append(f"<b>Brand Tag:</b> {product_details.get('brand_tag', 'N/A')}")
            
            fields_to_display = {
                "sanitized_caption": "Sanitized Caption", "price": "Price",
                "channel": "Channel", "telegram_message_date": "Message Date (UTC)"
            }
            for db_key, display_label in fields_to_display.items():
                value = product_details.get(db_key, "N/A")
                info_text.append(f"<b>{display_label}:</b> {value}")
            
            self.info_display_area.setHtml("<br>".join(info_text))

            self.clear_image_layout()
            for image_data in product_details.get('images', []):
                image_path = image_data['full_path']
                if image_path and os.path.exists(image_path):
                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        image_label = QLabel()
                        image_label.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                        self.image_layout.addWidget(image_label)

        except Exception as e:
            self.info_display_area.setText(f"Error displaying product info: {e}")
            self.clear_image_layout()
            print(f"Error displaying product info: {e}")

    def clear_image_layout(self):
        while self.image_layout.count():
            child = self.image_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            
    def showEvent(self, event):
        super().showEvent(event)
        self.load_product_list()
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.start()

    def closeEvent(self, event):
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        super().closeEvent(event)

if __name__ == '__main__':
    test_db_viewer_name = "standalone_viewer_test.sqlite"
    test_db_viewer_path = os.path.join(os.path.dirname(__file__), test_db_viewer_name)

    if not os.path.exists(test_db_viewer_path):
        print(f"Test database not found at {test_db_viewer_path}. Initializing...")
        try:
            database_handler.initialize_database(test_db_viewer_path)
            print(f"Test database '{test_db_viewer_path}' initialized.")
            print("Please run the main application (telegram2.py) to populate the DB.")
        except Exception as e:
            print(f"Error initializing test database: {e}")
            sys.exit(1)

    app = QApplication(sys.argv)
    try:
        qss_file = "dark_theme.qss"
        if os.path.exists(qss_file):
            with open(qss_file, "r") as f:
                app.setStyleSheet(f.read())
    except Exception as e:
        print(f"Could not load stylesheet: {e}")

    viewer = ProductViewerWindow(db_path=test_db_viewer_path) 
    viewer.show()
    sys.exit(app.exec())
