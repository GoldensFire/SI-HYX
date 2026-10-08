# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Генерация аниме-пака: реакции на настройки, списки пользователей, исключения, жанры и сбор PackSettings."""
from __future__ import annotations
import animepack_tab as _api


class AnimePackTabOptionsMixin:
    """Генерация аниме-пака: реакции на настройки, списки пользователей, исключения, жанры и сбор PackSettings."""

    def _on_source_switched(self, _lists: bool):
        self._refresh_lists_visibility()

    def _refresh_lists_visibility(self):
        """Карточки людей, совпадение и доли нужны, только когда пак
        собирается по спискам; кнопка базы — только при базе Shikimori."""
        random_mode = not self.src_switch.is_lists()
        self.box_users.setVisible(not random_mode)
        self.box_similar.setVisible(not random_mode)
        self.box_shares.setVisible(not random_mode
                                   and len(self.share_bar.keys()) > 1)
        self.btn_refresh_db.setVisible(random_mode)
        self._fit_settings_width()

    def _add_user_card(self, data: _api.Optional['_api.UserList'] = None):
        card = _api._UserCard(data or _api.UserList(), self.box_cards)
        card.removed.connect(self._remove_user_card)
        # Ник уходит в адресную книгу сразу, как только дописан, — не дожидаясь
        # запуска генерации: «в сохранённых должно числиться всё, что я вообще
        # добавлял».
        card.committed.connect(lambda c: self._remember_users([c.value()]))
        card.committed.connect(lambda *_: self._refresh_share_bar())
        card.changed.connect(self._on_card_changed)
        self._disable_wheel(card)
        self.cards_layout.addWidget(card)
        self._user_cards.append(card)
        self._refresh_share_bar()
        self._fit_settings_width()
        return card

    def _on_card_changed(self):
        """Карточку правили — подсказка состава могла устареть.

        Полосу долей отсюда НЕ трогаем: этот сигнал приходит на каждую букву
        ника, и доли перетасовывались бы прямо во время набора. Её пересобирает
        committed — когда ник дописан, а источник или раздел переключён."""
        self._recount()

    def _remove_user_card(self, card):
        try:
            self._user_cards.remove(card)
        except ValueError:
            pass
        card.setParent(None)
        card.deleteLater()
        self._refresh_share_bar()
        self._fit_settings_width()

    def _clear_user_cards(self):
        # Сначала в книгу, потом с глаз долой: кнопка «Очистить» убирает списки
        # из пака, а не забывает ники (для этого есть «Забыть отмеченных»).
        self._remember_users([c.value() for c in self._user_cards])
        for card in list(self._user_cards):
            self._remove_user_card(card)

    # ── адресная книга ников ──────────────────────────────────────────────
    @staticmethod
    def _user_key(user) -> tuple:
        return (user.username.strip().casefold(), user.source)

    def _remember_users(self, users) -> None:
        """Пополняет адресную книгу: любой ник, который вы вписали, потом
        добавляется одной кнопкой, а не набирается заново.

        Статусы тут не требуются нарочно: раньше ник запоминался только при
        запуске генерации и только со статусами, из-за чего «всё, что я вообще
        добавлял» в книге не оказывалось."""
        known = {self._user_key(u) for u in self._saved_users}
        for user in users:
            if not user.username.strip():
                continue
            key = self._user_key(user)
            if key in known:
                continue
            known.add(key)
            self._saved_users.append(_api.UserList(username=user.username.strip(),
                                              source=user.source,
                                              statuses=list(user.statuses)))

    def _open_saved_users(self):
        # В книгу заодно попадает всё, что набрано прямо сейчас: иначе окно
        # открылось бы без только что вписанного ника.
        self._remember_users([c.value() for c in self._user_cards])
        have = {self._user_key(c.value()) for c in self._user_cards}
        dlg = _api._SavedUsersDialog(self._saved_users, self, used=have)
        ok = dlg.exec()
        # «Забыть» действует независимо от того, чем закрыли окно.
        self._saved_users = dlg.remaining()
        if not ok:
            return
        # Галочки — это и есть итоговый набор списков: снятая убирает карточку,
        # поставленная добавляет.
        picked = {self._user_key(u): u for u in dlg.picked()}
        for card in list(self._user_cards):
            if self._user_key(card.value()) not in picked:
                self._remove_user_card(card)
        have = {self._user_key(c.value()) for c in self._user_cards}
        for key, user in picked.items():
            if key in have:
                continue
            self._add_user_card(_api.UserList(username=user.username,
                                         source=user.source,
                                         statuses=list(user.statuses),
                                         target=getattr(user, "target", "anime"),
                                         share=int(getattr(user, "share", 0) or 0),
                                         prefer_music=bool(
                                             getattr(user, "prefer_music", False))))

    def _on_mix_changed(self):
        """Ползунок состава сдвинули: настройки песен нужны, только если доля
        песен не нулевая."""
        self._refresh_song_opts()

    def _refresh_song_opts(self):
        """Настройки песен видны, только если песни в паке вообще будут.

        Видео находится внутри песен и скрывается вместе с их настройками.
        Второе число percents() сохранено для совместимости старого API."""
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
        """Видео — способ подачи песен; галочка не меняет состав пака."""
        if getattr(self, "box_video_opts", None) is not None:
            self.box_video_opts.setVisible(checked)
        if getattr(self, "mix", None) is not None:
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
            if getattr(self, "title_mix", None) is None:
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
        # Оценка и годы — такие же полосы с двумя ручками, как сложность
        # (просьба пользователя). Оценка хранится десятыми: 0…100 на полосе —
        # это 0.0…10.0 в настройках; sp_score_* отдают и принимают дроби, как
        # прежние спинбоксы.
        from datetime import date as _date
        from .difficulty_range import DifficultyRange, ScaledBound
        self.score_range = DifficultyRange(0, 100, minimum=0, maximum=100,
                                           formatter=lambda v: f"{v / 10:g}")
        self.sp_score_from = ScaledBound(self.score_range.low_control, 10)
        self.sp_score_to = ScaledBound(self.score_range.high_control, 10)
        # Сто лет до нынешнего: процентная полоса различает каждый год.
        this_year = _date.today().year
        self.year_range = DifficultyRange(1944, this_year,
                                          minimum=this_year - 100,
                                          maximum=this_year)
        self.sp_year_from = self.year_range.low_control
        self.sp_year_to = self.year_range.high_control
        for bar in (self.score_range, self.year_range):
            bar.setMinimumWidth(240)

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
        for title, bar in (("Оценка", self.score_range), ("Год", self.year_range)):
            label = self._lab(title)
            label.setContentsMargins(0, 5, 0, 0)
            g.addWidget(label, r, 0, alignment=_api.Qt.AlignmentFlag.AlignTop)
            g.addWidget(bar, r, 1, 1, 3)
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

    # ── группа «Прочее» ───────────────────────────────────────────────────
    def _group_other(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Прочее")
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        # Подписи нарочно короткие: длинный текст в QCheckBox не переносится и
        # задаёт минимальную ширину всей панели. Подробности — в подсказках.
        # Галочек «Дубли аниме» и «Дубли франшиз» больше нет: и то, и другое
        # выключено навсегда (просьба пользователя). Один тайтл — один вопрос,
        # одна франшиза — один тайтл.
        self.chk_sort_index = _api.QCheckBox("По индексу популярности")
        self.chk_sort_index.setToolTip(
            "Порядок вопросов и их цены берутся из «индекса популярности» — той "
            "же величины, по которой сортирует вкладка ShikimoriHYX (списки "
            "пользователей, взвешенные на свежесть выхода и слегка на оценку). "
            "Пак идёт от самых узнаваемых тайтлов к самым безвестным: самый "
            "узнаваемый вопрос стоит 2, самый редкий — 20.\n"
            "Выключено — цены считаются по сложности угадывания из AMQ.")
        # Отрезок песни, коллаж, подсказка о типе, сжатие дорожки, Chiptune и
        # каверы живут не здесь: всё, что про музыку, собрано под галочкой «Песни»
        # в составе пака (music_panel — просьба пользователя).
        # Сколько висит постер в ответе. Раньше это были зашитые три секунды.
        self.sp_answer_img = _api.QSpinBox()
        self.sp_answer_img.setRange(0, _api.ANSWER_IMAGE_MAX)
        self.sp_answer_img.setValue(3); self.sp_answer_img.setSuffix(" с")
        self.sp_answer_img.setMinimumWidth(74)
        self.sp_answer_img.setSpecialValueText("без ограничения")
        self.sp_answer_img.setToolTip(
            "Сколько секунд показывается постер тайтла в ОТВЕТЕ на вопрос.\n"
            f"Больше {_api.ANSWER_IMAGE_MAX} с не ставится: всё нужное с постера "
            "считывается за пару секунд, а игра тем временем стоит.\n"
            "«без ограничения» (ноль) — картинка остаётся на экране, пока "
            "ведущий не перейдёт дальше.")
        # ── Повторно используемые медиа и запасной источник обложек ────────
        self.chk_poster_cache = _api.QCheckBox("Хранить медиа в кэше на диске")
        self.chk_poster_cache.setChecked(True)
        self.chk_poster_cache.setToolTip(
            "Постеры, исходное аудио, кадры и готовые AVIF сохраняются рядом с "
            "настройками и при повторной генерации не скачиваются или не "
            "кодируются заново. Кэш постеров общий с вкладкой «Апгрейд пака».\n"
            "Случайные готовые вопросы и уникальные арты не сохраняются, чтобы "
            "паки не начинали повторяться.\n"
            f"Общий потолок — {_api.POSTER_CACHE_MB + _api.MEDIA_CACHE_MB} МБ; "
            "старые неиспользуемые файлы удаляются первыми.")
        self.chk_poster_cache.toggled.connect(self._on_poster_cache_toggled)
        self.btn_poster_clear = _api.QPushButton("Очистить")
        self.btn_poster_clear.setToolTip(
            "Удалить сохранённые постеры, аудио, кадры и готовые AVIF.")
        self.btn_poster_clear.clicked.connect(self._clear_poster_cache)
        self.btn_cache_view = _api.QPushButton("Файлы кэша…")
        self.btn_cache_view.setToolTip(
            "Посмотреть сохранённые файлы, открыть их или удалить выборочно.")
        self.btn_cache_view.clicked.connect(self._open_cache_dialog)
        self.lbl_poster_cache = _api.QLabel("")
        self.btn_tmdb_key = self._api_key_button("tmdb", "Ключ TMDB")
        self.sp_parallel = _api.QSpinBox(); self.sp_parallel.setRange(1, 16)
        self.sp_parallel.setValue(8); self.sp_parallel.setMinimumWidth(44)
        self.sp_parallel.setToolTip("Сколько вопросов качается одновременно.")
        self.chk_compress_images = _api.QCheckBox("Сжимать картинки")
        self.chk_compress_images.setChecked(True)
        self.chk_compress_images.setToolTip(
            "Включено — постеры и кадры пережимаются в AVIF тем же кодером, что "
            "и во вкладке «Обработка», с низким приоритетом процесса (работать "
            "за компьютером не мешает).\n"
            "Выключено — картинка кладётся в пак как есть, оригиналом с "
            "Shikimori: быстро, но пак тяжелее в разы.")
        self.chk_compress_images.toggled.connect(self._on_compress_images_toggled)
        self.sp_img_kb = _api.QSpinBox(); self.sp_img_kb.setRange(20, 2000)
        self.sp_img_kb.setValue(150); self.sp_img_kb.setSuffix(" КБ")
        self.sp_img_kb.setSingleStep(10); self.sp_img_kb.setMinimumWidth(74)
        self.sp_img_kb.setToolTip("До скольки ужимать каждую картинку.")
        self.sp_img_speed = _api.QSpinBox(); self.sp_img_speed.setRange(0, 8)
        self.sp_img_speed.setValue(8); self.sp_img_speed.setMinimumWidth(44)
        self.sp_img_speed.setToolTip(
            "Скорость кодирования AVIF (-cpu-used): 8 — самая быстрая, 0 — "
            "самая медленная и качественная. На 8 картинка считается меньше "
            "секунды, на 5 — секунд пять.")

        # «Сжимать аудио» стоит РЯДОМ со «Сжимать картинки» (просьба
        # пользователя): обе галочки про вес пака, и искать их логично вместе, а
        # не в настройках песенных вопросов. Сама подсказка осталась в
        # music_panel — она про звук отрезка.
        from .music_panel import COMPRESS_TIP
        self.chk_compress_audio = _api.QCheckBox("Сжимать аудио")
        self.chk_compress_audio.setChecked(True)
        self.chk_compress_audio.setToolTip(COMPRESS_TIP)

        r = 0
        g.addWidget(self.chk_compress_images, r, 0, 1, 4)
        r += 1
        # Настройки сжатия картинок видны, только когда оно включено.
        self.box_img_opts = _api.SettingsBox()
        ig = _api.QGridLayout(self.box_img_opts)
        ig.setContentsMargins(16, 0, 0, 0)
        ig.setHorizontalSpacing(8); ig.setVerticalSpacing(6)
        ig.addWidget(self._lab("Сжимать до"), 0, 0)
        ig.addWidget(self.sp_img_kb, 0, 1)
        ig.addWidget(self._lab("Скорость"), 1, 0)
        ig.addWidget(self.sp_img_speed, 1, 1)
        ig.setColumnStretch(1, 1)
        g.addWidget(self.box_img_opts, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_compress_audio, r, 0, 1, 4)
        r += 1
        self.chk_shuffle = _api.QCheckBox("Вопросы в разнобой")
        self.chk_shuffle.setToolTip(
            "Включено — вопросы в теме идут случайно, а не от дешёвых к "
            "дорогим: цена по теме скачет, как в живых паках.")
        g.addWidget(self.chk_shuffle, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_sort_index, r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Картинка в ответе"), r, 0, 1, 2)
        g.addWidget(self.sp_answer_img, r, 2, 1, 2)
        r += 1
        g.addWidget(self.chk_poster_cache, r, 0, 1, 2)
        g.addWidget(self.btn_cache_view, r, 2)
        g.addWidget(self.btn_poster_clear, r, 3)
        r += 1
        # Подпись «сколько обложек лежит» прячется вместе с галочкой, а ключ
        # TMDB — нет: запасной источник работает и без кладовой.
        g.addWidget(self.lbl_poster_cache, r, 0, 1, 4)
        # Подпись «сколько обложек лежит» нужна и без сохранённых настроек:
        # свежая вкладка иначе показывала бы пустую строку.
        self._refresh_poster_cache()
        r += 1
        g.addWidget(self._lab("Ключ TMDB"), r, 0, 1, 2)
        g.addWidget(self.btn_tmdb_key, r, 2, 1, 2)
        r += 1
        g.addWidget(self._lab("Параллельных загрузок"), r, 0, 1, 3)
        g.addWidget(self.sp_parallel, r, 3)
        r += 1
        # Готовые паки, чьи франшизы повторять не надо.
        excl_row = _api.QHBoxLayout(); excl_row.setSpacing(6)
        self.btn_excl_siq = _api.QPushButton("Не повторять франшизы из паков…")
        self.btn_excl_siq.setIcon(_api.get_icon('fa5s.file-import'))
        self.btn_excl_siq.setToolTip(
            "Выберите готовые .siq — программа прочитает их правильные ответы и "
            "не станет спрашивать те же франшизы снова. «Наруто» из старого "
            "пака закроет и «Наруто: Ураганные хроники» в новом.\n"
            "Читается только content.xml, медиа из архива не достаётся — это "
            "доли секунды на файл.")
        self.btn_excl_siq.clicked.connect(self._choose_exclude_siq)
        self.btn_excl_clear = _api.QPushButton("Очистить")
        self.btn_excl_clear.setToolTip("Убрать все паки из списка исключений.")
        self.btn_excl_clear.clicked.connect(self._clear_exclude_siq)
        self.btn_excl_list = _api.QPushButton("Изменить…")
        self.btn_excl_list.setToolTip("Добавить или убрать паки в списке.")
        self.btn_excl_list.clicked.connect(
            lambda: self._show_exclude_siq(False))
        excl_row.addWidget(self.btn_excl_siq, 1)
        excl_row.addWidget(self.btn_excl_list)
        excl_row.addWidget(self.btn_excl_clear)
        g.addLayout(excl_row, r, 0, 1, 4)
        r += 1
        self.lbl_excl_siq = self._hint("")
        g.addWidget(self.lbl_excl_siq, r, 0, 1, 4)
        r += 1
        exact_row = _api.QHBoxLayout(); exact_row.setSpacing(6)
        self.btn_exact_siq = _api.QPushButton("Не повторять из паков (те же вопросы)…")
        self.btn_exact_siq.setToolTip(
            "Пропускать только уже заданные вопросы: тот же OP/ED, тот же "
            "видеофрагмент сакуги, тот же сюжетный факт или то же медиа. "
            "Другие вопросы по этому аниме остаются доступны.")
        self.btn_exact_siq.clicked.connect(self._choose_exact_siq)
        self.btn_exact_clear = _api.QPushButton("Очистить")
        self.btn_exact_clear.clicked.connect(self._clear_exact_siq)
        self.btn_exact_list = _api.QPushButton("Изменить…")
        self.btn_exact_list.setToolTip("Добавить или убрать паки в списке.")
        self.btn_exact_list.clicked.connect(
            lambda: self._show_exclude_siq(True))
        exact_row.addWidget(self.btn_exact_siq, 1)
        exact_row.addWidget(self.btn_exact_list)
        exact_row.addWidget(self.btn_exact_clear)
        g.addLayout(exact_row, r, 0, 1, 4)
        r += 1
        self.lbl_exact_siq = self._hint("")
        g.addWidget(self.lbl_exact_siq, r, 0, 1, 4)
        r += 1
        self.chk_auto_add_exclusions = _api.QCheckBox(
            "Добавлять готовые паки в «не повторять»")
        self.chk_auto_add_exclusions.setChecked(True)
        self.chk_auto_add_exclusions.setToolTip(
            "После сохранения пака добавить его в оба списка выше: запрет "
            "франшиз и запрет тех же вопросов. Выключено — списки меняются "
            "только вручную. Для запущенного пака действует выбор на момент запуска.")
        g.addWidget(self.chk_auto_add_exclusions, r, 0, 1, 4)
        r += 1
        self.chk_ignore_test_packs = _api.QCheckBox("Не считать тестовые паки")
        self.chk_ignore_test_packs.setToolTip(
            "Паки меньше 96 вопросов получают отдельное имя «Тестовый № …», "
            "не занимают обычный номер и не исключают франшизы и вопросы "
            "из следующих паков.")
        g.addWidget(self.chk_ignore_test_packs, r, 0, 1, 4)
        r += 1
        self.btn_out_dir = _api.QPushButton("Папка для пака…")
        self.btn_out_dir.setIcon(_api.get_icon('fa5s.folder'))
        self.btn_out_dir.clicked.connect(self._choose_out_dir)
        g.addWidget(self.btn_out_dir, r, 0, 1, 4)
        r += 1
        self.lbl_out_dir = self._hint("")
        g.addWidget(self.lbl_out_dir, r, 0, 1, 4)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
        self._refresh_out_dir_label()
        self._refresh_exclude_label()
        self._refresh_exact_label()
        return grp

    # ── исключение франшиз по чужим пакам ─────────────────────────────────
    def _choose_exclude_siq(self):
        paths, _ = _api.QFileDialog.getOpenFileNames(
            self, "Паки, франшизы из которых не повторять",
            self._pack_picker_start(),
            "Пакеты SIGame (*.siq);;Все файлы (*)")
        if not paths:
            return
        have = {_api.os.path.normcase(p) for p in self._exclude_siq}
        for path in paths:
            if _api.os.path.normcase(path) not in have:
                self._exclude_siq.append(path)
                have.add(_api.os.path.normcase(path))
        self._refresh_exclude_label()

    def _clear_exclude_siq(self):
        self._exclude_siq = []
        self._refresh_exclude_label()

    def _show_exclude_siq(self, exact: bool):
        """Открыть редактируемый список одного из двух запретов повторов."""
        from .pack_list_dialog import show_included_packs
        paths = (self._exclude_exact_siq if exact else self._exclude_siq)
        title = ("Паки с уже заданными вопросами" if exact else
                 "Паки с исключёнными франшизами")
        attr = "_exact_list_dialog" if exact else "_franchise_list_dialog"
        old = getattr(self, attr, None)
        if old is not None:
            old.close()

        def changed(new_paths):
            if exact:
                self._exclude_exact_siq = list(new_paths)
                self._refresh_exact_label()
            else:
                self._exclude_siq = list(new_paths)
                self._refresh_exclude_label()

        setattr(self, attr, show_included_packs(
            self, title, list(paths), self._pack_picker_start(), changed,
            search_questions=exact))

    def _refresh_exclude_label(self):
        n = len(self._exclude_siq)
        if not n:
            self.lbl_excl_siq.setText("Исключений нет: пак собирается без "
                                      "оглядки на другие.")
            self.btn_excl_clear.setEnabled(False)
            self.btn_excl_list.setEnabled(True)
            return
        names = ", ".join(_api.os.path.basename(p) for p in self._exclude_siq[:3])
        if n > 3:
            names += f" и ещё {n - 3}"
        self.lbl_excl_siq.setText(f"Не повторяю франшизы из {n} пак(ов): {names}")
        self.lbl_excl_siq.setToolTip("\n".join(self._exclude_siq))
        self.btn_excl_clear.setEnabled(True)
        self.btn_excl_list.setEnabled(True)

    def _choose_exact_siq(self):
        paths, _ = _api.QFileDialog.getOpenFileNames(
            self, "Паки, вопросы из которых не повторять",
            self._pack_picker_start(),
            "Пакеты SIGame (*.siq);;Все файлы (*)")
        have = {_api.os.path.normcase(p) for p in self._exclude_exact_siq}
        for path in paths:
            if _api.os.path.normcase(path) not in have:
                self._exclude_exact_siq.append(path)
                have.add(_api.os.path.normcase(path))
        self._refresh_exact_label()

    def _clear_exact_siq(self):
        self._exclude_exact_siq = []
        self._refresh_exact_label()

    def _refresh_exact_label(self):
        count = len(self._exclude_exact_siq)
        self.lbl_exact_siq.setText(
            f"Не повторяю сами вопросы из {count} пак(ов)." if count else
            "Точные повторы из паков пока не исключаются.")
        self.lbl_exact_siq.setToolTip("")
        self.btn_exact_clear.setEnabled(bool(count))
        self.btn_exact_list.setEnabled(True)

    def _pack_picker_start(self) -> str:
        """Каталог, куда реально попадёт пак при текущих настройках."""
        if self._out_dir:
            return self._out_dir
        try:
            from utils import default_download_dir
            return default_download_dir()
        except Exception:
            return _api.os.path.expanduser("~")

    def _recount(self, *_):
        total = self.sp_rounds.value() * self.sp_themes.value() * self.sp_quest.value()
        self.lbl_total.setText(f"Вопросов в паке: {total}")
        if getattr(self, "cb_char_roles", None) is None:
            return                       # панель ещё строится
        settings = self.collect()
        if (settings.songs_percent
                and not any(chk.isChecked() for chk in
                            (self.chk_op, self.chk_ed, self.chk_in))):
            self.lbl_left.setText("Не выбран ни один тип песни — включите "
                                  "опенинги, эндинги или OST.")
            self.lbl_left.setStyleSheet(f"color:{_api.C['yellow']}; font-size:11px;")
            return
        # Ровно по одной строке на всё, что будет в паке (просьба пользователя):
        # «Кадров N, Опенингов N, Эндингов N, OST N, Персонажей N, Видео N».
        # Считает те же question_quotas, что и генератор, — цифры на вкладке и
        # в паке не расходятся.
        quotas = settings.question_quotas
        from .title_composition import LABELS
        counts = [f"{self.COUNT_LABELS[k]} — {quotas.get(k, 0)}"
                  for k in self.COUNT_ORDER if k not in LABELS and quotas.get(k, 0)]
        titles = sum(quotas.get(k, 0) for k in LABELS)
        if titles:
            counts.append(f"По названию — {titles}")
        parts = ", ".join(counts)
        # Приписки «Цены — по индексу популярности» тут больше нет: она висела
        # зелёным над всей панелью и ничего не подсказывала (просьба пользователя).
        if not parts:
            # Состав сняли целиком — раньше строка превращалась в одинокую точку
            # («» + «.»), и наверху панели висел непонятный знак препинания.
            self.lbl_left.setText("В составе пака ничего не выбрано — включите "
                                  "хотя бы один род вопросов.")
            self.lbl_left.setStyleSheet(f"color:{_api.C['yellow']}; font-size:11px;")
            return
        self.lbl_left.setText(parts + ".")
        self.lbl_left.setStyleSheet(f"color:{_api.C['green']}; font-size:11px;")

    def _refresh_out_dir_label(self):
        if self._out_dir:
            self.lbl_out_dir.setText(f"Пак сохранится в: {self._out_dir}")
        else:
            try:
                from utils import default_download_dir
                where = default_download_dir()
            except Exception:
                where = "папка загрузок"
            self.lbl_out_dir.setText(f"Пак сохранится в: {where}")

    def _choose_out_dir(self):
        start = self._pack_picker_start()
        path = _api.QFileDialog.getExistingDirectory(self, "Куда сохранять пак", start)
        if path:
            self._out_dir = path
            self._refresh_out_dir_label()

    # ── жанры ─────────────────────────────────────────────────────────────
    def _load_genres_async(self):
        if self._closing or self._genres_task is not None or self._genres_items:
            return
        task = _api._GenresTask()
        task.signals.finished.connect(self._on_genres_loaded)
        task.signals.failed.connect(self._on_genres_failed)
        self._genres_task = task
        self._pool.start(task)

    def _on_genres_loaded(self, genres: list):
        self._genres_task = None
        try:
            from shikimori_api import genre_group
        except Exception:
            def genre_group(_g):
                return "genre"
        items = []
        for g in genres:
            gid = g.get("id")
            if gid is None:
                continue
            items.append((int(gid), g.get("russian") or g.get("name") or str(gid),
                          genre_group(g)))
        items.sort(key=lambda x: x[1].lower())
        self._genres_items = items
        self._apply_pending_genres()

    def _apply_pending_genres(self):
        """Восстановленные из настроек id жанров применяем только после того,
        как пришёл их список — иначе нечем проверить, что такой жанр есть."""
        if not self._genres_items:
            return
        valid = {gid for gid, _, _ in self._genres_items}
        if self._pending_genres:
            self._sel_genres = [g for g in self._pending_genres if g in valid]
            self._pending_genres = []
        if self._pending_excl:
            self._excl_genres = [g for g in self._pending_excl if g in valid]
            self._pending_excl = []
        self._update_genres_btn()

    def _on_genres_failed(self, err: str):
        self._genres_task = None
        self.log(f"Список жанров не загрузился: {err}")

    def _open_genre_picker(self):
        if not self._genres_items:
            self._load_genres_async()
            _api.msgbox_information(self, "Жанры и темы",
                               "Список жанров ещё загружается — повторите через "
                               "секунду.")
            return
        from shikimori_tab import _GenrePickerDialog
        dlg = _GenrePickerDialog(self._genres_items, self._sel_genres,
                                 self._excl_genres, self)
        if dlg.exec():
            self._sel_genres = dlg.selected_ids()
            self._excl_genres = dlg.excluded_ids()
            self._update_genres_btn()

    def _update_genres_btn(self):
        names = {gid: label for gid, label, _ in self._genres_items}
        inc = [names.get(g, str(g)) for g in self._sel_genres]
        exc = [names.get(g, str(g)) for g in self._excl_genres]
        if not inc and not exc:
            self.btn_genres.setText("Жанры: любые")
            return
        parts = []
        if inc:
            parts.append("✓ " + ", ".join(inc[:2]) + ("…" if len(inc) > 2 else ""))
        if exc:
            parts.append("✕ " + ", ".join(exc[:2]) + ("…" if len(exc) > 2 else ""))
        self.btn_genres.setText("Жанры: " + "; ".join(parts))

    # ── настройки ─────────────────────────────────────────────────────────
    def collect(self) -> '_api.PackSettings':
        s = _api.PackSettings()
        s.preserve_composition = getattr(self, '_preserve_composition', True)
        s.ru_popularity = dict(getattr(self, "_ru_popularity_config", s.ru_popularity))
        s.title = self.ed_title.text().strip() or "Сгенерировано в SI-HYX"
        s.rounds = self.sp_rounds.value()
        s.themes = self.sp_themes.value()
        s.questions = self.sp_quest.value()
        s.theme_title = self.ed_theme.text().strip()
        # Сколько паков уже собрано: следующий получит номер на единицу больше
        # (см. start и pack_summary.numbered_title).
        s.pack_number = int(getattr(self, "_pack_number", 0) or 0)
        s.test_pack_number = int(getattr(self, "_test_pack_number", 0) or 0)
        s.random_mode = not self.src_switch.is_lists()
        s.random_source = "shikimori"
        s.users = [c.value() for c in self._user_cards]
        # Заодно пополняем книгу: collect() зовётся и при сохранении настроек,
        # так что ник не потеряется, даже если генерацию ни разу не запускали.
        self._remember_users(s.users)
        s.saved_users = list(self._saved_users)
        s.exclude_siq = list(self._exclude_siq)
        s.exclude_exact_siq = list(self._exclude_exact_siq)
        s.auto_add_to_exclusions = self.chk_auto_add_exclusions.isChecked()
        s.ignore_test_packs = self.chk_ignore_test_packs.isChecked()
        s.similar_count = self.sp_similar.value()
        from .composition_controls import collect
        collect(self, s)
        shares = self.mix.shares()
        (s.pct_songs, s.pct_videos, s.pct_frames,
         s.pct_chars, s.pct_manga) = self.mix.percents()
        s.pct_pixel = shares["pixel"]
        s.pct_plot = shares["plot"]
        from .description_controls import collect as collect_description
        collect_description(self, s)
        from .dialogue_controls import collect as collect_dialogue
        collect_dialogue(self, s)
        s.pct_ai_art = shares["ai_art"]
        s.pack_ai_art = self.chk_ai_art.isChecked()
        s.pct_pixiv_art = shares["pixiv_art"]
        s.pack_pixiv_art = self.chk_pixiv_art.isChecked()
        s.pixiv_refresh_token = self._api_key("pixiv")
        s.pixiv_r18_mode = self.cb_pixiv_r18.currentData() or "exclude"
        s.pixiv_ai_mode = self.cb_pixiv_ai.currentData() or "exclude"
        # Старые галочки пишем рядом: прежние сборки читают только их.
        s.pixiv_exclude_r18 = s.pixiv_r18_mode == "exclude"
        s.pixiv_exclude_ai = s.pixiv_ai_mode == "exclude"
        s.pixiv_allow_same_sex = self.chk_pixiv_same_sex.isChecked()
        s.pixiv_gemini_check = self.chk_pixiv_gemini.isChecked()
        from .frame_gemini_controls import collect as collect_frame_checks
        collect_frame_checks(self, s)
        s.pixiv_title_check_mode = self.cb_pixiv_title_mode.currentData() or "gemini"
        s.pixiv_gemini_model = self.cb_pixiv_gemini_model.currentText().strip()
        # Комиксы Pixiv (type=manga) не берутся никогда: это кадры с
        # репликами, а не рисунок (просьба пользователя — галочку убрали).
        s.pixiv_allow_manga = False
        s.pixiv_min_likes = self.sp_pixiv_likes.value()
        s.pixiv_groups_off = list(self._pixiv_groups_off)
        s.pixiv_tags_off = list(self._pixiv_tags_off)
        s.pixiv_tags_extra = list(self._pixiv_tags_extra)
        from si_hyx_parts.animepack_tab.sakuga_controls import collect as collect_sakuga
        collect_sakuga(self, s)
        from .episode_controls import collect as collect_episode
        collect_episode(self, s)
        from si_hyx_parts.animepack_tab.studio_controls import collect as collect_studio
        collect_studio(self, s)
        s.cloudflare_account_id = self._api_key("cloudflare_account_id")
        s.cloudflare_token = self._api_key("cloudflare")
        s.cloudflare_model = self.cb_cloudflare_model.currentData()
        s.pack_pixel = self.chk_pixel.isChecked()
        s.pixel_seconds = self.sp_pixel_sec.value()
        s.pixel_fps = self.sp_pixel_fps.value()
        s.pixel_steps = self.sp_pixel_steps.value()
        s.frame_preset = self.sp_frame_preset.value()
        s.pixel_block = self.sp_pixel_block.value()
        from si_hyx_parts.animepack_tab.frame_effect_controls import selected_effects
        s.frame_effect = self.cb_frame_effect.currentData() or "pixelize"
        s.frame_effects = selected_effects(self)
        s.frame_effect_strength = self.sp_frame_effect_strength.value()
        s.frame_dvd_folder = self.ed_dvd_folder.text().strip()
        s.frame_dvd_fps = int(self.cb_dvd_fps.currentData() or 30)
        from .entrance_controls import collect as collect_entrance
        collect_entrance(self, s)
        s.anagram_lang = self.cb_anagram_lang.currentData() or "russian"
        s.anagram_max_chars = self.sp_anagram_max.value()
        s.anagram_cps = self.sp_anagram_cps.value()
        s.pack_plot = self.chk_plot.isChecked()
        s.plot_mode = self.cb_plot_mode.currentData() or "title"
        s.gemini_key = self._api_key("gemini")
        s.gemini_model = self.cb_gemini_model.currentText().strip()
        s.gemini_image_model = self.cb_gemini_image_model.currentText().strip()
        s.gemini_image_thinking = self.cb_gemini_image_think.currentData() or "minimal"
        s.gemini_thinking = (self.cb_gemini_think.currentData()
                             or _api.GEMINI_THINKING_LEVEL)
        # Загадки по названию ходят к своей модели (просьба пользователя).
        s.gemini_title_model = self.cb_gemini_title_model.currentText().strip()
        s.gemini_title_thinking = (self.cb_gemini_title_think.currentData()
                                   or _api.GEMINI_THINKING_LEVEL)
        s.tmdb_key = self._api_key("tmdb")
        s.poster_cache = self.chk_poster_cache.isChecked()
        s.mark_owners = False
        s.char_roles = self.cb_char_roles.currentData() or "both"
        s.pack_manga = self.chk_manga.isChecked()
        s.manga_lang = self.cb_manga_lang.currentData() or ""
        s.manga_allow_erotica = self.chk_manga_erotica.isChecked()
        from si_hyx_parts.animepack_tab.manga_gemini_controls import collect as collect_manga_gemini
        collect_manga_gemini(self, s)
        from .manga_source_controls import collect as collect_manga_sources
        collect_manga_sources(self, s)
        s.manga_kinds = {k: chk.isChecked()
                         for k, chk in self.chk_manga_kinds.items()}
        s.song_video = self.chk_video.isChecked()
        s.video_cut = self.sp_video_cut.value()
        s.video_crf = self.sp_video_crf.value()
        s.video_preset = self.sp_video_preset.value()
        s.pick_openings = self.chk_op.isChecked()
        s.pick_endings = self.chk_ed.isChecked()
        s.pick_inserts = self.chk_in.isChecked()
        # Опенинги/эндинги/OST — это ДОЛИ песенных вопросов (полоса), а не
        # штуки: генератор всё равно ужимает их под число песен в паке.
        s.openings = self.kind_bar.value_of("opening")
        s.endings = self.kind_bar.value_of("ending")
        s.inserts = self.kind_bar.value_of("insert")
        s.difficulty_min = self.sp_diff_min.value()
        s.difficulty_max = self.sp_diff_max.value()
        s.ost_difficulty_min = self.sp_ost_diff_min.value()
        s.ost_difficulty_max = self.sp_ost_diff_max.value()
        s.categories = {c: chk.isChecked() for c, chk in self.chk_categories.items()}
        s.allow_rebroadcast = self.chk_rebroadcast.isChecked()
        s.allow_dub = self.chk_dub.isChecked()
        s.level_min = self.sp_level_from.value()
        s.level_max = self.sp_level_to.value()
        s.level_avg = self.sp_level_avg.value()
        from .level_controls import collect as collect_levels
        collect_levels(self, s)
        s.score_from = self.sp_score_from.value()
        s.score_to = self.sp_score_to.value()
        s.kinds = {k: chk.isChecked() for k, chk in self.chk_kinds.items()}
        s.year_from = self.sp_year_from.value()
        s.year_to = self.sp_year_to.value()
        s.genres_include = list(self._sel_genres)
        s.genres_exclude = list(self._excl_genres)
        s.genres_partial = self.chk_genres_partial.isChecked()
        # dup_anime/dup_franchise не трогаем: они выключены навсегда.
        s.sort_by_index = self.chk_sort_index.isChecked()
        s.images = self.chk_images.isChecked()
        s.images_time = self.sp_images_time.value()
        s.answer_image_time = self.sp_answer_img.value()
        # Подсказка о типе песни есть всегда: своей галочки у неё больше нет
        # (просьба пользователя), и сохранённое «выключено» из старых
        # настроек тоже не должно её гасить.
        s.hint = True
        s.compress_audio = self.chk_compress_audio.isChecked()
        from .music_effect_controls import collect_controls
        collect_controls(self, s)
        from .cover_controls import collect_controls as collect_cover_controls
        collect_cover_controls(self, s)
        from .karaoke_controls import collect_controls as collect_karaoke
        collect_karaoke(self, s)
        from .song_presentation_controls import collect as collect_presentations
        collect_presentations(self, s)
        s.compress_images = self.chk_compress_images.isChecked()
        s.image_limit_kb = self.sp_img_kb.value()
        s.image_speed = self.sp_img_speed.value()
        s.shuffle_questions = self.chk_shuffle.isChecked()
        s.audio_cut = self.sp_cut.value()
        s.parallel = self.sp_parallel.value()
        s.generation_priority = self.cb_generation_priority.currentData() or "normal"
        s.out_dir = self._out_dir
        return s

    def get_settings(self) -> dict:
        """Настройки вкладки для settings.json."""
        if not _api._HAS_CORE:
            return dict(self._initial)
        data = self.collect().to_dict()
        # Ключи API хранятся в общих настройках программы (Настройки → «Ключи
        # API»), а не здесь: иначе стёртый там ключ возвращался бы из этой
        # копии при следующем запуске.
        for k in ("gemini_key", "elevenlabs_key", "jimaku_key", "subdl_key", "tmdb_key",
                  "cloudflare_token",
                  "cloudflare_account_id", "pixiv_refresh_token", "animelib_token"):
            data.pop(k, None)
        return self._templates_to_settings(data)
