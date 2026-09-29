# -*- coding: utf-8 -*-
"""Зависший Shikimori не держит генерацию минутами: ретраи не перемножаются."""
import animepack_api
from si_hyx_parts.animepack_api.shikimori_api___init import SHIKIMORI_PREFIX


def test_shikimori_read_timeout_is_retried_once_other_hosts_keep_theirs():
    session = animepack_api.make_session()
    api = animepack_api.ShikimoriApi(session)
    for base in ("https://shikimori.io", "https://shikimori.one"):
        retry = session.get_adapter(base + "/api/graphql").max_retries
        assert retry.read == 1
        assert 503 in retry.status_forcelist and 429 in retry.status_forcelist
    assert session.get_adapter("https://animethemes.moe/x").max_retries.read == 4
    assert SHIKIMORI_PREFIX.startswith("https://shikimori.")
    assert api.client.max_retries == 1


def test_fake_session_is_left_alone():
    class Fake:
        headers = {}
    api = animepack_api.ShikimoriApi(Fake())
    assert isinstance(api.session, Fake)
