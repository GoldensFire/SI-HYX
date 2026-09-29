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

# ─────────────────────────────────────────────────────────────────────────────
# Вкладка
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackTab(_api.QWidget):
    """Генератор аниме-паков для «Своей игры» (порт ASPG)."""

    from si_hyx_parts.animepack_tab.anime_pack_tab___init import (
        __init__,
        _build_unavailable,
        _build_ui,
    )

    # Подписи колонок таблицы состава пака. «Ур.» — сложность тайтла. Отдельной
    # колонки «Перс.» больше нет (просьба пользователя): уровень вопроса-
    # персонажа всегда равен уровню тайтла и только дублировал «Ур.».
    TABLE_HEADERS = ("№", "Раунд", "Тема", "Цена", "Аниме", "Песня", "Тип",
                     "Сложн.", "Индекс", "Ур.")
    # Колонки с числами — их выравниваем по центру.
    TABLE_NUM_COLS = (0, 1, 2, 3, 7, 8, 9)

    from si_hyx_parts.animepack_tab.anime_pack_tab__update_table_hint import (
        _update_table_hint,
        _on_sort_changed,
        _lab,
        _hint,
        _api_key,
        _migrate_api_key,
        _open_api_settings,
        _api_key_button,
        _refresh_api_key_buttons,
        _build_settings_panel,
        _build_actions,
        _disable_wheel,
    )

    from si_hyx_parts.animepack_tab.presets import (
        load_templates as _load_templates,
        _build_templates,
        _template_selected,
        _apply_template,
        _editable_settings,
        _update_template,
        _save_template_as,
        _rename_template,
        _delete_template,
        templates_to_settings as _templates_to_settings,
    )

    # Уже этого панель настроек не сжимается: дальше подписи начинают резаться.
    SETTINGS_MIN_W = 300
    # Столько ширины оставляем таблице состава пака, пока есть из чего.
    TABLE_MIN_W = 260
    # Неподвижная колонка «Пак» + кнопки запуска: уже этого её поля режутся,
    # а шире — она отнимает ширину у настроек ни за что (кнопке
    # «Сгенерировать пак» хватает 242 точек, полю «Название» — сколько дадут).
    PACK_MIN_W = 300
    PACK_MAX_W = 310

    from si_hyx_parts.animepack_tab.anime_pack_tab__fit_settings_width import (
        _table_shown,
        _toggle_table,
        _fit_pack_column,
        _fit_settings_width,
        resizeEvent,
        showEvent,
        _group_pack,
        _group_lists,
        _on_shares_toggled,
        _on_share_bar_changed,
        _share_key,
        _card_key,
        _refresh_share_bar,
        _refresh_db,
        _on_db_refreshed,
        _on_db_failed,
        _finish_db_ui,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab__on_random_toggled import (
        _on_random_toggled,
        _on_random_shiki_toggled,
        _on_mark_owners_toggled,
        _refresh_lists_visibility,
        _refresh_amq_available,
        _add_user_card,
        _on_card_changed,
        _remove_user_card,
        _clear_user_cards,
        _user_key,
        _remember_users,
        _open_saved_users,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab__group_songs import _group_songs

    from si_hyx_parts.animepack_tab.anime_pack_tab__on_mix_changed import (
        _on_mix_changed,
        _refresh_song_opts,
        _refresh_song_geometry,
        _on_song_kinds_toggled,
        _refresh_diff_bands,
        _on_compress_images_toggled,
        _on_poster_cache_toggled,
        _refresh_poster_cache,
        _clear_poster_cache,
        _open_cache_dialog,
        _open_db_table,
        _on_video_toggled,
        _on_manga_toggled,
        _on_pixel_toggled,
        _on_anagram_toggled,
        _on_plot_toggled,
        _refresh_pixel_hint,
        _group_anime,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab__group_other import (
        _group_other,
        _choose_exclude_siq,
        _clear_exclude_siq,
        _show_exclude_siq,
        _refresh_exclude_label,
        _choose_exact_siq,
        _clear_exact_siq,
        _refresh_exact_label,
        _pack_picker_start,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab__apply_styles import _apply_styles

    # ── мелкая логика формы ───────────────────────────────────────────────
    # В каком порядке перечислять вопросы в итоговой строке состава.
    COUNT_ORDER = (_api.FRAME_KIND, "opening", "ending", "insert", _api.CHAR_KIND,
                   _api.VIDEO_KIND, _api.MANGA_KIND, _api.PIXEL_KIND,
                   _api.ANAGRAM_KIND, _api.DIALOGUE_KIND, _api.PLOT_KIND,
                   _api.DESCRIPTION_AUDIO_KIND,
                   _api.AI_ART_KIND,
                   _api.PIXIV_ART_KIND, _api.SAKUGA_KIND,
                   _api.STUDIO_KIND)
    COUNT_LABELS = {_api.FRAME_KIND: "Кадров", "opening": "Опенингов",
                    "ending": "Эндингов", "insert": "OST",
                    _api.CHAR_KIND: "Персонажей", _api.VIDEO_KIND: "Видео",
                    _api.MANGA_KIND: "Манги", _api.PIXEL_KIND: "Кадров с эффектами",
                    _api.ANAGRAM_KIND: "Анаграмм",
                    _api.DIALOGUE_KIND: "Диалогов",
                    _api.PLOT_KIND: "По сюжету",
                    _api.DESCRIPTION_AUDIO_KIND: "Описание",
                    _api.AI_ART_KIND: "ИИ-артов",
                    _api.PIXIV_ART_KIND: "Артов Pixiv",
                    _api.SAKUGA_KIND: "Сакуги",
                    _api.STUDIO_KIND: "Студий"}

    from si_hyx_parts.animepack_tab.anime_pack_tab__recount import (
        _recount,
        _refresh_out_dir_label,
        _choose_out_dir,
        _load_genres_async,
        _on_genres_loaded,
        _apply_pending_genres,
        _on_genres_failed,
        _open_genre_picker,
        _update_genres_btn,
        collect,
        get_settings,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab_apply_settings import (
        apply_settings,
        reset_settings,
        log,
        _log_gap,
        start,
        _launch_generation,
        stop,
        _progress,
        _on_progress,
        _eta,
        _finish_ui,
        _release_pack_number,
        _on_failed,
        _on_finished,
    )

    from si_hyx_parts.animepack_tab.generation_queue import (
        refresh_queue as _refresh_queue,
        remove_queued as _remove_queued,
        start_next as _start_next,
        remember_generated as _remember_generated,
        finish_queue as _finish_queue,
    )

    from si_hyx_parts.animepack_tab.anime_pack_tab__fill_table import (
        _fill_table,
        _open_result,
        _detach,
        cleanup,
    )

AnimePackTab.__module__ = _api.__name__
_api.AnimePackTab = AnimePackTab
