# -*- coding: utf-8 -*-
"""
Быстрые эвристики для авторазметки без LLM.

Возвращает словарь вида:
{
    "action": "reject" | "confirm" | "skip" | "ai",
    "label": "краткий тэг",
    "comment": "подробный комментарий",
    "confidence": 0.0..1.0
}
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


DOC_HINTS = ("docs/", "/docs/", "documentation", "readme", "changelog")
TEST_HINTS = ("/tests/", "tests/", "/test_", "_tests/", "_test.py", "/test/", "fixtures/", "migrations/")
VENDOR_HINTS = ("/site-packages/", "/dist-packages/")

SAFE_EXTS = (".txt", ".rst", ".md", ".yml", ".yaml", ".toml", ".ini")

# Правила, которые почти всегда FP в доках/тестах
RULES_FP_IN_DOCS = {
    "CONFIG_CRYPTO_KEY_NULL",
    "CONFIG_CRYPTO_KEY_EMPTY",
    "CONFIG_CRYPTO_KEY_HARDCODED",
    "CONFIG_PASSWORD_HARDCODED",
    "HTML_CRYPTO_MISSING_STEP",
}


def _is_textual_snippet(snippet: str) -> bool:
    s = (snippet or "").strip()
    if not s:
        return False
    return s.startswith("* ") or s.startswith(".. ") or s.startswith("# ") and "sample" in s.lower()


def analyze_warning(
    *,
    rule: str,
    level: str,
    file: str,
    line: int,
    message: str,
    snippet: str,
    file_text: str = "",
) -> Dict:
    """
    Возвращает auto-решение или 'ai', если нужно звать LLM.
    """
    path = file or ""
    rule = (rule or "").upper()
    level = (level or "info").lower()
    snippet = snippet or ""

    # 1) Отфильтровать явные не-прод файлы
    path_l = path.lower()
    if path_l.endswith(SAFE_EXTS) or any(h in path_l for h in DOC_HINTS):
        if rule in RULES_FP_IN_DOCS or _is_textual_snippet(snippet):
            return {
                "action": "reject",
                "label": "Документация/пример",
                "comment": f"Строка {line}: фрагмент описательного текста («{snippet[:64]}»), а не исполняемый код. Правило {rule} тут неприменимо.",
                "confidence": 0.95,
            }

    if any(h in path_l for h in TEST_HINTS):
        if rule in RULES_FP_IN_DOCS:
            return {
                "action": "reject",
                "label": "Тестовый код",
                "comment": f"Строка {line}: тестовый сценарий использует фиктивные значения; по смыслу это не уязвимость в прод-коде.",
                "confidence": 0.9,
            }

    if any(h in path_l for h in VENDOR_HINTS):
        return {
            "action": "reject",
            "label": "Сторонний код",
            "comment": "Находится в стороннем пакете; размечается отдельно от проекта.",
            "confidence": 0.8,
        }

    # 2) Простые подтверждения по сигнатурам
    if rule == "PYTHON_INJECTION_SQL":
        sn = snippet.replace(" ", "")
        if ".extra(" in sn or ".raw(" in sn or ("SELECT" in snippet and " % " in snippet):
            return {
                "action": "confirm",
                "label": "SQLi: конкатенация",
                "comment": f"Строка {line}: SQL выражение собирается динамически ({snippet.strip()[:80]}). При поступлении непроверенных данных возможно внедрение.",
                "confidence": 0.75,
            }

    # 3) По умолчанию — в LLM
    return {"action": "ai", "label": "", "comment": "", "confidence": 0.0}
