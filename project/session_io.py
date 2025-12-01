"""Persistence helpers for PageSession objects."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from PySide6.QtGui import QImage

from config import DEFAULT_DST_LANG, DEFAULT_SRC_LANG
from project.page_session import BubbleStyle, PageSession, TextBlock


def _serialize_block(block: TextBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "bbox": list(block.bbox),
        "original_text": block.original_text,
        "translated_text": block.translated_text,
        "block_type": block.block_type,
        "enabled": block.enabled,
        "orientation": block.orientation,
        "confidence": block.confidence,
        "deleted": block.deleted,
        "manual": block.manual,
        "font_size": block.font_size,
    }


def save_page_session(session: PageSession, base_folder: Path) -> None:
    """Persist a PageSession as JSON + optional paint layer PNG."""
    base_folder = Path(base_folder)
    base_folder.mkdir(parents=True, exist_ok=True)

    paint_layer_path: str | None = None
    paint_image = getattr(session, "paint_layer_image", None) or getattr(session, "paint_layer", None)
    if isinstance(paint_image, QImage) and not paint_image.isNull():
        paint_path = base_folder / f"page_{session.page_index:04d}_paint.png"
        paint_image.save(str(paint_path), "PNG")
        paint_layer_path = paint_path.name

    blocks_data = [_serialize_block(b) for b in session.text_blocks]
    regions: List[list[int]] = []
    for region in session.manually_selected_regions:
        try:
            x1, y1, x2, y2 = region
            regions.append([int(x1), int(y1), int(x2), int(y2)])
        except Exception:
            continue

    data = {
        "project_id": session.project_id,
        "page_index": session.page_index,
        "image_path": str(session.image_path),
        "original_image_path": str(session.original_image_path) if session.original_image_path else "",
        "page_width": int(getattr(session, "page_width", 0) or 0),
        "page_height": int(getattr(session, "page_height", 0) or 0),
        "src_lang": session.src_lang,
        "dst_lang": session.dst_lang,
        "mask_enabled": session.mask_enabled,
        "text_enabled": session.text_enabled,
        "show_sfx": session.show_sfx,
        "manually_selected_regions": regions,
        "paint_layer_path": paint_layer_path,
        "text_blocks": blocks_data,
        "bubble_styles": {
            bid: {
                "font_family": style.font_family,
                "font_size": style.font_size,
                "line_spacing": style.line_spacing,
                "align": style.align,
            }
            for bid, style in (session.bubble_styles or {}).items()
        },
    }

    json_path = base_folder / f"page_{session.page_index:04d}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    session.session_path = json_path
    session.paint_layer_path = base_folder / paint_layer_path if paint_layer_path else None


def load_page_session(base_folder: Path, page_index: int) -> PageSession:
    """Load a PageSession from JSON stored in the given folder."""
    base_folder = Path(base_folder)
    json_path = base_folder / f"page_{page_index:04d}.json"
    with json_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    project_id = str(data.get("project_id", ""))
    image_path_raw = data.get("image_path", "")
    image_path = Path(image_path_raw) if image_path_raw else Path()
    original_image_path_raw = data.get("original_image_path", "")
    original_image_path = Path(original_image_path_raw) if original_image_path_raw else None
    page_width = int(data.get("page_width", 0) or 0)
    page_height = int(data.get("page_height", 0) or 0)
    src_lang = data.get("src_lang", DEFAULT_SRC_LANG)
    dst_lang = data.get("dst_lang", DEFAULT_DST_LANG)
    mask_enabled = bool(data.get("mask_enabled", True))
    text_enabled = bool(data.get("text_enabled", True))
    show_sfx = bool(data.get("show_sfx", False))
    regions_raw = data.get("manually_selected_regions", []) or []
    regions: List[tuple[int, int, int, int]] = []
    for region in regions_raw:
        try:
            x1, y1, x2, y2 = region
            regions.append((int(x1), int(y1), int(x2), int(y2)))
        except Exception:
            continue

    paint_layer_rel = data.get("paint_layer_path")
    paint_layer_path = base_folder / paint_layer_rel if paint_layer_rel else None

    blocks: list[TextBlock] = []
    for b in data.get("text_blocks", []):
        bbox_raw = b.get("bbox", [0, 0, 0, 0])
        if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
            bbox_raw = [0, 0, 0, 0]
        bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        block = TextBlock(
            id=str(b.get("id", "")),
            bbox=bbox,
            original_text=b.get("original_text", ""),
            translated_text=b.get("translated_text", ""),
            block_type=b.get("block_type", "dialog"),
            enabled=bool(b.get("enabled", True)),
            orientation=b.get("orientation", "horizontal"),
            confidence=float(b.get("confidence", 1.0)),
            deleted=bool(b.get("deleted", False)),
            manual=bool(b.get("manual", False)),
            font_size=b.get("font_size"),
        )
        blocks.append(block)

    bubble_styles_raw = data.get("bubble_styles", {}) or {}
    bubble_styles: dict[str, BubbleStyle] = {}
    for bid, style in bubble_styles_raw.items():
        bubble_styles[str(bid)] = BubbleStyle(
            font_family=style.get("font_family"),
            font_size=style.get("font_size"),
            line_spacing=style.get("line_spacing"),
            align=style.get("align"),
        )

    session = PageSession(
        project_id=project_id,
        page_index=page_index,
        image_path=image_path,
        text_blocks=blocks,
        src_lang=src_lang,
        dst_lang=dst_lang,
        mask_enabled=mask_enabled,
        text_enabled=text_enabled,
        show_sfx=show_sfx,
        manually_selected_regions=regions,
        paint_layer_path=paint_layer_path,
        session_path=json_path,
        bubble_styles=bubble_styles,
        page_width=page_width,
        page_height=page_height,
        original_image_path=original_image_path,
    )
    return session
