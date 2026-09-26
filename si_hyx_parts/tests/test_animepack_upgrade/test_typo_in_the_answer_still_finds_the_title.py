# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_typo_in_the_answer_still_finds_the_title. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_typo_in_the_answer_still_finds_the_title():
    """Опечатка в букву — тот же тайтл, и строгость этому не мешает."""
    assert _api.pick_card("Gokukoku no Brunhildr", [_api.BRYNHILDR], strict=True) is _api.BRYNHILDR
    assert _api.match_score("Gokukoku no Brunhildr", _api.BRYNHILDR) == 1.0
    assert _api.matched_by_typo("Gokukoku no Brunhildr", _api.BRYNHILDR) is True
    assert _api.matched_by_typo("Gokukoku no Brynhildr", _api.BRYNHILDR) is False

test_typo_in_the_answer_still_finds_the_title.__module__ = _api.__name__
_api.test_typo_in_the_answer_still_finds_the_title = test_typo_in_the_answer_still_finds_the_title

@_api.pytest.mark.parametrize("a, b", [
    ("gokukoku no brunhildr", "gokukoku no brynhildr"),   # та самая буква
    ("overlord", "overload"),
    ("gochuumon wa usagi desu ka", "gochuumon wa usagi des ka"),  # длинное: две
])
def test_typo_is_the_same_title(a, b):
    assert _api.is_typo(a, b) is True

test_typo_is_the_same_title.__module__ = _api.__name__
_api.test_typo_is_the_same_title = test_typo_is_the_same_title

@_api.pytest.mark.parametrize("a, b", [
    ("air", "aria"),                        # короткие — только слово в слово
    ("naruto", "naruto ураганные хроники"),  # слов не поровну
    ("hellsing", "hellsing ultimate"),
    ("sword art online ii", "sword art online iii"),   # номер сезона
    ("yuru camp 2", "yuru camp 3"),
    ("bakemonogatari", "nisemonogatari"),   # разница в три буквы
])
def test_typo_does_not_swallow_other_titles(a, b):
    assert _api.is_typo(a, b) is False

test_typo_does_not_swallow_other_titles.__module__ = _api.__name__
_api.test_typo_does_not_swallow_other_titles = test_typo_does_not_swallow_other_titles

def test_typo_titles_are_counted_and_reported(tmp_path):
    class Fuzzy(_api.FakeApi):
        """Shikimori опечатку в запросе переживает и тайтл всё-таки отдаёт
        (проверено живым запросом) — подстрочный поиск FakeApi так не умеет."""

        def search_animes_by_name(self, name, limit=0):
            self.calls.append(name)
            return list(self.cards)

    api = Fuzzy([_api.BRYNHILDR])
    content = _api._pack(_api._q5(100, answer="Gokukoku no Brunhildr"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, add_poster=False,
                                  check_characters=False), api=api)
    assert result.typo_titles == 1 and len(result.titles) == 1
    assert "Gokukoku no Brynhildr" in result.titles[0].added
    assert any("опечаткой" in line for line in _api.example_lines(result))

test_typo_titles_are_counted_and_reported.__module__ = _api.__name__
_api.test_typo_titles_are_counted_and_reported = test_typo_titles_are_counted_and_reported
