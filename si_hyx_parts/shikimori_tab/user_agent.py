# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_user_agent. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _user_agent() -> str:
    return f"{_api.APP_NAME}/{_api.APP_VERSION} (+https://github.com)"

_user_agent.__module__ = _api.__name__
_api._user_agent = _user_agent

def _client_factory(max_retries: int = 3) -> '_api.ShikimoriApiClient':
    """Создаёт клиент. OAuth-токен (если задан) берём из переменной окружения
    SHIKIMORI_TOKEN — безопасно, без хранения в коде/настройках. max_retries
    повышаем для дозагрузки просмотров (там длинная серия запросов)."""
    token = _api.os.environ.get("SHIKIMORI_TOKEN") or None
    return _api.ShikimoriApiClient(base_url=_api.DEFAULT_BASE_URL,
                              user_agent=_api._user_agent(), token=token,
                              max_retries=max_retries)

_client_factory.__module__ = _api.__name__
_api._client_factory = _client_factory
