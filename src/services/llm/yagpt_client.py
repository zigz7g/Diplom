# -*- coding: utf-8 -*-
"""
Лёгкий клиент для YandexGPT (YC Foundation Models).
Совместим с прежними вызовами:
 - принимает model_name (alias of model)
 - имеет методы generate(), generate_json(), generate_any()
"""

from __future__ import annotations
import json
import os
import typing as t
import requests


class YandexGPTError(RuntimeError):
    pass


class YandexGPTClient:
    def __init__(
        self,
        api_key: str | None = None,
        folder_id: str | None = None,
        model: str | None = None,
        model_name: str | None = None,
        endpoint: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout: int = 45,
    ) -> None:
        self.api_key = api_key or os.getenv("YAGPT_API_KEY") or os.getenv("YA_API_KEY") or ""
        self.folder_id = folder_id or os.getenv("YAGPT_FOLDER_ID") or os.getenv("YA_FOLDER_ID") or ""
        if not self.api_key or not self.folder_id:
            raise YandexGPTError("api_key/folder_id not set")

        # alias
        self.model = (model or model_name or os.getenv("YAGPT_MODEL") or "yandexgpt-lite").strip()
        # официальный endpoint
        self.endpoint = (
            endpoint
            or os.getenv("YAGPT_ENDPOINT")
            or "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        )
        self.temperature = float(os.getenv("YAGPT_TEMPERATURE", temperature))
        self.max_tokens = int(os.getenv("YAGPT_MAX_TOKENS", max_tokens))
        self.timeout = int(os.getenv("YAGPT_TIMEOUT", timeout))

    # ----------- публичные методы-обёртки совместимости -----------

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        *,
        json_schema: dict | None = None,
        response_format: str | None = None,
    ) -> dict:
        """Базовый генератор. Если передан json_schema — заставит модель вернуть JSON."""
        messages = []
        if system:
            messages.append({"role": "system", "text": system})
        messages.append({"role": "user", "text": prompt})

        body: dict = {
            "modelUri": f"gpt://{self.folder_id}/{self.model}",
            "completionOptions": {
                "temperature": self.temperature,
                "maxTokens": self.max_tokens,
            },
            "messages": messages,
        }

        if json_schema:
            # YandexGPT не принимает JSON Schema напрямую,
            # поэтому подсказываем форматом инструкции.
            schema_hint = json.dumps(json_schema, ensure_ascii=False)
            messages[0:0] = [{
                "role": "system",
                "text": (
                    "Return ONLY a valid JSON object that strictly matches this schema. "
                    "Do not add explanations or extra fields.\nSCHEMA:\n" + schema_hint
                ),
            }]

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "x-folder-id": self.folder_id,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.endpoint, headers=headers, json=body, timeout=self.timeout)
        except Exception as e:
            raise YandexGPTError(f"HTTP error: {e!r}") from e

        if resp.status_code >= 400:
            raise YandexGPTError(f"HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        # ожидаемый ответ: data['result']['alternatives'][0]['message']['text']
        try:
            alt = data["result"]["alternatives"][0]
            text = alt["message"]["text"]
        except Exception as e:
            raise YandexGPTError(f"Unexpected response: {data}") from e

        out = {"text": text, "raw": data}

        # Если ожидаем JSON — попробуем распарсить.
        if json_schema or (response_format and "json" in response_format.lower()):
            try:
                out["json"] = json.loads(text)
            except Exception:
                # оставляем текст как есть, парсинг на стороне вызывающего
                pass
        return out

    def generate_json(self, prompt: str, schema: dict, system: str | None = None) -> dict:
        """Совместимый метод: принудительно JSON-ответ."""
        return self.generate(prompt, system=system, json_schema=schema, response_format="json")

    def generate_any(self, **kwargs) -> dict:
        """Совместимый метод с «широким» контрактом."""
        prompt = kwargs.get("prompt") or kwargs.get("text") or ""
        system = kwargs.get("system")
        schema = kwargs.get("schema") or kwargs.get("json_schema")
        return self.generate(prompt, system=system, json_schema=schema)
