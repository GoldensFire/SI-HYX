# -*- coding: utf-8 -*-
"""Отдельное окно с составом только что собранного аниме-пака.

Устроено как панель базы Shikimori, только обновлять здесь нечего: поиск со
счётчиком строк сверху, сортировка по любой колонке, подсказка на каждом
заголовке — что это за величина, и подсказка на строке — из чего у ЭТОГО
вопроса сложились узнаваемость и цена (просьба пользователя). Разбор приезжает
вместе с ячейками: складывает его генератор, а `clone()` уносит подсказки сюда.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QVBoxLayout,
)


# Откуда берётся каждая колонка — подсказкой на её заголовке. Тексты короткие
# нарочно: подробный разбор конкретной строки виден по наведению на саму
# строку, а здесь объясняется сама величина.
COLUMN_HINTS = {
    "№": "Порядок вопроса в паке. Сортировка по этой колонке возвращает "
         "таблицу к тому порядку, в каком вопросы лежат в файле.",
    "Раунд": "Номер раунда. Сколько их и сколько тем в каждом — настройка "
             "пака; раскладку считает сам генератор, так что таблица и пак "
             "совпадают до вопроса.",
    "Тема": "Номер темы внутри раунда.",
    "Цена": "База определяется уровнем тайтла: 1-й уровень стоит 6, каждый "
            "следующий на очко дороже, 15-й — 20. Сверху идут надбавки за "
            "род вопроса; персонаж получает +4 за главного героя или +6 за "
            "второстепенного. Наведите на строку — увидите полный разбор.",
    "Аниме": "Русское название тайтла (у вопроса-персонажа рядом, в кавычках, "
             "имя героя). Это же название и есть правильный ответ.",
    "Песня": "Исполнитель и название песни. У немых вопросов — кадра, манги, "
             "сюжета, анаграммы — стоит прочерк: песни в них нет.",
    "Тип": "Род вопроса: кадр, пиксели, персонаж, манга, сюжет, арт и так "
           "далее. У пикселей вместо рода написан выбранный эффект "
           "раскрытия.",
    "Сложн.": "Сложность песни по AMQ — насколько редко её угадывают там. "
              "Только у песенных вопросов и только про саму песню.",
    "Индекс": "Узнаваемость тайтла: сколько людей держат его в списках "
              "Shikimori, приглушённое возрастом выпуска и слегка — оценкой, "
              "плюс надбавка за «в избранном». У части серии берётся индекс "
              "всей франшизы. Наведите на строку — увидите разбор.",
    "Ур.": "Сложность вопроса от 1 (узнают все) до 15 (не узнает никто) — "
           "ступенька, на которую «Индекс» попал в лесенке.",
}


class PackTableDialog(QDialog):
    def __init__(self, source, headers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Состав сгенерированного пакета")
        self.resize(1100, 650)
        layout = QVBoxLayout(self)
        # Поиск по вопросам (просьба пользователя): пак на полторы сотни
        # строк глазами не пролистать.
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Поиск по аниме, песне, типу вопроса, цене…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.found = QLabel()
        top.addWidget(self.search, 1)
        top.addWidget(self.found)
        layout.addLayout(top)
        self.table = QTableWidget(self)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        # Ячейки сюда копируются через clone(), поэтому разбивка индекса и
        # цены приезжает вместе с ними — остаётся показать её по наведению.
        from .index_tooltip import install as install_tip
        from .index_tooltip import install_headers
        # whole_row: наводить можно на любую ячейку строки, а не только на
        # «Индекс» и «Цену», — ровно как в панели базы Shikimori.
        install_tip(self.table, whole_row=True)
        install_headers(self.table, COLUMN_HINTS)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh(source, headers)

    def refresh(self, source, headers):
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.setRowCount(source.rowCount())
        for row in range(source.rowCount()):
            for col in range(source.columnCount()):
                item = source.item(row, col)
                if item is not None:
                    # clone() у наших числовых ячеек переопределён: без него
                    # копия становится обычной строкой, и «Цена» с «Индексом»
                    # сортировались бы как текст — 1, 10, 11, 12.
                    self.table.setItem(row, col, item.clone())
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(
            0, Qt.SortOrder.AscendingOrder)
        self._apply_filter()

    def _apply_filter(self, *_args):
        """Прячет строки, в которых не нашлось искомого (регистр не важен)."""
        needle = self.search.text().strip().casefold()
        shown = 0
        for row in range(self.table.rowCount()):
            hit = not needle or any(
                needle in (self.table.item(row, col).text().casefold()
                           if self.table.item(row, col) is not None else "")
                for col in range(self.table.columnCount()))
            self.table.setRowHidden(row, not hit)
            shown += bool(hit)
        total = self.table.rowCount()
        self.found.setText(f"Строк: {total}" if not needle
                           else f"Найдено: {shown} из {total}")


def open_pack_table(tab):
    dialog = getattr(tab, "_table_dialog", None)
    if dialog is None:
        dialog = PackTableDialog(tab.table, tab.TABLE_HEADERS, tab)
        tab._table_dialog = dialog
    else:
        dialog.refresh(tab.table, tab.TABLE_HEADERS)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
