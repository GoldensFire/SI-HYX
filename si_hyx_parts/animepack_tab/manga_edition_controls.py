# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""One share bar for Japanese, Korean and Chinese comics."""
import animepack_tab as _api
from si_hyx_parts.animepack.manga_editions import KEYS, LABELS, shares


def build(tab):
    tab.manga_edition_bar = _api._ShareBar(
        [(k, LABELS[k], color) for k, color in
         zip(KEYS, ("accent", "green", "yellow"))])
    tab.manga_edition_bar.setMinimumWidth(240)
    tab.manga_edition_bar.setToolTip(
        "Доли среди вопросов по комиксам. Перетаскивайте границы: сумма "
        "всегда 100%. Нулевая доля исключает этот тип. Ваншоты и додзинси "
        "относятся к доле манги. Если кандидатов не хватит, ненулевые доли "
        "могут перераспределиться между включёнными типами.")
    tab.manga_edition_bar.changed.connect(tab._recount)
    saver = getattr(getattr(tab, "main", None), "_save_settings_soon", None)
    if saver:
        tab.manga_edition_bar.changed.connect(saver)


def collect(tab, settings):
    values = tab.manga_edition_bar.values()
    settings.manga_pct_manhwa = values["manhwa"]
    settings.manga_pct_manhua = values["manhua"]
    settings.manga_kinds.update({k: values[k] > 0 for k in KEYS})
    if not values["manga"]:
        settings.manga_kinds.update(one_shot=False, doujin=False)


def apply_controls(tab, settings):
    values = shares(settings)
    tab.manga_edition_bar.set_values(values if any(values.values())
                                     else dict.fromkeys(KEYS, 1))
