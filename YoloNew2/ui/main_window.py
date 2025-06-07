from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QListWidget, QPushButton, QLabel, QSplitter,
                             QStatusBar, QProgressBar, QSpinBox, QFileDialog,
                             QListWidgetItem, QMessageBox, QLineEdit, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer, QMimeData
from PyQt6.QtGui import QKeySequence, QShortcut, QDrag, QPixmap, QPainter, QFont, QColor
import os

from ui.image_canvas import ImageCanvas # Import the custom canvas
from ui.dialogs import AugmentationSettingsDialog # Import the Augmentation dialog
# from ui.dialogs import SaveOptionsDialog, AugmentationDialog, ModelManagerDialog # Future dialogs

# Custom class list widget with improved drag support
class ClassListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        # Set a larger font for the class list
        font = self.font()
        font.setPointSize(font.pointSize() + 2)  # Increase font size by 2 points
        self.setFont(font)
        
    def startDrag(self, supportedActions):
        # Get the selected item
        item = self.currentItem()
        if not item:
            return
            
        # Create mime data with the class name as plain text
        mimeData = QMimeData()
        mimeData.setText(item.text())
        
        # Create and start the drag operation
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        
        # Custom feedback based on class name
        # Create a small pixmap with the class name as text
        pm = QPixmap(200, 30)  # Create a small pixmap
        pm.fill(QColor(60, 60, 180, 210))  # Semi-transparent blue background
        painter = QPainter(pm)
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))  # White text
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, item.text())
        painter.end()
        
        # Set the pixmap as the drag cursor
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        
        # Execute the drag
        result = drag.exec(Qt.DropAction.CopyAction)
        
        # Show status message based on result
        if result == Qt.DropAction.CopyAction:
            parent = self.parent()
            while parent:
                if isinstance(parent, QMainWindow):
                    parent.statusBar().showMessage(f"Class '{item.text()}' assigned to box", 3000)
                    break
                parent = parent.parent()
        
class MainWindow(QMainWindow):

    # Define signals to notify AppLogic
    add_images_requested = pyqtSignal()
    select_model_requested = pyqtSignal()
    process_images_requested = pyqtSignal(list) # list of image paths
    save_dataset_requested = pyqtSignal(str, bool, int) # format, augment, num_augmentations
    save_state_requested = pyqtSignal() # Signal to request manual state save
    clear_state_requested = pyqtSignal() # Signal to request state clear/reset
    image_selected = pyqtSignal(str) # path of selected image
    delete_image_requested = pyqtSignal(str) # path of image to delete
    clear_images_requested = pyqtSignal() # signal to clear all images
    import_classes_requested = pyqtSignal(list) # list of class names to import
    class_added_requested = pyqtSignal(str) # name of new class
    class_removed_requested = pyqtSignal(str) # name of class to remove
    class_selected_for_assignment = pyqtSignal(int) # index of selected class

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_logic = None # Will be set by main.py
        self.setWindowTitle("YOLO Dataset Creator")
        self.setGeometry(100, 100, 1200, 800) # Adjust size as needed

        self._create_widgets()
        self._create_layout()
        self._create_menus()
        self._connect_signals()
        self._create_shortcuts()

        self.image_list_widget.itemSelectionChanged.connect(self._on_image_selection_changed)
        self.class_list_widget.itemSelectionChanged.connect(self._on_class_selection_changed)
        
        # Auto-save indicator timer
        self.auto_save_indicator_timer = QTimer(self)
        self.auto_save_indicator_timer.timeout.connect(self._hide_auto_save_indicator)
        self.auto_save_indicator_timer.setSingleShot(True)

    def set_app_logic(self, logic):
        """Connects the main window to the application logic."""
        self.app_logic = logic
        # Connect canvas signals TO AppLogic methods
        self.image_canvas.annotations_changed.connect(self.app_logic.on_annotations_updated)
        self.image_canvas.box_selected.connect(self.app_logic.on_box_selected_in_canvas)
        self.image_canvas.new_box_request.connect(self.app_logic.on_new_box_drawn)
        self.image_canvas.delete_box_request.connect(self.app_logic.on_delete_box_requested)
        self.image_canvas.mouse_pos_changed.connect(self._update_mouse_coords_status)
        self.image_canvas.class_assignment_request.connect(self.app_logic.on_class_assignment_requested)

    def _create_widgets(self):
        # --- Top Control Panel ---
        self.add_images_button = QPushButton("Add Images...")
        self.select_model_button = QPushButton("Select Model...")
        self.model_label = QLabel("Model: None")
        self.model_label.setFrameStyle(QLabel.Shape.Panel | QLabel.Shadow.Sunken)
        self.model_label.setMinimumWidth(150)
        self.process_button = QPushButton("Process All") # Changed from "Process Selected"
        self.process_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False) # Hide initially
        
        # Create combined save dataset button and options
        self.save_button = QPushButton("Save Dataset...")
        self.save_button.setEnabled(False)
        self.augment_spinbox = QSpinBox()
        self.augment_spinbox.setRange(0, 100)
        self.augment_spinbox.setValue(5)
        self.augment_label = QLabel("Aug:")
        self.aug_settings_button = QPushButton("Aug Settings...")
        self.aug_settings_button.setToolTip("Configure augmentation settings")
        
        # Remove the separate augment button
        # self.augment_button = QPushButton("Augment Dataset")

        # --- Left Panel ---
        self.image_list_widget = QListWidget()
        self.image_count_label = QLabel("Images: 0")
        
        # Buttons for image list operations
        self.delete_image_button = QPushButton("Delete Selected")
        self.delete_image_button.setToolTip("Delete selected image from list")
        self.delete_image_button.setEnabled(False)  # Initially disabled until image selected
        
        self.clear_images_button = QPushButton("Clear All")
        self.clear_images_button.setToolTip("Remove all images from list")

        # --- Center Panel ---
        self.image_canvas = ImageCanvas() # Use the custom widget

        # --- Right Panel ---
        self.class_list_widget = ClassListWidget()
        self.class_list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.add_class_input = QLineEdit()
        self.add_class_input.setPlaceholderText("New class name...")
        self.add_class_button = QPushButton("Add Class")
        self.remove_class_button = QPushButton("Remove Selected Class")
        self.import_classes_button = QPushButton("Import Classes...")
        self.import_classes_button.setToolTip("Import class names from a text file (one class per line)")
        self.export_classes_button = QPushButton("Export Classes...")
        self.export_classes_button.setToolTip("Export current class names to a text file")
        self.class_hint_label = QLabel("Select box, then click class\nor Right-click box\nor Drag class to box")

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.mouse_coords_label = QLabel("") # For mouse position
        self.auto_save_label = QLabel("Auto-saving...") # For auto-save indicator
        self.auto_save_label.setStyleSheet("color: green;")
        self.auto_save_label.setVisible(False) # Hide initially

    def _create_layout(self):
        # --- Top Controls Layout ---
        # Create a toolbar-like top panel with logical grouping
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(5, 5, 5, 5)  # Reduce margins to make it more compact
        top_layout.setSpacing(8)  # Set consistent spacing
        
        # First group: Image operations
        top_layout.addWidget(self.add_images_button)
        
        # Add a vertical separator line
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.VLine)
        separator1.setFrameShadow(QFrame.Shadow.Sunken)
        top_layout.addWidget(separator1)
        
        # Second group: Model operations
        top_layout.addWidget(self.select_model_button)
        top_layout.addWidget(self.model_label)
        
        # Add a vertical separator line
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.VLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        top_layout.addWidget(separator2)
        
        # Third group: Processing
        top_layout.addWidget(self.process_button)
        top_layout.addWidget(self.progress_bar, 1)  # Give progress bar stretch factor
        
        # Add a vertical separator line
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.Shape.VLine)
        separator3.setFrameShadow(QFrame.Shadow.Sunken)
        top_layout.addWidget(separator3)
        
        # Fourth group: Dataset operations
        top_layout.addWidget(self.augment_label)
        top_layout.addWidget(self.augment_spinbox)
        top_layout.addWidget(self.aug_settings_button)
        top_layout.addWidget(self.save_button)
        
        # Create the control panel widget
        control_panel_layout = QVBoxLayout()
        control_panel_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        control_panel_layout.addLayout(top_layout)
        
        control_panel_widget = QWidget()
        control_panel_widget.setLayout(control_panel_layout)
        control_panel_widget.setFixedHeight(50)  # Set fixed height to make it compact
        
        # --- Left Panel Layout ---
        left_panel_layout = QVBoxLayout()
        left_panel_layout.addWidget(QLabel("Image Files:"))
        left_panel_layout.addWidget(self.image_list_widget)
        left_panel_layout.addWidget(self.image_count_label)
        
        # Create horizontal layout for image management buttons
        image_buttons_layout = QHBoxLayout()
        image_buttons_layout.addWidget(self.delete_image_button)
        image_buttons_layout.addWidget(self.clear_images_button)
        left_panel_layout.addLayout(image_buttons_layout)
        
        left_panel_widget = QWidget()
        left_panel_widget.setLayout(left_panel_layout)

         # --- Right Panel Layout ---
        right_panel_layout = QVBoxLayout()
        right_panel_layout.addWidget(QLabel("Classes:"))
        right_panel_layout.addWidget(self.class_list_widget)
        add_class_layout = QHBoxLayout()
        add_class_layout.addWidget(self.add_class_input)
        add_class_layout.addWidget(self.add_class_button)
        right_panel_layout.addLayout(add_class_layout)
        right_panel_layout.addWidget(self.remove_class_button)
        
        # Add import/export buttons in a horizontal layout
        class_io_layout = QHBoxLayout()
        class_io_layout.addWidget(self.import_classes_button)
        class_io_layout.addWidget(self.export_classes_button)
        right_panel_layout.addLayout(class_io_layout)
        
        # Add a separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        right_panel_layout.addWidget(separator)
        
        right_panel_layout.addWidget(self.class_hint_label)
        right_panel_widget = QWidget()
        right_panel_widget.setLayout(right_panel_layout)

        # --- Main Splitter Layout ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel_widget)
        splitter.addWidget(self.image_canvas) # Center widget
        splitter.addWidget(right_panel_widget)
        splitter.setStretchFactor(0, 1) # Adjust initial size ratios
        splitter.setStretchFactor(1, 3) # Canvas gets more space
        splitter.setStretchFactor(2, 1)

        # --- Overall Layout ---
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)  # Reduce margins
        main_layout.setSpacing(5)  # Set smaller spacing
        main_layout.addWidget(control_panel_widget)
        main_layout.addWidget(splitter, 1)  # Make splitter take up all remaining space

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Add mouse coords label permanently to status bar
        self.status_bar.addPermanentWidget(self.auto_save_label)
        self.status_bar.addPermanentWidget(self.mouse_coords_label)

    def _connect_signals(self):
        # Connect UI element signals TO MainWindow methods/signals
        self.add_images_button.clicked.connect(self.add_images_requested)
        self.select_model_button.clicked.connect(self.select_model_requested)
        self.process_button.clicked.connect(self._on_process_clicked)
        self.save_button.clicked.connect(self._on_save_clicked)
        # Remove the augment button connection
        # self.augment_button.clicked.connect(self._on_augment_clicked)
        self.add_class_button.clicked.connect(self._on_add_class)
        self.remove_class_button.clicked.connect(self._on_remove_class)
        self.delete_image_button.clicked.connect(self._on_delete_image)
        self.clear_images_button.clicked.connect(self._on_clear_images)
        self.import_classes_button.clicked.connect(self._on_import_classes)
        self.export_classes_button.clicked.connect(self._on_export_classes)
        self.aug_settings_button.clicked.connect(self._show_augmentation_settings)

    def _create_shortcuts(self):
        # Example: Delete selected box with 'Delete' key
        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        # Connect shortcut to the same request signal used by context menu
        delete_shortcut.activated.connect(lambda: self.image_canvas.delete_box_request.emit(self.image_canvas.selected_box_idx) if self.image_canvas.selected_box_idx != -1 else None)

    # --- Internal Signal Handlers ---

    def _on_image_selection_changed(self):
        selected_items = self.image_list_widget.selectedItems()
        if selected_items:
            item = selected_items[0]
            image_path = item.data(Qt.ItemDataRole.UserRole) # Store path in UserRole
            if image_path:
                self.image_selected.emit(image_path)
                self.delete_image_button.setEnabled(True)
        else:
            # Handle deselection by clearing the canvas
            self.get_image_canvas().clear()
            self.delete_image_button.setEnabled(False)

    def _on_class_selection_changed(self):
        selected_items = self.class_list_widget.selectedItems()
        if selected_items:
             class_index = self.class_list_widget.row(selected_items[0])
             self.class_selected_for_assignment.emit(class_index)


    def _on_add_class(self):
        class_name = self.add_class_input.text().strip()
        if class_name:
            self.class_added_requested.emit(class_name)
            self.add_class_input.clear()
        else:
            self.show_message("Warning", "Class name cannot be empty.")

    def _on_remove_class(self):
        selected_items = self.class_list_widget.selectedItems()
        if selected_items:
            class_name = selected_items[0].text()
            # Add confirmation dialog here
            reply = QMessageBox.question(self, 'Confirm Deletion',
                                       f"Are you sure you want to remove class '{class_name}'?\n"
                                       f"(Annotations using this class might need reassignment)",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.class_removed_requested.emit(class_name)
        else:
             self.show_message("Info", "Select a class to remove.")

    def _on_process_clicked(self):
        # Modified to process all images, not just the selected one
        image_paths = []
        # Get all image paths from the list widget
        for i in range(self.image_list_widget.count()):
            item = self.image_list_widget.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                image_paths.append(path)
        
        if image_paths:
            self.process_images_requested.emit(image_paths)
        else:
            self.show_message("Info", "No images loaded. Please add images first.")


    def _on_save_clicked(self):
        """Handle saving dataset with optional augmentation"""
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not output_dir:
            return
            
        # Get augmentation setting from spinbox
        num_augmentations = self.augment_spinbox.value()
        will_augment = num_augmentations > 0
        
        formats = ["YOLO", "COCO", "VOC"]
        format_idx = 0  # Default to YOLO
        
        # Show confirmation dialog
        message = f"Save dataset to: {output_dir}\n"
        message += f"Format: {formats[format_idx]}\n"
        
        if will_augment:
            message += f"Including {num_augmentations} augmentations per image"
        else:
            message += "No augmentation (set Aug > 0 to enable)"
            
        reply = QMessageBox.question(self, 'Confirm Save Dataset', 
                                     message,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
                                     
        if reply == QMessageBox.StandardButton.Yes:
            # Emit signal to save dataset (with format, augment flag, and augment count)
            format_lower = formats[format_idx].lower()
            self.save_dataset_requested.emit(format_lower, will_augment, num_augmentations)

    def _on_import_classes(self):
        """Handle importing class names from a text file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Classes from Text File",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                class_names = [line.strip() for line in f.readlines() if line.strip()]
                
            if not class_names:
                self.show_message("Warning", "No valid class names found in the file.", QMessageBox.Icon.Warning)
                return
                
            # Show confirmation with the number of classes found
            reply = QMessageBox.question(
                self, 
                'Import Classes',
                f"Found {len(class_names)} classes in file.\nDo you want to import them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.import_classes_requested.emit(class_names)
                
        except Exception as e:
            self.show_message("Error", f"Failed to import classes: {str(e)}", QMessageBox.Icon.Critical)

    def _on_export_classes(self):
        """Handle exporting class names to a text file"""
        if not self.class_list_widget.count():
            self.show_message("Warning", "No classes to export.", QMessageBox.Icon.Warning)
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Classes to Text File",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                for i in range(self.class_list_widget.count()):
                    class_name = self.class_list_widget.item(i).text()
                    f.write(f"{class_name}\n")
                    
            self.status_bar.showMessage(
                f"Exported {self.class_list_widget.count()} classes to file", 
                3000
            )
                
        except Exception as e:
            self.show_message("Error", f"Failed to export classes: {str(e)}", QMessageBox.Icon.Critical)

    def _on_sort_classes(self):
        """Sort the class list alphabetically"""
        if not self.class_list_widget.count() or self.class_list_widget.count() <= 1:
            self.status_bar.showMessage("No classes to sort or only one class present", 3000)
            return
        
        # Get current class names
        class_names = []
        for i in range(self.class_list_widget.count()):
            class_names.append(self.class_list_widget.item(i).text())
        
        # Remember current selection
        current_selection = None
        if self.class_list_widget.currentItem():
            current_selection = self.class_list_widget.currentItem().text()
        
        # Sort alphabetically
        sorted_names = sorted(class_names)
        
        # Check if already sorted
        if sorted_names == class_names:
            self.status_bar.showMessage("Classes are already sorted alphabetically", 3000)
            return
        
        # Emit signal with sorted list
        # We can't directly modify the app_data.classes list here, so we use the app_logic
        # Instead of adding a new signal, we'll use a workaround with existing signals:
        # 1. Clear all classes
        for name in class_names[:]:  # Use a copy because we're modifying
            self.class_removed_requested.emit(name)
        
        # 2. Add sorted classes
        for name in sorted_names:
            self.class_added_requested.emit(name)
        
        # Try to restore selection
        if current_selection:
            for i in range(self.class_list_widget.count()):
                if self.class_list_widget.item(i).text() == current_selection:
                    self.class_list_widget.setCurrentRow(i)
                    break
                
        self.status_bar.showMessage(f"Sorted {len(sorted_names)} classes alphabetically", 3000)

    # --- Public Methods for AppLogic to Update UI ---

    def update_image_list(self, image_paths: list):
        self.image_list_widget.clear()
        for path in image_paths:
            item = QListWidgetItem(path.split('/')[-1].split('\\')[-1]) # Display filename
            item.setData(Qt.ItemDataRole.UserRole, path) # Store full path
            self.image_list_widget.addItem(item)
        self.image_count_label.setText(f"Images: {len(image_paths)}")

    def update_class_list(self, class_names: list):
        current_selection = self.class_list_widget.currentRow()
        self.class_list_widget.clear()
        
        for class_name in class_names:
            item = QListWidgetItem(class_name)
            # Set item flags to enable dragging
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            # Store the actual class name as data in the UserRole
            item.setData(Qt.ItemDataRole.UserRole, class_name)
            self.class_list_widget.addItem(item)
            
        # Try to restore selection
        if 0 <= current_selection < len(class_names):
            self.class_list_widget.setCurrentRow(current_selection)
        # Update canvas too, as it might need the latest list for context menus
        if self.image_canvas:
            self.image_canvas.class_names = class_names # Keep canvas class list sync'd

    def set_model_label(self, model_path: str | None):
        if model_path:
            filename = model_path.split('/')[-1].split('\\')[-1]
            self.model_label.setText(f"Model: {filename}")
        else:
            self.model_label.setText("Model: None")

    def set_ui_busy(self, busy: bool, message: str = ""):
        """Disable/Enable controls during background tasks."""
        self.add_images_button.setEnabled(not busy)
        self.select_model_button.setEnabled(not busy)
        self.process_button.setEnabled(not busy and self.app_logic.is_ready_to_process())
        self.save_button.setEnabled(not busy and self.app_logic.is_ready_to_save())
        self.image_list_widget.setEnabled(not busy)
        self.class_list_widget.setEnabled(not busy)
        self.add_class_button.setEnabled(not busy)
        self.remove_class_button.setEnabled(not busy)
        self.delete_image_button.setEnabled(not busy)
        self.clear_images_button.setEnabled(not busy)
        self.import_classes_button.setEnabled(not busy)
        self.export_classes_button.setEnabled(not busy)
        self.aug_settings_button.setEnabled(not busy)
        self.augment_spinbox.setEnabled(not busy)

        self.progress_bar.setVisible(busy)
        if busy:
            self.status_bar.showMessage(message if message else "Processing...")
            self.progress_bar.setRange(0, 0) # Indeterminate progress
        else:
            self.status_bar.showMessage("Ready" if not message else message, 5000) # Show Ready or final message
            self.progress_bar.setRange(0, 100) # Reset progress bar

    def update_progress(self, value: int, maximum: int):
        """Update determinate progress bar with current progress."""
        if maximum <= 0:
            # Handle invalid maximum values
            self.progress_bar.setRange(0, 0)  # Indeterminate mode
            return
        
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)
        
        # Calculate percentage for better readability
        percentage = int((value / maximum) * 100) if maximum > 0 else 0
        self.progress_bar.setFormat(f"{percentage}% ({value}/{maximum})")
        
        # Update status message with progress
        current_msg = self.status_bar.currentMessage()
        if current_msg and "..." in current_msg:
            # Only update if the message seems to be a "processing" message
            base_msg = current_msg.split(" - ")[0] if " - " in current_msg else current_msg
            self.status_bar.showMessage(f"{base_msg} - {percentage}% complete")

    def get_image_canvas(self) -> ImageCanvas:
        return self.image_canvas

    def show_message(self, title: str, message: str, icon=QMessageBox.Icon.Information):
         msg_box = QMessageBox(self)
         msg_box.setIcon(icon)
         msg_box.setWindowTitle(title)
         msg_box.setText(message)
         msg_box.exec()

    def _update_mouse_coords_status(self, pos: QPoint):
        """Updates the status bar with image coordinates."""
        if pos:
            self.mouse_coords_label.setText(f"Image Coords: ({pos.x()}, {pos.y()})")
        else:
            self.mouse_coords_label.setText("")

    def show_auto_save_indicator(self):
        """Show the auto-save indicator and start timer to hide it"""
        self.auto_save_label.setVisible(True)
        self.auto_save_indicator_timer.start(2000)  # Hide after 2 seconds
        
    def _hide_auto_save_indicator(self):
        """Hide the auto-save indicator"""
        self.auto_save_label.setVisible(False)

    # Add methods to get current selections if needed by AppLogic,
    # e.g., get_selected_image_path(), get_selected_class_index()

    def _create_menus(self):
        """Create application menus"""
        # Main menu bar
        menu_bar = self.menuBar()
        
        # File menu
        file_menu = menu_bar.addMenu("&File")
        
        # Add images action
        add_images_action = file_menu.addAction("&Add Images...")
        add_images_action.triggered.connect(self.add_images_requested)
        
        # Select model action
        select_model_action = file_menu.addAction("Select &Model...")
        select_model_action.triggered.connect(self.select_model_requested)
        
        file_menu.addSeparator()
        
        # Classes submenu
        classes_menu = file_menu.addMenu("&Classes")
        
        # Import classes action
        import_classes_action = classes_menu.addAction("&Import Classes...")
        import_classes_action.triggered.connect(self._on_import_classes)
        import_classes_action.setShortcut(QKeySequence("Ctrl+I"))
        import_classes_action.setStatusTip("Import class names from a text file (Ctrl+I)")
        
        # Export classes action
        export_classes_action = classes_menu.addAction("&Export Classes...")
        export_classes_action.triggered.connect(self._on_export_classes)
        export_classes_action.setShortcut(QKeySequence("Ctrl+E"))
        export_classes_action.setStatusTip("Export class names to a text file (Ctrl+E)")
        
        # Sort classes action
        sort_classes_action = classes_menu.addAction("&Sort Classes Alphabetically")
        sort_classes_action.triggered.connect(self._on_sort_classes)
        sort_classes_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        sort_classes_action.setStatusTip("Sort the class list alphabetically (Ctrl+Shift+S)")
        
        file_menu.addSeparator()
        
        # Save dataset action
        save_dataset_action = file_menu.addAction("&Save Dataset...")
        save_dataset_action.triggered.connect(self._on_save_clicked)
        
        file_menu.addSeparator()
        
        # Save application state action
        save_state_action = file_menu.addAction("Save App &State")
        save_state_action.triggered.connect(self.save_state_requested)
        
        # Reset application state action
        reset_state_action = file_menu.addAction("&Reset App State")
        reset_state_action.triggered.connect(self._on_reset_state_clicked)
        
        file_menu.addSeparator()
        
        # Exit action
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)
        
    def _on_reset_state_clicked(self):
        """Handle reset state button click with confirmation"""
        reply = QMessageBox.question(
            self, 
            'Reset Application State',
            'Are you sure you want to reset the application state?\n'
            'This will clear all saved annotations and settings.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_state_requested.emit()

    def _on_delete_image(self):
        selected_items = self.image_list_widget.selectedItems()
        if selected_items:
            item = selected_items[0]
            image_path = item.data(Qt.ItemDataRole.UserRole)
            if image_path:
                # Show confirmation dialog
                image_name = os.path.basename(image_path)
                reply = QMessageBox.question(
                    self, 
                    'Confirm Image Deletion',
                    f"Are you sure you want to delete image '{image_name}'?\n"
                    f"This will remove all annotations for this image.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.delete_image_requested.emit(image_path)
        else:
            self.show_message("Info", "Select an image to delete.")

    def _on_clear_images(self):
        # Show confirmation dialog
        if self.image_list_widget.count() > 0:
            reply = QMessageBox.question(
                self, 
                'Confirm Clear All Images',
                f"Are you sure you want to clear all {self.image_list_widget.count()} images?\n"
                f"This will remove all annotations for these images.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.clear_images_requested.emit()
        else:
            self.show_message("Info", "No images to clear.")

    def _show_augmentation_settings(self):
        """Show the augmentation settings dialog."""
        dialog = AugmentationSettingsDialog(self)
        dialog.settings_changed.connect(self._on_augmentation_settings_changed)
        dialog.exec()
        
    def _on_augmentation_settings_changed(self, settings):
        """Handle changes to augmentation settings."""
        # Pass the settings to the app_logic to update the ImageAugmenter
        if self.app_logic:
            self.app_logic.set_augmentation_settings(settings)
            self.status_bar.showMessage("Augmentation settings updated", 3000)