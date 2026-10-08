"""Large-cache migration preserves memo rows, backups and maintenance semantics."""
import json

import animepack as ap


def migrated(tmp_path, monkeypatch):
    from si_hyx_parts.animepack import db_memo_migration
    path = tmp_path / "db.json"
    cache = ap.ShikimoriDbCache(str(path))
    cache.remember_memo("manga_favorites", "1", 123)
    cache.remember_memo("characters", "2", {"names": ["Person"]})
    assert cache.save()
    monkeypatch.setattr(db_memo_migration, "THRESHOLD", 0)
    cache.remember_memo("characters", "3", ["Other"])
    assert cache.save()
    return path, cache


def test_sqlite_migration_keeps_all_rows_and_a_readable_backup(tmp_path, monkeypatch):
    path, cache = migrated(tmp_path, monkeypatch)
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["memo"] == {} and disk["memo_storage"]["version"] == 1
    assert path.with_name(path.name + ".before-memo-split").is_file()
    cache._shared["data"] = None
    fresh = ap.ShikimoriDbCache(str(path))
    assert fresh.memo("manga_favorites", "1") == 123
    assert fresh.memo("characters", "2") == {"names": ["Person"]}
    assert fresh.memo("characters", "3") == ["Other"]


def test_existing_memo_updates_do_not_rewrite_catalog(tmp_path, monkeypatch):
    path, cache = migrated(tmp_path, monkeypatch)
    stamp = path.stat().st_mtime_ns
    cache.remember_memo("characters", "2", {"names": ["Changed"]})
    assert cache.save()
    assert path.stat().st_mtime_ns == stamp
    value = cache.memo("characters", "2")
    value["names"].clear()
    assert cache.memo("characters", "2") == {"names": ["Changed"]}


def test_individual_lookup_does_not_count_the_entire_category(tmp_path, monkeypatch):
    _, cache = migrated(tmp_path, monkeypatch)
    statements = []
    store = cache._shared["memo_store"]
    store.connection.set_trace_callback(statements.append)
    assert cache.memo("characters", "2") == {"names": ["Person"]}
    assert not any("COUNT(" in query.upper() for query in statements)


def test_selective_clear_does_not_remove_other_sqlite_groups(tmp_path, monkeypatch):
    path, cache = migrated(tmp_path, monkeypatch)
    assert cache.part_counts()["favorites"]["count"] == 1
    assert cache.clear_part("favorites") == 1
    assert cache.save()
    assert cache.memo("manga_favorites", "1") is None
    assert cache.memo_group("characters") == {"2": {"names": ["Person"]}, "3": ["Other"]}
