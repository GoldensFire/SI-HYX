# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _group_songs. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


# ── группа «Состав пака» ──────────────────────────────────────────────
def _group_songs(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Состав пака")
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    # Ползунок вместо прежних галочек «только кадры» / «только персонажи» /
    # «ещё и кадры по N на песню»: одной полосой видно и что в паке есть, и
    # в какой пропорции.
    self.mix = _api._MixSlider()
    self.mix.setToolTip(
        "Доли включённых частей в процентах. Их сумма — 100%. "
        "Изменение одной доли распределяет остаток между остальными. "
        "Снимите галочку, чтобы убрать часть вместе с её ползунком.")
    self.mix.changed.connect(self._on_mix_changed)
    # Что и в каком количестве получится — первой строкой группы, чтобы это
    # было видно сразу, не листая до конца (просьба пользователя).
    self.lbl_left = self._hint("")
    self.lbl_left.setWordWrap(True)
    # Соотношение типов песен — такой же полосой, как состав пака: раньше
    # это были три счётчика «сколько штук», и их приходилось складывать до
    # числа вопросов вручную (просьба пользователя).
    self.kind_bar = _api._ShareBar()
    self.kind_bar.setToolTip(
        "В какой пропорции делить песенные вопросы между опенингами, "
        "эндингами и OST. Снятая галочка убирает тип из полосы совсем.")
    self.kind_bar.changed.connect(lambda: self._recount())
    self.kind_bar.set_parts([("opening", "Опенинги"), ("ending", "Эндинги"),
                             ("insert", "OST")])
    # Дефолт тот же, что был у счётчиков: 54 опенинга, 20 эндингов, 16 OST.
    self.kind_bar.set_values({"opening": 54, "ending": 20, "insert": 16})
    # Галочка у каждого типа: снятая — типа в паке нет вовсе.
    self.chk_op = _api.QCheckBox("Опенинги")
    self.chk_ed = _api.QCheckBox("Эндинги")
    self.chk_in = _api.QCheckBox("OST")
    for chk in (self.chk_op, self.chk_ed, self.chk_in):
        chk.setChecked(True)
        chk.setToolTip("Брать песни этого типа. Снимите — в паке их не "
                       "будет совсем.")
        chk.toggled.connect(self._on_song_kinds_toggled)
    from .difficulty_range import DifficultyRange
    self.song_diff_range = DifficultyRange(0, 100)
    self.ost_diff_range = DifficultyRange(0, 100)
    self.sp_diff_min = self.song_diff_range.low_control
    self.sp_diff_max = self.song_diff_range.high_control
    self.sp_ost_diff_min = self.ost_diff_range.low_control
    self.sp_ost_diff_max = self.ost_diff_range.high_control
    diff_tip = ("Доля игроков сайта Anime Music Quiz, угадавших песню: "
                "0 — почти никто, 100 — почти все. Это songDifficulty из "
                "базы AnisongDB, а не сходство кавера с оригиналом.\n"
                "Рамки ДВЕ и они независимы: опенинги с эндингами слушаются "
                "верхней, OST — нижней. Сузили верхнюю и увидели в паке песню "
                "со сложностью из старого диапазона — это OST, у него рамка "
                "своя (просьба пользователя).")
    for slider in (self.sp_diff_min, self.sp_diff_max,
                   self.sp_ost_diff_min, self.sp_ost_diff_max):
        slider.setToolTip(diff_tip)
    self.song_diff_range.setToolTip(diff_tip)
    self.ost_diff_range.setToolTip(diff_tip)

    # Кадр всегда случайный и всегда собирается из всех источников сразу
    # (скриншоты Shikimori + превью серий AniList и Kitsu) — отдельных
    # настроек для этого больше нет, выключать их было незачем.
    self.cb_char_roles = _api.QComboBox()
    for role in _api.CHAR_ROLES:
        self.cb_char_roles.addItem(_api.CHAR_ROLE_LABELS[role], role)
    self.cb_char_roles.setCurrentIndex(self.cb_char_roles.findData("both"))
    self.cb_char_roles.setToolTip(
        "Кого спрашивать в вопросах-персонажах: главных героев (их узнают "
        "почти все), второстепенных (сильно сложнее) или и тех, и других.\n"
        "Портрет берётся с Shikimori, ответ пишется как «Название аниме "
        "(2020) — 『Имя персонажа』» и засчитывает ВСЕ имена персонажа, в "
        "том числе «Прочие» с его страницы.\n"
        "Цена — как за сам тайтл, плюс 4 очка за главного героя или плюс 6 "
        "за второстепенного.")

    # ── Вопрос роликом (AnimeThemes) ─────────────────────────────────
    # Галочка живёт в составе пака: она включает в ползунке долю роликов,
    # а не превращает в видео все песни разом.
    self.chk_video = _api.QCheckBox("Опенинги с видеорядом")
    self.chk_video.setToolTip(
        "Добавляет в ползунок состава долю вопросов-РОЛИКОВ: вместо "
        "отрезка песни играет ВИДЕО опенинга или эндинга с "
        "animethemes.moe. Ролики там без кредитов — то есть без названия "
        "прямо в кадре, что для угадайки и нужно.\n"
        "Ключей и регистрации не требуется. Если ролика для этой песни нет "
        "(OST там не лежат вовсе), вопрос всё равно состоится — просто "
        "обычным отрезком звука.\n"
        "Ответ у ролика точно такой же, как у песни: название с тегом, "
        "год, песня, исполнитель и постер.\n"
        "Цена — как за обычный кадр этого тайтла, без надбавок за музыку.\n"
        "Ролик перекодируется в 720p тем же libsvtav1, что и во вкладке "
        "«Обработка», звук — в opus, как все дорожки пака.")
    self.chk_video.toggled.connect(self._on_video_toggled)
    self.sp_video_cut = _api.QSpinBox(); self.sp_video_cut.setRange(3, 90)
    self.sp_video_cut.setValue(_api.VIDEO_CUT); self.sp_video_cut.setSuffix(" с")
    self.sp_video_cut.setMinimumWidth(64)
    self.sp_video_cut.setToolTip("Длина ролика в вопросе.")
    self.sp_video_crf = _api.QSpinBox(); self.sp_video_crf.setRange(0, 63)
    self.sp_video_crf.setValue(_api.VIDEO_CRF); self.sp_video_crf.setMinimumWidth(44)
    self.sp_video_crf.setToolTip(
        "CRF libsvtav1: меньше — качественнее и тяжелее. 45 — заметно "
        "сжато, зато пак не раздувается.")
    self.sp_video_preset = _api.QSpinBox(); self.sp_video_preset.setRange(0, 13)
    self.sp_video_preset.setValue(_api.VIDEO_PRESET)
    self.sp_video_preset.setMinimumWidth(44)
    self.sp_video_preset.setToolTip(
        "Пресет libsvtav1: 13 — самый быстрый, 0 — самый медленный и "
        "качественный.")
    self.box_video_opts = _api.SettingsBox()
    vg = _api.QGridLayout(self.box_video_opts)
    vg.setContentsMargins(16, 0, 0, 0)
    vg.setHorizontalSpacing(8); vg.setVerticalSpacing(6)
    vg.addWidget(self._lab("Длина ролика"), 0, 0)
    vg.addWidget(self.sp_video_cut, 0, 1)
    vg.addWidget(self._lab("CRF"), 1, 0); vg.addWidget(self.sp_video_crf, 1, 1)
    vg.addWidget(self._lab("Пресет"), 2, 0)
    vg.addWidget(self.sp_video_preset, 2, 1)
    vg.setColumnStretch(1, 1)
    self.box_video_opts.setVisible(False)

    # ── Манга/манхва/ранобэ ──────────────────────────────────────────
    # Галочка, как у роликов: без неё доли манги на ползунке нет вовсе
    # (просьба пользователя).
    self.chk_manga = _api.QCheckBox("Манга")
    self.chk_manga.setToolTip(
        "Добавляет в ползунок состава долю вопросов по МАНГЕ (а также "
        "манхве, манхуа и ранобэ). Вопросом служит СТРАНИЦА оригинала с "
        "MangaDex — разворот из середины случайной главы.\n"
        "Тайтлы берутся из списков, переключённых на «Манга/манхва/маньхуа», либо "
        "из каталога Shikimori.\n"
        "Снятая галочка убирает мангу с ползунка целиком.")
    self.chk_manga.toggled.connect(self._on_manga_toggled)
    self.cb_manga_lang = _api.QComboBox()
    for key in _api.MANGA_LANGS:
        self.cb_manga_lang.addItem(_api.MANGA_LANG_LABELS[key], key)
    self.cb_manga_lang.setToolTip(
        "Из глав на каком языке брать страницу.\n"
        "«Любой»: сначала русский (ReManga и MangaLib в приоритете), "
        "затем английский и украинский.\n"
        "«Японский» — страницы оригинала, без переводных надписей.")
    self.chk_manga_erotica = _api.QCheckBox("Пускать главы 18+ (erotica)")
    self.chk_manga_erotica.setToolTip(
        "На MangaDex меткой erotica помечена и вполне обычная сэйнэн-"
        "классика: «Берсерк», например, без этой галочки не находится вовсе. "
        "Порнография (pornographic) не берётся никогда.")
    from si_hyx_parts.animepack_tab.frame_effect_controls import build_controls
    build_controls(self)

    from .frame_gemini_controls import build_controls as build_frame_checks
    build_frame_checks(self)

    # ── Вопрос-анаграмма ──────────────────────────────────────────────
    self.chk_anagram = _api.QCheckBox("Анаграммы")
    self.chk_anagram.setToolTip(
        "Добавляет в ползунок состава долю вопросов-АНАГРАММ: буквы "
        "названия тайтла перемешаны, ответ — само название.\n"
        "Каждое слово перемешивается САМО В СЕБЕ: буквы не переезжают из "
        "слова в слово, а форма названия сохраняется — сколько слов и "
        "какой длины было, столько и останется. Написано прописными.\n"
        "Продолжения с приписками («…: Порядковый ранг», «… 2») под "
        "анаграмму не берутся: загадывается сам тайтл.\n"
        "Ни сети, ни медиа такому вопросу не нужно: название уже есть в "
        "карточке Shikimori, поэтому анаграммы — самый быстрый и самый "
        "лёгкий по весу род вопросов.")
    self.chk_anagram.toggled.connect(self._on_anagram_toggled)
    self.cb_anagram_lang = _api.QComboBox()
    for lang in _api.ANAGRAM_LANGS:
        self.cb_anagram_lang.addItem(_api.ANAGRAM_LANG_LABELS[lang], lang)
    self.cb_anagram_lang.setToolTip(
        "Какое название перемешивать. Русское — с Shikimori, английское — "
        "поле english, ромадзи — латинская запись японского названия.\n"
        "Язык строгий: на другой анаграмма НЕ подменяется. Нет у тайтла "
        "названия на выбранном языке (или оно записано чужой "
        "письменностью — в поле russian у Shikimori попадается латиница) — "
        "вопрос достаётся следующему тайтлу.\n"
        "Правильными в ответе считаются ВСЕ написания тайтла.")
    # Потолок длины названия: у ранобэ они бывают в целое предложение, и
    # перемешанные буквы такой длины не разбирает никто (просьба
    # пользователя). 0 — потолка нет вовсе.
    self.sp_anagram_max = _api.QSpinBox()
    self.sp_anagram_max.setRange(0, 200)
    self.sp_anagram_max.setValue(_api.ANAGRAM_MAX_CHARS)
    self.sp_anagram_max.setMinimumWidth(64)
    self.sp_anagram_max.setSpecialValueText("без предела")
    self.sp_anagram_max.setSuffix(" симв.")
    self.sp_anagram_max.setToolTip(
        "Названия длиннее этого под анаграмму не берутся: у ранобэ и "
        "новинок они бывают в целое предложение, а перемешанные буквы такой "
        "длины не разбирает никто.\n"
        "Считаются все символы названия — вместе с пробелами и знаками, "
        "ровно как их видно на экране.\n"
        "Не уложилось название на выбранном языке — вопрос достанется "
        "следующему тайтлу: на другой язык анаграмма не подменяется.\n"
        "«без предела» (0) снимает ограничение совсем.")
    # Время показа всех текстовых вопросов — символов в секунду. Имя поля
    # оставлено прежним ради совместимости сохранённых настроек.
    self.sp_anagram_cps = _api.QDoubleSpinBox()
    self.sp_anagram_cps.setRange(0.0, _api.ANAGRAM_CPS_MAX)
    self.sp_anagram_cps.setDecimals(1)
    self.sp_anagram_cps.setSingleStep(1.0)
    self.sp_anagram_cps.setValue(_api.ANAGRAM_CHARS_PER_SEC)
    self.sp_anagram_cps.setMinimumWidth(96)
    self.sp_anagram_cps.setSpecialValueText("без таймера")
    self.sp_anagram_cps.setSuffix(" симв./сек")
    self.sp_anagram_cps.setToolTip(
        "Сколько времени любой текстовый вопрос висит на экране: его длина "
        "делится на это число. Настройка действует на анаграммы, синонимы, "
        "антонимы, переводы, определения, шифры и сюжетные вопросы.\n"
        "При 10 симв./сек текст из 30 символов показывается 3 секунды.\n"
        "Без этой настройки время берёт сам SIGame — из «скорости чтения» в "
        "настройках ИГРОКА, а она рассчитана на чтение вопроса вслух, а не "
        "на разгадывание, и текст улетает вдвое быстрее.\n"
        f"Меньше {_api.ANAGRAM_MIN_SECONDS} с не бывает: короткий текст "
        "иначе мелькнул бы, и прочитать его не успел бы никто.\n"
        "«без таймера» (0) — текст остаётся на экране, пока ведущий не "
        "откроет ответ.")
    self.lab_anagram_cps = self._lab("Показ текста")
    self.box_text_cps = _api.SettingsBox()
    text_timing = _api.QGridLayout(self.box_text_cps)
    text_timing.setContentsMargins(16, 0, 0, 0)
    text_timing.setHorizontalSpacing(8)
    text_timing.addWidget(self.lab_anagram_cps, 0, 0)
    text_timing.addWidget(self.sp_anagram_cps, 0, 1)
    text_timing.setColumnStretch(1, 1)
    self.box_text_cps.setVisible(False)
    self.box_anagram = _api.SettingsBox()
    ang = _api.QGridLayout(self.box_anagram)
    ang.setContentsMargins(16, 0, 0, 0)
    ang.setHorizontalSpacing(8); ang.setVerticalSpacing(6)
    ang.addWidget(self._lab("Язык названия"), 0, 0)
    ang.addWidget(self.cb_anagram_lang, 0, 1)
    ang.addWidget(self._lab("Не длиннее"), 0, 2)
    ang.addWidget(self.sp_anagram_max, 0, 3)
    ang.setColumnStretch(1, 1)
    self.box_anagram.setVisible(False)

    # ── Вопрос по сюжету (Fandom + Gemini) ────────────────────────────
    self.chk_plot = _api.QCheckBox("Сюжетные вопросы")
    self.chk_plot.setToolTip(
        "Добавляет в ползунок состава долю вопросов ПО СЮЖЕТУ: программа "
        "находит вики тайтла на fandom.com, берёт со страницы случайной "
        "серии раздел с пересказом и просит Gemini сделать из него вопрос.\n"
        "Fandom работает без ключей, а вот для Gemini нужен ВАШ ключ — "
        "бесплатного тарифа хватает, но запросов в минуту там немного, и "
        "пак с большой долей сюжета собирается заметно дольше обычного.\n"
        "Вики есть не у всякого тайтла: если пересказа не нашлось, вопрос "
        "просто достанется следующему тайтлу.")
    self.chk_plot.toggled.connect(self._on_plot_toggled)
    self.cb_plot_mode = _api.QComboBox()
    for mode in _api.PLOT_MODES:
        self.cb_plot_mode.addItem(_api.PLOT_MODE_LABELS[mode], mode)
    self.cb_plot_mode.setToolTip(
        "Что именно спрашивать.\n"
        "«Ответ — название аниме»: ведущий читает эпизод сюжета, игроки "
        "называют тайтл. Название и имена героев из вопроса вычищаются, "
        "иначе он решается с первого слова. Ответ и цена считаются как у "
        "любого другого вопроса пака — на слово модели тут ничего не "
        "принимается.\n"
        "«Ответ — деталь сюжета»: вопрос про сам сюжет («что герой сделал, "
        "когда…»), тайтл в вопросе назван прямо, а короткий ответ "
        "придумывает модель по пересказу. Проверяйте такие вопросы глазами "
        "перед игрой.")
    self.btn_gemini_key = self._api_key_button("gemini", "Ключ Gemini")
    self.cb_gemini_model = _api.QComboBox()
    for model in _api.GEMINI_MODELS:
        self.cb_gemini_model.addItem(model, model)
    self.cb_gemini_model.setCurrentText(_api.GEMINI_DEFAULT_MODEL)
    self.cb_gemini_model.setToolTip(
        "Flash-Lite — рабочая лошадка с самой высокой бесплатной квотой. "
        "Flash думает лучше, но запросов в сутки у него меньше. Новые "
        "стабильные Flash-модели добавляются из Gemini API автоматически.")
    self.cb_gemini_think = _api.QComboBox()
    for level in _api.GEMINI_THINKING_LEVELS:
        self.cb_gemini_think.addItem(_api.GEMINI_THINKING_LABELS[level], level)
    self.cb_gemini_think.setCurrentIndex(
        self.cb_gemini_think.findData(_api.GEMINI_THINKING_LEVEL))
    self.cb_gemini_think.setToolTip(
        "Сколько модель думает перед ответом. Уровень общий для любой "
        "выбранной модели Gemini.\n"
        "«Минимальный» — самый дешёвый и быстрый: для раскладки готовых "
        "ответов по франшизам думать не над чем.\n"
        "Выше уровень — аккуратнее загадки по названию и пересказы сюжета, "
        "но каждый запрос идёт дольше, а суточная квота бесплатного тарифа "
        "кончается быстрее.\n"
        "Уровень, которого модель не знает, она отвергает — её ответ придёт "
        "в журнал как есть.")
    from si_hyx_parts.animepack_tab.gemini_model_controls import setup
    setup(self)
    self.box_plot = _api.SettingsBox()
    plg = _api.QGridLayout(self.box_plot)
    plg.setContentsMargins(16, 0, 0, 0)
    plg.setHorizontalSpacing(8); plg.setVerticalSpacing(6)
    plg.addWidget(self.cb_plot_mode, 0, 0, 1, 2)
    # Своя рамка сложности у сюжета живёт в группе «Аниме», рядом с общей и
    # рамками остальных родов вопросов (просьба пользователя, см. level_panel).
    # Подписей «Ключ», «Модель», «Рассуждение» здесь больше нет (просьба
    # пользователя): кнопка ключа и так подписана «Ключ Gemini», в списке
    # моделей стоит имя модели, а в списке уровней — сам уровень. Виджеты
    # занимают обе колонки.
    row = 1
    plg.addWidget(self.btn_gemini_key, row, 0, 1, 2)
    plg.addWidget(self.cb_gemini_model, row + 1, 0, 1, 2)
    plg.addWidget(self.cb_gemini_think, row + 2, 0, 1, 2)
    # Дальше настройки Gemini дополняет composition_controls.rebuild.
    self._plot_grid_rows = row + 3
    plg.setColumnStretch(1, 1)
    self.box_plot.setVisible(False)
    from si_hyx_parts.animepack_tab.gemini_title_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.dialogue_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.description_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.ai_art_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.pixiv_art_controls import build_controls
    build_controls(self)

    self.chk_manga_kinds = {}
    # Книжные доли живут здесь, а рамка сложности — в группе «Аниме». Сама
    # группа строится позже, поэтому виджеты заводим уже сейчас.
    from si_hyx_parts.animepack_tab import level_panel
    from si_hyx_parts.animepack_tab.level_controls import place_manga
    level_panel.build(self)
    self.box_manga = _api.SettingsBox()
    mg = _api.QGridLayout(self.box_manga)
    mg.setContentsMargins(16, 0, 0, 0)
    mg.setHorizontalSpacing(8); mg.setVerticalSpacing(4)
    from .manga_source_controls import build_controls as build_sources
    build_sources(self, mg, 0)
    mg.addWidget(self._lab("Язык глав"), 1, 0)
    mg.addWidget(self.cb_manga_lang, 1, 1, 1, 3)
    mg.addWidget(self.chk_manga_erotica, 2, 0, 1, 4)
    from si_hyx_parts.animepack_tab.manga_gemini_controls import build_controls
    build_controls(self, mg, 3)
    extras = [k for k in _api.MANGA_KINDS if k in ("one_shot", "doujin")]
    for i, kind in enumerate(extras):
        chk = _api.QCheckBox(_api.MANGA_KIND_LABELS[kind])
        chk.setChecked(False)
        self.chk_manga_kinds[kind] = chk
        mg.addWidget(chk, 4 + i // 2, (i % 2) * 2, 1, 2)
    place_manga(self, mg, 4 + (len(extras) + 1) // 2)
    mg.setColumnStretch(1, 1)
    self.box_manga.setVisible(False)

    from si_hyx_parts.animepack_tab.sakuga_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.episode_controls import build_controls
    build_controls(self)
    from si_hyx_parts.animepack_tab.studio_controls import build_controls
    build_controls(self)

    r = 0
    g.addWidget(self.lbl_left, r, 0, 1, 4)
    r += 1
    g.addWidget(self.mix, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_video, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_video_opts, r, 0, 1, 4)
    r += 1
    g.addWidget(self._lab("Персонажи"), r, 0)
    g.addWidget(self.cb_char_roles, r, 1, 1, 3)
    r += 1
    g.addWidget(self.chk_manga, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_manga, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_pixel, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_pixel, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_anagram, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_anagram, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_text_cps, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_plot, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_plot, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_ai_art, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_ai_art, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_pixiv_art, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_pixiv_art, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_sakuga, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_sakuga, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_studio, r, 0, 1, 4)
    r += 1
    g.addWidget(self.box_studio, r, 0, 1, 4)
    r += 1
    self.box_song_opts = _api.SettingsBox()
    sg = _api.QGridLayout(self.box_song_opts)
    sg.setContentsMargins(0, 0, 0, 0)
    sg.setHorizontalSpacing(8); sg.setVerticalSpacing(8)
    g.addWidget(self.box_song_opts, r, 0, 1, 4)
    g, r = sg, 0                      # дальше всё кладём в подпанель песен
    g.addWidget(self.chk_op, r, 0)
    g.addWidget(self.chk_ed, r, 1)
    g.addWidget(self.chk_in, r, 2, 1, 2)
    r += 1
    g.addWidget(self.kind_bar, r, 0, 1, 4)
    r += 1
    self.song_diff_range.changed.connect(self._refresh_diff_bands)
    self.ost_diff_range.changed.connect(self._refresh_diff_bands)
    self.chk_rebroadcast = _api.QCheckBox("Повторные показы")
    self.chk_rebroadcast.setChecked(True)
    self.chk_rebroadcast.setToolTip("Песни из повторных трансляций (rebroadcast).")
    self.chk_dub = _api.QCheckBox("Дубляж (dub)")
    g.addWidget(self.chk_rebroadcast, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_dub, r, 0, 1, 4)
    r += 1
    g.addWidget(self._lab("Категории"), r, 0, 1, 4)
    r += 1
    self.chk_categories = {}
    for i, cat in enumerate(_api.SONG_CATEGORIES):
        chk = _api.QCheckBox(_api.CATEGORY_LABELS[cat])
        chk.setChecked(True)
        self.chk_categories[cat] = chk
        g.addWidget(chk, r + i // 2, (i % 2) * 2, 1, 2)
    r += (len(_api.SONG_CATEGORIES) + 1) // 2
    # Всё про музыку — длина отрезка, коллаж, подсказка, сжатие дорожки,
    # Chiptune и каверы — стоит ЗДЕСЬ же, а не в «Прочем» (просьба
    # пользователя): это настройки песенных вопросов, и листать за ними через
    # весь состав пака было незачем.
    # Со своим заголовком, как «Категории»: выше решается, КАКИЕ песни берём,
    # ниже — как они звучат. Без подписи отрезок и Chiptune читались продолжением
    # списка категорий.
    g.addWidget(self._lab("Звук вопроса"), r, 0, 1, 4)
    r += 1
    from .music_panel import build_controls as build_music
    g.addWidget(build_music(self), r, 0, 1, 4)
    for col in (1, 3):
        g.setColumnStretch(col, 1)
    from .composition_controls import rebuild
    rebuild(self, grp)
    return grp
