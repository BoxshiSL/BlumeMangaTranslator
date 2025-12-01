"""Project loading and saving utilities with chapter/page detection."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from PySide6 import QtGui

from config import DEFAULT_DST_LANG, DEFAULT_SRC_LANG, PROJECT_META_FILENAME
from knowledge.context_manager import ContextManager
from project.models import PageInfo, TitleProject
from project.resolution_presets import find_closest_preset, get_preset_by_id

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_CHAPTER_RE = re.compile(r"^\d+$")
_PAGE_RE = re.compile(r"^\d+$")
DEFAULT_NORMALIZED_DIR = Path(".normalized")


def _read_image_size(path: Path) -> tuple[int, int]:
    """Return (width, height) for an image or (0, 0) if it cannot be read."""
    try:
        img = QtGui.QImage(str(path))
        if img.isNull():
            return (0, 0)
        return (img.width(), img.height())
    except Exception:
        return (0, 0)


def load_project_meta(folder_path: Path) -> Optional[Dict[str, Any]]:
    """Load project metadata from project.yaml if present."""
    meta_path = folder_path / PROJECT_META_FILENAME
    if not meta_path.is_file():
        return None
    with meta_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_project_meta(project: TitleProject) -> None:
    """Save project metadata to project.yaml in the project folder."""
    meta_path = project.folder_path / PROJECT_META_FILENAME
    if meta_path.is_file():
        try:
            data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}

    data.update(
        {
            "title_id": project.title_id,
            "title_name": project.title_name,
            "original_language": project.original_language,
            "target_language": project.target_language,
            "skip_sfx_by_default": bool(getattr(project, "skip_sfx_by_default", True)),
            "content_type": project.content_type,
            "color_mode": project.color_mode,
            "target_width": int(getattr(project, "target_width", 0) or 0),
            "target_height": int(getattr(project, "target_height", 0) or 0),
            "resolution_preset_id": getattr(project, "resolution_preset_id", "custom") or "custom",
            "normalized_images_dir": str(
                getattr(project, "normalized_images_dir", DEFAULT_NORMALIZED_DIR)
                or DEFAULT_NORMALIZED_DIR
            ),
        }
    )

    meta_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    project.meta_path = meta_path


def _iter_chapter_dirs(title_folder: Path) -> List[Path]:
    """
    Return chapter folders inside a title folder, sorted by numeric name.

    A chapter folder name must consist only of digits.
    """
    chapters: List[Tuple[int, Path]] = []
    for child in title_folder.iterdir():
        if not child.is_dir():
            continue
        if not _CHAPTER_RE.match(child.name):
            continue
        chapters.append((int(child.name), child))
    chapters.sort(key=lambda x: x[0])
    return [p for _, p in chapters]


def _iter_pages_in_chapter(chapter_dir: Path) -> List[Tuple[int, Path]]:
    """
    Return pages inside a chapter directory as (page_number, file_path), sorted by number.
    """
    pages: List[Tuple[int, Path]] = []
    for child in chapter_dir.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stem = child.stem
        if not _PAGE_RE.match(stem):
            continue
        pages.append((int(stem), child))
    pages.sort(key=lambda x: x[0])
    return pages


def open_project_from_folder(folder_path: Path) -> TitleProject:
    """
    Load a title project from the provided folder path.

    Supports two layouts:
    1) Preferred: title folder contains chapter subfolders named with digits, each containing page images.
    2) Legacy: images directly inside the folder (treated as chapter 1).
    """
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    folder_path = folder_path.resolve()
    title_id = folder_path.name

    meta = load_project_meta(folder_path) or {}
    title_name = meta.get("title_name", title_id)

    original_language = meta.get("original_language", DEFAULT_SRC_LANG)
    target_language = meta.get("target_language", DEFAULT_DST_LANG)
    skip_sfx_by_default = bool(meta.get("skip_sfx_by_default", True))
    content_type = meta.get("content_type", "standard")
    color_mode = meta.get("color_mode", "bw")
    target_width = int(meta.get("target_width", 0) or 0)
    target_height = int(meta.get("target_height", 0) or 0)
    resolution_preset_id = meta.get("resolution_preset_id", "custom") or "custom"
    normalized_images_dir_raw = meta.get("normalized_images_dir", ".normalized") or ".normalized"
    normalized_images_dir = (
        Path(normalized_images_dir_raw) if normalized_images_dir_raw else DEFAULT_NORMALIZED_DIR
    )

    pages: List[PageInfo] = []
    chapter_dirs = _iter_chapter_dirs(folder_path)
    index = 0

    if chapter_dirs:
        # Title with chapters
        for chapter_dir in chapter_dirs:
            chapter_number = int(chapter_dir.name)
            for page_num, file_path in _iter_pages_in_chapter(chapter_dir):
                pages.append(
                    PageInfo(
                        index=index,
                        file_path=file_path,
                        chapter_number=chapter_number,
                        page_in_chapter=page_num,
                    )
                )
                index += 1
    else:
        # Legacy: all images directly in the folder
        image_files = sorted(
            [
                p
                for p in folder_path.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            ],
            key=lambda p: p.name,
        )
        page_in_chapter = 0
        for file_path in image_files:
            pages.append(
                PageInfo(
                    index=index,
                    file_path=file_path,
                    chapter_number=1,
                    page_in_chapter=page_in_chapter,
                )
            )
            index += 1
            page_in_chapter += 1

    # Fill missing resolution info from first page or defaults.
    if target_width <= 0 or target_height <= 0:
        first_page_path = pages[0].file_path if pages else None
        guessed_w, guessed_h = (0, 0)
        if first_page_path is not None:
            guessed_w, guessed_h = _read_image_size(first_page_path)
        if guessed_w <= 0 or guessed_h <= 0:
            preset = get_preset_by_id("std_manga")
            if preset:
                guessed_w, guessed_h = preset.width, preset.height
                resolution_preset_id = preset.id
        target_width = guessed_w
        target_height = guessed_h
        if resolution_preset_id == "custom":
            closest = find_closest_preset(target_width, target_height)
            if closest:
                resolution_preset_id = closest.id

    project = TitleProject(
        title_id=meta.get("title_id", title_id),
        title_name=title_name,
        folder_path=folder_path,
        pages=pages,
        original_language=original_language,
        target_language=target_language,
        skip_sfx_by_default=skip_sfx_by_default,
        knowledge=None,
        context_manager=ContextManager(),
        content_type=content_type,
        color_mode=color_mode,
        target_width=target_width,
        target_height=target_height,
        resolution_preset_id=resolution_preset_id,
        normalized_images_dir=normalized_images_dir,
    )
    project.meta_path = (
        folder_path / PROJECT_META_FILENAME
        if (folder_path / PROJECT_META_FILENAME).is_file()
        else None
    )
    return project
