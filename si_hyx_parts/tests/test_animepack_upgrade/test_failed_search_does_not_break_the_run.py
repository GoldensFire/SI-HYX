# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_failed_search_does_not_break_the_run. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_failed_search_does_not_break_the_run(tmp_path):
    class Broken(_api.FakeApi):
        def search_animes_by_name(self, name, limit=0):
            raise RuntimeError("Shikimori лёг")

    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=Broken())
    assert result.titles == [] and result.path        # пак всё равно записан

test_failed_search_does_not_break_the_run.__module__ = _api.__name__
_api.test_failed_search_does_not_break_the_run = test_failed_search_does_not_break_the_run

# ── Опознание тайтла ─────────────────────────────────────────────────────────
def test_strict_match_needs_exact_name():
    cards = [_api.NARUTO]
    assert _api.pick_card("наруто!", cards, strict=True) is _api.NARUTO   # знаки не в счёт
    assert _api.pick_card("Наруто: Ураганные хроники", cards, strict=True) is None

test_strict_match_needs_exact_name.__module__ = _api.__name__
_api.test_strict_match_needs_exact_name = test_strict_match_needs_exact_name

def test_loose_match_accepts_close_names():
    """С выключенной строгостью засчитывается опечатка, но не другой тайтл."""
    assert _api.pick_card("Нарутоо", [_api.NARUTO], strict=False) is _api.NARUTO
    assert _api.pick_card("Блич", [_api.NARUTO], strict=False) is None

test_loose_match_accepts_close_names.__module__ = _api.__name__
_api.test_loose_match_accepts_close_names = test_loose_match_accepts_close_names
