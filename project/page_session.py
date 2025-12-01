"""Models and helpers describing a single page session (OCR + translation results)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ocr.engine import OcrBlock

# Session format version
SESSION_FORMAT_VERSION = 2


@dataclass
class TextBlock:
    """
    Text block on a manga page (dialog, narration, SFX, etc.).
    """

    id: str
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2) in image coordinates
    original_text: str  # text recognized by OCR
    translated_text: str = ""  # translated text (may be empty)
    block_type: str = "dialog"  # "dialog", "narration", "sfx", "system"
    enabled: bool = True  # whether this block participates in translation/rendering
    orientation: str = "horizontal"  # "horizontal" or "vertical"
    confidence: float = 0.0  # OCR confidence (0..1)
    deleted: bool = False  # logical deletion flag
    manual: bool = False  # created manually by user
    font_size: Optional[int] = None  # optional font size override


@dataclass
class BubbleStyle:
    """Style overrides for a grouped text bubble."""

    font_family: Optional[str] = None
    font_size: Optional[int] = None
    line_spacing: Optional[float] = None
    align: Optional[str] = None  # left, center, right


@dataclass
class PageSession:
    """
    Session describing a single page: image path and its text blocks.
    Used by the UI and persistence layers.
    """

    project_id: str
    page_index: int
    image_path: Path
    original_image_path: Optional[Path] = None

    text_blocks: List[TextBlock] = field(default_factory=list)

    src_lang: str = "ja"
    dst_lang: str = "ru"
    mask_enabled: bool = True
    text_enabled: bool = True
    show_sfx: bool = True
    manually_selected_regions: List[Tuple[int, int, int, int]] = field(default_factory=list)
    paint_layer_path: Optional[Path] = None
    bubble_styles: Dict[str, BubbleStyle] = field(default_factory=dict)

    session_path: Optional[Path] = None  # path to saved session (JSON), if available
    page_width: int = 0
    page_height: int = 0

    def add_block(self, block: TextBlock) -> None:
        """Append a text block to this session."""
        self.text_blocks.append(block)

    def get_block_by_id(self, block_id: str) -> Optional[TextBlock]:
        """Find a text block by its identifier or return None if missing."""
        for block in self.text_blocks:
            if block.id == block_id:
                return block
        return None

    def iter_enabled_blocks(self) -> List[TextBlock]:
        """Return a list of blocks that are marked as enabled."""
        return [block for block in self.text_blocks if block.enabled]

    def __len__(self) -> int:
        """Return the number of text blocks in the session."""
        return len(self.text_blocks)


def infer_orientation(bbox: Tuple[int, int, int, int], text: str) -> str:
    """
    Infer orientation (horizontal/vertical) based on bbox aspect ratio and text.
    """
    x1, y1, x2, y2 = bbox
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    aspect_ratio = height / width

    if aspect_ratio >= 1.5:
        return "vertical"
    return "horizontal"


def infer_block_type(text: str) -> str:
    """
    Heuristic to guess block type based on its content.
    """
    stripped = text.strip()
    if not stripped:
        return "system"

    length = len(stripped)
    space_count = stripped.count(" ")
    exclam_count = stripped.count("!")
    question_count = stripped.count("?")

    if length <= 12 and space_count <= 1:
        if exclam_count + question_count >= 2:
            return "sfx"
        if stripped.isupper() and length >= 3:
            return "sfx"

    if stripped.startswith(("-", "—")):
        return "dialog"
    if any(q in stripped for q in ['"', "«", "»", "<", ">"]):
        return "dialog"
    if space_count >= 2 and (exclam_count + question_count) >= 1:
        return "dialog"

    upper_ratio = sum(ch.isupper() for ch in stripped) / max(1, len(stripped))
    if upper_ratio > 0.7 and space_count <= 3:
        return "system"

    return "narration"


def ocr_blocks_to_text_blocks(
    ocr_blocks: List[OcrBlock],
    *,
    skip_sfx_by_default: bool = True,
) -> List[TextBlock]:
    """Convert OCR blocks into TextBlock instances (without translation)."""
    result: List[TextBlock] = []

    for i, ocr_block in enumerate(ocr_blocks):
        text = ocr_block.text or ""
        bbox = ocr_block.bbox
        confidence = float(ocr_block.confidence)

        orientation = infer_orientation(bbox, text)
        block_type = infer_block_type(text)
        enabled = True
        if block_type == "sfx" and skip_sfx_by_default:
            enabled = False

        block_id = f"b{i}"
        tb = TextBlock(
            id=block_id,
            bbox=bbox,
            original_text=text,
            translated_text="",
            block_type=block_type,
            enabled=enabled,
            orientation=orientation,
            confidence=confidence,
        )
        result.append(tb)

    return result


def text_block_to_dict(block: TextBlock) -> Dict[str, Any]:
    """Serialize TextBlock to a JSON-friendly dict."""
    x1, y1, x2, y2 = block.bbox
    return {
        "id": block.id,
        "bbox": [int(x1), int(y1), int(x2), int(y2)],
        "original_text": block.original_text,
        "translated_text": block.translated_text,
        "block_type": block.block_type,
        "enabled": bool(block.enabled),
        "orientation": block.orientation,
        "confidence": float(block.confidence),
        "deleted": bool(block.deleted),
        "manual": bool(block.manual),
        "font_size": block.font_size,
    }


def text_block_from_dict(data: Dict[str, Any]) -> TextBlock:
    """Deserialize TextBlock from a dict."""
    bbox_list = data.get("bbox", [0, 0, 0, 0])
    if not isinstance(bbox_list, (list, tuple)) or len(bbox_list) != 4:
        bbox_list = [0, 0, 0, 0]
    x1, y1, x2, y2 = (
        int(bbox_list[0]),
        int(bbox_list[1]),
        int(bbox_list[2]),
        int(bbox_list[3]),
    )
    font_size_raw = data.get("font_size")
    return TextBlock(
        id=str(data.get("id", "")),
        bbox=(x1, y1, x2, y2),
        original_text=str(data.get("original_text", "")),
        translated_text=str(data.get("translated_text", "")),
        block_type=str(data.get("block_type", "dialog")),
        enabled=bool(data.get("enabled", True)),
        orientation=str(data.get("orientation", "horizontal")),
        confidence=float(data.get("confidence", 0.0)),
        deleted=bool(data.get("deleted", False)),
        manual=bool(data.get("manual", False)),
        font_size=int(font_size_raw) if font_size_raw is not None else None,
    )


def bubble_style_to_dict(style: BubbleStyle) -> Dict[str, Any]:
    return {
        "font_family": style.font_family,
        "font_size": style.font_size,
        "line_spacing": style.line_spacing,
        "align": style.align,
    }


def bubble_style_from_dict(data: Dict[str, Any]) -> BubbleStyle:
    return BubbleStyle(
        font_family=data.get("font_family"),
        font_size=data.get("font_size"),
        line_spacing=data.get("line_spacing"),
        align=data.get("align"),
    )


def page_session_to_dict(session: PageSession) -> Dict[str, Any]:
    """Serialize PageSession to a JSON-friendly dict."""
    return {
        "version": SESSION_FORMAT_VERSION,
        "project_id": session.project_id,
        "page_index": int(session.page_index),
        "image_path": str(session.image_path),
        "src_lang": session.src_lang,
        "dst_lang": session.dst_lang,
        "mask_enabled": bool(session.mask_enabled),
        "text_enabled": bool(session.text_enabled),
        "show_sfx": bool(session.show_sfx),
        "manually_selected_regions": [
            [int(x1), int(y1), int(x2), int(y2)] for (x1, y1, x2, y2) in session.manually_selected_regions
        ],
        "paint_layer_path": str(session.paint_layer_path) if session.paint_layer_path else None,
        "text_blocks": [text_block_to_dict(b) for b in session.text_blocks],
        "bubble_styles": {bid: bubble_style_to_dict(style) for bid, style in session.bubble_styles.items()},
    }


def page_session_from_dict(data: Dict[str, Any]) -> PageSession:
    """Deserialize PageSession from a dict."""
    _version = int(data.get("version", 1))
    project_id = str(data.get("project_id", ""))
    page_index = int(data.get("page_index", 0))
    image_path_str = str(data.get("image_path", ""))
    image_path = Path(image_path_str) if image_path_str else Path()
    src_lang = str(data.get("src_lang", ""))
    dst_lang = str(data.get("dst_lang", ""))
    mask_enabled = bool(data.get("mask_enabled", True))
    text_enabled = bool(data.get("text_enabled", True))
    show_sfx = bool(data.get("show_sfx", False))
    regions_raw = data.get("manually_selected_regions", []) or []
    manually_selected_regions: List[Tuple[int, int, int, int]] = []
    for r in regions_raw:
        try:
            x1, y1, x2, y2 = r
            manually_selected_regions.append((int(x1), int(y1), int(x2), int(y2)))
        except Exception:
            continue
    paint_layer_path_raw = data.get("paint_layer_path")
    paint_layer_path = Path(paint_layer_path_raw) if paint_layer_path_raw else None
    blocks_data = data.get("text_blocks", []) or []
    text_blocks = [text_block_from_dict(b) for b in blocks_data]
    bubble_styles_raw = data.get("bubble_styles", {}) or {}
    bubble_styles: Dict[str, BubbleStyle] = {}
    for bid, style_data in bubble_styles_raw.items():
        try:
            bubble_styles[str(bid)] = bubble_style_from_dict(style_data or {})
        except Exception:
            continue

    return PageSession(
        project_id=project_id,
        page_index=page_index,
        image_path=image_path,
        text_blocks=text_blocks,
        src_lang=src_lang,
        dst_lang=dst_lang,
        mask_enabled=mask_enabled,
        text_enabled=text_enabled,
        show_sfx=show_sfx,
        manually_selected_regions=manually_selected_regions,
        paint_layer_path=paint_layer_path,
        session_path=None,
        bubble_styles=bubble_styles,
    )


def save_page_session(session: PageSession, path: Path) -> None:
    """
    Persist a page session to a JSON file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = page_session_to_dict(session)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    session.session_path = path


def load_page_session(path: Path) -> PageSession:
    """
    Load a page session from a JSON file.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    session = page_session_from_dict(data)
    session.session_path = path
    return session
