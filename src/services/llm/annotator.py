# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from services.analysis.heuristics import analyze_warning
from services.llm.yagpt_client import YandexGPTClient


JSON_RE = re.compile(r"\{.*\}", re.S)


@dataclass
class AIResult:
    status: str
    label: str
    comment: str
    confidence: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "label": self.label, "comment": self.comment, "confidence": self.confidence}


class AIAnnotator:
    def __init__(self, client: Optional[YandexGPTClient] = None) -> None:
        self.client = client or YandexGPTClient()

    # Совместимость со старыми вызовами: вернуть (ok, payload)
    def annotate(self, **kwargs) -> Tuple[bool, Dict[str, Any]]:
        try:
            return True, self.annotate_one(**kwargs)
        except Exception as e:
            return False, {"status": "Не обработано", "label": "Ошибка", "comment": str(e), "confidence": 0.0}

    # Универсальный вход: принимает WarningDTO поля через kwargs
    def annotate_one(
        self,
        *,
        rule: str,
        level: str,
        file: str,
        line: int,
        message: str,
        snippet: str,
        file_text: str = "",
    ) -> Dict[str, Any]:
        rule = rule or ""
        level = level or "info"
        file = file or "-"
        line = int(line or 0)
        message = message or ""
        snippet = snippet or ""

        # 1) Быстрые эвристики
        h = analyze_warning(rule=rule, level=level, file=file, line=line, message=message, snippet=snippet, file_text=file_text)
        act = h.get("action")
        if act == "reject":
            return AIResult("Отклонено", h.get("label", "Не уязвимость"), h.get("comment", ""), h.get("confidence", 0.0)).as_dict()
        if act == "confirm":
            return AIResult("Подтверждено", h.get("label", "Уязвимость"), h.get("comment", ""), h.get("confidence", 0.0)).as_dict()

        # 2) LLM
        prompt = self._build_prompt(rule, level, file, line, message, snippet, file_text)
        raw = self.client.generate_any(prompt, temperature=0.2, max_tokens=600)

        data = self._safe_parse_json(raw)
        if not data:
            short = self._guess_short_label(rule, snippet)
            long = self._fallback_comment(rule, line, snippet)
            return AIResult("Не обработано", short, long, 0.1).as_dict()

        status_map = {
            "confirmed": "Подтверждено",
            "false_positive": "Отклонено",
            "info": "Не обработано",
        }
        status = status_map.get(str(data.get("status", "")).lower(), "Не обработано")
        label = str(data.get("label") or self._guess_short_label(rule, snippet))
        comment = str(data.get("comment") or "").strip()
        if not comment:
            comment = self._fallback_comment(rule, line, snippet)

        return AIResult(status, label, comment, float(data.get("confidence") or 0.0)).as_dict()

    # ---------- helpers ----------

    def _build_prompt(self, rule: str, level: str, file: str, line: int, message: str, snippet: str, file_text: str) -> str:
        return f"""
You are a security code reviewer. Analyze ONLY the provided code and rule. 
Return a single compact JSON and NOTHING else.

Rule: {rule}
Severity: {level}
File: {file}
Line: {line}
Scanner message: {message}

Code snippet (exact line shown with >>> markers if possible):
>>> {snippet}

If necessary, short context of the file:
{file_text[:2000]}

Instructions:
- Base your judgement on this code only. Do not discuss generic "source/sink" pipelines.
- If it's documentation or a test fixture (textual or non-executable), say why THIS line is not exploitable.
- Be concrete: mention variable names, operations, and why (2–4 sentences). No meta-commentary.
- Output JSON with the following schema:

{{
  "status": "confirmed|false_positive|info",
  "label": "short label 2–6 words",
  "comment": "2–4 sentences grounded in the snippet; no generic advice.",
  "confidence": 0.0
}}
        """.strip()

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        m = JSON_RE.search(text or "")
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        return {}

    def _guess_short_label(self, rule: str, snippet: str) -> str:
        if "extra(" in snippet or ".raw(" in snippet:
            return "SQLi: dynamic query"
        return (rule or "Issue").replace("_", " ").title()[:60]

    def _fallback_comment(self, rule: str, line: int, snippet: str) -> str:
        sn = snippet.strip().replace("\n", " ")
        return f"Правило {rule}. Строка {line}: проверьте выражение «{sn[:120]}». Нужна ручная проверка для корректной классификации."
