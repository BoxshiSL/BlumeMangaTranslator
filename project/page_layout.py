"""Helpers for grouping text blocks into renderable bubbles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from PySide6 import QtCore

from project.page_session import TextBlock


@dataclass
class Bubble:
    id: str
    text_block_ids: list[str]
    bbox: QtCore.QRectF
    block_type: str


MERGE_MARGIN = 16.0


def _bbox_to_rect(bbox: tuple[int, int, int, int]) -> QtCore.QRectF:
    """Convert (x1, y1, x2, y2) bbox to QRectF."""
    x1, y1, x2, y2 = bbox
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    return QtCore.QRectF(float(x1), float(y1), float(w), float(h))


def group_blocks_into_bubbles(text_blocks: Iterable[TextBlock]) -> List[Bubble]:
    """
    Group nearby/intersecting text blocks into bubbles for rendering.
    """
    blocks = list(text_blocks)
    if not blocks:
        return []

    blocks_sorted = sorted(blocks, key=lambda b: b.bbox[1])
    working: list[tuple[list[str], QtCore.QRectF, str]] = []

    for block in blocks_sorted:
        rect = _bbox_to_rect(block.bbox)
        merged = False
        for bubble_blocks, bubble_rect, bubble_type in working:
            expanded = bubble_rect.adjusted(-MERGE_MARGIN, -MERGE_MARGIN, MERGE_MARGIN, MERGE_MARGIN)
            if expanded.intersects(rect) or expanded.contains(rect):
                bubble_blocks.append(block.id)
                left = min(bubble_rect.left(), rect.left())
                top = min(bubble_rect.top(), rect.top())
                right = max(bubble_rect.right(), rect.right())
                bottom = max(bubble_rect.bottom(), rect.bottom())
                bubble_rect.setRect(left, top, right - left, bottom - top)
                merged = True
                break
        if not merged:
            working.append(([block.id], QtCore.QRectF(rect), block.block_type))

    bubbles: list[Bubble] = []
    for idx, (ids, rect, btype) in enumerate(working):
        bubble_id = f"bubble_{idx}"
        bubbles.append(Bubble(id=bubble_id, text_block_ids=ids, bbox=QtCore.QRectF(rect), block_type=btype))

    return bubbles
