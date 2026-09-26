# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_popular_synonym_beats_an_obscure_own_name. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_popular_synonym_beats_an_obscure_own_name():
    """«За гранью» — это «Kyoukai no Kanata» (синонимом, миллион в списках), а
    не одноимённая OVA «Sweat Punch», про которую не слышал никто."""
    assert _api.synonym_only("За гранью", _api.KYOUKAI) is True
    assert _api.synonym_only("За гранью", _api.SWEAT) is False
    assert _api.pick_card("За гранью", [_api.KYOUKAI, _api.SWEAT]) is _api.KYOUKAI
    # Порядок выдачи ничего не меняет: решает известность, а не место в списке.
    assert _api.pick_card("За гранью", [_api.SWEAT, _api.KYOUKAI]) is _api.KYOUKAI

test_popular_synonym_beats_an_obscure_own_name.__module__ = _api.__name__
_api.test_popular_synonym_beats_an_obscure_own_name = test_popular_synonym_beats_an_obscure_own_name

def test_close_popularity_still_prefers_the_own_name():
    """Синонимам верим только при разнице в разы: их правит кто угодно."""
    near = dict(_api.KYOUKAI, statusesStats=_api._stats(60000))
    assert _api.pick_card("За гранью", [near, _api.SWEAT]) is _api.SWEAT

test_close_popularity_still_prefers_the_own_name.__module__ = _api.__name__
_api.test_close_popularity_still_prefers_the_own_name = test_close_popularity_still_prefers_the_own_name

def test_synonym_only_match_without_popularity_is_still_refused():
    """Без статистики (её может не быть у старой карточки) правило прежнее."""
    bare = dict(_api.KYOUKAI)
    bare.pop("statusesStats")
    assert _api.pick_card("За гранью", [bare]) is None

test_synonym_only_match_without_popularity_is_still_refused.__module__ = _api.__name__
_api.test_synonym_only_match_without_popularity_is_still_refused = test_synonym_only_match_without_popularity_is_still_refused

def test_the_more_popular_of_two_own_names_wins():
    """Совпали собственными названиями оба — берём тот, что известнее."""
    small = dict(_api.BLEACH, statusesStats=_api._stats(1000))
    big = dict(_api.BLEACH, id=999, malId=999, statusesStats=_api._stats(900000))
    assert _api.pick_card("Блич", [small, big]) is big

test_the_more_popular_of_two_own_names_wins.__module__ = _api.__name__
_api.test_the_more_popular_of_two_own_names_wins = test_the_more_popular_of_two_own_names_wins

class RawApi(_api.FakeApi):
    """Выдача Shikimori как есть: поиск там ищет и по синонимам тоже, а
    самодельная фильтрация FakeApi про них не знает."""

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        return list(self.cards)

RawApi.__module__ = _api.__name__
_api.RawApi = RawApi

def test_kyoukai_no_kanata_is_found_in_a_pack(tmp_path):
    """Живой случай из пака пользователя: ответ «За Гранью» доставал OVA «Sweat
    Punch» со своими синонимами вместо настоящего тайтла."""
    result = _api._run(tmp_path, _api._pack(_api._q5(100, answer="За Гранью")),
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=_api.RawApi([_api.KYOUKAI, _api.SWEAT]))
    answers = _api._answers(result)
    assert "Kyoukai no Kanata" in answers
    assert "Sweat Punch" not in answers and "Kigeki" not in answers

test_kyoukai_no_kanata_is_found_in_a_pack.__module__ = _api.__name__
_api.test_kyoukai_no_kanata_is_found_in_a_pack = test_kyoukai_no_kanata_is_found_in_a_pack

# ── Темы про мангу, манхву и ранобэ ──────────────────────────────────────────
@_api.pytest.mark.parametrize("name", [
    "Manga(для читающих)", "Манга", "манги побольше", "Манхва",
    "Ранобэ и новеллы", "Light Novel", "МАНХУА"])
def test_book_themes_are_recognised(name):
    assert _api.is_book_theme(name) is True

test_book_themes_are_recognised.__module__ = _api.__name__
_api.test_book_themes_are_recognised = test_book_themes_are_recognised

@_api.pytest.mark.parametrize("name", ["Аниме-опенинги", "Мангал", "Романтика",
                                  "Студии", ""])
def test_other_themes_are_not_book_themes(name):
    assert _api.is_book_theme(name) is False

test_other_themes_are_not_book_themes.__module__ = _api.__name__
_api.test_other_themes_are_not_book_themes = test_other_themes_are_not_book_themes
