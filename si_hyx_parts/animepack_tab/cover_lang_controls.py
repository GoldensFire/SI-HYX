# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Языки каверов внутри панели каверов. Namespace: animepack_tab.

Отдельный вид исполнения «На другом языке» отвечал только на вопрос «пускать
ли перепетое вообще», а какой именно язык — не спрашивал никто (просьба
пользователя: «дай выбор, какие языки включать, а какие исключать»). Здесь
пятнадцать языков, которые умеет узнавать гейт (cover_meta_rules.LANGUAGES), и
один переключатель: отмеченные — это белый список или чёрный.

Отдельным модулем, а не строками в cover_controls: там и так полная коробка
настроек, а тут своя маленькая задача.
"""
from __future__ import annotations

import animepack_tab as _api
from cover_meta_rules import LANGUAGE_KEYS, LANGUAGE_LABELS

# Ключи режима — те же строки, что лежат в настройках (PackSettings).
MODES = (("allow", "Разрешать только отмеченные"),
         ("exclude", "Исключать отмеченные"))

LANG_TIP = ("На каком языке перепета песня. Язык берётся из заголовка ролика — "
            "того же, по которому вид исполнения попадает в подсказку вопроса "
            "(«Опенинг (кавер на английском)»).\n"
            "Ничего не отмечено — язык не отбирает вовсе.\n"
            "Записи, у которых язык в заголовке не назван, не трогает ни один "
            "режим: «неизвестно» — это не «другой язык», и почти всегда за ним "
            "стоит обычное японское исполнение.")


def build(tab) -> None:
    """Создаёт переключатель и галочки языков.

    Рисуются они в окне «Виды и языки исполнения» (cover_kinds_dialog): на
    самой панели пятнадцать галочек занимали пять строк подряд."""
    tab.cmb_cover_lang_mode = _api.QComboBox()
    for key, label in MODES:
        tab.cmb_cover_lang_mode.addItem(label, key)
    tab.cmb_cover_lang_mode.setToolTip(LANG_TIP)

    tab.cover_lang_checks = {}
    for key in LANGUAGE_KEYS:
        check = _api.QCheckBox(LANGUAGE_LABELS.get(key, key))
        check.setToolTip(LANG_TIP)
        tab.cover_lang_checks[key] = check


def collect(tab, settings) -> None:
    settings.cover_lang_mode = str(tab.cmb_cover_lang_mode.currentData()
                                   or "allow")
    settings.cover_langs = [key for key, check in tab.cover_lang_checks.items()
                            if check.isChecked()]


def apply(tab, settings) -> None:
    mode = str(getattr(settings, "cover_lang_mode", "allow") or "allow")
    index = tab.cmb_cover_lang_mode.findData(mode)
    tab.cmb_cover_lang_mode.setCurrentIndex(max(0, index))
    wanted = {str(key) for key in (getattr(settings, "cover_langs", None) or ())}
    for key, check in tab.cover_lang_checks.items():
        check.setChecked(key in wanted)
