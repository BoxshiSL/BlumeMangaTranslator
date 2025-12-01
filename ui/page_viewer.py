"""Page viewer widgets with navigation panel."""
from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, cast

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRect, QRectF, Signal

from project.page_session import PageSession, TextBlock
from ui.tools import PageTool


class MaskTool(Enum):
    """Available tools for editing translation masks."""

    NONE = 0
    ADD = auto()
    ERASE = auto()


class PageCanvas(QtWidgets.QWidget):
    """Canvas that draws page pixmap and overlay rectangles."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._blocks: List[TextBlock] = []
        self._show_mask: bool = True
        self._scale_factor: float = 1.0
        self._selection_rect: Optional[QtCore.QRectF] = None
        self._highlighted_block_id: Optional[str] = None

    def set_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        self._pixmap = pixmap
        self._update_size()
        self.update()

    def set_blocks(self, blocks: List[TextBlock]) -> None:
        self._blocks = list(blocks)
        if self._highlighted_block_id and not any(b.id == self._highlighted_block_id for b in self._blocks):
            self._highlighted_block_id = None
        self.update()

    def clear_blocks(self) -> None:
        self._blocks = []
        self.update()

    def set_show_translation_mask(self, show: bool) -> None:
        self._show_mask = bool(show)
        self.update()

    def set_selection_rect(self, rect: Optional[QtCore.QRectF]) -> None:
        """Store the current selection rectangle in image coordinates."""
        self._selection_rect = QtCore.QRectF(rect) if rect is not None else None
        self.update()

    def set_highlighted_block(self, block_id: Optional[str]) -> None:
        """Highlight a specific block by id."""
        self._highlighted_block_id = block_id
        self.update()

    def set_scale_factor(self, scale: float) -> None:
        self._scale_factor = max(0.01, scale)
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        if self._pixmap is None:
            self.resize(0, 0)
            return
        w = int(self._pixmap.width() * self._scale_factor)
        h = int(self._pixmap.height() * self._scale_factor)
        self.resize(w, h)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        if self._pixmap is None:
            return

        painter = QtGui.QPainter(self)
        painter.save()
        painter.scale(self._scale_factor, self._scale_factor)
        painter.drawPixmap(0, 0, self._pixmap)

        if self._show_mask and self._blocks:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 80))
            for block in self._blocks:
                if getattr(block, "deleted", False):
                    continue
                if not block.enabled:
                    continue

                x1, y1, x2, y2 = block.bbox
                w = max(1, x2 - x1)
                h = max(1, y2 - y1)
                rect = QtCore.QRectF(x1, y1, w, h)
                painter.drawRect(rect)

        if self._highlighted_block_id and self._blocks:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            for block in self._blocks:
                if getattr(block, "deleted", False):
                    continue
                if block.id != self._highlighted_block_id:
                    continue
                x1, y1, x2, y2 = block.bbox
                w = max(1, x2 - x1)
                h = max(1, y2 - y1)
                rect = QtCore.QRectF(x1, y1, w, h)
                pen = QtGui.QPen(QtGui.QColor(0, 120, 215))
                pen.setWidthF(2.0)
                pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
                break

        if self._selection_rect is not None and not self._selection_rect.isEmpty():
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            pen = QtGui.QPen(QtGui.QColor(0, 120, 215))
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            pen.setWidthF(1.5 / max(0.01, self._scale_factor))
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(0, 120, 215, 60))
            painter.drawRect(self._selection_rect)

        painter.restore()
        painter.end()


class PageViewer(QtWidgets.QWidget):
    """Scrollable page viewer with overlay rendering and OCR trigger button."""

    selectionFinished = Signal(QRectF)
    maskAddRequested = Signal(QRectF)
    maskEraseRequested = Signal(QRectF)
    showMaskToggled = Signal(bool)
    zoomActionRequested = Signal(str)
    viewActivated = Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._fit_to_window: bool = True  # contain: fit inside viewport
        self._fit_width_mode: bool = False
        self._zoom_factor: float = 1.0
        self._blocks: List[TextBlock] = []
        self._show_translation_mask: bool = True
        self._page_session: Optional[PageSession] = None
        self.current_mask_tool: MaskTool = MaskTool.NONE
        self.current_tool: PageTool = PageTool.NONE
        self._selection_active: bool = False
        self._selection_origin_canvas: Optional[QtCore.QPoint] = None
        self._selection_start_viewport: Optional[QtCore.QPoint] = None
        self._rubber_band: Optional[QtWidgets.QRubberBand] = None
        self._pan_active: bool = False
        self._pan_start: Optional[QtCore.QPoint] = None
        self._pan_scroll_start: Optional[QtCore.QPoint] = None

        self._canvas = PageCanvas(self)
        self._scroll_area = QtWidgets.QScrollArea(self)
        self._scroll_area.setWidget(self._canvas)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        self._canvas.set_show_translation_mask(self._show_translation_mask)
        self._scroll_area.viewport().installEventFilter(self)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self._scroll_area.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._scroll_area)
        self.ocr_button = QtWidgets.QPushButton("OCR + Translate", self)
        self.ocr_button.clicked.connect(self._emit_ocr_request)
        layout.addWidget(self.ocr_button)
        self.setLayout(layout)
        self._canvas.installEventFilter(self)
        self._update_cursor()

    def _emit_ocr_request(self) -> None:
        candidates = [self.parent(), self.window()]
        target = next(
            (obj for obj in candidates if obj is not None and hasattr(obj, "_on_ocr_and_translate_page_triggered")),
            None,
        )
        if target is not None:
            try:
                target._on_ocr_and_translate_page_triggered()  # type: ignore[attr-defined]
            except Exception:
                pass

    def set_page(self, image_path: Path) -> None:
        if not image_path.is_file():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        pixmap = QtGui.QPixmap(str(image_path))
        if pixmap.isNull():
            raise ValueError(f"Failed to load image: {image_path}")
        self.set_pixmap(pixmap)

    def set_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
            self._update_view()
            return
        self._pixmap = pixmap
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._fit_width_mode = False
        self._update_view()

    def set_blocks(self, blocks: List[TextBlock]) -> None:
        self._blocks = list(blocks)
        self._canvas.set_blocks(self._blocks)

    def set_page_session(self, session: Optional[PageSession]) -> None:
        self._page_session = session
        self.update()

    def clear_blocks(self) -> None:
        self._blocks = []
        self._canvas.clear_blocks()

    def set_show_translation_mask(self, show: bool) -> None:
        self._show_translation_mask = bool(show)
        self._canvas.set_show_translation_mask(self._show_translation_mask)
        self.showMaskToggled.emit(self._show_translation_mask)

    # Backward compatible alias
    def set_show_overlays(self, show: bool) -> None:
        self.set_show_translation_mask(show)

    def set_highlighted_block(self, block_id: Optional[str]) -> None:
        """Highlight a specific block and repaint."""
        self._canvas.set_highlighted_block(block_id)

    def set_fit_to_window(self, enabled: bool) -> None:
        self._fit_to_window = bool(enabled)
        if enabled:
            self._fit_width_mode = False
        self._update_view()

    def zoom_in(self, step: float = 0.1) -> None:
        self._fit_to_window = False
        self._fit_width_mode = False
        self._zoom_factor = min(5.0, self._zoom_factor + abs(step))
        self._update_view()

    def zoom_out(self, step: float = 0.1) -> None:
        self._fit_to_window = False
        self._fit_width_mode = False
        self._zoom_factor = max(0.1, self._zoom_factor - abs(step))
        self._update_view()

    def reset_zoom(self) -> None:
        self._fit_to_window = False
        self._fit_width_mode = False
        self._zoom_factor = 1.0
        self._update_view()

    def zoom_fit_width(self) -> None:
        """Adjust zoom so that image fits the available width."""
        if self._pixmap is None:
            return
        viewport = self._scroll_area.viewport().size()
        if viewport.width() <= 0 or self._pixmap.width() == 0:
            return
        self._fit_to_window = False
        self._fit_width_mode = True
        self._zoom_factor = max(0.01, viewport.width() / float(self._pixmap.width()))
        self._update_view()

    def zoom_fit_window(self) -> None:
        """Adjust zoom so that image fits fully inside viewport."""
        if self._pixmap is None:
            return
        viewport = self._scroll_area.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return
        self._fit_to_window = True
        self._fit_width_mode = False
        sx = viewport.width() / float(self._pixmap.width())
        sy = viewport.height() / float(self._pixmap.height())
        self._zoom_factor = max(0.01, min(sx, sy))
        self._update_view()

    def set_zoom_factor(self, factor: float) -> None:
        """Externally force zoom to a specific factor (disables fit modes)."""
        self._fit_to_window = False
        self._fit_width_mode = False
        self._zoom_factor = max(0.1, float(factor))
        self._update_view()

    def current_zoom_factor(self) -> float:
        return float(self._zoom_factor)

    def set_current_tool(self, tool: PageTool) -> None:
        """Set current tool and update cursor/mask mode."""
        if self.current_tool == tool:
            return
        self.current_tool = tool
        if tool == PageTool.BRUSH:
            self.current_mask_tool = MaskTool.ADD
        elif tool == PageTool.ERASER:
            self.current_mask_tool = MaskTool.ERASE
        else:
            self.current_mask_tool = MaskTool.NONE
            self._clear_selection_preview()
        if tool != PageTool.HAND:
            self._pan_active = False
            self._pan_start = None
            self._pan_scroll_start = None
        self._update_cursor()

    def _widget_point_to_image_point(self, point: QtCore.QPoint) -> Optional[QtCore.QPointF]:
        """Map a point from canvas coordinates to image coordinates."""
        if self._pixmap is None or self._canvas.width() == 0 or self._canvas.height() == 0:
            return None

        img_w = float(self._pixmap.width())
        img_h = float(self._pixmap.height())
        scale_x = img_w / float(self._canvas.width())
        scale_y = img_h / float(self._canvas.height())

        x = max(0.0, min(point.x() * scale_x, img_w))
        y = max(0.0, min(point.y() * scale_y, img_h))
        return QtCore.QPointF(x, y)

    def _image_rect_from_canvas_points(
        self, start: QtCore.QPoint, end: QtCore.QPoint
    ) -> Optional[QtCore.QRectF]:
        """Convert a canvas-space rectangle into image coordinates."""
        rect = QtCore.QRect(start, end).normalized()
        return self._widget_rect_to_image_rect(rect)

    def _update_selection_preview(self, current_canvas_point: QtCore.QPoint) -> None:
        """Update rubber band overlay + image-space preview rect."""
        if self._selection_origin_canvas is None:
            return
        rect = QtCore.QRect(self._selection_origin_canvas, current_canvas_point).normalized()
        image_rect = self._widget_rect_to_image_rect(rect)
        self._canvas.set_selection_rect(image_rect)
        self._update_rubber_band(current_canvas_point)

    def _clear_selection_preview(self) -> None:
        self._selection_active = False
        self._selection_origin_canvas = None
        self._selection_start_viewport = None
        self._canvas.set_selection_rect(None)
        if self._rubber_band is not None:
            self._rubber_band.hide()

    def _update_rubber_band(self, current_canvas_point: QtCore.QPoint) -> None:
        """Update the on-screen rubber band rectangle anchored to the scroll viewport."""
        if self._selection_origin_canvas is None:
            return
        start_vp = self._selection_start_viewport
        if start_vp is None:
            start_vp = self._canvas.mapTo(self._scroll_area.viewport(), self._selection_origin_canvas)
            self._selection_start_viewport = start_vp
        current_vp = self._canvas.mapTo(self._scroll_area.viewport(), current_canvas_point)
        rect = QtCore.QRect(start_vp, current_vp).normalized()
        if self._rubber_band is None:
            self._rubber_band = QtWidgets.QRubberBand(
                QtWidgets.QRubberBand.Shape.Rectangle, self._scroll_area.viewport()
            )
        self._rubber_band.setGeometry(rect)
        self._rubber_band.show()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._fit_to_window or self._fit_width_mode:
            self._update_view()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)

    def canvas_widget(self) -> QtWidgets.QWidget:
        return self._canvas

    def map_image_bbox_to_canvas_rect(self, bbox: tuple[int, int, int, int]) -> QtCore.QRect:
        x1, y1, x2, y2 = bbox
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        scale = float(self._zoom_factor or 1.0)
        sx = int(x1 * scale)
        sy = int(y1 * scale)
        sw = max(1, int(w * scale))
        sh = max(1, int(h * scale))
        return QtCore.QRect(sx, sy, sw, sh)

    def _update_view(self) -> None:
        if self._pixmap is None:
            self._canvas.set_pixmap(None)
            return

        if self._fit_width_mode:
            viewport_size = self._scroll_area.viewport().size()
            if viewport_size.width() > 0:
                self._zoom_factor = max(0.01, viewport_size.width() / float(self._pixmap.width()))
        elif self._fit_to_window:
            viewport_size = self._scroll_area.viewport().size()
            if viewport_size.width() > 0 and viewport_size.height() > 0:
                sx = viewport_size.width() / self._pixmap.width()
                sy = viewport_size.height() / self._pixmap.height()
                self._zoom_factor = min(sx, sy)

        self._canvas.set_pixmap(self._pixmap)
        self._canvas.set_scale_factor(self._zoom_factor)

    def _widget_rect_to_image_rect(self, rect: QtCore.QRect) -> Optional[QtCore.QRectF]:
        """
        Map a rectangle in canvas coordinates to image coordinates.
        """
        if self._pixmap is None or self._canvas.width() == 0 or self._canvas.height() == 0:
            return None

        img_w = float(self._pixmap.width())
        img_h = float(self._pixmap.height())
        if img_w <= 0 or img_h <= 0:
            return None

        scale_x = img_w / float(self._canvas.width())
        scale_y = img_h / float(self._canvas.height())

        x = rect.x() * scale_x
        y = rect.y() * scale_y
        w = rect.width() * scale_x
        h = rect.height() * scale_y

        x = max(0.0, min(x, img_w))
        y = max(0.0, min(y, img_h))
        if x + w > img_w:
            w = img_w - x
        if y + h > img_h:
            h = img_h - y

        return QtCore.QRectF(x, y, w, h)

    def _image_rect_to_widget_rect(self, bbox: tuple[int, int, int, int]) -> Optional[QtCore.QRect]:
        """
        Map an image-space bbox (x1, y1, x2, y2) to widget/canvas coordinates.
        """
        if self._pixmap is None:
            return None

        img_w = float(self._pixmap.width())
        img_h = float(self._pixmap.height())
        if img_w <= 0 or img_h <= 0:
            return None

        x1, y1, x2, y2 = bbox
        w_img = max(1.0, float(x2 - x1))
        h_img = max(1.0, float(y2 - y1))

        scale_x = float(self._canvas.width()) / img_w
        scale_y = float(self._canvas.height()) / img_h

        wx = int(x1 * scale_x)
        wy = int(y1 * scale_y)
        ww = int(w_img * scale_x)
        wh = int(h_img * scale_y)

        return QtCore.QRect(wx, wy, ww, wh)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # type: ignore[override]
        if obj is self._canvas:
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
                self.viewActivated.emit()
            if self.current_tool == PageTool.HAND:
                if self._handle_hand_event(event):
                    return True
            elif self.current_tool in (PageTool.BRUSH, PageTool.ERASER):
                if self._handle_mask_event(event):
                    return True
        if obj in (self._canvas, self._scroll_area.viewport()) and event.type() == QtCore.QEvent.Type.Wheel:
            we = cast(QtGui.QWheelEvent, event)
            if we.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                if we.angleDelta().y() > 0:
                    self.zoomActionRequested.emit("in")
                else:
                    self.zoomActionRequested.emit("out")
                return True
        return super().eventFilter(obj, event)

    def _handle_mask_event(self, event: QtCore.QEvent) -> bool:
        if self.current_mask_tool is MaskTool.NONE:
            return False
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            me = cast(QtGui.QMouseEvent, event)
            if me.button() == QtCore.Qt.MouseButton.LeftButton:
                canvas_point = me.position().toPoint()
                self._selection_active = True
                self._selection_origin_canvas = canvas_point
                self._selection_start_viewport = self._canvas.mapTo(self._scroll_area.viewport(), canvas_point)
                self._update_selection_preview(canvas_point)
            return True
        if event.type() == QtCore.QEvent.Type.MouseMove:
            if self._selection_active and self._selection_origin_canvas is not None:
                me = cast(QtGui.QMouseEvent, event)
                self._update_selection_preview(me.position().toPoint())
            return True
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            me = cast(QtGui.QMouseEvent, event)
            if self._selection_active and me.button() == QtCore.Qt.MouseButton.LeftButton:
                canvas_point = me.position().toPoint()
                image_rect = None
                if self._selection_origin_canvas is not None:
                    image_rect = self._image_rect_from_canvas_points(self._selection_origin_canvas, canvas_point)
                self._clear_selection_preview()
                if image_rect is not None and not image_rect.isEmpty():
                    self.selectionFinished.emit(image_rect)
                    if self.current_mask_tool == MaskTool.ADD:
                        self.maskAddRequested.emit(image_rect)
                    elif self.current_mask_tool == MaskTool.ERASE:
                        self.maskEraseRequested.emit(image_rect)
            return True
        return False

    def _handle_hand_event(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            me = cast(QtGui.QMouseEvent, event)
            if me.button() == QtCore.Qt.MouseButton.LeftButton:
                self._pan_active = True
                self._pan_start = me.position().toPoint()
                self._pan_scroll_start = QtCore.QPoint(
                    self._scroll_area.horizontalScrollBar().value(),
                    self._scroll_area.verticalScrollBar().value(),
                )
                self._set_closed_hand_cursor()
                return True
        if event.type() == QtCore.QEvent.Type.MouseMove and self._pan_active:
            me = cast(QtGui.QMouseEvent, event)
            if self._pan_start is None or self._pan_scroll_start is None:
                return True
            delta = me.position().toPoint() - self._pan_start
            self._scroll_area.horizontalScrollBar().setValue(self._pan_scroll_start.x() - delta.x())
            self._scroll_area.verticalScrollBar().setValue(self._pan_scroll_start.y() - delta.y())
            return True
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease and self._pan_active:
            me = cast(QtGui.QMouseEvent, event)
            if me.button() == QtCore.Qt.MouseButton.LeftButton:
                self._pan_active = False
                self._pan_start = None
                self._pan_scroll_start = None
                if self.current_tool == PageTool.HAND:
                    self._update_cursor()
                return True
        return False

    def _update_cursor(self) -> None:
        cursor = QtCore.Qt.CursorShape.ArrowCursor
        if self.current_tool in (PageTool.BRUSH, PageTool.ERASER):
            cursor = QtCore.Qt.CursorShape.CrossCursor
        elif self.current_tool == PageTool.EYEDROPPER:
            cursor = QtCore.Qt.CursorShape.PointingHandCursor
        elif self.current_tool == PageTool.HAND:
            cursor = QtCore.Qt.CursorShape.OpenHandCursor

        for widget in (self._canvas, self._scroll_area.viewport()):
            widget.setCursor(QtGui.QCursor(cursor))

    def _set_closed_hand_cursor(self) -> None:
        for widget in (self._canvas, self._scroll_area.viewport()):
            widget.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))


class PageViewerPanel(QtWidgets.QWidget):
    """Wrapper with PageViewer on top and navigation bar below."""

    viewActivated = Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.viewer = PageViewer(self)
        self.viewer.viewActivated.connect(self.viewActivated)
        self.btn_first = QtWidgets.QPushButton("<<", self)
        self.btn_prev = QtWidgets.QPushButton("<", self)
        self.lbl_page_info = QtWidgets.QLabel("Page 0 / 0", self)
        self.btn_next = QtWidgets.QPushButton(">", self)
        self.btn_last = QtWidgets.QPushButton(">>", self)
        self.progress_label = QtWidgets.QLabel("", self)
        self.progress_label.setStyleSheet("color: #666;")
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setMaximumWidth(180)

        nav_layout = QtWidgets.QHBoxLayout()
        nav_layout.setContentsMargins(4, 4, 4, 4)
        nav_layout.setSpacing(6)
        nav_layout.addWidget(self.btn_first)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.lbl_page_info)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(self.btn_last)
        nav_layout.addSpacing(8)
        nav_layout.addWidget(self.progress_label)
        nav_layout.addWidget(self.progress_bar, 1)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)
        main_layout.addWidget(self.viewer, 1)
        main_layout.addLayout(nav_layout)

    # Proxy helpers
    def set_page(self, image_path: Path) -> None:
        self.viewer.set_page(image_path)

    def set_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        self.viewer.set_pixmap(pixmap)

    def set_blocks(self, blocks: List[TextBlock]) -> None:
        self.viewer.set_blocks(blocks)

    def clear_blocks(self) -> None:
        self.viewer.clear_blocks()

    def set_show_translation_mask(self, show: bool) -> None:
        self.viewer.set_show_translation_mask(show)

    def set_show_overlays(self, show: bool) -> None:
        self.viewer.set_show_overlays(show)

    def set_highlighted_block(self, block_id: Optional[str]) -> None:
        self.viewer.set_highlighted_block(block_id)

    def set_current_tool(self, tool: PageTool) -> None:
        self.viewer.set_current_tool(tool)

    def canvas_widget(self) -> QtWidgets.QWidget:
        return self.viewer.canvas_widget()

    def map_image_bbox_to_canvas_rect(self, bbox: tuple[int, int, int, int]) -> QtCore.QRect:
        return self.viewer.map_image_bbox_to_canvas_rect(bbox)

    def set_page_label(self, text: str) -> None:
        self.lbl_page_info.setText(text)

    def set_nav_enabled(self, enable_first: bool, enable_prev: bool, enable_next: bool, enable_last: bool) -> None:
        self.btn_first.setEnabled(enable_first)
        self.btn_prev.setEnabled(enable_prev)
        self.btn_next.setEnabled(enable_next)
        self.btn_last.setEnabled(enable_last)

    def set_progress(self, message: str, busy: bool) -> None:
        """Update bottom progress indicator."""
        self.progress_label.setText(message)
        self.progress_bar.setVisible(busy)
        self.progress_bar.setRange(0, 0 if busy else 1)
