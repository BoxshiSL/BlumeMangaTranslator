"""Image export utilities for translated pages."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from config import app_config
from project.page_layout import group_blocks_into_bubbles
from project.page_session import BubbleStyle, PageSession, TextBlock
from ui.text_layout import apply_style_and_layout_text_item, resolve_bubble_style


def _load_qimage(path: Path) -> QtGui.QImage:
    img = QtGui.QImage(str(path))
    if img.isNull():
        raise FileNotFoundError(f"Failed to load image for export: {path}")
    return img


def _bubble_text(blocks: Iterable[TextBlock]) -> str:
    lines = [b.translated_text for b in blocks if (b.translated_text or "").strip()]
    return "\n".join(lines)


def _resolve_paint_layer(session: PageSession, size: QtCore.QSize) -> Optional[QtGui.QImage]:
    paint_image = getattr(session, "paint_layer_image", None)
    if paint_image is None and session.paint_layer_path:
        candidate = QtGui.QImage(str(session.paint_layer_path))
        if not candidate.isNull():
            paint_image = candidate
    if paint_image is None or paint_image.isNull():
        return None
    if paint_image.size() != size:
        return None
    return paint_image


def export_page_with_translations(
    session: PageSession,
    dst_lang: str,
    content_type: str = "standard",
    color_mode: str = "bw",
    font_path: str | None = None,
    font_size: int = 24,
) -> Path:
    """
    Export a single page with translated text drawn over it.

    Export is rendered in image space to match on-screen layout.
    """
    image_path = session.image_path
    original_path = session.original_image_path or image_path
    chapter_dir = original_path.parent
    out_dir = chapter_dir / dst_lang
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / original_path.name

    page_image = _load_qimage(image_path)
    size = page_image.size()

    scene = QtWidgets.QGraphicsScene()
    scene.setSceneRect(QtCore.QRectF(0, 0, size.width(), size.height()))

    background_item = scene.addPixmap(QtGui.QPixmap.fromImage(page_image))
    background_item.setZValue(0)

    paint_layer = _resolve_paint_layer(session, size)
    if paint_layer is not None:
        paint_item = scene.addPixmap(QtGui.QPixmap.fromImage(paint_layer))
        paint_item.setZValue(20)
    else:
        paint_item = None

    visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
    bubbles = group_blocks_into_bubbles(visible_blocks)

    block_map = {b.id: b for b in visible_blocks}
    for bubble in bubbles:
        rect = bubble.bbox
        blocks_in_bubble = [block_map[bid] for bid in bubble.text_block_ids if bid in block_map and block_map[bid].enabled]
        blocks_in_bubble.sort(key=lambda b: b.bbox[1])
        bubble_enabled = any(getattr(b, "enabled", True) for b in blocks_in_bubble) if blocks_in_bubble else True
        if bubble.block_type == "sfx" and not session.show_sfx:
            bubble_enabled = False
        if not bubble_enabled:
            continue

        if session.mask_enabled:
            mask_item = scene.addRect(rect, pen=QtCore.Qt.PenStyle.NoPen, brush=QtGui.QBrush(QtCore.Qt.white))
            mask_item.setZValue(10)

        if not session.text_enabled:
            continue

        text = _bubble_text(blocks_in_bubble)
        text_item = scene.addText(text)
        text_item.setDefaultTextColor(QtGui.QColor("black"))
        text_item.setTextWidth(rect.width())
        text_item.setZValue(30)

        style = session.bubble_styles.get(bubble.id, BubbleStyle())
        fallback_size = blocks_in_bubble[0].font_size if blocks_in_bubble and blocks_in_bubble[0].font_size else font_size
        default_family = app_config.sfx_font_family if bubble.block_type == "sfx" else app_config.manga_font_family
        resolved = resolve_bubble_style(
            style,
            default_family=default_family,
            default_size=font_size,
            fallback_font_size=fallback_size,
        )
        apply_style_and_layout_text_item(text_item, rect, resolved)

    export_image = QtGui.QImage(size, QtGui.QImage.Format_ARGB32_Premultiplied)
    export_image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(export_image)
    scene.render(painter, QtCore.QRectF(0, 0, size.width(), size.height()), scene.sceneRect())
    painter.end()

    export_image.save(str(output_path))
    return output_path
