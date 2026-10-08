"""Window filters hide rows without changing values or maintenance settings."""
from si_hyx_parts.animepack_tab.db_filters import DbFiltersDialog
from si_hyx_parts.animepack_tab.db_view_filters import defaults, title_rows
from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog
import animepack as api


def test_view_predicates_only_select_existing_rows():
    rows = [{"id": 1, "media": "anime", "kind": "tv", "year": 1990,
             "score": 8, "level": 3, "price": 10, "favorites": 0},
            {"id": 2, "media": "anime", "kind": "movie", "year": 2020,
             "score": 9, "level": 7, "price": 40, "favorites": -1}]
    filters = {**defaults(), "year_from": 2000, "score_from": 8.5}
    assert title_rows(rows, filters) == [rows[1]]
    assert rows[1]["price"] == 40 and rows[1]["level"] == 7
    assert title_rows(rows, defaults()) == rows


def test_filter_controls_have_a_full_reset(qapp):
    filters = {**defaults(), "anime": ("movie",), "year_from": 2010,
               "score_from": 8, "favorites_status": "AGE_RESTRICTED"}
    dialog = DbFiltersDialog(filters)
    try:
        assert dialog.values()["year_from"] == 2010
        dialog.reset()
        assert dialog.values() == defaults()
    finally:
        dialog.deleteLater()


def test_window_filters_do_not_change_cache_counts_or_refresh_parts(qapp, tmp_path):
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("anime", "all", [{"id": "1", "malId": "1", "kind": "tv",
                                      "name": "Old", "airedOn": {"year": 1990}}])
    cache.save()
    calls = []

    class Tab:
        _db_task = None
        def collect(self):
            raise AssertionError("pack settings read by database window")
        def _refresh_db(self, parts):
            calls.append(parts)

    dialog = DbTableDialog(cache, Tab())
    try:
        dialog.flush()
        dialog._set_filters({**defaults(), "anime": (), "year_from": 2020})
        dialog.flush()
        assert dialog._rows_for("anime", dialog._filters_snapshot()) == []
        assert dialog._counts["anime"]["count"] == 1
        dialog.btn_all.click()
        assert calls == [api.db_refresh_parts()]
        assert len(cache.all_cards("anime")) == 1
    finally:
        dialog.flush()
        dialog.deleteLater()


def test_tab_refresh_does_not_read_pack_controls(qapp, monkeypatch):
    import animepack_tab
    from test_animepack_tab_mix import _FakeMain
    calls = []
    class Task:
        def __init__(self, settings, parts):
            self.settings, self.parts = settings, parts
            self.signals = animepack_tab._RefreshDbSignals()
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        monkeypatch.setattr(tab, "collect", lambda: (_ for _ in ()).throw(
            AssertionError("database refresh read pack controls")))
        monkeypatch.setattr(animepack_tab, "_RefreshDbTask", Task)
        monkeypatch.setattr(tab._pool, "start", calls.append)
        tab._refresh_db(("anime",))
        assert calls[0].settings.year_from == 0 and calls[0].settings.score_from == 0
        assert all(calls[0].settings.kinds.values())
        assert calls[0].parts == ("anime",)
    finally:
        tab._finish_db_ui()
        tab.cleanup()
        tab.deleteLater()
