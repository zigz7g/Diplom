# -*- coding: utf-8 -*-
# Пакет-шим для обратной совместимости импортов вида:
# from services.llm.clients.yandex_gpt import YandexGPTClient
from .yandex_gpt import YandexGPTClient

__all__ = ["YandexGPTClient"]
