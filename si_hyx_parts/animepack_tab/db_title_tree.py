# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Дерево франшиз в панели базы Shikimori. Namespace: animepack_tab.

В корне каждой франшизы стоит её самый узнаваемый тайтл. Остальные части
живут детьми и не раздувают каталог, пока пользователь не раскрыл стрелку или
не сделал двойной клик. Модель хранит те же заранее посчитанные строки, что и
плоская таблица: на десятках тысяч карточек виджеты на каждую строку не
создаются.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt

import animepack as ap


def group_title_rows(rows, franchise_parts=None) -> tuple[list, list[int]]:
    """(строки, родители) с самым популярным тайтлом во главе франшизы.

    Родитель ``-1`` означает корневую строку; остальные значения — индекс
    корня в возвращённом списке. Популярность здесь — тот же итоговый индекс,
    по которому сортируется панель и от которого считается сложность пака.
    """
    families: dict[tuple[str, str], list] = {}
    singles = []
    for row in rows:
        key = str((row or {}).get("franchise") or "").strip()
        if key:
            branch = str((row or {}).get("franchise_branch") or "")
            families.setdefault((key, branch), []).append(row)
        else:
            singles.append([row])

    def popular(row):
        return (float(row.get("index") or 0.0),
                float(row.get("base") or 0.0),
                int(row.get("favorites") or -1),
                float(row.get("score") or 0.0),
                -int(row.get("id") or 0))

    groups = []
    for (key, branch), members in families.items():
        ordered = sorted(members, key=popular, reverse=True)
        parts = franchise_parts(key) if callable(franchise_parts) else None
        if branch and parts:
            parts = ap.franchise_branch_parts(
                (ordered[0] or {}).get("card") or {}, parts)
        header = _missing_family_header(key, ordered, parts)
        groups.append((header, ordered))
    for members in singles:
        groups.append((None, members))
    groups.sort(key=lambda group: popular(group[1][0]), reverse=True)

    flat, parents = [], []
    for header, members in groups:
        root = len(flat)
        flat.append(header or members[0])
        parents.append(-1)
        children = members if header else members[1:]
        for row in children:
            flat.append(row)
            parents.append(root)
    return flat, parents


def _missing_family_header(key: str, members, parts):
    """Групповой корень, если часть франшизы скрыта фильтрами каталога."""
    if not isinstance(parts, list) or len(parts) < 2:
        return None
    present = {str(row.get("id") or row.get("mal") or "") for row in members}
    known = {str(row.get("id") or row.get("malId") or "") for row in parts
             if isinstance(row, dict)}
    known.discard("")
    if not known or known <= present:
        return None
    lead = next((row for row in parts if isinstance(row, dict)), {})
    name = str(lead.get("russian") or lead.get("name") or "").strip()
    if not name:
        name = key.replace("_", " ").strip().title()
    total = len(known | present)
    # Ссылка группового корня ведёт на реальную ведущую часть франшизы. Раньше
    # id и url намеренно обнулялись, поэтому именно у франшизы кнопки не было.
    header = dict(members[0])
    header.update({
        "title": f"{name} — франшиза ({len(members)} из {total} в каталоге)",
        "_franchise_header": True,
    })
    return header


@dataclass
class _Node:
    source: int
    parent: "_Node | None" = None
    children: list = field(default_factory=list)


class DbTitleTreeModel(QAbstractItemModel):
    """Лёгкая иерархическая модель: франшизы в корне, части под ними."""

    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self._headers = tuple(headers)
        self._rows: list = []
        self._texts: list = []
        self._sorts: list = []
        self._hay: list = []
        self._roots: list[_Node] = []
        self._shown_roots: list[_Node] = []
        self._shown_children: dict[int, list[_Node]] = {}
        self._needle = ""
        self._sort_col = -1
        self._descending = True
        self._numeric: tuple = ()

    def set_data(self, rows, texts, sorts, hay, parents=None) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._texts, self._sorts, self._hay = list(texts), list(sorts), list(hay)
        self._numeric = tuple(value is not None for value in self._sorts[0]) \
            if self._sorts else ()
        nodes = [_Node(i) for i in range(len(self._rows))]
        self._roots = []
        for i, node in enumerate(nodes):
            parent = int(parents[i]) if parents and i < len(parents) else -1
            if 0 <= parent < len(nodes):
                node.parent = nodes[parent]
                nodes[parent].children.append(node)
            else:
                self._roots.append(node)
        self._rebuild()
        self.endResetModel()

    def clear(self) -> None:
        self.set_data([], [], [], [], [])

    def set_needle(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        if needle == self._needle:
            return
        self.beginResetModel()
        self._needle = needle
        self._rebuild()
        self.endResetModel()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        self._sort_col = int(column)
        self._descending = order == Qt.SortOrder.DescendingOrder
        self._rebuild()
        self.endResetModel()

    def _key(self, node: _Node):
        col = self._sort_col
        if not 0 <= col < len(self._headers):
            return 0
        value = self._sorts[node.source][col]
        return (self._texts[node.source][col].casefold()
                if value is None else value)

    def _ordered(self, nodes):
        out = list(nodes)
        if 0 <= self._sort_col < len(self._headers):
            try:
                out.sort(key=self._key, reverse=self._descending)
            except TypeError:  # pragma: no cover — смешанные значения
                out.sort(key=lambda node: str(self._key(node)),
                         reverse=self._descending)
        return out

    def _rebuild(self) -> None:
        needle = self._needle
        roots, children = [], {}
        for root in self._roots:
            own = not needle or needle in self._hay[root.source]
            shown = (list(root.children) if own else
                     [c for c in root.children if needle in self._hay[c.source]])
            if own or shown:
                roots.append(root)
                children[root.source] = self._ordered(shown)
        self._shown_roots = self._ordered(roots)
        self._shown_children = children

    # ── Qt model ─────────────────────────────────────────────────────────
    def index(self, row, column, parent=QModelIndex()):
        if row < 0 or column < 0 or column >= len(self._headers):
            return QModelIndex()
        nodes = self._shown_roots
        if parent.isValid():
            if parent.column() != 0:
                return QModelIndex()
            node = parent.internalPointer()
            nodes = self._shown_children.get(node.source, [])
        if row >= len(nodes):
            return QModelIndex()
        return self.createIndex(row, column, nodes[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent = node.parent
        if parent is None:
            return QModelIndex()
        try:
            row = self._shown_roots.index(parent)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent)

    def rowCount(self, parent=QModelIndex()):        # noqa: N802
        if not parent.isValid():
            return len(self._shown_roots)
        if parent.column() != 0:
            return 0
        node = parent.internalPointer()
        return len(self._shown_children.get(node.source, []))

    def columnCount(self, parent=QModelIndex()):     # noqa: N802
        return 0 if parent.isValid() and parent.column() > 0 else len(self._headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation != Qt.Orientation.Horizontal
                or not 0 <= section < len(self._headers)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(self._align(section) | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _align(self, column: int):
        numeric = self._numeric[column] if column < len(self._numeric) else False
        return (Qt.AlignmentFlag.AlignHCenter if numeric
                else Qt.AlignmentFlag.AlignLeft)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if self._headers[column] == "Место":
                return str(index.row() + 1)
            return self._texts[node.source][column]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(self._align(column) | Qt.AlignmentFlag.AlignVCenter)
        return None

    def source(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return None
        return self._rows[index.internalPointer().source]

    def total(self) -> int:
        return sum(not row.get("_franchise_header") for row in self._rows)

    def visible_total(self) -> int:
        nodes = list(self._shown_roots)
        for rows in self._shown_children.values():
            nodes.extend(rows)
        return sum(not self._rows[node.source].get("_franchise_header")
                   for node in nodes)
