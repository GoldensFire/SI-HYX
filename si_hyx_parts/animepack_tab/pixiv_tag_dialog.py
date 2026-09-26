# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Окно «Исключаемые теги Pixiv»: правка списков меток самим пользователем.

Возвращает три списка ровно в том виде, в каком их ждут настройки пака:
выключенные группы, снятые по одной метки и свои добавленные (см.
pixiv_tag_rules.TagRules)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialogButtonBox, QHBoxLayout, QLineEdit,
                             QPushButton, QTreeWidget, QTreeWidgetItem)

import animepack_tab as _api
import pixiv_art_tags as tags

CHECKED = Qt.CheckState.Checked
UNCHECKED = Qt.CheckState.Unchecked
MINE = "Мои метки"


def _item(text, checked=True, tip=""):
    row = QTreeWidgetItem([text])
    row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    row.setCheckState(0, CHECKED if checked else UNCHECKED)
    if tip:
        row.setToolTip(0, tip)
    return row


class PixivTagDialog(_api.QDialog):
    """Группы встроенных меток с галочками плюс свои метки пользователя."""

    def __init__(self, parent=None, groups_off=(), tags_off=(), extra=()):
        super().__init__(parent)
        self.setWindowTitle("Исключаемые теги Pixiv")
        self.setMinimumSize(460, 560)
        off_groups = {str(k) for k in (groups_off or [])}
        off_terms = {str(t).casefold() for t in (tags_off or [])}

        box = _api.QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        hint = _api.QLabel(
            "Снятая галочка — такие работы снова можно брать в пак. Метки "
            "уходят минусом в сам запрос к Pixiv (туда влезает 256 символов, "
            "остальное отсеивается уже здесь), поэтому свои метки идут "
            "первыми. Шок-контент не выключается.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        box.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._sync)
        self._filling = True
        self._mine = _item(MINE, True)
        self._mine.setFlags(self._mine.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        self.tree.addTopLevelItem(self._mine)
        for term in tags.clean_terms(extra):
            self._mine.addChild(_item(term, term.casefold() not in off_terms))
        self._mine.setExpanded(True)
        for key, title, tip, group_tags, group_fragments, locked in tags.GROUPS:
            node = _item(title, key not in off_groups or locked, tip)
            node.setData(0, Qt.ItemDataRole.UserRole, key)
            if locked:
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            for term in sorted(group_tags) + list(group_fragments):
                node.addChild(_item(term, term.casefold() not in off_terms))
            self.tree.addTopLevelItem(node)
        self._filling = False
        box.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.ed_new = QLineEdit()
        self.ed_new.setPlaceholderText("Своя метка Pixiv, например: 落書き")
        self.ed_new.setToolTip(
            "Метка пишется так же, как на самом Pixiv. Работы с ней в пак не "
            "попадут, а сама метка уйдёт минусом в поиск.")
        self.ed_new.returnPressed.connect(self._add)
        btn_add = QPushButton("Добавить")
        btn_add.clicked.connect(self._add)
        row.addWidget(self.ed_new, 1)
        row.addWidget(btn_add)
        box.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults).setText("Сбросить")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults
                       ).clicked.connect(self._reset)
        box.addWidget(buttons)

    def _add(self):
        """Своя метка в список. Повтор просто отмечается галочкой заново."""
        term = " ".join(self.ed_new.text().split())
        if not term:
            return
        self.ed_new.clear()
        for i in range(self._mine.childCount()):
            row = self._mine.child(i)
            if row.text(0).casefold() == term.casefold():
                row.setCheckState(0, CHECKED)
                return
        self._mine.addChild(_item(term, True))
        self._mine.setExpanded(True)

    def _sync(self, item, _column):
        """Галочка на группе ставит и снимает все её метки разом."""
        if self._filling or item.childCount() == 0:
            return
        self._filling = True
        state = item.checkState(0)
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, state)
        self._filling = False

    def _reset(self):
        """Вернуть встроенные списки: всё включено, свои метки убраны."""
        self._filling = True
        self._mine.takeChildren()
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            if node is not self._mine:
                node.setCheckState(0, CHECKED)
            for j in range(node.childCount()):
                node.child(j).setCheckState(0, CHECKED)
        self._filling = False

    def result_lists(self) -> tuple[list[str], list[str], list[str]]:
        """(выключенные группы, снятые метки, свои метки)."""
        groups_off, off_terms, extra = [], [], []
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            key = node.data(0, Qt.ItemDataRole.UserRole)
            if node is self._mine:
                for j in range(node.childCount()):
                    row = node.child(j)
                    extra.append(row.text(0))
                    if row.checkState(0) != CHECKED:
                        off_terms.append(row.text(0))
                continue
            if node.checkState(0) != CHECKED:
                groups_off.append(str(key))
                continue        # вся группа выключена — по одной не считаем
            for j in range(node.childCount()):
                row = node.child(j)
                if row.checkState(0) != CHECKED:
                    off_terms.append(row.text(0))
        return groups_off, tags.clean_terms(off_terms), tags.clean_terms(extra)


def edit_tags(tab):
    """Показывает окно и складывает ответ обратно на вкладку."""
    dialog = PixivTagDialog(tab, tab._pixiv_groups_off, tab._pixiv_tags_off,
                            tab._pixiv_tags_extra)
    if dialog.exec() != _api.QDialog.DialogCode.Accepted:
        return
    (tab._pixiv_groups_off, tab._pixiv_tags_off,
     tab._pixiv_tags_extra) = dialog.result_lists()
    refresh_button(tab)


def refresh_button(tab):
    """Надпись на кнопке: сразу видно, правил ли пользователь списки."""
    changed = (len(tab._pixiv_groups_off) + len(tab._pixiv_tags_off)
               + len(tab._pixiv_tags_extra))
    tab.btn_pixiv_tags.setText(
        f"Исключаемые теги… (правок: {changed})" if changed
        else "Исключаемые теги…")
