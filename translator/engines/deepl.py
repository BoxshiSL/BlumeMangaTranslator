"""DeepL translator calling HTTP endpoint (official or custom)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import TranslationRequest, TranslationResult, Translator, TranslatorCapabilities
from translator.errors import LimitedModeError
from translator.mt_api import call_mt_api, translate_deepl_web
from translator.rate_limiter import get_backoff_state, get_rate_limiter, register_backoff_failure


class DeepLTranslator(Translator):
    """DeepL translator using web endpoint by default, API/endpoint optionally."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id="deepl",
            name="DeepL",
            settings=settings,
            capabilities=capabilities,
        )

    def _translate_request(self, request: TranslationRequest, _container=None) -> TranslationResult:
        text = request.text or ""
        if not text.strip():
            return TranslationResult(translated_text="", metadata=dict(request.metadata))

        endpoint = str(self.settings.get("endpoint", "") or "").strip()
        api_key = str(self.settings.get("api_key", "") or "").strip()
        use_api = bool(self.settings.get("use_api", False))
        prompt = request.prompt_data or {
            "text": text,
            "src_lang": request.src_lang,
            "dst_lang": request.dst_lang,
        }

        if use_api and (endpoint or api_key):
            translated = call_mt_api(prompt, engine_id=self.engine_id, api_key=api_key or None, endpoint=endpoint or None)
        else:
            limiter = get_rate_limiter(self.engine_id)
            backoff = get_backoff_state(self.engine_id)
            limiter.wait_or_raise(len(text), backoff)
            try:
                translated = translate_deepl_web(text, request.src_lang, request.dst_lang)
            except Exception as exc:  # noqa: BLE001
                register_backoff_failure(self.engine_id, getattr(exc, "status_code", None), str(exc))
                raise LimitedModeError(getattr(exc, "status_code", None), str(exc)) from exc

        return TranslationResult(translated_text=translated, metadata=dict(request.metadata))
