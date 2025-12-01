"""Common translator engine implementations used by registry entries."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import (
    TranslationRequest,
    TranslationResult,
    Translator,
    TranslatorCapabilities,
)
from translator.errors import LimitedModeError
from translator.mt_api import MtApiError, call_mt_api


class HttpApiTranslator(Translator):
    """
    HTTP-based translator that posts prompt data to a configured endpoint.

    The endpoint and api_key are taken from `settings` (per-engine saved state).
    If no endpoint is configured, falls back to a deterministic stub.
    """

    def __init__(
        self,
        engine_id: str,
        display_name: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id=engine_id,
            name=display_name or engine_id,
            capabilities=capabilities,
            settings=settings,
        )

    def _translate_request(
        self,
        request: TranslationRequest,
        _container=None,
    ) -> TranslationResult:
        text = request.text or ""
        if not text.strip():
            return TranslationResult(translated_text="", metadata=dict(request.metadata))

        endpoint = str(self.settings.get("endpoint", "") or "").strip()
        api_key = str(self.settings.get("api_key", "") or "").strip()
        prompt = request.prompt_data or {
            "text": text,
            "src_lang": request.src_lang,
            "dst_lang": request.dst_lang,
        }

        translated = call_mt_api(prompt, engine_id=self.engine_id, api_key=api_key or None, endpoint=endpoint or None)
        return TranslationResult(translated_text=translated, metadata=dict(request.metadata))
