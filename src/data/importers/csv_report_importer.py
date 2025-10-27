import csv
from pathlib import Path
from typing import List, Optional

from core.schema import WarningDTO

def _norm_sev(s: str) -> str:
    s = (s or "").strip().lower()
    if "err" in s:
        return "error"
    if "warn" in s:
        return "warning"
    if "note" in s:
        return "note"
    return "warning"

class CsvReportImporter:
    """
    Гибкий CSV/TSV импорт:
    ожидаемые поля (case-insensitive, допускаются синонимы):
      rule|rule_id|id
      title|name
      message|msg|description
      severity|level
      file|path|file_path
      line|start_line
      end_line (необязательно)
    Разделитель autodetect (comma/semicolon/tab).
    """
    def run(self, path: str) -> List[WarningDTO]:
        p = Path(path)
        raw = p.read_text(encoding="utf-8", errors="ignore")

        # autodetect delimiter
        dialect = csv.Sniffer().sniff(raw.splitlines()[0], delimiters=",;\t")
        reader = csv.DictReader(raw.splitlines(), dialect=dialect)

        def pick(row, *names, default=None):
            for n in names:
                for k in row.keys():
                    if k.strip().lower() == n:
                        return row[k]
            return default

        items: List[WarningDTO] = []
        for row in reader:
            rule_id = (pick(row, "rule_id", "rule", "id", default="Unknown Rule") or "").strip()
            title = (pick(row, "title", "name", default=rule_id) or "").strip() or rule_id
            message = (pick(row, "message", "msg", "description", default="") or "").strip()
            severity = _norm_sev(pick(row, "severity", "level", default="warning") or "")
            file_path = (pick(row, "file_path", "file", "path", default="Unknown") or "").strip() or "Unknown"
            start_line = pick(row, "start_line", "line", default="")
            end_line = pick(row, "end_line", default="")

            def to_int(v) -> Optional[int]:
                try:
                    v = str(v).strip()
                    return int(v) if v else None
                except Exception:
                    return None

            items.append(WarningDTO(
                id=rule_id,
                title=title,
                message=message,
                severity=severity,   # type: ignore
                file_path=file_path,
                start_line=to_int(start_line),
                end_line=to_int(end_line) or to_int(start_line),
            ))
        return items
