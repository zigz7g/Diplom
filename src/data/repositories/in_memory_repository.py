# src/data/repositories/in_memory_repository.py
from __future__ import annotations
from typing import List, Iterable
from core.schema import WarningDTO

class InMemoryRepository:
    def __init__(self) -> None:
        self._items: List[WarningDTO] = []

    # Было: не было метода add -> ломался импорт
    def add(self, item: WarningDTO) -> None:
        self._items.append(item)

    def add_many(self, items: Iterable[WarningDTO]) -> int:
        n = 0
        for it in items:
            self._items.append(it)
            n += 1
        return n

    def clear(self) -> None:
        self._items.clear()

    def list_all(self) -> List[WarningDTO]:
        return list(self._items)
