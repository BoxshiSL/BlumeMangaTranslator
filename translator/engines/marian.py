"""Marian/M2M/NLLB translator with optional HF pipeline."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import TranslationRequest, TranslationResult, Translator, TranslatorCapabilities
from translator.mt_api import MtApiError, call_mt_api, translate_with_hf_model


class MarianTranslator(Translator):
    """Offline HuggingFace translator (falls back to HTTP stub if no model is configured)."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id="marian_m2m_nllb",
            name="Marian/M2M/NLLB",
            settings=settings,
            capabilities=capabilities,
        )

    def _translate_request(self, request: TranslationRequest, _container=None) -> TranslationResult:
        text = request.text or ""
        if not text.strip():
            return TranslationResult(translated_text="", metadata=dict(request.metadata))

        model_name = str(self.settings.get("model_name", "") or "").strip()
        try:
            if not model_name:
                raise MtApiError("model_name is not configured")
            translated = translate_with_hf_model(text, model_name, request.src_lang, request.dst_lang)
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
