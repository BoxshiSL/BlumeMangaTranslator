"""Helpers for resolving bubble text styles and laying out text items."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QTextBlockFormat

from config import app_config
from project.page_session import BubbleStyle

logger = logging.getLogger(__name__)

MIN_FONT_SIZE = 6
MAX_FONT_SIZE = 96


def safe_set_line_height(
    fmt: QtGui.QTextBlockFormat,
    height: float | int | None,
    height_type: QtGui.QTextBlockFormat.LineHeightTypes = QtGui.QTextBlockFormat.LineHeightTypes.ProportionalHeight,
) -> None:
    """
    Safely set line height on a QTextBlockFormat, ignoring invalid values.
    height_type must be passed as int for PySide6.
    """
    if height is None:
        return
    try:
        h = float(height)
    except (TypeError, ValueError):
        return
    if h <= 0:
        return
    try:
        height_type_int = int(getattr(height_type, "value", height_type))
    except (TypeError, ValueError):
        return
    fmt.setLineHeight(h, height_type_int)

@dataclass
class ResolvedBubbleStyle:
    font_family: str
    font_size: int
    line_spacing: Optional[float]
    align: str  # "center" | "left" | "right"


def resolve_bubble_style(
    style: Optional[BubbleStyle],
    *,
    default_family: Optional[str] = None,
    default_size: int = 24,
    default_align: str = "center",
    default_line_spacing: float | None = 1.0,
    fallback_font_size: Optional[int] = None,
) -> ResolvedBubbleStyle:
    """Fill missing style fields with defaults."""
    family = (style.font_family if style else None) or default_family or app_config.manga_font_family or ""
    size = _normalize_font_size(style.font_size if style else None, default_size, fallback_font_size)
    align = _normalize_align((style.align if style else None) or default_align)
    line_spacing = _normalize_line_spacing(style.line_spacing if style else None, default_line_spacing)
    return ResolvedBubbleStyle(font_family=family, font_size=size, line_spacing=line_spacing, align=align)


def apply_style_and_layout_text_item(
    text_item: QtWidgets.QGraphicsTextItem,
    rect: QtCore.QRectF,
    style: ResolvedBubbleStyle,
    *,
    min_size: int = 6,
) -> None:
    """Apply style to a text item and shrink-to-fit inside rect in image coordinates."""
    font = QtGui.QFont(style.font_family if style.font_family else "")
    target_size = max(min_size, min(style.font_size, MAX_FONT_SIZE))
    text_item.setTextWidth(rect.width())

    # Alignment
    option = QtGui.QTextOption()
    align_map = {
        "left": QtCore.Qt.AlignmentFlag.AlignLeft,
        "right": QtCore.Qt.AlignmentFlag.AlignRight,
        "center": QtCore.Qt.AlignmentFlag.AlignHCenter,
    }
    option.setAlignment(align_map.get(style.align, QtCore.Qt.AlignmentFlag.AlignHCenter))

    # Fit font size
    size = target_size
    while size >= min_size:
        font.setPointSize(size)
        text_item.setFont(font)
        doc = text_item.document()
        doc.setDefaultTextOption(option)
        _apply_line_spacing(doc, style.line_spacing)
        bounds = text_item.boundingRect()
        if bounds.width() <= rect.width() and bounds.height() <= rect.height():
            break
        size -= 1

    # Final alignment positioning
    bounds = text_item.boundingRect()
    if style.align == "left":
        x = rect.x()
    elif style.align == "right":
        x = rect.right() - bounds.width()
    else:
        x = rect.x() + (rect.width() - bounds.width()) / 2
    y = rect.y() + (rect.height() - bounds.height()) / 2
    text_item.setPos(x, y)


def _apply_line_spacing(document: QtGui.QTextDocument, line_spacing: Optional[float]) -> None:
    """Apply proportional line spacing to all blocks in the document."""
    if line_spacing is None:
        return
    try:
        spacing_value = float(line_spacing)
    except (TypeError, ValueError):
        return
    if spacing_value <= 0:
        return

    cursor = QtGui.QTextCursor(document)
    block_format = QTextBlockFormat()
    safe_set_line_height(
        block_format,
        spacing_value,
        QTextBlockFormat.LineHeightTypes.ProportionalHeight,
    )
    cursor.select(QtGui.QTextCursor.SelectionType.Document)
    cursor.setBlockFormat(block_format)


def _normalize_font_size(
    raw_size: Optional[int | float],
    default_size: int,
    fallback_size: Optional[int] = None,
) -> int:
    """Clamp font size to a sane range, falling back to defaults on bad data."""
    candidate = fallback_size if fallback_size is not None else default_size
    if raw_size is not None:
        try:
            parsed = int(raw_size)
        except (TypeError, ValueError):
            logger.warning("Invalid font size value %r, using fallback %s", raw_size, candidate)
        else:
            if parsed > 0:
                candidate = parsed
            else:
                logger.warning("Non-positive font size %s ignored, using fallback %s", parsed, candidate)
    return max(MIN_FONT_SIZE, min(candidate, MAX_FONT_SIZE))


def _normalize_line_spacing(
    raw_spacing: Optional[float | int],
    default_spacing: Optional[float | int],
) -> Optional[float]:
    """
    Convert stored spacing into the percent value expected by Qt.
    Accepts either multipliers (<=10 -> treated as x100%) or already-percentage values.
    """
    source = raw_spacing if raw_spacing is not None else default_spacing
    if source is None:
        return None
    try:
        spacing = float(source)
    except (TypeError, ValueError):
        logger.warning("Invalid line spacing %r, skipping line-height application", source)
        return None
    if spacing <= 0.0:
        logger.warning("Non-positive line spacing %s ignored", spacing)
        return None
    if spacing <= 10.0:
        return spacing * 100.0
    return spacing


def _normalize_align(raw_align: str) -> str:
    """Return a safe alignment keyword."""
    if raw_align in ("left", "right", "center"):
        return raw_align
    return "center"
