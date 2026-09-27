# -*- coding: utf-8 -*-
"""Окно со списком SIQ-пакетов, включённых в запрет повторов."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from utils import reveal_in_explorer


class IncludedPacksDialog(QDialog):
    def __init__(self, title: str, paths: list[str], start_dir: str,
                 on_change=None, parent=None, search_questions=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 420)
        self._title = title
        self._start_dir = start_dir
        self._on_change = on_change
        self._search_questions = bool(search_questions)
        layout = QVBoxLayout(self)
        self.label = QLabel()
        layout.addWidget(self.label)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._open)
        self._install_menu(self.list)
        self.list.itemSelectionChanged.connect(self._refresh_buttons)
        layout.addWidget(self.list, 1)
        if self._search_questions:
            self.search = QLineEdit()
            self.search.setPlaceholderText(
                "Поиск по вопросам, ответам, темам и использованным файлам…")
            self.search.textChanged.connect(self._refresh_search)
            layout.addWidget(self.search)
            self.search_label = QLabel("Введите название аниме или часть вопроса.")
            layout.addWidget(self.search_label)
            self.results = QListWidget()
            self.results.currentItemChanged.connect(self._show_result)
            self.results.itemDoubleClicked.connect(self._open)
            self._install_menu(self.results)
            layout.addWidget(self.results, 1)
            self.details = QPlainTextEdit()
            self.details.setReadOnly(True)
            self.details.setMaximumHeight(150)
            layout.addWidget(self.details)
            self.resize(900, 700)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Добавить паки…")
        self.add_btn.clicked.connect(self._choose_files)
        self.remove_btn = QPushButton("Убрать выбранные")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.open_btn = QPushButton("Открыть пак")
        self.open_btn.clicked.connect(lambda: self._open(self.list.currentItem()))
        self.reveal_btn = QPushButton("Показать в папке")
        self.reveal_btn.clicked.connect(self._reveal_selected)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addWidget(self.open_btn)
        row.addWidget(self.reveal_btn)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self._set_paths(paths)

    def paths(self) -> list[str]:
        return [str(self.list.item(row).data(Qt.ItemDataRole.UserRole) or "")
                for row in range(self.list.count())]

    def _set_paths(self, paths) -> None:
        self.list.clear()
        for path in paths:
            self._append(path)
        self._changed(notify=False)

    def _append(self, path: str) -> None:
        exists = os.path.isfile(path)
        text = os.path.basename(path) or path
        if not exists:
            text += "  (файл не найден)"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)

    def add_paths(self, paths) -> None:
        have = {os.path.normcase(path) for path in self.paths()}
        for path in paths:
            if os.path.normcase(path) not in have:
                self._append(path)
                have.add(os.path.normcase(path))
        self._changed()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._title, self._start_dir,
            "Пакеты SIGame (*.siq);;Все файлы (*)")
        if paths:
            self.add_paths(paths)

    def _remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._changed()

    def _changed(self, notify=True) -> None:
        paths = self.paths()
        self.label.setText(f"Включено пакетов: {len(paths)}")
        self._refresh_buttons()
        if self._search_questions:
            self._refresh_search()
        if notify and self._on_change is not None:
            self._on_change(paths)

    def _refresh_buttons(self) -> None:
        selected = bool(self.list.selectedItems())
        self.remove_btn.setEnabled(selected)
        self.reveal_btn.setEnabled(selected)
        self.open_btn.setEnabled(os.path.isfile(self._item_path(self.list.currentItem())))

    @staticmethod
    def _item_path(item) -> str:
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value.get("path") or "") if isinstance(value, dict) else str(value or "")

    def _open(self, item):
        path = self._item_path(item)
        if not os.path.isfile(path):
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path))):
            from msgbox import msgbox_warning
            msgbox_warning(self, "Открыть пак",
                           "Не удалось открыть пак. Назначьте приложение для файлов .siq.")

    def _install_menu(self, view):
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(
            lambda pos: self._context_menu(view, pos))

    def _item_menu(self, view, item):
        menu = QMenu(view)
        action = menu.addAction("Открыть пак", lambda: self._open(item))
        action.setEnabled(os.path.isfile(self._item_path(item)))
        menu.addAction("Показать в папке", lambda: self._reveal(item))
        return menu

    def _context_menu(self, view, pos):
        item = view.itemAt(pos)
        if item is None:
            return
        menu = self._item_menu(view, item)
        menu.exec(view.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _reveal_selected(self):
        self._reveal(self.list.currentItem())

    @classmethod
    def _reveal(cls, item):
        path = cls._item_path(item)
        if path:
            reveal_in_explorer(path)

    def _refresh_search(self):
        self.results.clear()
        self.details.clear()
        query = self.search.text().strip()
        if not query:
            self.search_label.setText("Введите название аниме или часть вопроса.")
            return
        from .pack_question_search import search_questions
        rows = search_questions(self.paths(), query)
        self.search_label.setText(f"Найдено вопросов: {len(rows)}")
        for row in rows:
            question = row["question"] or ", ".join(row["used"]) or "без текста"
            preview = question[:120] + ("…" if len(question) > 120 else "")
            where = " › ".join(value for value in
                               (row["pack"], row["round"], row["theme"]) if value)
            item = QListWidgetItem(
                f"{where} · {row['price'] or '—'} — {preview}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _show_result(self, current, previous=None):
        row = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not isinstance(row, dict):
            self.details.clear()
            return
        lines = [f"Пак: {row['pack']}", f"Файл: {row['path']}"]
        if row["round"]:
            lines.append(f"Раунд: {row['round']}")
        if row["theme"]:
            lines.append(f"Тема: {row['theme']}")
        lines.append(f"Цена: {row['price'] or '—'}")
        lines.append(f"Вопрос: {row['question'] or 'только медиа'}")
        lines.append("Использовано: " + (", ".join(row["used"]) or "текст"))
        lines.append("Ответы: " + ("; ".join(row["answers"]) or "не указаны"))
        self.details.setPlainText("\n".join(lines))


def show_included_packs(parent, title: str, paths: list[str], start_dir: str,
                        on_change=None, search_questions=False):
    dialog = IncludedPacksDialog(title, paths, start_dir, on_change, parent,
                                 search_questions)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
