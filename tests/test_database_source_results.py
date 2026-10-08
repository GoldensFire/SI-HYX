"""Source failures retain reasons; missing aliases never poison caches."""
from types import SimpleNamespace
import re
import animepack_api as api
from si_hyx_parts.animepack.ru_snapshot_repair import repair_snapshot
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig


def source(body, status=200):
    current = api.ShikimoriApi(client=SimpleNamespace())
    response = SimpleNamespace(status_code=status, text=body, raise_for_status=lambda: None)
    current._get = lambda *args, **kwargs: response
    return current


def test_access_states_are_not_numeric_measurements():
    current = source("Доступ ограничен 18+", 403)
    result = current.title_favorites_result(1, "manga", "/mangas/1-title")
    assert result["status"] == "AGE_RESTRICTED" and result["value"] == -1
    assert current.title_favorites(1, "manga", "/mangas/1-title") == -1
    assert source("missing", 404).title_favorites_result(1, "anime", "/animes/1")["status"] == "NOT_FOUND"


def test_zero_requires_a_real_page_and_an_unreadable_widget_is_not_zero():
    result = source('body class="p-mangas-show"').title_favorites_result(1, "manga", "/mangas/1")
    assert result["status"] == "NORMAL" and result["value"] == 0
    result = source('p-mangas-show <div class="b-favoured"><div class="count">?</div></div>').title_favorites_result(
        1, "manga", "/mangas/1")
    assert result["status"] == "ERROR" and result["value"] == -1


def test_batch_censorship_preserves_all_ids_without_filters():
    calls = []
    def send(query, variables):
        calls.append(query)
        groups = re.findall(r'p(\d+): mangas\(ids: "([0-9,]+)"', query)
        return {f"p{alias}": [{"id": ident, "isCensored": int(ident) % 2 == 0}
                              for ident in ids.split(",")] for alias, ids in groups}
    current = api.ShikimoriApi(client=SimpleNamespace(_graphql=send))
    current.limiter = SimpleNamespace(acquire=lambda: None)
    result = current.title_censorship_flags(range(1, 802))
    assert set(result) == set(range(1, 802)) and len(calls) == 2
    assert result[2] is True and result[3] is False
    assert all("season:" not in query and "genre:" not in query for query in calls)


def test_missing_franchise_alias_is_not_an_empty_franchise():
    current = api.ShikimoriApi(client=SimpleNamespace(_graphql=lambda *args: {"f0": []}))
    current.limiter = SimpleNamespace(acquire=lambda: None)
    assert current.franchise_parts(["first", "second"]) == {"first": []}
    assert "second" in current._franchise_errors


def test_cached_cohort_repair_preserves_remote_catalog_age():
    rows = [{"id": str(i), "kind": "manga", "status": "NORMAL", "raw_metric": i}
            for i in (1, 2)]
    rows.append({"id": "3", "kind": "", "status": "RIGHTS_RESTRICTED", "raw_metric": 3})
    old = {"version": 1, "complete": True, "timestamp": 10, "titles": rows,
           "metric": "bookmarks", "type_fallback": "complete_site_catalog_types_unresolved"}
    result = repair_snapshot(old, "remanga", RuPopularityConfig(min_samples=2), lambda: 100)
    assert result["catalog_timestamp"] == 10 and result["timestamp"] == 100
    assert result["distributions"] == {"manga": [1, 2]}
    assert old["timestamp"] == 10


def test_reclassified_catalog_is_not_a_fresh_remote_refresh(tmp_path):
    from test_manga_db_refresh_audit import database
    from tools.manga_db_refresh import audit
    from si_hyx_parts.animepack.ru_popularity_math import SNAPSHOT_GROUP
    cache = database(tmp_path)
    row = cache.memo(SNAPSHOT_GROUP, "remanga")
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", {**row, "timestamp": 200,
                                                   "catalog_timestamp": 80})
    assert not audit(cache, 90)["success"]
