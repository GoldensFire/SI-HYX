# -*- coding: utf-8 -*-
"""Отдельные источники в меню манги не запускают чужие обходы."""
from types import SimpleNamespace
import time

import pytest
import animepack as ap
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig, SNAPSHOT_GROUP
from si_hyx_parts.animepack.ru_popularity_refresh import refresh_ru_popularity
from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore
from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog
from test_manga_ru_cache import title


@pytest.mark.parametrize("source", ["remanga", "mangalib"])
def test_source_selection_retains_other_snapshots_and_never_calls_other_sites(tmp_path, source):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    other = "mangalib" if source == "remanga" else "remanga"
    for key in (other, "shikimori"):
        cache.remember_memo(SNAPSHOT_GROUP, key, {"previous": key})
    calls = []

    class Client:
        metric = "views"

        def __init__(self, key):
            self.source = key

        def catalog_page(self, page):
            calls.append((self.source, page))
            assert self.source == source
            return [title(source, id=str(i)) for i in (1, 2)] if page == 1 else []

    store = RuPopularityStore(cache, {key: Client(key) for key in (source, other)},
                              RuPopularityConfig(min_samples=2))
    gen = SimpleNamespace(_ru_popularity_service=store, db_cache=cache,
                          stopped=lambda: False, log=lambda message: None)
    refresh_ru_popularity(gen, sources=(source,))
    assert calls == [(source, 1), (source, 2)]
    assert cache.memo(SNAPSHOT_GROUP, source)["complete"]
    assert cache.memo(SNAPSHOT_GROUP, other) == {"previous": other}
    assert cache.memo(SNAPSHOT_GROUP, "shikimori") == {"previous": "shikimori"}
    assert cache.memo("ru_population_refresh_status_v1", source)["status"] == "NORMAL"


@pytest.mark.parametrize("part, expected", [
    ("manga", ["shikimori"]), ("favorites", ["shikimori"]),
    ("remanga", ["remanga"]), ("mangalib", ["mangalib"]),
])
def test_generator_routes_each_part_to_its_own_popularity_source(tmp_path, monkeypatch, part, expected):
    from si_hyx_parts.animepack import ru_popularity_refresh
    calls = []
    monkeypatch.setattr(ru_popularity_refresh, "refresh_ru_popularity",
                        lambda gen, sources=None: calls.append(sources))
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    gen = ap.AnimePackGenerator(ap.PackSettings(), db_cache=cache)
    # Любой случайный запрос чужого каталога вызовет ошибку, а не сеть.
    gen.shikimori = SimpleNamespace()
    gen.fetch_full_catalog = lambda **kw: []
    gen.refresh_db((part,))
    assert calls == [expected]


def test_failed_external_sweep_cannot_report_database_updated(tmp_path, monkeypatch):
    from si_hyx_parts.animepack import ru_popularity_refresh
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    gen = ap.AnimePackGenerator(ap.PackSettings(), db_cache=cache)

    def refresh(current, sources=None):
        cache.remember_memo("ru_population_refresh_status_v1", "mangalib",
                            {"status": "ERROR", "timestamp": time.time(), "reason": "502"})

    monkeypatch.setattr(ru_popularity_refresh, "refresh_ru_popularity", refresh)
    with pytest.raises(ap.AnimePackError, match="mangalib: 502"):
        gen.refresh_db(["mangalib"])
    assert ap.ShikimoriDbCache(cache.path).memo(
        "ru_population_refresh_status_v1", "mangalib")["status"] == "ERROR"


@pytest.mark.parametrize("part", ["remanga", "mangalib"])
def test_menu_dispatches_source_and_manga_block_can_stop_it(qapp, tmp_path, part):
    calls = []
    tab = SimpleNamespace(_db_task=None, _db_parts=(), _refresh_db=calls.append)
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    dialog = DbTableDialog(cache, tab)
    try:
        dialog.flush()
        button = dialog.blocks["manga"].button
        actions = {action.data(): action for action in button.menu().actions()}
        actions[part].trigger()
        assert calls == [(part,)]
        actions["manga_all"].trigger()
        assert calls[-1] == ("manga", "remanga", "mangalib")
        tab._db_task, tab._db_parts = object(), (part,)
        dialog.sync_state()
        assert button.text() == "Остановить" and button.isEnabled()
        assert not any(action.isEnabled() for action in actions.values())
        assert not dialog.blocks["anime"].button.isEnabled()
        button.click()
        assert calls[-1] == ("manga",)  # вкладка останавливает текущую задачу
    finally:
        dialog.deleteLater()


def test_refresh_parts_keep_explicit_source_and_whole_base_has_both():
    assert ap.db_refresh_parts("mangalib") == ("mangalib",)
    assert ap.db_refresh_parts("remanga") == ("remanga",)
    assert ap.db_refresh_parts(None) == ("anime", "manga", "remanga", "mangalib", "franchises")
