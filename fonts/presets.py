"""Font presets for quick manga-ready setups."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FontPreset:
    id: str
    label: str
    ui_font: str
    manga_font: str
    sfx_font: str


FONT_PRESETS: List[FontPreset] = [
    FontPreset(
        id="classic_manga",
        label="Classic manga",
        ui_font="Inter",
        manga_font="Neucha",
        sfx_font="Comfortaa",
    ),
    FontPreset(
        id="handwritten",
        label="Handwritten",
        ui_font="Inter",
        manga_font="Neucha",
        sfx_font="Neucha",
    ),
    FontPreset(
        id="sfx_heavy",
        label="SFX heavy",
        ui_font="Inter",
        manga_font="Comfortaa",
        sfx_font="Comfortaa",
    ),
]


def detect_preset(ui_font: str, manga_font: str, sfx_font: str) -> Optional[FontPreset]:
    """Return preset that matches the given families, if any."""
    for preset in FONT_PRESETS:
        if preset.ui_font == ui_font and preset.manga_font == manga_font and preset.sfx_font == sfx_font:
            return preset
    return None


def apply_preset(
    preset: FontPreset,
    registry: Dict[str, Dict],
    set_ui: callable,
    set_manga: callable,
    set_sfx: callable,
) -> None:
    """Apply a preset, choosing only families that exist in the registry."""
    if preset.ui_font in registry:
        set_ui(preset.ui_font)
    if preset.manga_font in registry:
        set_manga(preset.manga_font)
    if preset.sfx_font in registry:
        set_sfx(preset.sfx_font)
