import sys
import os
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QCheckBox, QToolBar, QStatusBar,
    QSpinBox, QProgressBar, QPushButton, QSpacerItem
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QAction, QTransform, QPainter
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QCoreApplication

# --- Constants ---
DEFAULT_ZOOM_FACTOR = 1.0
ZOOM_INCREMENT = 0.1
MAX_ZOOM = 5.0
MIN_ZOOM = 0.1
THUMBNAIL_SIZE = QSize(100, 141) # Approximate A4 ratio
DEFAULT_JPEG_QUALITY = 90
DEFAULT_CONVERSION_DPI = 150 # DPI for conversion, independent of view zoom

# --- Dark Theme Stylesheet ---
DARK_STYLESHEET = """
    QWidget {
        background-color: #2b2b2b;
        color: #f0f0f0;
        font-size: 10pt;
    }
    QMainWindow {
        background-color: #3c3f41;
        border: 1px solid #1e1e1e;
    }
    QToolBar {
        background-color: #3c3f41;
        border: none;
        padding: 2px;
        spacing: 5px; /* Spacing between buttons */
    }
    QToolBar QToolButton {
        background-color: #4b4f52;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 5px;
        min-width: 30px; /* Ensure buttons have some width */
    }
    QToolBar QToolButton:hover {
        background-color: #5a5f62;
    }
    QToolBar QToolButton:pressed {
        background-color: #6a6f72;
    }
    QToolBar QToolButton:disabled {
        background-color: #404040;
        color: #777;
        border: 1px solid #444;
    }
    QStatusBar {
        background-color: #3c3f41;
        color: #f0f0f0;
        border-top: 1px solid #1e1e1e;
    }
    QMenuBar {
        background-color: #3c3f41;
        color: #f0f0f0;
    }
    QMenuBar::item {
        background-color: transparent;
        padding: 4px 8px;
    }
    QMenuBar::item:selected {
        background-color: #4b4f52;
    }
    QMenu {
        background-color: #3c3f41;
        border: 1px solid #555;
        color: #f0f0f0;
    }
    QMenu::item:selected {
        background-color: #4b4f52;
    }
    QLabel {
        color: #f0f0f0;
    }
    QScrollArea {
        background-color: #2b2b2b;
        border: 1px solid #444;
    }
    QListWidget {
        background-color: #353535;
        border: 1px solid #444;
        padding: 5px;
    }
    QListWidget::item {
        color: #f0f0f0;
        padding: 5px;
        margin-bottom: 2px; /* Space between items */
        border-radius: 3px;
    }
    QListWidget::item:selected {
        background-color: #4a5157; /* Slightly lighter blue/gray */
        color: #ffffff;
        border: 1px solid #5a8cbb; /* Highlight border */
    }
    QListWidget::item:hover {
        background-color: #404040;
    }
    QCheckBox {
        spacing: 5px; /* Space between checkbox and text */
    }
    QCheckBox::indicator {
        width: 13px;
        height: 13px;
    }
    QCheckBox::indicator:unchecked {
        border: 1px solid #666;
        background-color: #444;
        border-radius: 3px;
    }
    QCheckBox::indicator:checked {
        background-color: #5a8cbb; /* Blueish color for checked */
        border: 1px solid #77aadd;
        border-radius: 3px;
        /* You might need to add an image for a check mark if desired */
    }
    QSpinBox {
        background-color: #4b4f52;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 2px 5px;
        color: #f0f0f0;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        subcontrol-origin: border;
        background-color: #5a5f62;
        border: 1px solid #666;
        border-radius: 2px;
        width: 16px;
    }
    QSpinBox::up-button { subcontrol-position: top right; }
    QSpinBox::down-button { subcontrol-position: bottom right; }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {
        background-color: #6a6f72;
    }
    QSpinBox::up-arrow, QSpinBox::down-arrow {
        width: 10px;
        height: 10px;
        /* Consider using QIcon for arrows if default look isn't good */
    }
    QPushButton {
        background-color: #4b4f52;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 5px 10px;
        min-width: 60px;
    }
    QPushButton:hover {
        background-color: #5a5f62;
    }
    QPushButton:pressed {
        background-color: #6a6f72;
    }
    QPushButton:disabled {
        background-color: #404040;
        color: #777;
        border: 1px solid #444;
    }
    QProgressBar {
        border: 1px solid #555;
        border-radius: 4px;
        text-align: center;
        background-color: #4b4f52;
        color: #f0f0f0;
    }
    QProgressBar::chunk {
        background-color: #5a8cbb; /* Blueish progress */
        border-radius: 3px;
        margin: 1px; /* Small margin around the chunk */
    }
    QMessageBox {
        background-color: #3c3f41;
        border: 1px solid #555;
    }
    QMessageBox QLabel { /* Target QLabel inside QMessageBox */
        color: #f0f0f0;
        background-color: transparent; /* Ensure it doesn't override */
    }
    QMessageBox QPushButton { /* Target buttons inside QMessageBox */
        background-color: #4b4f52;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 5px 10px;
        min-width: 70px; /* Ensure buttons are wide enough */
    }
    QMessageBox QPushButton:hover { background-color: #5a5f62; }
    QMessageBox QPushButton:pressed { background-color: #6a6f72; }
"""

# --- Conversion Worker Thread ---
class ConversionWorker(QThread):
    """
    Worker thread to handle PDF to JPEG conversion in the background.
    """
    progress_update = pyqtSignal(int)  # Signal for progress percentage
    conversion_finished = pyqtSignal(str) # Signal for success message
    conversion_error = pyqtSignal(str)   # Signal for error message

    def __init__(self, pdf_path, page_indices, output_folder, quality, dpi):
        super().__init__()
        self.pdf_path = pdf_path
        self.page_indices = page_indices # 0-based indices
        self.output_folder = output_folder
        self.quality = quality
        self.dpi = dpi
        self.is_running = True

    def run(self):
        """Execute the conversion process."""
        try:
            doc = fitz.open(self.pdf_path)
            total_pages_to_convert = len(self.page_indices)
            base_filename = os.path.splitext(os.path.basename(self.pdf_path))[0]

            # Calculate matrix for desired DPI
            matrix = fitz.Matrix(self.dpi / 72, self.dpi / 72)

            for i, page_index in enumerate(self.page_indices):
                if not self.is_running:
                    self.conversion_error.emit("Conversion cancelled.")
                    return

                if 0 <= page_index < doc.page_count:
                    page = doc.load_page(page_index)
                    pix = page.get_pixmap(matrix=matrix, alpha=False) # No alpha for JPEG

                    # Construct output path
                    output_filename = f"{base_filename}_page_{page_index + 1}.jpg"
                    output_path = os.path.join(self.output_folder, output_filename)

                    # Convert QPixmap to QImage for saving with quality
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                    if not img.save(output_path, "JPEG", self.quality):
                         raise IOError(f"Failed to save page {page_index + 1} to {output_path}")

                    # Emit progress
                    progress = int(((i + 1) / total_pages_to_convert) * 100)
                    self.progress_update.emit(progress)
                else:
                    print(f"Warning: Page index {page_index} out of bounds.") # Log warning

            doc.close()
            self.conversion_finished.emit(f"Successfully converted {total_pages_to_convert} page(s).")

        except Exception as e:
            self.conversion_error.emit(f"Conversion failed: {str(e)}")
        finally:
            # Ensure doc is closed if an error occurred mid-process
            if 'doc' in locals() and doc is not None and not doc.is_closed:
                doc.close()

    def stop(self):
        """Stop the conversion process."""
        self.is_running = False

# --- Main Application Window ---
class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf_document = None
        self.current_page_index = 0
        self.total_pages = 0
        self.zoom_factor = DEFAULT_ZOOM_FACTOR
        self.pdf_path = ""
        self.conversion_worker = None

        self.setWindowTitle("PyQt6 PDF Viewer & Converter")
        self.setGeometry(100, 100, 1200, 800) # Initial size

        self._init_ui()
        self.apply_dark_theme()
        self._update_ui_state() # Initial state (most things disabled)

    def _init_ui(self):
        """Initialize the user interface components."""
        # --- Central Widget & Layout ---
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # --- Left Panel: Page List & Controls ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(250) # Fixed width for the list panel

        # Page List Widget (Thumbnails)
        self.page_list_widget = QListWidget()
        self.page_list_widget.setSpacing(5)
        self.page_list_widget.setIconSize(THUMBNAIL_SIZE)
        self.page_list_widget.setMovement(QListWidget.Movement.Static) # Prevent dragging
        self.page_list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection) # Selection handled by checkbox
        self.page_list_widget.currentItemChanged.connect(self._go_to_selected_list_item) # Navigate on click
        left_layout.addWidget(QLabel("Pages:"))
        left_layout.addWidget(self.page_list_widget)

        # Selection Buttons
        selection_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self._select_all_pages)
        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.clicked.connect(self._deselect_all_pages)
        selection_layout.addWidget(self.select_all_button)
        selection_layout.addWidget(self.deselect_all_button)
        left_layout.addLayout(selection_layout)

        # Conversion Controls
        conversion_label = QLabel("JPEG Quality (1-100):")
        self.quality_spinbox = QSpinBox()
        self.quality_spinbox.setRange(1, 100)
        self.quality_spinbox.setValue(DEFAULT_JPEG_QUALITY)
        self.quality_spinbox.setToolTip("Set the quality for JPEG conversion (higher is better quality, larger file size).")
        left_layout.addWidget(conversion_label)
        left_layout.addWidget(self.quality_spinbox)

        self.save_selected_button = QPushButton("Save Selected Pages")
        self.save_selected_button.clicked.connect(lambda: self._start_conversion(selected_only=True))
        self.save_selected_button.setToolTip("Convert selected pages to JPEG images.")
        self.save_all_button = QPushButton("Save All Pages")
        self.save_all_button.clicked.connect(lambda: self._start_conversion(selected_only=False))
        self.save_all_button.setToolTip("Convert all pages to JPEG images.")

        left_layout.addWidget(self.save_selected_button)
        left_layout.addWidget(self.save_all_button)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False) # Initially hidden
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        left_layout.addWidget(self.progress_bar)

        # Add left panel to main layout
        main_layout.addWidget(left_panel)

        # --- Right Panel: PDF Display ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Scroll Area for Image
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Image Label
        self.image_label = QLabel("Open a PDF file to view.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_label.setScaledContents(False) # We handle scaling manually for zoom

        self.scroll_area.setWidget(self.image_label)
        right_layout.addWidget(self.scroll_area)

        # Add right panel to main layout
        main_layout.addWidget(right_panel, 1) # Give right panel more stretch factor

        # --- Actions ---
        self._create_actions()

        # --- Menu Bar ---
        self._create_menus()

        # --- Toolbar ---
        self._create_toolbars()

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("No PDF loaded.")
        self.status_bar.addPermanentWidget(self.status_label)


    def _create_actions(self):
        """Create QAction objects for menus and toolbars."""
        # File Actions
        self.open_action = QAction(QIcon.fromTheme("document-open", QIcon("icons/open.png")), "&Open PDF...", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.setStatusTip("Open a PDF file")
        self.open_action.triggered.connect(self._open_pdf)

        self.exit_action = QAction(QIcon.fromTheme("application-exit", QIcon("icons/exit.png")), "E&xit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.setStatusTip("Exit the application")
        self.exit_action.triggered.connect(self.close)

        # Navigation Actions
        self.prev_page_action = QAction(QIcon.fromTheme("go-previous", QIcon("icons/prev.png")), "&Previous Page", self)
        self.prev_page_action.setShortcut("Left")
        self.prev_page_action.setStatusTip("Go to the previous page")
        self.prev_page_action.triggered.connect(self._previous_page)

        self.next_page_action = QAction(QIcon.fromTheme("go-next", QIcon("icons/next.png")), "&Next Page", self)
        self.next_page_action.setShortcut("Right")
        self.next_page_action.setStatusTip("Go to the next page")
        self.next_page_action.triggered.connect(self._next_page)

        # Zoom Actions
        self.zoom_in_action = QAction(QIcon.fromTheme("zoom-in", QIcon("icons/zoom_in.png")), "Zoom &In", self)
        self.zoom_in_action.setShortcut("Ctrl++")
        self.zoom_in_action.setStatusTip("Zoom in")
        self.zoom_in_action.triggered.connect(self._zoom_in)

        self.zoom_out_action = QAction(QIcon.fromTheme("zoom-out", QIcon("icons/zoom_out.png")), "Zoom &Out", self)
        self.zoom_out_action.setShortcut("Ctrl+-")
        self.zoom_out_action.setStatusTip("Zoom out")
        self.zoom_out_action.triggered.connect(self._zoom_out)

        self.zoom_reset_action = QAction(QIcon.fromTheme("zoom-original", QIcon("icons/zoom_reset.png")), "&Reset Zoom", self)
        self.zoom_reset_action.setShortcut("Ctrl+0")
        self.zoom_reset_action.setStatusTip("Reset zoom to 100%")
        self.zoom_reset_action.triggered.connect(self._reset_zoom)

        # Help Actions
        self.about_action = QAction(QIcon.fromTheme("help-about", QIcon("icons/about.png")), "&About", self)
        self.about_action.setStatusTip("Show information about the application")
        self.about_action.triggered.connect(self._about)

    def _create_menus(self):
        """Create the application's menu bar."""
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        # View Menu (for Zoom)
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_reset_action)
        view_menu.addSeparator()
        view_menu.addAction(self.prev_page_action)
        view_menu.addAction(self.next_page_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.about_action)

    def _create_toolbars(self):
        """Create the main toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(24, 24)) # Adjust icon size
        self.addToolBar(toolbar)

        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addAction(self.prev_page_action)
        toolbar.addAction(self.next_page_action)
        toolbar.addSeparator()
        toolbar.addAction(self.zoom_out_action)
        toolbar.addAction(self.zoom_in_action)
        toolbar.addAction(self.zoom_reset_action)
        toolbar.addSeparator()
        # Add Save buttons to toolbar as well? Maybe not, keep them in side panel.

    def apply_dark_theme(self):
        """Apply the dark stylesheet to the application."""
        self.setStyleSheet(DARK_STYLESHEET)
        # Force style update on children if needed
        QCoreApplication.processEvents()


    def _update_ui_state(self):
        """Enable/disable UI elements based on whether a PDF is loaded."""
        pdf_loaded = self.pdf_document is not None
        converting = self.conversion_worker is not None and self.conversion_worker.isRunning()

        # Enable/disable actions
        self.prev_page_action.setEnabled(pdf_loaded and self.current_page_index > 0 and not converting)
        self.next_page_action.setEnabled(pdf_loaded and self.current_page_index < self.total_pages - 1 and not converting)
        self.zoom_in_action.setEnabled(pdf_loaded and self.zoom_factor < MAX_ZOOM and not converting)
        self.zoom_out_action.setEnabled(pdf_loaded and self.zoom_factor > MIN_ZOOM and not converting)
        self.zoom_reset_action.setEnabled(pdf_loaded and self.zoom_factor != DEFAULT_ZOOM_FACTOR and not converting)

        # Enable/disable buttons
        self.select_all_button.setEnabled(pdf_loaded and not converting)
        self.deselect_all_button.setEnabled(pdf_loaded and not converting)
        self.save_selected_button.setEnabled(pdf_loaded and not converting)
        self.save_all_button.setEnabled(pdf_loaded and not converting)
        self.quality_spinbox.setEnabled(pdf_loaded and not converting)
        self.page_list_widget.setEnabled(pdf_loaded and not converting)

        # Show/hide progress bar
        self.progress_bar.setVisible(converting)

        # Update status bar
        if pdf_loaded:
            filename = os.path.basename(self.pdf_path)
            self.status_label.setText(f"{filename} | Page {self.current_page_index + 1} of {self.total_pages} | Zoom: {self.zoom_factor:.1f}x")
        else:
            self.status_label.setText("No PDF loaded.")


    def _open_pdf(self):
        """Open a PDF file using a file dialog."""
        if self.conversion_worker and self.conversion_worker.isRunning():
            QMessageBox.warning(self, "Busy", "Please wait for the current conversion to finish.")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open PDF File", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if filepath:
            try:
                # Close previous document if open
                if self.pdf_document:
                    self.pdf_document.close()
                    self.pdf_document = None # Explicitly clear

                self.pdf_document = fitz.open(filepath)
                self.pdf_path = filepath
                self.total_pages = self.pdf_document.page_count
                self.current_page_index = 0
                self.zoom_factor = DEFAULT_ZOOM_FACTOR

                self.setWindowTitle(f"PyQt6 PDF Viewer - {os.path.basename(filepath)}")
                self._populate_page_list()
                self._display_page(self.current_page_index)

            except Exception as e:
                QMessageBox.critical(self, "Error Loading PDF", f"Could not load file: {filepath}\nError: {e}")
                self.pdf_document = None
                self.pdf_path = ""
                self.total_pages = 0
                self.page_list_widget.clear()
                self.image_label.setText("Failed to load PDF.")
                self.setWindowTitle("PyQt6 PDF Viewer & Converter")
            finally:
                self._update_ui_state()


    def _populate_page_list(self):
        """Fill the QListWidget with page thumbnails and checkboxes."""
        self.page_list_widget.clear()
        if not self.pdf_document:
            return

        # Use a smaller DPI for thumbnails to speed things up
        thumb_dpi = 72
        thumb_matrix = fitz.Matrix(thumb_dpi / 72, thumb_dpi / 72)

        for i in range(self.total_pages):
            try:
                page = self.pdf_document.load_page(i)

                # Generate thumbnail pixmap
                pix = page.get_pixmap(matrix=thumb_matrix, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                thumbnail_pixmap = QPixmap.fromImage(img).scaled(THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon = QIcon(thumbnail_pixmap)

                # Create list item and checkbox widget
                item = QListWidgetItem(icon, "") # Text is handled by checkbox
                item.setSizeHint(QSize(THUMBNAIL_SIZE.width() + 30, THUMBNAIL_SIZE.height() + 10)) # Adjust size hint

                checkbox = QCheckBox(f"Page {i + 1}")
                checkbox.setChecked(False) # Default to unchecked
                # Store page index in checkbox for later retrieval
                checkbox.setProperty("page_index", i)
                checkbox.stateChanged.connect(self._update_selection_status) # Optional: update status immediately

                self.page_list_widget.addItem(item)
                # Set the checkbox as the item widget
                self.page_list_widget.setItemWidget(item, checkbox)

            except Exception as e:
                print(f"Error generating thumbnail for page {i+1}: {e}")
                # Add a placeholder item if thumbnail fails
                item = QListWidgetItem(f"Page {i + 1} (Error)")
                self.page_list_widget.addItem(item)

            # Allow UI to update slightly during population of large lists
            if i % 10 == 0:
                 QCoreApplication.processEvents()


    def _update_selection_status(self):
        # This function could be used to update counts or UI based on checkbox changes
        # For now, we just retrieve the state when needed for conversion
        pass

    def _go_to_selected_list_item(self, current_item, previous_item):
        """Navigate to the page corresponding to the clicked list item."""
        if current_item:
            widget = self.page_list_widget.itemWidget(current_item)
            if isinstance(widget, QCheckBox):
                page_index = widget.property("page_index")
                if page_index is not None:
                    self._display_page(page_index)


    def _display_page(self, page_index):
        """Render and display the specified page index."""
        if not self.pdf_document or not (0 <= page_index < self.total_pages):
            self.image_label.setText("Invalid page index.")
            return

        try:
            self.current_page_index = page_index
            page = self.pdf_document.load_page(self.current_page_index)

            # Calculate transformation matrix based on zoom factor
            mat = fitz.Matrix(self.zoom_factor, self.zoom_factor)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # Convert to QImage and then QPixmap
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(img)

            self.image_label.setPixmap(pixmap)
            # Optional: Adjust label size to pixmap size if not using scaled contents
            self.image_label.adjustSize()

            # Highlight the current page in the list (visually select the item)
            # Find the item corresponding to the page index
            for i in range(self.page_list_widget.count()):
                item = self.page_list_widget.item(i)
                widget = self.page_list_widget.itemWidget(item)
                if isinstance(widget, QCheckBox) and widget.property("page_index") == page_index:
                    # Ensure the item is visible and set as current
                    self.page_list_widget.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
                    # Note: We are not using built-in selection, so just scrolling is enough.
                    # If using selectionMode != NoSelection, you'd use:
                    # self.page_list_widget.setCurrentItem(item)
                    break


        except Exception as e:
            QMessageBox.critical(self, "Error Displaying Page", f"Could not display page {page_index + 1}.\nError: {e}")
            self.image_label.setText(f"Error loading page {page_index + 1}.")
        finally:
            self._update_ui_state()

    def _previous_page(self):
        """Go to the previous page."""
        if self.current_page_index > 0:
            self._display_page(self.current_page_index - 1)

    def _next_page(self):
        """Go to the next page."""
        if self.current_page_index < self.total_pages - 1:
            self._display_page(self.current_page_index + 1)

    def _zoom_in(self):
        """Increase the zoom factor."""
        if self.zoom_factor < MAX_ZOOM:
            self.zoom_factor = min(MAX_ZOOM, self.zoom_factor + ZOOM_INCREMENT)
            self._display_page(self.current_page_index) # Re-render with new zoom

    def _zoom_out(self):
        """Decrease the zoom factor."""
        if self.zoom_factor > MIN_ZOOM:
            self.zoom_factor = max(MIN_ZOOM, self.zoom_factor - ZOOM_INCREMENT)
            self._display_page(self.current_page_index) # Re-render with new zoom

    def _reset_zoom(self):
        """Reset zoom to default."""
        if self.zoom_factor != DEFAULT_ZOOM_FACTOR:
            self.zoom_factor = DEFAULT_ZOOM_FACTOR
            self._display_page(self.current_page_index)

    def _select_all_pages(self):
        """Check all checkboxes in the page list."""
        for i in range(self.page_list_widget.count()):
            item = self.page_list_widget.item(i)
            widget = self.page_list_widget.itemWidget(item)
            if isinstance(widget, QCheckBox):
                widget.setChecked(True)

    def _deselect_all_pages(self):
        """Uncheck all checkboxes in the page list."""
        for i in range(self.page_list_widget.count()):
            item = self.page_list_widget.item(i)
            widget = self.page_list_widget.itemWidget(item)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)

    def _get_selected_pages(self):
        """Return a list of 0-based indices of selected pages."""
        selected_indices = []
        for i in range(self.page_list_widget.count()):
            item = self.page_list_widget.item(i)
            widget = self.page_list_widget.itemWidget(item)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                page_index = widget.property("page_index")
                if page_index is not None:
                    selected_indices.append(page_index)
        return selected_indices

    def _start_conversion(self, selected_only=True):
        """Initiate the PDF to JPEG conversion process."""
        if not self.pdf_document:
            QMessageBox.warning(self, "No PDF", "Please open a PDF file first.")
            return

        if self.conversion_worker and self.conversion_worker.isRunning():
            QMessageBox.warning(self, "Busy", "A conversion is already in progress.")
            return

        if selected_only:
            pages_to_convert = self._get_selected_pages()
            if not pages_to_convert:
                QMessageBox.warning(self, "No Selection", "Please select at least one page to convert.")
                return
        else:
            # Convert all pages
            pages_to_convert = list(range(self.total_pages))

        output_folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if not output_folder:
            return # User cancelled

        quality = self.quality_spinbox.value()

        # Start the worker thread
        self.conversion_worker = ConversionWorker(
            self.pdf_path, pages_to_convert, output_folder, quality, DEFAULT_CONVERSION_DPI
        )
        self.conversion_worker.progress_update.connect(self._update_progress)
        self.conversion_worker.conversion_finished.connect(self._conversion_complete)
        self.conversion_worker.conversion_error.connect(self._conversion_error_occurred)
        self.conversion_worker.finished.connect(self._conversion_thread_finished) # Cleanup signal

        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.conversion_worker.start()
        self._update_ui_state() # Disable controls during conversion


    def _update_progress(self, value):
        """Update the progress bar."""
        self.progress_bar.setValue(value)
        self.status_label.setText(f"Converting... {value}%")

    def _conversion_complete(self, message):
        """Handle successful completion of the conversion."""
        QMessageBox.information(self, "Conversion Successful", message)
        self.status_label.setText(message) # Update status bar too

    def _conversion_error_occurred(self, error_message):
        """Handle errors during conversion."""
        QMessageBox.critical(self, "Conversion Error", error_message)
        self.status_label.setText("Conversion failed.")

    def _conversion_thread_finished(self):
        """Called when the worker thread finishes (success or error)."""
        self.conversion_worker = None # Clear the worker reference
        self.progress_bar.setVisible(False)
        self._update_ui_state() # Re-enable controls
        # Restore normal status message if needed
        if self.pdf_document:
             self._update_ui_state() # Call again to reset status text


    def _about(self):
        """Show the About dialog."""
        QMessageBox.about(
            self,
            "About PDF Viewer & Converter",
            "<b>PDF Viewer & Converter v1.0</b><br><br>"
            "A simple application to view PDF files and convert pages to JPEG format.<br><br>"
            "Built with Python, PyQt6, and PyMuPDF.<br>"
            "Dark theme applied using QSS."
        )

    def closeEvent(self, event):
        """Handle the window close event."""
        if self.conversion_worker and self.conversion_worker.isRunning():
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "A conversion is in progress. Are you sure you want to exit? The conversion will be cancelled.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.conversion_worker.stop() # Signal worker to stop
                self.conversion_worker.wait(1000) # Wait briefly for it to finish
            else:
                event.ignore()
                return

        # Cleanly close the PDF document
        if self.pdf_document:
            try:
                self.pdf_document.close()
            except Exception as e:
                print(f"Error closing PDF document: {e}") # Log error
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Optional: Set application details
    app.setApplicationName("PDFViewerConverter")
    app.setOrganizationName("GeminiCode")

    # For better icon integration on some systems
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)

    window = PDFViewerApp()
    window.show()
    sys.exit(app.exec())