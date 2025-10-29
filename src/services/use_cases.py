# -*- coding: utf-8 -*-
from __future__ import annotations
from core.schema import WarningDTO
from services import sarif_reader

class ImportSarifService:
    def __init__(self, repo):
        self.repo = repo

    def run(self, path: str) -> int:
        data = sarif_reader.load_sarif(path)
        n = 0
        for item in sarif_reader.iter_results(data):
            w = WarningDTO(
                rule_id=item["rule"],
                severity=item["severity"],
                file=item["file"],
                line=int(item["start_line"] or 1),
                message=item["message"],
                status="Не обработано",
            )
            # координаты + сниппет
            w.start_line = item["start_line"]
            w.start_col  = item["start_col"]
            w.end_line   = item["end_line"]
            w.end_col    = item["end_col"]
            w.snippet_text = item["snippet"] or ""
            w.severity_ui = w.severity
            w.comment = ""

            try:
                self.repo.add(w)
            except Exception:
                self.repo.items.append(w)  # in-memory fallback
            n += 1
        return n

class ImportCsvService:
    def __init__(self, repo): self.repo = repo
    def run(self, path: str) -> int: return 0
