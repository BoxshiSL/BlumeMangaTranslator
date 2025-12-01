"""Utility helpers for loading and storing user settings in YAML."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml

from config import (
    DEFAULT_MANGA_FONT_FAMILY,
    DEFAULT_SFX_FONT_FAMILY,
    DEFAULT_UI_FONT_FAMILY,
    PROJECT_META_FILENAME,
)

# Global config file placed next to the main sources.
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

# Default shape of the settings tree used across the dialog and runtime checks.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "general": {
        "ui_language": "en",
        "open_last_project": False,
        "autosave_enabled": False,
        "autosave_interval_min": 5,
        "default_resolution_preset": "ask",  # "ask" or preset id
    },
    "ocr": {
        "selected": "",
        "engines": {},
    },
    "translator": {
        "selected": "",
        "engines": {},
    },
    "appearance": {
        "scale": 1.0,
        "theme": "system",
        "fit_to_width": True,
    },
    "fonts": {
        "ui_font_family": DEFAULT_UI_FONT_FAMILY,
        "manga_font_family": DEFAULT_MANGA_FONT_FAMILY,
        "sfx_font_family": DEFAULT_SFX_FONT_FAMILY,
    },
}


def _merge_dicts(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge two dictionaries without mutating the inputs."""
    merged = deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_global_settings() -> Dict[str, Any]:
    """Load global settings from config.yaml (or return defaults)."""
    settings = deepcopy(DEFAULT_SETTINGS)
    if not CONFIG_PATH.is_file():
        return settings
    try:
        raw_data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        settings = _merge_dicts(settings, raw_data)
    except Exception:
        # Keep defaults if the file is malformed.
        pass
    return settings


def save_global_settings(settings: Dict[str, Any]) -> None:
    """Persist settings into the global config.yaml."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_project_settings(project_folder: Path | None) -> Dict[str, Any]:
    """Load settings stored alongside project metadata."""
    if project_folder is None:
        return {}
    meta_path = project_folder / PROJECT_META_FILENAME
    if not meta_path.is_file():
        return {}
    try:
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

    settings: Dict[str, Any] = data.get("settings", {}) or {}
    # Keep backward-compatible keys if they live at the root.
    for key in ("general", "ocr", "translator", "appearance"):
        if key in data and key not in settings:
            settings[key] = data.get(key, {})
    return settings


def save_project_settings(project_folder: Path | None, settings: Dict[str, Any]) -> None:
    """Persist settings into project.yaml while preserving existing metadata."""
    if project_folder is None:
        return
    meta_path = project_folder / PROJECT_META_FILENAME
    if meta_path.is_file():
        try:
            data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}

    data["settings"] = _merge_dicts(data.get("settings", {}), settings)

    for key in ("general", "ocr", "translator", "appearance"):
        if key in settings:
            value = settings[key]
            if isinstance(value, dict):
                data[key] = _merge_dicts(data.get(key, {}), value)
            else:
                data[key] = value

    meta_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_effective_settings(project_folder: Path | None) -> Dict[str, Any]:
    """Return global settings merged with project-level overrides (if any)."""
    global_settings = load_global_settings()
    project_settings = load_project_settings(project_folder)
    if not project_settings:
        return global_settings
    return _merge_dicts(global_settings, project_settings)
