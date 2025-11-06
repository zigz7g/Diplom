# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Dict, Tuple

def _safe_ts() -> str:
    # Только ASCII-формат, чтобы избежать ValueError на Windows/locale
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def _to_dict(w: Any) -> Dict[str, Any]:
    if is_dataclass(w):
        d = asdict(w)
    elif isinstance(w, dict):
        d = dict(w)
    else:
        d = {}
        # извлекаем распространённые поля безопасно
        for k in (
            "id", "rule_id", "rule", "severity", "severity_ui",
            "file", "path", "line", "start_line", "end_line",
            "message", "snippet", "snippet_text", "status",
            "label", "comment", "confidence",
        ):
            d[k] = getattr(w, k, None)
    # нормализуем альтернативные названия
    d.setdefault("rule_id", d.get("rule"))
    d.setdefault("severity_ui", d.get("severity"))
    d.setdefault("file", d.get("path"))
    d.setdefault("line", d.get("start_line") or d.get("line"))
    d.setdefault("snippet", d.get("snippet_text") or d.get("snippet"))
    return d

def export_warnings_csv(warnings: Iterable[Any], dst_dir: Path) -> Path:
    rows = [_to_dict(w) for w in warnings]
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / f"warnings_{_safe_ts()}.csv"
    # фиксированный порядок колонок + добьём остальными ключами
    base_cols = [
        "rule_id", "severity_ui", "file", "line", "message",
        "snippet", "status",
    ]
    extra_keys = set()
    for r in rows:
        extra_keys |= set(r.keys())
    cols = base_cols + sorted(k for k in (extra_keys - set(base_cols)))
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=cols)
        wcsv.writeheader()
        for r in rows:
            wcsv.writerow({k: r.get(k, "") for k in cols})
    return out

def export_ai_csv(pairs: Iterable[Tuple[Any, Dict[str, Any]]], dst_dir: Path) -> Path:
    """
    pairs: итерируемое из (warning, ai_result_dict)
    ai_result_dict ожидает поля: status/label/comment/confidence (гибко)
    """
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / f"ai_annotations_{_safe_ts()}.csv"

    cols = [
        "rule_id", "severity_ui", "file", "line", "message",
        "status", "label", "comment", "confidence",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=cols)
        wcsv.writeheader()
        for w, a in pairs:
            wd = _to_dict(w)
            a = a or {}
            row = {
                "rule_id": wd.get("rule_id", ""),
                "severity_ui": wd.get("severity_ui", ""),
                "file": wd.get("file", ""),
                "line": wd.get("line", ""),
                "message": wd.get("message", ""),
                "status": a.get("status", a.get("state", "")),
                "label": a.get("label", ""),
                "comment": a.get("comment", a.get("explanation", "")),
                "confidence": a.get("confidence", ""),
            }
            wcsv.writerow(row)
    return out

def export_full_json(pairs: Iterable[Tuple[Any, Dict[str, Any]]], dst_dir: Path) -> Path:
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / f"report_full_{_safe_ts()}.json"
    data: List[Dict[str, Any]] = []
    for w, a in pairs:
        d = _to_dict(w)
        d["_ai"] = a or {}
        data.append(d)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

def export_markdown_summary(pairs: Iterable[Tuple[Any, Dict[str, Any]]], dst_dir: Path) -> Path:
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / f"summary_{_safe_ts()}.md"
    lines = ["# Отчёт по разметке\n"]
    for w, a in pairs:
        d = _to_dict(w)
        a = a or {}
        lines += [
            f"## {d.get('rule_id','?')} — {d.get('severity_ui','')}",
            f"**Файл:** `{d.get('file','')}`  **Строка:** {d.get('line','')}",
            f"**Сообщение:** {d.get('message','').strip()}",
            f"**Статус:** {a.get('status','')}",
            f"**Метка:** {a.get('label','')}",
            f"**Комментарий:** {a.get('comment','').strip()}",
            f"**Доверие:** {a.get('confidence','')}",
            "",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
