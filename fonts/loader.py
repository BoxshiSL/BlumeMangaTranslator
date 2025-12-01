from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtGui import QFontDatabase


def _iter_font_files(fonts_dir: Path) -> list[Path]:
    """
    Return a list of font files (.ttf / .otf) inside the given directory.
    Missing directories are treated as empty.
    """
    if not fonts_dir.exists():
        return []

    font_paths: list[Path] = []
    for path in fonts_dir.rglob("*"):
        if path.suffix.lower() in {".ttf", ".otf"}:
            font_paths.append(path)
    return font_paths


def load_builtin_fonts(base_path: Path) -> dict[str, dict[str, Any]]:
    """
    Load bundled and user fonts into the application registry.
    Returns a dict: {family: {"file": Path, "font_id": int}}.
    """
    fonts_root = base_path / "resources" / "fonts"
    user_fonts_root = base_path / "resources" / "user_fonts"
    fonts_root.mkdir(parents=True, exist_ok=True)
    user_fonts_root.mkdir(parents=True, exist_ok=True)

    registry: dict[str, dict[str, Any]] = {}
    font_files: list[Path] = []
    font_files.extend(_iter_font_files(fonts_root))
    font_files.extend(_iter_font_files(user_fonts_root))

    for font_path in font_files:
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            continue

        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            continue

        family = families[0]
        # Keep the first file we encounter for the same family to stay deterministic.
        if family in registry:
            continue

        registry[family] = {
            "file": font_path,
            "font_id": font_id,
        }

    return registry


def has_font_family(family: str, registry: dict[str, Any]) -> bool:
    """Return True if the given family exists in the provided registry."""
    return bool(family) and family in registry
