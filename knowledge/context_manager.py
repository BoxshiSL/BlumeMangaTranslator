"""
Менеджер контекста перевода для тайтла.

Хранит историю пар (original, translated) и позволяет
получать последние N элементов для подстановки в промт.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ContextEntry:
    """Один сегмент контекста перевода: исходный текст + перевод."""

    original: str
    translated: str


class ContextManager:
    """Простой менеджер контекста для одного тайтла или сессии перевода."""

    def __init__(self, max_length: int = 50) -> None:
        self._max_length = max_length
        self._history: List[ContextEntry] = []

    def add_segment(self, original: str, translated: str) -> None:
        """
        Добавляет новый сегмент в историю контекста.
        """
        self._history.append(ContextEntry(original=original, translated=translated))
        if len(self._history) > self._max_length:
            self._history = self._history[-self._max_length :]

    def get_recent_context(self, limit: int = 10) -> List[ContextEntry]:
        """
        Возвращает список последних `limit` элементов контекста.
        """
        return self._history[-limit:].copy()

    def clear(self) -> None:
        """Полностью очищает историю контекста."""
        self._history.clear()

    def to_dict_list(self) -> List[Dict[str, str]]:
        """
        Возвращает историю в виде списка словарей, удобных для сериализации.
        """
        return [{"original": e.original, "translated": e.translated} for e in self._history]

    def load_from_dict_list(self, data: List[Dict[str, str]]) -> None:
        """
        Загружает историю из списка словарей (формат, возвращаемый to_dict_list).
        """
        self._history = [
            ContextEntry(original=item.get("original", ""), translated=item.get("translated", ""))
            for item in data
        ][: self._max_length]
