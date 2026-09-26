# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: _fill_table. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def _fill_table(self, result):
    rows = (result.changes + list(result.skipped_specials)
            + list(getattr(result, "skipped_titles", [])))
    self.table.setRowCount(0)
    # Объединённые клетки живут по номеру строки и переживают setRowCount(0):
    # не снять их — и следующий отчёт слепит колонки не тем строкам.
    self.table.clearSpans()
    # Карточка пака уступает место списку правок — за ней всегда можно
    # вернуться, выбрав файл заново.
    self.left_stack.setCurrentIndex(1)
    labels = {"special": "Спецвопрос", "title": "Названия",
              "case": "Написание", "poster": "Постер",
              "image": "Картинка", "character": "Персонаж",
              "repeat": "Повтор", "merge": "Вместе", "empty": "Пустой",
              "audio": "Аудио", "video": "Видео", "unused": "Мусор"}
    files: list[str] = []                 # имена файлов на три колонки
    rounds: list[str] = []                # раунды обычных правок
    for i, change in enumerate(sorted(rows, key=lambda c: c.order)):
        self.table.insertRow(i)
        is_file = change.kind in self.FILE_KINDS
        cells = [
            _api.QTableWidgetItem(str(i + 1)),
            # У файла имя лежит в «Теме», но показать его надо во всю
            # ширину — кладём в «Раунд» и растягиваем до «Цены».
            _api.QTableWidgetItem(change.theme_name if is_file
                             else change.round_name),
            _api.QTableWidgetItem("" if is_file else change.theme_name),
            _api.QTableWidgetItem("" if is_file else str(change.price)),
            _api.QTableWidgetItem(labels.get(change.kind, change.kind)),
            _api.QTableWidgetItem(change.before),
            _api.QTableWidgetItem(change.after),
        ]
        for col, item in enumerate(cells):
            if col in self.TABLE_NUM_COLS:
                item.setTextAlignment(_api.Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, col, item)
        if is_file:
            self.table.setSpan(i, 1, 1, 3)
            files.append(change.theme_name)
        else:
            rounds.append(change.round_name)
    self._fit_round_column(files, rounds)

def _fit_round_column(self, files: list, rounds: list) -> None:
    """Ширина «Раунда» — своими руками, остальные колонки по-прежнему по
        содержимому.

        Объединённые клетки Qt меряет по-своему и имени файла места недодаёт
        (проверено на живом окне: длинное имя обрывалось многоточием), поэтому
        «Раунду» ширина выставляется прямо: столько, сколько имени не хватило на
        «Тему» с «Ценой», но не меньше, чем нужно самим раундам."""
    table = self.table
    header = table.horizontalHeader()
    table.resizeColumnsToContents()
    fm = table.fontMetrics()
    pad = 12                              # отступы клетки в текст не входят
    need = max([fm.horizontalAdvance(self.TABLE_HEADERS[1])]
               + [fm.horizontalAdvance(name) for name in rounds]) + pad
    if files:
        free = table.columnWidth(2) + table.columnWidth(3)
        need = max(need, max(fm.horizontalAdvance(name) for name in files)
                   + pad - free)
    header.resizeSection(1, max(header.minimumSectionSize(), need))

def _open_result(self):
    if not self._last_pack:
        return
    try:
        from utils import reveal_in_explorer
        reveal_in_explorer(self._last_pack)
    except Exception as e:  # noqa: BLE001
        _api.msgbox_critical(self, "Не открылось", str(e))

# ── завершение работы страницы ────────────────────────────────────────
def cleanup(self):
    if self._task is not None:
        self._task.stop()
    self._task = None
