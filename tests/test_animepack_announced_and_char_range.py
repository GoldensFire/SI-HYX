# -*- coding: utf-8 -*-
"""Анонсы в пак не идут; рамка персонажей проверяется при выборе рода вопроса."""
import datetime as dt

import animepack as ap
from animepack import CHAR_KIND, PackSettings

from test_animepack_new_kinds import make_anime


def test_announced_cards_are_filtered_out():
    s = PackSettings()
    assert ap.filter_anime(make_anime(), s)
    assert not ap.filter_anime(make_anime(status="anons"), s)
    assert ap.filter_anime(make_anime(status="ongoing"), s)


def test_old_cards_without_status_are_announced_by_future_date():
    future = dt.date.today().year + 2
    assert ap.is_announced({"airedOn": {"year": future}})
    assert not ap.is_announced({"airedOn": {"year": 2006}})
    assert not ap.is_announced({})
    # Строки REST (/api/characters/:id) — status и aired_on.
    assert ap.is_announced({"status": "anons", "aired_on": "2001-01-01"})
    assert ap.is_announced({"aired_on": f"{future}-01-01"})


def test_character_range_is_part_of_level_bounds():
    s = PackSettings(char_level_min=3, char_level_max=8, level_min=1,
                     level_max=15)
    assert s.level_range(CHAR_KIND) == (3, 8)
    # Рамка персонажей шире общей — поиск кандидатов её учитывает.
    wide = PackSettings(pct_songs=0, pct_chars=100, char_level_min=1,
                        char_level_max=15, level_min=5, level_max=6)
    assert wide.level_span == (1, 15)


def test_pack_title_level_has_one_decimal():
    from si_hyx_parts.animepack import pack_summary
    from types import SimpleNamespace
    rows = [SimpleNamespace(level=7), SimpleNamespace(level=7),
            SimpleNamespace(level=8), SimpleNamespace(level=7),
            SimpleNamespace(level=7)]
    assert pack_summary.pack_title("Пак", 3, rows) == "Пак № 3 (Ур. 7.2)"
