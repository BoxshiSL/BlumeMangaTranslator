"""
Overlay-модуль для отображения переводов блоков поверх интерфейса.

Реализует:
- OverlayWidget — отдельная полупрозрачная плашка с текстом;
- OverlayManager — менеджер, который создаёт/удаляет такие плашки для списка TextBlock.

В этой версии overlay работает только внутри родительского окна/виджета
(никакого глобального захвата экрана).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from project.page_session import TextBlock


class OverlayWidget(QtWidgets.QWidget):
    """
    Одна плашка overlay для отображения текста поверх родительского виджета.

    Рисует полупрозрачный прямоугольник с текстом перевода/оригинала.
    Координаты заданы в системе координат родительского виджета.
    """

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        rect: QtCore.QRect,
        text: str,
    ) -> None:
        super().__init__(parent)
        self._rect = QtCore.QRect(rect)
        self._text = text

        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(self._rect)

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()

    def set_rect(self, rect: QtCore.QRect) -> None:
        self._rect = QtCore.QRect(rect)
        self.setGeometry(self._rect)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        if not self._text.strip():
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        bg_color = QtGui.QColor(0, 0, 0, 180)
        border_color = QtGui.QColor(255, 255, 255, 220)

        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = 4

        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.fillPath(path, bg_color)

        pen = QtGui.QPen(border_color)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.setPen(QtCore.Qt.white)
        inner = rect.adjusted(4, 2, -4, -2)
        painter.drawText(
            inner,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap,
            self._text,
        )


class OverlayManager(QtCore.QObject):
    """Manages a set of overlays for a given parent widget."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._overlays: List[OverlayWidget] = []
        self._visible: bool = False

    def clear(self) -> None:
        """Hide and remove all overlays."""
        for ov in self._overlays:
            ov.hide()
            ov.deleteLater()
        self._overlays.clear()
        self._visible = False

    def _create_overlay_for_block(self, block: TextBlock) -> Optional[OverlayWidget]:
        if not block.enabled:
            return None
        text = (block.translated_text or "").strip()
        if not text:
            text = (block.original_text or "").strip()
        if not text:
            return None

        x1, y1, x2, y2 = block.bbox
        rect = QtCore.QRect(int(x1), int(y1), max(1, int(x2 - x1)), max(1, int(y2 - y1)))
        return OverlayWidget(self._parent_widget, rect, text)

    def show_for_blocks(self, blocks: List[TextBlock]) -> None:
        """Create overlays for the given blocks and show them."""
        self.clear()
        for block in blocks:
            overlay = self._create_overlay_for_block(block)
            if overlay is None:
                continue
            overlay.show()
            overlay.raise_()
            self._overlays.append(overlay)
        self._visible = bool(self._overlays)

    def hide(self) -> None:
        """Hide all overlays (they remain constructed)."""
        for ov in self._overlays:
            ov.hide()
        self._visible = False

    def show(self) -> None:
        """Show existing overlays."""
        for ov in self._overlays:
            ov.show()
            ov.raise_()
        self._visible = bool(self._overlays)

    def toggle(self, blocks: Optional[List[TextBlock]] = None) -> None:
        """Toggle overlay visibility; rebuild if blocks provided."""
        if self._visible:
            self.hide()
        else:
            if blocks is not None:
                self.show_for_blocks(blocks)
            else:
                self.show()

    def is_visible(self) -> bool:
        """Return True if overlays are currently visible."""
        return self._visible
