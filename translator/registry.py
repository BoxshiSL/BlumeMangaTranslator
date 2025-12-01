"""Translator registry and factory inspired by Translumo's translator layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.engines_registry import EngineConfig, TRANSLATOR_ENGINES, normalize_engine_id
from translator.base import Translator, TranslatorCapabilities
from translator.engines import (
    ArgosTranslator,
    AzureTranslator,
    DeepLTranslator,
    GoogleTranslator,
    MarianTranslator,
    OpenAITranslator,
    YandexTranslator,
)

BuilderType = Callable[[Dict[str, Any], TranslatorCapabilities], Translator]


@dataclass(frozen=True)
class TranslatorRegistryEntry:
    """Descriptor tying EngineConfig to a concrete translator builder and limits."""

    config: EngineConfig
    builder: BuilderType
    capabilities: TranslatorCapabilities


def normalize_translator_id(engine_id: str) -> str:
    """Normalize engine id accounting for legacy aliases."""
    return normalize_engine_id(engine_id)


def _default_caps() -> TranslatorCapabilities:
    return TranslatorCapabilities()


# Capabilities tuned for queueing/batching logic; can be adjusted per engine.
_CAPABILITIES: Dict[str, TranslatorCapabilities] = {
    "deepl": TranslatorCapabilities(
        supports_batch=True,
        max_batch_size=50,
        max_chars_per_request=4500,
        context_window=10,
        attempt_delay_ms=700,
    ),
    "google_translate": TranslatorCapabilities(
        supports_batch=True,
        max_batch_size=20,
        max_chars_per_request=4000,
        context_window=8,
        attempt_delay_ms=500,
    ),
    "yandex_translate": TranslatorCapabilities(
        supports_batch=True,
        max_batch_size=10,
        max_chars_per_request=4500,
        context_window=8,
        attempt_delay_ms=800,
    ),
    "azure_translate": TranslatorCapabilities(
        supports_batch=True,
        max_batch_size=25,
        max_chars_per_request=9000,
        context_window=12,
        attempt_delay_ms=700,
    ),
    "openai_translate": TranslatorCapabilities(
        supports_batch=False,
        max_batch_size=1,
        max_chars_per_request=2500,
        context_window=16,
        attempt_delay_ms=800,
    ),
    "argos": TranslatorCapabilities(
        supports_batch=False,
        max_batch_size=1,
        max_chars_per_request=1200,
        context_window=6,
        attempt_delay_ms=500,
    ),
    "marian_m2m_nllb": TranslatorCapabilities(
        supports_batch=True,
        max_batch_size=8,
        max_chars_per_request=2200,
        context_window=8,
        attempt_delay_ms=600,
    ),
}

_BUILDERS: Dict[str, BuilderType] = {
    "deepl": lambda settings, caps: DeepLTranslator(settings=settings, capabilities=caps),
    "google_translate": lambda settings, caps: GoogleTranslator(settings=settings, capabilities=caps),
    "yandex_translate": lambda settings, caps: YandexTranslator(settings=settings, capabilities=caps),
    "azure_translate": lambda settings, caps: AzureTranslator(settings=settings, capabilities=caps),
    "openai_translate": lambda settings, caps: OpenAITranslator(settings=settings, capabilities=caps),
    "argos": lambda settings, caps: ArgosTranslator(settings=settings, capabilities=caps),
    "marian_m2m_nllb": lambda settings, caps: MarianTranslator(settings=settings, capabilities=caps),
}

_ENGINE_CONFIGS: Dict[str, EngineConfig] = {cfg.id: cfg for cfg in TRANSLATOR_ENGINES}

_ENTRIES: Dict[str, TranslatorRegistryEntry] = {}
for engine_id, cfg in _ENGINE_CONFIGS.items():
    caps = _CAPABILITIES.get(engine_id, _default_caps())
    builder = _BUILDERS.get(engine_id)
    if builder is None:
        # Fallback to a simple echo translator if builder is missing.
        builder = lambda settings, caps, _eid=engine_id: GoogleTranslator(  # type: ignore[misc]
            settings=settings, capabilities=caps
        )
    _ENTRIES[engine_id] = TranslatorRegistryEntry(config=cfg, builder=builder, capabilities=caps)


def list_translator_engines() -> List[EngineConfig]:
    """Return all registered translator engine configs."""
    return list(_ENGINE_CONFIGS.values())


def get_translator_engine_config(engine_id: str) -> Optional[EngineConfig]:
    """Return EngineConfig for the given translator id, if registered."""
    normalized = normalize_translator_id(engine_id)
    return _ENGINE_CONFIGS.get(normalized)


def get_translator_capabilities(engine_id: str) -> TranslatorCapabilities:
    """Return capabilities for batching/context limits of the selected engine."""
    normalized = normalize_translator_id(engine_id)
    return _CAPABILITIES.get(normalized, _default_caps())


def create_translator(
    engine_id: str,
    engine_state: Optional[Dict[str, Any]] = None,
) -> Translator:
    """Instantiate a translator by id using registry metadata."""
    normalized = normalize_translator_id(engine_id)
    if normalized not in _ENTRIES:
        raise ValueError(f"Translator '{engine_id}' is not registered")

    entry = _ENTRIES[normalized]
    settings = engine_state or {}
    caps = TranslatorCapabilities(**vars(entry.capabilities))
    return entry.builder(settings, caps)
