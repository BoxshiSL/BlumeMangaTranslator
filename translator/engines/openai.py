"""OpenAI/LLM translator via HTTP endpoint."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import TranslatorCapabilities
from translator.engines.common import HttpApiTranslator


class OpenAITranslator(HttpApiTranslator):
    """LLM-based translator via configured endpoint/API key."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id="openai_translate",
            display_name="OpenAI LLM",
            settings=settings,
            capabilities=capabilities,
        )
