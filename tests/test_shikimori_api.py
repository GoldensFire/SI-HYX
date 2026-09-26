# -*- coding: utf-8 -*-
"""Тесты shikimori_api.py: модель, фильтр, клиент с ретраями, find_anime."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import datetime

import pytest

import shikimori_api as api
from conftest import FakeResponse, FakeSession

from si_hyx_parts.tests.test_shikimori_api.no_sleep import (
    no_sleep,
    TestViewsFromCard,
    TestIndexBase,
    TestKindStatusHelpers,
    TestGenreGroup,
)


# ── Anime model ──────────────────────────────────────────────────────────────
SAMPLE_JSON = {
    "id": "42", "name": "Naruto", "russian": "Наруто", "kind": "tv",
    "score": "8.12", "status": "released", "episodes": "220",
    "episodes_aired": 220, "aired_on": "2002-10-03", "released_on": None,
    "image": {"preview": "/system/animes/preview/42.jpg"},
    "url": "/animes/42-naruto",
}

from si_hyx_parts.tests.test_shikimori_api.test_anime_model import (
    TestAnimeModel,
    TestAnimeFilter,
    _client,
    TestClientGet,
)

from si_hyx_parts.tests.test_shikimori_api.test_graphql import (
    TestGraphql,
    TestHighLevel,
    _page,
    TestFindAnime,
)
