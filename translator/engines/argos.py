"""Argos Translate implementation with optional local models."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import TranslationRequest, TranslationResult, TranslatorCapabilities, Translator
from translator.mt_api import MtApiError, call_mt_api, translate_with_argos


class ArgosTranslator(Translator):
    """Offline Argos translator (falls back to HTTP stub if models are missing)."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id="argos",
            name="Argos",
            settings=settings,
            capabilities=capabilities,
        )

    def _translate_request(self, request: TranslationRequest, _container=None) -> TranslationResult:
        text = request.text or ""
        if not text.strip():
            return TranslationResult(translated_text="", metadata=dict(request.metadata))

        try:
            translated = translate_with_argos(text, request.src_lang, request.dst_lang)
        except MtApiError:
            endpoint = str(self.settings.get("endpoint", "") or "").strip()
            api_key = str(self.settings.get("api_key", "") or "").strip()
            prompt = request.prompt_data or {
                "text": text,
                "src_lang": request.src_lang,
                "dst_lang": request.dst_lang,
            }
            translated = call_mt_api(prompt, engine_id=self.engine_id, api_key=api_key or None, endpoint=endpoint or None)

        return TranslationResult(translated_text=translated, metadata=dict(request.metadata))
