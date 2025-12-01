"""Fixed resolution presets used across the application."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class ResolutionPreset:
    """Predefined resolution with a user-facing label and description."""

    id: str
    label: str
    width: int
    height: int
    description: str


PRESETS: list[ResolutionPreset] = [
    ResolutionPreset(
        id="std_manga",
        label="Standard digital manga",
        width=1600,
        height=2400,
        description="Balanced quality/performance for most digital manga pages.",
    ),
    ResolutionPreset(
        id="hires_manga",
        label="High-res manga",
        width=2400,
        height=3600,
        description="Higher resolution for detailed scans or when extra fidelity is needed.",
    ),
    ResolutionPreset(
        id="webtoon_vertical",
        label="Webtoon vertical strip",
        width=1080,
        height=4096,
        description="Tall vertical slices typical for webtoons or scrolling releases.",
    ),
]


def get_preset_by_id(preset_id: str | None) -> Optional[ResolutionPreset]:
    """Return preset by id or None if not found."""
    if not preset_id:
        return None
    normalized = preset_id.strip().lower()
    for preset in PRESETS:
        if preset.id == normalized:
            return preset
    return None


def find_closest_preset(width: int, height: int) -> Optional[ResolutionPreset]:
    """
    Return the preset that best matches the provided size by minimal absolute delta.
    """
    if width <= 0 or height <= 0:
        return None
    best: Optional[ResolutionPreset] = None
    best_score = float("inf")
    for preset in PRESETS:
        dw = abs(preset.width - width)
        dh = abs(preset.height - height)
        score = dw + dh
        if score < best_score:
            best_score = score
            best = preset
    return best


def iter_preset_options(include_custom: bool = True) -> Iterable[tuple[str, str]]:
    """
    Yield (id, label) pairs for UI combo boxes.
    """
    if include_custom:
        yield ("custom", "Custom")
    for preset in PRESETS:
        yield (preset.id, preset.label)
