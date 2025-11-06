# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:
    import yandexgpt  # type: ignore
except Exception:
    yandexgpt = None  # type: ignore

import requests


class YandexGPTClient:
    """
    Универсальный тонкий клиент к YandexGPT.

    Переменные окружения (fallback):
      YAGPT_API_KEY / YA_API_KEY
      YAGPT_FOLDER_ID / YA_FOLDER_ID
      YAGPT_MODEL (default: 'yandexgpt-lite')
    """
    def __init__(self, api_key: str = "", folder_id: str = "", model_name: str = "") -> None:
        self.api_key = api_key or os.getenv("YAGPT_API_KEY") or os.getenv("YA_API_KEY") or ""
        self.folder_id = folder_id or os.getenv("YAGPT_FOLDER_ID") or os.getenv("YA_FOLDER_ID") or ""
        self.model_name = model_name or os.getenv("YAGPT_MODEL") or "yandexgpt-lite"

    # единая точка
    def generate_any(self, prompt: str, **kw) -> str:
        return self._generate_text(prompt, **kw)

    # синонимы на случай старых вызовов
    def complete(self, *a, **kw):         return self._generate_text(*a, **kw)
    def generate(self, *a, **kw):         return self._generate_text(*a, **kw)
    def generate_text(self, *a, **kw):    return self._generate_text(*a, **kw)
    def chat(self, *a, **kw):             return self._generate_text(*a, **kw)
    def completion(self, *a, **kw):       return self._generate_text(*a, **kw)
    def invoke(self, *a, **kw):           return self._generate_text(*a, **kw)
    def run(self, *a, **kw):              return self._generate_text(*a, **kw)
    def predict(self, *a, **kw):          return self._generate_text(*a, **kw)
    def text(self, *a, **kw):             return self._generate_text(*a, **kw)

    def _assert_creds(self) -> None:
        if not self.api_key or not self.folder_id:
            raise RuntimeError("YandexGPTClient: api_key/folder_id not set")

    def _generate_text(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 800, **_) -> str:
        self._assert_creds()
        if yandexgpt is not None:
            try:
                return yandexgpt.generate(
                    prompt=prompt, api_key=self.api_key, folder_id=self.folder_id,
                    model=self.model_name, temperature=temperature, max_tokens=max_tokens
                )
            except Exception:
                pass

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "x-folder-id": self.folder_id,
        }
        body = {
            "modelUri": f"gpt://{self.folder_id}/{self.model_name}",
            "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": max_tokens},
            "messages": [{"role": "system", "text": "You are a helpful assistant."},
                         {"role": "user", "text": prompt}],
        }
        try:
            r = requests.post(url, headers=headers, data=json.dumps(body), timeout=60)
            r.raise_for_status()
            data = r.json()
            alt = data.get("result", {}).get("alternatives", [{}])[0]
            msg = alt.get("message", {}) or {}
            txt = msg.get("text", "")
            if not isinstance(txt, str) or not txt:
                raise RuntimeError("empty response text")
            return txt
        except Exception as e:
            raise RuntimeError(f"YandexGPTClient HTTP error: {e}") from e
