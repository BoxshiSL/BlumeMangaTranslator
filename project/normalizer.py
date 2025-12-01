"""Helpers for normalizing page images to a consistent resolution."""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from PySide6 import QtCore, QtGui

from project.models import PageInfo, TitleProject

DEFAULT_NORMALIZED_DIR = Path(".normalized")


def compute_scale_and_offsets(src_w: int, src_h: int, target_w: int, target_h: int) -> tuple[float, int, int, int, int]:
    """Return scale and offsets to fit src into target while preserving aspect."""
    if src_w <= 0 or src_h <= 0 or target_w <= 0 or target_h <= 0:
        return (1.0, 0, 0, src_w, src_h)
    scale = min(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    return (scale, offset_x, offset_y, new_w, new_h)


def normalize_page_image(src_path: Path, dst_path: Path, target_width: int, target_height: int) -> None:
    """Resize and letterbox a page image into the target resolution as PNG."""
    if target_width <= 0 or target_height <= 0:
        raise ValueError("Target width/height must be positive for normalization")

    image = QtGui.QImage(str(src_path))
    if image.isNull():
        raise FileNotFoundError(f"Failed to load source image: {src_path}")

    scale, offset_x, offset_y, new_w, new_h = compute_scale_and_offsets(image.width(), image.height(), target_width, target_height)
    scaled = image.scaled(new_w, new_h, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)

    canvas = QtGui.QImage(target_width, target_height, QtGui.QImage.Format_RGB32)
    canvas.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(canvas)
    painter.drawImage(offset_x, offset_y, scaled)
    painter.end()

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(dst_path), "PNG")


def _normalized_relative_path(project: TitleProject, page_info: PageInfo) -> Path:
    base = project.normalized_images_dir if getattr(project, "normalized_images_dir", None) else DEFAULT_NORMALIZED_DIR
    try:
        rel = page_info.file_path.relative_to(project.folder_path)
    except Exception:
        rel = page_info.file_path.name
    return Path(base) / Path(rel).with_suffix(".png")


def get_normalized_image_path(project: TitleProject, page_info: PageInfo) -> Path:
    """Return path to normalized image for a page, creating/updating if needed."""
    target_w = getattr(project, "target_width", 0) or 0
    target_h = getattr(project, "target_height", 0) or 0
    if target_w <= 0 or target_h <= 0:
        # fallback to current image size
        img = QtGui.QImage(str(page_info.file_path))
        target_w, target_h = img.width(), img.height()
        project.target_width = target_w
        project.target_height = target_h

    normalized_rel = _normalized_relative_path(project, page_info)
    dst_path = project.folder_path / normalized_rel
    src_path = page_info.file_path

    needs_regen = not dst_path.is_file()
    if not needs_regen:
        existing = QtGui.QImage(str(dst_path))
        if existing.isNull() or existing.width() != target_w or existing.height() != target_h:
            needs_regen = True
        else:
            try:
                needs_regen = src_path.stat().st_mtime > dst_path.stat().st_mtime
            except Exception:
                needs_regen = False

    if needs_regen:
        normalize_page_image(src_path, dst_path, target_w, target_h)

    page_info.normalized_path = dst_path
    return dst_path


def compute_resolution_stats(pages: Iterable[PageInfo]) -> Dict[str, Any]:
    """Collect simple width/height stats for a list of pages."""
    widths: list[int] = []
    heights: list[int] = []
    for page in pages:
        img = QtGui.QImage(str(page.file_path))
        if img.isNull():
            continue
        widths.append(img.width())
        heights.append(img.height())
    if not widths or not heights:
        return {"count": 0}

    def _median(values: list[int]) -> int:
        return int(statistics.median(values)) if values else 0

    return {
        "count": len(widths),
        "min_width": min(widths),
        "max_width": max(widths),
        "min_height": min(heights),
        "max_height": max(heights),
        "median_width": _median(widths),
        "median_height": _median(heights),
        "avg_width": int(statistics.mean(widths)),
        "avg_height": int(statistics.mean(heights)),
    }


def remap_bbox_to_target(bbox: tuple[int, int, int, int], src_size: tuple[int, int], target_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Map bbox from original coordinates into normalized target space."""
    src_w, src_h = src_size
    tgt_w, tgt_h = target_size
    scale, offset_x, offset_y, _, _ = compute_scale_and_offsets(src_w, src_h, tgt_w, tgt_h)
    x1, y1, x2, y2 = bbox
    nx1 = int(round(x1 * scale)) + offset_x
    ny1 = int(round(y1 * scale)) + offset_y
    nx2 = int(round(x2 * scale)) + offset_x
    ny2 = int(round(y2 * scale)) + offset_y
    return (nx1, ny1, nx2, ny2)


def remap_region_list(regions: Iterable[tuple[int, int, int, int]], src_size: tuple[int, int], target_size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    """Remap regions using the same strategy as normalization."""
    return [remap_bbox_to_target(region, src_size, target_size) for region in regions]


def migrate_session_geometry(
    session: Any,
    src_size: tuple[int, int],
    target_size: tuple[int, int],
) -> bool:
    """
    Rescale session bboxes/regions into the target normalized size.

    Returns True if geometry was updated.
    """
    src_w, src_h = src_size
    tgt_w, tgt_h = target_size
    if src_w <= 0 or src_h <= 0 or tgt_w <= 0 or tgt_h <= 0:
        return False
    if src_w == tgt_w and src_h == tgt_h:
        session.page_width = tgt_w
        session.page_height = tgt_h
        return False

    changed = False
    for block in session.text_blocks:
        block.bbox = remap_bbox_to_target(block.bbox, src_size, target_size)
        changed = True

    regions = getattr(session, "manually_selected_regions", [])
    if regions:
        session.manually_selected_regions = remap_region_list(regions, src_size, target_size)
        changed = True

    paint_image = getattr(session, "paint_layer_image", None)
    if paint_image is not None and hasattr(paint_image, "isNull") and not paint_image.isNull():
        session.paint_layer_image = paint_image.scaled(
            tgt_w,
            tgt_h,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        changed = True

    session.page_width = tgt_w
    session.page_height = tgt_h
    return changed
