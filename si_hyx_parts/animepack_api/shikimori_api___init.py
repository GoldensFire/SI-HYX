# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: __init__. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api

# Адреса Shikimori (домен кочует между .one и .io) — у них свои ретраи сессии.
SHIKIMORI_PREFIX = "https://shikimori."


def __init__(self, session: _api.Optional[_api.requests.Session] = None,
             client: _api.Optional[_api.Any] = None):
    self.session = session or _api.make_session()
    _mount_shikimori_retry(self.session)
    self.limiter = _api.RateLimiter(2, per_minute=self.PER_MINUTE)
    self._client = client


def _mount_shikimori_retry(session) -> None:
    """Таймаут чтения у Shikimori повторяем один раз, а не пять.

    Ретраи были вложены: urllib3 в сессии (make_session) повторял таймаут пять
    раз по 15 с с паузами, а ShikimoriApiClient повторял всё это ещё пять раз.
    Один зависший GraphQL-запрос держал генерацию восемь минут (живой прогон:
    «поиск кандидатов 18 мин», «Экранизации манги не загрузились» через 8 мин
    после предыдущей). 429 и 5xx сессия переживает по-прежнему."""
    if not isinstance(session, _api.requests.Session):
        return      # подменённая в тестах сессия
    retry = _api.Retry(
        total=4, connect=4, read=1, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount(SHIKIMORI_PREFIX,
                  _api.HTTPAdapter(max_retries=retry, pool_maxsize=16))

# ── клиент shikimori_api (ленивый импорт) ──────────────────────────────
@property
def client(self):
    if self._client is None:
        from shikimori_api import ShikimoriApiClient
        # Один свой повтор: 429 и 5xx уже повторяет сессия, а каждый
        # лишний повтор клиента умножал ожидание зависшего запроса.
        self._client = ShikimoriApiClient(user_agent=_api.USER_AGENT,
                                          max_retries=1,
                                          session=self.session)
    return self._client

@property
def base_url(self) -> str:
    try:
        return self.client.base_url
    except Exception:  # pragma: no cover
        return "https://shikimori.io"
