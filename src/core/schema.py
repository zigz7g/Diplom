# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

SEVERITY_COLORS = {
    "critical": "#DC2626",
    "medium":   "#EA580C",
    "low":      "#CA8A04",
    "info":     "#0891B2",
}

@dataclass(slots=True)
class WarningDTO:
    # базовые поля
    rule_id: str
    severity: str
    file_path: str
    message: str
    code_snippet: str = ""

    # статус разметки
    status: str = "Не обработано"   # "Подтверждено" | "Отклонено" | "Не обработано"
    comment: str = ""
    severity_ui: str = ""           # если пусто — используем severity

    # координаты (для подсветки)
    start_line: Optional[int] = None
    start_col:  Optional[int] = None
    end_line:   Optional[int] = None
    end_col:    Optional[int] = None

    # сниппет из SARIF (когда исходника на диске нет)
    snippet_text: str = ""

    # --- AI/ML метаданные ---
    ml_model: str = ""
    ml_label: str = ""         # 'confirmed'|'rejected'|'needs_review'
    ml_confidence: float = 0.0 # 0..1
    ml_reason: str = ""

    def eff_severity(self) -> str:
        return self.severity_ui or self.severity
