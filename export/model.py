"""Data models describing exportable page layers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

LayerKind = Literal["background", "mask", "paint", "text"]
AlignKind = Literal["left", "center", "right"]


@dataclass
class ExportTextStyle:
    font_family: str
    font_size: int
    color: tuple[int, int, int, int]  # RGBA
    align: AlignKind


@dataclass
class ExportTextBubble:
    id: str
    rect: tuple[int, int, int, int]  # x, y, w, h in image coords
    text: str
    style: ExportTextStyle
    block_type: str
    enabled: bool


@dataclass
class ExportPageData:
    page_index: int
    width: int
    height: int
    background_image: Path
    mask_enabled: bool
    text_enabled: bool
    show_sfx: bool
    mask_color: tuple[int, int, int, int]
    paint_layer_path: Optional[Path]
    paint_layer_image: Optional[Any]  # QImage if available
    bubbles: list[ExportTextBubble]
