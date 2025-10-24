# data/repositories/in_memory_repository.py
from typing import List, Iterable
from core.schema import WarningDTO
from ports import Repository

class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self._items: List[WarningDTO] = []

    def clear(self) -> None:
        self._items.clear()

    def add_many(self, items: Iterable[WarningDTO]) -> None:
        self._items.extend(items)

    def list_all(self) -> List[WarningDTO]:
        return list(self._items)