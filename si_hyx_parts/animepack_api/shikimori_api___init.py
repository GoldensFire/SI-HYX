# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: __init__. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def __init__(self, session: _api.Optional[_api.requests.Session] = None,
             client: _api.Optional[_api.Any] = None):
    self.session = session or _api.make_session()
    self.limiter = _api.RateLimiter(2, per_minute=self.PER_MINUTE)
    self._client = client

# ── клиент shikimori_api (ленивый импорт) ──────────────────────────────
@property
def client(self):
    if self._client is None:
        from shikimori_api import ShikimoriApiClient
        self._client = ShikimoriApiClient(user_agent=_api.USER_AGENT,
                                          max_retries=4,
                                          session=self.session)
    return self._client

@property
def base_url(self) -> str:
    try:
        return self.client.base_url
    except Exception:  # pragma: no cover
        return "https://shikimori.io"
