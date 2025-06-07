# custom_widgets.py
import os
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QCheckBox, QFileIconProvider
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtCore import Qt, QSize

# Define colors for clarity
INCLUDED_COLOR = QColor("#2E4237")  # Dark Green
EXCLUDED_COLOR = QColor("#422E2E")  # Dark Red
ITEM_BACKGROUND_COLOR = QColor("#2c313c")

def format_size(size_bytes):
    """Formats a size in bytes to a human-readable string."""
    if size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels):
        size_bytes /= power
        n += 1
    return f"{size_bytes:.1f} {power_labels[n]}B"

class FileItemWidget(QWidget):
    """
    A custom widget for displaying a file/folder in the list.
    Includes an icon, checkbox, name, size, and date.
    """
    def __init__(self, full_path, size_bytes, m_time, is_dir, parent=None):
        super().__init__(parent)
        self.full_path = full_path
        self.is_included = True

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # 1. Checkbox for inclusion
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self.update_state_from_checkbox)

        # 2. Icon
        self.icon_label = QLabel()
        icon_provider = QFileIconProvider()
        file_icon = icon_provider.icon(QFileIconProvider.IconType.Folder if is_dir else QFileIconProvider.IconType.File)
        self.icon_label.setPixmap(file_icon.pixmap(QSize(24, 24)))

        # 3. Name
        self.name_label = QLabel(f"<b>{full_path.split(os.path.sep)[-1]}</b>")

        # 4. Metadata (Size and Date)
        date_str = m_time.strftime('%Y-%m-%d %H:%M')
        size_str = format_size(size_bytes) if not is_dir else "---"
        self.meta_label = QLabel(f"{size_str.ljust(10)} | {date_str}")
        self.meta_label.setStyleSheet("color: #9099a6;") # Lighter gray for metadata

        layout.addWidget(self.checkbox)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        layout.addStretch()
        layout.addWidget(self.meta_label)
        
        self.setAutoFillBackground(True)
        self.update_visual_state()

    def update_state_from_checkbox(self, state):
        """Called when the checkbox is toggled by the user."""
        self.set_state(state == Qt.CheckState.Checked.value)

    def set_state(self, included: bool):
        """Sets the inclusion state and updates UI accordingly."""
        self.is_included = included
        self.checkbox.setChecked(included)
        self.update_visual_state()

    def update_visual_state(self):
        """Sets the background color based on the inclusion state."""
        color_hex = INCLUDED_COLOR.name() if self.is_included else EXCLUDED_COLOR.name()
        self.setStyleSheet(f"background-color: {color_hex}; border-radius: 4px;")
