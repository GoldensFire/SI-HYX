# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Все рамки сложности — одним местом в группе «Аниме». Namespace: animepack_tab.

Раньше они были раскиданы по панели: общая в «Аниме», персонажи — под своей
галочкой, книги — внутри настроек манги, сюжет — среди настроек Gemini. Чтобы
сравнить «а насколько узнаваемы у меня арты против кадров», приходилось листать
всю колонку (просьба пользователя: «все настройки сложности каждого из составов
перенеси туда, где выбирается сложность аниме»).

Теперь здесь стоят подряд общая рамка и рамки родов вопросов: песни,
персонажи, арты, книги, сюжет. Рамка показывается, только пока её род вопросов
в паке есть — иначе группа «Аниме» разрослась бы вшестеро на пустом месте.

Сами виджеты по-прежнему создаёт level_controls: их имена читают и сохранение
настроек, и тесты. Здесь только раскладка и показ.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

from . import level_controls

# Ключ блока, подпись и виджеты (рамка, средняя). Порядок — порядок на панели.
BLOCKS = (
    ("song", "Песни", "song_level_range", "sp_song_level_avg"),
    ("studio", "Студии", "studio_level_range", "sp_studio_level_avg"),
    ("chars", "Персонажи", "char_level_range", "sp_char_avg"),
    ("art", "Арты", "art_level_range", "sp_art_level_avg"),
    ("manga", "Комиксы", "manga_level_range", "sp_manga_level_avg"),
    ("plot", "Сюжет", "plot_level_range", "sp_plot_level_avg"),
)


def build(tab) -> None:
    """Создаёт виджеты всех рамок (каждый — своим модулем level_controls).

    Звать можно сколько угодно раз: группа «Состав пака» строится РАНЬШЕ
    «Аниме», и книжные доли ей нужны уже там — поэтому она вызывает то же
    самое, а здесь уже готовое не пересоздаётся."""
    for name, make in (("song_level_range", level_controls.build_song),
                       ("studio_level_range", level_controls.build_studio),
                       ("char_level_range", level_controls.build_char),
                       ("art_level_range", level_controls.build_art),
                       ("manga_level_range", level_controls.build_manga),
                       ("plot_level_range", level_controls.build_plot)):
        if getattr(tab, name, None) is None:
            make(tab)


def place(tab, grid, row: int) -> int:
    """Кладёт рамки в сетку группы «Аниме»; отдаёт следующую строку."""
    tab._level_blocks = {}
    for key, title, range_name, avg_name in BLOCKS:
        bar = getattr(tab, range_name)
        avg = getattr(tab, avg_name)
        label = tab._lab(title)
        label.setContentsMargins(0, 5, 0, 0)
        grid.addWidget(label, row, 0,
                       alignment=Qt.AlignmentFlag.AlignTop)
        grid.addWidget(bar, row, 1, 1, 3)
        row += 1
        if key == "song":
            row = _place_amq(tab, grid, row)
        tab._level_blocks[key] = (label, bar)
    refresh(tab)
    return row


def _place_amq(tab, grid, row: int) -> int:
    """Рамки AMQ стоят в средней колонке, сразу под сложностью песен."""
    opening_label = tab._lab("Сложность AMQ опенингов/эндингов")
    ost_label = tab._lab("Сложность AMQ OST")
    grid.addWidget(opening_label, row, 0, 1, 4)
    row += 1
    grid.addWidget(tab.song_diff_range, row, 0, 1, 4)
    row += 1
    grid.addWidget(ost_label, row, 0, 1, 4)
    row += 1
    grid.addWidget(tab.ost_diff_range, row, 0, 1, 4)
    row += 1
    tab._amq_widgets = (opening_label, tab.song_diff_range, ost_label,
                        tab.ost_diff_range)
    return row


def _on(tab, key: str) -> bool:
    """Есть ли в паке род вопросов, которому нужна эта рамка."""
    def checked(name: str) -> bool:
        box = getattr(tab, "chk_" + name, None)
        return box is not None and box.isChecked()

    if key == "song":
        return checked("songs") or checked("video")
    if key == "studio":
        return checked("studio")
    if key == "chars":
        return checked("chars")
    if key == "art":
        return checked("ai_art") or checked("pixiv_art")
    if key == "manga":
        return checked("manga")
    if key == "plot":
        return checked("plot")
    return True


def refresh(tab) -> None:
    """Прячет рамки родов вопросов, которых в паке нет."""
    blocks = getattr(tab, "_level_blocks", None)
    if not blocks:
        return
    for key, widgets in blocks.items():
        on = _on(tab, key)
        for widget in widgets:
            widget.setVisible(on)
    song_on = _on(tab, "song")
    for widget in getattr(tab, "_amq_widgets", ()):
        widget.setVisible(song_on)
