# services/analysis/heuristics.py

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any


@dataclass
class HeuristicContext:
    """
    Описание контекста срабатывания, которое мы передаём в LLM
    только как подсказку, а не как жёсткое правило.
    """
    file_path: str
    file_role: str               # prod | test | doc | example | config | locale | third_party | unknown
    is_test: bool
    is_doc: bool
    is_example: bool
    is_config: bool
    is_locale: bool
    is_frontend: bool
    is_third_party: bool
    rule_family: str             # crypto | sql | xss | config | auth | other
    severity: str                # critical | medium | low | info | unknown
    tags: List[str]
    risk_hint: str               # likely_tp | likely_fp | unclear
    summary: str                 # короткое русское описание контекста

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # чтобы промпт был компактнее
        d["tags"] = sorted(set(self.tags))
        return d


def _detect_file_role(path: Path) -> (str, List[str]):
    """
    Грубое определение типа файла по пути.
    Никаких решений здесь не принимается — только контекст.
    """
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    tags: List[str] = []

    # тесты
    if (
        "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in path.as_posix()
    ):
        tags.append("test-file")
        return "test", tags

    # документация / примеры
    if (
        "docs" in parts
        or "doc" in parts
        or "howto" in parts
        or "topics" in parts
        or name.endswith(".txt")
        or name.endswith(".rst")
    ):
        tags.append("documentation")
        return "doc", tags

    # локализация
    if name.endswith(".po") or "locale" in parts:
        tags.append("locale")
        return "locale", tags

    # webpack / html / js / css
    if any(name.endswith(ext) for ext in (".html", ".js", ".ts", ".css")):
        tags.append("frontend")
        return "frontend", tags

    # конфиги
    if any(name.endswith(ext) for ext in (".yml", ".yaml", ".ini", ".cfg", ".json")):
        tags.append("config-file")
        return "config", tags

    if name in ("settings.py", "config.py"):
        tags.append("config-file")
        return "config", tags

    # third-party (условно)
    if "site-packages" in parts or "dist-packages" in parts:
        tags.append("third-party")
        return "third_party", tags

    return "prod", tags  # по умолчанию считаем промышленным кодом


def _detect_rule_family(rule_id: str) -> str:
    r = rule_id.upper()
    if "CRYPTO" in r or "PASSWORD" in r or "SECRET" in r:
        return "crypto"
    if "SQL" in r:
        return "sql"
    if "XSS" in r:
        return "xss"
    if "CONFIG" in r:
        return "config"
    if "AUTH" in r or "SESSION" in r:
        return "auth"
    return "other"


def _normalize_severity(level: str) -> str:
    lvl = (level or "").lower()
    if "crit" in lvl:
        return "critical"
    if "med" in lvl:
        return "medium"
    if "low" in lvl:
        return "low"
    if "info" in lvl:
        return "info"
    return "unknown"


def analyze_warning(
    *,
    rule_id: str,
    file_path: str,
    level: str,
    code: str | None,
    text: str | None,
) -> HeuristicContext:
    """
    Главная точка входа для ИИ-анализатора.

    ВАЖНО: функция НИКОГДА не принимает решение «уязвимость / не уязвимость».
    Она только описывает контекст, который будет отдан в промпт модели.
    """

    path = Path(file_path)
    file_role, tags = _detect_file_role(path)

    rule_family = _detect_rule_family(rule_id)
    severity = _normalize_severity(level)

    is_test = file_role == "test"
    is_doc = file_role in {"doc", "example"}
    is_example = "example" in (text or "").lower()
    is_config = file_role == "config"
    is_locale = file_role == "locale"
    is_frontend = file_role == "frontend"
    is_third_party = file_role == "third_party"

    # первичная оценка риска для ПОДСКАЗКИ модели
    if is_test or is_doc or is_locale or is_third_party:
        risk_hint = "likely_fp"  # сильно похоже на FP
    elif rule_family in {"crypto", "sql", "auth"} and severity in {"critical", "medium"}:
        risk_hint = "likely_tp"
    else:
        risk_hint = "unclear"

    if is_test:
        ctx_summary = "Файл с тестами, изменение поведения в проде маловероятно."
    elif is_doc:
        ctx_summary = "Документация / пример кода, обычно не исполняется в проде."
    elif is_config:
        ctx_summary = "Конфигурационный файл, изменения влияют на окружение."
    elif is_frontend:
        ctx_summary = "Фронтенд-код (HTML/JS/CSS)."
    elif is_locale:
        ctx_summary = "Файл локализации (строки интерфейса)."
    elif is_third_party:
        ctx_summary = "Сторонняя библиотека (site-packages/dist-packages)."
    else:
        ctx_summary = "Обычный рабочий код приложения."

    if rule_family == "crypto":
        tags.append("crypto")
    elif rule_family == "sql":
        tags.append("sql")
    elif rule_family == "xss":
        tags.append("xss")
    elif rule_family == "auth":
        tags.append("auth")

    if is_example:
        tags.append("example-in-text")

    return HeuristicContext(
        file_path=file_path,
        file_role=file_role,
        is_test=is_test,
        is_doc=is_doc,
        is_example=is_example,
        is_config=is_config,
        is_locale=is_locale,
        is_frontend=is_frontend,
        is_third_party=is_third_party,
        rule_family=rule_family,
        severity=severity,
        tags=tags,
        risk_hint=risk_hint,
        summary=ctx_summary,
    )
