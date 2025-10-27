from dataclasses import dataclass
from typing import Optional, Literal

Severity = Literal["error", "warning", "note"]

@dataclass
class WarningDTO:
    id: str                # ruleId
    title: str             # читаемое имя правила (если есть)
    message: str           # сообщение анализатора
    severity: Severity     # error|warning|note
    file_path: str         # относительный или абсолютный путь (как в отчёте)
    start_line: Optional[int]  # 1-based
    end_line: Optional[int]    # 1-based
