# -*- coding: utf-8 -*-
"""Очередь снимков настроек аниме-пака и последовательный запуск."""
from __future__ import annotations

import os


def refresh_queue(self):
    view = self.queue_list
    view.clear()
    for position, settings in enumerate(self._queue, 1):
        view.addItem(f"{position}. {settings.title} · {settings.total_questions} вопросов")
    view.setVisible(bool(self._queue))
    self.btn_queue_remove.setVisible(bool(self._queue))
    self.btn_start.setText("Добавить в очередь" if self._task else "Сгенерировать пак")
    self.btn_start.setToolTip(
        "Сохранить текущие настройки для следующего пака"
        if self._task else "Начать генерацию с текущими настройками")


def remove_queued(self):
    row = self.queue_list.currentRow()
    if 0 <= row < len(self._queue):
        self._queue.pop(row)
        self._refresh_queue()


def start_next(self):
    if (self._closing or self._task is not None or self._db_task is not None
            or not self._queue):
        return
    settings = self._queue.pop(0)
    self._refresh_queue()
    # Пак, добавленный во время работы, наследует уже готовые исключения.
    settings.exclude_siq = list(dict.fromkeys(
        list(settings.exclude_siq) + list(self._exclude_siq)))
    settings.exclude_exact_siq = list(dict.fromkeys(
        list(settings.exclude_exact_siq) + list(self._exclude_exact_siq)))
    self._launch_generation(settings)


def remember_generated(self, path):
    """Готовый (в том числе частичный) пак закрывает свои франшизы и вопросы."""
    path = os.path.abspath(str(path or "")) if path else ""
    if not path or not os.path.isfile(path):
        return
    for attr, update in (("_exclude_siq", self._refresh_exclude_label),
                         ("_exclude_exact_siq", self._refresh_exact_label)):
        paths = getattr(self, attr)
        if os.path.normcase(path) not in {os.path.normcase(p) for p in paths}:
            paths.append(path)
            update()
    saver = getattr(self.main, "_save_settings_soon", None)
    if saver is not None:
        saver()


def finish_queue(self):
    self._refresh_queue()
    if self._queue and not self._closing:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._start_next)
