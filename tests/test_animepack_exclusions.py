# -*- coding: utf-8 -*-
"""Чужие паки закрывают не только тайтл, но и всю его франшизу.

Кнопка «Не повторять из паков…» читает правильные ответы готовых .siq. Корень
названия закрывает лишь одинаково названные части («Наруто» и «Наруто:
Ураганные хроники»), а у «Fate/Zero» и «Fate/stay night» корни разные при одной
франшизе — её и добираем по каталогу (просьба пользователя).
"""
import zipfile

import animepack as ap
from animepack import PackSettings, SongCandidate

from test_animepack_new_kinds import make_anime


def _pack_with_answer(path, anime):
    """Готовый .siq, в котором спрошен этот тайтл."""
    settings = PackSettings(rounds=1, themes=1, questions=1)
    cand = SongCandidate(song={}, anime=anime, kind=ap.FRAME_KIND)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml([cand], settings))
    return str(path)


def _fate(mal, russian, name):
    return make_anime(malId=mal, id=mal, russian=russian, name=name,
                      english=name, franchise="fate")


def test_the_whole_franchise_is_closed_even_under_another_name(tmp_path):
    zero = _fate(1, "Судьба: Начало", "Fate/Zero")
    night = _fate(2, "Судьба: Ночь схватки", "Fate/stay night")
    old = _pack_with_answer(tmp_path / "старый.siq", zero)

    settings = PackSettings(exclude_siq=[old])
    gen = ap.AnimePackGenerator(settings,
                                frames_history_path=str(tmp_path / "f.json"))
    # Каталог уже набран — франшизу берём оттуда, сети это не стоит ничего.
    gen.db_cache.add_cards("anime", ap.shiki_cache_signature(settings),
                           [zero, night])
    gen.load_exclusions()

    assert not gen._accept_anime(zero, 1, set(), set())
    # Другое название, та же франшиза — тоже мимо.
    assert not gen._accept_anime(night, 2, set(), set())
    other = make_anime(malId=9, id=9, russian="Стальной алхимик",
                       name="Fullmetal Alchemist", english="Fullmetal Alchemist",
                       franchise="fma")
    assert gen._accept_anime(other, 9, set(), set())


def test_a_matching_root_closes_the_franchise_on_the_fly(tmp_path):
    """Каталога под рукой нет — франшиза закрывается первой же встреченной
    частью с совпавшим названием."""
    zero = _fate(1, "Судьба: Начало", "Fate/Zero")
    night = _fate(2, "Судьба: Ночь схватки", "Fate/stay night")
    old = _pack_with_answer(tmp_path / "старый.siq", zero)
    gen = ap.AnimePackGenerator(PackSettings(exclude_siq=[old]),
                                frames_history_path=str(tmp_path / "f.json"))
    gen.load_exclusions()
    assert not gen._excluded_franchises
    assert not gen._accept_anime(zero, 1, set(), set())
    assert gen._excluded_franchises == {"fate"}
    assert not gen._accept_anime(night, 2, set(), set())
