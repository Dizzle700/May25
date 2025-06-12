

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QComboBox, QLineEdit, QFileDialog, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QMessageBox, QApplication, QSizePolicy
)
from PyQt6.QtGui import QPixmap, QIcon, QDrag, QPainter, QImage
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QSize, QPointF

# Import from other local .py files
from utils import APP_CONFIG, get_icon_path
from threading_workers import BackgroundRemovalWorker
from app_logic import BackgroundRemoverCore, ImageComposerCore # For type hinting or direct calls if not threaded

class DraggablePixmapItem(QGraphicsPixmapItem):
    """Custom QGraphicsPixmapItem that is draggable."""
    def __init__(self, pixmap, parent=None):
        super().__init__(pixmap, parent)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        # self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable) # Optional

    def itemChange(self, change, value):
        # Could add logic here if needed, e.g., snap to grid during drag
        return super().itemChange(change, value)

class SettingsPane(QWidget):
    """Left pane for all settings and batch processing controls."""
    # Define signals if this pane needs to communicate outwards, e.g.
    # start_processing_requested = pyqtSignal(dict) # dict could contain settings

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Batch Processing Section ---
        batch_group = QFrame(self)
        batch_group.setFrameShape(QFrame.Shape.StyledPanel)
        batch_layout = QVBoxLayout(batch_group)
        batch_layout.addWidget(QLabel("<b>Batch Background Removal</b>"))

        # Input Folder
        input_layout = QHBoxLayout()
        self.input_folder_edit = QLineEdit("No folder selected")
        self.input_folder_edit.setReadOnly(True)
        input_btn = QPushButton("Browse Input")
        input_btn.setIcon(QIcon(get_icon_path("folder_open.png"))) # Example icon
        input_btn.clicked.connect(self.select_input_folder)
        input_layout.addWidget(self.input_folder_edit)
        input_layout.addWidget(input_btn)
        batch_layout.addLayout(input_layout)

        # Output Folder
        output_layout = QHBoxLayout()
        self.output_folder_edit = QLineEdit("No folder selected / Using default")
        self.output_folder_edit.setReadOnly(True)
        output_btn = QPushButton("Browse Output")
        output_btn.setIcon(QIcon(get_icon_path("folder_open.png")))
        output_btn.clicked.connect(self.select_output_folder)
        output_layout.addWidget(self.output_folder_edit)
        output_layout.addWidget(output_btn)
        batch_layout.addLayout(output_layout)

        # Output Format
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Output Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "WebP", "Both"])
        format_layout.addWidget(self.format_combo)
        batch_layout.addLayout(format_layout)

        # Device
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Processing Device:"))
        self.device_label = QLabel("Auto (CPU/GPU)") # Will be updated
        self.switch_device_btn = QPushButton("Switch Device")
        # self.switch_device_btn.clicked.connect(self.parent().parent().switch_processing_device) # Connect in MainWindow
        device_layout.addWidget(self.device_label)
        device_layout.addWidget(self.switch_device_btn)
        batch_layout.addLayout(device_layout)

        # Processing Controls
        process_controls_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(QIcon(get_icon_path("start_icon.png")))
        # self.start_btn.clicked.connect(self.on_start_processing)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(QIcon(get_icon_path("pause_icon.png")))
        self.pause_btn.setEnabled(False)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(QIcon(get_icon_path("stop_icon.png")))
        self.stop_btn.setEnabled(False)
        process_controls_layout.addWidget(self.start_btn)
        process_controls_layout.addWidget(self.pause_btn)
        process_controls_layout.addWidget(self.stop_btn)
        batch_layout.addLayout(process_controls_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred
        )
        self.progress_bar.setMaximumWidth(300) # Adjust this value as needed
        batch_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready.")
        batch_layout.addWidget(self.status_label)

        layout.addWidget(batch_group)

        # --- Compositing Section ---
        compo_group = QFrame(self)
        compo_group.setFrameShape(QFrame.Shape.StyledPanel)
        compo_layout = QVBoxLayout(compo_group)
        compo_layout.addWidget(QLabel("<b>Image Compositing</b>"))

        self.bg_btn = QPushButton("Select Background Image")
        self.bg_btn.setIcon(QIcon(get_icon_path("background_icon.png")))
        # self.bg_btn.clicked.connect(self.parent().parent().select_background_for_canvas) # Connect in MainWindow
        compo_layout.addWidget(self.bg_btn)

        grid_layout_h = QHBoxLayout()
        grid_layout_h.addWidget(QLabel("Grid Layout:"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(["Freeform", "1x1", "2x2", "2x3", "3x2", "3x3"])
        # self.grid_combo.currentTextChanged.connect(self.parent().parent().canvas_pane.set_grid_mode) # Connect in MainWindow
        grid_layout_h.addWidget(self.grid_combo)
        compo_layout.addLayout(grid_layout_h)

        self.clear_canvas_btn = QPushButton("Clear Canvas")
        self.clear_canvas_btn.setIcon(QIcon(get_icon_path("clear_icon.png")))
        # self.clear_canvas_btn.clicked.connect(self.parent().parent().canvas_pane.clear_foreground_items) # Connect in MainWindow
        compo_layout.addWidget(self.clear_canvas_btn)

        self.save_composite_btn = QPushButton("Save Composite")
        self.save_composite_btn.setIcon(QIcon(get_icon_path("save_icon.png")))
        # self.save_composite_btn.clicked.connect(self.parent().parent().canvas_pane.save_composite) # Connect in MainWindow
        compo_layout.addWidget(self.save_composite_btn)

        layout.addWidget(compo_group)
        self.setLayout(layout)

    def select_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.input_folder_edit.setText(folder)
            # Potentially emit a signal or call a method in MainWindow to update image list
            print(f"Input folder selected: {folder}")


    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder_edit.setText(folder)
            print(f"Output folder selected: {folder}")

    def update_status(self, message):
        self.status_label.setText(message)

    def update_progress(self, value, maximum):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    def set_processing_buttons_state(self, is_processing):
        self.start_btn.setEnabled(not is_processing)
        self.pause_btn.setEnabled(is_processing)
        self.stop_btn.setEnabled(is_processing)
        if not is_processing:
            self.pause_btn.setText("Pause")


class CanvasPane(QGraphicsView):
    """Center pane for displaying and compositing images."""
    background_changed = pyqtSignal(QPixmap) # Signal when BG changes
    item_dropped_on_canvas = pyqtSignal(QPixmap, QPointF) # Pixmap and drop position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self.background_item = None
        self.foreground_items = [] # To keep track of added images
        self.grid_mode = "Freeform" # e.g., "2x2", "3x3"
        self.grid_lines = []

    def set_background_image(self, image_path):
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", f"Could not load background image: {image_path}")
            return

        if self.background_item:
            self.scene.removeItem(self.background_item)
        self.background_item = QGraphicsPixmapItem(pixmap)
        self.background_item.setZValue(-1) # Ensure it's behind foreground items
        self.scene.addItem(self.background_item)
        self.setSceneRect(self.background_item.boundingRect()) # Fit view to background
        self.fitInView(self.background_item.boundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.background_changed.emit(pixmap)
        self.draw_grid() # Redraw grid if mode is active

    def add_foreground_image(self, pixmap, position=None):
        if pixmap.isNull():
            return

        item = DraggablePixmapItem(pixmap)
        self.scene.addItem(item)
        self.foreground_items.append(item)

        if self.grid_mode != "Freeform" and self.background_item:
            self._snap_item_to_grid(item)
        elif position:
            item.setPos(position)
        else: # Default position if none given (e.g. center)
            item.setPos(self.scene.width()/2 - item.boundingRect().width()/2,
                        self.scene.height()/2 - item.boundingRect().height()/2)


    def _snap_item_to_grid(self, item):
        # Placeholder: Implement snapping logic based on self.grid_mode and mouse drop position
        if not self.background_item: return
        bg_rect = self.background_item.boundingRect()
        rows, cols = self._get_grid_dimensions()
        if rows == 0 or cols == 0: return

        cell_width = bg_rect.width() / cols
        cell_height = bg_rect.height() / rows

        # Determine which cell it was dropped into (based on item.pos() or mouse drop pos)
        # For simplicity, let's find the closest cell center for now
        # A more robust way would be to use the actual drop event's scenePos

        # This is a very basic snap to the top-left of the first cell, improve this
        target_col = int(item.pos().x() / cell_width) if cell_width > 0 else 0
        target_row = int(item.pos().y() / cell_height) if cell_height > 0 else 0
        target_col = max(0, min(target_col, cols -1))
        target_row = max(0, min(target_row, rows -1))

        cell_x = target_col * cell_width
        cell_y = target_row * cell_height

        # Scale item to fit cell (aspect ratio preserved)
        scaled_pixmap = item.pixmap().scaled(QSize(int(cell_width), int(cell_height)),
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        item.setPixmap(scaled_pixmap)

        # Center in cell
        item_x = cell_x + (cell_width - item.boundingRect().width()) / 2
        item_y = cell_y + (cell_height - item.boundingRect().height()) / 2
        item.setPos(item_x, item_y)
        print(f"Snapped item to grid cell ({target_row}, {target_col})")


    def _get_grid_dimensions(self):
        if self.grid_mode == "Freeform" or not self.grid_mode:
            return 0, 0
        try:
            rows, cols = map(int, self.grid_mode.split('x'))
            return rows, cols
        except ValueError:
            return 0, 0

    def set_grid_mode(self, mode_text):
        self.grid_mode = mode_text
        self.draw_grid()
        # Optionally re-snap existing items
        # for item in self.foreground_items:
        #     self._snap_item_to_grid(item)

    def draw_grid(self):
        # Clear existing grid lines
        for line in self.grid_lines:
            self.scene.removeItem(line)
        self.grid_lines.clear()

        if self.grid_mode == "Freeform" or not self.background_item:
            return

        rows, cols = self._get_grid_dimensions()
        if rows == 0 or cols == 0: return

        bg_rect = self.background_item.boundingRect()
        pen = QPainter().pen() # Default pen
        pen.setColor(Qt.GlobalColor.gray)
        pen.setStyle(Qt.PenStyle.DashLine)

        # Draw vertical lines
        for i in range(1, cols):
            x = bg_rect.left() + i * (bg_rect.width() / cols)
            line = self.scene.addLine(x, bg_rect.top(), x, bg_rect.bottom(), pen)
            line.setZValue(0) # Above background, below foreground items
            self.grid_lines.append(line)

        # Draw horizontal lines
        for i in range(1, rows):
            y = bg_rect.top() + i * (bg_rect.height() / rows)
            line = self.scene.addLine(bg_rect.left(), y, bg_rect.right(), y, pen)
            line.setZValue(0)
            self.grid_lines.append(line)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-qt-imagepath") or \
           event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-qt-imagepath"):
            image_path = event.mimeData().data("application/x-qt-imagepath").data().decode()
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                drop_pos = self.mapToScene(event.position().toPoint())
                self.add_foreground_image(pixmap, drop_pos)
                self.item_dropped_on_canvas.emit(pixmap, drop_pos)
            event.acceptProposedAction()
        elif event.mimeData().hasImage():
            qimage = event.mimeData().imageData()
            pixmap = QPixmap.fromImage(qimage)
            if not pixmap.isNull():
                drop_pos = self.mapToScene(event.position().toPoint())
                self.add_foreground_image(pixmap, drop_pos)
                self.item_dropped_on_canvas.emit(pixmap, drop_pos)
            event.acceptProposedAction()
        else:
            event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.background_item:
            self.fitInView(self.background_item.boundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.draw_grid() # Redraw grid on resize

    def clear_foreground_items(self):
        for item in self.foreground_items:
            self.scene.removeItem(item)
        self.foreground_items.clear()
        print("Canvas foreground cleared.")

    def save_composite(self):
        if not self.background_item:
            QMessageBox.warning(self, "Save Error", "No background image to save.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Composite Image", "", "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg)"
        )
        if file_path:
            # Ensure scene bounding rect is tight around the content
            self.scene.setSceneRect(self.scene.itemsBoundingRect())
            image = QImage(self.scene.sceneRect().size().toSize(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent) # Fill with transparent before painting

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.scene.render(painter) # Render the scene to the image
            painter.end()

            if image.save(file_path):
                QMessageBox.information(self, "Success", f"Composite image saved to {file_path}")
            else:
                QMessageBox.critical(self, "Save Error", f"Could not save image to {file_path}")


class ProcessedImagesPane(QListWidget):
    """Right pane to display thumbnails of processed (transparent background) images."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(100, 100))
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setDragEnabled(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setWordWrap(True) # For item text if any

    def add_processed_image(self, image_path, thumbnail_pixmap=None):
        if thumbnail_pixmap is None:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                print(f"Error: Could not load thumbnail for {image_path}")
                return
            # Create a smaller thumbnail for the list
            thumbnail_pixmap = pixmap.scaled(self.iconSize(),
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)

        item = QListWidgetItem(QIcon(thumbnail_pixmap), image_path.split('/')[-1].split('\\')[-1])
        item.setData(Qt.ItemDataRole.UserRole, image_path) # Store full path
        item.setSizeHint(QSize(self.iconSize().width() + 20, self.iconSize().height() + 40)) # Adjust item size
        self.addItem(item)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item:
            image_path = item.data(Qt.ItemDataRole.UserRole)
            mime_data = QMimeData()
            # Using a custom MIME type for path, or can send QImage directly
            mime_data.setData("application/x-qt-imagepath", image_path.encode())

            # For direct image data (can be large for many items)
            # pixmap = QPixmap(image_path)
            # if not pixmap.isNull():
            #     mime_data.setImageData(pixmap.toImage())

            drag = QDrag(self)
            drag.setMimeData(mime_data)

            # Optional: set a pixmap for the drag cursor
            drag_pixmap = QPixmap(image_path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio)
            drag.setPixmap(drag_pixmap)
            drag.setHotSpot(drag_pixmap.rect().center())

            # drag.exec(supportedActions) # Old way
            drag.exec(supportedActions, Qt.DropAction.CopyAction)


class MainWindow(QMainWindow):
    """Main application window."""
    def __init__(self):
        super().__init__()
        self.bg_remover_core = BackgroundRemoverCore() # Handles model and processing logic
        self.image_composer_core = ImageComposerCore() # Handles compositing logic
        self.bg_removal_worker = None # For threaded background removal

        self.setWindowTitle(APP_CONFIG.get("app_name", "Smart Background Remover & Compositor"))
        self.setGeometry(100, 100, 1200, 700) # x, y, width, height
        self.init_ui()
        self.connect_signals()
        self.update_device_label()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Create Panes
        self.settings_pane = SettingsPane()
        self.canvas_pane = CanvasPane()
        self.processed_images_pane = ProcessedImagesPane()

        # Use QSplitter for resizable panes
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.settings_pane)
        splitter.addWidget(self.canvas_pane)
        splitter.addWidget(self.processed_images_pane)

        # Adjust initial sizes (optional)
        splitter.setSizes([300, 600, 300]) # Left, Center, Right initial widths

        main_layout.addWidget(splitter)
        self.create_menus() # Optional

    def create_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(QApplication.instance().quit)

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about_dialog)

    def show_about_dialog(self):
        QMessageBox.about(self, "About " + APP_CONFIG.get("app_name", ""),
                          f"{APP_CONFIG.get('app_name', '')}\nVersion {APP_CONFIG.get('version', '1.0')}\n\n"
                          "Powered by RMBG-2.0 AI Model.\n"
                          "Developed by [Your Name/Organization].")


    def connect_signals(self):
        # Settings Pane controls -> Main Window handlers
        self.settings_pane.start_btn.clicked.connect(self.start_batch_processing)
        self.settings_pane.pause_btn.clicked.connect(self.pause_batch_processing)
        self.settings_pane.stop_btn.clicked.connect(self.stop_batch_processing)
        self.settings_pane.switch_device_btn.clicked.connect(self.switch_processing_device)
        self.settings_pane.bg_btn.clicked.connect(self.select_background_for_canvas)
        self.settings_pane.grid_combo.currentTextChanged.connect(self.canvas_pane.set_grid_mode)
        self.settings_pane.clear_canvas_btn.clicked.connect(self.canvas_pane.clear_foreground_items)
        self.settings_pane.save_composite_btn.clicked.connect(self.canvas_pane.save_composite)


    def update_device_label(self):
        device_name = self.bg_remover_core.get_device_name()
        self.settings_pane.device_label.setText(device_name)

    def switch_processing_device(self):
        switched = self.bg_remover_core.switch_device()
        if switched:
            self.update_device_label()
            QMessageBox.information(self, "Device Switched", f"Processing device set to {self.bg_remover_core.get_device_name()}.")
        else:
            QMessageBox.information(self, "Device Switch", "No other processing device available or switch failed.")


    def select_background_for_canvas(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if file_path:
            self.canvas_pane.set_background_image(file_path)

    # --- Batch Background Removal Handling ---
    def start_batch_processing(self):
        input_dir = self.settings_pane.input_folder_edit.text()
        output_dir = self.settings_pane.output_folder_edit.text() # Add logic for default if empty
        output_format = self.settings_pane.format_combo.currentText()

        if not input_dir or input_dir == "No folder selected":
            QMessageBox.warning(self, "Input Missing", "Please select an input folder.")
            return

        if not output_dir or output_dir == "No folder selected / Using default":
            # Default to a "processed" subfolder in input_dir
            import os
            output_dir = os.path.join(input_dir, "processed_images")
            os.makedirs(output_dir, exist_ok=True)
            self.settings_pane.output_folder_edit.setText(output_dir)


        self.settings_pane.update_status("Initializing background removal...")
        self.settings_pane.set_processing_buttons_state(True)
        self.processed_images_pane.clear() # Clear previous results

        # Ensure model is loaded (can be done once at app start or here)
        if not self.bg_remover_core.model_loaded:
            if not self.bg_remover_core.load_model():
                self.settings_pane.update_status("Error: Failed to load AI model.")
                self.settings_pane.set_processing_buttons_state(False)
                return

        self.bg_removal_worker = BackgroundRemovalWorker(
            self.bg_remover_core, input_dir, output_dir, output_format
        )
        self.bg_removal_worker.progress_updated.connect(self.settings_pane.update_progress)
        self.bg_removal_worker.status_updated.connect(self.settings_pane.update_status)
        self.bg_removal_worker.image_processed.connect(self.processed_images_pane.add_processed_image)
        self.bg_removal_worker.processing_finished.connect(self.on_batch_processing_finished)
        self.bg_removal_worker.start()

    def pause_batch_processing(self):
        if self.bg_removal_worker and self.bg_removal_worker.isRunning():
            if self.bg_removal_worker.is_paused():
                self.bg_removal_worker.resume()
                self.settings_pane.pause_btn.setText("Pause")
                self.settings_pane.update_status("Resuming...")
            else:
                self.bg_removal_worker.pause()
                self.settings_pane.pause_btn.setText("Resume")
                self.settings_pane.update_status("Paused.")

    def stop_batch_processing(self):
        if self.bg_removal_worker and self.bg_removal_worker.isRunning():
            self.bg_removal_worker.stop()
            self.settings_pane.update_status("Stopping...")
            # State will be fully reset in on_batch_processing_finished

    def on_batch_processing_finished(self, message):
        self.settings_pane.set_processing_buttons_state(False)
        self.settings_pane.update_status(message)
        self.settings_pane.progress_bar.setValue(0) # Reset progress bar
        if "successfully" in message.lower() and self.settings_pane.output_folder_edit.text():
            try:
                output_dir = self.settings_pane.output_folder_edit.text()
                # Try to open output folder (platform dependent)
                import os, subprocess, platform
                if platform.system() == "Windows":
                    os.startfile(output_dir)
                elif platform.system() == "Darwin": # macOS
                    subprocess.Popen(["open", output_dir])
                else: # Linux
                    subprocess.Popen(["xdg-open", output_dir])
            except Exception as e:
                print(f"Could not open output folder: {e}")

        self.bg_removal_worker = None # Clear worker

    def closeEvent(self, event):
        # Ensure worker thread is stopped cleanly if app is closed during processing
        if self.bg_removal_worker and self.bg_removal_worker.isRunning():
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Processing is ongoing. Are you sure you want to exit?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_batch_processing()
                # self.bg_removal_worker.wait() # Wait for thread to finish (can hang if not careful)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
