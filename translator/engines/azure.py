"""Azure Translate via HTTP endpoint."""
from __future__ import annotations

from typing import Any, Dict, Optional

from translator.base import TranslatorCapabilities
from translator.engines.common import HttpApiTranslator


class AzureTranslator(HttpApiTranslator):
    """Cloud Azure translator via configured endpoint/API key."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
    ) -> None:
        super().__init__(
            engine_id="azure_translate",
            display_name="Azure Translate",
            settings=settings,
            capabilities=capabilities,
        )
