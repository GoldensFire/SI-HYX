# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Non-blocking discovery of new stable Gemini Flash models."""
from __future__ import annotations

import queue
import threading
import time

from PyQt6.QtCore import QTimer

from gemini_api import discover_models


def setup(tab):
    results = queue.Queue()
    state = {"busy": False, "key": "", "next": 0.0}

    def credentials():
        return str(tab._api_key("gemini") or "").strip()

    def refresh():
        key = credentials()
        if not key or state["busy"]:
            return
        state.update(busy=True, key=key)

        def work():
            try:
                models = discover_models(key)
            except Exception:
                models = ()
            results.put((key, models))

        threading.Thread(target=work, daemon=True).start()

    def tick():
        try:
            key, models = results.get_nowait()
        except queue.Empty:
            pass
        else:
            state["busy"] = False
            if key == credentials():
                # Найденные модели дописываем в ОБА списка: у загадок по
                # названию модель своя (см. gemini_title_controls).
                for name in ("cb_gemini_model", "cb_gemini_title_model",
                             "cb_pixiv_gemini_model", "cb_manga_gemini_model"):
                    box = getattr(tab, name, None)
                    if box is None:
                        continue
                    selected = box.currentText()
                    for model in models:
                        if box.findText(model) < 0:
                            box.addItem(model, model)
                    if selected:
                        box.setCurrentText(selected)
                state["next"] = float("inf") if models else time.monotonic() + 300
        key = credentials()
        visible = (tab.box_plot.isVisibleTo(tab)
                   or getattr(tab, "box_pixiv_art", tab).isVisibleTo(tab)
                   or getattr(tab, "box_manga", tab).isVisibleTo(tab))
        if (visible and key
                and (key != state["key"] or time.monotonic() >= state["next"])):
            refresh()

    tab._gemini_models_timer = QTimer(tab)
    tab._gemini_models_timer.timeout.connect(tick)
    tab._gemini_models_timer.start(1000)
    tab.chk_plot.toggled.connect(lambda checked: refresh() if checked else None)
    if hasattr(tab, "chk_pixiv_art"):
        tab.chk_pixiv_art.toggled.connect(
            lambda checked: refresh() if checked else None)
    tab.cb_gemini_model.currentTextChanged.connect(
        lambda: refresh_thinking_levels(tab))
    refresh_thinking_levels(tab)


def refresh_thinking_levels(tab):
    """Оставляет в списке только те уровни, которые принимает выбранная модель.

    «Минимальный» умеет один Flash-Lite: обычный Flash отвечает на него 400, и
    вопрос пропадал впустую (просьба пользователя). Выбранный уровень
    сохраняется, а недоступный заменяется ближайшим доступным."""
    from gemini_api import model_thinking_levels
    import animepack_tab as api

    box = getattr(tab, "cb_gemini_think", None)
    if box is None:
        return
    levels = model_thinking_levels(tab.cb_gemini_model.currentText())
    if [box.itemData(i) for i in range(box.count())] == list(levels):
        return
    want = box.currentData()
    box.blockSignals(True)
    box.clear()
    for level in levels:
        box.addItem(api.GEMINI_THINKING_LABELS[level], level)
    index = box.findData(want)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.blockSignals(False)
