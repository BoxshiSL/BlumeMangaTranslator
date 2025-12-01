"""Simple per-engine rate limiting and backoff for limited (no-API) modes."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class RateLimitConfig:
    min_interval_sec: float
    max_calls_per_min: int
    max_chars_per_request: int


@dataclass
class BackoffState:
    penalty_delay_sec: float = 0.0
    last_error_ts: float = 0.0
    slow_mode: bool = False
    slow_since: float = 0.0
    notified: bool = False


class RateLimiter:
    def __init__(self, cfg: RateLimitConfig) -> None:
        self.cfg = cfg
        self._last_call_ts: float = 0.0
        self._window_start_ts: float = 0.0
        self._window_calls: int = 0

    def wait_or_raise(self, text_length: int, backoff: BackoffState | None = None) -> None:
        if text_length > self.cfg.max_chars_per_request:
            raise ValueError("Text too long for limited mode")

        now = time.monotonic()
        slow_mode = bool(backoff and backoff.slow_mode)
        if backoff and backoff.slow_mode and backoff.last_error_ts:
            if now - backoff.last_error_ts > 300:
                backoff.slow_mode = False
                backoff.penalty_delay_sec = 0.0
                backoff.slow_since = 0.0
                backoff.notified = False
                slow_mode = False

        if not slow_mode:
            self._last_call_ts = now
            return

        if self.cfg.max_calls_per_min > 0:
            if self._window_start_ts <= 0 or now - self._window_start_ts >= 60:
                self._window_start_ts = now
                self._window_calls = 0
            elif self._window_calls >= self.cfg.max_calls_per_min:
                wait_for = max(0.0, 60 - (now - self._window_start_ts))
                if wait_for > 0:
                    time.sleep(wait_for)
                    now = time.monotonic()
                self._window_start_ts = time.monotonic()
                self._window_calls = 0

        since_last = now - self._last_call_ts
        if since_last < self.cfg.min_interval_sec:
            time.sleep(self.cfg.min_interval_sec - since_last)

        if backoff and backoff.penalty_delay_sec > 0:
            time.sleep(backoff.penalty_delay_sec)

        self._last_call_ts = time.monotonic()
        self._window_calls += 1


DEFAULT_LIMITS: Dict[str, RateLimitConfig] = {
    "deepl": RateLimitConfig(min_interval_sec=4.0, max_calls_per_min=10, max_chars_per_request=800),
    "google_translate": RateLimitConfig(min_interval_sec=3.5, max_calls_per_min=12, max_chars_per_request=800),
    "yandex_translate": RateLimitConfig(min_interval_sec=4.0, max_calls_per_min=10, max_chars_per_request=800),
}

_LIMITERS: Dict[str, RateLimiter] = {}
_BACKOFFS: Dict[str, BackoffState] = {}


def get_rate_limiter(engine_id: str) -> RateLimiter:
    if engine_id not in _LIMITERS:
        cfg = DEFAULT_LIMITS.get(engine_id)
        if cfg is None:
            cfg = RateLimitConfig(min_interval_sec=3.0, max_calls_per_min=10, max_chars_per_request=800)
        _LIMITERS[engine_id] = RateLimiter(cfg)
    return _LIMITERS[engine_id]


def get_backoff_state(engine_id: str) -> BackoffState:
    if engine_id not in _BACKOFFS:
        _BACKOFFS[engine_id] = BackoffState()
    return _BACKOFFS[engine_id]


def activate_slow_mode(engine_id: str, reason: str | None = None) -> BackoffState:
    """Enable slow mode after encountering a rate limit. Returns the updated state."""
    state = get_backoff_state(engine_id)
    was_slow = state.slow_mode
    now = time.monotonic()
    state.last_error_ts = now
    state.slow_since = state.slow_since or now
    state.slow_mode = True
    if not was_slow:
        state.notified = False
    state.penalty_delay_sec = min(max(state.penalty_delay_sec, 2.0), 30.0)
    return state


def is_slow_mode(engine_id: str) -> bool:
    return get_backoff_state(engine_id).slow_mode


def consume_slow_mode_notice(engine_id: str) -> bool:
    """Return True if slow mode is active and not yet shown to the user, then mark as shown."""
    state = get_backoff_state(engine_id)
    if state.slow_mode and not state.notified:
        state.notified = True
        return True
    return False


def register_backoff_failure(engine_id: str, status_code: int | None, message: str | None = None) -> None:
    state = get_backoff_state(engine_id)
    if status_code in (429, 403) or (message and "rate limit" in message.lower()):
        activate_slow_mode(engine_id, message)
    else:
        state.penalty_delay_sec = min(state.penalty_delay_sec + 1.0, 10.0)
        state.last_error_ts = time.monotonic()
