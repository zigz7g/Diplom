# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple


_NON_PROD_DIR_RE = re.compile(
    r"(?:^|/)(tests?|test_|docs|examples?|example_|sample_|fixtures?|locale/|i18n/|po/)"
    r"(?:/|$)",
    re.IGNORECASE,
)

# Файлы «локализаций» часто подсвечивают строки, не имеющие отношения к исполнению кода
_LOCALE_FILE_RE = re.compile(r"(?:/LC_MESSAGES/|\.po$|\.pot$|/locale/)", re.IGNORECASE)

# Мини-карта правил -> «ярлык» по умолчанию (если LLM не сможет проставить)
_DEFAULT_LABEL_BY_RULE_PREFIX = {
    "XSS": "XSS",
    "SQL": "SQLi",
    "INJECTION": "Injection",
    "PASSWORD": "InsecureConfig",
    "CRYPTO": "HardcodedKey",
    "CONFIG": "InsecureConfig",
    "DESERIALIZATION": "UnsafeDeserialization",
}


@dataclass
class HeuristicsResult:
    path_class: str                 # 'non_prod' | 'prod' | 'unknown'
    forced: bool                    # если True — LLM лучше не звать, решение окончательное
    status: str                     # 'false_positive' | 'confirmed' | 'info'
    severity: str                   # 'info'|'low'|'medium'|'critical'
    label: str                      # короткий ярлык
    comment: str                    # краткое объяснение на основе пути/контекста
    confidence: float               # 0..1
    flags: Tuple[str, ...]          # дополнительные флаги для промпта/журнала

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["flags"] = list(self.flags)
        return d


def _guess_label(rule_id: str) -> str:
    r = (rule_id or "").upper()
    for pref, lab in _DEFAULT_LABEL_BY_RULE_PREFIX.items():
        if pref in r:
            return lab
    return "InsecureFinding"


def analyze_warning(*, file: str, rule_id: str, message: str) -> HeuristicsResult:
    """
    Лёгкая эвристика до LLM, чтобы:
    1) моментально отсечь тесты/доки/локализации как FP;
    2) дать LLM контекст (flags), но не навязывать шаблонных фраз.
    """
    path = file or ""
    flags = []

    # По умолчанию — считаем прод, неизвестную важность «info»
    path_class = "prod"
    status = "confirmed"
    severity = "info"
    forced = False
    label = _guess_label(rule_id)

    # Некоторые классы путей считаем непроизводственными
    if _NON_PROD_DIR_RE.search(path):
        path_class = "non_prod"
        status = "false_positive"
        severity = "info"
        forced = False  # не принуждаем, т.к. иногда в tests бывает рабочий пример
        flags.append("non_prod_path")

    if _LOCALE_FILE_RE.search(path):
        flags.append("locale_like")

    # Если правило из «CONFIG_*» или «*_KEY_*» — понижаем серьёзность в non_prod
    if path_class == "non_prod" and ("KEY" in (rule_id or "").upper() or "CONFIG" in (rule_id or "").upper()):
        severity = "info"
        status = "false_positive"

    # Комментарий — короткая, но конкретная причина (используемая, если LLM не звать/сломался)
    if path_class == "non_prod":
        comment = (
            "Файл находится в непроизводственном пути (docs/tests/examples/fixtures/locale). "
            "Фрагмент предназначен для документации или тестов и не участвует в исполнении в проде."
        )
        confidence = 0.95
    else:
        comment = "Потенциальная уязвимость требует анализа кода по месту использования."
        confidence = 0.4

    return HeuristicsResult(
        path_class=path_class,
        forced=forced,
        status=status,
        severity=severity,
        label=label,
        comment=comment,
        confidence=confidence,
        flags=tuple(flags),
    )
