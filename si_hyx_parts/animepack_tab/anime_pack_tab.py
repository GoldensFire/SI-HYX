# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api
from si_hyx_parts.animepack.test_packs import TEST_LIMIT
from si_hyx_parts.animepack_tab.tab_layout import AnimePackTabLayoutMixin
from si_hyx_parts.animepack_tab.tab_options import AnimePackTabOptionsMixin
from si_hyx_parts.animepack_tab.presets import TemplatesMixin
from si_hyx_parts.animepack_tab.generation_queue import GenerationQueueMixin


def _compact_numeric_fields(tab):
    """Не даёт числовым полям растягиваться на целую колонку.

    Сетки настроек нарочно тянут правую колонку: это нужно длинным
    спискам и строкам, но QSpinBox из-за этого вырастал до 200–300 px.
    112 px хватает году, дробной оценке, проценту и длинному seed.
    """
    for cls in (_api.QSpinBox, _api.QDoubleSpinBox):
        for field in tab.findChildren(cls):
            field.setMaximumWidth(112)

def _remember_if_complete(self, result, wanted):
    """В «не повторять» сам попадает только полный пак.

    Обрубок после ошибки или остановки тоже добавлялся — и его франшизы
    выпадали из следующих паков, хотя его обычно пересобирают, а не играют."""
    if not wanted or not result.path:
        return
    if result.cancelled or result.aborted or len(result.songs) < result.requested:
        self.log("В исключения не добавлен: пак неполный. Если будете его "
                 "играть, добавьте его в список вручную.")
        return
    self._remember_generated(result.path)


# ─────────────────────────────────────────────────────────────────────────────
# Вкладка
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackTab(
    AnimePackTabLayoutMixin,
    AnimePackTabOptionsMixin,
    TemplatesMixin,
    GenerationQueueMixin,
    _api.QWidget,
):
    """Генератор аниме-паков для «Своей игры» (порт ASPG)."""

    def __init__(self, main_window=None, settings: _api.Optional[dict] = None):
        super().__init__()
        self.main = main_window
        self._pool = _api.QThreadPool.globalInstance()
        self._task = None
        self._queue = []                  # снимки настроек ожидающих паков
        self._active_settings = None
        self._genres_task = None
        self._genres_timer = None          # отложенная загрузка списка жанров
        self._db_task = None               # обновление базы Shikimori
        self._db_parts = ()                # какие её части сейчас собираются
        self._genres_items: list = []      # (id, подпись, группа) для окна выбора
        self._sel_genres: list = []
        self._excl_genres: list = []
        self._pending_genres: list = []
        self._pending_excl: list = []
        self._user_cards: list = []
        self._saved_users: list = []       # адресная книга ников
        self._exclude_siq: list = []       # паки, чьи франшизы не повторяем
        self._exclude_exact_siq: list = [] # паки, чьи вопросы не повторяем
        self._out_dir = ""
        self._pack_number = 0              # сколько паков уже собрано (для «№ N»)
        self._test_pack_number = 0
        self._last_pack = ""
        self._started_at = 0.0             # для оценки времени на прогресс-баре
        self._closing = False              # после cleanup() новых задач не заводим
        self._initial = dict(settings or {})
        self._load_templates(self._initial)

        if not _api._HAS_CORE:
            self._build_unavailable()
            return
        self._build_ui()
        if self._initial:
            try:
                self.apply_settings(self._initial)
            except Exception:
                pass
        self._recount()
        self._update_table_hint()
        # Жанры нужны только при открытии окна выбора — тянем их с задержкой,
        # чтобы не толкаться с остальным стартом приложения. Таймер именно свой,
        # а не QTimer.singleShot: статический уходит жить сам по себе, и его уже
        # ничем не отменить — cleanup() закрывал вкладку, а через полторы секунды
        # всё равно уходил сетевой запрос.
        self._genres_timer = _api.QTimer(self)
        self._genres_timer.setSingleShot(True)
        self._genres_timer.timeout.connect(self._load_genres_async)
        self._genres_timer.start(1500)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_unavailable(self):
        lay = _api.QVBoxLayout(self)
        lbl = _api.QLabel("Не удалось загрузить вкладку «Генерация аниме-пака».\n\n"
                     f"{_api._IMPORT_ERROR}")
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    def _build_ui(self):
        root = _api.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 0, 12)
        root.setSpacing(10)

        body = _api.QHBoxLayout(); body.setSpacing(12)
        root.addLayout(body, 1)

        # ── Слева: состав пака, лог, прогресс ─────────────────────────────
        # Таблица живёт в своей коробке и по умолчанию СПРЯТАНА: до генерации в
        # ней пусто, а место (полвкладки) нужнее настройкам — они и занимают всю
        # ширину, раскладываясь в несколько колонок. Показывается таблица кнопкой
        # «Показать таблицу» под настройками (просьба пользователя).
        self.table_box = _api.QWidget()
        left = _api.QVBoxLayout(self.table_box); left.setSpacing(6)
        left.setContentsMargins(0, 0, 0, 0)
        self.table = _api.QTableWidget(0, len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.TABLE_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(_api.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(_api.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        # Клик по заголовку сортирует таблицу; «№» возвращает порядок пака.
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        # Родная стрелка сортировки ВЫКЛЮЧЕНА нарочно: место под неё Qt
        # резервирует в каждой секции (замерено — ровно 28 px на колонку), из-за
        # чего «Раунд», «Цена» и «Ур.» были вчетверо шире своих цифр. Стрелку
        # рисуем сами — стрелочкой в подписи сортируемой колонки.
        hh.setSortIndicatorShown(False)
        hh.sortIndicatorChanged.connect(self._on_sort_changed)
        hh.setSectionsClickable(True)
        # Ширина колонки — по её содержимому: длинные названия аниме не режутся,
        # а короткие «Ур.» и «Цена» не занимают полтаблицы. Растягивать колонки
        # на всю ширину (Stretch) больше не нужно — пусть будут по значениям.
        hh.setSectionResizeMode(_api.QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(False)
        # Узкие колонки не должны раздуваться из-за заголовка: у «Раунда» и
        # «Цены» содержимое — одна-две цифры, а секция выходила вчетверо шире
        # (просьба пользователя). Стрелку сортировки рисуем маленькой и поверх
        # текста — место под неё Qt резервирует в КАЖДОЙ секции.
        hh.setMinimumSectionSize(24)
        hh.setDefaultAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        # Подсказка «из чего сложился индекс» — своим тёмным попапом по наведению
        # (просьба пользователя), а не синим системным QToolTip.
        from si_hyx_parts.animepack_tab.index_tooltip import install as install_tip
        install_tip(self.table)
        # Таблица занимает всю высоту вкладки: строки состояния над ней больше
        # нет — «Готово за столько-то» пишется прямо на общей полосе прогресса
        # (просьба пользователя), а освободившееся место отдано таблице.
        # Пока таблица пустая (пак ещё не сгенерирован), вместо неё показываем
        # предупреждение про запрет выкладывать сгенерированное в сеть.
        left.addWidget(self.table, 1)
        # Предупреждение рисуется НАКЛАДКОЙ прямо на таблицу (родитель — сама
        # таблица, а не общий layout): скрывать/показывать саму QTableWidget
        # здесь нельзя — hide()/show() на ней плодит крэши в тестах на этой
        # связке PyQt6/Qt. Накладка перекрывает пустую таблицу целиком, пока
        # пак не собран, а прячется — сама, table остаётся видимой всегда.
        self.lbl_table_hint = _api.QLabel(
            "Сгенерированные паки/вопросы запрещено выкладывать в сеть.",
            self.table)
        self.lbl_table_hint.setWordWrap(True)
        self.lbl_table_hint.setAlignment(
            _api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_table_hint.setStyleSheet(
            f"background:{_api.C['bg']}; color:{_api.C['text2']}; font-size:13px; "
            "padding: 0 12px;")
        self.lbl_table_hint.setGeometry(self.table.rect())
        # Ни своей консоли, ни своего прогресс-бара у вкладки нет: и то, и
        # другое идёт в общую полосу внизу окна, как у остальных вкладок.
        self.table_box.setVisible(False)
        body.addWidget(self.table_box, 1)

        self._build_settings_panel(body)
        _compact_numeric_fields(self)
        self._apply_styles()
        # Стили меняют размеры полей — ширину панели считаем уже по ним.
        self._fit_settings_width()
        self._on_song_kinds_toggled()

    # Подписи колонок таблицы состава пака. «Ур.» — сложность тайтла. Отдельной
    # колонки «Перс.» больше нет (просьба пользователя): уровень вопроса-
    # персонажа всегда равен уровню тайтла и только дублировал «Ур.».
    TABLE_HEADERS = ("№", "Раунд", "Тема", "Цена", "Аниме", "Песня", "Тип",
                     "Сложн.", "Индекс", "Ур.")
    # Колонки с числами — их выравниваем по центру.
    TABLE_NUM_COLS = (0, 1, 2, 3, 7, 8, 9)

    # Уже этого панель настроек не сжимается: дальше подписи начинают резаться.
    SETTINGS_MIN_W = 300
    # Столько ширины оставляем таблице состава пака, пока есть из чего.
    TABLE_MIN_W = 260
    # Неподвижная колонка «Пак» + кнопки запуска: уже этого её поля режутся,
    # а шире — она отнимает ширину у настроек ни за что (кнопке
    # «Сгенерировать пак» хватает 242 точек, полю «Название» — сколько дадут).
    PACK_MIN_W = 300
    PACK_MAX_W = 310

    # ── мелкая логика формы ───────────────────────────────────────────────
    # В каком порядке перечислять вопросы в итоговой строке состава.
    COUNT_ORDER = (_api.FRAME_KIND, "opening", "ending", "insert", _api.CHAR_KIND,
                   _api.VIDEO_KIND, _api.MANGA_KIND, _api.PIXEL_KIND,
                   _api.ANAGRAM_KIND, _api.DIALOGUE_KIND, _api.PLOT_KIND,
                   _api.DESCRIPTION_AUDIO_KIND,
                   _api.AI_ART_KIND,
                   _api.PIXIV_ART_KIND, _api.SAKUGA_KIND,
                   _api.STUDIO_KIND, _api.EPISODE_KIND)
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
                    _api.STUDIO_KIND: "Студий", _api.EPISODE_KIND: "Отрывков серий"}

    def apply_settings(self, data: dict):
        if not _api._HAS_CORE or not isinstance(data, dict):
            return
        s = _api.PackSettings.from_dict(data)
        self._preserve_composition = s.preserve_composition
        from .song_video_controls import migrate_settings
        migrate_settings(s)
        self._ru_popularity_config = dict(s.ru_popularity)
        from .entrance_controls import apply as apply_entrance
        apply_entrance(self, s)
        self.ed_title.setText(s.title)
        self.ed_theme.setText(s.theme_title)
        # Сколько паков уже собрано: следующий получит номер на единицу больше.
        self._pack_number = max(0, int(getattr(s, "pack_number", 0) or 0))
        self._test_pack_number = max(0, int(getattr(s, "test_pack_number", 0) or 0))
        self.sp_rounds.setValue(s.rounds)
        self.sp_themes.setValue(s.themes)
        self.sp_quest.setValue(s.questions)
        # Прежний «случайные из базы AMQ» открывается базой Shikimori.
        self.src_switch.set_lists(not s.random_mode)
        self._clear_user_cards()
        for u in s.users:
            self._add_user_card(u)
        self._saved_users = list(s.saved_users)
        self._exclude_siq = list(s.exclude_siq)
        self._refresh_exclude_label()
        self._exclude_exact_siq = list(getattr(s, "exclude_exact_siq", []))
        self._refresh_exact_label()
        self.chk_auto_add_exclusions.setChecked(s.auto_add_to_exclusions)
        self.chk_ignore_test_packs.setChecked(s.ignore_test_packs)
        self.sp_similar.setValue(max(1, int(s.similar_count)))
        # Галочки необязательных частей — ДО долей: они решают, есть ли в полосе
        # такие части (иначе сохранённые проценты уехали бы в песни).
        self.chk_video.setChecked(s.song_video)
        self.chk_manga.setChecked(s.pack_manga)
        self.mix.set_manga(s.pack_manga)
        self.chk_pixel.setChecked(s.pack_pixel)
        self.mix.set_pixel(s.pack_pixel)
        self.chk_anagram.setChecked(s.pack_anagram)
        self.mix.set_anagram(s.pack_anagram)
        self.chk_plot.setChecked(s.pack_plot)
        self.mix.set_plot(s.pack_plot)
        from .description_controls import apply as apply_description
        apply_description(self, s)
        from .dialogue_controls import apply as apply_dialogue
        apply_dialogue(self, s)
        self.chk_ai_art.setChecked(s.pack_ai_art)
        self.mix.set_ai_art(s.pack_ai_art)
        self.chk_pixiv_art.setChecked(s.pack_pixiv_art)
        self.mix.set_pixiv_art(s.pack_pixiv_art)
        self.chk_sakuga.setChecked(s.pack_sakuga)
        self.mix.set_sakuga(s.pack_sakuga)
        from .episode_controls import apply_controls as apply_episode
        apply_episode(self, s)
        self.chk_studio.setChecked(s.pack_studio)
        self.mix.set_studio(s.pack_studio)
        from .composition_controls import apply, TITLE_LABELS
        apply(self, s)
        shares = s.mix_shares
        self.mix.set_shares({
            "songs": shares.get("songs", 0), "video": shares.get(_api.VIDEO_KIND, 0),
            "frames": shares.get(_api.FRAME_KIND, 0),
            "chars": shares.get(_api.CHAR_KIND, 0),
            "manga": shares.get(_api.MANGA_KIND, 0),
            "pixel": shares.get(_api.PIXEL_KIND, 0),
            "anagram": shares.get(_api.ANAGRAM_KIND, 0),
            "plot": shares.get(_api.PLOT_KIND, 0),
            "description_audio": shares.get(_api.DESCRIPTION_AUDIO_KIND, 0),
            "dialogue": shares.get(_api.DIALOGUE_KIND, 0),
            "ai_art": shares.get(_api.AI_ART_KIND, 0),
            "pixiv_art": shares.get(_api.PIXIV_ART_KIND, 0),
            "sakuga": shares.get(_api.SAKUGA_KIND, 0),
            "episode": shares.get(_api.EPISODE_KIND, 0),
            "studio": shares.get(_api.STUDIO_KIND, 0),
            **{k: shares.get(k, 0) for k in TITLE_LABELS}})
        from si_hyx_parts.animepack_tab.ai_art_controls import apply_controls
        apply_controls(self, s)
        from si_hyx_parts.animepack_tab.pixiv_art_controls import apply_controls
        apply_controls(self, s)
        from si_hyx_parts.animepack_tab.sakuga_controls import apply_controls
        apply_controls(self, s)
        from si_hyx_parts.animepack_tab.studio_controls import apply_controls
        apply_controls(self, s)
        self.sp_pixel_sec.setValue(max(2, int(s.pixel_seconds or _api.PIXEL_SECONDS)))
        self.sp_pixel_fps.setValue(max(1, min(60, int(s.pixel_fps or _api.PIXEL_FPS))))
        self.sp_pixel_steps.setValue(max(1, min(20, int(s.pixel_steps or _api.PIXEL_STEPS))))
        self.sp_pixel_block.setValue(max(4, min(256, int(s.pixel_block or _api.PIXEL_BLOCK))))
        from si_hyx_parts.animepack_tab.frame_effect_controls import apply_controls
        apply_controls(self, s)
        idx = self.cb_anagram_lang.findData(s.anagram_lang)
        self.cb_anagram_lang.setCurrentIndex(idx if idx >= 0 else 0)
        self.sp_anagram_max.setValue(
            max(0, min(200, int(getattr(s, "anagram_max_chars", _api.ANAGRAM_MAX_CHARS)
                                or 0))))
        try:
            cps = float(getattr(s, "anagram_cps", _api.ANAGRAM_CHARS_PER_SEC) or 0.0)
        except (TypeError, ValueError):
            cps = _api.ANAGRAM_CHARS_PER_SEC
        self.sp_anagram_cps.setValue(max(0.0, min(_api.ANAGRAM_CPS_MAX, cps)))
        idx = self.cb_plot_mode.findData(s.plot_mode)
        self.cb_plot_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._migrate_api_key("gemini", s.gemini_key)
        if s.gemini_model:
            if self.cb_gemini_model.findText(s.gemini_model) < 0:
                self.cb_gemini_model.addItem(s.gemini_model, s.gemini_model)
            self.cb_gemini_model.setCurrentText(s.gemini_model)
        # Список уровней зависит от модели (у Flash нет «минимального»), поэтому
        # сперва пересобираем его под уже выбранную модель, а недоступный уровень
        # заменяем ближайшим доступным — первым в списке.
        from si_hyx_parts.animepack_tab.gemini_model_controls import (
            refresh_thinking_levels)
        refresh_thinking_levels(self)
        idx = self.cb_gemini_think.findData(
            str(getattr(s, "gemini_thinking", "") or _api.GEMINI_THINKING_LEVEL))
        if idx < 0:
            idx = self.cb_gemini_think.findData(_api.GEMINI_THINKING_LEVEL)
        self.cb_gemini_think.setCurrentIndex(max(0, idx))
        # То же самое для своей модели загадок по названию. Пустое значение в
        # старых settings.json значит «как у сюжета».
        title_model = str(getattr(s, "gemini_title_model", "") or "") or s.gemini_model
        if title_model:
            if self.cb_gemini_title_model.findText(title_model) < 0:
                self.cb_gemini_title_model.addItem(title_model, title_model)
            self.cb_gemini_title_model.setCurrentText(title_model)
        from si_hyx_parts.animepack_tab.gemini_title_controls import refresh_levels
        refresh_levels(self)
        idx = self.cb_gemini_title_think.findData(
            str(getattr(s, "gemini_title_thinking", "") or "")
            or str(getattr(s, "gemini_thinking", "") or _api.GEMINI_THINKING_LEVEL))
        if idx < 0:
            idx = self.cb_gemini_title_think.findData(_api.GEMINI_THINKING_LEVEL)
        self.cb_gemini_title_think.setCurrentIndex(max(0, idx))
        self._migrate_api_key("tmdb", getattr(s, "tmdb_key", ""))
        self.chk_poster_cache.setChecked(bool(getattr(s, "poster_cache", True)))
        self._on_poster_cache_toggled(self.chk_poster_cache.isChecked())
        self.sp_video_cut.setValue(max(3, int(s.video_cut)))
        self.sp_video_crf.setValue(max(0, min(63, int(s.video_crf))))
        self.sp_video_preset.setValue(max(0, min(13, int(s.video_preset))))
        idx = self.cb_char_roles.findData(s.char_roles)
        self.cb_char_roles.setCurrentIndex(idx if idx >= 0 else
                                           self.cb_char_roles.findData("both"))
        idx = self.cb_manga_lang.findData(str(getattr(s, "manga_lang", "") or ""))
        self.cb_manga_lang.setCurrentIndex(idx if idx >= 0 else 0)
        self.chk_manga_erotica.setChecked(
            bool(getattr(s, "manga_allow_erotica", False)))
        from si_hyx_parts.animepack_tab.manga_gemini_controls import apply_controls as apply_manga_gemini
        apply_manga_gemini(self, s)
        from .gemini_groups import apply as apply_gemini_groups
        apply_gemini_groups(self, s)
        from .frame_gemini_controls import apply_controls as apply_frame_checks
        apply_frame_checks(self, s)
        from .manga_source_controls import apply_controls as apply_manga_sources
        apply_manga_sources(self, s)
        for kind, chk in self.chk_manga_kinds.items():
            chk.setChecked(bool(s.manga_kinds.get(kind, False)))
        self.chk_op.setChecked(s.pick_openings)
        self.chk_ed.setChecked(s.pick_endings)
        self.chk_in.setChecked(s.pick_inserts)
        # Галочки уже переставили набор частей полосы — теперь её значения.
        self._on_song_kinds_toggled()
        self.kind_bar.set_values({"opening": s.openings, "ending": s.endings,
                                  "insert": s.inserts})
        self.sp_diff_min.setValue(int(s.difficulty_min))
        self.sp_diff_max.setValue(int(s.difficulty_max))
        saved_ost_min = getattr(s, "ost_difficulty_min", None)
        saved_ost_max = getattr(s, "ost_difficulty_max", None)
        ost_min = s.difficulty_min if saved_ost_min is None else saved_ost_min
        ost_max = s.difficulty_max if saved_ost_max is None else saved_ost_max
        self.sp_ost_diff_min.setValue(int(ost_min))
        self.sp_ost_diff_max.setValue(int(ost_max))
        # Полоса рамки меняется без сигнала (set_range нарочно молчит), поэтому
        # строчку «какая рамка на какой тип песни» обновляем здесь сами.
        self._refresh_diff_bands()
        for cat, chk in self.chk_categories.items():
            chk.setChecked(bool(s.categories.get(cat, True)))
        self.chk_rebroadcast.setChecked(s.allow_rebroadcast)
        self.chk_dub.setChecked(s.allow_dub)
        self.level_range.set_range(max(1, min(_api.MAX_LEVEL, int(s.level_min))),
                                   max(1, min(_api.MAX_LEVEL, int(s.level_max))))
        self.sp_level_avg.setValue(
            max(0, min(_api.MAX_LEVEL, int(s.level_avg))))
        from .level_controls import apply_controls as apply_levels
        apply_levels(self, s)
        self.sp_score_from.setValue(float(s.score_from))
        self.sp_score_to.setValue(float(s.score_to))
        for kind, chk in self.chk_kinds.items():
            chk.setChecked(bool(s.kinds.get(kind, True)))
        self.sp_year_from.setValue(int(s.year_from))
        self.sp_year_to.setValue(int(s.year_to))
        # Жанры подставим, когда придёт их список (id проверяются по нему).
        self._pending_genres = list(s.genres_include)
        self._pending_excl = list(s.genres_exclude)
        self._apply_pending_genres()
        self.chk_genres_partial.setChecked(s.genres_partial)
        self.chk_sort_index.setChecked(s.sort_by_index)
        self.chk_images.setChecked(s.images)
        self.sp_images_time.setValue(int(s.images_time))
        self.sp_answer_img.setValue(
            max(0, min(_api.ANSWER_IMAGE_MAX, int(s.answer_image_time))))
        self.chk_compress_audio.setChecked(s.compress_audio)
        from .music_effect_controls import apply_controls
        apply_controls(self, s)
        from .cover_controls import apply_controls as apply_cover_controls
        apply_cover_controls(self, s)
        from .karaoke_controls import apply_controls as apply_karaoke
        apply_karaoke(self, s)
        from .song_presentation_controls import apply as apply_presentations
        apply_presentations(self, s)
        self.chk_compress_images.setChecked(s.compress_images)
        self.sp_img_kb.setValue(max(20, int(s.image_limit_kb)))
        self.sp_img_speed.setValue(max(0, min(8, int(s.image_speed))))
        self.chk_shuffle.setChecked(s.shuffle_questions)
        self.sp_cut.setValue(int(s.audio_cut))
        self.sp_parallel.setValue(int(s.parallel))
        priority_index = self.cb_generation_priority.findData(s.generation_priority)
        self.cb_generation_priority.setCurrentIndex(
            priority_index if priority_index >= 0 else 1)
        self._out_dir = s.out_dir or ""
        self._refresh_out_dir_label()
        # Доли списков: галочка включается сама, если в настройках они заданы.
        # Значения ставим на полосу из ФАЙЛА, а не из карточек: пока карточки
        # добавлялись по одной, полоса успела раздать им свои доли.
        saved_shares = {self._share_key(u): int(u.share or 0) for u in s.users}
        self.chk_shares.blockSignals(True)
        self.chk_shares.setChecked(any(saved_shares.values()))
        self.chk_shares.blockSignals(False)
        self.share_bar.setVisible(self.chk_shares.isChecked())
        self._refresh_share_bar()
        if any(saved_shares.values()):
            self.share_bar.set_values(saved_shares)
            self._on_share_bar_changed()
        self._refresh_lists_visibility()
        self._refresh_song_opts()
        self._on_compress_images_toggled(s.compress_images)
        self._on_video_toggled(s.song_video)
        self._on_manga_toggled(s.pack_manga)
        self._on_pixel_toggled(s.pack_pixel)
        self._on_anagram_toggled(s.pack_anagram)
        self._on_plot_toggled(s.pack_plot)
        self._on_song_kinds_toggled()
        self._refresh_pixel_hint()
        self._recount()

    def reset_settings(self):
        self._sel_genres = []
        self._excl_genres = []
        # Адресную книгу сброс настроек не трогает: ники копятся годами, а
        # кнопка обещает вернуть настройки, а не стереть накопленное.
        saved = list(self._saved_users)
        self.apply_settings(_api.PackSettings().to_dict())
        self._saved_users = saved
        self._update_genres_btn()

    # ── генерация ─────────────────────────────────────────────────────────
    def log(self, msg: str):
        """Всё пишем в общую консоль внизу окна — своей у вкладки нет."""
        if self.main is not None and hasattr(self.main, "log"):
            try:
                self.main.log(f"[Аниме-пак] {msg}")
            except Exception:
                pass

    def _log_gap(self, lines: int = 5):
        """Пустые строки перед логами нового прогона — чтобы их было видно."""
        main = self.main
        if main is None:
            return
        try:
            if hasattr(main, "log_gap"):
                main.log_gap(lines)
            else:                              # старое главное окно без отбивки
                for _ in range(lines):
                    main.txt_log.append("")
        except Exception:
            pass

    def start(self):
        if self._db_task is not None and self._task is None:
            _api.msgbox_information(self, "Секунду",
                               "Сейчас обновляется база Shikimori — дождитесь "
                               "конца или остановите сбор той же кнопкой, иначе "
                               "пак соберётся по полупустому каталогу.")
            return
        settings = self.collect()
        problems = settings.validate()
        if problems:
            _api.msgbox_warning(self, "Так не получится", "\n\n".join(problems))
            return
        if self._task is not None or self._queue:
            self._queue.append(settings)
            self._refresh_queue()
            self.log(f"Добавлен в очередь: «{settings.title}» "
                     f"({settings.total_questions} вопросов).")
            if self._task is None:
                self._start_next()
            return
        self._launch_generation(settings)

    def _launch_generation(self, settings, recovery: str = ""):
        # В очереди каждый пак хранит свой приоритет; поле показывает активный.
        blocked = self.cb_generation_priority.blockSignals(True)
        try:
            self.cb_generation_priority.setCurrentIndex(
                self.cb_generation_priority.findData(settings.generation_priority))
        finally:
            self.cb_generation_priority.blockSignals(blocked)
        # Каждый новый пак — следующий номер в названии (просьба пользователя).
        # Считаем ЗДЕСЬ, а не в генераторе: имя файла и название внутри пака должны
        # совпасть, а известны они генератору с самого начала. Сохраняем сразу —
        # иначе аварийное закрытие программы вернуло бы нумерацию назад.
        #
        # ОТМЕНЁННАЯ генерация номер возвращает (см. _release_pack_number): пак,
        # который бросили на середине, — не пак, и следующий не должен через него
        # перешагивать.
        settings.test_pack_number = self._test_pack_number + 1
        if settings.ignore_test_packs and settings.total_questions < TEST_LIMIT:
            settings.pack_number = 0
        else:
            self._pack_number = int(getattr(self, "_pack_number", 0) or 0) + 1
            settings.pack_number = self._pack_number
        saver = getattr(self.main, "_save_settings_soon", None)
        if saver is not None:
            try:
                saver()
            except Exception:      # noqa: BLE001 — номер важнее, чем запись
                pass
        self._remember_users(settings.users)
        if self.main is not None and hasattr(self.main, "clear_global_result"):
            self.main.clear_global_result()
        self.table.setRowCount(0)
        self._update_table_hint()
        self.btn_table.setEnabled(False)
        self.btn_table.setText("Показать таблицу")
        self._last_pack = ""
        self.btn_open.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._started_at = _api.time.monotonic()
        self._progress(0, "Подготовка…")
        # Отбивка в пять пустых строк: журнал общий на всё приложение, и без неё
        # логи нового пака сливались с прошлыми (просьба пользователя).
        self._log_gap()
        self.log(f"Собираю пак «{settings.title}»: {settings.total_questions} "
                 "вопросов.")

        task = _api._GenTask(settings, recovery=recovery)
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        self._active_settings = settings
        self._refresh_queue()
        from .saved_attempt import refresh as refresh_saved_attempt
        refresh_saved_attempt(self)
        self._pool.start(task)

    def stop(self):
        self._queue.clear()
        self._refresh_queue()
        if self._task is not None:
            self._task.stop()
            self._progress(0, "Останавливаюсь…")
            self.btn_stop.setEnabled(False)

    def _progress(self, pct: int, text: str) -> None:
        """Своей полосы у вкладки нет — пишем в общую, внизу окна. Она же и
        строка состояния вкладки: отдельной подписи над таблицей больше нет."""
        if self.main is None or not hasattr(self.main, "update_global_progress"):
            return
        try:
            self.main.update_global_progress(
                max(0, min(100, int(pct))), text, started_at=self._started_at,
                running=self._task is not None or text == "Подготовка…")
        except Exception:
            pass

    def _on_progress(self, done: int, total: int, msg: str):
        """Счётчик, чем генератор занят прямо сейчас и оставшееся время.

        Названия тайтлов на полосе по-прежнему нет — они мелькали слишком
        быстро, чтобы их прочитать, и для них есть журнал. А вот РОД вопроса
        («Сакуга», «Кадр», «Манга») там нужен: по нему сразу видно, на чём
        генерация встала (просьба пользователя)."""
        total = max(1, total)
        if done <= 0:
            self._progress(0, msg or f"0/{total}")
            return
        text = f"{done}/{total}"
        if msg:
            text += f" · {msg}"
        eta = self._eta(done, total)
        if eta:
            text += f" — осталось {eta}"
        self._progress(int(done * 100 / total), text)

    def _eta(self, done: int, total: int) -> str:
        """Оценка остатка по средней скорости с начала генерации. Первые
        несколько вопросов не в счёт: пока качается база и разгоняется пул
        загрузок, средняя скорость врёт в разы."""
        if not self._started_at or done < 3 or done >= total:
            return ""
        spent = _api.time.monotonic() - self._started_at
        if spent <= 0:
            return ""
        return _api.fmt_elapsed(spent / done * (total - done))

    def _finish_ui(self):
        self._task = None
        self._active_settings = None
        self.btn_start.setEnabled(True)
        from .saved_attempt import refresh as refresh_saved_attempt
        refresh_saved_attempt(self)
        self.btn_stop.setEnabled(False)
        self._refresh_queue()

    def _release_pack_number(self, number) -> None:
        """Возвращает номер, выданный в start(), — пака под ним не вышло.

        Отменённый и упавший прогон нумерацию не двигают (просьба
        пользователя): иначе после пары остановок следующий собранный пак
        получал «№ 7» вместо «№ 4». Возвращаем ТОЛЬКО свой, последний выданный
        номер: пока генерация шла, человек мог сменить его руками в настройках,
        и затирать чужое значение нельзя."""
        try:
            issued = int(number or 0)
        except (TypeError, ValueError):
            return
        if issued <= 0 or int(getattr(self, "_pack_number", 0) or 0) != issued:
            return
        self._pack_number = issued - 1
        saver = getattr(self.main, "_save_settings_soon", None)
        if saver is not None:
            try:
                saver()
            except Exception:      # noqa: BLE001 — номер важнее, чем запись
                pass

    def _on_failed(self, err: str):
        self._release_pack_number(getattr(self._active_settings, "pack_number", 0))
        self._finish_ui()
        self._progress(0, "Не получилось")
        self.log(f"Ошибка: {err}")
        _api.msgbox_critical(self, "Генерация не удалась", err)
        self._finish_queue()

    def _on_finished(self, result):
        settings = self._active_settings
        auto_add = getattr(settings, "auto_add_to_exclusions",
                           self.chk_auto_add_exclusions.isChecked())
        is_test = (bool(getattr(settings, "ignore_test_packs", False))
                   and bool(result.path) and len(result.songs) < TEST_LIMIT)
        if is_test:
            self._release_pack_number(getattr(result, "pack_number", 0))
            self._test_pack_number = max(self._test_pack_number,
                                         int(getattr(settings, "test_pack_number", 0)))
            saver = getattr(self.main, "_save_settings_soon", None)
            if saver is not None:
                saver()
        self._finish_ui()
        self._fill_table(result.songs)
        spent = _api.fmt_elapsed(getattr(result, "elapsed", 0.0))
        if result.cancelled:
            self._release_pack_number(getattr(result, "pack_number", 0))
            if result.path:
                _remember_if_complete(self, result, auto_add and not is_test)
                self._last_pack = result.path
                self.btn_open.setEnabled(True)
                if self.main is not None and hasattr(self.main, "set_global_result"):
                    self.main.set_global_result(result.path)
                self._progress(100, f"Частичный пак: {len(result.songs)} вопросов")
                self.log(f"Генерация остановлена; сохранено {len(result.songs)} "
                         f"вопросов из {result.requested}: {result.path}")
            else:
                self._progress(0, "Остановлено")
                self.log("Генерация остановлена до первого готового вопроса.")
            self._finish_queue()
            return
        _remember_if_complete(self, result, auto_add and not is_test)
        self._last_pack = result.path
        self.btn_open.setEnabled(bool(result.path))
        if self.main is not None and hasattr(self.main, "set_global_result"):
            self.main.set_global_result(result.path)
        # Итог пишем прямо на полосу вместо голого «Готово»: своей строки
        # состояния у вкладки больше нет (просьба пользователя).
        self._progress(100, f"Готово за {spent} · "
                            f"{_api.os.path.basename(result.path)}")
        self.log(f"Пак собран за {spent}: {result.path}")
        if len(result.songs) < result.requested:
            self.log(f"Вопросов получилось {len(result.songs)} из "
                     f"{result.requested}; пак сохранён с фактическим составом.")
        self._finish_queue()

    def _fill_table(self, songs: list):
        settings = self.collect()
        per_round = max(1, settings.themes)
        # Пока идёт заполнение, сортировку выключаем: иначе строки едут
        # прямо под руками и ячейки попадают не в свои ряды.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        # Раскладку (темы, порядок и цены) считает сам генератор — таблица и пак
        # обязаны совпадать до вопроса.
        row = 0
        for theme_no, theme in enumerate(_api.arrange_questions(songs, settings)):
            round_no = theme_no // per_round
            for cand in theme:
                self.table.insertRow(row)
                title_text = cand.title_ru
                if cand.is_character:
                    # Имя персонажа — часть ОТВЕТА, а не название песни: в
                    # колонке «Песня» ему было не место.
                    song_text, difficulty = "—", ""
                    if cand.char_name:
                        title_text = f"{cand.title_ru} — 『{cand.char_name}』"
                elif cand.is_silent:
                    # Кадр, пиксели, анаграмма, сюжет — песни в вопросе нет,
                    # даже если карточка песни осталась от отбора.
                    song_text, difficulty = "—", ""
                else:
                    song_text = (f"{cand.song.get('songArtist') or ''} — "
                                 f"{cand.song.get('songName') or ''}")
                    difficulty = f"{cand.difficulty:.0f}"
                kind_text = _api.KIND_TITLES.get(cand.kind, cand.kind)
                if cand.is_pixel and cand.frame_effect:
                    from frame_reveal import EFFECT_LABELS
                    kind_text = EFFECT_LABELS.get(cand.frame_effect, kind_text)
                if cand.kind == _api.VIDEO_KIND and not cand.has_video:
                    # Ролика для этой песни не нашлось — вопрос вышел обычным.
                    kind_text = _api.KIND_TITLES.get(cand.base_kind, kind_text)
                if cand.entrance_effect:
                    from image_entrance import EFFECT_LABELS as ENTRANCE_LABELS
                    kind_text += " · " + ENTRANCE_LABELS[cand.entrance_effect]
                cells = [
                    _api._NumItem(str(row + 1), row + 1),
                    _api._NumItem(str(round_no + 1), round_no + 1),
                    _api._NumItem(str(theme_no % per_round + 1), theme_no % per_round + 1),
                    _api._NumItem(str(cand.price), cand.price),
                    _api.QTableWidgetItem(title_text),
                    _api.QTableWidgetItem(song_text),
                    _api.QTableWidgetItem(kind_text),
                    _api._NumItem(difficulty, cand.difficulty),
                    _api._NumItem(f"{cand.index:,.0f}".replace(",", " "), cand.index),
                    _api._NumItem(str(cand.level), cand.level),
                ]
                # Из чего сложился «Индекс» — подсказкой прямо на ячейке
                # (просьба пользователя). Текст кладём в саму ячейку: окно
                # состава пака копирует ячейки через clone(), и подсказка
                # уезжает туда вместе с числом.
                from .index_tooltip import (PRICE_ROLE, TIP_ROLE, build_price_text,
                                            build_text)
                cells[8].setData(TIP_ROLE, build_text(cand))
                # То же самое для «Цены»: из каких надбавок и множителей она
                # сложилась (просьба пользователя).
                cells[3].setData(PRICE_ROLE, build_price_text(cand))
                for col, item in enumerate(cells):
                    if col in self.TABLE_NUM_COLS:
                        item.setTextAlignment(_api.Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, col, item)
                row += 1
        # Заново показываем пак в его собственном порядке: сортировка «по №»
        # и есть порядок вопросов в файле.
        self.table.horizontalHeader().setSortIndicator(0, _api.Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        # setSortingEnabled(True) сам включает родную стрелку — гасим её снова
        # (иначе колонки опять раздуются на 28 px каждая).
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self._update_table_hint()
        # Таблица по умолчанию спрятана, поэтому кнопка сама говорит, что в ней
        # уже есть что смотреть (просьба пользователя: «после генерации кнопкой
        # посмотреть, что там выбрано»).
        button = getattr(self, "btn_table", None)
        if button is not None:
            button.setEnabled(self.table.rowCount() > 0)
            button.setText(f"Показать таблицу ({self.table.rowCount()})")
        dialog = getattr(self, "_table_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.refresh(self.table, self.TABLE_HEADERS)

    def _open_result(self):
        if not self._last_pack:
            return
        try:
            from utils import reveal_in_explorer
            reveal_in_explorer(self._last_pack)
        except Exception as e:  # noqa: BLE001
            _api.msgbox_critical(self, "Не открылось", str(e))

    # ── завершение работы вкладки ─────────────────────────────────────────
    @staticmethod
    def _detach(task):
        """Просит задачу остановиться и отвязывает её сигналы от вкладки.

        Дождаться QRunnable мы не можем: генерация пака идёт минутами, а
        cleanup() зовут при закрытии окна. Зато можно сделать так, чтобы поток
        доработал молча — иначе сигнал прилетает в виджет, которого уже нет."""
        if task is None:
            return
        try:
            task.stop()
        except Exception:
            pass
        for name in ("log", "progress", "finished", "failed"):
            sig = getattr(task.signals, name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except TypeError:
                pass               # к этому сигналу никто и не подключался

    def cleanup(self):
        self._closing = True
        timer = getattr(self, "_template_notice_timer", None)
        if timer is not None:
            timer.stop()
            self.template_notice.hide()
        preview = getattr(self, "entrance_preview", None)
        if preview is not None:
            preview.timer.stop()
        if getattr(self, "_gemini_quota_timer", None) is not None:
            self._gemini_quota_timer.stop()
        if getattr(self, "_ai_quota_timer", None) is not None:
            self._ai_quota_timer.stop()
        if getattr(self, "_gemini_models_timer", None) is not None:
            self._gemini_models_timer.stop()
        # Отложенная загрузка жанров: таймер мог ещё не сработать.
        if self._genres_timer is not None:
            self._genres_timer.stop()
        self._detach(self._task)
        self._task = None
        self._detach(self._db_task)
        self._db_task = None
        self._detach(self._genres_task)
        self._genres_task = None
        for name in ("_table_dialog", "_cache_dialog", "_db_table_dialog",
                     "_franchise_list_dialog",
                     "_exact_list_dialog"):
            dialog = getattr(self, name, None)
            if dialog is not None:
                try:
                    dialog.close()
                except Exception:
                    pass


AnimePackTab.__module__ = _api.__name__
_api.AnimePackTab = AnimePackTab
