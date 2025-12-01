"""
Загрузка базы знаний тайтла из YAML-файлов (meta, characters, glossary, style).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from knowledge.models import Character, StyleConfig, Term, TitleKnowledge, TitleMeta

_cache: Dict[tuple[str, Path], TitleKnowledge] = {}


def load_yaml(path: Path) -> dict:
    """
    Загружает YAML-файл и возвращает данные в виде dict.
    """
    if not path.is_file():
        raise FileNotFoundError(f"YAML file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse YAML file {path}: {exc}") from exc
    return data if data is not None else {}


def load_meta(base_dir: Path, title_id: str) -> TitleMeta:
    folder = base_dir / title_id
    meta_path = folder / "meta.yaml"
    meta_data = load_yaml(meta_path)
    return TitleMeta(
        id=meta_data.get("id", title_id),
        display_name=meta_data.get("display_name", title_id),
        original_language=meta_data.get("original_language", ""),
        target_language=meta_data.get("target_language", ""),
        editor_preferences=meta_data.get("editor_preferences"),
        description=meta_data.get("description"),
        notes=meta_data.get("notes"),
    )


def load_characters(base_dir: Path, title_id: str) -> List[Character]:
    chars_path = base_dir / title_id / "characters.yaml"
    if not chars_path.is_file():
        return []
    data = load_yaml(chars_path)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"characters.yaml must contain a list, got: {type(data)}")

    characters: List[Character] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("Each character entry must be a mapping/dict.")
        characters.append(
            Character(
                id=entry.get("id", ""),
                original_names=entry.get("original_names", []) or [],
                display_name=entry.get("display_name", ""),
                gender=entry.get("gender"),
                role=entry.get("role"),
                pronouns=entry.get("pronouns"),
                speech_style=entry.get("speech_style"),
                notes=entry.get("notes"),
            )
        )
    return characters


def load_terms(base_dir: Path, title_id: str) -> List[Term]:
    terms_path = base_dir / title_id / "glossary.yaml"
    if not terms_path.is_file():
        return []

    data = load_yaml(terms_path)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"glossary.yaml must contain a list, got: {type(data)}")

    terms: List[Term] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("Each glossary entry must be a mapping/dict.")
        terms.append(
            Term(
                source=entry.get("source", ""),
                target=entry.get("target", ""),
                term_type=entry.get("term_type"),
                notes=entry.get("notes"),
                tags=entry.get("tags", []) or [],
            )
        )
    return terms


def load_style(base_dir: Path, title_id: str) -> Optional[StyleConfig]:
    style_path = base_dir / title_id / "style.yaml"
    if not style_path.is_file():
        return None
    data = load_yaml(style_path)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"style.yaml must contain a mapping/dict, got: {type(data)}")
    return StyleConfig(
        tone=data.get("tone"),
        honorifics_policy=data.get("honorifics_policy"),
        sfx_policy=data.get("sfx_policy"),
        punctuation_style=data.get("punctuation_style"),
        casing_style=data.get("casing_style"),
        extra=data.get("extra", {}) or {},
    )


def load_title_knowledge(title_id: str, base_dir: Path) -> TitleKnowledge:
    """
    Загружает полную базу знаний для тайтла (meta, characters, terms, style)
    и возвращает TitleKnowledge.
    """
    key = (title_id, base_dir.resolve())
    if key in _cache:
        return _cache[key]

    meta = load_meta(base_dir, title_id)
    characters = load_characters(base_dir, title_id)
    terms = load_terms(base_dir, title_id)
    style = load_style(base_dir, title_id)

    knowledge = TitleKnowledge(meta=meta, characters=characters, terms=terms, style=style)
    _cache[key] = knowledge
    return knowledge
