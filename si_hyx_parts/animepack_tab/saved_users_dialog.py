# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_SavedUsersDialog. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


# ─────────────────────────────────────────────────────────────────────────────
# Окно выбора сохранённых ников
# ─────────────────────────────────────────────────────────────────────────────
class _SavedUsersDialog(_api.QDialog):
    """Небольшое окно со списком запомненных людей: галочками отмечаются те,
    чьи списки надо добавить в пак. Лишние ники убираются кнопкой «Забыть»."""

    def __init__(self, saved: list, parent=None, used: _api.Optional[set] = None):
        super().__init__(parent)
        self.setWindowTitle("Сохранённые списки")
        self.setMinimumWidth(360)
        # Те, чьи списки уже добавлены, идут первыми и сразу с галочкой: окно
        # показывает текущий набор, а не пустой лист (просьба пользователя).
        used = used or set()

        def key(user):
            return (user.username.strip().casefold(), user.source)

        self._saved = sorted(saved, key=lambda u: key(u) not in used)
        self._used = used

        v = _api.QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        lbl = _api.QLabel("Отметьте, чьи списки добавить:")
        lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        v.addWidget(lbl)

        # Поиск: ников за годы копится много, и листать их глазами — мучение.
        # Фильтр только ПРЯЧЕТ строки, галочки со скрытых не снимаются, так что
        # отметить можно нескольких по очереди, набирая разные куски ников.
        self.ed_search = _api.QLineEdit()
        self.ed_search.setPlaceholderText("Поиск по нику…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._apply_filter)
        v.addWidget(self.ed_search)

        self.list = _api.QListWidget()
        self.list.setSelectionMode(_api.QAbstractItemView.SelectionMode.NoSelection)
        # Правой кнопкой строку можно забыть, не расставляя галочек (просьба
        # пользователя): ПКМ по нику → «Забыть».
        self.list.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)
        for user in self._saved:
            item = _api.QListWidgetItem(
                f"{user.username} — {_api.SOURCE_LABELS.get(user.source, user.source)}")
            item.setFlags(item.flags() | _api.Qt.ItemFlag.ItemIsUserCheckable)
            here = (user.username.strip().casefold(), user.source) in self._used
            item.setCheckState(_api.Qt.CheckState.Checked if here
                               else _api.Qt.CheckState.Unchecked)
            self.list.addItem(item)
        v.addWidget(self.list, 1)
        self.lbl_empty = _api.QLabel("Пока пусто: ники запоминаются сами, как только "
                                "вы их вписали.")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
        self.lbl_empty.setVisible(not self._saved)
        v.addWidget(self.lbl_empty)

        row = _api.QHBoxLayout(); row.setSpacing(6)
        self.btn_forget = _api.QPushButton("Забыть отмеченных")
        self.btn_forget.clicked.connect(self._forget_checked)
        btn_add = _api.QPushButton("Добавить")
        btn_add.setObjectName("b_primary")
        btn_add.clicked.connect(self.accept)
        btn_cancel = _api.QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_add)
        v.addLayout(row)

    def _apply_filter(self, text: str):
        """Прячет строки, не подходящие под поиск. Ищем и по нику, и по
        названию источника — «anilist» находит всех оттуда."""
        needle = (text or "").strip().casefold()
        shown = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            hit = not needle or needle in item.text().casefold()
            item.setHidden(not hit)
            shown += int(hit)
        if not self._saved:
            return
        self.lbl_empty.setVisible(shown == 0)
        if shown == 0:
            self.lbl_empty.setText(f"По «{text}» ничего не нашлось.")

    def _checked_rows(self) -> list[int]:
        return [i for i in range(self.list.count())
                if self.list.item(i).checkState() == _api.Qt.CheckState.Checked]

    def _forget_checked(self):
        self._forget_rows(self._checked_rows())

    def _forget_rows(self, rows) -> None:
        for i in sorted(set(rows), reverse=True):
            if 0 <= i < len(self._saved):
                self.list.takeItem(i)
                del self._saved[i]

    def _row_menu(self, pos):
        """ПКМ по строке: забыть её (или все отмеченные, если строка отмечена)."""
        item = self.list.itemAt(pos)
        if item is None:
            return
        row = self.list.row(item)
        checked = self._checked_rows()
        rows = checked if (row in checked and len(checked) > 1) else [row]
        menu = _api.QMenu(self)
        if len(rows) > 1:
            act_del = menu.addAction(f"Забыть отмеченных ({len(rows)})")
        else:
            act_del = menu.addAction(f"Забыть «{self._saved[row].username}»")
        act_copy = menu.addAction("Скопировать ник")
        picked = menu.exec(self.list.mapToGlobal(pos))
        if picked is act_del:
            self._forget_rows(rows)
        elif picked is act_copy:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._saved[row].username)

    def picked(self) -> list:
        return [self._saved[i] for i in self._checked_rows()]

    def remaining(self) -> list:
        """Что осталось в адресной книге после кнопки «Забыть»."""
        return list(self._saved)

_SavedUsersDialog.__module__ = _api.__name__
_api._SavedUsersDialog = _SavedUsersDialog
