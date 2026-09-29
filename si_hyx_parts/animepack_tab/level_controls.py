# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Отдельные рамки сложности: арты и книги. Namespace: animepack_tab.

Общая «Сложность пака» годится кадрам, песням и персонажам, но не всему. Арт с
Pixiv — это не кадр из аниме: по фанатскому рисунку тайтл узнают куда хуже, и
под арты обычно берут заметные тайтлы, даже когда остальной пак собран из
редкостей. А у книг узнаваемость и меряется-то иначе (см. MANGA_INDEX_LEVELS),
так что общая рамка им просто не подходит. Поэтому у тех и других рамка своя
(просьба пользователя).
"""
from __future__ import annotations

import animepack_tab as _api

ART_TIP = ("Насколько узнаваемы тайтлы, которым достанутся АРТЫ (и Pixiv, и "
           "сгенерированные). По рисунку тайтл узнают хуже, чем по кадру из "
           "самого аниме, поэтому под арты обычно берут тайтлы известнее "
           "остального пака: «от 1 до 6» при общей рамке «от 1 до 15».\n"
           "Шкала та же: 1 — знают все, 15 — не знает никто.")
MANGA_TIP = ("Насколько узнаваемы КНИГИ в паке. Шкала общая с аниме, но "
             "книжный счёт переводится на неё отдельно: читателей у манги на "
             "порядок меньше, чем зрителей, и мерить их одной линейкой "
             "нельзя.\n"
             "Книга БЕЗ аниме упирается в потолок: легче 6-го уровня она не "
             "бывает, как бы её ни читали. Первые уровни — «узнают все» — "
             "остаются за тем, что показывали сериалом: «Прощай, Эри» знают "
             "только читавшие, а «Восхождение героя щита» — все, кто видел "
             "аниме.\n"
             "Манга С АНИМЕ-ЭКРАНИЗАЦИЕЙ поэтому и считается по сериалу: ей "
             "засчитывается узнаваемость самого аниме, и стоит такой вопрос "
             "на два очка дороже вопроса-кадра по тому же тайтлу.")


PLOT_TIP = ("Насколько узнаваемы тайтлы, по которым спрашивают СЮЖЕТ. Рамка "
            "отдельная, потому что играет тут не узнаваемость названия: в "
            "режиме «ответ — деталь сюжета» тайтл в вопросе назван прямо, и "
            "вопрос берут те, кто помнит сами события, — а помнят их только у "
            "заметных тайтлов.\n"
            "Шкала та же: 1 — знают все, 15 — не знает никто.")


AVG_TIP = ("Куда должна выйти СЕРЕДИНА этой части пака. Рамка «от … до» "
           "задаёт, что вообще пускать, а средняя — на что выйдет большинство: "
           "«от 1 до 15, в среднем 4» даёт редкие крайности и середину около "
           "четвёрки.\n"
           "«Любая» — не следить: тогда эти вопросы держат общую среднюю пака "
           "вместе со всеми остальными. Заданная средняя, наоборот, считается "
           "ОТДЕЛЬНО и в общую среднюю пака не входит.")


def _avg(tab, tip):
    """Прежний интерфейс значения теперь принадлежит общей полосе."""
    return tab._new_level_bar.avg_control


def _range(tip, low=1, high=None):
    from .difficulty_range import DifficultyRange
    high = _api.MAX_LEVEL if high is None else high
    bar = DifficultyRange(low, high, minimum=1, maximum=_api.MAX_LEVEL,
                          average=True)
    bar.setMinimumWidth(240)
    bar.setToolTip(tip + "\n" + AVG_TIP)
    return bar


SONG_TIP = ("Насколько узнаваемы тайтлы, которым достанутся ПЕСЕННЫЕ вопросы "
            "(и вопросы-ролики). Шкала та же, что у общей сложности: 1 — "
            "знают все, 15 — не знает никто.\n"
            "Это НЕ «Сложность AMQ» из состава пака: та величина — доля "
            "игроков сайта Anime Music Quiz, угадавших САМУ ПЕСНЮ, а здесь "
            "речь про узнаваемость аниме, как и у кадров, артов и книг "
            "(просьба пользователя).\n"
            "Пока рамку не трогали, она повторяет общую «Сложность» — так же "
           "работали и настройки, сохранённые до её появления.")

STUDIO_TIP = ("Насколько узнаваемы тайтлы в вопросах на СТУДИЮ. Рамка "
              "отдельная: игрок видит несколько кадров разных аниме и должен "
              "найти их общего создателя, поэтому сложность такого вопроса "
              "не обязана совпадать со сложностью обычных кадров.\n"
              "Шкала та же: 1 — знают все, 15 — не знает никто. Пока рамку "
              "не трогали, она повторяет общую сложность пака.")


def build_song(tab):
    """Рамка узнаваемости аниме у песенных вопросов и роликов."""
    tab.song_level_range = _range(SONG_TIP)
    tab._new_level_bar = tab.song_level_range
    tab.sp_song_level_from = tab.song_level_range.low_control
    tab.sp_song_level_to = tab.song_level_range.high_control
    tab.sp_song_level_avg = _avg(tab, AVG_TIP)


def build_studio(tab):
    """Своя рамка узнаваемости вопросов на студию."""
    tab.studio_level_range = _range(STUDIO_TIP)
    tab._new_level_bar = tab.studio_level_range
    tab.sp_studio_level_from = tab.studio_level_range.low_control
    tab.sp_studio_level_to = tab.studio_level_range.high_control
    tab.sp_studio_level_avg = _avg(tab, AVG_TIP)


def build_art(tab):
    """Рамка сложности для артов — рядом с общей «Сложностью пака»."""
    tab.art_level_range = _range(ART_TIP)
    tab._new_level_bar = tab.art_level_range
    tab.sp_art_level_from = tab.art_level_range.low_control
    tab.sp_art_level_to = tab.art_level_range.high_control
    tab.sp_art_level_avg = _avg(tab, AVG_TIP)


def refresh_art(tab):
    """Показ рамок теперь общий — level_panel. Имя оставлено прежним."""
    from .level_panel import refresh
    refresh(tab)


def build_plot(tab):
    """Рамка сложности вопросов по сюжету — внутри их же настроек."""
    tab.plot_level_range = _range(PLOT_TIP)
    tab._new_level_bar = tab.plot_level_range
    tab.sp_plot_level_from = tab.plot_level_range.low_control
    tab.sp_plot_level_to = tab.plot_level_range.high_control
    tab.sp_plot_level_avg = _avg(tab, AVG_TIP)


def refresh_plot(tab):
    """Показ рамок теперь общий — level_panel. Имя оставлено прежним."""
    from .level_panel import refresh
    refresh(tab)


CHAR_TIP = ("Сложность тайтлов, из которых берутся ПЕРСОНАЖИ. Уровень героя "
            "ровно равен уровню его тайтла; число добавивших героя в избранное "
            "его больше не сдвигает. Рамка отдельная от других видов вопросов. "
            "Шкала та же: 1 — знают все, 15 — не знает никто.")


def build_char(tab):
    """Своя рамка и средняя сложность вопросов-ПЕРСОНАЖЕЙ."""
    tab.char_level_range = _range(CHAR_TIP)
    tab._new_level_bar = tab.char_level_range
    tab.sp_char_level_from = tab.char_level_range.low_control
    tab.sp_char_level_to = tab.char_level_range.high_control
    tab.sp_char_avg = _avg(tab, AVG_TIP)


def build_manga(tab):
    """Рамка сложности книг и доли внутри книжной части."""
    tab.manga_level_range = _range(MANGA_TIP)
    tab._new_level_bar = tab.manga_level_range
    tab.sp_manga_level_from = tab.manga_level_range.low_control
    tab.sp_manga_level_to = tab.manga_level_range.high_control
    tab.sp_manga_level_avg = _avg(tab, AVG_TIP)
    tab.sp_manga_adapted = _api.QSpinBox()
    tab.sp_manga_adapted.setRange(0, 100)
    tab.sp_manga_adapted.setValue(50)
    tab.sp_manga_adapted.setSuffix(" %")
    tab.sp_manga_adapted.setToolTip(
        "Сколько книжных вопросов достанется манге, у которой ЕСТЬ "
        "аниме-экранизация. Такую книгу узнают по сериалу, и вопрос выходит "
        "заметно легче: её цена считается по узнаваемости самого аниме плюс "
        "два очка.\n"
        "Остальные места уходят книгам без экранизации — их узнают только те, "
        "кто читал.\n"
        "Доля соблюдается мягко: если подходящих книг в каталоге подряд не "
        "находится, генератор берёт что есть и пишет об этом в журнал.")
    tab.sp_manga_manhwa = _api.QSpinBox()
    tab.sp_manga_manhua = _api.QSpinBox()
    for sp, tip in ((tab.sp_manga_manhwa,
                     "Доля МАНХВЫ (корейские издания) среди книжных вопросов."),
                    (tab.sp_manga_manhua,
                     "Доля МАНЬХУА (китайские издания) среди книжных вопросов.")):
        sp.setRange(0, 100)
        sp.setValue(0)
        sp.setSuffix(" %")
        sp.setToolTip(tip + "\nОстальное достаётся японской манге и ранобэ. "
                      "Без отдельной доли корейские и китайские издания в "
                      "паке почти не появлялись: японской манги в каталоге "
                      "Shikimori на порядок больше.\nСчитается только среди "
                      "включённых выше типов изданий.")


def place_manga(tab, grid, row):
    """Книжные ДОЛИ в сетке «Манга»; сама рамка сложности живёт в «Аниме»."""
    grid.addWidget(tab._lab("С аниме"), row, 0)
    grid.addWidget(tab.sp_manga_adapted, row, 1)
    row += 1
    grid.addWidget(tab._lab("Манхва"), row, 0)
    grid.addWidget(tab.sp_manga_manhwa, row, 1)
    grid.addWidget(tab._lab("Маньхуа"), row, 2)
    grid.addWidget(tab.sp_manga_manhua, row, 3)
    return row + 1


def collect(tab, settings):
    settings.song_level_min = tab.sp_song_level_from.value()
    settings.song_level_max = max(tab.sp_song_level_from.value(),
                                  tab.sp_song_level_to.value())
    settings.song_level_avg = tab.sp_song_level_avg.value()
    settings.studio_level_min = tab.sp_studio_level_from.value()
    settings.studio_level_max = max(tab.sp_studio_level_from.value(),
                                    tab.sp_studio_level_to.value())
    settings.studio_level_avg = tab.sp_studio_level_avg.value()
    settings.char_level_min = tab.sp_char_level_from.value()
    settings.char_level_max = max(tab.sp_char_level_from.value(),
                                  tab.sp_char_level_to.value())
    settings.char_level_avg = tab.sp_char_avg.value()
    settings.plot_level_min = tab.sp_plot_level_from.value()
    settings.plot_level_max = tab.sp_plot_level_to.value()
    settings.plot_level_avg = tab.sp_plot_level_avg.value()
    settings.art_level_min = tab.sp_art_level_from.value()
    settings.art_level_max = tab.sp_art_level_to.value()
    settings.manga_level_min = tab.sp_manga_level_from.value()
    settings.manga_level_max = tab.sp_manga_level_to.value()
    settings.art_level_avg = tab.sp_art_level_avg.value()
    settings.manga_level_avg = tab.sp_manga_level_avg.value()
    settings.manga_adapted_percent = tab.sp_manga_adapted.value()
    settings.manga_pct_manhwa = tab.sp_manga_manhwa.value()
    settings.manga_pct_manhua = tab.sp_manga_manhua.value()


def apply_controls(tab, settings):
    def clamp(value, low=1, high=_api.MAX_LEVEL):
        return max(low, min(high, int(value or low)))
    # None у песенной рамки — «как общая»: настройки, сохранённые до её
    # появления, ничего не меняют в уже собранных паках.
    song_min = getattr(settings, "song_level_min", None)
    song_max = getattr(settings, "song_level_max", None)
    tab.song_level_range.set_range(
        clamp(settings.level_min if song_min is None else song_min),
        clamp(settings.level_max if song_max is None else song_max))
    tab.sp_song_level_avg.setValue(
        clamp(getattr(settings, "song_level_avg", 0), 0))
    studio_min = getattr(settings, "studio_level_min", None)
    studio_max = getattr(settings, "studio_level_max", None)
    tab.studio_level_range.set_range(
        clamp(settings.level_min if studio_min is None else studio_min),
        clamp(settings.level_max if studio_max is None else studio_max))
    tab.sp_studio_level_avg.setValue(
        clamp(getattr(settings, "studio_level_avg", 0), 0))
    tab.char_level_range.set_range(
        clamp(getattr(settings, "char_level_min", 1)),
        clamp(getattr(settings, "char_level_max", _api.MAX_LEVEL)))
    tab.sp_char_avg.setValue(clamp(getattr(settings, "char_level_avg", 0), 0))
    tab.plot_level_range.set_range(
        clamp(getattr(settings, "plot_level_min", 1)),
        clamp(getattr(settings, "plot_level_max", _api.MAX_LEVEL)))
    tab.sp_plot_level_avg.setValue(
        clamp(getattr(settings, "plot_level_avg", 0), 0))
    tab.art_level_range.set_range(clamp(settings.art_level_min),
                                  clamp(settings.art_level_max))
    tab.manga_level_range.set_range(clamp(settings.manga_level_min),
                                    clamp(settings.manga_level_max))
    tab.sp_art_level_avg.setValue(clamp(getattr(settings, "art_level_avg", 0), 0))
    tab.sp_manga_level_avg.setValue(
        clamp(getattr(settings, "manga_level_avg", 0), 0))
    tab.sp_manga_adapted.setValue(clamp(settings.manga_adapted_percent, 0, 100))
    tab.sp_manga_manhwa.setValue(clamp(settings.manga_pct_manhwa, 0, 100))
    tab.sp_manga_manhua.setValue(clamp(settings.manga_pct_manhua, 0, 100))
    refresh_art(tab)
