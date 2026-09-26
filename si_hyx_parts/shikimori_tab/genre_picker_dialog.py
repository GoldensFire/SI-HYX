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

# ─── Вкладка ─────────────────────────────────────────────────────────────────
class ShikimoriTab(_api.QWidget):
    """Экспериментальная вкладка поиска аниме/манги через Shikimori API.

    Включается/выключается в Настройках (по умолчанию выключена). Не зависит от
    QtMultimedia и тяжёлых модулей — грузится быстро.
    """

    from si_hyx_parts.shikimori_tab.shikimori_tab___init import (
        __init__,
        _build_unavailable,
        _build_ui,
    )

    from si_hyx_parts.shikimori_tab.shikimori_tab__build_settings_panel import (
        _build_settings_panel,
        eventFilter,
        _apply_styles,
        _content_type,
        _on_content_changed,
    )

    from si_hyx_parts.shikimori_tab.shikimori_tab__rebuild_kind_status import (
        _rebuild_kind_status,
        _collect_filter,
        start_search,
        cancel_search,
        clear_results,
        _on_search_progress,
        _stop_limit_value,
        _on_search_batch,
        _on_search_finished,
        _on_search_failed,
        _set_busy,
        _set_actions_enabled,
        _is_excluded,
        _franchise_seen,
        _on_collapse_toggled,
        _rebuild_excluded_bases,
        _apply_exclusions,
        _views_sort_active,
        _index_sort_active,
        _sort_key,
        _sort_phrase,
    )

    from si_hyx_parts.shikimori_tab.shikimori_tab__update_views_max_enabled import (
        _update_views_max_enabled,
        _views_sort_limit,
        _display_results,
        _stop_views_task,
        _begin_views_sort,
        _on_views_item,
        _index_tooltip_for,
        _on_views_progress,
        _on_views_finished,
        _load_index_cache,
        _schedule_index_cache_save,
        _save_index_cache,
        _resort_by_views,
        _fill_list,
        _row_text,
        _append_anime,
        _placeholder_icon,
    )

    from si_hyx_parts.shikimori_tab.shikimori_tab__load_visible_thumbs import (
        _load_visible_thumbs,
        _on_thumb_loaded,
        _on_selection_changed,
        _open_selected_in_browser,
        _siq_datasets,
        _pack_answers,
        _choose_packs,
        _load_genres_async,
        _on_genres_loaded,
        _open_genre_picker,
        _update_genres_btn,
        get_settings,
    )

    from si_hyx_parts.shikimori_tab.shikimori_tab_apply_settings import (
        apply_settings,
        _restore_packs,
        reset_settings,
        _export,
        cleanup,
    )

ShikimoriTab.__module__ = _api.__name__
_api.ShikimoriTab = ShikimoriTab
