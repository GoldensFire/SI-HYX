# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _on_mix_changed. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _on_mix_changed(self):
    """Ползунок состава сдвинули: настройки песен нужны, только если доля
        песен не нулевая."""
    self._refresh_song_opts()

def _refresh_song_opts(self):
    """Настройки песен видны, только если песни в паке вообще будут.

        Ролику песня нужна ровно так же, как обычному вопросу (он и есть песня,
        только видео), поэтому доля роликов держит эти настройки на экране."""
    pcts = self.mix.percents()
    songs = bool(pcts[0] or pcts[1])
    self.box_song_opts.setVisible(songs)
    if getattr(self, "box_audio_opts", None) is not None:
        self.box_audio_opts.setVisible(songs)
    if getattr(self, "cb_char_roles", None) is not None:
        self.cb_char_roles.setEnabled(bool(pcts[3]))
        # Список ролей живёт в своей коробке под галочкой «Персонажи»:
        # прячем её целиком, иначе подпись осталась бы висеть одна.
        box = getattr(self, "box_chars", None)
        (box or self.cb_char_roles).setVisible(bool(pcts[3]))
    if getattr(self, "box_manga", None) is not None:
        # Настройки манги живут при её галочке, а не при доле: ползунок
        # можно увести в ноль и вернуть, не теряя их из виду.
        self.box_manga.setVisible(self.chk_manga.isChecked())
    if getattr(self, "_level_blocks", None):
        # Рамки сложности родов вопросов держатся на их галочках: без арта
        # или без книг своя рамка только мешает.
        from .level_panel import refresh as refresh_levels
        refresh_levels(self)
    if hasattr(self, "chk_synonyms"):
        from .composition_controls import refresh_gemini
        refresh_gemini(self)
    self._refresh_amq_available()
    self._refresh_song_geometry()
    self._fit_settings_width()
    # Во время сигнала toggled Qt ещё может держать старый sizeHint скрытой
    # песенной панели. Второй проход после обработки события не даёт следующим
    # галочкам («Кадры», «Персонажи») наехать на только что раскрытые поля.
    _api.QTimer.singleShot(0, self._refresh_song_geometry)
    self._recount()


def _refresh_song_geometry(self):
    """Пересчитать высоту вложенной панели после включения/выключения песен."""
    if getattr(self, "_closing", False):
        return
    for name in ("box_audio_opts", "box_song_opts"):
        box = getattr(self, name, None)
        if box is None:
            continue
        layout = box.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        box.setMinimumHeight(box.sizeHint().height() if not box.isHidden() else 0)
        box.updateGeometry()
    columns = getattr(self, "settings_columns", None)
    if columns is not None:
        columns.refresh_geometry()

def _on_song_kinds_toggled(self, *_):
    """Снятый тип песни убираем из полосы соотношения совсем."""
    parts = [(k, label) for k, label, chk in
             (("opening", "Опенинги", self.chk_op),
              ("ending", "Эндинги", self.chk_ed),
              ("insert", "OST", self.chk_in)) if chk.isChecked()]
    self.kind_bar.setVisible(bool(parts))
    if parts:
        self.kind_bar.set_parts(parts)
    ordinary = self.chk_op.isChecked() or self.chk_ed.isChecked()
    for name in ("sp_diff_min", "sp_diff_max"):
        if getattr(self, name, None) is not None:
            getattr(self, name).setEnabled(ordinary)
    for name in ("sp_ost_diff_min", "sp_ost_diff_max"):
        if getattr(self, name, None) is not None:
            getattr(self, name).setEnabled(self.chk_in.isChecked())
    if getattr(self, "song_diff_range", None) is not None:
        self.song_diff_range.setEnabled(ordinary)
    if getattr(self, "ost_diff_range", None) is not None:
        self.ost_diff_range.setEnabled(self.chk_in.isChecked())
    self._refresh_diff_bands()
    self._refresh_amq_available()


def _refresh_diff_bands(self, *_):
    """Рамки AMQ сами показывают свои числа; лишней сводки нет."""
    self._recount()

def _on_compress_images_toggled(self, checked: bool):
    if getattr(self, "box_img_opts", None) is not None:
        self.box_img_opts.setVisible(checked)

# ── общая кладовая обложек ────────────────────────────────────────────
def _on_poster_cache_toggled(self, checked: bool):
    if getattr(self, "lbl_poster_cache", None) is not None:
        self.lbl_poster_cache.setVisible(checked)
    if getattr(self, "btn_poster_clear", None) is not None:
        self.btn_poster_clear.setVisible(checked)
    if checked:
        self._refresh_poster_cache()

def _refresh_poster_cache(self):
    """Подпись с общим размером двух кладовых переиспользуемых медиа."""
    if getattr(self, "lbl_poster_cache", None) is None:
        return
    try:
        posters, poster_size = _api.poster_cache.stats()
        media, media_size = _api.media_cache.stats()
        num, size = posters + media, poster_size + media_size
    except Exception:  # noqa: BLE001 — подпись не повод падать
        num, size = 0, 0
    if not num:
        self.lbl_poster_cache.setText(
            "Кладовая медиа пуста — файлы появятся после генерации.")
        return
    # Запятая — только в дробном числе: «шт.» с точкой (иначе выходило
    # «1 шт,, 0,0 МБ»).
    mb = f"{size / (1024.0 * 1024.0):.1f}".replace(".", ",")
    self.lbl_poster_cache.setText(
        f"В кэше медиа: {num} шт., {mb} МБ "
        f"(потолок {_api.POSTER_CACHE_MB + _api.MEDIA_CACHE_MB} МБ)")

def _clear_poster_cache(self):
    try:
        gone = _api.poster_cache.clear() + _api.media_cache.clear()
    except Exception as e:  # noqa: BLE001
        _api.msgbox_warning(self, "Кэш медиа", f"Не вышло очистить: {e}")
        return
    self._refresh_poster_cache()
    self.log(f"Кэш медиа очищен: удалено {gone} файлов.")


def _open_db_table(self):
    """Окно «Что в базе»: тайтлы и персонажи кэша с индексом и сложностью."""
    from .db_table_dialog import open_db_table
    open_db_table(self)

def _open_cache_dialog(self):
    from .cache_dialog import CacheDialog
    dialog = getattr(self, "_cache_dialog", None)
    if dialog is None:
        dialog = CacheDialog(self, self._refresh_poster_cache)
        self._cache_dialog = dialog
    else:
        dialog.refresh()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

def _on_video_toggled(self, checked: bool):
    """Галочка роликов добавляет/убирает их долю в ползунке состава."""
    if getattr(self, "box_video_opts", None) is not None:
        self.box_video_opts.setVisible(checked)
    if getattr(self, "mix", None) is not None:
        self.mix.set_video(checked)
        self._refresh_song_opts()
    self._fit_settings_width()

def _on_manga_toggled(self, checked: bool):
    """То же для манги: без галочки её доли на ползунке нет."""
    if getattr(self, "box_manga", None) is not None:
        self.box_manga.setVisible(checked)
    if getattr(self, "mix", None) is not None:
        self.mix.set_manga(checked)
        self._refresh_song_opts()
    self._fit_settings_width()

def _on_pixel_toggled(self, checked: bool):
    """Галочка пикселей добавляет/убирает их долю в ползунке состава."""
    if getattr(self, "box_pixel", None) is not None:
        self.box_pixel.setVisible(checked)
    if getattr(self, "mix", None) is not None:
        self.mix.set_pixel(checked)
        self._refresh_song_opts()
    self._fit_settings_width()

def _on_anagram_toggled(self, checked: bool):
    """То же для анаграмм."""
    if getattr(self, "box_anagram", None) is not None:
        self.box_anagram.setVisible(checked)
    if getattr(self, "mix", None) is not None:
        self.mix.set_anagram(checked)
        self._refresh_song_opts()
    from .composition_controls import refresh_text_timing
    refresh_text_timing(self)
    self._fit_settings_width()

def _on_plot_toggled(self, checked: bool):
    """То же для вопросов по сюжету (им нужен ещё и ключ Gemini)."""
    if getattr(self, "box_plot", None) is not None:
        self.box_plot.setVisible(checked)
    if getattr(self, "mix", None) is not None:
        self.mix.set_plot(checked)
        self._refresh_song_opts()
    from .composition_controls import refresh_text_timing
    refresh_text_timing(self)
    self._fit_settings_width()

def _refresh_pixel_hint(self, *_):
    """Общая подсказка эффектов; имя сохранено для совместимости."""
    from si_hyx_parts.animepack_tab.frame_effect_controls import refresh_controls
    refresh_controls(self)

# ── группа «Аниме» ────────────────────────────────────────────────────
def _group_anime(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Аниме")
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    g.setContentsMargins(16, 18, 16, 14)
    self.sp_score_from = _api.QDoubleSpinBox(); self.sp_score_from.setRange(0, 10)
    self.sp_score_from.setSingleStep(0.5); self.sp_score_from.setDecimals(1)
    self.sp_score_to = _api.QDoubleSpinBox(); self.sp_score_to.setRange(0, 10)
    self.sp_score_to.setSingleStep(0.5); self.sp_score_to.setDecimals(1)
    self.sp_score_to.setValue(10.0)
    from datetime import date as _date
    self.sp_year_from = _api.QSpinBox(); self.sp_year_from.setRange(1900, 2100)
    self.sp_year_from.setValue(1944)
    self.sp_year_to = _api.QSpinBox(); self.sp_year_to.setRange(1900, 2100)
    self.sp_year_to.setValue(_date.today().year)
    for sp in (self.sp_score_from, self.sp_score_to,
               self.sp_year_from, self.sp_year_to):
        sp.setMinimumWidth(50)

    from .difficulty_range import DifficultyRange
    self.level_range = DifficultyRange(1, _api.MAX_LEVEL, minimum=1,
                                       maximum=_api.MAX_LEVEL,
                                       average=True)
    self.sp_level_from = self.level_range.low_control
    self.sp_level_to = self.level_range.high_control
    self.level_range.setMinimumWidth(240)
    tip = ("Насколько узнаваемы тайтлы в паке: 1 — то, что смотрели все "
           "(«Атака титанов», «Клинок, рассекающий демонов»), 15 — то, о "
           "чём почти никто не слышал. Считается по индексу популярности "
           "Shikimori, поэтому работает и без песен — по кадрам тоже.\n"
           "Поставьте «от 2», чтобы самые заезженные тайтлы в пак не "
           "попадали.\n"
           "Часть серии наследует узнаваемость всей франшизы: «Доктор "
           "Стоун: Научное будущее. Часть 3» считается настолько же "
           "известным, как «Доктор Стоун».")
    self.level_range.setToolTip(tip)
    # Средняя сложность — поверх рамок «от … до»: они говорят, что вообще
    # пускать, а это — на что должна выйти середина пака.
    self.sp_level_avg = self.level_range.avg_control
    self.sp_level_avg.setToolTip(
        "Куда должна выйти СРЕДНЯЯ сложность пака (просьба пользователя): "
        "«от 1 до 15, в среднем 4» — это пак, где крайности редки, а "
        "середина около четвёрки.\n"
        "«любая» (ноль) — не следить за средней вовсе, как было раньше.\n"
        "Пока набранная средняя выше цели, генератор берёт только тайтлы "
        "полегче, и наоборот. Если подходящих не находится, он всё же "
        "берёт что есть — иначе пак остался бы недобранным (о таком пишет "
        "в лог).")
    self.sp_level_avg.valueChanged.connect(self._recount)
    from si_hyx_parts.animepack_tab import level_panel
    level_panel.build(self)

    r = 0
    level_label = self._lab("Сложность")
    level_label.setContentsMargins(0, 5, 0, 0)
    g.addWidget(level_label, r, 0, alignment=_api.Qt.AlignmentFlag.AlignTop)
    g.addWidget(self.level_range, r, 1, 1, 3)
    r += 1
    # Рамки сложности КАЖДОГО рода вопросов — здесь же, сразу под общей
    # (просьба пользователя): песни, персонажи, арты, книги, сюжет. Показана
    # только та, чей род вопросов в паке есть (см. level_panel).
    r = level_panel.place(self, g, r)
    g.addWidget(self._hint("1 — знают все, 15 — не знает никто."), r, 0, 1, 4)
    r += 1
    g.addWidget(self._lab("Оценка от"), r, 0); g.addWidget(self.sp_score_from, r, 1)
    g.addWidget(self._lab("до"), r, 2); g.addWidget(self.sp_score_to, r, 3)
    r += 1
    g.addWidget(self._lab("Год с"), r, 0); g.addWidget(self.sp_year_from, r, 1)
    g.addWidget(self._lab("по"), r, 2); g.addWidget(self.sp_year_to, r, 3)
    r += 1
    g.addWidget(self._lab("Типы"), r, 0, 1, 4)
    r += 1
    self.chk_kinds = {}
    for i, kind in enumerate(_api.ANIME_KINDS):
        chk = _api.QCheckBox(_api.KIND_LABELS[kind])
        chk.setChecked(True)
        self.chk_kinds[kind] = chk
        g.addWidget(chk, r + i // 2, (i % 2) * 2, 1, 2)
    r += (len(_api.ANIME_KINDS) + 1) // 2
    self.btn_genres = _api.QPushButton("Жанры: любые")
    self.btn_genres.setToolTip("Жанры и темы Shikimori: зелёный ✓ — только с "
                               "ним, красный ✕ — исключить.")
    self.btn_genres.clicked.connect(self._open_genre_picker)
    g.addWidget(self.btn_genres, r, 0, 1, 4)
    r += 1
    self.chk_genres_partial = _api.QCheckBox("Достаточно одного жанра")
    self.chk_genres_partial.setChecked(True)
    self.chk_genres_partial.setToolTip(
        "Включено — аниме подходит, если у него есть ХОТЯ БЫ один из "
        "выбранных жанров. Выключено — нужны все сразу.")
    g.addWidget(self.chk_genres_partial, r, 0, 1, 4)
    for col in (1, 3):
        g.setColumnStretch(col, 1)
    return grp
