from pdfminer.high_level import extract_text
import re
from typing import List, Dict  # Исправили Dict
from core.schema import WarningDTO
from pathlib import Path

# Поддерживаем 3 категории ошибок: критические, предупреждения, заметки
SEVERITY_MAP = {
    "critical": "critical", "критический": "critical",
    "warning": "warning", "предупреждение": "warning",
    "note": "note", "замечание": "note",
}

def _norm_sev(s: str) -> str:
    s = (s or "").strip().lower()
    return SEVERITY_MAP.get(s, s or "warning")

def _parse_vulns(txt: str) -> List[dict]:
    """
    Поддерживаем два формата строк в отчёте:
    1) RULE SEVERITY FILE:LINE - MESSAGE
    2) Блочный:
       Rule: <...>
       Severity: <...>
       File: <...>
       Line: <...>
       Message: <...>
    """
    vulns = []
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines() if l.strip()]

    # Строки с уязвимостями (однострочный формат)
    rx_one = re.compile(
        r"^(?P<rule>[A-Za-z0-9_]{3,})\s+(?P<sev>critical|warning|note|критический|предупреждение|замечание)\s+(?P<file>[^:\s]+):(?P<line>\d+)\s*[-—:]\s*(?P<msg>.+)$",
        re.IGNORECASE
    )

    # Блочный формат с явными метками (например, Rule: <...>)
    block = {}
    def flush():
        nonlocal block
        if not block:
            return
        rule = block.get("rule") or block.get("rule_id")
        sev = _norm_sev(block.get("severity", ""))
        file_path = block.get("file") or block.get("file_path")
        line = block.get("line") or block.get("start_line")
        msg = block.get("message") or block.get("msg") or ""
        if rule and file_path and line:
            m = re.search(r"\d+", str(line))
            start_line = int(m.group()) if m else 1
            vulns.append({
                "rule_id": rule.strip(),
                "severity": sev or "warning",
                "file_path": file_path.strip(),
                "start_line": start_line,
                "end_line": start_line,
                "message": msg.strip(),
                "raw": str(block)
            })
        block = {}

    for line in lines:
        m = rx_one.match(line)
        if m:
            vulns.append({
                "rule_id": m.group("rule"),
                "severity": _norm_sev(m.group("sev")),
                "file_path": m.group("file"),
                "start_line": int(m.group("line")),
                "end_line": int(m.group("line")),
                "message": m.group("msg"),
                "raw": line
            })
            block = {}
            continue

        # Обработка блоков
        def take(prefixes, key):
            nonlocal block
            for p in prefixes:
                if line.lower().startswith(p.lower()+":"):
                    if key == "rule" and block.get("rule"):
                        flush()
                    block[key] = line.split(":", 1)[1].strip()
                    return True
            return False

        if take(["Rule","rule","RuleId","ruleId","Правило","ID правила"], "rule"):   continue
        if take(["Severity","severity","Уровень"], "severity"):                       continue
        if take(["File","file","Файл","Путь"], "file"):                               continue
        if take(["Line","line","Строка"], "line"):                                    continue
        if take(["Message","message","Сообщение","Описание"], "message"):             continue

        if any(line.lower().startswith(s) for s in ["---", "====", "правило:", "rule:"]):
            flush()

    flush()
    return vulns

class PdfReportImporter:
    """Импортёр PDF-отчёта: извлекает текст, парсит уязвимости, нормализует пути."""
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = Path(project_root) if project_root else None

    def load(self, source: str) -> List[WarningDTO]:
        src = Path(source).resolve()
        text = extract_text(str(src))
        vulns = _parse_vulns(text)
        root = self.project_root or src.parent  # можно настроить в будущем в Settings

        out: List[WarningDTO] = []
        for i, v in enumerate(vulns):
            fp = Path(v["file_path"])
            if not fp.is_absolute():
                fp = (root / fp).resolve()
            out.append(WarningDTO(
                id=str(i),
                rule_id=v["rule_id"],
                severity=v["severity"],
                message=v["message"],
                file_path=str(fp),
                start_line=int(v["start_line"]),
                end_line=int(v["end_line"]),
                raw=v.get("raw", "")
            ))
        return out
