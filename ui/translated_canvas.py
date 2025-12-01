"""Translated page canvas that renders masks and translated text on top of a page image."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, cast

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QBrush, QFont, QImage, QPainter, QPen, QTextOption

from config import app_config
from project.page_layout import group_blocks_into_bubbles
from project.page_session import BubbleStyle, PageSession, TextBlock
from ui.tools import ActiveLayer, PageTool
from ui.text_layout import ResolvedBubbleStyle, apply_style_and_layout_text_item, resolve_bubble_style


@dataclass
class BlockGraphics:
    bubble_id: str
    text_block_ids: list[str]
    bbox: QtCore.QRectF
    block_type: str
    mask_item: Optional[QtWidgets.QGraphicsRectItem]
    text_item: Optional[QtWidgets.QGraphicsTextItem]
    enabled: bool = True


class TranslatedPageCanvas(QtWidgets.QWidget):
    """Graphics-based canvas to display translated page masks and text."""

    blockAreaSelected = QtCore.Signal(QtCore.QRectF)
    paintLayerChanged = QtCore.Signal()
    viewActivated = QtCore.Signal()
    selectedBubbleChanged = QtCore.Signal(object)
    blockClicked = QtCore.Signal(str)
    zoomChanged = QtCore.Signal(float)

    BACKGROUND_Z = 0
    MASK_Z = 10
    PAINT_Z = 20
    TEXT_Z = 30
    HIGHLIGHT_Z = 40

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._view = QtWidgets.QGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        self._view.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)

        self.background_item: Optional[QtWidgets.QGraphicsPixmapItem] = None
        self.mask_items: Dict[str, QtWidgets.QGraphicsRectItem] = {}
        self.text_items: Dict[str, QtWidgets.QGraphicsTextItem] = {}
        self.paint_layer: Optional[QImage] = None
        self.paint_item: Optional[QtWidgets.QGraphicsPixmapItem] = None
        self._blocks: Dict[str, BlockGraphics] = {}
        self._bubble_by_block_id: Dict[str, BlockGraphics] = {}
        self._current_pixmap: Optional[QtGui.QPixmap] = None
        self._page_image: Optional[QImage] = None
        self._session: Optional[PageSession] = None
        self._show_sfx: bool = True

        self.layer_visible_background: bool = True
        self.layer_visible_mask: bool = True
        self.layer_visible_paint: bool = True
        self.layer_visible_text: bool = True
        self.active_layer: ActiveLayer = ActiveLayer.TEXT

        self.current_tool: PageTool = PageTool.NONE
        self._fit_width_mode: bool = False
        self._fit_window_mode: bool = True
        self._zoom_factor: float = 1.0

        self._brush_color: QColor = QColor(0, 0, 0)
        self._brush_width: int = 4
        self._is_drawing: bool = False
        self._last_draw_pos: Optional[QPointF] = None
        self._hand_dragging: bool = False

        self._add_block_mode: bool = False
        self._selection_origin: Optional[QPointF] = None
        self._selection_rect_item: Optional[QtWidgets.QGraphicsRectItem] = None

        self.selected_bubble_id: Optional[str] = None
        self._selection_highlight: Optional[QtWidgets.QGraphicsRectItem] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)
        self.setLayout(layout)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._view.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self._view.viewport().setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
        self._view.viewport().installEventFilter(self)
        self._update_cursor()

    # -------------------- public API --------------------
    def set_active_layer(self, layer: ActiveLayer) -> None:
        if self.active_layer == layer:
            return
        self.active_layer = layer
        self._update_cursor()

    def set_layer_visible_background(self, visible: bool) -> None:
        self.layer_visible_background = bool(visible)
        self._apply_layer_visibility()

    def set_layer_visible_mask(self, visible: bool) -> None:
        self.layer_visible_mask = bool(visible)
        self._apply_layer_visibility()

    def set_layer_visible_paint(self, visible: bool) -> None:
        self.layer_visible_paint = bool(visible)
        self._apply_layer_visibility()

    def set_layer_visible_text(self, visible: bool) -> None:
        self.layer_visible_text = bool(visible)
        self._apply_layer_visibility()

    def set_page_session(
        self, pixmap: QtGui.QPixmap, session: PageSession, paint_layer: Optional[QImage] = None
    ) -> None:
        """Render a page pixmap together with translated blocks and masks."""
        if pixmap is None or pixmap.isNull():
            self.set_pixmap(None)
            return

        previous_session = self._session
        self._session = session
        self._page_image = pixmap.toImage()

        paint_image = paint_layer
        if paint_image is None and previous_session is session and self.paint_layer is not None:
            paint_image = QImage(self.paint_layer)
        if paint_image is None:
            paint_image = getattr(session, "paint_layer_image", None)

        self._clear_scene()
        self._current_pixmap = pixmap
        self._scene.setSceneRect(pixmap.rect())
        self._fit_width_mode = False
        self._fit_window_mode = True
        self._zoom_factor = 1.0

        self.background_item = self._scene.addPixmap(pixmap)
        self.background_item.setZValue(self.BACKGROUND_Z)

        size = pixmap.size()
        if paint_image is not None and not paint_image.isNull() and paint_image.size() == size:
            self.paint_layer = QImage(paint_image)
        else:
            self.paint_layer = QImage(size.width(), size.height(), QImage.Format_ARGB32_Premultiplied)
            self.paint_layer.fill(QtCore.Qt.transparent)
        self.paint_item = self._scene.addPixmap(QtGui.QPixmap.fromImage(self.paint_layer))
        self.paint_item.setZValue(self.PAINT_Z)

        self._build_bubbles(session)
        self._apply_layer_visibility()
        self._fit_in_view()
        self._select_bubble(None)

    def set_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        """Display only the given pixmap on the canvas (no blocks)."""
        self._clear_scene()
        if pixmap is None or pixmap.isNull():
            self._current_pixmap = None
            return
        dummy_session = PageSession(project_id="", page_index=0, image_path=Path(), text_blocks=[])
        self.set_page_session(pixmap, dummy_session)

    def set_current_tool(self, tool: PageTool) -> None:
        if self.current_tool == tool:
            return
        self.current_tool = tool
        if tool == PageTool.HAND and not self._add_block_mode:
            self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self._hand_dragging = False
        if tool not in (PageTool.BRUSH, PageTool.ERASER):
            self._is_drawing = False
            self._last_draw_pos = None
        self._update_cursor()

    def set_brush_color(self, color: QColor) -> None:
        self._brush_color = QColor(color)

    def brush_color(self) -> QColor:
        return QColor(self._brush_color)

    def set_brush_width(self, width: int) -> None:
        self._brush_width = max(1, int(width))

    def get_paint_layer_image(self) -> Optional[QImage]:
        if self.paint_layer is None:
            return None
        return QImage(self.paint_layer)

    def set_paint_layer_image(self, image: Optional[QImage]) -> None:
        if image is None or image.isNull() or self._current_pixmap is None:
            return
        if image.size() != self._current_pixmap.size():
            return
        self.paint_layer = QImage(image)
        if self.paint_item is None:
            self.paint_item = self._scene.addPixmap(QtGui.QPixmap.fromImage(self.paint_layer))
        else:
            self.paint_item.setPixmap(QtGui.QPixmap.fromImage(self.paint_layer))
        self.paint_item.setZValue(self.PAINT_Z)
        self._apply_layer_visibility()

    def toggle_mask_enabled(self, on: bool) -> None:
        self.set_layer_visible_mask(on)

    def toggle_text_enabled(self, on: bool) -> None:
        self.set_layer_visible_text(on)

    def set_show_sfx(self, on: bool) -> None:
        self._show_sfx = bool(on)
        self._apply_layer_visibility()

    def set_add_block_mode(self, enabled: bool) -> None:
        self._add_block_mode = bool(enabled)
        if enabled:
            self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self._hand_dragging = False
            self._is_drawing = False
            self._last_draw_pos = None
        else:
            self._clear_selection_rect()
            if self.current_tool == PageTool.HAND:
                self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self._update_cursor()

    def zoom_in(self, step: float = 0.1) -> None:
        self._fit_width_mode = False
        self._fit_window_mode = False
        self._zoom_factor = min(8.0, self._zoom_factor + abs(step))
        self._fit_in_view()
        self._emit_zoom_changed()

    def zoom_out(self, step: float = 0.1) -> None:
        self._fit_width_mode = False
        self._fit_window_mode = False
        self._zoom_factor = max(0.1, self._zoom_factor - abs(step))
        self._fit_in_view()
        self._emit_zoom_changed()

    def reset_zoom(self) -> None:
        self._fit_width_mode = False
        self._fit_window_mode = True
        self._zoom_factor = 1.0
        self._fit_in_view()
        self._emit_zoom_changed()

    def zoom_fit_width(self) -> None:
        self._fit_width_mode = True
        self._fit_window_mode = False
        self._fit_in_view()
        self._emit_zoom_changed()

    def zoom_fit_window(self) -> None:
        self._fit_width_mode = False
        self._fit_window_mode = True
        self._fit_in_view()
        self._emit_zoom_changed()

    def set_zoom_factor(self, factor: float) -> None:
        """Force a specific zoom factor for the translated canvas."""
        self._fit_width_mode = False
        self._fit_window_mode = False
        self._zoom_factor = max(0.1, min(8.0, float(factor)))
        self._fit_in_view()
        self._emit_zoom_changed()

    def current_zoom_factor(self) -> float:
        """Return current zoom factor for syncing other viewers."""
        return float(self._zoom_factor)

    def set_highlighted_block(self, block_id: Optional[str]) -> None:
        """Highlight/select a bubble corresponding to a block id."""
        if block_id is None:
            self._select_bubble(None)
            return
        bubble = self._bubble_by_block_id.get(block_id)
        target_id = bubble.bubble_id if bubble else None
        self._select_bubble(target_id)

    def first_block_id_for_bubble(self, bubble_id: str) -> Optional[str]:
        bubble = self._blocks.get(bubble_id)
        if bubble is None or not bubble.text_block_ids:
            return None
        return bubble.text_block_ids[0]

    # -------------------- text + style helpers --------------------
    def update_block_translation(self, block_id: str, new_text: str) -> None:
        """Update rendered translation text for a specific block."""
        if self._session is None:
            return
        bubble = self._bubble_by_block_id.get(block_id)
        if bubble is None or bubble.text_item is None:
            return

        target_block: Optional[TextBlock] = None
        for b in self._session.text_blocks:
            if b.id == block_id:
                target_block = b
                break
        if target_block is None:
            return
        target_block.translated_text = new_text

        blocks_in_bubble = self._blocks_for_bubble(bubble)
        text = "\n".join(b.translated_text for b in blocks_in_bubble if b.translated_text)
        bubble.text_item.setPlainText(text)
        bubble.text_item.setTextWidth(bubble.bbox.width())
        self._apply_style_to_text_item(bubble.bubble_id, bubble.text_item, bubble.block_type, bubble.bbox, blocks_in_bubble)

    def remove_block(self, block_id: str) -> None:
        """Remove a block from canvas visuals and update bubble content."""
        if self._session is None:
            return
        bubble = self._bubble_by_block_id.get(block_id)
        if bubble is None:
            return

        if block_id in bubble.text_block_ids:
            bubble.text_block_ids.remove(block_id)
        self._bubble_by_block_id.pop(block_id, None)

        if bubble.text_block_ids:
            blocks_in_bubble = self._blocks_for_bubble(bubble)
            if bubble.text_item is not None:
                bubble.text_item.setPlainText(
                    "\n".join(b.translated_text for b in blocks_in_bubble if b.translated_text)
                )
                bubble.text_item.setTextWidth(bubble.bbox.width())
                self._apply_style_to_text_item(
                    bubble.bubble_id, bubble.text_item, bubble.block_type, bubble.bbox, blocks_in_bubble
                )
            bubble.enabled = any(getattr(b, "enabled", True) for b in blocks_in_bubble)
            self._apply_layer_visibility()
        else:
            if bubble.mask_item is not None:
                self._scene.removeItem(bubble.mask_item)
            if bubble.text_item is not None:
                self._scene.removeItem(bubble.text_item)
            self._blocks.pop(bubble.bubble_id, None)
            if self.selected_bubble_id == bubble.bubble_id:
                self._select_bubble(None)

    def apply_bubble_style(
        self,
        bubble_id: str,
        *,
        font_family: Optional[str] = None,
        font_size: Optional[int] = None,
        align: Optional[str] = None,
    ) -> None:
        """Update style for a bubble and refresh its text item."""
        if self._session is None:
            return
        bg = self._blocks.get(bubble_id)
        if bg is None or bg.text_item is None:
            return

        current_style = self._session.bubble_styles.get(bubble_id, BubbleStyle())
        current_style.font_family = font_family
        clamped_size: Optional[int]
        if font_size is None:
            clamped_size = None
        else:
            try:
                clamped_size = max(6, min(int(font_size), 96))
            except (TypeError, ValueError):
                clamped_size = None
        current_style.font_size = clamped_size
        if align is not None and align not in ("left", "center", "right"):
            align = "center"
        current_style.align = align
        self._session.bubble_styles[bubble_id] = current_style

        blocks_in_bubble = self._blocks_for_bubble(bg)
        self._apply_style_to_text_item(bubble_id, bg.text_item, bg.block_type, bg.bbox, blocks_in_bubble)

    def selected_bubble_style(self) -> tuple[Optional[str], Optional[int], Optional[str]]:
        if self._session is None or self.selected_bubble_id is None:
            return None, None, None
        style = self._session.bubble_styles.get(self.selected_bubble_id, BubbleStyle())
        return style.font_family, style.font_size, style.align

    # -------------------- mouse events --------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._fit_in_view()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.viewActivated.emit()
        if self._add_block_mode:
            scene_pos = self._view.mapToScene(event.pos())
            self._selection_origin = QPointF(scene_pos)
            self._update_selection_rect(self._selection_origin, self._selection_origin)
            event.accept()
            return

        if self.current_tool == PageTool.HAND:
            self._hand_dragging = True
            self._view.viewport().setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))
            super().mousePressEvent(event)
            return

        scene_pos = self._view.mapToScene(event.pos())

        if self.active_layer == ActiveLayer.TEXT:
            bubble = self._bubble_at_scene_point(scene_pos)
            self._select_bubble(bubble.bubble_id if bubble else None)
            if bubble and bubble.text_block_ids:
                self.blockClicked.emit(bubble.text_block_ids[0])
            event.accept()
            return

        if self.active_layer == ActiveLayer.PAINT:
            if self.current_tool == PageTool.EYEDROPPER:
                self._pick_color_at(scene_pos)
                event.accept()
                return
            if self.current_tool in (PageTool.BRUSH, PageTool.ERASER):
                self._is_drawing = True
                self._last_draw_pos = QPointF(self._clamp_to_image(scene_pos))
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if self._add_block_mode:
            if self._selection_origin is not None:
                scene_pos = self._view.mapToScene(event.pos())
                self._update_selection_rect(self._selection_origin, QPointF(scene_pos))
            event.accept()
            return
        if self.current_tool == PageTool.HAND and self._hand_dragging:
            super().mouseMoveEvent(event)
            return

        if self.active_layer == ActiveLayer.PAINT and self._is_drawing and self.paint_layer is not None:
            current_point = QPointF(self._clamp_to_image(self._view.mapToScene(event.pos())))
            if self._last_draw_pos is None:
                self._last_draw_pos = current_point
            painter = QPainter(self.paint_layer)
            painter.setRenderHint(QPainter.Antialiasing, True)
            if self.current_tool == PageTool.ERASER:
                painter.setCompositionMode(QPainter.CompositionMode.Clear)
                pen = QPen(QtCore.Qt.GlobalColor.transparent)
            else:
                pen = QPen(self._brush_color)
            pen.setWidth(self._brush_width)
            painter.setPen(pen)
            painter.drawLine(self._last_draw_pos, current_point)
            painter.end()

            self._last_draw_pos = current_point
            if self.paint_item is not None:
                self.paint_item.setPixmap(QtGui.QPixmap.fromImage(self.paint_layer))
            self.paintLayerChanged.emit()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        if self._add_block_mode:
            if self._selection_origin is not None:
                scene_pos = self._view.mapToScene(event.pos())
                rect = QtCore.QRectF(self._selection_origin, QPointF(scene_pos)).normalized()
                rect = rect.intersected(self._scene.sceneRect())
                if rect.width() > 1 and rect.height() > 1:
                    self.blockAreaSelected.emit(rect)
            self._add_block_mode = False
            self._clear_selection_rect()
            if self.current_tool == PageTool.HAND:
                self._view.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
            self._update_cursor()
            event.accept()
            return

        if self.current_tool == PageTool.HAND:
            self._hand_dragging = False
            self._update_cursor()
            super().mouseReleaseEvent(event)
            return

        if self.active_layer == ActiveLayer.PAINT and self._is_drawing:
            self._is_drawing = False
            self._last_draw_pos = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # type: ignore[override]
        if obj is self._view.viewport() and event.type() == QtCore.QEvent.Type.Wheel:
            we = cast(QtGui.QWheelEvent, event)
            if we.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                if we.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True
        return super().eventFilter(obj, event)

    # -------------------- internal helpers --------------------
    def _build_bubbles(self, session: PageSession) -> None:
        visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
        bubbles = group_blocks_into_bubbles(visible_blocks)
        self._blocks.clear()
        self._bubble_by_block_id.clear()
        self.mask_items.clear()
        self.text_items.clear()

        block_map = {b.id: b for b in visible_blocks}
        for bubble in bubbles:
            rect = bubble.bbox
            mask_item = self._scene.addRect(rect, pen=QtCore.Qt.PenStyle.NoPen, brush=QtGui.QBrush(QtCore.Qt.white))
            mask_item.setZValue(self.MASK_Z)

            blocks_in_bubble = [block_map[bid] for bid in bubble.text_block_ids if bid in block_map]
            blocks_in_bubble.sort(key=lambda b: b.bbox[1])
            bubble_text = "\n".join(b.translated_text for b in blocks_in_bubble if b.translated_text)

            text_item = self._scene.addText(bubble_text)
            text_item.setDefaultTextColor(QtGui.QColor("black"))
            text_item.setTextWidth(rect.width())
            text_item.setZValue(self.TEXT_Z)
            self._apply_style_to_text_item(bubble.id, text_item, bubble.block_type, rect, blocks_in_bubble)

            bubble_enabled = any(getattr(b, "enabled", True) for b in blocks_in_bubble) if blocks_in_bubble else True

            bg = BlockGraphics(
                bubble_id=bubble.id,
                text_block_ids=list(bubble.text_block_ids),
                bbox=rect,
                block_type=bubble.block_type,
                mask_item=mask_item,
                text_item=text_item,
                enabled=bubble_enabled,
            )
            self._blocks[bubble.id] = bg
            for bid in bubble.text_block_ids:
                self._bubble_by_block_id[bid] = bg
            self.mask_items[bubble.id] = mask_item
            self.text_items[bubble.id] = text_item

    def _apply_style_to_text_item(
        self,
        bubble_id: str,
        text_item: QtWidgets.QGraphicsTextItem,
        block_type: str,
        rect: QtCore.QRectF,
        blocks_in_bubble: list[TextBlock],
    ) -> None:
        style = BubbleStyle()
        if self._session is not None:
            style = self._session.bubble_styles.get(bubble_id, BubbleStyle())

        fallback_size = blocks_in_bubble[0].font_size if blocks_in_bubble and blocks_in_bubble[0].font_size else 24
        default_family = self._font_family_for_block_type(block_type)
        resolved = resolve_bubble_style(
            style,
            default_family=default_family,
            default_size=fallback_size,
            fallback_font_size=fallback_size,
            default_align="center",
        )
        apply_style_and_layout_text_item(text_item, rect, resolved)

    def _apply_layer_visibility(self) -> None:
        if self.background_item is not None:
            self.background_item.setVisible(self.layer_visible_background)
        if self.paint_item is not None:
            self.paint_item.setVisible(self.layer_visible_paint)

        for bubble in self._blocks.values():
            show_mask = self.layer_visible_mask and bubble.enabled
            show_text = self.layer_visible_text and bubble.enabled
            if bubble.block_type == "sfx" and not self._show_sfx:
                show_mask = False
                show_text = False
            if bubble.mask_item is not None:
                bubble.mask_item.setVisible(show_mask)
            if bubble.text_item is not None:
                bubble.text_item.setVisible(show_text)

        if self._selection_highlight is not None:
            self._selection_highlight.setVisible(self.selected_bubble_id is not None)
        if self._selection_rect_item is not None:
            self._selection_rect_item.setVisible(self._add_block_mode)

    def _font_family_for_block_type(self, block_type: str) -> Optional[str]:
        if block_type == "sfx" and app_config.sfx_font_family:
            return app_config.sfx_font_family
        if app_config.manga_font_family:
            return app_config.manga_font_family
        return None

    def _blocks_for_bubble(self, bubble: BlockGraphics) -> list[TextBlock]:
        if self._session is None:
            return []
        blocks_map = {b.id: b for b in self._session.text_blocks}
        blocks: list[TextBlock] = []
        for bid in bubble.text_block_ids:
            block = blocks_map.get(bid)
            if block is None or getattr(block, "deleted", False):
                continue
            blocks.append(block)
        blocks.sort(key=lambda b: b.bbox[1])
        return blocks

    def _bubble_at_scene_point(self, point: QtCore.QPointF) -> Optional[BlockGraphics]:
        for bubble in self._blocks.values():
            if bubble.bbox.contains(point):
                return bubble
        return None

    def _select_bubble(self, bubble_id: Optional[str]) -> None:
        if self.selected_bubble_id == bubble_id:
            return
        self.selected_bubble_id = bubble_id
        self._update_selection_highlight()
        self.selectedBubbleChanged.emit(bubble_id)

    def _update_selection_highlight(self) -> None:
        if self._selection_highlight is not None:
            self._scene.removeItem(self._selection_highlight)
            self._selection_highlight = None
        if self.selected_bubble_id is None:
            return
        bubble = self._blocks.get(self.selected_bubble_id)
        if bubble is None:
            return
        pen = QPen(QColor(0, 120, 215))
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        pen.setWidthF(1.5)
        self._selection_highlight = self._scene.addRect(bubble.bbox, pen=pen, brush=QtCore.Qt.BrushStyle.NoBrush)
        self._selection_highlight.setZValue(self.HIGHLIGHT_Z)
        self._selection_highlight.setVisible(True)

    def _pick_color_at(self, scene_pos: QtCore.QPointF) -> None:
        if self.paint_layer is not None:
            pt = self._clamp_to_image(scene_pos)
            x, y = int(pt.x()), int(pt.y())
            if 0 <= x < self.paint_layer.width() and 0 <= y < self.paint_layer.height():
                sampled = QColor(self.paint_layer.pixel(x, y))
                if sampled.alpha() > 0:
                    self._brush_color = sampled
                    return
        if self._page_image is not None:
            pt = self._clamp_to_image(scene_pos)
            x, y = int(pt.x()), int(pt.y())
            if 0 <= x < self._page_image.width() and 0 <= y < self._page_image.height():
                self._brush_color = QColor(self._page_image.pixel(x, y))

    def _update_cursor(self) -> None:
        cursor = QtCore.Qt.CursorShape.ArrowCursor
        paint_only = self.current_tool in (PageTool.BRUSH, PageTool.ERASER, PageTool.EYEDROPPER)
        if paint_only and self.active_layer != ActiveLayer.PAINT:
            cursor = QtCore.Qt.CursorShape.ForbiddenCursor
        elif self._add_block_mode or self.current_tool in (PageTool.BRUSH, PageTool.ERASER):
            cursor = QtCore.Qt.CursorShape.CrossCursor
        elif self.current_tool == PageTool.EYEDROPPER:
            cursor = QtCore.Qt.CursorShape.PointingHandCursor
        elif self.current_tool == PageTool.HAND:
            cursor = QtCore.Qt.CursorShape.OpenHandCursor
        self._view.viewport().setCursor(QtGui.QCursor(cursor))

    def _update_selection_rect(self, start: QPointF, end: QPointF) -> None:
        rect = QtCore.QRectF(start, end).normalized()
        rect = rect.intersected(self._scene.sceneRect())
        if self._selection_rect_item is None:
            pen = QPen(QColor(0, 120, 215))
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            brush = QBrush(QColor(0, 120, 215, 60))
            self._selection_rect_item = self._scene.addRect(rect, pen=pen, brush=brush)
            self._selection_rect_item.setZValue(self.HIGHLIGHT_Z)
        else:
            self._selection_rect_item.setRect(rect)

    def _clear_selection_rect(self) -> None:
        if self._selection_rect_item is not None:
            self._scene.removeItem(self._selection_rect_item)
            self._selection_rect_item = None
        self._selection_origin = None

    def _clear_scene(self) -> None:
        self._scene.clear()
        self.background_item = None
        self.mask_items = {}
        self.text_items = {}
        self.paint_layer = None
        self.paint_item = None
        self._blocks = {}
        self._bubble_by_block_id = {}
        self._current_pixmap = None
        self._page_image = None
        self._is_drawing = False
        self._last_draw_pos = None
        self._selection_origin = None
        self._hand_dragging = False
        self._selection_highlight = None
        if self._selection_rect_item is not None:
            self._scene.removeItem(self._selection_rect_item)
            self._selection_rect_item = None
        self._add_block_mode = False
        self.selected_bubble_id = None
        self._update_cursor()

    def _fit_in_view(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isNull():
            return
        viewport_center = self._view.mapToScene(self._view.viewport().rect().center())
        if self._fit_width_mode:
            viewport = self._view.viewport().size()
            if viewport.width() > 0 and rect.width() > 0:
                self._zoom_factor = max(0.01, viewport.width() / rect.width())
        elif self._fit_window_mode:
            viewport = self._view.viewport().size()
            if viewport.width() > 0 and viewport.height() > 0 and rect.width() > 0 and rect.height() > 0:
                sx = viewport.width() / rect.width()
                sy = viewport.height() / rect.height()
                self._zoom_factor = max(0.01, min(sx, sy))
        self._view.resetTransform()
        self._view.scale(self._zoom_factor, self._zoom_factor)
        if self._fit_width_mode or self._fit_window_mode:
            self._view.centerOn(rect.center().x(), rect.top())
        else:
            self._view.centerOn(viewport_center)

    def _emit_zoom_changed(self) -> None:
        try:
            self.zoomChanged.emit(float(self._zoom_factor))
        except Exception:
            pass

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._fit_width_mode or self._fit_window_mode:
            self._fit_in_view()
            self._emit_zoom_changed()

    def _clamp_to_image(self, scene_pos: QtCore.QPointF) -> QtCore.QPointF:
        if self._current_pixmap is None:
            return scene_pos
        x = max(0.0, min(scene_pos.x(), float(self._current_pixmap.width() - 1)))
        y = max(0.0, min(scene_pos.y(), float(self._current_pixmap.height() - 1)))
        return QtCore.QPointF(x, y)
