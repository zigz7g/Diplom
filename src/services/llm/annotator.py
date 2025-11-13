# -*- coding: utf-8 -*-
"""
AIAnnotator — единая точка для LLM-разметки.
Толерантен к входу: можно передавать dict warning ИЛИ только набор **kwargs.
Не падает на неожиданных полях, сам собирает контекст.
"""

from __future__ import annotations
import json
import typing as t

from services.llm.yagpt_client import YandexGPTClient
from services.analysis.heuristics import analyze_warning

Json = dict[str, t.Any]


class AIAnnotator:
    def __init__(self, client: YandexGPTClient) -> None:
        self.client = client

    def annotate_one(self, warning: t.Optional[dict] = None, /, **kwargs) -> tuple[bool, Json, str]:
        """
        Универсальный вход:
          - annotate_one(warning_dict)
          - annotate_one(rule='X', file='...', line=123, ...)
        Возвращает: (ok, ai_json, short_comment)
        """
        # Сливаем всё, что передали, в один словарь
        data: dict[str, t.Any] = {}
        if isinstance(warning, dict):
            data.update(warning)
        if kwargs:
            data.update(kwargs)

        # Мягко достаём поля
        file_path: str = str(data.get("file") or data.get("path") or "")
        rule: str = str(data.get("rule") or data.get("rule_id") or data.get("name") or "")
        level: str = str(data.get("level") or data.get("severity") or "")
        message: str = str(data.get("message") or "")
        code_snippet: str = str(data.get("snippet") or data.get("code") or "")
        line: int = int(data.get("line") or data.get("line_number") or 0)
        tags_str: str = str(data.get("tags") or data.get("tags_str") or "")

        # Быстрые эвристики (подсказки для LLM)
        heur = analyze_warning(
            file_path=file_path,
            rule=rule,
            level=level,
            message=message,
            code_snippet=code_snippet,
            line=line,
            tags_str=tags_str,
        )

        # Схема требуемого JSON от LLM
        schema: Json = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["confirmed", "false_positive"]},
                "severity": {"type": "string", "enum": ["critical", "medium", "low", "info"]},
                "label": {"type": "string"},
                "confidence": {"type": "number"},
                "comment": {"type": "string"},
            },
            "required": ["status", "severity", "label", "confidence", "comment"],
            "additionalProperties": False,
        }

        system = (
            "You are a senior static-analysis triager. "
            "Decide if the finding is a real vulnerability. "
            "Answer ONLY a JSON object that strictly matches the SCHEMA."
        )

        prompt = f"""
Rule: {rule}
Severity (scanner): {level}
File: {file_path}
Line: {line}
Tags: {tags_str}
Message: {message}

Code snippet (focus on the highlighted line):
---
{code_snippet}
---

Context notes (heuristics):
- is_test_or_docs: {heur.get('is_test_or_docs')}
- fake_or_placeholder_secret: {heur.get('fake_or_placeholder_secret')}
- reason: {heur.get('reason')}

Task:
1) If the code path is non-exploitable or belongs to tests/docs/examples, mark as false_positive with a short rationale tied to the snippet.
2) Otherwise mark as confirmed and briefly state the concrete data flow (source→sink) or misuse that makes it exploitable.
3) Confidence: 0.0–1.0
""".strip()

        # Жёстко просим JSON
        llm = self.client.generate_json(prompt, schema=schema, system=system)

        ai_json: Json = {
            "status": "false_positive",
            "severity": (level or "info").lower(),
            "label": rule or "",
            "confidence": 0.3,
            "comment": "No structured result from LLM.",
        }

        text = llm.get("text") or ""
        ok = False

        if "json" in llm and isinstance(llm["json"], dict):
            ai_json = llm["json"]
            ok = True
        else:
            # Попытка вычленить объект JSON из текста
            try:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = json.loads(text[start : end + 1])
                    if isinstance(parsed, dict):
                        ai_json = parsed
                        ok = True
            except Exception:
                ok = False

        # Нормализуем и страхуем обязательные поля
        if not isinstance(ai_json, dict):
            ai_json = {}

        ai_json.setdefault("status", "false_positive")
        ai_json.setdefault("severity", (level or "info").lower())
        ai_json.setdefault("label", rule or "")
        ai_json.setdefault("confidence", 0.3)
        ai_json.setdefault("comment", (text[:300] if text else "LLM returned empty text"))

        short_comment = str(ai_json.get("comment") or "")
        return bool(ok), ai_json, short_comment

    def annotate_batch(self, warnings: list[dict]) -> list[tuple[bool, Json, str]]:
        return [self.annotate_one(w) for w in warnings]
