"""Builder that converts PageSession into export-ready data."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtGui

from config import (
    DEFAULT_MANGA_FONT_FAMILY,
    DEFAULT_SFX_FONT_FAMILY,
    app_config,
)
from export.model import ExportPageData, ExportTextBubble, ExportTextStyle
from project.page_layout import group_blocks_into_bubbles
from project.page_session import PageSession, TextBlock


def _block_rect(block: TextBlock) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = block.bbox
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    return (x1, y1, w, h)


def _bubble_rect_from_bbox(rectf) -> tuple[int, int, int, int]:
    x = rectf.x()
    y = rectf.y()
    w = rectf.width()
    h = rectf.height()
    return (int(x), int(y), int(w), int(h))


def _resolved_font_family(block_type: str) -> str:
    if block_type == "sfx":
        return app_config.sfx_font_family or DEFAULT_SFX_FONT_FAMILY
    return app_config.manga_font_family or DEFAULT_MANGA_FONT_FAMILY


def build_export_page_data(
    session: PageSession,
    *,
    mask_color: tuple[int, int, int, int] = (255, 255, 255, 255),
) -> ExportPageData:
    """Create ExportPageData from a PageSession."""
    if session.image_path is None or not session.image_path.is_file():
        raise FileNotFoundError("Page image is missing for export")
    image = QtGui.QImage(str(session.image_path))
    if image.isNull():
        raise ValueError("Failed to load page image for export")
    width, height = image.width(), image.height()

    visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
    bubbles = group_blocks_into_bubbles(visible_blocks)
    block_map = {b.id: b for b in visible_blocks}

    export_bubbles: list[ExportTextBubble] = []
    for bubble in bubbles:
        rect = _bubble_rect_from_bbox(bubble.bbox)
        blocks_in_bubble: list[TextBlock] = []
        for bid in bubble.text_block_ids:
            block = block_map.get(bid)
            if block is None or getattr(block, "deleted", False):
                continue
            blocks_in_bubble.append(block)
        blocks_in_bubble.sort(key=lambda b: b.bbox[1])

        bubble_enabled = any(getattr(b, "enabled", True) for b in blocks_in_bubble) if blocks_in_bubble else True
        if bubble.block_type == "sfx" and not session.show_sfx:
            bubble_enabled = False

        text = ""
        if session.text_enabled and bubble_enabled:
            text_lines = [b.translated_text for b in blocks_in_bubble if b.translated_text]
            text = "\n".join(text_lines)

        size_hint = blocks_in_bubble[0].font_size if blocks_in_bubble and blocks_in_bubble[0].font_size else 24
        style = session.bubble_styles.get(bubble.id) if hasattr(session, "bubble_styles") else None
        font_family = (style.font_family if style else None) or _resolved_font_family(bubble.block_type) or ""
        font_size = int(style.font_size) if style and style.font_size else int(size_hint)
        align = (style.align if style and style.align else "center")  # type: ignore[assignment]
        export_style = ExportTextStyle(
            font_family=font_family,
            font_size=font_size,
            color=(0, 0, 0, 255),
            align=align,  # type: ignore[arg-type]
        )

        export_bubbles.append(
            ExportTextBubble(
                id=bubble.id,
                rect=rect,
                text=text,
                style=export_style,
                block_type=bubble.block_type,
                enabled=bubble_enabled,
            )
        )

    paint_path: Optional[Path] = None
    paint_image = getattr(session, "paint_layer_image", None)
    if getattr(session, "paint_layer_path", None):
        paint_path = Path(session.paint_layer_path)
    elif paint_image is not None:
        paint_path = None

    return ExportPageData(
        page_index=session.page_index,
        width=width,
        height=height,
        background_image=session.image_path,
        mask_enabled=bool(getattr(session, "mask_enabled", True)),
        text_enabled=bool(getattr(session, "text_enabled", True)),
        show_sfx=bool(getattr(session, "show_sfx", False)),
        mask_color=mask_color,
        paint_layer_path=paint_path,
        paint_layer_image=paint_image if paint_image is not None else None,
        bubbles=export_bubbles,
    )
