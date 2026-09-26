# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_extra_space_in_the_answer_is_the_same_title. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_extra_space_in_the_answer_is_the_same_title():
    assert _api.pick_card("Tegami bachi", [_api.TEGAMI], strict=True) is _api.TEGAMI
    assert _api.match_score("Tegami bachi", _api.TEGAMI) == 1.0
    assert _api.matched_by_typo("Tegami bachi", _api.TEGAMI) is True

test_extra_space_in_the_answer_is_the_same_title.__module__ = _api.__name__
_api.test_extra_space_in_the_answer_is_the_same_title = test_extra_space_in_the_answer_is_the_same_title

def test_short_names_are_not_glued_together():
    """«K-On!» склеенное — это «kon», уже другое слово: пробелы прощаются
    только длинным названиям."""
    kon = dict(_api.TEGAMI, name="Kon", russian=None)
    assert _api.pick_card("K-On!", [kon], strict=True) is None

test_short_names_are_not_glued_together.__module__ = _api.__name__
_api.test_short_names_are_not_glued_together = test_short_names_are_not_glued_together
