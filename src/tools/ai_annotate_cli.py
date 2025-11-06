# -*- coding: utf-8 -*-
"""
CLI для пакетной авторазметки SARIF JSON и экспорта в CSV.
Пример (Windows, PyCharm/Terminal):
  py -m src.tools.ai_annotate_cli ^
     --sarif "C:\path\to\report.sarif.json" ^
     --out   "C:\path\to\results.csv"
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from typing import List

from core.schema import WarningDTO
from services import sarif_reader
from services.export_service import ExportService
from services.llm.yagpt_client import YandexGPTClient
from services.llm.annotator import AutoAnnotator

def load_sarif(path: str) -> List[WarningDTO]:
    data = sarif_reader.load_sarif(path)
    items: List[WarningDTO] = []
    for item in sarif_reader.iter_results(data):
        w = WarningDTO(
            rule_id=item["rule"],
            severity=item["severity"],
            file_path=item["file"] or "",
            start_line=item["start_line"],
            message=item["message"] or "",
            code_snippet=item.get("snippet") or "",
            start_col=item.get("start_col"),
            end_line=item.get("end_line"),
            end_col=item.get("end_col"),
            snippet_text=item.get("snippet") or "",
        )
        w.severity_ui = w.severity
        items.append(w)
    return items

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sarif", required=True, help="Путь к SARIF JSON (2.1.0)")
    ap.add_argument("--out", required=True, help="Путь к CSV для экспорта")
    ap.add_argument("--limit", type=int, default=0, help="Ограничить кол-во (0 = все)")
    args = ap.parse_args()

    items = load_sarif(args.sarif)
    if args.limit and args.limit > 0:
        items = items[:args.limit]

    client = YandexGPTClient()
    annot = AutoAnnotator(client=client)
    annot.annotate_batch(items)

    n = ExportService().to_csv(items, args.out)
    print(f"Аннотировано: {len(items)}; записано: {n}; файл: {args.out}")

if __name__ == "__main__":
    sys.exit(main())
