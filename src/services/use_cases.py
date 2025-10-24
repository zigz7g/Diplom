# services/use_cases.py
from ports import Importer, Repository

class ImportWarningsService:
    def __init__(self, importer: Importer, repository: Repository):
        self.importer = importer
        self.repository = repository

    def run(self, source_path: str) -> int:
        items = self.importer.load(source_path)
        self.repository.clear()
        self.repository.add_many(items)
        return len(items)