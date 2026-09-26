# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_slash_answer_is_split_into_both_names. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_slash_answer_is_split_into_both_names():
    """«Ueno-san wa Bukiyou/ Неуклюжая Уэно» — это одно и то же название двумя
    строками: Shikimori и сам показывает тайтл так."""
    assert _api.answer_queries(["Ueno-san wa Bukiyou/ Неуклюжая Уэно"]) == [
        "Ueno-san wa Bukiyou/ Неуклюжая Уэно", "Ueno-san wa Bukiyou",
        "Неуклюжая Уэно"]

test_slash_answer_is_split_into_both_names.__module__ = _api.__name__
_api.test_slash_answer_is_split_into_both_names = test_slash_answer_is_split_into_both_names

def test_whole_answer_is_tried_before_its_parts():
    """«Fate/Zero» — цельное название, и находится оно раньше, чем дело дойдёт
    до разбиения по черте."""
    assert _api.answer_queries(["Fate/Zero"])[0] == "Fate/Zero"

test_whole_answer_is_tried_before_its_parts.__module__ = _api.__name__
_api.test_whole_answer_is_tried_before_its_parts = test_whole_answer_is_tried_before_its_parts

def test_slash_answer_finds_the_title(tmp_path):
    """Строкой целиком тайтл не опознаётся, а каждой частью — да."""
    api = _api.FakeApi([_api.UENO])
    content = _api._pack(_api._q5(100, answer="Ueno-san wa Bukiyou/ Неуклюжая Уэно"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=api)
    assert len(result.titles) == 1
    assert "Уэно-сан, какая же Вы неуклюжая" in _api._answers(result)
    assert "How Clumsy you are, Miss Ueno" in _api._answers(result)

test_slash_answer_finds_the_title.__module__ = _api.__name__
_api.test_slash_answer_finds_the_title = test_slash_answer_finds_the_title

def test_slash_answer_counts_as_an_exact_match(tmp_path):
    """Совпала часть — значит, совпало точно: постер и написание тут уместны."""
    kokoro = dict(_api.UENO, id=11887, malId=11887, russian="Связь сердец",
                  name="Kokoro Connect", english="Kokoro Connect",
                  synonyms=["Kokoroco"])
    content = _api._pack(_api._q5(100, answer="Kokoro Connect/Связь сердец"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=_api.FakeApi([kokoro]))
    assert result.exact_titles == 1
    assert "Kokoroco" in _api._answers(result)

test_slash_answer_counts_as_an_exact_match.__module__ = _api.__name__
_api.test_slash_answer_counts_as_an_exact_match = test_slash_answer_counts_as_an_exact_match

# ── Несколько точных совпадений: побеждает известность ───────────────────────
def _stats(watchers: int) -> list:
    return [{"status": "completed", "count": watchers}]

_stats.__module__ = _api.__name__
_api._stats = _stats
