# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_GenrePickerDialog. Public namespace: shikimori_tab."""
import shikimori_tab as _api


class _GenrePickerDialog(_api.QDialog):
    """Выбор жанров и тем (как в фильтрах Shikimori). У каждого пункта ОДИН
    трёхпозиционный квадрат (см. _TriStateGenre): клик циклически переключает
    «выкл → включить (зелёный) → исключить (красный) → выкл». items — кортежи
    (id, подпись, группа); selected/excluded — заранее отмеченные id."""

    def __init__(self, items, selected, excluded=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Жанры и темы")
        self._items = {}                       # id -> _TriStateGenre
        sel = set(selected or [])
        exc = set(excluded or [])

        root = _api.QVBoxLayout(self)
        root.setSpacing(8)
        hint = _api.QLabel("Клик по пункту переключает: 1× — показывать только с ним "
                      "(зелёный ✓), 2× — исключить (красный ✕), 3× — сбросить.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        root.addWidget(hint)

        scroll = _api.QScrollArea(); scroll.setWidgetResizable(True)
        host = _api.QWidget(); hv = _api.QVBoxLayout(host); hv.setSpacing(10)
        groups = {g: [] for g in _api.GENRE_GROUP_ORDER}
        for gid, label, group in items:
            groups.setdefault(group, []).append((gid, label))
        for group, lst in groups.items():
            if not lst:
                continue
            box = _api.QGroupBox(_api.GENRE_GROUP_LABELS.get(group, group))
            grid = _api.QGridLayout(box)
            grid.setHorizontalSpacing(10); grid.setVerticalSpacing(2)
            lst.sort(key=lambda x: x[1].lower())
            # Раскладываем пункты в 2 колонки для компактности (сам пункт — один
            # переключатель, без отдельных столбцов «вкл»/«искл»).
            cols = 2
            for i, (gid, label) in enumerate(lst):
                st = (_api._TriStateGenre.INC if gid in sel
                      else _api._TriStateGenre.EXC if gid in exc
                      else _api._TriStateGenre.OFF)
                w = _api._TriStateGenre(gid, label, st)
                self._items[gid] = w
                grid.addWidget(w, i // cols, i % cols)
            for c in range(cols):
                grid.setColumnStretch(c, 1)
            hv.addWidget(box)
        hv.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        bb = _api.QDialogButtonBox()
        btn_clear = bb.addButton("Сбросить", _api.QDialogButtonBox.ButtonRole.ResetRole)
        bb.addButton(_api.QDialogButtonBox.StandardButton.Ok)
        bb.addButton(_api.QDialogButtonBox.StandardButton.Cancel)
        btn_clear.clicked.connect(self._clear_all)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.resize(560, 580)

    def _clear_all(self):
        for w in self._items.values():
            w.set_state(_api._TriStateGenre.OFF)

    def selected_ids(self):
        return [gid for gid, w in self._items.items()
                if w.state() == _api._TriStateGenre.INC]

    def excluded_ids(self):
        return [gid for gid, w in self._items.items()
                if w.state() == _api._TriStateGenre.EXC]

_GenrePickerDialog.__module__ = _api.__name__
_api._GenrePickerDialog = _GenrePickerDialog
