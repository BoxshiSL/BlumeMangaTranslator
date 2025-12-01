"""
Модели базы знаний для конкретного тайтла (манги/манхвы).

Содержит dataclass-ы:
- TitleMeta: метаданные тайтла;
- Character: персонажи;
- Term: термины глоссария;
- StyleConfig: настройки стиля перевода;
- TitleKnowledge: объединённая модель базы знаний.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TitleMeta:
    """
    Общие метаданные тайтла (манги/манхвы/комикса).
    """

    id: str
    display_name: str
    original_language: str
    target_language: str
    editor_preferences: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Character:
    """
    Описание персонажа тайтла.
    """

    id: str
    original_names: List[str]
    display_name: str

    gender: Optional[str] = None
    role: Optional[str] = None
    pronouns: Optional[List[str]] = None
    speech_style: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Term:
    """
    Термин/устойчивое выражение для глоссария тайтла.
    """

    source: str
    target: str
    term_type: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class StyleConfig:
    """
    Настройки стиля перевода для конкретного тайтла.
    """

    tone: Optional[str] = None
    honorifics_policy: Optional[str] = None
    sfx_policy: Optional[str] = None
    punctuation_style: Optional[str] = None
    casing_style: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TitleKnowledge:
    """
    Полная база знаний для одного тайтла.
    """

    meta: TitleMeta
    characters: List[Character] = field(default_factory=list)
    terms: List[Term] = field(default_factory=list)
    style: Optional[StyleConfig] = None
