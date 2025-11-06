# -*- coding: utf-8 -*-
from __future__ import annotations
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
Вы — эксперт по статическому анализу кода и безопасности.
Ваша задача — аннотировать срабатывания правил из SARIF/отчетов:
определить статус, уровень, краткую метку и комментарий, а также уверенность в процентах.

ФОРМАТ ОТВЕТА — только JSON:
{
  "status": "confirmed | false_positive | insufficient_evidence",
  "severity": "critical | medium | low | info",
  "label": "краткое имя проблемы",
  "comment": "2–3 предложения с объяснением",
  "confidence": 0..100
}
""").strip()

def build_user_prompt(*, rule: str, level: str, file: str, line: int,
                      message: str, snippet: str, code_text: str,
                      around_hint: str = "") -> str:
    code_short = code_text if len(code_text) <= 6000 else code_text[:6000] + "\n…<truncated>"
    snippet_show = (snippet or "").strip()[:1200]
    return dedent(f"""
    Rule: {rule}
    Level (report): {level}
    File: {file}
    Line: {line}
    Message: {message}

    Snippet:
    ```
    {snippet_show}
    ```

    File content (trimmed to 6000 chars):
    ```text
    {code_short}
    ```

    {around_hint}
    Return strictly JSON as specified above.
    """).strip()
