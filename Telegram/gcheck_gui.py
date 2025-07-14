import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QLineEdit, QHeaderView, QCheckBox
)
from PyQt6.QtCore import Qt
import google.generativeai as genai

def get_gemini_models_info():
    genai.configure(api_key="AIzaSyAToCzFpUkXZ-vAyfJl1aQezk6WnPXLQ_8")
    
    models_data = []
    for m in genai.list_models():
        models_data.append({
            "Name": m.name,
            "Description": m.description,
            "Input Methods": ", ".join(m.supported_generation_methods)
        })
    return models_data

class GeminiCheckerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gemini Model Checker")
        self.setGeometry(100, 100, 900, 600)
        self.all_models_data = []
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()

        self.title_label = QLabel("Gemini Model Information", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        main_layout.addWidget(self.title_label)

        # Filter Section
        filter_layout = QHBoxLayout()
        
        filter_layout.addWidget(QLabel("Name Filter:"))
        self.name_filter_input = QLineEdit(self)
        self.name_filter_input.setPlaceholderText("Filter by model name...")
        filter_layout.addWidget(self.name_filter_input)

        filter_layout.addWidget(QLabel("Description Filter:"))
        self.desc_filter_input = QLineEdit(self)
        self.desc_filter_input.setPlaceholderText("Filter by description...")
        filter_layout.addWidget(self.desc_filter_input)

        self.image_video_filter_checkbox = QCheckBox("Accepts Image/Video Input", self)
        filter_layout.addWidget(self.image_video_filter_checkbox)

        self.filter_button = QPushButton("Apply Filters", self)
        self.filter_button.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                padding: 8px 15px;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        self.filter_button.clicked.connect(self.apply_filters)
        filter_layout.addWidget(self.filter_button)

        main_layout.addLayout(filter_layout)

        # Check Button
        self.check_button = QPushButton("Fetch Gemini Models", self)
        self.check_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 16px;
                margin-top: 10px;
                margin-bottom: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.check_button.clicked.connect(self.run_check)
        main_layout.addWidget(self.check_button)

        # Output Table
        self.output_table = QTableWidget(self)
        self.output_table.setColumnCount(3)
        self.output_table.setHorizontalHeaderLabels(["Name", "Description", "Input Methods"])
        self.output_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.output_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.output_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.output_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Make table read-only
        self.output_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                border: 1px solid #ccc;
                gridline-color: #ddd;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                padding: 5px;
                border: 1px solid #ccc;
                font-weight: bold;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #b0e0e6;
                color: black;
            }
        """)
        main_layout.addWidget(self.output_table)

        self.setLayout(main_layout)

    def run_check(self):
        self.output_table.setRowCount(0) # Clear existing rows
        self.all_models_data = [] # Clear previous data
        
        # Display a loading message
        self.output_table.setRowCount(1)
        self.output_table.setItem(0, 0, QTableWidgetItem("Fetching data..."))
        self.output_table.setSpan(0, 0, 1, 3) # Span across all columns
        self.output_table.item(0, 0).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        try:
            self.all_models_data = get_gemini_models_info()
            self.populate_table(self.all_models_data)
        except Exception as e:
            self.output_table.setRowCount(1)
            self.output_table.setItem(0, 0, QTableWidgetItem(f"Error fetching models: {e}"))
            self.output_table.setSpan(0, 0, 1, 3)
            self.output_table.item(0, 0).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def populate_table(self, models_to_display):
        self.output_table.setRowCount(len(models_to_display))
        for row_idx, model in enumerate(models_to_display):
            self.output_table.setItem(row_idx, 0, QTableWidgetItem(model.get("Name", "")))
            self.output_table.setItem(row_idx, 1, QTableWidgetItem(model.get("Description", "")))
            self.output_table.setItem(row_idx, 2, QTableWidgetItem(model.get("Input Methods", "")))

    def apply_filters(self):
        filtered_models = []
        name_filter_text = self.name_filter_input.text().lower()
        desc_filter_text = self.desc_filter_input.text().lower()
        image_video_checked = self.image_video_filter_checkbox.isChecked()

        for model in self.all_models_data:
            name_match = name_filter_text in model.get("Name", "").lower()
            desc_match = desc_filter_text in model.get("Description", "").lower()
            
            input_methods = model.get("Input Methods", "").lower()
            image_video_match = True
            if image_video_checked:
                image_video_match = ("image" in input_methods or "video" in input_methods)

            if name_match and desc_match and image_video_match:
                filtered_models.append(model)
        
        self.populate_table(filtered_models)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GeminiCheckerApp()
    window.show()
    sys.exit(app.exec())
