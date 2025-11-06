# services/llm/annotator.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .yagpt_client import YandexGPTClient


_PATH_TAGS = [
    ("tests", re.compile(r'(^|/)(tests?|testing)/', re.I)),
    ("docs",  re.compile(r'(^|/)(docs?|doc|readme|changelog|examples?)/|(\.md|\.rst)$', re.I)),
    ("i18n",  re.compile(r'(^|/)(locale|i18n|l10n)/|/LC_MESSAGES/|(\.po|\.pot)$', re.I)),
    ("static",re.compile(r'(^|/)(static|assets)/|(\.png|\.jpg|\.jpeg|\.svg|\.css|\.map)$', re.I)),
    ("migrations", re.compile(r'(^|/)migrations?(/|$)', re.I)),
]

def _path_tags(path: str) -> list[str]:
    p = (path or "").replace("\\", "/")
    tags = [name for name, rx in _PATH_TAGS if rx.search(p)]
    # js как код считаем кодом, а не статикой
    if "static" in tags and p.lower().endswith(".js"):
        tags.remove("static")
    return tags

def _looks_like_key(snippet: str) -> bool:
    s = (snippet or "").lower()
    return bool(re.search(r'(secret|key|token|pass|aes|des|rsa|hmac|apikey)', s))

@dataclass
class AIAnnotator:
    client: YandexGPTClient

    # ---------- быстрый отсев без LLM ----------
    def _fast_filters(
        self, rule: str, level: str, file: str, line: int,
        message: str, snippet: str, file_text: str
    ) -> Optional[Dict[str, Any]]:
        tags = _path_tags(file)

        # i18n/локализации: визуальные RTL/LTR — не уязвимость
        if "i18n" in tags and "RIGHT_LEFT" in (rule or ""):
            return {
                "status": "false_positive", "severity": "info",
                "comment": "Файл локализаций (.po). Изменение отображения RTL/LTR не влияет на безопасность.",
                "confidence": 0.95, "label": "I18N/UI"
            }

        # «жёстко зашитый ключ» в docs/tests, где нет признаков ключа
        if ("CRYPTO_KEY_HARDCODED" in (rule or "")) and (("docs" in tags) or ("tests" in tags)):
            if not _looks_like_key(snippet):
                return {
                    "status": "false_positive", "severity": "info",
                    "comment": "Фрагмент из документации/тестов. В тексте нет ключей/секретов, это служебная строка.",
                    "confidence": 0.9, "label": "HardcodedKey"
                }

        # SQLi в юнит-тестах (assert/fixtures)
        if ("INJECTION_SQL" in (rule or "")) and ("tests" in tags):
            if re.search(r'\bassert\b|\bassertRaises\b|fixture|setup', snippet or "", re.I):
                return {
                    "status": "false_positive", "severity": "info",
                    "comment": "Юнит-тест намеренно формирует ошибочный SQL для проверки поведения.",
                    "confidence": 0.9, "label": "TestFixture"
                }

        return None

    # ---------- промпт ----------
    def _build_prompt(
        self, rule: str, level: str, file: str, line: int,
        message: str, snippet: str, file_text: str,
        project_title: Optional[str] = None,
    ) -> str:
        pt = (project_title or "").strip()
        ctx_header = f"Проект: {pt}\n" if pt else ""
        snippet = snippet or ""
        file_text = file_text or ""
        tags = _path_tags(file)
        tags_str = ", ".join(tags) if tags else "none"

        return f"""{ctx_header}Ты — аналитик статического кода. Прими решение строго по фактам.
НЕЛЬЗЯ подтверждать уязвимость, если нет чёткой цепочки source→(sanitizer?)→sink в продукционном пути.

Дано:
- Правило: {rule}
- Базовый уровень отчёта: {level}
- Файл: {file}
- Теги пути: {tags_str}   # tests/docs/i18n/static/migrations/none
- Строка: {line}
- Сообщение сканера: {message}

Фрагмент кода (snippet):

Контекст файла (укороченно, можно игнорировать нерелевантное):

Инструкции для решения:
1) Определи, есть ли источник непроверенных данных (source), конечная точка (sink) и путь исполнения между ними. Если хотя бы одно звено отсутствует — это false_positive.
2) Если файл — tests/docs/i18n, по умолчанию false_positive, кроме случаев, когда код реально исполняется в проде (обоснуй).
3) Для XSS укажи конкретную точку вставки в DOM/HTML и откуда берутся данные, есть ли экранирование/санитайзеры.
4) Для SQLi укажи конкретный конкат/форматирование запроса и место, где вход приходит от пользователя.
5) Для HardcodedKey проверь, что это действительно ключ/секрет, а не имя файла/пример/переменная окружения.
6) Никогда не делай вывод «по названию правила».

Верни СТРОГО JSON:
{{
  "status": "confirmed|false_positive",
  "severity": "critical|medium|low|info",
  "comment": "2–4 предложения с обоснованием: укажи source, sanitizer (если есть), sink/или почему их нет. Сошлись на переменные/строки из кода.",
  "confidence": 0.0-1.0,
  "label": "краткий тег (XSS|SQLi|HardcodedKey|InsecureConfig|…)"
}}"""

    # ---------- парсер ответа ----------
    def _extract_json(self, text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"status":"false_positive","severity":"info","comment":"","confidence":0.0,"label":""}

    # ---------- публичный метод ----------
    def annotate_one(self, *args, **kwargs) -> Dict[str, Any]:
        if args and len(args) == 1 and not kwargs:
            w = args[0]
            rule = getattr(w, "rule_id", "") or getattr(w, "rule", "") or ""
            level = getattr(w, "severity_ui", "") or getattr(w, "level", "") or "info"
            file = getattr(w, "file", "") or getattr(w, "file_path", "") or "-"
            line = int(getattr(w, "start_line", None) or getattr(w, "line", 0) or 0)
            message = getattr(w, "message", "") or ""
            snippet = getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or ""
            file_text = ""
        else:
            rule = kwargs.get("rule", "") or ""
            level = kwargs.get("level", "") or "info"
            file = kwargs.get("file", "") or "-"
            line = int(kwargs.get("line", 0) or 0)
            message = kwargs.get("message", "") or ""
            snippet = kwargs.get("snippet", "") or ""
            file_text = kwargs.get("file_text", "") or ""

        # 1) быстрый отсев
        fast = self._fast_filters(rule, level, file, line, message, snippet, file_text)
        if fast:
            return fast

        # 2) LLM
        prompt = self._build_prompt(rule, level, file, line, message, snippet, file_text)
        raw = self.client.generate_any(prompt)   # универсальный вызов (см. адаптер ниже)
        data = self._extract_json(raw)

        # нормализация
        status = str(data.get("status", "")).lower()
        if status not in {"confirmed", "false_positive"}:
            status = "false_positive"
        sev = str(data.get("severity", "")).lower()
        if sev not in {"critical","medium","low","info"}:
            sev = "info"
        try:
            conf = float(data.get("confidence", 0))
        except Exception:
            conf = 0.0
        if conf > 1.0:
            conf = conf / 100.0

        return {
            "status": status,
            "severity": sev,
            "comment": (data.get("comment") or "").strip(),
            "confidence": max(0.0, min(1.0, conf)),
            "label": (data.get("label") or "").strip(),
        }
