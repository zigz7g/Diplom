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
    # базовые поля, которые читает UI
    rule_id: str
    severity: str
    file: str
    line: int
    message: str
    status: str = "Не обработано"

    # поля для UI и разметки
    comment: str = ""
    severity_ui: str = ""  # если пусто — используем severity

    # координаты нахождения (для подсветки)
    start_line: Optional[int] = None
    start_col:  Optional[int] = None
    end_line:   Optional[int] = None
    end_col:    Optional[int] = None

    # сниппет из SARIF (когда исходника на диске нет)
    snippet_text: str = ""

    def eff_severity(self) -> str:
        return self.severity_ui or self.severity
