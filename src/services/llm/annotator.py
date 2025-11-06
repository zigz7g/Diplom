# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional

from services.analysis.heuristics import analyze_warning
from services.llm.prompts import build_annotation_prompt


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Достаём первый валидный JSON-объект из ответа.
    """
    if not text:
        raise ValueError("empty LLM response")
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError("no JSON object found")
    payload = m.group(0)
    return json.loads(payload)


class AIAnnotator:
    """
    Обёртка над LLM-клиентом: резистентно вызывает метод генерации, склеивает эвристику и ответ.
    Требование интерфейса: возвращать строго dict со свойствами:
      status, severity, label, confidence, comment.
    """

    def __init__(self, client: Any):
        self.client = client

    # ——— внутренний вызов LLM со списком кандидатных методов (во избежание "no usable method") ———
    def _call_llm(self, prompt: str) -> str:
        last_err = None
        for method_name in ("complete", "generate", "generate_text", "completion", "invoke", "run", "predict", "text"):
            fn = getattr(self.client, method_name, None)
            if not callable(fn):
                continue
            try:
                # некоторые клиенты возвращают объект {text: "..."} / {choices:[...]} — нормализуем
                out = fn(prompt)
                if isinstance(out, str):
                    return out
                if isinstance(out, dict):
                    if "text" in out and isinstance(out["text"], str):
                        return out["text"]
                    if "choices" in out and out["choices"]:
                        # chat-like
                        ch0 = out["choices"][0]
                        if isinstance(ch0, dict):
                            msg = ch0.get("message") or {}
                            if isinstance(msg, dict) and "content" in msg:
                                return msg["content"]
                            # на всякий случай
                            if "text" in ch0:
                                return ch0["text"]
                # fallback: приведение к строке
                return str(out)
            except Exception as e:
                last_err = e
                # ретраим на transient ошибках (включая HTTP 5xx)
                time.sleep(0.4)
                continue
        raise RuntimeError(f"LLM call failed: {last_err or 'no method available'}")

    def annotate_one(
        self,
        *,
        rule: str,
        level: str,
        file: str,
        line: int,
        message: str,
        snippet: str,
        file_text: str,
    ) -> Dict[str, Any]:
        """
        Единая точка — всегда возвращает валидный dict.
        """
        # 1) Лёгкая эвристика пути
        heur = analyze_warning(file=file, rule_id=rule, message=message).to_dict()

        ctx: Dict[str, Any] = {
            "rule_id": rule or "",
            "level": level or "info",
            "file": file or "-",
            "line": int(line or 0),
            "message": message or "",
            "snippet": snippet or "",
            "file_text": file_text or "",
        }

        # 2) Если хочется полностью «коротко-замкнуть» — можно принудительно вернуть эвристику
        # Сейчас принуждаем только если очень уверены, но по умолчанию даём LLM шанс
        force_only_heur = False

        if force_only_heur:
            return {
                "status": heur["status"],
                "severity": heur["severity"],
                "label": heur["label"],
                "confidence": heur["confidence"],
                "comment": heur["comment"],
            }

        # 3) Строим промпт с учётом эвристик
        prompt = build_annotation_prompt(ctx, heur)

        # 4) Зовём LLM и парсим JSON. Если что-то пошло не так — используем эвристику.
        try:
            raw = self._call_llm(prompt)
            parsed = _extract_json(raw)
        except Exception:
            parsed = {
                "status": heur["status"],
                "severity": heur["severity"],
                "label": heur["label"],
                "confidence": heur["confidence"],
                "comment": heur["comment"],
            }

        # 5) Нормализация / «overrides» на базе эвристик пути (чтобы статус и комментарий не противоречили)
        # Если файл явно non_prod, а LLM вдруг «confirmed», мягко опустим до FP и скорректируем комментарий.
        if "non_prod_path" in heur.get("flags", []) and parsed.get("status") == "confirmed":
            parsed["status"] = "false_positive"
            parsed["severity"] = "info"
            # объединяем причину из LLM (если была предметная) с явной ссылкой на непроизводственный путь
            base_comment = parsed.get("comment") or ""
            suffix = " Файл относится к непроизводственному пути (docs/tests/examples/fixtures/locale), поэтому срабатывание не влияет на прод."
            parsed["comment"] = (base_comment + " " + suffix).strip()
            parsed["confidence"] = max(float(parsed.get("confidence") or 0.5), 0.8)

        # 6) Значения по умолчанию/валидация
        parsed["status"] = parsed.get("status") in ("confirmed", "false_positive") and parsed["status"] or heur["status"]
        parsed["severity"] = parsed.get("severity") in ("critical", "medium", "low", "info") and parsed["severity"] or heur["severity"]
        parsed["label"] = parsed.get("label") or heur["label"]
        try:
            parsed["confidence"] = float(parsed.get("confidence", 0.6))
        except Exception:
            parsed["confidence"] = 0.6
        parsed["comment"] = (parsed.get("comment") or "").strip()

        # Финальная страховка: комментарий должен ссылаться на код/файл/строку
        if not parsed["comment"]:
            parsed["comment"] = f"Разбор {rule} в {file}:{line}: требуется ручная проверка по месту использования."
        else:
            # если совсем нет конкретики — мягко подталкиваем
            if all(k not in parsed["comment"] for k in (str(line), "(", ")", "=", ".", "[", "]")):
                parsed["comment"] += f" (см. {file}:{line})"

        return parsed
