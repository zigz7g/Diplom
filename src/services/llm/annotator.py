# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Callable, Iterable, Dict, Any, Union

from .yagpt_client import YandexGPTClient
from .prompts import SYSTEM_PROMPT, build_user_prompt


@dataclass
class AIResult:
    status: str
    severity: str
    label: str
    comment: str
    confidence: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "label": self.label,
            "comment": self.comment,
            "confidence": int(self.confidence),
        }


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Безопасно взять поле из объекта или словаря."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


class AIAnnotator:
    """
    Обертка над YandexGPT с максимально «терпимым» API:

    - Новая форма (рекомендуется):
        annotate_one(
            rule=..., level=..., file=..., line=..., message=..., snippet=..., file_text=...
        )

    - Старая форма (поддерживается):
        annotate_one(warning)  # где warning: dict или DTO с полями rule/rule_id, level, file, line, message, snippet_text

      В старой форме "file_text" неоткуда брать — используем snippet_text или snippet
      как fallback (модель тоже справляется).
    """

    def __init__(self, client: Optional[YandexGPTClient] = None):
        self.client = client or YandexGPTClient()

    # >>> ГЛАВНЫЙ МЕТОД С ОБРАТНОЙ СОВМЕСТИМОСТЬЮ <<<
    def annotate_one(self, *args, **kwargs) -> AIResult:
        """
        Поддерживает:
          - annotate_one(rule=..., level=..., file=..., line=..., message=..., snippet=..., file_text=...)
          - annotate_one(warning_dict_or_dto)
        """
        if args and kwargs:
            # если вдруг смешали формы — считаем это ошибкой вызова
            raise TypeError("annotate_one(): use EITHER positional (warning) OR keyword arguments, not both")

        if kwargs:
            # новая форма — всё ясно
            rule = kwargs.get("rule") or ""
            level = kwargs.get("level") or kwargs.get("severity") or "info"
            file_ = kwargs.get("file") or "-"
            line = _to_int(kwargs.get("line"), 0)
            message = kwargs.get("message") or ""
            snippet = kwargs.get("snippet") or ""
            file_text = kwargs.get("file_text") or kwargs.get("code_text") or snippet
        else:
            # старая форма — позиционный один аргумент
            if not args:
                raise TypeError("annotate_one(): expected a warning object or keyword arguments")

            row = args[0]

            # поддержим и rule_id, и rule
            rule = _get_attr(row, "rule", "") or _get_attr(row, "rule_id", "")
            level = _get_attr(row, "level", "") or _get_attr(row, "severity", "") or "info"
            file_ = _get_attr(row, "file", "-") or "-"
            line = _to_int(_get_attr(row, "line", 0), 0)
            message = _get_attr(row, "message", "") or ""
            snippet = _get_attr(row, "snippet", "") or _get_attr(row, "snippet_text", "") or ""
            # в старой форме нет file_text — используем сниппет
            file_text = snippet

        # Сформировать промпт и дернуть модель
        user = build_user_prompt(
            rule=rule, level=level, file=file_, line=line,
            message=message, snippet=snippet, code_text=file_text,
        )
        data = self.client.complete_json(system=SYSTEM_PROMPT, user=user)

        status = str(data.get("status", "insufficient_evidence")).strip()
        if status not in {"confirmed", "false_positive", "insufficient_evidence"}:
            status = "insufficient_evidence"

        severity = str(data.get("severity", level or "info")).strip().lower()
        if severity not in {"critical", "medium", "low", "info"}:
            severity = "info"

        label = str(data.get("label", rule or "")).strip()[:120]
        comment = str(data.get("comment", "")).strip()[:500]

        conf = data.get("confidence", 0)
        try:
            conf = int(round(float(conf)))
        except Exception:
            conf = 0
        conf = max(0, min(100, conf))

        return AIResult(status=status, severity=severity, label=label, comment=comment, confidence=conf)

    def annotate_bulk(self,
                      rows: Iterable[Union[dict, object]],
                      get_text: Optional[Callable[[Union[dict, object]], str]] = None) -> list[AIResult]:
        """
        Массовая разметка. Каждая запись — dict или DTO.
        Если есть возможность предоставить полный текст для файла — передай get_text(row).
        """
        out: list[AIResult] = []
        for r in rows:
            file_text = get_text(r) if get_text else (_get_attr(r, "snippet_text", "") or _get_attr(r, "snippet", "") or "")
            res = self.annotate_one(
                rule=_get_attr(r, "rule", "") or _get_attr(r, "rule_id", ""),
                level=_get_attr(r, "level", "") or _get_attr(r, "severity", "") or "info",
                file=_get_attr(r, "file", "-") or "-",
                line=_to_int(_get_attr(r, "line", 0), 0),
                message=_get_attr(r, "message", "") or "",
                snippet=_get_attr(r, "snippet", "") or _get_attr(r, "snippet_text", "") or "",
                file_text=file_text,
            )
            out.append(res)
        return out


# совместимость со старым импортом
AutoAnnotator = AIAnnotator
__all__ = ["AIAnnotator", "AutoAnnotator", "AIResult"]
