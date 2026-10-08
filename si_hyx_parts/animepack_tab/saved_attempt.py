# -*- coding: utf-8 -*-
"""Кнопка «Собрать сохранённое»: пак из готовых вопросов неудачной упаковки.

Попытку сохраняет генератор (animepack/assembly_recovery), когда отбор и
загрузки прошли, а упаковка упала. Кнопка видна, только пока попытка есть,
и собирает пак с ТЕКУЩИМИ настройками вкладки — их можно поправить.
"""
from __future__ import annotations

import time

import animepack_tab as _api


def build(tab) -> None:
    tab.btn_rebuild_saved = _api.QPushButton("Собрать сохранённое")
    tab.btn_rebuild_saved.setIcon(_api.get_icon('fa5s.box-open'))
    tab.btn_rebuild_saved.clicked.connect(lambda: rebuild(tab))
    tab.btn_rebuild_saved.setVisible(False)
    refresh(tab)


def refresh(tab) -> None:
    button = getattr(tab, "btn_rebuild_saved", None)
    if button is None:
        return
    from si_hyx_parts.animepack import assembly_recovery
    attempt = assembly_recovery.latest()
    button.setVisible(bool(attempt))
    button.setEnabled(bool(attempt) and getattr(tab, "_task", None) is None)
    if attempt:
        when = time.strftime("%d.%m %H:%M", time.localtime(attempt.get("created", 0)))
        button.setToolTip(
            f"Попытка «{attempt.get('title', '')}» от {when}: "
            f"{attempt.get('questions', 0)} готовых вопросов.\n"
            f"Генерация прервалась: {attempt.get('error', '')}\n"
            "Пак соберётся из них с текущими настройками вкладки — "
            "без нового отбора и загрузок.")


def rebuild(tab) -> None:
    from si_hyx_parts.animepack import assembly_recovery
    attempt = assembly_recovery.latest()
    if not attempt or getattr(tab, "_task", None) is not None:
        refresh(tab)
        return
    settings = tab.collect()
    tab._launch_generation(settings, recovery=attempt["path"])
    refresh(tab)
