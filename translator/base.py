"""Core translator abstractions and lightweight failover primitives."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from knowledge.context_manager import ContextEntry
from translator.errors import LimitedModeError


class TranslationError(Exception):
    """Raised when translation fails or no containers are available."""


@dataclass
class TranslatorCapabilities:
    """Describes translator limits and batching capabilities."""

    supports_batch: bool = False
    max_batch_size: int = 1
    max_chars_per_request: Optional[int] = None
    max_chars_total: Optional[int] = None
    context_window: int = 10
    attempt_delay_ms: int = 600


@dataclass
class TranslationRequest:
    """Single translation unit prepared by TranslationService."""

    text: str
    src_lang: str
    dst_lang: str
    prompt_data: Optional[Dict[str, Any]] = None
    context: Sequence[ContextEntry] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TranslationResult:
    """Normalized translation output returned by translators."""

    translated_text: str
    raw_response: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TranslatorContainer:
    """
    Minimal container describing a single translator backend instance.

    Mirrors the idea of Translumo's containers: keeps track of failures,
    blocking window, and last use time, so translators can rotate between
    primary/backup backends (proxies, API tokens, etc.).
    """

    name: str
    is_primary: bool = False
    block_timeout_sec: float = 60.0
    max_failures: int = 3
    fail_uses: int = 0
    blocked_until: float | None = None
    last_used_at: float = field(default_factory=lambda: 0.0)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        """Return True if this container is temporarily blocked."""
        return self.blocked_until is not None and self.blocked_until > time.monotonic()

    def mark_success(self) -> None:
        """Mark container as used successfully and reset failure counters."""
        self.fail_uses = 0
        self.blocked_until = None
        self.last_used_at = time.monotonic()

    def mark_failure(self) -> None:
        """Increment failure counter and block if the limit is exceeded."""
        self.fail_uses += 1
        self.last_used_at = time.monotonic()
        if self.fail_uses >= self.max_failures:
            self.blocked_until = time.monotonic() + self.block_timeout_sec

    def restore(self) -> None:
        """Unblock container and reset counters."""
        self.fail_uses = 0
        self.blocked_until = None


class Translator:
    """Abstract translator with simple failover logic over containers."""

    def __init__(
        self,
        engine_id: str,
        name: Optional[str] = None,
        capabilities: Optional[TranslatorCapabilities] = None,
        settings: Optional[Dict[str, Any]] = None,
        containers: Optional[List[TranslatorContainer]] = None,
    ) -> None:
        self.engine_id = engine_id
        self.name = name or engine_id
        self.capabilities = capabilities or TranslatorCapabilities()
        self.settings = settings or {}
        self._containers = containers or [TranslatorContainer(name=self.name, is_primary=True)]

    def translate_text(self, request: TranslationRequest) -> TranslationResult:
        """Translate a single request."""
        return self.translate_batch([request])[0]

    def translate_batch(self, requests: Sequence[TranslationRequest]) -> List[TranslationResult]:
        """
        Translate a batch sequentially with container failover.

        Translators that support native batching should override this method.
        """
        results: List[TranslationResult] = []
        for req in requests:
            results.append(self._translate_with_failover(req))
        return results

    # -------------------- internals --------------------
    def _translate_with_failover(self, request: TranslationRequest) -> TranslationResult:
        """Execute a single request with basic container rotation on failure."""
        last_error: Exception | None = None
        container = self._get_container(prefer_primary=True, last_used=None)
        attempts = 0
        max_attempts = max(len(self._containers), 1) * 2

        while attempts < max_attempts:
            attempts += 1
            if container is None:
                break
            try:
                result = self._translate_request(request, container)
            except LimitedModeError:
                container.mark_failure()
                raise
            except TranslationError as exc:
                last_error = exc
                container.mark_failure()
                container = self._get_container(prefer_primary=False, last_used=container)
                if self.capabilities.attempt_delay_ms > 0:
                    time.sleep(self.capabilities.attempt_delay_ms / 1000.0)
                continue
            except Exception as exc:  # noqa: BLE001
                container.mark_failure()
                raise TranslationError(str(exc)) from exc
            else:
                container.mark_success()
                return result

        if last_error is not None:
            raise TranslationError(str(last_error)) from last_error
        raise TranslationError("No available translator containers")

    def _get_container(
        self,
        prefer_primary: bool,
        last_used: Optional[TranslatorContainer],
    ) -> Optional[TranslatorContainer]:
        """
        Select the next available container.

        Chooses the least recently used, non-blocked container; when all are blocked
        and prefer_primary is True, attempts to restore the primary container.
        """
        available = [c for c in self._containers if not c.is_blocked]
        if not available and prefer_primary:
            primary = self._primary_container()
            if primary:
                primary.restore()
                available = [primary]
        if not available:
            return None

        available = sorted(available, key=lambda c: (c is last_used, c.last_used_at))
        chosen = available[0]
        chosen.last_used_at = time.monotonic()
        return chosen

    def _primary_container(self) -> Optional[TranslatorContainer]:
        """Return the primary container if present."""
        for container in self._containers:
            if container.is_primary:
                return container
        return self._containers[0] if self._containers else None

    def _translate_request(
        self,
        request: TranslationRequest,
        container: Optional[TranslatorContainer] = None,
    ) -> TranslationResult:
        """Implement translation for a single request."""
        raise NotImplementedError
