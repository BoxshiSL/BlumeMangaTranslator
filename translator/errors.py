"""Shared exceptions for translator limited modes."""
from __future__ import annotations


class LimitedModeError(Exception):
    """Raised when a limited/no-API translation call fails."""

    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code
