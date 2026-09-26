# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_character_answer_is_left_alone. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_character_answer_is_left_alone(tmp_path):
    api = _api.CharApi([_api.LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _api._pack(_api._q5(100, answer="Teto Kasane"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, strict_match=False),
                  api=api)
    assert api.char_calls == ["Teto Kasane"]
    assert result.titles == [] and result.posters == []
    assert len(result.skipped_titles) == 1
    assert result.skipped_titles[0].kind == "character"
    assert _api._answers(result) == ["Teto Kasane"]

test_character_answer_is_left_alone.__module__ = _api.__name__
_api.test_character_answer_is_left_alone = test_character_answer_is_left_alone

def test_exact_title_is_not_second_guessed(tmp_path):
    """«Shiki», «Monster», «Goblin Slayer» — настоящие аниме, у которых герой
    зовётся так же, и точный персонаж там находится всегда. Раз собственное
    название совпало точь-в-точь, спрашивать про персонажа незачем."""
    card = {"id": 8, "malId": 8, "russian": "Усопшие", "name": "Shiki",
            "english": "Corpse Demon", "licenseNameRu": "", "synonyms": [],
            "kind": "tv"}
    api = _api.CharApi([card], chars=[{"name": "Shiki", "russian": "Сики"}])
    content = _api._pack(_api._q5(100, answer="Shiki"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=api)
    assert api.char_calls == []                 # лишнего запроса не было
    assert result.titles and result.skipped_titles == []
    assert "Усопшие" in _api._answers(result)

test_exact_title_is_not_second_guessed.__module__ = _api.__name__
_api.test_exact_title_is_not_second_guessed = test_exact_title_is_not_second_guessed

def test_character_check_can_be_switched_off(tmp_path):
    api = _api.CharApi([_api.LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _api._pack(_api._q5(100, answer="Teto Kasane"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, strict_match=False,
                                  check_characters=False), api=api)
    assert api.char_calls == [] and result.skipped_titles == []
    assert result.titles

test_character_check_can_be_switched_off.__module__ = _api.__name__
_api.test_character_check_can_be_switched_off = test_character_check_can_be_switched_off

def test_same_character_is_asked_once(tmp_path):
    api = _api.CharApi([_api.LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _api._pack(_api._q5(100, answer="Teto Kasane") + _api._q5(200, answer="Teto Kasane"))
    _api._run(tmp_path, content,
         _api.UpgradeSettings(strip_specials=False, strict_match=False), api=api)
    assert api.char_calls == ["Teto Kasane"]

test_same_character_is_asked_once.__module__ = _api.__name__
_api.test_same_character_is_asked_once = test_same_character_is_asked_once

def test_skipped_characters_are_reported(tmp_path):
    api = _api.CharApi([_api.LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _api._pack(_api._q5(100, answer="Teto Kasane"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, strict_match=False),
                  api=api)
    lines = _api.example_lines(result)
    assert any("пропущено как имена персонажей: 1" in l for l in lines)

test_skipped_characters_are_reported.__module__ = _api.__name__
_api.test_skipped_characters_are_reported = test_skipped_characters_are_reported

# ── Функция 5: повторяющийся текст темы ──────────────────────────────────────
def _q5_items(price: int, items: str, answer: str = "Ответ") -> str:
    """Вопрос v5 с произвольным содержимым (несколько <item> подряд)."""
    return (f'<question price="{price}"><params>'
            f'<param name="question" type="content">{items}</param></params>'
            f"<right><answer>{answer}</answer></right></question>")

_q5_items.__module__ = _api.__name__
_api._q5_items = _q5_items

def _shot(name: str = "кадр.jpg") -> str:
    return f'<item type="image" isRef="True">{name}</item>'

_shot.__module__ = _api.__name__
_api._shot = _shot
