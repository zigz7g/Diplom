# -*- coding: utf-8 -*-
from __future__ import annotations
import os

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")

# Если True — всё, что распознано как тестовый путь, помечаем FP без запроса к LLM.
AI_TESTS_ALWAYS_FP: bool = _truthy(os.getenv("AI_TESTS_ALWAYS_FP", "1"))

# Минимальная уверенность для non-prod/тестовых эвристик.
try:
    AI_NONPROD_MIN_CONFIDENCE: float = float(os.getenv("AI_NONPROD_MIN_CONFIDENCE", "0.93"))
except Exception:
    AI_NONPROD_MIN_CONFIDENCE = 0.93
