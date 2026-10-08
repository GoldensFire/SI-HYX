"""Database maintenance has independent coverage and verifiable outcomes."""
from types import SimpleNamespace
import sqlite3
import pytest
import animepack as api
from si_hyx_parts.animepack.db_backup import backup_database
from si_hyx_parts.animepack.ru_catalog_snapshot import _snapshot
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig


def card(ident, kind="tv"):
    return {"id": str(ident), "malId": str(ident), "russian": f"Title {ident}",
            "kind": kind, "score": 8, "airedOn": {"year": 1999},
            "statusesStats": [{"status": "completed", "count": 100000}]}


def test_whole_database_parts_ignore_all_pack_settings():
    settings = api.PackSettings(pack_manga=False, pct_manga=0, score_from=10,
                                year_from=2025, year_to=2025, kinds={})
    assert api.db_refresh_parts(None, settings) == (
        "anime", "manga", "remanga", "mangalib", "favorites", "franchises")


def test_refresh_is_unfiltered_and_resumes_a_saved_partial_catalog(tmp_path):
    calls, halt = [], [False]

    class Source:
        def random_animes(self, page, **filters):
            calls.append((page, filters))
            if page == 1:
                halt[0] = True
                return [card(1)]
            return []

    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    settings = api.PackSettings(kinds={"movie": True}, year_from=2025,
                                year_to=2025, score_from=10, genres_exclude=[12])
    generator = api.AnimePackGenerator(settings, db_cache=cache, shikimori=Source(),
                                       should_stop=lambda: halt[0])
    generator.refresh_db(("anime",))
    assert calls[0][1]["season"] == ""
    assert calls[0][1]["score"] == 0 and calls[0][1]["genres_exclude"] == ()
    assert set(calls[0][1]["kinds"]) == set(api.ANIME_KINDS)
    assert settings.year_from == 2025 and settings.genres_exclude == [12]
    halt[0] = False
    cache.reload()
    resumed = api.AnimePackGenerator(settings, db_cache=cache, shikimori=Source())
    assert resumed.refresh_db(("anime",)) == 1
    assert [page for page, _ in calls] == [1, 2]
    assert resumed._db_refresh_report["status"] == "COMPLETE"


def test_page_ceiling_is_a_failed_refresh_not_success(tmp_path):
    source = SimpleNamespace(random_animes=lambda page, **kwargs: [card(page)])
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    generator = api.AnimePackGenerator(api.PackSettings(), shikimori=source, db_cache=cache)
    generator.FULL_MAX_PAGES = 1
    with pytest.raises(api.AnimePackError, match="не завершено"):
        generator.refresh_db(("anime",))
    assert cache.all_cards("anime")
    assert generator._db_refresh_report["status"] == "ERROR"


def test_legacy_unknown_counter_is_retried_and_zero_is_valid(tmp_path):
    from si_hyx_parts.animepack.db_favorites_refresh import refresh_favorites
    calls = []
    source = SimpleNamespace(title_favorites=lambda ident, *args: calls.append(ident) or 0)
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("anime", "old", [card(1)])
    cache.remember_memo("anime_favorites", 1, -1)
    generator = SimpleNamespace(shikimori=source, db_cache=cache, stopped=lambda: False,
                                log=lambda message: None)
    refresh_favorites(generator)
    assert calls == [1]
    assert cache.memo("anime_favorites", 1) == 0
    assert generator._favorites_refresh_report["anime"]["received"] == 1


def test_age_preflight_preserves_unknown_without_a_page_request(tmp_path):
    from si_hyx_parts.animepack.db_favorites_refresh import refresh_favorites, ACCESS_GROUP
    source = SimpleNamespace(title_censorship_flags=lambda ids, target, **kwargs: {1: True},
                             title_favorites=lambda *args: pytest.fail("closed page requested"))
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("manga", "old", [card(1, "manga")])
    generator = SimpleNamespace(shikimori=source, db_cache=cache, stopped=lambda: False,
                                log=lambda message: None)
    refresh_favorites(generator)
    assert cache.memo("manga_favorites", 1) is None
    assert cache.memo(ACCESS_GROUP, "manga:1")["status"] == "AGE_RESTRICTED"
    assert generator._favorites_refresh_report["manga"]["restricted"] == 1


def test_restricted_unknown_types_do_not_merge_valid_population_cohorts():
    rows = [{"id": str(i), "kind": kind, "status": "NORMAL", "raw_metric": i}
            for i, kind in ((1, "manga"), (2, "manga"), (3, "manhwa"), (4, "manhwa"))]
    rows.append({"id": "5", "kind": "", "status": "RIGHTS_RESTRICTED", "raw_metric": 10})
    result = _snapshot(SimpleNamespace(source="remanga", metric="bookmarks"),
                       RuPopularityConfig(min_samples=2), rows)
    assert result["distributions"] == {"manga": [1, 2], "manhwa": [3, 4]}
    assert result["type_fallback"] == ""


def test_backup_includes_committed_sqlite_memo(tmp_path):
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("anime", "all", [card(1)])
    cache.save()
    with sqlite3.connect(cache.path + ".memo.sqlite") as connection:
        connection.execute("CREATE TABLE probe (value INTEGER)")
        connection.execute("INSERT INTO probe VALUES (42)")
    output = backup_database(cache, tmp_path / "backup")
    assert (output / "database-before.json.bak").read_bytes() == (tmp_path / "db.json").read_bytes()
    with sqlite3.connect(output / "memo-before.sqlite") as connection:
        assert connection.execute("SELECT value FROM probe").fetchone()[0] == 42


def test_generation_retries_legacy_unknown_and_does_not_cache_new_failures(tmp_path):
    calls = []
    source = SimpleNamespace(title_favorites=lambda ident, *args: calls.append(ident) or -1)
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.remember_memo("anime_favorites", 1, -1)
    generator = api.AnimePackGenerator(api.PackSettings(), shikimori=source, db_cache=cache)
    candidate = api.SongCandidate({}, card(1))
    assert generator._title_favorites(candidate) == -1
    assert calls == [1]
    assert cache.memo("favorites_access_status_v1", "anime:1")["status"] == "ERROR"
    assert generator._title_favorites(candidate) == -1
    assert calls == [1]  # recent failure has a bounded retry delay, not a numeric success


def test_failed_write_cannot_be_reported_as_complete(tmp_path, monkeypatch):
    from si_hyx_parts.animepack.db_refresh_report import finish_report
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    monkeypatch.setattr(cache, "save", lambda: False)
    generator = SimpleNamespace(db_cache=cache, stopped=lambda: False)
    report = finish_report(generator, (), 0)
    assert report["status"] == "ERROR" and report["saved"] is False
    assert "сохранить" in report["failures"][0]
