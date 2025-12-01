"""Default configuration for the Blume Manga Translator desktop application."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from fonts.loader import load_builtin_fonts

# Application identity
APP_NAME = "Blume Manga Translator"
APP_VERSION = "0.1.0"

# Paths
BASE_PATH = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_PATH / "data"
# Knowledge base lives next to the app, under the data folder
DEFAULT_KNOWLEDGE_BASE_DIR = DEFAULT_DATA_DIR
# Session subfolder inside a project
SESSIONS_SUBDIR = Path(".blume") / "sessions"

# Language defaults
DEFAULT_SRC_LANG = "ja"
# Target language can be changed in title settings
DEFAULT_DST_LANG = "ru"

# Project files
PROJECT_META_FILENAME = "project.yaml"


@dataclass
class AppConfig:
    ui_font_family: Optional[str] = None
    manga_font_family: Optional[str] = None
    sfx_font_family: Optional[str] = None


# Runtime font registry populated at startup.
FONTS_REGISTRY: Dict[str, Dict[str, Any]] = {}
# Backward-compatibility alias for existing imports.
fonts_registry = FONTS_REGISTRY
app_config = AppConfig()

# Preferred bundled font families (expected in resources/fonts).
DEFAULT_UI_FONT_FAMILY = "Inter"
DEFAULT_MANGA_FONT_FAMILY = "Neucha"
DEFAULT_SFX_FONT_FAMILY = "Comfortaa"


def init_fonts() -> None:
    """Load bundled and user fonts into the global registry."""
    FONTS_REGISTRY.clear()
    FONTS_REGISTRY.update(load_builtin_fonts(BASE_PATH))


def has_font_family(family: str) -> bool:
    """Check whether a font family is available in the loaded registry."""
    return bool(family) and family in FONTS_REGISTRY


def pick_default_font(preferred: str, fallback: str = "") -> str:
    """Return the first available font among preferred, fallback, or any loaded family."""
    if has_font_family(preferred):
        return preferred
    if fallback and has_font_family(fallback):
        return fallback
    return next(iter(FONTS_REGISTRY.keys()), "")


def get_data_dir() -> Path:
    """Return the default data directory bundled with the application."""
    return DEFAULT_DATA_DIR


def get_knowledge_base_dir() -> Path:
    """Return the default knowledge base directory."""
    return DEFAULT_KNOWLEDGE_BASE_DIR
