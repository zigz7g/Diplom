# -*- coding: utf-8 -*-
"""
Унифицированный клиент для YandexGPT.
Гарантирует наличие методов: chat(), completion(), generate_json(), generate().
Любые старые вызовы в коде работают без падений.
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
import urllib.error


YA_BASE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1"


def _http_post(url: str, data: Dict[str, Any], headers: Dict[str, str], timeout: int = 60) -> Dict[str, Any]:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        # Читаем тело ошибки, чтобы показать понятную причину
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YandexGPT HTTP {e.code} at {url}: {err_body}") from None
    except Exception as e:
        raise RuntimeError(f"YandexGPT request failed at {url}: {e}") from None


@dataclass
class YandexGPTClient:
    api_key: str
    folder_id: str
    # Идентификатор модели допускает «lite/latest», «pro/latest» и т.п.
    model_id: str = ""
    base_url: str = YA_BASE_URL

    def __post_init__(self) -> None:
        if not self.model_id:
            # Безопасное значение по умолчанию
            self.model_id = f"gpt://{self.folder_id}/yandexgpt-lite/latest"

    # --- Служебное

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "x-folder-id": self.folder_id,
        }

    def _completion_payload(
        self,
        text: str,
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> Dict[str, Any]:
        # API completion
        return {
            "modelUri": self.model_id,
            "completionOptions": {
                "stream": False,
                "temperature": float(temperature),
                "maxTokens": int(max_tokens),
            },
            "messages": [{"role": "user", "text": text}],
        }

    # --- Унифицированные методы

    def completion(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> str:
        """Базовый вызов completion; возвращает чистый текст."""
        url = f"{self.base_url}/completion"
        payload = self._completion_payload(prompt, temperature=temperature, max_tokens=max_tokens)
        data = _http_post(url, payload, self._headers())
        try:
            return data["result"]["alternatives"][0]["message"]["text"]
        except Exception:
            # На всякий случай вернём сырой JSON-дамп
            return json.dumps(data, ensure_ascii=False)

    # Синоним для совместимости с прежним кодом
    def generate(self, prompt: str, **kwargs) -> str:
        return self.completion(prompt, **kwargs)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> str:
        """
        Совместимая обёртка «chat»: склеиваем сообщения в один промпт и зовём completion().
        messages = [{"role": "system"/"user"/"assistant", "text": "..."}]
        """
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            text = (m.get("content") or m.get("text") or "").strip()
            if not text:
                continue
            if role == "system":
                parts.append(f"[СИСТЕМНОЕ]: {text}")
            elif role == "assistant":
                parts.append(f"[ПОМОЩНИК]: {text}")
            else:
                parts.append(f"[ПОЛЬЗОВАТЕЛЬ]: {text}")
        if not parts:
            parts = ["[ПОЛЬЗОВАТЕЛЬ]: Ответь на русском языке."]
        big_prompt = "\n".join(parts)
        return self.completion(big_prompt, temperature=temperature, max_tokens=max_tokens)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        """
        Совместимый вызов, когда ждут JSON. Возвращает строку ответа (не парсит),
        чтобы вызывающий код сам распарсил нужную структуру.
        """
        msgs = [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": user_prompt},
        ]
        return self.chat(msgs, temperature=temperature, max_tokens=max_tokens)
