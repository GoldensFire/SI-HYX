# -*- coding: utf-8 -*-
"""База Shikimori читается и пишется порциями — и ровно как json.

Разбор двухсот мегабайт одним json.load держал GIL секундами, окно программы
висло («Не отвечает»), см. si_hyx_parts/animepack/db_json.py."""
import json

import pytest

from si_hyx_parts.animepack import db_json

SAMPLE = {
    "anime": {"1944-2026|tv|0|": {"fetched": 1.5, "cards": {
        "1": {"id": 1, "russian": "Ковбой Бибоп", "airedOn": {"year": 1998},
              "genres": [{"name": "Космос"}], "score": 8.75},
        "5": {"id": 5, "russian": "Сёгун \"\\ \u2028\n", "english": None}}}},
    "manga": {},
    "franchises": {"bebop": [{"malId": 1, "kind": "tv"}], "пусто": []},
    "memo": {"anime_favorites": {"1": 120, "5": -1},
             "characters": {"anime:1": [{"id": 3, "role": "Main"}]}},
    "ok": True, "nothing": None, "num": [1, 2.5, -3e-5],
}


def test_loads_matches_json():
    text = json.dumps(SAMPLE, ensure_ascii=False, indent=1)
    assert db_json.loads(text) == SAMPLE
    assert db_json.loads(json.dumps(SAMPLE)) == SAMPLE


def test_dump_is_byte_identical_to_json():
    assert "".join(db_json.dump_parts(SAMPLE)) == json.dumps(
        SAMPLE, ensure_ascii=False)
    odd = {"memo": {"x": {5: 1, 2.5: 2, True: 3, None: 4}}}
    assert "".join(db_json.dump_parts(odd)) == json.dumps(
        odd, ensure_ascii=False)


@pytest.mark.parametrize("bad", ["{", '{"a" 1}', '{"a": 1,}', '{"a": 1} x',
                                 '{"a": {"b": 1 "c": 2}}'])
def test_broken_json_is_rejected(bad):
    with pytest.raises(ValueError):
        db_json.loads(bad)


def test_file_roundtrip_through_the_cache(tmp_path):
    import animepack as ap
    path = tmp_path / "db.json"
    path.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    cache = ap.ShikimoriDbCache(str(path))
    assert cache.all_cards("anime")[0]["russian"] == "Ковбой Бибоп"
    cache.add_cards("anime", "sig", [{"id": 7, "russian": "Новая"}])
    assert cache.save()
    assert json.loads(path.read_text(encoding="utf-8"))["anime"]["sig"][
        "cards"]["7"]["russian"] == "Новая"


def test_reload_skips_an_unchanged_file(tmp_path, monkeypatch):
    import animepack as ap
    path = tmp_path / "db.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    cache = ap.ShikimoriDbCache(str(path))
    cache.all_cards("anime")
    reads = []
    real = db_json.load_file
    monkeypatch.setattr(db_json, "load_file",
                        lambda p: reads.append(p) or real(p))
    cache.reload()
    cache.all_cards("anime")
    assert reads == []                       # файл тот же — не перечитали
    other = ap.ShikimoriDbCache(str(path))
    other.add_cards("anime", "sig2", [{"id": 9}])
    other.save()                             # базу обновил другой держатель
    cache.reload()
    assert any(c.get("id") == 9 for c in cache.all_cards("anime"))
    # Экземпляры одного файла делят разобранную базу (db_cache_shared):
    # ни «другой», ни сам кэш файл заново не разбирали.
    assert reads == []
    # Файл сменил кто-то посторонний — тогда перечитываем.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["anime"]["sig3"] = {"cards": {"77": {"id": 77}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    cache.reload()
    assert any(c.get("id") == 77 for c in cache.all_cards("anime"))
    assert reads == [str(path)]
