"""Shared enums and helpers for page editing tools."""
from __future__ import annotations

from enum import Enum, auto


class PageTool(Enum):
    """Unified tool selection for page viewers and canvas widgets."""

    NONE = auto()
    BRUSH = auto()
    ERASER = auto()
    EYEDROPPER = auto()
    HAND = auto()


class ActiveLayer(Enum):
    """Editable/renderable layers on the translated page canvas."""

    BACKGROUND = auto()
    MASK = auto()
    PAINT = auto()
    TEXT = auto()
