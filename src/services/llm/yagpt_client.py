# -*- coding: utf-8 -*-
from __future__ import annotations

# .env грузим надежно из нескольких мест
import os, json, requests, re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    from dotenv import load_dotenv
    _candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for _f in _candidates:
        if _f.exists():
            load_dotenv(dotenv_path=_f, override=True)
            break
    else:
        load_dotenv(override=True)
except Exception:
    pass

YA_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default

def _extract_json(text: str) -> str:
    if not text:
        raise ValueError("empty model response")

    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S | re.I)
    if m:
        return m.group(1)

    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        start = text.find(open_ch)
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == open_ch: depth += 1
                elif text[i] == close_ch:
                    depth -= 1
                    if depth == 0:
                        return text[start:i+1]
            start = text.find(open_ch, start + 1)

    s = text.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        return s
    return s

@dataclass
class YandexGPTClient:
    api_key: Optional[str] = None
    folder_id: Optional[str] = None
    model_name: Optional[str] = None            # 'yandexgpt-lite' | 'yandexgpt' | полный gpt://.../latest
    temperature: float = float(_env("YAGPT_TEMPERATURE", "YA_TEMPERATURE", default="0.1"))
    max_tokens: int = int(_env("YAGPT_MAXTOKENS", "YA_MAXTOKENS", default="1100"))
    timeout: int = 60

    def __post_init__(self):
        self.api_key   = self.api_key   or _env("YAGPT_API_KEY", "YA_API_KEY")
        self.folder_id = self.folder_id or _env("YAGPT_FOLDER_ID", "YA_FOLDER_ID")
        base = self.model_name or _env("YAGPT_MODEL", "YA_MODEL", default="yandexgpt-lite")

        if not self.api_key:
            raise RuntimeError("Empty API key. Set YAGPT_API_KEY (или YA_API_KEY).")
        if not self.folder_id and not (isinstance(base, str) and base.startswith("gpt://")):
            raise RuntimeError("Empty folder id. Set YAGPT_FOLDER_ID (или YA_FOLDER_ID).")

        if isinstance(base, str) and base.startswith("gpt://"):
            self.model_uri = base
        else:
            self.model_uri = f"gpt://{self.folder_id}/{base}/latest"

        self.headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "x-folder-id": self.folder_id or "",
            "Content-Type": "application/json",
        }

        if self.headers["x-folder-id"]:
            try:
                fid_in_uri = self.model_uri.split("gpt://", 1)[1].split("/", 1)[0]
                if fid_in_uri != self.headers["x-folder-id"]:
                    raise RuntimeError(
                        f"Folder mismatch: x-folder-id={self.headers['x-folder-id']} vs modelUri={self.model_uri}"
                    )
            except Exception:
                pass

    @retry(retry=retry_if_exception_type(requests.RequestException),
           wait=wait_exponential(multiplier=1, min=1, max=20),
           stop=stop_after_attempt(5), reraise=True)
    def _call(self, messages: List[dict]) -> str:
        body = {
            "modelUri": self.model_uri,
            "completionOptions": {"stream": False, "temperature": float(self.temperature), "maxTokens": int(self.max_tokens)},
            "messages": messages,
        }
        r = requests.post(YA_URL, headers=self.headers, json=body, timeout=self.timeout)
        if r.status_code == 401:
            raise requests.RequestException("401 Unauthorized: проверь Api-Key (значение ключа), область execute у ключа.")
        if r.status_code == 403:
            raise requests.RequestException("403 Forbidden: у сервисного аккаунта нет роли ai.languageModels.user на папке.")
        if r.status_code == 400:
            raise requests.RequestException(f"400 Bad Request: {r.text[:400]}")
        if r.status_code >= 300:
            raise requests.RequestException(f"{r.status_code}: {r.text[:400]}")

        data = r.json()
        return data["result"]["alternatives"][0]["message"]["text"]

    def complete_text(self, system: str, user: str) -> str:
        return self._call([{"role": "system", "text": system},
                           {"role": "user", "text": user}])

    def complete_json(self, system: str, user: str) -> dict:
        text = self.complete_text(system, user)
        blob = _extract_json(text)
        return json.loads(blob)
