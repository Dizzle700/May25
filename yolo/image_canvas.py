"""
ImageCanvas module - Custom widget for displaying images and managing interactions
"""

from PyQt6.QtWidgets import QWidget, QSizePolicy, QApplication
from PyQt6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QFontMetrics, QImage, QCursor
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer
import cv2
import numpy as np
from typing import List, Tuple, Optional

# Use local imports due to flat structure
from utils import cxcywh_normalized_to_xyxy, calculate_contrast_color, cv2_to_qimage, clamp

class ImageCanvas(QWidget):
    """
    Custom widget for displaying images, bounding boxes, and handling interactions.
    Supports zooming, panning, box selection, and drawing new boxes.
    """
    boxSelected = pyqtSignal(int)  # Signal emitted when a box is selected (sends box index, -1 for none)
    newBoxDrawn = pyqtSignal(QRect) # Signal emitted when a new box is drawn (pixel coords in image)
    requestContextMenu = pyqtSignal(QPoint) # Signal for context menu requests

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Image Display
        self.pixmap: Optional[QPixmap] = None
        self.image_cv2_bgr: Optional[np.ndarray] = None # Store original BGR for saving/processing
        self.image_path: Optional[str] = None
        self.aspect_ratio: float = 1.0
        self.scale_factor: float = 1.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0
        self.display_rect: QRect = QRect() # Cache the display rect

        # Annotations
        self.annotations: List[dict] = []
        self.selected_box_idx: int = -1
        self.class_names: List[str] = []
        self.default_class_colors: List[QColor] = [
            QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255), QColor(255, 255, 0),
            QColor(255, 0, 255), QColor(0, 255, 255), QColor(255, 128, 0), QColor(128, 0, 255),
            QColor(0, 128, 128), QColor(128, 128, 0),
        ]
        self.unassigned_color = QColor(128, 128, 128, 180) # Gray for unassigned boxes

        # Appearance
        self.box_line_width: int = 2
        self.label_font: QFont = QFont("Arial", 10)
        self.font_metrics: QFontMetrics = QFontMetrics(self.label_font)
        self.background_color: QColor = QColor(64, 64, 64)

        # Interaction State
        self._panning: bool = False
        self._drawing_box: bool = False
        self._is_drawing_enabled: bool = False
        self._start_drag_pos: Optional[QPoint] = None
        self._current_drag_pos: Optional[QPoint] = None
        self._last_mouse_pos: Optional[QPoint] = None

        # Widget Settings
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True) # Needed for cursor changes and hover effects (if any)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # To receive key events

        # Timer for delayed updates (e.g., after resize)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self.update)
        self._update_timer.setInterval(50) # ms delay


    def set_image(self, image_path: Optional[str] = None, cv2_image: Optional[np.ndarray] = None) -> bool:
        """Load and display an image from path or CV2 BGR image object."""
        self.image_path = image_path
        self.selected_box_idx = -1
        self._reset_interactions()

        temp_image_cv2 = None
        if cv2_image is not None:
            temp_image_cv2 = cv2_image
        elif image_path:
            temp_image_cv2 = cv2.imread(image_path)
            if temp_image_cv2 is None:
                print(f"Failed to load image: {image_path}")
                self.pixmap = None
                self.image_cv2_bgr = None
                self.update()
                return False
        else:
            self.pixmap = None
            self.image_cv2_bgr = None
            self.update()
            return False

        self.image_cv2_bgr = temp_image_cv2 # Store BGR
        h, w = self.image_cv2_bgr.shape[:2]

        # Convert BGR to RGB for QImage
        rgb_image = cv2.cvtColor(self.image_cv2_bgr, cv2.COLOR_BGR2RGB)
        qimg = cv2_to_qimage(rgb_image)

        if qimg is None:
            print("Failed to convert CV2 image to QImage.")
            self.pixmap = None
            self.image_cv2_bgr = None
            self.update()
            return False

        self.pixmap = QPixmap.fromImage(qimg)
        self.aspect_ratio = w / h if h > 0 else 1.0
        self.fit_to_view() # Reset zoom/pan and update
        return True

    def set_annotations(self, annotations: List[dict]):
        """Set annotations. Expected: [{'class_id': int, 'bbox': [cx, cy, w, h]}, ...]"""
        self.annotations = annotations
        self.update()

    def set_class_names(self, class_names: List[str]):
        """Set the list of class names."""
        self.class_names = class_names
        self.update()

    def select_box(self, index: int):
        """Programmatically select a bounding box."""
        if 0 <= index < len(self.annotations):
            if self.selected_box_idx != index:
                self.selected_box_idx = index
                self.boxSelected.emit(index)
                self.update()
        elif self.selected_box_idx != -1:
             self.selected_box_idx = -1
             self.boxSelected.emit(-1)
             self.update()

    def set_drawing_enabled(self, enabled: bool):
        """Enable or disable drawing mode."""
        self._is_drawing_enabled = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.select_box(-1) # Deselect any box when enabling drawing
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._reset_drawing() # Ensure drawing state is cleared if disabled mid-draw

    # --- Zoom and Pan ---

    def fit_to_view(self):
        """Scale image to fit the widget size."""
        if self.pixmap is None: return
        self.scale_factor = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._calculate_display_rect() # Update display rect immediately
        self.update()

    def zoom(self, factor: float, anchor_point: Optional[QPoint] = None):
        """Zoom in/out centered around an anchor point (widget coordinates)."""
        if self.pixmap is None: return

        if anchor_point is None:
             # Default to center of the widget
            anchor_point = QPoint(self.width() // 2, self.height() // 2)

        # Calculate image coordinates corresponding to the anchor point before zoom
        img_x, img_y = self._display_to_image_coords(anchor_point.x(), anchor_point.y())

        # Apply zoom factor
        new_scale_factor = self.scale_factor * factor
        # Add constraints if needed (e.g., max/min zoom)
        # new_scale_factor = max(0.1, min(new_scale_factor, 10.0))

        # Update scale factor
        self.scale_factor = new_scale_factor

        # Recalculate display rectangle based on new scale
        self._calculate_display_rect()

        # Calculate display coordinates corresponding to the same image point *after* zoom
        new_disp_x, new_disp_y = self._image_to_display_coords(img_x, img_y)

        # Adjust offset to keep the anchor point stationary
        self.offset_x += anchor_point.x() - new_disp_x
        self.offset_y += anchor_point.y() - new_disp_y

        # Recalculate display rect with new offset and clamp
        self._calculate_display_rect()
        self.update()


    def zoom_in(self, anchor_point: Optional[QPoint] = None):
        self.zoom(1.2, anchor_point)

    def zoom_out(self, anchor_point: Optional[QPoint] = None):
        self.zoom(1 / 1.2, anchor_point)

    def pan(self, delta_x: int, delta_y: int):
        """Pan the image by a delta."""
        if self.pixmap is None: return
        self.offset_x += delta_x
        self.offset_y += delta_y
        self._calculate_display_rect() # Update display rect immediately
        self.update()

    # --- Painting ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)

        if self.pixmap is None or self.image_cv2_bgr is None:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Image Loaded")
            return

        # Calculate display rect if needed (e.g., first paint or resize)
        if self.display_rect.isNull() or self.display_rect.size() != self._get_target_display_size():
            self._calculate_display_rect()

        # Draw the image
        painter.drawPixmap(self.display_rect, self.pixmap, self.pixmap.rect())

        # Draw annotations
        img_h, img_w = self.image_cv2_bgr.shape[:2]
        for i, annotation in enumerate(self.annotations):
            bbox_norm = annotation.get('bbox', [0, 0, 0, 0])
            class_id = annotation.get('class_id', -1) # Default to -1 if missing

            x1, y1, x2, y2 = cxcywh_normalized_to_xyxy(bbox_norm, img_w, img_h)
            disp_x1, disp_y1 = self._image_to_display_coords(x1, y1)
            disp_x2, disp_y2 = self._image_to_display_coords(x2, y2)
            box_rect = QRect(disp_x1, disp_y1, disp_x2 - disp_x1, disp_y2 - disp_y1)

            # Determine color and style
            is_selected = (i == self.selected_box_idx)
            is_unassigned = (class_id < 0 or class_id >= len(self.class_names))

            if is_unassigned:
                box_color = self.unassigned_color
                label_text = "Unassigned"
                pen_width = self.box_line_width
                pen_style = Qt.PenStyle.DotLine
            else:
                box_color = self._get_color_for_class(class_id)
                label_text = self.class_names[class_id]
                pen_width = self.box_line_width * 2 if is_selected else self.box_line_width
                pen_style = Qt.PenStyle.DashLine if is_selected else Qt.PenStyle.SolidLine

            # Add confidence if available
            confidence = annotation.get('confidence')
            if confidence is not None:
                 label_text += f" ({confidence:.2f})"

            # Draw the box
            pen = QPen(box_color, pen_width)
            pen.setStyle(pen_style)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush) # No fill
            painter.drawRect(box_rect)

            # Draw label
            if label_text:
                label_width = self.font_metrics.horizontalAdvance(label_text) + 10
                label_height = self.font_metrics.height() + 4
                label_x = box_rect.left()
                # Position above box if possible, else inside
                label_y = box_rect.top() - label_height if box_rect.top() >= label_height else box_rect.top()

                # Draw label background
                painter.fillRect(label_x, label_y, label_width, label_height, box_color)

                # Draw label text with contrasting color
                text_color = calculate_contrast_color(box_color)
                painter.setPen(text_color)
                painter.setFont(self.label_font)
                painter.drawText(
                    label_x + 5,
                    label_y + self.font_metrics.ascent() + 2, # Adjusted for better vertical centering
                    label_text
                )

        # Draw the temporary box being drawn by the user
        if self._drawing_box and self._start_drag_pos and self._current_drag_pos:
            draw_rect = QRect(self._start_drag_pos, self._current_drag_pos).normalized()
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.drawRect(draw_rect)

        painter.end()

    # --- Mouse Events ---

    def mousePressEvent(self, event):
        pos = event.pos()
        self._last_mouse_pos = pos

        if self.pixmap is None: return

        # Right Button: Context Menu
        if event.button() == Qt.MouseButton.RightButton:
             self.requestContextMenu.emit(pos) # TODO: Implement context menu logic
             return # Consume event

        # Panning: Middle Button or Ctrl + Left Button
        if event.button() == Qt.MouseButton.MiddleButton or \
           (event.button() == Qt.MouseButton.LeftButton and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)):
            if self.display_rect.contains(pos):
                self._panning = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

        # Drawing: Left Button when drawing enabled
        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_enabled:
            if self.display_rect.contains(pos):
                 # Start drawing only if inside the displayed image area
                self._drawing_box = True
                self._start_drag_pos = pos
                self._current_drag_pos = pos
                self.select_box(-1) # Deselect any selected box
                self.update()
                return

        # Selection: Left Button when drawing NOT enabled
        if event.button() == Qt.MouseButton.LeftButton and not self._is_drawing_enabled:
            clicked_box_idx = self._get_box_at(pos)
            if clicked_box_idx != self.selected_box_idx:
                self.select_box(clicked_box_idx) # Will trigger update and emit signal
            # If clicking outside any box, deselect
            elif clicked_box_idx == -1 and self.selected_box_idx != -1:
                 self.select_box(-1)
            return

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self._last_mouse_pos is None: # Should not happen if pressed first, but safety check
            self._last_mouse_pos = pos
            return

        delta = pos - self._last_mouse_pos
        self._last_mouse_pos = pos

        # Handle Panning
        if self._panning:
            self.pan(delta.x(), delta.y())
            return

        # Handle Drawing
        if self._drawing_box:
            self._current_drag_pos = pos
            self.update()
            return

        # Update cursor based on mode and position
        if self._is_drawing_enabled:
            if self.display_rect.contains(pos):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.display_rect.contains(pos):
            # Change cursor if hovering over a box (optional)
            hover_idx = self._get_box_at(pos)
            if hover_idx != -1:
                 self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                 self.setCursor(Qt.CursorShape.ArrowCursor) # Or OpenHandCursor if panning is possible
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)


    def mouseReleaseEvent(self, event):
        pos = event.pos()

        # End Panning
        if event.button() == Qt.MouseButton.MiddleButton or \
           (event.button() == Qt.MouseButton.LeftButton and self._panning): # Handle Ctrl release
            if self._panning:
                self._panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor) # Reset cursor appropriately
                self.mouseMoveEvent(event) # Trigger cursor update based on final position
                return

        # End Drawing
        if event.button() == Qt.MouseButton.LeftButton and self._drawing_box:
            if self._start_drag_pos is not None and self._current_drag_pos is not None:
                # Convert display rectangle to image rectangle
                start_img_x, start_img_y = self._display_to_image_coords(self._start_drag_pos.x(), self._start_drag_pos.y())
                end_img_x, end_img_y = self._display_to_image_coords(self._current_drag_pos.x(), self._current_drag_pos.y())

                # Create normalized QRect in image pixel coordinates
                img_rect = QRect(QPoint(start_img_x, start_img_y), QPoint(end_img_x, end_img_y)).normalized()

                # Only emit if the box has a valid size
                if img_rect.width() > 1 and img_rect.height() > 1:
                    self.newBoxDrawn.emit(img_rect)

            self._reset_drawing()
            self.update()
            # Keep drawing mode active, cursor handled by mouseMoveEvent
            return

    def wheelEvent(self, event):
        """Handle mouse wheel zooming."""
        if self.pixmap is None: return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier: # Only zoom when Ctrl is pressed
             angle = event.angleDelta().y()
             if angle > 0:
                 self.zoom_in(event.position().toPoint())
             elif angle < 0:
                 self.zoom_out(event.position().toPoint())
             event.accept() # Indicate event was handled

    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)
        # Use a timer to avoid rapid updates during resize drag
        self._update_timer.start()
        # self._calculate_display_rect() # Calculate immediately if timer is not preferred
        # self.update()

    def keyPressEvent(self, event):
        """Handle key presses (e.g., for deleting boxes)."""
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            if self.selected_box_idx != -1:
                # TODO: Emit a signal to AppLogic to handle the deletion
                print(f"Request delete box index: {self.selected_box_idx}") # Placeholder
                # self.deleteSelectedBox.emit(self.selected_box_idx) # Need signal
                pass
            else:
                event.ignore()
        else:
            event.ignore() # Pass other keys up

    # --- Internal Helper Methods ---

    def _reset_interactions(self):
        """Reset flags related to mouse interactions."""
        self._panning = False
        self._drawing_box = False
        self._start_drag_pos = None
        self._current_drag_pos = None
        self._last_mouse_pos = None
        if not self._is_drawing_enabled:
             self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
             self.setCursor(Qt.CursorShape.CrossCursor)

    def _reset_drawing(self):
        """Reset only the drawing state variables."""
        self._drawing_box = False
        self._start_drag_pos = None
        self._current_drag_pos = None

    def _get_target_display_size(self) -> Tuple[int, int]:
        """Calculate the target size of the pixmap display area based on scale and aspect ratio."""
        if self.pixmap is None: return (0, 0)

        widget_w = self.width()
        widget_h = self.height()
        pix_w = self.pixmap.width()
        pix_h = self.pixmap.height()

        if pix_w == 0 or pix_h == 0: return (0, 0)

        # Start with widget size as the container
        container_w, container_h = widget_w, widget_h

        # Calculate potential scaled size based on width
        scaled_w = container_w * self.scale_factor
        scaled_h = scaled_w / self.aspect_ratio

        # If too tall, calculate based on height instead
        if scaled_h > container_h * self.scale_factor:
            scaled_h = container_h * self.scale_factor
            scaled_w = scaled_h * self.aspect_ratio

        return int(scaled_w), int(scaled_h)


    def _calculate_display_rect(self):
        """Calculate and cache the display rectangle, applying offsets and clamping."""
        if self.pixmap is None:
            self.display_rect = QRect()
            return

        widget_w = self.width()
        widget_h = self.height()
        scaled_w, scaled_h = self._get_target_display_size()

        if scaled_w <= 0 or scaled_h <= 0:
            self.display_rect = QRect()
            return

        # Calculate initial position (centered)
        base_x = (widget_w - scaled_w) / 2
        base_y = (widget_h - scaled_h) / 2

        # Apply pan offset
        current_x = base_x + self.offset_x
        current_y = base_y + self.offset_y

        # --- Clamping ---
        # Prevent panning image completely out of view
        # Max offset: image edge aligns with widget edge
        max_offset_x = widget_w - base_x - 1 # Max positive offset (image left edge at widget right edge - 1px)
        min_offset_x = -base_x - scaled_w + 1 # Min negative offset (image right edge at widget left edge + 1px)
        max_offset_y = widget_h - base_y - 1
        min_offset_y = -base_y - scaled_h + 1

        # If image is smaller than widget, don't allow panning beyond center alignment
        if scaled_w < widget_w:
            max_offset_x = (widget_w - scaled_w) / 2
            min_offset_x = (widget_w - scaled_w) / 2
        if scaled_h < widget_h:
            max_offset_y = (widget_h - scaled_h) / 2
            min_offset_y = (widget_h - scaled_h) / 2

        # Clamp the offsets
        self.offset_x = clamp(self.offset_x, min_offset_x, max_offset_x)
        self.offset_y = clamp(self.offset_y, min_offset_y, max_offset_y)

        # Recalculate position with clamped offsets
        final_x = base_x + self.offset_x
        final_y = base_y + self.offset_y

        self.display_rect = QRect(int(final_x), int(final_y), int(scaled_w), int(scaled_h))


    def _image_to_display_coords(self, img_x: float, img_y: float) -> Tuple[int, int]:
        """Convert image pixel coordinates to display widget coordinates."""
        if self.image_cv2_bgr is None or self.display_rect.isNull():
            return (0, 0)

        img_h, img_w = self.image_cv2_bgr.shape[:2]
        if img_w == 0 or img_h == 0: return (0, 0)

        norm_x = img_x / img_w
        norm_y = img_y / img_h

        disp_x = self.display_rect.x() + norm_x * self.display_rect.width()
        disp_y = self.display_rect.y() + norm_y * self.display_rect.height()

        return int(disp_x), int(disp_y)

    def _display_to_image_coords(self, disp_x: int, disp_y: int) -> Tuple[int, int]:
        """Convert display widget coordinates to image pixel coordinates."""
        if self.image_cv2_bgr is None or self.display_rect.isNull() or \
           self.display_rect.width() == 0 or self.display_rect.height() == 0:
            return (0, 0)

        img_h, img_w = self.image_cv2_bgr.shape[:2]

        # Normalize within the display rectangle
        norm_x = (disp_x - self.display_rect.x()) / self.display_rect.width()
        norm_y = (disp_y - self.display_rect.y()) / self.display_rect.height()

        # Clamp normalized coordinates to [0, 1] to avoid coords outside image
        norm_x = clamp(norm_x, 0.0, 1.0)
        norm_y = clamp(norm_y, 0.0, 1.0)

        img_x = norm_x * img_w
        img_y = norm_y * img_h

        return int(img_x), int(img_y)

    def _get_box_at(self, pos: QPoint) -> int:
        """Find the index of the bounding box at the given display coordinates."""
        if self.image_cv2_bgr is None or not self.annotations:
            return -1

        img_h, img_w = self.image_cv2_bgr.shape[:2]

        # Iterate in reverse order so topmost boxes are checked first
        for i in range(len(self.annotations) - 1, -1, -1):
            annotation = self.annotations[i]
            bbox_norm = annotation.get('bbox', [0, 0, 0, 0])

            x1, y1, x2, y2 = cxcywh_normalized_to_xyxy(bbox_norm, img_w, img_h)
            disp_x1, disp_y1 = self._image_to_display_coords(x1, y1)
            disp_x2, disp_y2 = self._image_to_display_coords(x2, y2)
            box_rect = QRect(disp_x1, disp_y1, disp_x2 - disp_x1, disp_y2 - disp_y1).normalized()

            # Add a small margin for easier clicking (optional)
            # box_rect.adjust(-2, -2, 2, 2)

            if box_rect.contains(pos):
                return i
        return -1

    def _get_color_for_class(self, class_id: int) -> QColor:
        """Get a color for a class ID."""
        if 0 <= class_id < len(self.default_class_colors):
            return self.default_class_colors[class_id]
        else:
            # Generate predictable color for other IDs
            h = (class_id * 37 + 50) % 360
            s = ((class_id * 61 + 150) % 106) + 150 # Saturation 150-255
            v = ((class_id * 41 + 200) % 56) + 200   # Value 200-255
            return QColor.fromHsv(h, s, v)