"""Independent searches overlap without corrupting chapters or pacing."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import animepack_api as api
from si_hyx_parts.animepack_api.manga_page_sources import MangaPageSources
from si_hyx_parts.animepack_api.manga_reader_pool import ReaderHealth


def test_worker_searches_overlap_and_return_their_own_metadata(monkeypatch):
    gate = threading.Barrier(2)
    instances = []

    class Reader:
        def __init__(self, *args, **kwargs):
            self.language = ""
            self.limiter = object()
            instances.append(self)

        def panel_url(self, card, excluded):
            ident = card["malId"]
            self.last_chapter = str(ident)
            self.last_titles = [str(ident)]
            self.last_source_link = f"chapter/{ident}"
            self.last_page_info = {"id": ident}
            gate.wait(timeout=3)
            return f"https://cdn.test/{ident}.png"

    monkeypatch.setattr(api, "MangaFireApi", Reader)
    source = MangaPageSources(sources={"mangafire": True})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: source.select_page({"malId": i}), (11, 22)))
    assert [r.chapter for r in results] == ["11", "22"]
    assert [r.info["id"] for r in results] == [11, 22]
    assert results[0].client is not results[1].client
    assert all(reader.limiter is instances[0].limiter for reader in instances)


def test_repeated_cdn_denials_have_a_bounded_shared_cooldown(monkeypatch):
    from si_hyx_parts.animepack_api import manga_reader_pool
    clock = [100.0]
    monkeypatch.setattr(manga_reader_pool.time, "monotonic", lambda: clock[0])
    health = ReaderHealth()
    error = SimpleNamespace(response=SimpleNamespace(status_code=403))
    for _ in range(3):
        health.record("https://bad.test/page", error, "remanga")
    assert not health.available("https://bad.test/other-title")
    assert health.available("https://good.test/page")
    assert not health.provider_available("remanga")
    assert health.provider_available("mangalib")
    clock[0] += 91
    assert health.available("https://bad.test/page")
    assert health.provider_available("remanga")
