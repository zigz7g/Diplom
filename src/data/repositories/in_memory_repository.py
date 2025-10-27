from typing import List
from core.schema import WarningDTO

class InMemoryRepository:
    def __init__(self) -> None:
        self._items: List[WarningDTO] = []

    def replace_all(self, items: List[WarningDTO]) -> None:
        self._items = list(items)

    def list_all(self) -> List[WarningDTO]:
        return list(self._items)
