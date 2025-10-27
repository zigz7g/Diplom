from pathlib import Path
from typing import List, Optional

from data.repositories.in_memory_repository import InMemoryRepository
from data.importers.sarif_report_importer import SarifReportImporter
from data.importers.csv_report_importer import CsvReportImporter

class ImportSarifService:
    def __init__(self, repo: InMemoryRepository):
        self.repo = repo
        self._imp = SarifReportImporter()

    def run(self, path: str) -> int:
        items = self._imp.run(path)
        self.repo.replace_all(items)
        return len(items)

class ImportCsvService:
    def __init__(self, repo: InMemoryRepository):
        self.repo = repo
        self._imp = CsvReportImporter()

    def run(self, path: str) -> int:
        items = self._imp.run(path)
        self.repo.replace_all(items)
        return len(items)

class CodeProvider:
    """Читает фрагмент кода из локальных исходников."""
    def __init__(self, source_root: Optional[str] = None):
        self.source_root = Path(source_root).resolve() if source_root else None

    def set_root(self, root: str) -> None:
        self.source_root = Path(root).resolve()

    def _norm_artifact_path(self, p: str) -> Path:
        if not p or p.lower() == "unknown":
            return Path("__unknown__")
        # URI file:///… → локальный путь
        if p.startswith("file:///"):
            p = p[8:]
            # Windows drive
            if p[1:3] == ":/":
                p = p.replace("/", "\\")
        return Path(p)

    def read_snippet(self, file_path: str, start_line: Optional[int], end_line: Optional[int], ctx: int = 5) -> str:
        try:
            rel = self._norm_artifact_path(file_path)
            if rel.name == "__unknown__":
                return "Фрагмент кода не найден: путь отсутствует в отчёте."
            # абсолютный? тогда используем как есть; относительный — из корня
            cand = rel if rel.is_absolute() else (self.source_root / rel if self.source_root else rel)
            if not cand.exists():
                return f"Файл не найден: {cand}"
            lines = cand.read_text(encoding="utf-8", errors="ignore").splitlines()
            if not start_line or start_line < 1:
                # покажем начало файла
                start = 1
                end = min(len(lines), 1 + ctx * 2)
            else:
                start = max(1, start_line - ctx)
                end = min(len(lines), (end_line or start_line) + ctx)
            # форматируем с номерами строк
            out = []
            numw = len(str(end))
            target = set(range(start_line or 0, (end_line or start_line or 0) + 1))
            for i in range(start, end + 1):
                mark = ">>" if i in target else "  "
                out.append(f"{mark} {str(i).rjust(numw)} | {lines[i-1] if i-1 < len(lines) else ''}")
            return "\n".join(out)
        except Exception as e:
            return f"Ошибка чтения кода: {e}"
