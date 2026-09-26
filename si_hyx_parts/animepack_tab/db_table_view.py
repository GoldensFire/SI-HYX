# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Таблица панели базы Shikimori. Namespace: animepack_tab.

Раньше страница панели была QTableWidget, и на каталоге книг это упиралось в
стену: полсотни тысяч строк — это четыреста тысяч ячеек-объектов (секунд пять
на одно открытие вкладки), а каждая набранная в поиске буква перебирала их все
и дёргала setRowHidden на каждую строку — ещё по три секунды на букву.

Теперь строки лежат обычными кортежами, а ячейка создаётся только для того,
что видно на экране. Поиск и сортировка — тоже здесь, своим списком порядка:
QSortFilterProxyModel сравнивал бы строки через data(), то есть звал бы Python
на каждое сравнение, и одна сортировка каталога книг стоила бы десяток секунд
(проверено). Обычный `list.sort` по заранее посчитанным ключам делает то же за
сотые доли.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableView,
    QMenu, QTreeView, QVBoxLayout, QWidget,
)

from .db_row_tip import RowTipWatcher, _InfoTipPopup
from .db_title_delegate import TitleActionsDelegate, character_url
from .db_title_tree import DbTitleTreeModel

# Предел ширины текстовой колонки: длинное название переносится на вторую
# строку, а не растягивает таблицу так, что «Индекс» и «Ур.» уезжают за край
# окна (просьба пользователя).
TEXT_COL_WIDTH = 320
# Уже этого первую колонку не жмём даже в узком окне: название всё-таки должно
# читаться. Ниже — горизонтальная прокрутка, и это честнее каши из двух букв.
MIN_TEXT_COL_WIDTH = 160
# Поиск ждёт паузы в наборе: иначе каждая буква пересобирает выдачу.
SEARCH_DELAY_MS = 150



def build_cells(rows, build) -> tuple[list, list, list]:
    """(подписи, значения для сортировки, строки для поиска) по строкам базы.

    Считается ОДИН раз и без единого виджета — поэтому и годится для рабочего
    потока: интерфейс на время сборки каталога книг не замирает.
    `build(row)` отдаёт по ячейке пару «подпись, значение» (значение None —
    колонка текстовая: сортируется и выравнивается как текст)."""
    texts, sorts, hay = [], [], []
    for row in rows:
        cells = tuple(build(row))
        line = tuple(str(text) for text, _value in cells)
        texts.append(line)
        sorts.append(tuple(value for _text, value in cells))
        hay.append("\n".join(line).casefold())
    return texts, sorts, hay


class DbTableModel(QAbstractTableModel):
    """Готовые подписи строк базы плюс свои поиск и сортировка.

    `_order` — какие исходные строки сейчас показаны и в каком порядке. Всё
    остальное (подписи, значения, строка для поиска) лежит по исходным
    номерам и не трогается."""

    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self._headers = tuple(headers)
        self._rows: list = []
        self._texts: list = []
        self._sorts: list = []
        self._hay: list = []
        self._order: list = []
        self._needle = ""
        self._sort_col = -1
        self._descending = True
        self._numeric: tuple = ()

    # ── наполнение ────────────────────────────────────────────────────────
    def set_data(self, rows, texts, sorts, hay) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._texts, self._sorts, self._hay = list(texts), list(sorts), list(hay)
        # Числовая колонка стоит по центру, текстовая — по левому краю; то же
        # самое у её заголовка, иначе шапка «съезжает» относительно цифр.
        self._numeric = tuple(value is not None for value in self._sorts[0]) \
            if self._sorts else ()
        self._order = self._make_order()
        self.endResetModel()

    def clear(self) -> None:
        self.set_data([], [], [], [])

    def set_needle(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        if needle == self._needle:
            return
        self._needle = needle
        self._reorder()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        """Заголовок таблицы — сортировка по заранее посчитанным значениям."""
        self._sort_col = int(column)
        self._descending = order == Qt.SortOrder.DescendingOrder
        self._reorder()

    def _reorder(self) -> None:
        self.beginResetModel()
        self._order = self._make_order()
        self.endResetModel()

    def _make_order(self) -> list:
        needle = self._needle
        if needle:
            order = [i for i, hay in enumerate(self._hay) if needle in hay]
        else:
            order = list(range(len(self._texts)))
        col = self._sort_col
        if 0 <= col < len(self._headers):
            texts, sorts = self._texts, self._sorts

            def key(index):
                value = sorts[index][col]
                return texts[index][col] if value is None else value

            try:
                order.sort(key=key, reverse=self._descending)
            except TypeError:   # pragma: no cover — колонка вперемешку
                order.sort(key=lambda index: str(texts[index][col]),
                           reverse=self._descending)
        return order

    # ── чтение ────────────────────────────────────────────────────────────
    def rowCount(self, parent=QModelIndex()):        # noqa: N802 — имя из Qt
        return 0 if parent.isValid() else len(self._order)

    def columnCount(self, parent=QModelIndex()):     # noqa: N802 — имя из Qt
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section, orientation,       # noqa: N802 — имя из Qt
                   role=Qt.ItemDataRole.DisplayRole):
        if (orientation != Qt.Orientation.Horizontal
                or not 0 <= section < len(self._headers)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(self._align(section) | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _align(self, col: int):
        numeric = self._numeric[col] if col < len(self._numeric) else False
        return (Qt.AlignmentFlag.AlignHCenter if numeric
                else Qt.AlignmentFlag.AlignLeft)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role not in (Qt.ItemDataRole.DisplayRole,
                        Qt.ItemDataRole.TextAlignmentRole):
            return None
        try:
            source = self._order[index.row()]
            col = index.column()
            text = self._texts[source][col]
        except IndexError:      # pragma: no cover — модель как раз сменилась
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if self._headers[col] == "Место":
                return str(index.row() + 1)
            return text
        return int(self._align(col) | Qt.AlignmentFlag.AlignVCenter)

    def source(self, row):
        """Исходная строка разбора — по ней строится подсказка."""
        if isinstance(row, QModelIndex):
            row = row.row()
        try:
            return self._rows[self._order[row]]
        except IndexError:      # pragma: no cover
            return None

    def total(self) -> int:
        """Сколько строк в базе вообще — до поиска."""
        return len(self._texts)


class Page(QWidget):
    """Одна вкладка панели: поиск сверху, таблица снизу."""

    def __init__(self, headers, explain=None, parent=None, *,
                 hierarchical=False, refresh_title=None,
                 refresh_franchise=None):
        super().__init__(parent)
        self._headers = tuple(headers)
        self._explain = explain
        self._hierarchical = bool(hierarchical)
        self._refresh_title = refresh_title
        self._refresh_franchise = refresh_franchise
        self._main_col = next((self._headers.index(name)
                               for name in ("Название", "Персонаж")
                               if name in self._headers), 0)
        self._wanted: list = []           # ширины, которые просит содержимое
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._search_timer.start())
        self.count = QLabel()
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        layout.addLayout(top)
        # Набор букв сам по себе выдачу не пересобирает: ждём паузу, иначе на
        # каталоге книг каждая буква стоила бы отдельного прохода.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_search)
        self.model = (DbTitleTreeModel(headers, self) if self._hierarchical
                      else DbTableModel(headers, self))
        self.table = QTreeView() if self._hierarchical else QTableView()
        self.table.setModel(self.model)
        if self._hierarchical:
            self.table.setRootIsDecorated(True)
            self.table.setItemsExpandable(True)
            self.table.setExpandsOnDoubleClick(True)
            self.table.setIndentation(18)
            self._title_delegate = TitleActionsDelegate(
                self.table, column=self._main_col)
            self.table.setItemDelegateForColumn(
                self._main_col, self._title_delegate)
            # У дерева нет вертикального заголовка, а высоту многострочных
            # названий задаёт делегат. Разные строки могут иметь свою высоту.
            self.table.setUniformRowHeights(False)
        else:
            self.table.verticalHeader().setVisible(False)
            if "Персонаж" in self._headers:
                self._title_delegate = TitleActionsDelegate(
                    self.table, column=self._main_col, text_key="name",
                    url_for=character_url)
                self.table.setItemDelegateForColumn(
                    self._main_col, self._title_delegate)
        if refresh_title is not None or refresh_franchise is not None:
            self.table.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._row_menu)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        # Длинное название переносится на вторую строку вместо того, чтобы
        # растягивать колонку (просьба пользователя). Высота строк при этом
        # ОДНА на всю таблицу: пересчитывать её по содержимому нельзя — на
        # полсотне тысяч строк это десяток секунд на каждое открытие панели.
        self.table.setWordWrap(True)
        if not self._hierarchical:
            rows = self.table.verticalHeader()
            rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            rows.setDefaultSectionSize(self.fontMetrics().height() * 2 + 8)
        self.model.modelReset.connect(self._show_count)
        layout.addWidget(self.table, 1)
        if explain is not None and _InfoTipPopup is not None:
            # Фильтр держим ссылкой на странице: иначе сборщик Python унесёт
            # его, и подсказка перестанет появляться через случайное время.
            self._tip_watcher = RowTipWatcher(self)
            self.table.viewport().setMouseTracking(True)
            self.table.viewport().installEventFilter(self._tip_watcher)
            self.model.modelReset.connect(self._tip_watcher.reset)
        self._show_count()

    # ── наполнение ────────────────────────────────────────────────────────
    def set_busy(self, text: str) -> None:
        """Таблица пока собирается: показываем это вместо пустого счётчика."""
        self.model.clear()
        self.search.setEnabled(False)
        self.count.setText(text)

    def set_data(self, rows, texts, sorts, hay, sort_by=0, parents=None, *,
                 preserve_state=False) -> None:
        """Готовые строки (их считает build_cells, обычно в рабочем потоке)."""
        state = self._capture_tree_state() if preserve_state else None
        if state is None:
            self.table.sortByColumn(sort_by, Qt.SortOrder.DescendingOrder)
        if self._hierarchical:
            self.model.set_data(rows, texts, sorts, hay, parents)
            if state is None:
                self.table.collapseAll()
        else:
            self.model.set_data(rows, texts, sorts, hay)
        self.search.setEnabled(True)
        if self._hierarchical:
            for column in range(self.model.columnCount()):
                self.table.resizeColumnToContents(column)
        else:
            self.table.resizeColumnsToContents()
        self._wanted = [self.table.columnWidth(col)
                        for col in range(self.model.columnCount())]
        self._fit_columns()
        if state is not None:
            self._restore_tree_state(state)
        self._show_count()

    @staticmethod
    def _row_identity(row):
        if not isinstance(row, dict):
            return None
        if row.get("_franchise_header"):
            return ("franchise", str(row.get("franchise") or ""))
        try:
            ident = int(row.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        return (str(row.get("media") or "anime"), ident) if ident else None

    def _capture_tree_state(self):
        """Состояние, которое полный reset модели обычно теряет."""
        if not self._hierarchical or not self.model.total():
            return None
        expanded = set()
        for row in range(self.model.rowCount()):
            index = self.model.index(row, 0)
            if self.table.isExpanded(index):
                expanded.add(self._row_identity(self.model.source(index)))
        current = self.table.currentIndex()
        return {
            "expanded": expanded,
            "current": self._row_identity(self.model.source(current)),
            "scroll": self.table.verticalScrollBar().value(),
        }

    def _find_identity(self, wanted):
        if wanted is None:
            return None
        for row in range(self.model.rowCount()):
            root = self.model.index(row, 0)
            if self._row_identity(self.model.source(root)) == wanted:
                return root
            for child_row in range(self.model.rowCount(root)):
                child = self.model.index(child_row, 0, root)
                if self._row_identity(self.model.source(child)) == wanted:
                    return child
        return None

    def _restore_tree_state(self, state) -> None:
        if self.search.text().strip():
            self.table.expandAll()
        else:
            for wanted in state["expanded"]:
                index = self._find_identity(wanted)
                if index is not None:
                    self.table.setExpanded(index, True)
        current = self._find_identity(state["current"])
        if current is not None:
            self.table.setCurrentIndex(current)
        self.table.verticalScrollBar().setValue(state["scroll"])

    def fill(self, rows, build, sort_by=0) -> None:
        """Собрать и показать сразу — путь для тестов и мелких таблиц."""
        texts, sorts, hay = build_cells(rows, build)
        self.set_data(rows, texts, sorts, hay, sort_by)

    def total(self) -> int:
        return self.model.total()

    # ── ширины колонок ────────────────────────────────────────────────────
    def _fit_columns(self) -> None:
        """Текстовые колонки шире TEXT_COL_WIDTH не бывают, а свободное место
        достаётся первой из них — той, по которой строку и ищут.

        Без верхнего предела одно «Провожающая в последний путь Фрирен: …»
        растягивало таблицу так, что «Индекс» и «Ур.» уезжали за край окна; без
        раздачи остатка первая колонка сидела бы в своих 320 точках, а справа
        от таблицы висела пустота."""
        if not self._wanted:
            return
        header = (self.table.header() if self._hierarchical
                  else self.table.horizontalHeader())
        header.setSectionResizeMode(self._main_col,
                                    QHeaderView.ResizeMode.Interactive)
        widths = [min(want, TEXT_COL_WIDTH) for want in self._wanted]
        room = self.table.viewport().width()
        bar = self.table.verticalScrollBar()
        if not bar.isVisible():
            # Полосы прокрутки ещё нет: строки в таблицу только что положили,
            # и она появится первой же отрисовкой. Место под неё оставляем
            # заранее, иначе последняя колонка уезжает под полосу.
            room -= bar.sizeHint().width()
        spare = room - sum(widths)
        if spare < 0:
            # Колонок больше, чем места: лишнее снимаем с первой — из неё
            # название и так переносится на вторую строку, а вот «Индекс» и
            # «Ур.» уезжать за край окна не должны (просьба пользователя).
            col = self._main_col
            widths[col] -= min(-spare, max(0, widths[col]
                                            - MIN_TEXT_COL_WIDTH))
        for col, want in enumerate(self._wanted):
            if spare <= 0:
                break
            extra = min(spare, want - widths[col])
            if extra > 0:
                widths[col] += extra
                spare -= extra
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)

    def resizeEvent(self, event):            # noqa: N802 — имя из Qt
        """Окно растянули — колонка названия получает свободное место."""
        super().resizeEvent(event)
        self._fit_columns()

    # ── поиск и подсказки ─────────────────────────────────────────────────
    def _apply_search(self) -> None:
        self.model.set_needle(self.search.text())
        if self._hierarchical:
            if self.search.text().strip():
                self.table.expandAll()
            else:
                self.table.collapseAll()
        self._show_count()

    def _show_count(self, *_args) -> None:
        total = self.model.total()
        if self._hierarchical:
            shown = self.model.visible_total()
            roots = self.model.rowCount()
            suffix = f" · верхних: {roots}"
            self.count.setText(
                (f"Тайтлов: {shown} из {total}" if shown != total
                 else f"Тайтлов: {total}") + suffix)
        else:
            shown = self.model.rowCount()
            self.count.setText(f"Строк: {shown} из {total}" if shown != total
                               else f"Строк: {total}")

    def tip_key_at(self, pos):
        """Чем ячейка под курсором отличается для подсказки (None — ничем).

        Разбор у всей строки один, кроме колонки «Цена»: там своя разбивка."""
        index = self.table.indexAt(pos)
        row = self.model.source(index) if index.isValid() else None
        if row is None:
            return None
        return id(row), self._headers[index.column()] == "Цена"

    def explain_at(self, pos) -> str:
        """Разбор строки под курсором (пусто — строить нечего)."""
        if self._explain is None:
            return ""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return ""
        row = self.model.source(index)
        if row is None:
            return ""
        try:
            return self._explain(row, self._headers[index.column()]) or ""
        except TypeError:       # прежние сторонние обработчики с одним arg
            return self._explain(row) or ""
        except Exception:  # noqa: BLE001 — подсказка не стоит падения панели
            return ""

    def row_rect(self, row: int = 0):
        """Прямоугольник строки выдачи — нужен тестам, чтобы «навести мышь»."""
        return self.table.visualRect(self.model.index(row, 0))

    def row_actions(self, row) -> list:
        """Пункты ПКМ для строки: [(подпись, действие)].

        У франшизы — строки-заголовка или любой её части — есть и «Обновить
        всю франшизу» (просьба пользователя): перечитываются все её части,
        что лежат в базе, а не одна строка."""
        if not isinstance(row, dict):
            return []
        out = []
        if self._refresh_title is not None and not row.get("_franchise_header"):
            out.append(("Обновить данные", lambda: self._refresh_title(row)))
        if (self._refresh_franchise is not None
                and str(row.get("franchise") or "").strip()):
            out.append(("Обновить всю франшизу",
                        lambda: self._refresh_franchise(row)))
        return out

    def _row_menu(self, pos) -> None:
        """ПКМ по строке: точечно перечитать только её данные."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        actions = self.row_actions(self.model.source(index))
        if not actions:
            return
        from config import get_icon
        icon = get_icon("fa5s.sync-alt", color="#89b4fa")
        menu = QMenu(self.table)
        picked_map = {}
        for label, callback in actions:
            action = menu.addAction(icon, label)
            picked_map[action] = callback
        picked = menu.exec(self.table.viewport().mapToGlobal(pos))
        if picked in picked_map:
            picked_map[picked]()
