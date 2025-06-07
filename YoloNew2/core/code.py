import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QApplication, QRubberBand, QMenu
from PyQt6.QtGui import QPainter, QPixmap, QColor, QPen, QImage, QCursor, QAction
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal

from core.models import BoundingBox
from core import utils # Assuming utils has conversion functions

class ImageCanvas(QWidget):
    """Widget for displaying images and handling bounding box annotations."""
    # Signals
    annotations_changed = pyqtSignal() # Emitted when boxes are added/modified/deleted
    box_selected = pyqtSignal(int) # Emits index of selected box, or -1 if deselected
    new_box_request = pyqtSignal(QRect) # Emits pixel rect of newly drawn box
    delete_box_request = pyqtSignal(int) # Emits index of box to delete
    mouse_pos_changed = pyqtSignal(QPoint) # Emits pixel coordinates relative to image

    # Editing states
    IDLE = 0
    DRAWING = 1
    SELECTING = 2 # (Maybe merge with IDLE, selected_box_idx indicates selection)
    MOVING = 3
    RESIZING = 4

    # Resize handle codes (powers of 2 for bitwise checks)
    HANDLE_NONE = 0
    HANDLE_TOP_LEFT = 1
    HANDLE_TOP_RIGHT = 2
    HANDLE_BOTTOM_LEFT = 4
    HANDLE_BOTTOM_RIGHT = 8
    HANDLE_TOP = 16
    HANDLE_BOTTOM = 32
    HANDLE_LEFT = 64
    HANDLE_RIGHT = 128
    HANDLE_MOVE = 256 # Special case for moving the whole box

    HANDLE_SIZE = 10 # Size of resize handles in pixels

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image_path = None
        self.pixmap: QPixmap | None = None
        self.cv_image: np.ndarray | None = None # Store OpenCV image for processing
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0) # For panning (future enhancement)

        self.annotations: List[BoundingBox] = []
        self.class_names: List[str] = []

        self.rubber_band: QRubberBand | None = None
        self.origin = QPoint() # Start point for drawing/moving

        self.current_state = self.IDLE
        self.selected_box_idx = -1
        self.hovered_box_idx = -1
        self.hovered_handle = self.HANDLE_NONE
        self.resizing_origin_rect = QRect() # Original rect before resize/move

        self.setMouseTracking(True) # Enable mouseMoveEvent even without button press

    def set_image(self, image_path: str):
        """Loads and displays an image."""
        self.current_image_path = image_path
        try:
            self.cv_image = cv2.imread(image_path)
            if self.cv_image is None:
                raise ValueError(f"Could not load image: {image_path}")
            self.cv_image = cv2.cvtColor(self.cv_image, cv2.COLOR_BGR2RGB) # Convert for QImage
            height, width, channel = self.cv_image.shape
            bytes_per_line = 3 * width
            q_image = QImage(self.cv_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            self.pixmap = QPixmap.fromImage(q_image)
            self.selected_box_idx = -1 # Deselect box on new image
            self.hovered_box_idx = -1
            self.hovered_handle = self.HANDLE_NONE
            # Reset scale/offset if desired, or implement zoom/pan logic
            self.scale_factor = 1.0
            self.offset = QPoint(0, 0)
            self.update() # Trigger repaint
        except Exception as e:
            print(f"Error loading image {image_path}: {e}")
            self.pixmap = None
            self.cv_image = None
            self.update()

    def set_annotations(self, annotations: List[BoundingBox], class_names: List[str]):
        """Updates the annotations to be displayed."""
        self.annotations = annotations
        self.class_names = class_names
        # Keep selection if index is still valid
        if self.selected_box_idx >= len(self.annotations):
             self.selected_box_idx = -1
        self.update()

    def get_image_coords(self, event_pos: QPoint) -> QPoint | None:
        """Converts widget coordinates to image pixel coordinates."""
        if self.pixmap is None:
            return None

        # Basic version without zoom/pan
        # TODO: Add scale_factor and offset calculations for zoom/pan
        scaled_pixmap_rect = self._get_scaled_pixmap_rect()
        if not scaled_pixmap_rect.contains(event_pos):
            return None # Click outside image

        img_x = int((event_pos.x() - scaled_pixmap_rect.x()) / self.scale_factor)
        img_y = int((event_pos.y() - scaled_pixmap_rect.y()) / self.scale_factor)

        # Clamp to image dimensions
        img_width = self.pixmap.width()
        img_height = self.pixmap.height()
        img_x = max(0, min(img_x, img_width - 1))
        img_y = max(0, min(img_y, img_height - 1))

        return QPoint(img_x, img_y)

    def _get_scaled_pixmap_rect(self) -> QRect:
        """Calculates the rectangle where the scaled pixmap is drawn."""
        if not self.pixmap:
            return QRect()

        pm_size = self.pixmap.size()
        scaled_size = pm_size * self.scale_factor
        widget_size = self.size()

        # Center the image (basic centering)
        x = max(0, int((widget_size.width() - scaled_size.width()) / 2)) + self.offset.x()
        y = max(0, int((widget_size.height() - scaled_size.height()) / 2)) + self.offset.y()

        # TODO: Improve centering/positioning with panning

        return QRect(QPoint(x, y), scaled_size.toSize())


    # --- Event Handlers ---

    def mousePressEvent(self, event):
        if self.pixmap is None: return

        image_pos = self.get_image_coords(event.pos())
        if image_pos is None: return # Click outside

        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.pos() # Store widget coords for rubberband/dragging

            handle, box_idx = self._check_handle_or_box_hover(event.pos())

            if self.selected_box_idx != -1 and handle != self.HANDLE_NONE:
                # Start resizing or moving the selected box
                self.current_state = self.RESIZING if handle != self.HANDLE_MOVE else self.MOVING
                self.hovered_handle = handle # Lock the handle being interacted with
                # Store original pixel rect for calculations during resize/move
                bbox_pixels = utils.normalized_to_pixel(self.annotations[self.selected_box_idx].bbox_norm, self.pixmap.width(), self.pixmap.height())
                self.resizing_origin_rect = QRect(QPoint(bbox_pixels[0], bbox_pixels[1]), QPoint(bbox_pixels[2], bbox_pixels[3]))

            elif box_idx != -1:
                 # Select the clicked box (but don't start moving yet)
                self.selected_box_idx = box_idx
                self.current_state = self.SELECTING # Or just update selection and stay IDLE?
                self.box_selected.emit(self.selected_box_idx)
                self.update()

            else:
                # Start drawing a new box
                self.selected_box_idx = -1 # Deselect any current box
                self.box_selected.emit(-1)
                self.current_state = self.DRAWING
                if self.rubber_band is None:
                    self.rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
                self.rubber_band.setGeometry(QRect(self.origin, QSize()))
                self.rubber_band.show()
                self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            handle, box_idx = self._check_handle_or_box_hover(event.pos())
            if box_idx != -1:
                self.selected_box_idx = box_idx # Select box on right click too
                self.box_selected.emit(self.selected_box_idx)
                self.update()
                self._show_context_menu(event.pos(), box_idx)


    def mouseMoveEvent(self, event):
        if self.pixmap is None: return

        # Update mouse position label in status bar (emit signal)
        img_coords = self.get_image_coords(event.pos())
        if img_coords:
            self.mouse_pos_changed.emit(img_coords) # Emit image coords

        current_widget_pos = event.pos()

        if self.current_state == self.DRAWING:
            if self.rubber_band:
                self.rubber_band.setGeometry(QRect(self.origin, current_widget_pos).normalized())
        elif self.current_state == self.MOVING:
            self._move_selected_box(current_widget_pos)
            self.update()
        elif self.current_state == self.RESIZING:
            self._resize_selected_box(current_widget_pos)
            self.update()
        else: # IDLE or SELECTING - update cursor based on hover
             handle, box_idx = self._check_handle_or_box_hover(current_widget_pos)
             self.hovered_box_idx = box_idx
             self.hovered_handle = handle if box_idx == self.selected_box_idx else self.HANDLE_NONE
             self._update_cursor()
             self.update() # To redraw hover highlights


    def mouseReleaseEvent(self, event):
        if self.pixmap is None: return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.current_state == self.DRAWING:
                if self.rubber_band:
                    rect_widget = self.rubber_band.geometry()
                    self.rubber_band.hide()

                    # Convert widget rect to image pixel rect
                    top_left_img = self.get_image_coords(rect_widget.topLeft())
                    bottom_right_img = self.get_image_coords(rect_widget.bottomRight())

                    if top_left_img and bottom_right_img and \
                       abs(top_left_img.x() - bottom_right_img.x()) > 5 and \
                       abs(top_left_img.y() - bottom_right_img.y()) > 5: # Min size check

                        pixel_rect = QRect(top_left_img, bottom_right_img).normalized()
                        # Emit signal for logic layer to handle creation
                        self.new_box_request.emit(pixel_rect)
                        # Logic layer will update annotations and call set_annotations

                self.current_state = self.IDLE

            elif self.current_state == self.MOVING or self.current_state == self.RESIZING:
                 # Finalize the changes - signal that annotations changed
                 self.annotations_changed.emit()
                 self.current_state = self.IDLE # Or SELECTING if desired
                 # Recalculate hover state after operation finishes
                 handle, box_idx = self._check_handle_or_box_hover(event.pos())
                 self.hovered_box_idx = box_idx
                 self.hovered_handle = handle if box_idx == self.selected_box_idx else self.HANDLE_NONE
                 self._update_cursor()


            elif self.current_state == self.SELECTING:
                 # Remain in selecting state or switch to IDLE? Assume IDLE for now.
                 self.current_state = self.IDLE


    def paintEvent(self, event):
        """Draws the image and annotations."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.pixmap:
            target_rect = self._get_scaled_pixmap_rect()
            painter.drawPixmap(target_rect, self.pixmap, self.pixmap.rect())

            img_w = self.pixmap.width()
            img_h = self.pixmap.height()

            # Draw bounding boxes
            for i, box in enumerate(self.annotations):
                pixels = utils.normalized_to_pixel(box.bbox_norm, img_w, img_h)
                if not pixels: continue
                x_min, y_min, x_max, y_max = pixels

                # Scale pixel coords to widget coords
                widget_x_min = target_rect.x() + x_min * self.scale_factor
                widget_y_min = target_rect.y() + y_min * self.scale_factor
                widget_x_max = target_rect.x() + x_max * self.scale_factor
                widget_y_max = target_rect.y() + y_max * self.scale_factor
                box_rect = QRect(QPoint(int(widget_x_min), int(widget_y_min)),
                                 QPoint(int(widget_x_max), int(widget_y_max)))

                # --- Styling ---
                is_selected = (i == self.selected_box_idx)
                is_hovered = (i == self.hovered_box_idx and self.current_state == self.IDLE)

                pen_width = 2 if is_selected else 1
                color = QColor("cyan") if is_selected else QColor("yellow")
                if is_hovered and not is_selected:
                    color = QColor("orange")

                pen = QPen(color, pen_width)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush) # No fill
                painter.drawRect(box_rect)

                # Draw class label
                if box.class_id >= 0 and box.class_id < len(self.class_names):
                    label = f"{self.class_names[box.class_id]}"
                    if box.confidence is not None:
                        label += f" ({box.confidence:.2f})"

                    text_color = color
                    bg_color = QColor(0, 0, 0, 180) # Semi-transparent black background

                    font_metrics = painter.fontMetrics()
                    text_width = font_metrics.horizontalAdvance(label)
                    text_height = font_metrics.height()

                    text_rect = QRect(box_rect.topLeft() - QPoint(0, text_height),
                                      QSize(text_width + 4, text_height))

                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(bg_color)
                    painter.drawRect(text_rect)

                    painter.setPen(text_color)
                    painter.drawText(text_rect.adjusted(2, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter, label)


                # Draw resize handles if selected
                if is_selected:
                    self._draw_handles(painter, box_rect)

        else:
            painter.setPen(QColor("grey"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Load an image")

        painter.end()

    # --- Helper Methods ---

    def _draw_handles(self, painter: QPainter, box_rect: QRect):
        """Draws resize handles around the given rectangle."""
        painter.setBrush(QColor("cyan"))
        painter.setPen(QColor("black"))
        handle_size = self.HANDLE_SIZE
        hs = handle_size // 2

        handles = {
            self.HANDLE_TOP_LEFT: box_rect.topLeft(),
            self.HANDLE_TOP_RIGHT: box_rect.topRight(),
            self.HANDLE_BOTTOM_LEFT: box_rect.bottomLeft(),
            self.HANDLE_BOTTOM_RIGHT: box_rect.bottomRight(),
            self.HANDLE_TOP: QPoint(box_rect.center().x(), box_rect.top()),
            self.HANDLE_BOTTOM: QPoint(box_rect.center().x(), box_rect.bottom()),
            self.HANDLE_LEFT: QPoint(box_rect.left(), box_rect.center().y()),
            self.HANDLE_RIGHT: QPoint(box_rect.right(), box_rect.center().y()),
        }

        for handle_code, pos in handles.items():
             handle_rect = QRect(pos.x() - hs, pos.y() - hs, handle_size, handle_size)
             # Highlight hovered handle
             current_pen = painter.pen()
             if handle_code == self.hovered_handle:
                 painter.setPen(QPen(QColor("white"), 2))
             painter.drawRect(handle_rect)
             painter.setPen(current_pen) # Restore pen

    def _check_handle_or_box_hover(self, widget_pos: QPoint) -> Tuple[int, int]:
        """Checks if mouse is over a resize handle or inside a box."""
        if self.pixmap is None: return self.HANDLE_NONE, -1

        target_rect = self._get_scaled_pixmap_rect()
        img_w = self.pixmap.width()
        img_h = self.pixmap.height()
        hs = self.HANDLE_SIZE // 2

        # Check handles first (only for the selected box)
        if self.selected_box_idx != -1:
            box = self.annotations[self.selected_box_idx]
            pixels = utils.normalized_to_pixel(box.bbox_norm, img_w, img_h)
            if pixels:
                x_min, y_min, x_max, y_max = pixels
                widget_x_min = target_rect.x() + x_min * self.scale_factor
                widget_y_min = target_rect.y() + y_min * self.scale_factor
                widget_x_max = target_rect.x() + x_max * self.scale_factor
                widget_y_max = target_rect.y() + y_max * self.scale_factor
                box_rect = QRect(QPoint(int(widget_x_min), int(widget_y_min)),
                                 QPoint(int(widget_x_max), int(widget_y_max)))

                handles = {
                    self.HANDLE_TOP_LEFT: box_rect.topLeft(),
                    self.HANDLE_TOP_RIGHT: box_rect.topRight(),
                    # ... (include all handles as in _draw_handles) ...
                    self.HANDLE_BOTTOM_LEFT: box_rect.bottomLeft(),
                    self.HANDLE_BOTTOM_RIGHT: box_rect.bottomRight(),
                    self.HANDLE_TOP: QPoint(box_rect.center().x(), box_rect.top()),
                    self.HANDLE_BOTTOM: QPoint(box_rect.center().x(), box_rect.bottom()),
                    self.HANDLE_LEFT: QPoint(box_rect.left(), box_rect.center().y()),
                    self.HANDLE_RIGHT: QPoint(box_rect.right(), box_rect.center().y()),
                }
                for handle_code, pos in handles.items():
                    handle_rect = QRect(pos.x() - hs, pos.y() - hs, self.HANDLE_SIZE, self.HANDLE_SIZE)
                    if handle_rect.contains(widget_pos):
                        return handle_code, self.selected_box_idx

                # Check if inside the selected box for MOVE handle
                if box_rect.contains(widget_pos):
                    return self.HANDLE_MOVE, self.selected_box_idx

        # Check if hovering over any box (iterate in reverse for Z-order)
        for i in range(len(self.annotations) - 1, -1, -1):
            box = self.annotations[i]
            pixels = utils.normalized_to_pixel(box.bbox_norm, img_w, img_h)
            if not pixels: continue
            x_min, y_min, x_max, y_max = pixels
            widget_x_min = target_rect.x() + x_min * self.scale_factor
            widget_y_min = target_rect.y() + y_min * self.scale_factor
            widget_x_max = target_rect.x() + x_max * self.scale_factor
            widget_y_max = target_rect.y() + y_max * self.scale_factor
            box_rect = QRect(QPoint(int(widget_x_min), int(widget_y_min)),
                             QPoint(int(widget_x_max), int(widget_y_max)))
            if box_rect.contains(widget_pos):
                 # Don't consider hover over selected box if a handle wasn't hit
                 if i != self.selected_box_idx:
                    return self.HANDLE_NONE, i
                 else:
                    # Hovering inside selected box, but not on handle = MOVE
                    return self.HANDLE_MOVE, i


        return self.HANDLE_NONE, -1 # No handle or box hovered

    def _update_cursor(self):
        """Sets the cursor shape based on hover state."""
        cursor = Qt.CursorShape.ArrowCursor # Default
        if self.hovered_handle != self.HANDLE_NONE:
            if self.hovered_handle in (self.HANDLE_TOP_LEFT, self.HANDLE_BOTTOM_RIGHT):
                cursor = Qt.CursorShape.SizeFDiagCursor
            elif self.hovered_handle in (self.HANDLE_TOP_RIGHT, self.HANDLE_BOTTOM_LEFT):
                cursor = Qt.CursorShape.SizeBDiagCursor
            elif self.hovered_handle in (self.HANDLE_TOP, self.HANDLE_BOTTOM):
                cursor = Qt.CursorShape.SizeVerCursor
            elif self.hovered_handle in (self.HANDLE_LEFT, self.HANDLE_RIGHT):
                cursor = Qt.CursorShape.SizeHorCursor
            elif self.hovered_handle == self.HANDLE_MOVE:
                cursor = Qt.CursorShape.SizeAllCursor
        elif self.hovered_box_idx != -1:
             # Hovering over a box (but not selected one's handles)
             cursor = Qt.CursorShape.PointingHandCursor
        elif self.current_state == self.DRAWING:
             cursor = Qt.CursorShape.CrossCursor

        self.setCursor(QCursor(cursor))

    def _move_selected_box(self, current_widget_pos: QPoint):
        """Updates selected box position during drag."""
        if self.selected_box_idx == -1 or self.pixmap is None: return

        delta = current_widget_pos - self.origin
        # Apply delta to the original pixel rect where move started
        new_top_left = self.resizing_origin_rect.topLeft() + delta / self.scale_factor
        new_rect = QRect(new_top_left.toPoint(), self.resizing_origin_rect.size())

        # Clamp to image boundaries
        img_w = self.pixmap.width()
        img_h = self.pixmap.height()
        new_rect.setX(max(0, new_rect.x()))
        new_rect.setY(max(0, new_rect.y()))
        new_rect.setRight(min(img_w - 1, new_rect.right()))
        new_rect.setBottom(min(img_h - 1, new_rect.bottom()))

        # Convert back to normalized and update
        bbox_norm = utils.pixel_to_normalized(
            (new_rect.left(), new_rect.top(), new_rect.right(), new_rect.bottom()),
            img_w, img_h
        )
        if bbox_norm:
            self.annotations[self.selected_box_idx].bbox_norm = bbox_norm
            # Optionally update pixel coords too
            # self.annotations[self.selected_box_idx].bbox_pixels = (new_rect.left(), new_rect.top(), new_rect.right(), new_rect.bottom())

    def _resize_selected_box(self, current_widget_pos: QPoint):
        """Updates selected box size during resize drag."""
        if self.selected_box_idx == -1 or self.pixmap is None or self.hovered_handle == self.HANDLE_NONE: return

        current_img_pos = self.get_image_coords(current_widget_pos)
        if not current_img_pos: return

        new_rect = QRect(self.resizing_origin_rect) # Start with original rect
        img_x = current_img_pos.x()
        img_y = current_img_pos.y()

        # Adjust rect based on the handle being dragged
        if self.hovered_handle & self.HANDLE_TOP: new_rect.setTop(img_y)
        if self.hovered_handle & self.HANDLE_BOTTOM: new_rect.setBottom(img_y)
        if self.hovered_handle & self.HANDLE_LEFT: new_rect.setLeft(img_x)
        if self.hovered_handle & self.HANDLE_RIGHT: new_rect.setRight(img_x)

        new_rect = new_rect.normalized() # Ensure width/height positive

        # Clamp to image boundaries and minimum size
        img_w = self.pixmap.width()
        img_h = self.pixmap.height()
        min_size = 5
        if new_rect.width() < min_size: new_rect.setWidth(min_size)
        if new_rect.height() < min_size: new_rect.setHeight(min_size)

        new_rect.setLeft(max(0, new_rect.left()))
        new_rect.setTop(max(0, new_rect.top()))
        new_rect.setRight(min(img_w - 1, new_rect.right()))
        new_rect.setBottom(min(img_h - 1, new_rect.bottom()))


        # Convert back to normalized and update
        bbox_norm = utils.pixel_to_normalized(
            (new_rect.left(), new_rect.top(), new_rect.right(), new_rect.bottom()),
            img_w, img_h
        )
        if bbox_norm:
            self.annotations[self.selected_box_idx].bbox_norm = bbox_norm


    def _show_context_menu(self, pos: QPoint, box_index: int):
        """Shows context menu for the selected bounding box."""
        context_menu = QMenu(self)

        # --- Assign Class Submenu ---
        assign_menu = context_menu.addMenu("Assign Class")
        if not self.class_names:
            no_classes_action = QAction("No classes defined", self)
            no_classes_action.setEnabled(False)
            assign_menu.addAction(no_classes_action)
        else:
            for class_id, class_name in enumerate(self.class_names):
                action = QAction(class_name, self)
                # Use lambda with default argument to capture current class_id
                action.triggered.connect(lambda checked=False, b_idx=box_index, c_id=class_id: self._assign_class_action(b_idx, c_id))
                assign_menu.addAction(action)

        context_menu.addSeparator()

        # --- Delete Action ---
        delete_action = QAction("Delete Box", self)
        delete_action.triggered.connect(lambda checked=False, b_idx=box_index: self.delete_box_request.emit(b_idx))
        context_menu.addAction(delete_action)

        context_menu.exec(self.mapToGlobal(pos))

    def _assign_class_action(self, box_index: int, class_id: int):
        """Handler for assign class menu action."""
        if 0 <= box_index < len(self.annotations):
            self.annotations[box_index].class_id = class_id
            self.annotations_changed.emit() # Signal the change
            self.update() # Redraw immediately