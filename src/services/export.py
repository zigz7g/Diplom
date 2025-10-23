from __future__ import annotations
from typing import Iterable
from pathlib import Path
import pandas as pd
from core.schema import WarningDTO

def export_warnings(items: Iterable[WarningDTO], out_path: str) -> str:
    rows = [{
        "rule_id": w.rule_id,
        "severity": w.severity,
        "file_path": w.file_path,
        "start_line": w.start_line,
        "end_line": w.end_line,
        "message": w.message,
    } for w in items]

    df = pd.DataFrame(rows)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".xlsx":
        df.to_excel(out, index=False)
    else:
        # по умолчанию CSV
        if out.suffix.lower() != ".csv":
            out = out.with_suffix(".csv")
        df.to_csv(out, index=False, encoding="utf-8-sig")
    return str(out)
