# -*- coding: utf-8 -*-
"""
Простые эвристики, чтобы подсказать LLMу контекст.
Функция толерантна к аргументам — лишние/отсутствующие не ломают вызов.
"""

from __future__ import annotations
import re
from typing import Any, Dict


TEST_DOC_DIR_RE = re.compile(r"(?:^|/)(tests?|test_|docs?|examples?|tutorials?)(?:/|$)", re.IGNORECASE)
FAKE_SECRET_RE = re.compile(r"\b(fake[_-]?key|dummy|example|test[_-]?key|placeholder)\b", re.IGNORECASE)


def analyze_warning(
    *,
    file_path: str = "",
    rule: str = "",
    level: str = "",
    message: str = "",
    code_snippet: str = "",
    line: int = 0,
    tags_str: str = "",
    **_: Any,
) -> Dict[str, Any]:
    is_test_or_docs = bool(TEST_DOC_DIR_RE.search(file_path))
    fake_or_placeholder_secret = bool(FAKE_SECRET_RE.search(code_snippet) or FAKE_SECRET_RE.search(message))

    reason_parts = []
    if is_test_or_docs:
        reason_parts.append("path indicates tests/docs/examples")
    if fake_or_placeholder_secret:
        reason_parts.append("fake/placeholder secret found")

    return {
        "is_test_or_docs": is_test_or_docs,
        "fake_or_placeholder_secret": fake_or_placeholder_secret,
        "reason": "; ".join(reason_parts) or "none",
    }
