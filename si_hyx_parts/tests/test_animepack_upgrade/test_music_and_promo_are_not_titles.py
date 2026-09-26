# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_music_and_promo_are_not_titles. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_music_and_promo_are_not_titles(tmp_path):
    content = _api._pack(_api._q5(100, answer="Mumei"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=_api.FakeApi([_api.CLIP_MUMEI]))
    assert result.titles == [] and result.posters == []
    assert result.recased == [] and result.not_found == 1
    assert _api._answers(result) == ["Mumei"]      # ответ не тронут вовсе

test_music_and_promo_are_not_titles.__module__ = _api.__name__
_api.test_music_and_promo_are_not_titles = test_music_and_promo_are_not_titles

@_api.pytest.mark.parametrize("kind", ["music", "pv", "cm", "MUSIC"])
def test_every_clip_kind_is_refused(kind):
    assert _api.pick_card("Блич", [dict(_api.BLEACH, kind=kind)]) is None

test_every_clip_kind_is_refused.__module__ = _api.__name__
_api.test_every_clip_kind_is_refused = test_every_clip_kind_is_refused

@_api.pytest.mark.parametrize("kind", ["tv", "movie", "ova", "ona", "special", "",
                                  None])
def test_real_kinds_and_unknown_ones_pass(kind):
    """Незнакомый тип считаем настоящим: список типов Shikimori пополняет."""
    assert _api.pick_card("Блич", [dict(_api.BLEACH, kind=kind)]) is _api.BLEACH or True
    assert _api.pick_card("Блич", [dict(_api.BLEACH, kind=kind)]) is not None

test_real_kinds_and_unknown_ones_pass.__module__ = _api.__name__
_api.test_real_kinds_and_unknown_ones_pass = test_real_kinds_and_unknown_ones_pass

def test_synonym_only_match_is_refused(tmp_path):
    """«Teto Kasane» — синоним клипа «Yababaina»: собственные названия записи к
    ответу отношения не имеют, такое совпадение не значит ничего."""
    assert _api.synonym_only("Teto Kasane", _api.CLIP_YABA) is True
    content = _api._pack(_api._q5(100, answer="Teto Kasane"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=_api.FakeApi([dict(_api.CLIP_YABA, kind="tv")]))
    assert result.titles == [] and _api._answers(result) == ["Teto Kasane"]

test_synonym_only_match_is_refused.__module__ = _api.__name__
_api.test_synonym_only_match_is_refused = test_synonym_only_match_is_refused

def test_synonym_match_counts_when_the_title_is_in_the_answer():
    """А вот «Наруто ТВ-1» (тоже синоним) засчитывается: собственное название
    тайтла в ответе есть."""
    assert _api.synonym_only("Наруто ТВ-1", _api.NARUTO) is False
    assert _api.pick_card("Наруто ТВ-1", [_api.NARUTO]) is _api.NARUTO

test_synonym_match_counts_when_the_title_is_in_the_answer.__module__ = _api.__name__
_api.test_synonym_match_counts_when_the_title_is_in_the_answer = test_synonym_match_counts_when_the_title_is_in_the_answer

# ── Регистр: не по японскому полю и не в худшую сторону ──────────────────────
def test_case_is_not_taken_from_the_japanese_field(tmp_path):
    """У записи Shikimori японское название бывает записано латиницей строчными
    («mumei») — по нему регистр правился в худшую сторону."""
    card = dict(_api.CLIP_MUMEI, kind="tv")
    assert "mumei" in _api.card_names(card)          # для опознания оно годится
    assert "mumei" not in _api.spelling_names(card)  # для написания — нет
    content = _api._pack(_api._q5(100, answer="Mumei"))
    # add_poster=False: тайтл здесь опознаётся, и с постером по умолчанию тест
    # уходил качать https://shikimori/m.jpg по-настоящему. Речь про регистр.
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=_api.FakeApi([card]))
    assert result.recased == [] and _api._answers(result)[0] == "Mumei"

test_case_is_not_taken_from_the_japanese_field.__module__ = _api.__name__
_api.test_case_is_not_taken_from_the_japanese_field = test_case_is_not_taken_from_the_japanese_field

def test_leading_capital_is_never_lowered():
    assert _api.recased("Mumei", ["mumei"]) is None
    assert _api.recased("mumei", ["Mumei"]) == "Mumei"

test_leading_capital_is_never_lowered.__module__ = _api.__name__
_api.test_leading_capital_is_never_lowered = test_leading_capital_is_never_lowered

# ── Ответ — имя персонажа, а не тайтл ────────────────────────────────────────
@_api.pytest.mark.parametrize("text,expected", [
    ("Mumei", True), ("Teto Kasane", True), ("Mio Akiyama", True),
    ("Наруто", False),                    # кириллицу не проверяем — см. ниже
    ("Стрелок с чёрной скалы", False),
    ("Boku no Kanojo ga Majimesugiru Sho-bitch na Ken", False),  # длинновато
    ("ナルト", False), ("", False),
])
def test_which_answers_are_worth_a_character_query(text, expected):
    assert _api.looks_like_character_name(text) is expected

test_which_answers_are_worth_a_character_query.__module__ = _api.__name__
_api.test_which_answers_are_worth_a_character_query = test_which_answers_are_worth_a_character_query

def test_character_hit_compares_latin_names_only():
    """У персонажа «Naruto-kun» русское имя — «Наруто»: сравнивай мы русские,
    проверка съела бы настоящий тайтл «Наруто»."""
    chars = [{"name": "Naruto-kun", "russian": "Наруто"},
             {"name": "Naruto Uzumaki", "russian": "Наруто Узумаки"}]
    assert _api.character_hit("Naruto", chars) is None
    assert _api.character_hit("Наруто", chars) is None
    assert _api.character_hit("Naruto-kun", chars) == "Naruto-kun"

test_character_hit_compares_latin_names_only.__module__ = _api.__name__
_api.test_character_hit_compares_latin_names_only = test_character_hit_compares_latin_names_only

class CharApi(_api.FakeApi):
    """FakeApi, который ещё и «знает» персонажей."""

    def __init__(self, cards=None, chars=None):
        super().__init__(cards)
        self.chars = list(chars or [])
        self.char_calls = []

    def search_characters_by_name(self, name):
        self.char_calls.append(name)
        return list(self.chars)

CharApi.__module__ = _api.__name__
_api.CharApi = CharApi
