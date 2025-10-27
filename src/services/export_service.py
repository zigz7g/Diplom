from __future__ import annotations

import csv
from typing import Iterable
from core.schema import WarningDTO

class ExportService:
    """
    Экспорт результатов в CSV.
    По умолчанию UTF-8 с BOM (utf-8-sig) и разделитель ';' — удобно для Excel в RU-среде.
    Можно менять через параметры.
    """
    def to_csv(
        self,
        items: Iterable[WarningDTO],
        out_path: str,
        *,
        encoding: str = "utf-8-sig",
        delimiter: str = ";",
    ) -> int:
        cols = ["index", "severity", "rule", "file", "line", "message", "snippet"]
        count = 0
        with open(out_path, "w", encoding=encoding, newline="") as f:
            wr = csv.writer(f, delimiter=delimiter)
            wr.writerow(cols)
            for i, w in enumerate(items, 1):
                wr.writerow([
                    i,
                    (w.severity or ""),
                    (w.rule or ""),
                    (w.file_path or ""),
                    (w.start_line if w.start_line is not None else ""),
                    (w.message or "").replace("\n", " ").replace("\r", " "),
                    (w.code_snippet or "").replace("\n", " ").replace("\r", " "),
                ])
                count += 1
        return count
