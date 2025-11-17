from __future__ import annotations

import json
import logging
import textwrap
from typing import Any, Dict, Tuple

from services.llm.clients.yandex_gpt import YandexGPTClient
from services.analysis.heuristics import analyze_warning

log = logging.getLogger(__name__)


class AIAnnotator:
    """
    Обёртка над YandexGPT для авторозметки одного срабатывания.

    ВАЖНО: метод annotate_one возвращает словарь в "внутреннем" формате UI:

        {
            "status": "confirmed" | "false_positive",
            "severity": "critical" | "medium" | "low" | "info",
            "comment": "<объяснение на русском>",
            "confidence": float (0..1),
            "label": "<произвольная метка>"
        }

    Дальше этот словарь нормализуется в MainWindow._coerce_ai_result()
    и применяется к объекту WarningDTO в _apply_ai_result().
    """

    def __init__(self, client: YandexGPTClient) -> None:
        self.client = client

    # ----------------- Публичный метод -----------------

    def annotate_one(
        self,
        rule: str,
        level: str,
        file_path: str,
        line: int,
        code: str,
        text: str,
        status: str,
    ) -> Dict[str, Any]:
        """
        Авторозметка одного предупреждения статического анализа.
        """

        # Эвристический контекст (подсказки для модели)
        ctx = analyze_warning(
            rule_id=rule,
            file_path=file_path,
            level=level,
            code=code,
            text=text,
        )

        prompt = self._build_prompt(
            rule=rule,
            level=level,
            file_path=file_path,
            line=line,
            code=code,
            text=text,
            ctx=ctx,
        )

        raw_answer = self.client.generate(prompt)
        status_ru, comment_ru = self._parse_answer(raw_answer, fallback_ctx=ctx)

        # --- нормализация в формат UI ---

        # внутренний статус в UI — "confirmed"/"false_positive"
        normalized_status = (
            "confirmed" if status_ru.lower().startswith("подтверж") else "false_positive"
        )

        # базовая серьёзность берём из эвристики (по сути — из исходного отчёта)
        severity = getattr(ctx, "severity", None) or level or "info"
        if severity not in {"critical", "medium", "low", "info"}:
            severity = "info"

        risk_hint = getattr(ctx, "risk_hint", "") or ""
        # грубая оценка confidence по эвристике
        base_conf = 0.7
        if risk_hint == "likely_tp":
            base_conf = 0.9
        elif risk_hint == "likely_fp":
            base_conf = 0.85

        # label — просто аккуратная метка по типу/семейству правила + теги
        label_parts = []
        rule_family = getattr(ctx, "rule_family", "") or ""
        if rule_family:
            label_parts.append(rule_family)

        tags = getattr(ctx, "tags", []) or []
        label_parts.extend(tags)
        label = ",".join(sorted(set(label_parts))) if label_parts else ""

        return {
            "status": normalized_status,
            "severity": severity,
            "comment": comment_ru,
            "confidence": float(base_conf),
            "label": label,
        }

    # ----------------- Внутренние методы -----------------

    def _build_prompt(
        self,
        rule: str,
        level: str,
        file_path: str,
        line: int,
        code: str,
        text: str,
        ctx: Any,
    ) -> str:
        """
        Собираем промпт для YandexGPT.

        Здесь мы только подготавливаем все данные и явно просим
        вернуть JSON с полями status / comment.
        """

        file_roles = []
        if getattr(ctx, "is_test", False):
            file_roles.append("тестовый файл")
        if getattr(ctx, "is_doc", False) or getattr(ctx, "is_documentation", False):
            file_roles.append("файл документации или примера")
        if getattr(ctx, "is_locale", False):
            file_roles.append("файл локализации/переводов")
        if getattr(ctx, "is_migration", False):
            file_roles.append("миграции или вспомогательные скрипты")

        file_role_str = ", ".join(file_roles) if file_roles else "боевой код приложения"

        rule_desc = getattr(ctx, "rule_description", "") or ""

        # код подсказки риска от эвристики
        risk_hint_code = getattr(ctx, "risk_hint", "") or ""
        risk_hint_ru = getattr(ctx, "risk_hint_ru", "") or ""

        # если заранее не подготовлен текст, аккуратно сформулируем его здесь
        if not risk_hint_ru and risk_hint_code:
            if risk_hint_code == "likely_tp":
                risk_hint_ru = (
                    "эвристика считает, что срабатывание ПОХОЖЕ на реальную уязвимость, "
                    "но окончательное решение нужно принимать по коду и логике приложения"
                )
            elif risk_hint_code == "likely_fp":
                risk_hint_ru = (
                    "эвристика считает, что срабатывание ПОХОЖЕ на ложноположительное "
                    "(тесты, документация, примеры и т.п.), "
                    "но нужно проверить код перед окончательным решением"
                )
            elif risk_hint_code == "unclear":
                risk_hint_ru = (
                    "эвристика не даёт однозначной подсказки, решение нужно принимать "
                    "исключительно по коду и контексту"
                )

        tags = getattr(ctx, "tags", []) or []
        tags_str = ", ".join(tags)

        # аккуратно оформляем фрагмент кода
        code_block = (code or "").strip()
        code_block = textwrap.dedent(code_block)
        if not code_block:
            code_block = "<фрагмент кода отсутствует>"
        code_block = textwrap.indent(code_block, "    ")

        text_block = (text or "").strip()

        prompt = f"""
Ты — эксперт по информационной безопасности и статическому анализу исходного кода.

Тебе дано одно срабатывание статического анализатора (Svace / AppScreener).
Нужно решить, является ли оно реальной уязвимостью или ложноположительным срабатыванием,
и кратко объяснить своё решение. Отвечай ВСЕГДА на русском языке.

Информация о срабатывании:
- Правило: {rule}
- Уровень (severity) из отчёта: {level}
- Файл: {file_path}
- Номер строки: {line}
- Роль файла: {file_role_str}
- Описание правила (если есть): {rule_desc}
- Подсказка по риску (эвристика): {risk_hint_ru}
- Эвристические теги: {tags_str}

Текст сообщения статического анализатора:
\"\"\"{text_block}\"\"\"

Код (фрагмент вокруг срабатывания):
{code_block}

Проанализируй всё выше и реши:
1) Есть ли здесь реальная уязвимость, которую нужно исправлять в продукте?
2) Почему ты так считаешь (учитывай, является ли файл тестовым, документацией,
   файлом локализации, примером из мануала и т.п.).

Верни ответ СТРОГО в формате JSON одной строкой, без каких-либо пояснений до или после:

{{"status": "Подтверждено" | "Отклонено",
  "comment": "развёрнутый, но ёмкий комментарий на русском языке (2–5 предложений)"}}

Где:
- "Подтверждено" — действительно опасная уязвимость в коде приложения;
- "Отклонено" — ложноположительное срабатывание (например, тест, пример, документация,
  локаль, неиспользуемый код и т.п.).
"""
        return textwrap.dedent(prompt).strip()

    def _parse_answer(self, raw: Any, fallback_ctx: Any) -> Tuple[str, str]:
        """
        Разбор ответа модели.

        На выходе всегда:
            ("Подтверждено" | "Отклонено", "комментарий")
        """

        # Клиент YandexGPT может вернуть как строку, так и словарь
        # вида {"text": "...", "raw": {...}} (и иногда "json": {...}).
        # Приводим всё к строке.
        if isinstance(raw, dict):
            raw_text = (
                    raw.get("text")
                    or raw.get("answer")
                    or raw.get("output_text")
                    or json.dumps(raw, ensure_ascii=False)
            )
        else:
            raw_text = raw

        raw = (raw_text or "").strip()
        default_status = (
            "Подтверждено"
            if getattr(fallback_ctx, "risk_hint", "") == "likely_tp"
            else "Отклонено"
        )
        default_comment = (
            "Модель вернула некорректный ответ, использован результат по эвристике."
        )

        if not raw:
            return default_status, default_comment

        # Пытаемся вытащить JSON из произвольного текста
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            json_part = raw[start:end]
            data = json.loads(json_part)
        except Exception as e:  # noqa: BLE001
            log.warning("LLM ответ не похож на JSON: %r (%s)", raw, e)
            return default_status, default_comment

        status_raw = str(data.get("status", "")).strip()
        comment = str(data.get("comment", "")).strip()

        if not comment:
            comment = default_comment

        status_low = status_raw.lower()

        if status_low.startswith("подтверж"):
            status_ru = "Подтверждено"
        elif status_low.startswith(("откл", "false", "fp")):
            status_ru = "Отклонено"
        else:
            # на всякий случай учитываем флаг is_security_issue, если модель его вернёт
            is_issue = data.get("is_security_issue")
            if isinstance(is_issue, bool):
                status_ru = "Подтверждено" if is_issue else "Отклонено"
            else:
                status_ru = default_status

        return status_ru, comment