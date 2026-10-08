# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


# ─────────────────────────────────────────────────────────────────────────────
# Страница профиля (сама вкладка — AnimePackUpgradeTab ниже)
# ─────────────────────────────────────────────────────────────────────────────
class _UpgradePage(_api.QWidget):
    """Доводка готового .siq: спецвопросы → обычные, ответы → с вариантами
    названий тайтла с Shikimori."""

    def __init__(self, main_window=None, settings: _api.Optional[dict] = None,
                 profile: str = "anime"):
        super().__init__()
        self.main = main_window
        self.profile = _api.normalize_profile(profile) if _api._HAS_CORE else "anime"
        self._pool = _api.QThreadPool.globalInstance()
        self._task = None
        self._siq = ""                     # какой пак апгрейдим
        self._out_dir = ""
        self._last_pack = ""
        self._started_at = 0.0
        self._initial = dict(settings or {})

        if not _api._HAS_CORE:
            self._build_unavailable()
            return
        self._build_ui()
        self.apply_settings(self._initial or _api.UpgradeSettings(
            profile=self.profile).to_dict())
        # Пак можно просто бросить на вкладку мышью — как файлы на «Обработку».
        self.setAcceptDrops(True)

    # ── чем наполнен пак ──────────────────────────────────────────────────
    @property
    def source_name(self) -> str:
        """Как зовут базу названий."""
        return "Shikimori"

    @property
    def what(self) -> str:
        """Чем наполнен пак — словом, каким это называть в подписях."""
        return "аниме"

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_unavailable(self):
        lay = _api.QVBoxLayout(self)
        lbl = _api.QLabel("Не удалось загрузить вкладку «Апгрейд пака».\n\n"
                     f"{_api._IMPORT_ERROR}")
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    # Подписи колонок таблицы изменений.
    TABLE_HEADERS = ("№", "Раунд", "Тема", "Цена", "Функция", "Было", "Стало")
    TABLE_NUM_COLS = (0, 3)

    def _build_ui(self):
        root = _api.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = _api.QHBoxLayout(); body.setSpacing(12)
        root.addLayout(body, 1)

        # ── Слева: что именно поменялось ──────────────────────────────────
        left = _api.QVBoxLayout(); left.setSpacing(6)
        self.table = _api.QTableWidget(0, len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.TABLE_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(_api.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            _api.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        # Колонку двигаем горизонтальной полосой, а не режем: «Стало» стояло
        # Stretch и забирало ровно остаток ширины, из-за чего длинный текст
        # обрывался многоточием, а полосы прокрутки не появлялось вовсе —
        # прочитать правку было нечем. Теперь ширина колонок — по содержимому
        # (как в «Генерации аниме-пака»), а таблица прокручивается вбок.
        self.table.setHorizontalScrollMode(
            _api.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(
            _api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(_api.QHeaderView.ResizeMode.ResizeToContents)
        # «Раунд» — руками: в его колонке начинается имя файла, растянутое на
        # три клетки, а объединённые клетки Qt меряет по-своему (см.
        # _fit_round_column).
        hh.setSectionResizeMode(1, _api.QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(24)
        hh.setDefaultAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        # До запуска на месте таблицы стоит карточка выбранного пака: имя, автор
        # и темы. Таблица правок появляется там же, когда апгрейд закончится.
        self.left_stack = _api.QStackedWidget()
        self.left_stack.addWidget(self._build_pack_card())
        self.left_stack.addWidget(self.table)
        left.addWidget(self.left_stack, 1)
        body.addLayout(left, 1)

        self._build_settings_panel(body)
        self._apply_styles()
        self._fit_settings_width()
        self._refresh_siq_label()
        self._refresh_out_dir_label()

    # ── карточка выбранного пака ──────────────────────────────────────────
    def _build_pack_card(self) -> _api.QWidget:
        """Что за пак сейчас выбран: название крупно, автор и список тем.

        Стоит на месте таблицы правок до запуска — чтобы было видно, тот ли
        файл взяли, ещё до того, как что-то в нём поменяется."""
        box = _api.QScrollArea()
        box.setWidgetResizable(True)
        box.setObjectName("packcard")
        inner = _api.QWidget()
        v = _api.QVBoxLayout(inner)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)

        self.lbl_pack_name = _api.QLabel()
        self.lbl_pack_name.setWordWrap(True)
        self.lbl_pack_name.setTextInteractionFlags(
            _api.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_pack_name.setStyleSheet(
            f"color:{_api.C['text']}; font-size:24px; font-weight:800;")
        v.addWidget(self.lbl_pack_name)

        self.lbl_pack_author = _api.QLabel()
        self.lbl_pack_author.setWordWrap(True)
        self.lbl_pack_author.setStyleSheet(
            f"color:{_api.C['accent']}; font-size:14px;")
        v.addWidget(self.lbl_pack_author)

        self.lbl_pack_meta = _api.QLabel()
        self.lbl_pack_meta.setWordWrap(True)
        self.lbl_pack_meta.setStyleSheet(
            f"color:{_api.C['text3']}; font-size:12px;")
        v.addWidget(self.lbl_pack_meta)

        self.lbl_pack_themes = _api.QLabel()
        self.lbl_pack_themes.setWordWrap(True)
        self.lbl_pack_themes.setTextFormat(_api.Qt.TextFormat.RichText)
        self.lbl_pack_themes.setAlignment(_api.Qt.AlignmentFlag.AlignTop)
        self.lbl_pack_themes.setStyleSheet(
            f"color:{_api.C['text2']}; font-size:13px;")
        v.addWidget(self.lbl_pack_themes)
        v.addStretch(1)
        box.setWidget(inner)
        return box

    @staticmethod
    def _esc(text) -> str:
        return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _show_pack_card(self):
        """Заполняет карточку по выбранному файлу и показывает её."""
        self.left_stack.setCurrentIndex(0)
        if not self._siq:
            self.lbl_pack_name.setText("Пак не выбран")
            self.lbl_pack_author.setText("")
            self.lbl_pack_meta.setText(
                "Нажмите «Выбрать .siq…» справа или перетащите файл сюда мышью.")
            self.lbl_pack_themes.setText("")
            return
        base = _api.os.path.splitext(_api.os.path.basename(self._siq))[0]
        try:
            info = _api.read_pack_info(self._siq)
        except Exception as e:  # noqa: BLE001 — битый файл тоже надо показать
            self.lbl_pack_name.setText(base)
            self.lbl_pack_author.setText("")
            self.lbl_pack_meta.setText(f"Пак не читается: {e}")
            self.lbl_pack_themes.setText("")
            return
        self.lbl_pack_name.setText(info.name or base)
        self.lbl_pack_author.setText(f"Автор: {info.author}" if info.author
                                     else "Автор не указан")
        bits = [f"{info.questions} вопрос(ов)", f"{len(info.themes)} тем"]
        if info.specials:
            bits.append(f"спецвопросов: {info.specials}")
        if info.date:
            bits.append(info.date)
        if info.version:
            bits.append(f"формат {info.version}")
        self.lbl_pack_meta.setText(" · ".join(bits))
        self.lbl_pack_themes.setText(self._themes_html(info))

    def _themes_html(self, info) -> str:
        """Темы пака по раундам. Раунд подписывается, только если их несколько:
        у пака из одного раунда заголовок над списком лишний."""
        many = len(info.rounds) > 1
        out = []
        for rname, names in info.rounds:
            if many:
                out.append(f"<p style='margin:10px 0 2px 0; color:{_api.C['text3']};"
                           f" font-size:11px;'>{self._esc(rname).upper()}</p>")
            for name in names:
                out.append(f"<p style='margin:1px 0;'>• {self._esc(name)}</p>")
        return "".join(out) or "<p>Тем в паке нет.</p>"

    def _lab(self, text):
        l = _api.QLabel(text)
        l.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        l.setWordWrap(True)
        return l

    def _hint(self, text):
        l = _api.QLabel(text)
        l.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
        l.setWordWrap(True)
        return l

    def _build_settings_panel(self, body):
        # Правая колонка = прокручиваемые настройки + НЕподвижная полоса кнопок
        # под ними (как в «Генерации аниме-пака»): прокрутка настроек не должна
        # уносить кнопку запуска.
        self.right_col = _api.QWidget()
        col = _api.QVBoxLayout(self.right_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.scroll_settings = scroll = _api.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel = _api.QWidget()
        pv = _api.QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        pv.addWidget(self._group_pack())
        pv.addWidget(self._group_specials())
        pv.addWidget(self._group_titles())
        pv.addWidget(self._group_repeats())
        pv.addWidget(self._group_merge())
        pv.addWidget(self._group_empty())
        pv.addWidget(self._group_images())
        pv.addWidget(self._group_audio())
        pv.addWidget(self._group_video())
        pv.addWidget(self._group_unused())

        self.btn_reset = _api.QPushButton("Сбросить настройки")
        self.btn_reset.setIcon(_api.get_icon('fa5s.undo'))
        self.btn_reset.clicked.connect(self.reset_settings)
        pv.addWidget(self.btn_reset)
        pv.addStretch(1)

        scroll.setWidget(panel)
        self._disable_wheel(panel)
        col.addWidget(scroll, 1)
        col.addWidget(self._build_actions())
        body.addWidget(self.right_col)

    # ── группа «Пак» ──────────────────────────────────────────────────────
    def _group_pack(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Пак")
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.btn_pick = _api.QPushButton("Выбрать .siq…")
        self.btn_pick.setIcon(_api.get_icon('fa5s.file-import'))
        self.btn_pick.setToolTip("Пак, который надо доработать. Файл можно "
                                 "просто перетащить мышью на вкладку.")
        self.btn_pick.clicked.connect(self._choose_siq)
        g.addWidget(self.btn_pick, r, 0, 1, 2)
        r += 1
        self.lbl_siq = self._hint("")
        g.addWidget(self.lbl_siq, r, 0, 1, 2)
        r += 1
        self.btn_out_dir = _api.QPushButton("Папка для результата…")
        self.btn_out_dir.setIcon(_api.get_icon('fa5s.folder'))
        self.btn_out_dir.clicked.connect(self._choose_out_dir)
        g.addWidget(self.btn_out_dir, r, 0, 1, 2)
        r += 1
        self.lbl_out_dir = self._hint("")
        g.addWidget(self.lbl_out_dir, r, 0, 1, 2)
        r += 1
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Спецвопросы» ──────────────────────────────────────────────
    def _group_specials(self) -> _api.QGroupBox:
        # Галочка в заголовке группы и есть выключатель функции: снятая гасит
        # всю группу разом.
        grp = _api.QGroupBox("Убрать спецвопросы")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Вопросы со ставкой, с секретом, для себя, для всех и для всех со "
            "ставкой становятся обычными: сам вопрос, ответы и цена остаются на "
            "месте, снимается только особый режим.\n"
            "Названия типов — те же, какими их зовёт SIQuester.\n"
            "Понимает оба формата: и старый v4 (<type name=\"cat\">), и v5 "
            "SIGame 7 (type=\"secret\" плюс параметры темы/цены/режима выбора).")
        self.grp_specials = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.chk_no_question = _api.QCheckBox("Трогать и «с секретом без вопроса»")
        self.chk_no_question.setToolTip(
            "«С секретом без вопроса» (secretNoQuestion) — это выдача денег "
            "сразу, самого вопроса в нём нет. Обычным он станет пустым, поэтому "
            "по умолчанию такие вопросы остаются как есть (о каждом пишется в "
            "отчёт).")
        g.addWidget(self.chk_no_question, r, 0, 1, 2)
        r += 1
        g.addWidget(self._hint(
            "Вопросы, у которых вообще нет содержимого, здесь пропускаются в "
            "любом случае: обычным делать нечего. Их убирает «Удалить пустые "
            "вопросы»."), r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Варианты названий» ────────────────────────────────────────
    def _group_titles(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Дописать варианты названий")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            f"Если правильный ответ похож на название {self.what}, оно ищется "
            f"на {self.source_name}, и в ответ дописываются остальные его "
            f"названия — ровно как это делает «Генерация аниме-пака».\n"
            "Иероглифика не берётся вовсе: ведущему её не прочитать, игроку "
            "не набрать.")
        self.grp_titles = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.chk_strict = _api.QCheckBox("Только точное совпадение названия")
        self.chk_strict.setChecked(True)
        self.chk_strict.setToolTip(
            "Варианты дописываются, только когда одно из названий тайтла "
            "совпало с ответом слово в слово (регистр и знаки не в счёт).\n"
            "Опечатка в букву-другую сюда всё равно входит — «Gokukoku no "
            "Brunhildr» это «Brynhildr», а не другой тайтл. Слов при этом "
            "должно быть поровну, а номера сезонов совпадать точно: «Sword Art "
            "Online II» и «III» отличаются одним символом, но это разное.\n"
            "Снимите — засчитается и просто близкое название, но тогда чужой "
            "ответ может утащить варианты постороннего тайтла (например, "
            "сиквела).")
        g.addWidget(self.chk_strict, r, 0, 1, 2)
        r += 1
        self.chk_other_answers = _api.QCheckBox("Искать по всем вариантам ответа")
        self.chk_other_answers.setChecked(True)
        self.chk_other_answers.setToolTip(
            "Тайтл ищется не только по первой строке ответа, но и по остальным "
            "— а первая ещё и без песни за тире («Эхо террора - Trigger» → "
            "«Эхо террора»).\n"
            "На живом паке без этого не опознавался каждый третий ответ: "
            "голое название там лежит второй строкой. Ищем до первого "
            "попадания, так что на опознанных ответах лишних запросов нет.")
        g.addWidget(self.chk_other_answers, r, 0, 1, 2)
        r += 1
        self.chk_fix_case = _api.QCheckBox("Исправлять написание названия")
        self.chk_fix_case.setChecked(True)
        self.chk_fix_case.setToolTip(
            f"Ответ переписывается так, как название написано на "
            f"{self.source_name}: в паке «наруто» — станет «Наруто».\n"
            "Меняется ТОЛЬКО регистр букв и только при точном совпадении: "
            "иначе это был бы уже другой ответ, а не другое написание.")
        g.addWidget(self.chk_fix_case, r, 0, 1, 2)
        r += 1
        self.chk_poster = _api.QCheckBox(f"Ставить постер {self.what} в ответ")
        self.chk_poster.setChecked(True)
        self.chk_poster.setToolTip(
            f"В ответ кладётся постер с {self.source_name} — так же, как это "
            "делает «Генерация аниме-пака» (AVIF, три секунды на экране).\n"
            "Только при точном совпадении названия и только если своей картинки "
            "в ответе ещё нет. Один тайтл — один файл на весь пак.")
        g.addWidget(self.chk_poster, r, 0, 1, 2)
        r += 1
        self.chk_book_themes = _api.QCheckBox("Манга и ранобэ — искать книгу")
        self.chk_book_themes.setChecked(True)
        self.chk_book_themes.setToolTip(
            "Если в названии темы написано «манга», «манхва» или «ранобэ» "
            "(и латиницей тоже — «Manga»), ответ ищется по книгам, а не по "
            "аниме: обложка аниме в таком вопросе неверна, а у части ответов "
            "аниме нет вовсе («Soul Cartel», «Noblesse» — манхва).\n"
            "Книга не нашлась — названия всё равно доищутся по аниме, но "
            "обложка из него уже не берётся.")
        self.chk_characters = _api.QCheckBox("Не путать персонажа с тайтлом")
        self.chk_characters.setChecked(True)
        self.chk_characters.setToolTip(
            "Если ответ похож на имя героя (латиница в одно-три слова — «Mumei», "
            "«Teto Kasane»), он проверяется по базе персонажей Shikimori. Имя "
            "совпало точно — вопрос не трогается вовсе: спрашивали персонажа, а "
            "не аниме.\n"
            "Лишний запрос уходит только на такие ответы, и о каждом пропущенном "
            "пишется в таблицу.")
        g.addWidget(self.chk_book_themes, r, 0, 1, 2)
        r += 1
        g.addWidget(self.chk_characters, r, 0, 1, 2)
        r += 1
        g.addWidget(self._hint(
            "Дописываются все названия сразу: ромадзи, английское, "
            "лицензионное, синонимы и русское."),
            r, 0, 1, 2)
        r += 1
        self.sp_max_variants = _api.QSpinBox(); self.sp_max_variants.setRange(1, 50)
        self.sp_max_variants.setValue(8)
        self.sp_max_variants.setToolTip(
            "Потолок дописанных строк на один ответ. У популярных тайтлов "
            "синонимов бывает под два десятка, и весь список в ответе читать "
            "невозможно.")
        g.addWidget(self._lab("Не больше вариантов"), r, 0)
        g.addWidget(self.sp_max_variants, r, 1)
        r += 1
        self.sp_min_len = _api.QSpinBox(); self.sp_min_len.setRange(1, 20)
        self.sp_min_len.setValue(3)
        self.sp_min_len.setToolTip(
            f"Ответы короче этого на {self.source_name} не ищутся вовсе: «Да», "
            f"«1945» и прочее к {self.what} отношения не имеют, а запрос на "
            f"каждый такой ответ — это лишние секунды.")
        g.addWidget(self._lab("Ответ длиннее, символов"), r, 0)
        g.addWidget(self.sp_min_len, r, 1)
        r += 1
        g.addWidget(self._hint(
            f"Один и тот же тайтл спрашивается ровно раз на пак. "
            f"{self.source_name} отвечает не быстрее пяти раз в секунду — на "
            f"паке из полусотни разных названий это примерно полминуты."),
            r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Повторяющийся текст» ──────────────────────────────────────
    def _group_repeats(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Убрать повторяющийся текст")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Если один и тот же короткий текстовый блок стоит в КАЖДОМ вопросе "
            "темы («Назвать аниме»), он оттуда убирается: за ним всё равно идёт "
            "скрин или отрывок, и так понятно, что назвать надо аниме, а на "
            "экране это лишние секунды на каждом вопросе.\n"
            "Понимает оба формата: v5 (<item> в параметре вопроса) и v4 (<atom> "
            "сценария до маркера ответа). Вопрос без содержимого не остаётся "
            "никогда: если убирать пришлось бы всё, вопрос не трогается.")
        self.grp_repeats = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.sp_repeat_len = _api._no_wheel(_api.QSpinBox())
        self.sp_repeat_len.setRange(1, 500)
        self.sp_repeat_len.setValue(_api.UpgradeSettings().repeat_text_max_len)
        self.sp_repeat_len.setSuffix(" симв.")
        self.sp_repeat_len.setToolTip(
            "Длиннее этого текст не убирается, даже если он стоит во всех "
            "вопросах темы: короткая подпись — это указание, а длинный текст "
            "скорее сам вопрос.")
        g.addWidget(self._lab("Подпись не длиннее"), r, 0)
        g.addWidget(self.sp_repeat_len, r, 1)
        r += 1
        self.chk_known_labels = _api.QCheckBox("Убирать известные подписи")
        self.chk_known_labels.setChecked(True)
        self.chk_known_labels.setToolTip(
            "Закрытый список знакомых подписей — «Назвать аниме», «Назвать "
            "персонажа», «Назвать фильм», «Назвать песню» и подобные — "
            "убирается и тогда, когда в одном вопросе темы такой подписи нет.\n"
            "Правило «в КАЖДОМ вопросе» на живых паках спотыкается: в теме "
            "«Hayami Saori» из «Anime by Hinoriku 6» «Назвать персонажа» стоит "
            "в семи вопросах из восьми, а восьмой спрашивает совсем другое — "
            "и подпись оставалась во всех семи.\n"
            "Вопрос без содержимого тут тоже не остаётся: если убрать пришлось "
            "бы всё, вопрос не трогается.")
        g.addWidget(self.chk_known_labels, r, 0, 1, 2)
        r += 1
        g.addWidget(self._hint(
            "Тема из одного вопроса не в счёт: «в каждом» там значит «в "
            "единственном». Убирается только текст — картинки, звук и ролики "
            "остаются на месте."), r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Текст под звук» ───────────────────────────────────────────
    def _group_merge(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Текст под звук")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Если в вопросе идёт текстовый блок, а сразу за ним отрывок, текст "
            "включается ОДНОВРЕМЕННО со звуком — то самое «Объединить со "
            "следующим (играть одновременно)» из SIQuester.\n"
            "Без этого игра сначала держит текст на экране по таймеру и только "
            "потом включает музыку, хотя текст там как раз подпись к ней.\n"
            "Понимает оба формата: v5 (waitForFinish у <item>) и v4 (time=\"-1\" "
            "у <atom>). Ни новых блоков, ни параметров при этом не заводится — "
            "правится то, что в вопросе уже есть.")
        self.grp_merge = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        g.addWidget(self._hint(
            "Там, где автор уже включил одновременное воспроизведение, ничего "
            "не меняется. Картинки и ролики не в счёт: правило только про "
            "текст перед звуком."), 0, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Пустые вопросы» ───────────────────────────────────────────
    def _group_empty(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Удалить пустые вопросы")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Вопросы, в которых нет ничего — ни текста, ни картинки, ни звука, "
            "ни ролика, — выкидываются из пака целиком.\n"
            "Ответ не в счёт: играть в такой вопрос всё равно нечем, на экране "
            "пустота, сколько бы вариантов ответа под ним ни лежало.\n"
            "Тема, оставшаяся совсем без вопросов, убирается следом за ними.")
        self.grp_empty = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        g.addWidget(self._hint(
            "Каждый удалённый вопрос попадает в таблицу правок — видно, что "
            "именно ушло. Если пустыми выглядят ВСЕ вопросы пака, не трогается "
            "ни один: пустой пак игре не открыть."), 0, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Картинки» ─────────────────────────────────────────────────
    def _group_images(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Сжать тяжёлые картинки")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Картинки в паке тяжелее порога пережимаются в AVIF под лимит — тем "
            "же кодированием и с теми же быстрыми настройками, что в «Генерации "
            "аниме-пака» (libaom, tune=iq, подбор CQ, сторона не больше 1280).\n"
            "Ссылки в content.xml переводятся на новое имя файла, всё остальное "
            "медиа копируется как есть. GIF и уже готовый AVIF не трогаются.")
        self.grp_images = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.sp_img_min = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_img_min.setRange(0.1, 100.0)
        self.sp_img_min.setSingleStep(0.5)
        self.sp_img_min.setDecimals(1)
        self.sp_img_min.setValue(1.0)
        self.sp_img_min.setSuffix(" МБ")
        self.sp_img_min.setToolTip(
            "Картинки легче этого не трогаются вовсе: они и так не тянут пак "
            "вниз, а каждое кодирование — это время.")
        g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
        g.addWidget(self.sp_img_min, r, 1)
        r += 1
        self.sp_img_kb = _api._no_wheel(_api.QSpinBox())
        self.sp_img_kb.setRange(50, 20000)
        self.sp_img_kb.setSingleStep(50)
        self.sp_img_kb.setValue(500)
        self.sp_img_kb.setSuffix(" КБ")
        self.sp_img_kb.setToolTip(
            "До скольки килобайт ужимать. Кодер подбирает качество под этот "
            "размер, а если не влезает даже на минимальном — ужимает и "
            "разрешение.")
        g.addWidget(self._lab("Ужимать до"), r, 0)
        g.addWidget(self.sp_img_kb, r, 1)
        r += 1
        self.sp_img_speed = _api._no_wheel(_api.QSpinBox())
        self.sp_img_speed.setRange(0, 8)
        self.sp_img_speed.setValue(8)
        self.sp_img_speed.setToolTip(
            "Скорость кодирования AVIF (-cpu-used): 8 — быстро, 0 — медленно и "
            "чуть качественнее. Восьмёрка стоит и в генераторе паков.")
        g.addWidget(self._lab("Скорость (0–8)"), r, 0)
        g.addWidget(self.sp_img_speed, r, 1)
        r += 1
        g.addWidget(self._hint(
            "Кодирование идёт с низким приоритетом процесса — работать за "
            "компьютером оно не мешает. Картинка, которая после сжатия не стала "
            "легче, остаётся исходной."), r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Аудио» ────────────────────────────────────────────────────
    def _group_audio(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Сжать тяжёлое аудио")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Дорожки в паке тяжелее порога перекодируются в opus — тем же "
            "кодером и с теми же настройками, что во вкладке «Обработка» "
            "(libopus, переменный битрейт).\n"
            "Битрейт исходника сначала спрашивается у ffprobe: если он и так не "
            "выше выбранного, файл не трогается вовсе — перекод только испортил "
            "бы звук, ничего не выиграв.\n"
            "Громкость не трогается: в готовом паке её уже выставил автор.")
        self.grp_audio = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.sp_aud_min = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_aud_min.setRange(0.1, 500.0)
        self.sp_aud_min.setSingleStep(1.0)
        self.sp_aud_min.setDecimals(1)
        self.sp_aud_min.setValue(_api.UpgradeSettings().audio_min_mb)
        self.sp_aud_min.setSuffix(" МБ")
        self.sp_aud_min.setToolTip(
            "Дорожки легче этого не трогаются вовсе: они и так не тянут пак "
            "вниз, а каждое перекодирование — это время.")
        g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
        g.addWidget(self.sp_aud_min, r, 1)
        r += 1
        self.cb_aud_kbps = _api._no_wheel(_api.QComboBox())
        self.cb_aud_kbps.addItems([str(k) for k in _api.AUDIO_BITRATES])
        self.cb_aud_kbps.setCurrentText(str(_api.UpgradeSettings().audio_kbps))
        self.cb_aud_kbps.setToolTip(
            "В скольки килобитах кодировать. Список — тот же, что во вкладке "
            "«Обработка»; 128 кбит — качество звука на YouTube, 192 — с запасом "
            "и заметно легче исходных mp3 и wav.")
        g.addWidget(self._lab("Битрейт, кбит/с"), r, 0)
        g.addWidget(self.cb_aud_kbps, r, 1)
        r += 1
        self.chk_aud_norm = _api.QCheckBox("Нормализовать громкость (loudnorm)")
        self.chk_aud_norm.setToolTip(
            "Тот же loudnorm и с теми же тремя числами, что во вкладке "
            "«Обработка»: целевая громкость (LUFS), допустимый разброс (LRA) и "
            "потолок пиков (TP).\n"
            "Выключено по умолчанию: в ЧУЖОМ паке громкость уже выставил автор, "
            "и двигать её вслепую нельзя.\n"
            "Включённая, она снимает обе оговорки «не трогаю»: дорожка "
            "перекодируется, даже если и так не богаче выбранного битрейта и "
            "даже если легче не станет, — иначе нормализовать было бы нечего.\n"
            "Звук роликов нормализуется той же настройкой.")
        g.addWidget(self.chk_aud_norm, r, 0, 1, 2)
        r += 1
        norm_row = _api.QHBoxLayout()
        norm_row.setSpacing(4)
        self.sp_norm_i = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_norm_i.setRange(-60.0, 20.0)
        self.sp_norm_i.setSingleStep(0.1)
        self.sp_norm_i.setValue(_api.UpgradeSettings().audio_norm_i)
        self.sp_norm_i.setToolTip("Целевая громкость, LUFS. −20 — как в "
                                  "«Обработке».")
        self.sp_norm_lra = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_norm_lra.setRange(0.0, 50.0)
        self.sp_norm_lra.setSingleStep(0.1)
        self.sp_norm_lra.setValue(_api.UpgradeSettings().audio_norm_lra)
        self.sp_norm_lra.setToolTip("Допустимый разброс громкости (LRA).")
        self.sp_norm_tp = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_norm_tp.setRange(-60.0, 10.0)
        self.sp_norm_tp.setSingleStep(0.1)
        self.sp_norm_tp.setValue(_api.UpgradeSettings().audio_norm_tp)
        self.sp_norm_tp.setToolTip("Потолок пиков, dBTP.")
        for name, widget in (("LUFS:", self.sp_norm_i), ("LRA:", self.sp_norm_lra),
                             ("TP:", self.sp_norm_tp)):
            widget.setMaximumWidth(70)
            norm_row.addWidget(self._lab(name))
            norm_row.addWidget(widget)
        norm_row.addStretch(1)
        g.addLayout(norm_row, r, 0, 1, 2)
        r += 1
        g.addWidget(self._hint(
            "Ссылки в content.xml переводятся на новое имя файла (.opus), "
            "остальное медиа копируется как есть. Дорожка, которая после "
            "перекода не стала легче, остаётся исходной."), r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        self.chk_aud_norm.toggled.connect(self._refresh_norm_enabled)
        self._refresh_norm_enabled(self.chk_aud_norm.isChecked())
        return grp

    def _refresh_norm_enabled(self, on: bool) -> None:
        """Три числа нормализации без самой нормализации ничего не значат."""
        for widget in (self.sp_norm_i, self.sp_norm_lra, self.sp_norm_tp):
            widget.setEnabled(bool(on))

    # ── группа «Видео» ────────────────────────────────────────────────────
    def _group_video(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Сжать тяжёлое видео")
        grp.setCheckable(True)
        grp.setChecked(False)
        grp.setToolTip(
            "Ролики в паке перекодируются в AV1 — тем же кодером и с теми же "
            "флагами, что во вкладке «Обработка» и в генераторе паков "
            "(libsvtav1, keyint=-1 и scd=1: ключевые кадры только на сменах "
            "сцены). Звук ролика идёт в opus на том же битрейте и с той же "
            "нормализацией, что дорожки пака.\n"
            "Выключено по умолчанию НАРОЧНО, в отличие от остальных функций: "
            "перекод ролика идёт минутами, а с галочкой «не в AV1» под него "
            "попадает вообще всё видео пака.\n"
            "Ролик, который после перекода не стал легче, остаётся исходным.")
        self.grp_video = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        r = 0
        self.sp_vid_min = _api._no_wheel(_api.QDoubleSpinBox())
        self.sp_vid_min.setRange(0.1, 2000.0)
        self.sp_vid_min.setSingleStep(5.0)
        self.sp_vid_min.setDecimals(1)
        self.sp_vid_min.setValue(_api.UpgradeSettings().video_min_mb)
        self.sp_vid_min.setSuffix(" МБ")
        self.sp_vid_min.setToolTip(
            "Ролики тяжелее этого перекодируются всегда — каким бы кодеком они "
            "ни были закодированы, хоть тем же AV1.")
        g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
        g.addWidget(self.sp_vid_min, r, 1)
        r += 1
        self.chk_vid_non_av1 = _api.QCheckBox("Сжимать и всё, что не в AV1")
        self.chk_vid_non_av1.setChecked(True)
        self.chk_vid_non_av1.setToolTip(
            "Лёгкие ролики тоже перекодируются, если кодек у них отличается от "
            "AV1: mp4 с H.264 из чужого пака в AV1 худеет вдвое-втрое даже без "
            "ужимания разрешения.\n"
            "Кодек виден только после распаковки (ffprobe читает файл, а не "
            "запись архива), поэтому с этой галочкой из пака достаётся каждый "
            "ролик — на паке с десятком роликов это заметное время.\n"
            "Ролик, который уже в AV1 и легче порога, не трогается.")
        g.addWidget(self.chk_vid_non_av1, r, 0, 1, 2)
        r += 1
        self.sp_vid_crf = _api._no_wheel(_api.QSpinBox())
        self.sp_vid_crf.setRange(0, 63)
        self.sp_vid_crf.setValue(_api.UpgradeSettings().video_crf)
        self.sp_vid_crf.setToolTip(
            "Качество AV1 (CRF): больше — легче и хуже. 45 стоит и в "
            "генераторе паков — для ролика на экране SIGame этого хватает.")
        g.addWidget(self._lab("CRF (0–63)"), r, 0)
        g.addWidget(self.sp_vid_crf, r, 1)
        r += 1
        self.sp_vid_preset = _api._no_wheel(_api.QSpinBox())
        self.sp_vid_preset.setRange(0, 13)
        self.sp_vid_preset.setValue(_api.UpgradeSettings().video_preset)
        self.sp_vid_preset.setToolTip(
            "Пресет libsvtav1: 13 — самый быстрый, 0 — самый медленный и чуть "
            "качественнее. Тринадцать стоит и в генераторе паков.")
        g.addWidget(self._lab("Пресет (0–13)"), r, 0)
        g.addWidget(self.sp_vid_preset, r, 1)
        r += 1
        self.cb_vid_height = _api._no_wheel(_api.QComboBox())
        for height in _api.VIDEO_HEIGHTS:
            self.cb_vid_height.addItem("Исходное" if not height else f"{height}p",
                                       height)
        self.cb_vid_height.setToolTip(
            "До какой высоты ужимать кадр. Ролик только уменьшается: 480p не "
            "растянется до 1080p, сколько ни выбирай.")
        g.addWidget(self._lab("Разрешение"), r, 0)
        g.addWidget(self.cb_vid_height, r, 1)
        r += 1
        g.addWidget(self._hint(
            "Ссылки в content.xml переводятся на новое имя файла (.mp4). "
            "Ролики кодируются по одному: libsvtav1 и сам занимает все ядра. "
            "Битрейт звука и нормализацию ролик берёт из «Сжать тяжёлое "
            "аудио» — своих у него нет, чтобы пак звучал ровно."), r, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return grp

    # ── группа «Неиспользуемые файлы» ─────────────────────────────────────
    def _group_unused(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Удалить неиспользуемые файлы")
        grp.setCheckable(True)
        grp.setChecked(True)
        grp.setToolTip(
            "Медиа, на которое в content.xml нет ни одной ссылки, в новый пак "
            "не переносится: автор поменял картинку, а старая осталась лежать "
            "в архиве и весить.\n"
            "Занятым считается файл, чьё имя встретилось где угодно в "
            "content.xml — и в тексте, и в любом атрибуте: логотип пака, "
            "например, записан атрибутом, а не ссылкой в вопросе.\n"
            "Служебные части пака (content.xml, Texts/, [Content_Types].xml) "
            "не трогаются вовсе. Если «неиспользуемым» вышло ВСЁ медиа пака, "
            "не удаляется ни один файл: так не бывает.")
        self.grp_unused = grp
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        return grp

    def _build_actions(self) -> _api.QWidget:
        box = _api.QWidget()
        v = _api.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.btn_start = _api.QPushButton("Проапгрейдить пак")
        self.btn_start.setIcon(_api.get_icon('fa5s.magic', color='#11111b'))
        self.btn_start.setIconSize(_api.QSize(16, 16))
        self.btn_start.setObjectName("b_primary")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = _api.QPushButton("Стоп")
        self.btn_stop.setIcon(_api.get_icon('fa5s.stop'))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Остановить апгрейд (готовый файл не пишется, "
                                 "исходный пак не тронут).")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_open = _api.QPushButton("Открыть папку")
        self.btn_open.setIcon(_api.get_icon('fa5s.folder-open'))
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_result)
        v.addWidget(self.btn_start)
        row = _api.QHBoxLayout(); row.setSpacing(6)
        row.addWidget(self.btn_stop, 1)
        row.addWidget(self.btn_open, 1)
        v.addLayout(row)
        return box

    @staticmethod
    def _disable_wheel(root) -> None:
        for cls in (_api.QSpinBox, _api.QDoubleSpinBox, _api.QComboBox):
            for widget in root.findChildren(cls):
                _api._no_wheel(widget)

    # Уже этого панель настроек не сжимается: дальше подписи начинают резаться.
    SETTINGS_MIN_W = 300
    TABLE_MIN_W = 260

    def _fit_settings_width(self):
        """Ширина панели настроек — по её содержимому, но не больше, чем даёт
        окно (то же правило, что в «Генерации аниме-пака»)."""
        scroll = getattr(self, "scroll_settings", None)
        panel = scroll.widget() if scroll is not None else None
        if panel is None:
            return
        need = max(panel.sizeHint().width(), panel.minimumSizeHint().width(),
                   self.SETTINGS_MIN_W)
        if panel.minimumWidth() != need:
            panel.setMinimumWidth(need)
        sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        want = need + sb + 2 * scroll.frameWidth() + 4
        avail = self.width() - 24 - self.TABLE_MIN_W
        if avail > 0:
            want = min(want, max(self.SETTINGS_MIN_W, avail))
        col = getattr(self, "right_col", None) or scroll
        if want != col.width() or col.maximumWidth() != want:
            col.setFixedWidth(want)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if _api._HAS_CORE:
            self._fit_settings_width()

    def showEvent(self, event):
        super().showEvent(event)
        if _api._HAS_CORE:
            self._fit_settings_width()

    # ── перетаскивание пака мышью ─────────────────────────────────────────
    @staticmethod
    def _dropped_siq(event) -> str:
        data = event.mimeData()
        if not data.hasUrls():
            return ""
        for url in data.urls():
            path = url.toLocalFile()
            if path.lower().endswith(".siq"):
                return path
        return ""

    def dragEnterEvent(self, event):
        if self._dropped_siq(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        path = self._dropped_siq(event)
        if not path:
            super().dropEvent(event)
            return
        self.set_siq(path)
        event.acceptProposedAction()

    def set_siq(self, path: str) -> bool:
        """Подставить пак снаружи — тем же путём, что и перетаскивание мышью.
        False — вкладка не собралась (нет ядра) или файла нет на диске."""
        if not _api._HAS_CORE or not path or not _api.os.path.isfile(path):
            return False
        self._siq = path
        self._refresh_siq_label()
        return True

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget {{ color: {_api.C['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 5px 7px; color: {_api.C['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {_api.C['accent']};
            }}
            QPushButton, QToolButton {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 6px 12px; color: {_api.C['text']};
            }}
            QPushButton:hover, QToolButton:hover {{ background: {_api.C['surface2']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
            QPushButton#b_primary {{
                background: {_api.C['accent']}; color: #11111b; border: none;
                font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {_api.C['accent2']}; }}
            QPushButton#b_primary:disabled {{
                background: {_api.C['surface3']}; color: {_api.C['text3']};
            }}
            QGroupBox {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {_api.C['accent']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }}
            /* Выключенная функция и выглядеть должна выключенной. */
            QGroupBox:!enabled, QGroupBox::title:!enabled {{ color: {_api.C['text3']}; }}
            QTableWidget, QScrollArea#packcard {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 6px; outline: none;
            }}
            QScrollArea#packcard > QWidget > QWidget {{
                background: {_api.C['surface']};
            }}
            QHeaderView::section {{
                background: {_api.C['surface2']}; color: {_api.C['text2']};
                border: none; padding: 3px 3px; font-size: 11px;
            }}
            QTableWidget::item:selected {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
            }}
        """)

    # ── выбор файлов ──────────────────────────────────────────────────────
    def _choose_siq(self):
        start = (_api.os.path.dirname(self._siq) if self._siq
                 else self._out_dir or _api.os.path.expanduser("~"))
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Пак, который надо проапгрейдить", start,
            "Пакеты SIGame (*.siq);;Все файлы (*)")
        if not path:
            return
        self._siq = path
        self._refresh_siq_label()

    def _refresh_siq_label(self):
        if not self._siq:
            self.lbl_siq.setText("Пак не выбран: нажмите кнопку выше или "
                                 "перетащите .siq на вкладку.")
            self.lbl_siq.setToolTip("")
            self._show_pack_card()
            return
        try:
            size = _api.os.path.getsize(self._siq) / (1024 * 1024)
            size_text = f", {size:.1f} МБ"
        except OSError:
            size_text = ""
        self.lbl_siq.setText(f"{_api.os.path.basename(self._siq)}{size_text}")
        self.lbl_siq.setToolTip(self._siq)
        self._show_pack_card()

    def _choose_out_dir(self):
        start = self._out_dir or (_api.os.path.dirname(self._siq) if self._siq
                                  else _api.os.path.expanduser("~"))
        folder = _api.QFileDialog.getExistingDirectory(
            self, "Куда класть готовый пак", start)
        if folder:
            self._out_dir = folder
            self._refresh_out_dir_label()

    def _refresh_out_dir_label(self):
        if self._out_dir:
            self.lbl_out_dir.setText(self._out_dir)
            self.lbl_out_dir.setToolTip(self._out_dir)
        else:
            self.lbl_out_dir.setText("Рядом с исходным паком.")
            self.lbl_out_dir.setToolTip("")

    # ── настройки ─────────────────────────────────────────────────────────
    def collect(self) -> '_api.UpgradeSettings':
        s = _api.UpgradeSettings()
        s.profile = self.profile
        s.strip_specials = self.grp_specials.isChecked()
        s.strip_no_question = self.chk_no_question.isChecked()
        s.add_titles = self.grp_titles.isChecked()
        s.strict_match = self.chk_strict.isChecked()
        s.use_other_answers = self.chk_other_answers.isChecked()
        s.fix_case = self.chk_fix_case.isChecked()
        s.add_poster = self.chk_poster.isChecked()
        s.check_characters = self.chk_characters.isChecked()
        s.book_themes = self.chk_book_themes.isChecked()
        s.max_variants = self.sp_max_variants.value()
        s.min_query_len = self.sp_min_len.value()
        s.strip_repeated_text = self.grp_repeats.isChecked()
        s.repeat_text_max_len = self.sp_repeat_len.value()
        s.strip_known_labels = self.chk_known_labels.isChecked()
        s.merge_text_audio = self.grp_merge.isChecked()
        s.compress_images = self.grp_images.isChecked()
        s.image_min_mb = self.sp_img_min.value()
        s.image_limit_kb = self.sp_img_kb.value()
        s.image_speed = self.sp_img_speed.value()
        s.drop_empty_questions = self.grp_empty.isChecked()
        s.compress_audio = self.grp_audio.isChecked()
        s.audio_min_mb = self.sp_aud_min.value()
        s.audio_kbps = _api.nearest_bitrate(self.cb_aud_kbps.currentText())
        s.audio_norm = self.chk_aud_norm.isChecked()
        s.audio_norm_i = self.sp_norm_i.value()
        s.audio_norm_lra = self.sp_norm_lra.value()
        s.audio_norm_tp = self.sp_norm_tp.value()
        s.compress_video = self.grp_video.isChecked()
        s.video_min_mb = self.sp_vid_min.value()
        s.video_non_av1 = self.chk_vid_non_av1.isChecked()
        s.video_crf = self.sp_vid_crf.value()
        s.video_preset = self.sp_vid_preset.value()
        s.video_height = _api.nearest_height(self.cb_vid_height.currentData())
        s.drop_unused = self.grp_unused.isChecked()
        s.out_dir = self._out_dir
        return s

    def get_settings(self) -> dict:
        """Настройки вкладки для settings.json."""
        if not _api._HAS_CORE:
            return dict(self._initial)
        data = self.collect().to_dict()
        # Сам пак тоже запоминаем: обычно дорабатывают тот же файл, что и в
        # прошлый раз, и искать его в проводнике заново незачем.
        data["siq"] = self._siq
        return data

    def apply_settings(self, data: dict):
        if not _api._HAS_CORE or not isinstance(data, dict):
            return
        s = _api.UpgradeSettings.from_dict(data)
        self.grp_specials.setChecked(s.strip_specials)
        self.chk_no_question.setChecked(s.strip_no_question)
        self.grp_titles.setChecked(s.add_titles)
        self.chk_strict.setChecked(s.strict_match)
        self.chk_other_answers.setChecked(s.use_other_answers)
        self.chk_fix_case.setChecked(s.fix_case)
        self.chk_poster.setChecked(s.add_poster)
        self.chk_characters.setChecked(s.check_characters)
        self.chk_book_themes.setChecked(s.book_themes)
        self.sp_max_variants.setValue(max(1, min(50, int(s.max_variants))))
        self.sp_min_len.setValue(max(1, min(20, int(s.min_query_len))))
        self.grp_repeats.setChecked(s.strip_repeated_text)
        self.sp_repeat_len.setValue(max(1, min(500, int(s.repeat_text_max_len))))
        self.chk_known_labels.setChecked(s.strip_known_labels)
        self.grp_merge.setChecked(s.merge_text_audio)
        self.grp_images.setChecked(s.compress_images)
        self.sp_img_min.setValue(max(0.1, min(100.0, float(s.image_min_mb))))
        self.sp_img_kb.setValue(max(50, min(20000, int(s.image_limit_kb))))
        self.sp_img_speed.setValue(max(0, min(8, int(s.image_speed))))
        self.grp_empty.setChecked(s.drop_empty_questions)
        self.grp_audio.setChecked(s.compress_audio)
        self.sp_aud_min.setValue(max(0.1, min(500.0, float(s.audio_min_mb))))
        self.cb_aud_kbps.setCurrentText(str(_api.nearest_bitrate(s.audio_kbps)))
        self.chk_aud_norm.setChecked(s.audio_norm)
        self.sp_norm_i.setValue(max(-60.0, min(20.0, float(s.audio_norm_i))))
        self.sp_norm_lra.setValue(max(0.0, min(50.0, float(s.audio_norm_lra))))
        self.sp_norm_tp.setValue(max(-60.0, min(10.0, float(s.audio_norm_tp))))
        self.grp_video.setChecked(s.compress_video)
        self.sp_vid_min.setValue(max(0.1, min(2000.0, float(s.video_min_mb))))
        self.chk_vid_non_av1.setChecked(s.video_non_av1)
        self.sp_vid_crf.setValue(max(0, min(63, int(s.video_crf))))
        self.sp_vid_preset.setValue(max(0, min(13, int(s.video_preset))))
        height = _api.nearest_height(s.video_height)
        self.cb_vid_height.setCurrentIndex(
            max(0, self.cb_vid_height.findData(height)))
        self.grp_unused.setChecked(s.drop_unused)
        self._out_dir = s.out_dir or ""
        siq = str(data.get("siq") or "")
        # Пропавший файл не подставляем: подпись врала бы про выбранный пак.
        self._siq = siq if siq and _api.os.path.isfile(siq) else ""
        self._refresh_siq_label()
        self._refresh_out_dir_label()

    def reset_settings(self):
        # Сброс — про настройки, а не про выбранный файл: терять путь к паку
        # ради галочек пользователь не просил.
        siq = self._siq
        self.apply_settings(_api.UpgradeSettings(profile=self.profile).to_dict())
        self._siq = siq
        self._refresh_siq_label()

    # ── работа ────────────────────────────────────────────────────────────
    def log(self, msg: str):
        """Всё пишем в общую консоль внизу окна — своей у вкладки нет.

        Профиль в подписи обязателен: страниц две, а консоль на них одна, и без
        него было бы не понять, чей это апгрейд идёт."""
        if self.main is not None and hasattr(self.main, "log"):
            try:
                self.main.log(f"[{_api.PROFILE_LABELS.get(self.profile, 'Апгрейд')}]"
                              f" {msg}")
            except Exception:
                pass

    def start(self):
        if self._task is not None:
            return
        if not self._siq or not _api.os.path.isfile(self._siq):
            _api.msgbox_warning(self, "Нечего апгрейдить",
                           "Сначала выберите .siq — кнопкой «Выбрать .siq…» "
                           "или перетащив файл на вкладку.")
            return
        settings = self.collect()
        problems = settings.validate()
        if problems:
            _api.msgbox_warning(self, "Так не получится", "\n\n".join(problems))
            return

        if self.main is not None and hasattr(self.main, "clear_global_result"):
            self.main.clear_global_result()

        self.table.setRowCount(0)
        self._last_pack = ""
        self.btn_open.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._started_at = _api.time.monotonic()
        self._progress(0, "Читаю пак…")
        self.log(f"Апгрейд «{_api.os.path.basename(self._siq)}»: "
                 + ", ".join(self._what_for(settings)))

        task = _api._UpgradeTask(self._siq, settings)
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        self._pool.start(task)

    @staticmethod
    def _what_for(settings) -> list[str]:
        what = []
        if settings.strip_specials:
            what.append("убираю спецвопросы")
        if settings.add_titles:
            what.append(f"дописываю варианты названий "
                        f"({settings.source_name})")
        if settings.strip_repeated_text:
            what.append("убираю повторяющийся текст тем")
        if settings.merge_text_audio:
            what.append("включаю текст перед отрывком одновременно со звуком")
        if settings.drop_empty_questions:
            what.append("удаляю пустые вопросы")
        if settings.compress_images:
            what.append(f"сжимаю картинки тяжелее {settings.image_min_mb:g} МБ")
        if settings.compress_audio:
            what.append(f"перекодирую аудио тяжелее {settings.audio_min_mb:g} МБ"
                        f" в opus {settings.audio_kbps} кбит"
                        + (" с нормализацией" if settings.audio_norm else ""))
        if settings.compress_video:
            what.append(f"перекодирую видео тяжелее {settings.video_min_mb:g} МБ"
                        + (" (и всё не в AV1)" if settings.video_non_av1 else "")
                        + f" в av1 crf {settings.video_crf}")
        if settings.drop_unused:
            what.append("удаляю неиспользуемые файлы")
        return what or ["ничего не делаю"]

    def stop(self):
        if self._task is not None:
            self._task.stop()
            self._progress(0, "Останавливаюсь…")
            self.btn_stop.setEnabled(False)

    def _progress(self, pct: int, text: str) -> None:
        """Своей полосы у вкладки нет — пишем в общую, внизу окна."""
        if self.main is None or not hasattr(self.main, "update_global_progress"):
            return
        try:
            self.main.update_global_progress(
                max(0, min(100, int(pct))), text, started_at=self._started_at,
                running=self._task is not None or text == "Читаю пак…")
        except Exception:
            pass

    def _on_progress(self, done: int, total: int, msg: str):
        total = max(1, total)
        self._progress(int(done * 100 / total), msg or f"{done}/{total}")

    def _finish_ui(self):
        self._task = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_failed(self, err: str):
        self._finish_ui()
        self._progress(0, "Не получилось")
        self.log(f"Ошибка: {err}")
        _api.msgbox_critical(self, "Апгрейд не удался", err)

    def _on_finished(self, result):
        self._finish_ui()
        self._fill_table(result)
        if result.cancelled:
            self._progress(0, "Остановлено")
            self.log("Апгрейд остановлен, файл не записан — исходный пак цел.")
            return
        spent = _api.fmt_elapsed(getattr(result, "elapsed", 0.0))
        self._last_pack = result.path
        self.btn_open.setEnabled(bool(result.path))
        if self.main is not None and hasattr(self.main, "set_global_result"):
            self.main.set_global_result(result.path)
        self._progress(100, f"Готово за {spent} · "
                            f"{_api.os.path.basename(result.path)}")
        # Три примера с каждой функции — прямо в лог, следом за итогом.
        for line in _api.example_lines(result, limit=3):
            self.log(line)
        self.log(f"Пак сохранён за {spent}: {result.path}")
        if not result.total:
            _api.msgbox_information(
                self, "Менять было нечего",
                "Ни спецвопросов, ни опознанных названий аниме, ни тяжёлых "
                "картинок в паке не нашлось — постеры и написание названий "
                "тоже правились не по чему. Копия всё равно сохранена:\n\n"
                + result.path)

    # Правки, у которых места в раундах нет вовсе: это не вопрос, а файл в
    # архиве. Ни раунда, ни цены у них не бывает, и имя файла занимает все три
    # колонки разом — иначе оно жалось в «Тему» между двумя пустыми клетками.
    FILE_KINDS = ("image", "audio", "video", "unused")

    def _fill_table(self, result):
        rows = (result.changes + list(result.skipped_specials)
                + list(getattr(result, "skipped_titles", [])))
        self.table.setRowCount(0)
        # Объединённые клетки живут по номеру строки и переживают setRowCount(0):
        # не снять их — и следующий отчёт слепит колонки не тем строкам.
        self.table.clearSpans()
        # Карточка пака уступает место списку правок — за ней всегда можно
        # вернуться, выбрав файл заново.
        self.left_stack.setCurrentIndex(1)
        labels = {"special": "Спецвопрос", "title": "Названия",
                  "case": "Написание", "poster": "Постер",
                  "image": "Картинка", "character": "Персонаж",
                  "repeat": "Повтор", "merge": "Вместе", "empty": "Пустой",
                  "audio": "Аудио", "video": "Видео", "unused": "Мусор"}
        files: list[str] = []                 # имена файлов на три колонки
        rounds: list[str] = []                # раунды обычных правок
        for i, change in enumerate(sorted(rows, key=lambda c: c.order)):
            self.table.insertRow(i)
            is_file = change.kind in self.FILE_KINDS
            cells = [
                _api.QTableWidgetItem(str(i + 1)),
                # У файла имя лежит в «Теме», но показать его надо во всю
                # ширину — кладём в «Раунд» и растягиваем до «Цены».
                _api.QTableWidgetItem(change.theme_name if is_file
                                 else change.round_name),
                _api.QTableWidgetItem("" if is_file else change.theme_name),
                _api.QTableWidgetItem("" if is_file else str(change.price)),
                _api.QTableWidgetItem(labels.get(change.kind, change.kind)),
                _api.QTableWidgetItem(change.before),
                _api.QTableWidgetItem(change.after),
            ]
            for col, item in enumerate(cells):
                if col in self.TABLE_NUM_COLS:
                    item.setTextAlignment(_api.Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, col, item)
            if is_file:
                self.table.setSpan(i, 1, 1, 3)
                files.append(change.theme_name)
            else:
                rounds.append(change.round_name)
        self._fit_round_column(files, rounds)

    def _fit_round_column(self, files: list, rounds: list) -> None:
        """Ширина «Раунда» — своими руками, остальные колонки по-прежнему по
        содержимому.

        Объединённые клетки Qt меряет по-своему и имени файла места недодаёт
        (проверено на живом окне: длинное имя обрывалось многоточием), поэтому
        «Раунду» ширина выставляется прямо: столько, сколько имени не хватило на
        «Тему» с «Ценой», но не меньше, чем нужно самим раундам."""
        table = self.table
        header = table.horizontalHeader()
        table.resizeColumnsToContents()
        fm = table.fontMetrics()
        pad = 12                              # отступы клетки в текст не входят
        need = max([fm.horizontalAdvance(self.TABLE_HEADERS[1])]
                   + [fm.horizontalAdvance(name) for name in rounds]) + pad
        if files:
            free = table.columnWidth(2) + table.columnWidth(3)
            need = max(need, max(fm.horizontalAdvance(name) for name in files)
                       + pad - free)
        header.resizeSection(1, max(header.minimumSectionSize(), need))

    def _open_result(self):
        if not self._last_pack:
            return
        try:
            from utils import reveal_in_explorer
            reveal_in_explorer(self._last_pack)
        except Exception as e:  # noqa: BLE001
            _api.msgbox_critical(self, "Не открылось", str(e))

    # ── завершение работы страницы ────────────────────────────────────────
    def cleanup(self):
        if self._task is not None:
            self._task.stop()
        self._task = None


_UpgradePage.__module__ = _api.__name__
_api._UpgradePage = _UpgradePage
