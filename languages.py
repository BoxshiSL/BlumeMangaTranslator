"""Shared language utilities for Blume Manga Translator (OCR, translation, UI)."""
from typing import Optional

# Primary language registry used across the app.
SUPPORTED_LANGS: dict[str, dict[str, str]] = {
    "ja": {"name": "Japanese", "native_name": "日本語", "script": "CJK"},
    "ko": {"name": "Korean", "native_name": "한국어", "script": "CJK"},
    "zh": {"name": "Chinese (simplified)", "native_name": "中文", "script": "CJK"},
    "en": {"name": "English", "native_name": "English", "script": "Latin"},
    "es": {"name": "Spanish", "native_name": "Español", "script": "Latin"},
    "it": {"name": "Italian", "native_name": "Italiano", "script": "Latin"},
    "de": {"name": "German", "native_name": "Deutsch", "script": "Latin"},
    "ru": {"name": "Russian", "native_name": "Русский", "script": "Cyrillic"},
}


def is_supported_lang(code: Optional[str]) -> bool:
    """Return True if the provided language code is registered as supported."""
    if not code:
        return False
    return code in SUPPORTED_LANGS


def get_lang_display_name(code: str) -> str:
    """Return human-readable language name or a fallback if unknown."""
    if code in SUPPORTED_LANGS:
        return SUPPORTED_LANGS[code]["name"]
    return f"Unknown ({code})" if code else "Unknown"


# Friendly alias used by UI code.
def get_display_name(code: str) -> str:
    """Return display name for language code."""
    return get_lang_display_name(code)


def get_ocr_langs_for_src(src_lang: str) -> list[str]:
    """
    Return OCR language list for the given source language.

    EasyOCR has strict combos for some languages (e.g., ch_sim must pair with en).
    """
    src_lang = (src_lang or "").lower()

    if src_lang == "ja":
        return ["ja", "en"]
    if src_lang == "ko":
        return ["ko", "en"]
    if src_lang in ("zh", "zh_cn", "zh-hans", "ch_sim"):
        return ["ch_sim", "en"]
    if src_lang in {"en", "es", "it", "de"}:
        return ["en"]
    return ["en"]


def get_default_target_for_src(src_lang: str) -> str:
    """
    Suggest a default translation target for the given source language.
    """
    if src_lang in {"ja", "ko", "zh"}:
        return "ru"
    if src_lang == "en":
        return "ru"
    return "en"
