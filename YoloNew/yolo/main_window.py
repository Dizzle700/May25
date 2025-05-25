"""
MainWindow module - Main window for the YOLO Dataset Creator application (PyQt6)
"""

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QProgressBar, QSpinBox, QDoubleSpinBox,
    QLineEdit, QStatusBar, QFileDialog, QMessageBox, QStyleOption, QStyle,
    QMenuBar, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QSettings, QCoreApplication, QDir, QPoint, QByteArray, pyqtSlot
from PyQt6.QtGui import QIcon, QPainter, QColor, QPalette, QAction, QCloseEvent
from typing import Dict

# Use local imports due to flat structure
from image_canvas import ImageCanvas

class MainWindow(QMainWindow):
    """
    Main window for the YOLO Dataset Creator application.
    """
    # --- Signals for AppLogic ---
    addImagesClicked = pyqtSignal(list)         # Emits list of file paths
    selectModelClicked = pyqtSignal(str)        # Emits model file path
    processImageClicked = pyqtSignal()          # Emits when process button clicked
    saveDatasetClicked = pyqtSignal(str)        # Emits output directory
    addClassClicked = pyqtSignal(str)           # Emits class name to add
    removeClassClicked = pyqtSignal(str)        # Emits class name to remove
    imageSelected = pyqtSignal(str)             # Emits image path when selected in list
    classSelected = pyqtSignal(str)             # Emits class name when selected in list
    configChanged = pyqtSignal(dict)            # Emits dict of config values (conf, iou, split)
    drawBoxClicked = pyqtSignal(bool)           # Emits True when Draw Box is toggled on, False off
    deleteSelectedBoxClicked = pyqtSignal()
    augmentationOptionsChanged = pyqtSignal(dict) # New signal

    # --- Signals for Project Operations (Emitted TO AppLogic) ---
    newProjectRequested = pyqtSignal()
    openProjectRequested = pyqtSignal(str) # file_path
    saveProjectRequested = pyqtSignal()
    saveProjectAsRequested = pyqtSignal(str) # file_path
    requestClose = pyqtSignal() # Signal to AppLogic to check save before closing

    def __init__(self):
        super().__init__()
        self._app_logic = None # Placeholder for AppLogic reference needed by closeEvent
        self.base_window_title = "YOLO Dataset Creator (PyQt6)"
        self.setWindowTitle(self.base_window_title)
        # self.resize(1300, 850) # Size will be handled by QSettings
        self.augment_actions: Dict[str, QAction] = {} # To store augmentation actions

        self._create_actions() # Now creates menu actions
        self._create_menu()
        self._create_widgets()
        self._create_layout()
        self._create_connections()
        self._update_buttons_state({}) # Initial empty state

        self.status_bar.showMessage("Ready")

        self._read_settings() # Load window state and other UI settings

    def set_app_logic(self, app_logic):
        """Set a reference to AppLogic, needed for closeEvent."""
        self._app_logic = app_logic

    def _create_actions(self):
        """Create QAction objects for menus and potentially toolbars."""
        # --- File Actions ---
        self.new_action = QAction(QIcon.fromTheme("document-new"), "&New Project", self)
        self.new_action.setShortcut("Ctrl+N")
        self.new_action.setStatusTip("Create a new annotation project")
        self.new_action.triggered.connect(self._on_new_project)

        self.open_action = QAction(QIcon.fromTheme("document-open"), "&Open Project...", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.setStatusTip("Open an existing annotation project (.ydc_proj file)")
        self.open_action.triggered.connect(self._prompt_open_project)

        self.save_action = QAction(QIcon.fromTheme("document-save"), "&Save Project", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setStatusTip("Save the current project")
        self.save_action.triggered.connect(self.saveProjectRequested)

        self.save_as_action = QAction(QIcon.fromTheme("document-save-as"), "Save Project &As...", self)
        self.save_as_action.setShortcut("Ctrl+Shift+S")
        self.save_as_action.setStatusTip("Save the current project to a new file")
        self.save_as_action.triggered.connect(self._prompt_save_project_as)

        self.exit_action = QAction(QIcon.fromTheme("application-exit"), "E&xit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.setStatusTip("Exit the application")
        self.exit_action.triggered.connect(self.close) # Triggers closeEvent

        # --- Augmentation Actions (Dynamically created later) ---
        # Placeholder, will be populated in _create_menu based on augmenter options
        pass

    def _create_menu(self):
        """Create the main menu bar."""
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        # --- Augmentations Menu --- #
        self.augment_menu = menu_bar.addMenu("&Augmentations")
        self.augment_menu.setEnabled(False)

        # Edit Menu (Placeholder)
        # edit_menu = menu_bar.addMenu("&Edit")
        # ... add actions ...

        # View Menu (Placeholder)
        # view_menu = menu_bar.addMenu("&View")
        # ... add actions ...

    def _create_widgets(self):
        """Create all the widgets for the main window."""
        # --- Top Controls ---
        self.add_images_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), " Add Images...")
        self.select_model_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon), " Select Model...")
        self.model_label = QLabel("Selected Model: None")
        self.model_label.setWordWrap(True)

        self.process_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), " Process Image")
        self.conf_spinbox = QDoubleSpinBox()
        self.conf_spinbox.setRange(0.01, 1.0)
        self.conf_spinbox.setSingleStep(0.05)
        self.conf_spinbox.setValue(0.25)
        self.conf_spinbox.setPrefix("Conf: ")
        self.iou_spinbox = QDoubleSpinBox()
        self.iou_spinbox.setRange(0.01, 1.0)
        self.iou_spinbox.setSingleStep(0.05)
        self.iou_spinbox.setValue(0.45)
        self.iou_spinbox.setPrefix("IoU: ")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False) # Status bar shows messages

        self.augmentations_spin = QSpinBox()
        self.augmentations_spin.setRange(0, 50) # Allow 0 augmentations
        self.augmentations_spin.setValue(0) # Default to 0
        self.augmentations_spin.setPrefix("Aug Count: ") # Changed prefix
        self.augmentations_spin.setToolTip("Number of augmented variations per image to generate during Save Dataset")

        self.save_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), " Save Dataset...")
        self.train_split_spinbox = QDoubleSpinBox()
        self.train_split_spinbox.setRange(0.1, 0.9)
        self.train_split_spinbox.setSingleStep(0.05)
        self.train_split_spinbox.setValue(0.8)
        self.train_split_spinbox.setPrefix("Train Split: ")
        self.train_split_spinbox.setDecimals(2)

        # --- Left Panel (Images) ---
        self.images_list = QListWidget()
        self.images_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.images_status_label = QLabel("Loaded: 0 images")

        # --- Center Panel (Annotation) ---
        self.image_canvas = ImageCanvas()
        self.zoom_in_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp), " Zoom +")
        self.zoom_out_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown), " Zoom -")
        self.fit_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), " Fit") # Icon choice is arbitrary
        self.draw_box_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView), " Draw Box") # Icon choice arbitrary
        self.draw_box_btn.setCheckable(True)
        self.delete_box_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), " Delete Box")

        # --- Right Panel (Classes) ---
        self.classes_list = QListWidget()
        self.classes_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.new_class_edit = QLineEdit()
        self.new_class_edit.setPlaceholderText("Enter new class name...")
        self.add_class_btn = QPushButton("Add Class")
        self.remove_class_btn = QPushButton("Remove Selected")

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _create_layout(self):
        """Create the main layout and add widgets."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Controls Panel Layout
        controls_panel = QWidget()
        controls_layout = QHBoxLayout(controls_panel)
        controls_layout.addWidget(self.add_images_btn)
        controls_layout.addWidget(self.select_model_btn)
        controls_layout.addWidget(self.model_label, 1) # Stretch label
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.process_btn)
        controls_layout.addWidget(self.conf_spinbox)
        controls_layout.addWidget(self.iou_spinbox)
        controls_layout.addWidget(self.progress_bar, 1) # Stretch progress bar
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.save_btn)
        controls_layout.addWidget(self.augmentations_spin)
        controls_layout.addWidget(self.train_split_spinbox)
        main_layout.addWidget(controls_panel)

        # Main Splitter Layout
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter, 1) # Make splitter take remaining space

        # Images Panel (Left)
        images_panel = QWidget()
        images_layout = QVBoxLayout(images_panel)
        images_layout.addWidget(QLabel("<b>Image Files</b>"))
        images_layout.addWidget(self.images_list, 1)
        images_layout.addWidget(self.images_status_label)
        main_splitter.addWidget(images_panel)

        # Annotation Panel (Center)
        annotation_panel = QWidget()
        annotation_layout = QVBoxLayout(annotation_panel)
        annotation_layout.addWidget(QLabel("<b>Annotation Area</b>"))
        annotation_layout.addWidget(self.image_canvas, 1) # Canvas takes most space

        canvas_controls_layout = QHBoxLayout()
        canvas_controls_layout.addWidget(self.zoom_in_btn)
        canvas_controls_layout.addWidget(self.zoom_out_btn)
        canvas_controls_layout.addWidget(self.fit_btn)
        canvas_controls_layout.addStretch(1)
        canvas_controls_layout.addWidget(self.draw_box_btn)
        canvas_controls_layout.addWidget(self.delete_box_btn)
        annotation_layout.addLayout(canvas_controls_layout)

        instructions = QLabel("Ctrl+Scroll: Zoom | Middle Mouse/Ctrl+Drag: Pan | Click Box: Select | Click Class: Assign/Select")
        instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instructions.setWordWrap(True)
        annotation_layout.addWidget(instructions)
        main_splitter.addWidget(annotation_panel)

        # Classes Panel (Right)
        classes_panel = QWidget()
        classes_layout = QVBoxLayout(classes_panel)
        classes_layout.addWidget(QLabel("<b>Classes</b>"))
        classes_layout.addWidget(self.classes_list, 1)
        classes_layout.addWidget(QLabel("Add New Class:"))
        classes_layout.addWidget(self.new_class_edit)
        add_remove_layout = QHBoxLayout()
        add_remove_layout.addWidget(self.add_class_btn)
        add_remove_layout.addWidget(self.remove_class_btn)
        classes_layout.addLayout(add_remove_layout)
        main_splitter.addWidget(classes_panel)

        # Set Splitter Sizes (adjust ratios as needed)
        total_width = self.width()
        main_splitter.setSizes([int(total_width * 0.18), int(total_width * 0.60), int(total_width * 0.22)])
        # Set stretch factors for better resizing
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1) # Center panel gets extra space
        main_splitter.setStretchFactor(2, 0)

    def _create_connections(self):
        """Connect signals and slots."""
        # Top Controls
        self.add_images_btn.clicked.connect(self._on_add_images_clicked)
        self.select_model_btn.clicked.connect(self._on_select_model_clicked)
        self.process_btn.clicked.connect(self.processImageClicked)
        self.save_btn.clicked.connect(self._on_save_dataset_clicked)
        self.conf_spinbox.valueChanged.connect(self._on_config_changed)
        self.iou_spinbox.valueChanged.connect(self._on_config_changed)
        self.train_split_spinbox.valueChanged.connect(self._on_config_changed)
        self.augmentations_spin.valueChanged.connect(self._on_config_changed)

        # Image List
        self.images_list.currentItemChanged.connect(self._on_image_selected)

        # Canvas Controls
        self.zoom_in_btn.clicked.connect(self.image_canvas.zoom_in)
        self.zoom_out_btn.clicked.connect(self.image_canvas.zoom_out)
        self.fit_btn.clicked.connect(self.image_canvas.fit_to_view)
        self.draw_box_btn.toggled.connect(self._on_draw_box_toggled)
        self.delete_box_btn.clicked.connect(self.deleteSelectedBoxClicked)

        # Class List / Management
        self.classes_list.currentItemChanged.connect(self._on_class_selected)
        self.add_class_btn.clicked.connect(self._on_add_class_clicked)
        self.new_class_edit.returnPressed.connect(self._on_add_class_clicked)
        self.remove_class_btn.clicked.connect(self._on_remove_class_clicked)

        # Canvas -> Main Window (indirectly to AppLogic)
        self.image_canvas.boxSelected.connect(self._on_box_selected_in_canvas)

        # --- No need to connect menu actions here, they are connected in _create_actions ---

    # --- Event Handlers / Slots for UI Actions ---

    def _get_last_dir(self, key: str) -> str:
        """Helper to get the last used directory from QSettings."""
        settings = QSettings()
        last_dir = settings.value(f"ui/last{key}Dir", QDir.homePath(), type=str)
        return last_dir

    def _set_last_dir(self, key: str, dir_path: str):
        """Helper to save the last used directory to QSettings."""
        settings = QSettings()
        settings.setValue(f"ui/last{key}Dir", dir_path)

    def _on_add_images_clicked(self):
        last_dir = self._get_last_dir("Image")
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Images", last_dir, "Image Files (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)"
        )
        if file_paths:
            self._set_last_dir("Image", os.path.dirname(file_paths[0]))
            self.addImagesClicked.emit(file_paths)

    def _on_select_model_clicked(self):
        last_dir = self._get_last_dir("Model")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select YOLO Model", last_dir, "YOLO Models (*.pt *.onnx)"
        )
        if file_path:
            self._set_last_dir("Model", os.path.dirname(file_path))
            self.selectModelClicked.emit(file_path)

    def _on_save_dataset_clicked(self):
        last_dir = self._get_last_dir("Dataset")
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory for Dataset", last_dir
        )
        if output_dir:
            self._set_last_dir("Dataset", output_dir)
            self.saveDatasetClicked.emit(output_dir)

    # --- Slots for Menu Actions ---
    def _on_new_project(self):
        # Forward to AppLogic (assuming AppLogic has a new_project method)
        if self._app_logic:
            self._app_logic.new_project()

    def _prompt_open_project(self):
        last_dir = self._get_last_dir("Project")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", last_dir, "YOLO Dataset Creator Project (*.ydc_proj);;All Files (*)"
        )
        if file_path:
            self._set_last_dir("Project", os.path.dirname(file_path))
            self.openProjectRequested.emit(file_path)

    def _prompt_save_project_as(self):
        last_dir = self._get_last_dir("Project")
        # Suggest a filename based on current project or default
        suggested_name = "untitled.ydc_proj"
        if self._app_logic and self._app_logic.current_project_path:
            suggested_name = os.path.basename(self._app_logic.current_project_path)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", os.path.join(last_dir, suggested_name),
            "YOLO Dataset Creator Project (*.ydc_proj);;All Files (*)"
        )
        if file_path:
             # Ensure it has the correct extension
            if not file_path.lower().endswith(".ydc_proj"):
                 file_path += ".ydc_proj"
            self._set_last_dir("Project", os.path.dirname(file_path))
            self.saveProjectAsRequested.emit(file_path)
            return True # Indicate save was attempted (used by AppLogic.save_project)
        return False # Indicate save was cancelled

    # --- Event Handlers / Slots for UI Interactions (keep existing) ---

    def _on_add_class_clicked(self):
        class_name = self.new_class_edit.text().strip()
        if class_name:
            self.addClassClicked.emit(class_name)
            self.new_class_edit.clear()
        else:
            self.status_bar.showMessage("Class name cannot be empty.", 3000)

    def _on_remove_class_clicked(self):
        selected_items = self.classes_list.selectedItems()
        if selected_items:
            class_name = selected_items[0].text()
            reply = QMessageBox.question(self, "Remove Class",
                                         f"Are you sure you want to remove class '{class_name}'?\nThis will unassign it from all annotations.",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                 self.removeClassClicked.emit(class_name)
        else:
             self.status_bar.showMessage("Select a class to remove.", 3000)

    def _on_image_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None):
        if current:
            image_path = current.data(Qt.ItemDataRole.UserRole) # Get path from item data
            self.imageSelected.emit(image_path)
        else:
            self.imageSelected.emit("") # Emit empty string if selection cleared

    def _on_class_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None):
        if current:
            class_name = current.text()
            self.classSelected.emit(class_name)
        else:
            self.classSelected.emit("")

    def _on_box_selected_in_canvas(self, box_index: int):
        # Maybe highlight corresponding class if box has one?
        # For now, just let AppLogic handle assignment logic.
        pass # No direct UI action needed here, AppLogic handles it

    def _on_config_changed(self):
        config = self.get_config()
        self.configChanged.emit(config)

    def _on_draw_box_toggled(self, checked: bool):
        self.drawBoxClicked.emit(checked)

    # --- UI Update Methods ---

    def add_images_to_list(self, image_paths: list[str]):
        """Add image paths to the QListWidget, storing the full path."""
        current_paths = set()
        for i in range(self.images_list.count()):
            item = self.images_list.item(i)
            current_paths.add(item.data(Qt.ItemDataRole.UserRole))

        for path in image_paths:
            if path not in current_paths:
                item = QListWidgetItem(os.path.basename(path))
                item.setData(Qt.ItemDataRole.UserRole, path) # Store full path
                item.setToolTip(path) # Show full path on hover
                self.images_list.addItem(item)
        self.images_status_label.setText(f"Loaded: {self.images_list.count()} images")

    def set_model_path(self, model_path: str | None):
        if model_path and os.path.isfile(model_path):
            self.model_label.setText(f"Selected Model: {os.path.basename(model_path)}")
            self.model_label.setToolTip(model_path)
        else:
            self.model_label.setText("Selected Model: None")
            self.model_label.setToolTip("")

    def add_class_to_list(self, class_name: str):
        # AppLogic should ensure it's not a duplicate, but double-check here
        if not self.classes_list.findItems(class_name, Qt.MatchFlag.MatchExactly):
            item = QListWidgetItem(class_name)
            self.classes_list.addItem(item)
            # Optional: Assign a color? Requires more logic.

    def remove_class_from_list(self, class_name: str):
        items = self.classes_list.findItems(class_name, Qt.MatchFlag.MatchExactly)
        for item in items:
            row = self.classes_list.row(item)
            self.classes_list.takeItem(row)
            del item # Explicitly delete item

    def get_selected_image_path(self) -> str | None:
        selected_items = self.images_list.selectedItems()
        return selected_items[0].data(Qt.ItemDataRole.UserRole) if selected_items else None

    def get_selected_class_name(self) -> str | None:
        selected_items = self.classes_list.selectedItems()
        return selected_items[0].text() if selected_items else None

    def get_class_names(self) -> list[str]:
        return [self.classes_list.item(i).text() for i in range(self.classes_list.count())]

    def display_image(self, image_path: str | None):
        """Tell the canvas to display the image."""
        if image_path:
            success = self.image_canvas.set_image(image_path=image_path)
            if not success:
                 self.show_message("Image Load Error", f"Failed to load or display image:\n{image_path}", "error")
        else:
            self.image_canvas.set_image(None) # Clear canvas

    def update_annotations(self, annotations: list[dict]):
        """Update the annotations displayed on the canvas."""
        self.image_canvas.set_annotations(annotations)

    def update_class_names_display(self, class_names: list[str]):
        """Update the class names list and the canvas's internal list."""
        # --- Update QListWidget ---
        # Store current selection
        selected_text = self.get_selected_class_name()

        # Clear and repopulate
        self.classes_list.clear()
        new_selection_row = -1
        for i, name in enumerate(class_names):
            item = QListWidgetItem(name)
            self.classes_list.addItem(item)
            if name == selected_text:
                 new_selection_row = i

        # Restore selection if possible
        if new_selection_row != -1:
             self.classes_list.setCurrentRow(new_selection_row)
        else:
             self.classes_list.clearSelection()

        # --- Update ImageCanvas ---
        self.image_canvas.set_class_names(class_names)

    def set_progress(self, value: int, max_value: int = 100):
        self.progress_bar.setRange(0, max_value)
        self.progress_bar.setValue(value)
        self.progress_bar.setTextVisible(value > 0 and value < max_value)

    def set_status(self, message: str, timeout: int = 0):
        self.status_bar.showMessage(message, timeout)

    def show_message(self, title: str, message: str, level: str = "info"):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        icon = QMessageBox.Icon.Information
        if level == "warning":
            icon = QMessageBox.Icon.Warning
        elif level == "error":
            icon = QMessageBox.Icon.Critical
        msg_box.setIcon(icon)
        msg_box.exec()

    def get_config(self) -> dict:
        return {
            'conf_threshold': self.conf_spinbox.value(),
            'iou_threshold': self.iou_spinbox.value(),
            'train_split': self.train_split_spinbox.value(),
            'augment_count': self.augmentations_spin.value(),
        }

    @pyqtSlot(dict)
    def _update_buttons_state(self, state: dict):
        """Update enabled state of buttons based on the state dict from AppLogic."""
        # --- Update buttons based on explicit state keys ---
        self.add_images_btn.setEnabled(state.get('enable_add_images', True))
        self.select_model_btn.setEnabled(state.get('enable_select_model', True))
        self.process_btn.setEnabled(state.get('enable_process', False))
        self.save_btn.setEnabled(state.get('enable_save_dataset', False))
        self.add_class_btn.setEnabled(state.get('enable_add_class', True))
        self.remove_class_btn.setEnabled(state.get('enable_remove_class', False))
        self.delete_box_btn.setEnabled(state.get('enable_delete_box', False))
        self.draw_box_btn.setEnabled(state.get('enable_draw_box', False))

        # --- Update Menu actions ---
        self.save_action.setEnabled(state.get('enable_save_project', False))
        self.save_as_action.setEnabled(state.get('enable_save_project_as', False))
        # New/Open/Exit are generally always enabled, unless maybe during modal processing?
        is_processing = not state.get('enable_add_images', True) # Infer processing from a base action
        self.new_action.setEnabled(not is_processing)
        self.open_action.setEnabled(not is_processing)
        # self.exit_action always enabled
        self.augment_menu.setEnabled(not is_processing) # Disable menu during processing

    @pyqtSlot(str, bool)
    def _update_window_title(self, project_path: str, is_dirty: bool):
        """Updates the window title with project name and dirty status."""
        title = self.base_window_title
        if project_path != "Unsaved Project":
             title = f"{os.path.basename(project_path)} - {title}"
        if is_dirty:
            title += " *"
        self.setWindowTitle(title)

    # --- Settings Persistence ---
    def _write_settings(self):
        """Save UI settings using QSettings."""
        settings = QSettings()
        settings.beginGroup("MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())
        # Save splitter sizes
        if hasattr(self, 'main_splitter'): # Check if splitter exists
             settings.setValue("mainSplitter", self.main_splitter.saveState())
        settings.endGroup()

        settings.beginGroup("UI")
        settings.setValue("confThreshold", self.conf_spinbox.value())
        settings.setValue("iouThreshold", self.iou_spinbox.value())
        settings.setValue("trainSplit", self.train_split_spinbox.value())
        settings.setValue("augmentCount", self.augmentations_spin.value())
        # Last directories are saved by the dialog handlers
        settings.endGroup()

        # Save Augmentation Options
        settings.beginGroup("AugmentationOptions")
        for name, action in self.augment_actions.items():
            settings.setValue(name, action.isChecked())
        settings.endGroup()

    def _read_settings(self):
        """Load UI settings using QSettings."""
        settings = QSettings()
        settings.beginGroup("MainWindow")
        geom = settings.value("geometry", QByteArray())
        if geom and isinstance(geom, QByteArray) and not geom.isEmpty():
             self.restoreGeometry(geom)
        state = settings.value("state", QByteArray())
        if state and isinstance(state, QByteArray) and not state.isEmpty():
             self.restoreState(state)
        # Restore splitter sizes
        if hasattr(self, 'main_splitter'): # Check if splitter exists
            splitter_state = settings.value("mainSplitter", QByteArray())
            if splitter_state and isinstance(splitter_state, QByteArray) and not splitter_state.isEmpty():
                self.main_splitter.restoreState(splitter_state)
            else:
                 # Apply default split if no saved state
                 total_width = self.size().width() if self.size().width() > 200 else 1200 # Use default if size not reliable yet
                 self.main_splitter.setSizes([int(total_width * 0.18), int(total_width * 0.60), int(total_width * 0.22)])

        settings.endGroup()

        settings.beginGroup("UI")
        self.conf_spinbox.setValue(settings.value("confThreshold", 0.25, type=float))
        self.iou_spinbox.setValue(settings.value("iouThreshold", 0.45, type=float))
        self.train_split_spinbox.setValue(settings.value("trainSplit", 0.8, type=float))
        self.augmentations_spin.setValue(settings.value("augmentCount", 0, type=int))
        settings.endGroup()

        # NOTE: Augmentation settings are read AFTER the menu is populated
        # in _read_augmentation_settings called from populate_augment_menu

        # Trigger initial config emission after loading general UI settings
        self._on_config_changed()

    def _read_augmentation_settings(self):
        """Load augmentation option states AFTER menu actions are created."""
        settings = QSettings()
        settings.beginGroup("AugmentationOptions")
        options_changed = False
        current_options = {}
        if not hasattr(self, 'augment_actions') or not self.augment_actions:
             print("Warning: Trying to read augmentation settings before actions are created.")
             settings.endGroup()
             return

        for name, action in self.augment_actions.items():
            # Default to the action's initial state if setting not found
            default_value = action.isChecked()
            is_checked = settings.value(name, default_value, type=bool)
            if action.isChecked() != is_checked:
                 action.setChecked(is_checked)
            current_options[name] = is_checked

        settings.endGroup()

    # --- Close Event Handling ---
    def closeEvent(self, event: QCloseEvent):
        """Handle the window close event, checking for unsaved changes."""
        if self._app_logic and self._app_logic._check_save_before_proceed():
            self._write_settings() # Save settings on successful close
            event.accept()
        else:
            event.ignore()

    def populate_augment_menu(self, aug_options: Dict[str, bool]):
        """Populate the Augmentations menu with checkable actions."""
        self.augment_menu.clear() # Clear any previous items
        self.augment_actions = {}
        for name, is_checked in aug_options.items():
            action = QAction(name, self, checkable=True)
            action.setChecked(is_checked)
            action.triggered.connect(self._on_augmentation_option_changed)
            self.augment_menu.addAction(action)
            self.augment_actions[name] = action
        self.augment_menu.setEnabled(True) # Enable the menu now
        # Read settings again specifically for augmentation options AFTER populating
        self._read_augmentation_settings()

    def _on_augmentation_option_changed(self):
        """Called when any augmentation checkable action is toggled."""
        current_options = {name: action.isChecked() for name, action in self.augment_actions.items()}
        self.augmentationOptionsChanged.emit(current_options)