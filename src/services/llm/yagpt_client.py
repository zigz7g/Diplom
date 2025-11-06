# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
from typing import Optional
import requests


class YandexGPTClient:
    """
    Минималистичный HTTP-клиент к YandexGPT (foundationModels).
    Нужны переменные:
      - YAGPT_API_KEY  (или YA_API_KEY)
      - YAGPT_FOLDER_ID (или YA_FOLDER_ID)
      - YAGPT_MODEL  (необязательно; 'yandexgpt' | 'yandexgpt-lite')
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        model_name: str = "yandexgpt",
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key or os.getenv("YAGPT_API_KEY") or os.getenv("YA_API_KEY") or ""
        self.folder_id = folder_id or os.getenv("YAGPT_FOLDER_ID") or os.getenv("YA_FOLDER_ID") or ""
        self.model_name = os.getenv("YAGPT_MODEL", model_name or "yandexgpt").strip() or "yandexgpt"
        self.timeout = timeout

        if not self.api_key or not self.folder_id:
            raise RuntimeError("YandexGPTClient: api_key/folder_id not set")

        # endpoint для completion (сообщения с ролями)
        self._url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def _model_uri(self) -> str:
        # маппинг коротких имён на полные URI
        base = "yandexgpt-lite" if "lite" in self.model_name.lower() else "yandexgpt"
        return f"gpt://{self.folder_id}/{base}/latest"

    def complete(self, prompt: str) -> str:
        """
        Вернёт сгенерированный текст как одну строку.
        """
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "x-folder-id": self.folder_id,
        }
        payload = {
            "modelUri": self._model_uri(),
            "completionOptions": {
                "temperature": 0.2,
                "maxTokens": 800,
                "stream": False,
            },
            "messages": [
                {"role": "user", "text": prompt}
            ],
        }

        resp = requests.post(self._url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"YandexGPTClient HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        # ожидаемый путь: result -> alternatives[0] -> message -> text
        try:
            return data["result"]["alternatives"][0]["message"]["text"]
        except Exception:
            raise RuntimeError(f"YandexGPTClient: unexpected response: {json.dumps(data)[:500]}")

    # services/llm/yagpt_client.py (добавить в класс YandexGPTClient)

    def generate_any(self, prompt: str) -> str:
        """
        Унифицированный вызов генерации. Бросает понятную ошибку, если не настроены ключи.
        """
        if not (getattr(self, "api_key", None) and getattr(self, "folder_id", None)):
            raise RuntimeError("YandexGPTClient: api_key/folder_id not set")

        # пробуем известные методы клиента; возвращаем первую удачную строку
        for name in ("complete", "generate", "generate_text", "chat", "completion", "invoke", "run", "predict", "text"):
            fn = getattr(self, name, None)
            if callable(fn):
                try:
                    out = fn(prompt)
                    if isinstance(out, str) and out.strip():
                        return out
                except Exception:
                    continue
        raise RuntimeError("YandexGPTClient: no underlying text-generation method found")
