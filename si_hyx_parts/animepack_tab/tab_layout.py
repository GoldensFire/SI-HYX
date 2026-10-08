# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Генерация аниме-пака: панель настроек, группы, таблица результатов и стили."""
from __future__ import annotations
import animepack_tab as _api


# Расстояние между колонками вкладки — то же, что задано body в _build_ui.
BODY_SPACING = 12

def _fit_columns(self, scroll, outer: int):
    """Сколько колонок настроек помещается в отведённую панели ширину.

    Считаем по ширине, которую панель ТОЛЬКО ЧТО получила, а не по её
    нынешней геометрии: сама панель растёт вслед за числом колонок, и мерить
    по ней значило бы гнаться за собственным хвостом. По этой же причине не
    годится и viewport: сразу после «Показать таблицу» он ещё старый."""
    columns = getattr(self, "settings_columns", None)
    if columns is None:
        return
    sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
    # Поля самой панели (2 + 8) и рамка окна прокрутки.
    columns.apply_width(max(1, int(outer) - sb - 2 * scroll.frameWidth() - 14))

def _db_panel(self):
    """Открытая панель базы или None."""
    dialog = getattr(self, "_db_table_dialog", None)
    try:
        return dialog if dialog is not None and dialog.isVisible() else None
    except RuntimeError:                 # окно уже удалено
        return None


class AnimePackTabLayoutMixin:
    """Генерация аниме-пака: панель настроек, группы, таблица результатов и стили."""

    def _update_table_hint(self):
        """Показывает предупреждение НАКЛАДКОЙ на таблицу, пока пак ещё не
        собран (строк нет), и прячет её, как только строки появились. Саму
        таблицу видимость не трогает — только накладку поверх неё."""
        hint = getattr(self, "lbl_table_hint", None)
        if hint is None:
            return
        hint.setGeometry(self.table.rect())
        hint.setVisible(self.table.rowCount() == 0)

    def _on_sort_changed(self, section: int, order):
        """Своя стрелка сортировки — в подписи колонки (родную мы выключили,
        чтобы она не резервировала место во всех секциях сразу)."""
        arrow = "↑" if order == _api.Qt.SortOrder.AscendingOrder else "↓"
        for col, name in enumerate(self.TABLE_HEADERS):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                item.setText(f"{name} {arrow}" if col == section else name)

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

    # ── Ключи внешних API (единое место — Настройки программы) ────────────
    def _api_key(self, name: str) -> str:
        fn = getattr(getattr(self, "main", None), "get_api_key", None)
        if fn is None:
            return ""
        try:
            return str(fn(name) or "").strip()
        except Exception:
            return ""

    def _migrate_api_key(self, name: str, old_value):
        """Ключ, сохранённый ещё в настройках самой вкладки, один раз
        переезжает в общие настройки программы (Настройки → «Ключи API»)."""
        val = str(old_value or "").strip()
        setter = getattr(getattr(self, "main", None), "set_api_key", None)
        if val and setter is not None and not self._api_key(name):
            try:
                setter(name, val)
            except Exception:
                pass
        self._refresh_api_key_buttons()

    def _open_api_settings(self):
        fn = getattr(getattr(self, "main", None), "_open_settings_dialog", None)
        if fn is not None:
            try:
                fn("Ключи API")
            except Exception:
                pass
        self._refresh_api_key_buttons()

    def _api_key_button(self, name: str, title: str) -> _api.QPushButton:
        """Вместо поля ввода — кнопка «задан / не задан», открывающая Настройки:
        один и тот же ключ нужен нескольким вкладкам, и место у него одно."""
        btn = _api.QPushButton()
        btn.setToolTip(f"{title} — открыть Настройки программы, раздел «Ключи API»")
        btn.clicked.connect(self._open_api_settings)
        if not hasattr(self, "_api_key_buttons"):
            self._api_key_buttons = []
        self._api_key_buttons.append((btn, name, title))
        self._refresh_api_key_buttons()
        return btn

    def _refresh_api_key_buttons(self):
        for btn, name, title in getattr(self, "_api_key_buttons", []):
            has = bool(self._api_key(name))
            btn.setText("задан" if has else "не задан — ввести")

    def _build_settings_panel(self, body):
        # Правая колонка прокручивается отдельно: при низком окне шаблон,
        # параметры пака и кнопки сохраняют полную высоту и доступны через скролл.
        self.scroll_settings = scroll = _api.QScrollArea()
        scroll.setWidgetResizable(True)
        # Горизонтальная полоса — на самый крайний случай (окно уже, чем панель
        # вообще может сжаться). Раньше она была выключена наглухо, и правый
        # край настроек просто срезало.
        scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel = _api.QWidget()
        pv = _api.QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        # Группы настроек раскладываются по колонкам под ширину панели: пока
        # таблица спрятана, вкладка отдаёт настройкам всю ширину, и одна узкая
        # колонка на несколько экранов прокрутки больше не нужна (просьба
        # пользователя). Список групп и их порядок прежние.
        # «Пак» из колонок ушёл: он теперь стоит справа, рядом с кнопками.
        from si_hyx_parts.animepack_tab.settings_columns import SettingsColumns
        groups = [self._group_songs(), self._group_lists(),
                  self._group_anime(), self.group_gemini, self._group_other()]
        self.settings_columns = SettingsColumns(
            groups, self.SETTINGS_MIN_W, pinned_second=True)
        pv.addWidget(self.settings_columns)

        self.btn_reset = _api.QPushButton("Сбросить настройки")
        self.btn_reset.setIcon(_api.get_icon('fa5s.undo'))
        self.btn_reset.clicked.connect(self.reset_settings)
        pv.addWidget(self.btn_reset)
        pv.addStretch(1)

        scroll.setWidget(panel)
        from PyQt6.QtWidgets import QTabWidget
        from .entrance_controls import build_page
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(scroll, "Настройки")
        self.scroll_entrance = build_page(self)
        self.settings_tabs.addTab(self.scroll_entrance, "Появление")
        body.addWidget(self.settings_tabs, 1)

        self.right_col = _api.QWidget()
        self.right_col.setObjectName("packSettingsPanel")
        self.right_col.setStyleSheet(
            f"#packSettingsPanel {{ background: {_api.C['bg']}; }}")
        col = _api.QVBoxLayout(self.right_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.templates_box = self._build_templates()
        col.addWidget(self.templates_box)
        self.pack_box = self._group_pack()
        col.addWidget(self.pack_box)
        # Действия относятся к «Паку», поэтому держим их рядом. Растяжка ниже
        # оставляет свободное место внизу колонки, а не разрывает связанные
        # элементы огромной пустотой на высоком окне.
        self.actions_box = self._build_actions()
        col.addWidget(self.actions_box)
        col.addStretch(1)
        self.scroll_pack = _api.QScrollArea()
        self.scroll_pack.setWidgetResizable(True)
        self.scroll_pack.setFrameShape(_api.QFrame.Shape.NoFrame)
        self.scroll_pack.setHorizontalScrollBarPolicy(
            _api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_pack.setVerticalScrollBarPolicy(
            _api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_pack.setWidget(self.right_col)
        body.addWidget(self.scroll_pack)
        # Колесо мыши не должно менять счётчики ни в настройках, ни в «Паке».
        self._disable_wheel(panel)
        self._disable_wheel(self.right_col)
        self._fit_settings_width()

    def _build_actions(self) -> _api.QWidget:
        """Полоса запуска под настройками: «Сгенерировать пак», «Стоп»,
        «Открыть папку» и строчка про автора идеи."""
        box = _api.QWidget()
        v = _api.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.btn_start = _api.QPushButton("Сгенерировать пак")
        self.btn_start.setIcon(_api.get_icon('fa5s.magic', color='#11111b'))
        self.btn_start.setIconSize(_api.QSize(16, 16))
        self.btn_start.setObjectName("b_primary")
        self.btn_start.clicked.connect(self.start)
        from .priority_slider import PrioritySlider
        self.cb_generation_priority = PrioritySlider()
        self.cb_generation_priority.currentIndexChanged.connect(self._change_priority)
        self.cb_generation_priority.setToolTip(
            "Низкий ограничивает параллельные задачи двумя и понижает приоритет "
            "рабочих потоков и ffmpeg. Обычный использует заданное число потоков. "
            "Приоритет можно менять во время генерации; начатые задачи завершаются.")
        self.queue_list = _api.QListWidget()
        self.queue_list.setMaximumHeight(100)
        self.queue_list.setVisible(False)
        self.btn_queue_remove = _api.QPushButton("Убрать выбранный из очереди")
        self.btn_queue_remove.setVisible(False)
        self.btn_queue_remove.clicked.connect(self._remove_queued)
        self.btn_stop = _api.QPushButton("Стоп")
        self.btn_stop.setIcon(_api.get_icon('fa5s.stop'))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Остановить генерацию и очистить очередь")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_open = _api.QPushButton("Открыть папку")
        self.btn_open.setIcon(_api.get_icon('fa5s.folder-open'))
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_result)
        # Таблица состава пака показывается ТОЛЬКО по этой кнопке (просьба
        # пользователя): до генерации в ней всё равно пусто, а место у неё —
        # половина вкладки, и настройкам оно нужнее.
        self.btn_table = _api.QPushButton("Показать таблицу")
        self.btn_table.setIcon(_api.get_icon('fa5s.table'))
        self.btn_table.setEnabled(False)
        self.btn_table.setToolTip(
            "Что именно отобрано в пак: тема, раунд, аниме, песня, род вопроса и "
            "цена. После генерации открывается в отдельном окне.")
        self.btn_table.clicked.connect(self._toggle_table)
        v.addWidget(_api.QLabel("Приоритет генерации:"))
        v.addWidget(self.cb_generation_priority)
        v.addWidget(self.btn_start)
        from .saved_attempt import build as build_saved_attempt
        build_saved_attempt(self)
        v.addWidget(self.btn_rebuild_saved)
        v.addWidget(self.queue_list)
        v.addWidget(self.btn_queue_remove)
        row = _api.QHBoxLayout(); row.setSpacing(6)
        row.addWidget(self.btn_stop, 1)
        row.addWidget(self.btn_open, 1)
        v.addLayout(row)
        v.addWidget(self.btn_table)

        # Ссылка на автора идеи — единственная благодарность на вкладке: слева,
        # под таблицей, такой же надписи больше нет (просьба пользователя).
        # Открывается в браузере (setOpenExternalLinks). Прочие имена в скобках —
        # те же самые ники того же человека, поэтому они выделены и кликабельны
        # ровно так же, как «Leleath» (просьба пользователя).
        link = ('<a href="https://github.com/Leleath/aspg"'
                f' style="color:{_api.C["accent"]}; text-decoration:none;">%s</a>')
        # Это один человек: ссылка охватывает и основной ник, и скобки, и запятые,
        # поэтому вся подпись имени выглядит одним цельным синим фрагментом.
        self.lbl_credit = _api.QLabel(
            "Идея взята у уважаемого " + (link % "Leleath (ффыв, nanri, нефор)"))
        self.lbl_credit.setWordWrap(True)
        self.lbl_credit.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_credit.setOpenExternalLinks(True)
        self.lbl_credit.setTextInteractionFlags(
            _api.Qt.TextInteractionFlag.TextBrowserInteraction)
        self.lbl_credit.setToolTip("https://github.com/Leleath/aspg")
        self.lbl_credit.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
        # Без флага выравнивания в addWidget! С ним раскладка отдаёт надписи её
        # собственный sizeHint, а у QLabel с переносом слов он в одну короткую
        # строку (122 px на живом окне) — строка обрезалась сразу после «Идея
        # взята у уважаемого», и ни «Leleath», ни «нефор» видно не было. Ширину
        # даёт сама колонка, а по центру текст ставит setAlignment выше.
        v.addWidget(self.lbl_credit)
        return box

    @staticmethod
    def _disable_wheel(root) -> None:
        """Колесо мыши не должно менять значения счётчиков и списков — оно
        прокручивает панель (просьба пользователя)."""
        for cls in (_api.QSpinBox, _api.QDoubleSpinBox, _api.QComboBox):
            for widget in root.findChildren(cls):
                _api._no_wheel(widget)

    def _table_shown(self) -> bool:
        """Встроенная таблица больше не показывается: она открывается окном."""
        box = getattr(self, "table_box", None)
        return box is not None and not box.isHidden()

    def _toggle_table(self):
        """Открыть состав пакета отдельным окном, не сжимая настройки."""
        if self.table.rowCount() <= 0:
            return
        from .table_dialog import open_pack_table
        open_pack_table(self)

    def _fit_pack_column(self) -> int:
        """Ширина неподвижной колонки «Пак» + кнопки; она же и возвращается.

    Колонка стоит на месте всегда, поэтому ширину ей даёт СВОЁ содержимое, а
    не остаток вкладки: иначе кнопка «Сгенерировать пак» ездила бы туда-сюда
    от каждого показа таблицы.

    Сверху — потолок: своим желанием группа «Пак» просит на четыре десятка
    пикселей больше, чем ей нужно (поле «Название» тянется), а отнимает их у
    настроек, и на экране 1600 точек это стоило им целой колонки."""
        pack = getattr(self, "right_col", None)
        if pack is None:
            return 0
        group = getattr(self, "pack_box", None)
        if group is not None:
            from .settings_box import needed_height
            # Стили добавляют полям padding и min-height уже после создания.
            # Обычный минимум QGroupBox этого не учитывает целиком и позволяет
            # низкому окну обрезать счётчики. Берём полную высоту после стилей.
            group.ensurePolished()
            group.setMinimumHeight(0)
            group.layout().invalidate()
            group.layout().activate()
            group.setMinimumHeight(needed_height(group))
        want = max(self.PACK_MIN_W,
                   min(self.PACK_MAX_W, int(pack.sizeHint().width())))
        scroll = getattr(self, "scroll_pack", None)
        reserved = scroll.verticalScrollBar().sizeHint().width() if scroll else 0
        content_width = max(1, want - reserved)
        if pack.maximumWidth() != content_width:
            pack.setFixedWidth(content_width)
        # Содержимое не должно сжиматься по высоте: недостающее место отдаётся
        # прокрутке. Учитываем и действия с переносимой подписью под кнопками.
        from .settings_box import needed_height
        boxes = (self.templates_box, self.pack_box, self.actions_box)
        pack.setMinimumHeight(sum(needed_height(box) for box in boxes)
                              + 2 * pack.layout().spacing())
        if scroll is None:
            return want
        # Полоса помещается внутри прежней ширины правой панели: соседние
        # настройки не теряют целую колонку из-за нескольких новых пикселей.
        scroll.setFixedWidth(want)
        return want

    def _fit_settings_width(self):
        """Keep a stable settings column; only resizing the window can shrink it."""
        scroll = getattr(self, "scroll_settings", None)
        panel = scroll.widget() if scroll is not None else None
        if panel is None:
            return
        pack = self._fit_pack_column()
        margins = self.layout().contentsMargins()
        available = self.width() - margins.left() - margins.right()
        entrance_columns = getattr(self, "entrance_columns", None)
        if entrance_columns is not None:
            entrance_columns.apply_width(max(1, available - pack - BODY_SPACING - 40))
        if not self._table_shown():
            # Таблица спрятана — настройки забирают всю оставшуюся ширину вкладки
            # и сами раскладываются в несколько колонок (settings_columns).
            # Фиксированную ширину, выставленную в режиме с таблицей, здесь надо
            # снять: иначе панель так и осталась бы узкой полосой.
            panel.setMinimumWidth(0)
            scroll.setMinimumWidth(self.SETTINGS_MIN_W)
            scroll.setMaximumWidth(_api.QWIDGETSIZE_MAX)
            _fit_columns(self, scroll, available - pack - BODY_SPACING)
            return
        need = max(480, self.SETTINGS_MIN_W)
        # Панель не даём сжимать ниже её собственной ширины: тогда в совсем
        # узком окне появляется горизонтальная полоса и до правого края всё
        # равно можно доехать, вместо того чтобы поля молча резались.
        if panel.minimumWidth() != need:
            panel.setMinimumWidth(need)
        sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        want = need + sb + 2 * scroll.frameWidth() + 4
        # Поля root-раскладки плюс две неподвижные соседки: таблица слева и
        # колонка «Пак» справа.
        avail = available - self.TABLE_MIN_W - pack - 2 * BODY_SPACING
        if avail > 0:
            want = min(want, max(self.SETTINGS_MIN_W, avail))
        if want != scroll.width() or scroll.maximumWidth() != want:
            scroll.setFixedWidth(want)
        _fit_columns(self, scroll, want)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_settings_width()
        self._update_table_hint()

    def showEvent(self, event):
        super().showEvent(event)
        # Первый показ — единственный момент, когда размеры полей уже настоящие
        # (стили применены, шрифты подобраны).
        self._fit_settings_width()
        self._update_table_hint()

    # ── группа «Пак» ──────────────────────────────────────────────────────
    def _group_pack(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Пак")
        g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        self.ed_title = _api.QLineEdit("Сгенерировано в SI-HYX")
        self.ed_theme = _api.QLineEdit("SI-HYX")
        self.sp_rounds = _api.QSpinBox(); self.sp_rounds.setRange(1, 20); self.sp_rounds.setValue(3)
        self.sp_themes = _api.QSpinBox(); self.sp_themes.setRange(1, 20); self.sp_themes.setValue(5)
        self.sp_quest = _api.QSpinBox(); self.sp_quest.setRange(1, 20); self.sp_quest.setValue(6)
        for sp in (self.sp_rounds, self.sp_themes, self.sp_quest):
            sp.setMinimumWidth(44)
            sp.valueChanged.connect(self._recount)
        # Подписи текстовых полей стоят над ними. Три счётчика образуют одну
        # ровную строку: подписи сверху, одинаковые поля снизу. Все элементы
        # лежат прямо в сетке группы: вложенная сетка неверно отдавала Qt свою
        # высоту при масштабировании Windows, из-за чего счётчики обрезались, а
        # следующая подпись рисовалась поверх них.
        r = 0
        g.addWidget(self._lab("Название"), r, 0, 1, 3)
        r += 1
        g.addWidget(self.ed_title, r, 0, 1, 3)
        r += 1
        for column, (caption, field) in enumerate((
                ("Раунды", self.sp_rounds),
                ("Темы", self.sp_themes),
                ("Вопросов\nв теме", self.sp_quest))):
            label = self._lab(caption)
            # Явный перенос даёт строке постоянную высоту и убирает
            # heightForWidth, из-за которого Qt мог сжать соседние поля.
            label.setWordWrap(False)
            label.setSizePolicy(
                _api.QSizePolicy.Policy.Ignored,
                _api.QSizePolicy.Policy.Preferred)
            label.setAlignment(_api.Qt.AlignmentFlag.AlignHCenter
                               | _api.Qt.AlignmentFlag.AlignBottom)
            g.addWidget(label, r, column)
            field.setSizePolicy(
                _api.QSizePolicy.Policy.Expanding,
                _api.QSizePolicy.Policy.Fixed)
            g.addWidget(field, r + 1, column)
            g.setColumnStretch(column, 1)
        r += 2
        self.lbl_theme_title = self._lab("Название тем")
        g.addWidget(self.lbl_theme_title, r, 0, 1, 3)
        r += 1
        g.addWidget(self.ed_theme, r, 0, 1, 3)
        r += 1
        self.lbl_total = self._hint("")
        g.addWidget(self.lbl_total, r, 0, 1, 3)
        # Все подписи здесь короткие или имеют явный перенос. Даже одна
        # оставшаяся wordWrap-подпись включает heightForWidth у всей группы:
        # тогда при низком окне Qt снова сжимает счётчики ниже их полной высоты.
        for label in grp.findChildren(_api.QLabel):
            label.setWordWrap(False)
        return grp

    # ── группа «Списки» ───────────────────────────────────────────────────
    def _group_lists(self) -> _api.QGroupBox:
        grp = _api.QGroupBox("Списки")
        v = _api.QVBoxLayout(grp); v.setSpacing(6)
        # Откуда тайтлы: случайные из базы Shikimori (фильтры год/тип/оценка
        # уходят прямо на сервер) или из списков людей. Мастер-лист AMQ убран.
        from .source_switch import SourceSwitch
        self.src_switch = SourceSwitch(_api.C)
        self.src_switch.btn_shiki.setToolTip(
            "Аниме берутся случайной выборкой из каталога Shikimori. Год, тип, "
            "оценка и исключённые жанры фильтруются самим Shikimori.")
        self.src_switch.btn_lists.setToolTip(
            "Аниме берутся из списков добавленных ниже людей на MyAnimeList / "
            "Shikimori / AniList; ник того, у кого тайтл есть, пишется в ответе.")
        self.src_switch.changed.connect(self._on_source_switched)
        v.addWidget(self.src_switch)
        # Каталог Shikimori кэшируется на диск и живёт там, пока его не обновят
        # (просьба пользователя: «один раз собрал — и хранится»). Кнопка тут одна
        # на всю базу: прежние «Обновить базу Shikimori» и «Что в базе…» делали
        # одно дело с разных концов, и обновление шло вслепую одним куском.
        # Теперь она открывает панель, где видно, что в базе лежит, и где каждая
        # её часть обновляется отдельно (просьба пользователя).
        self.btn_refresh_db = _api.QPushButton("Обновить базу")
        self.btn_refresh_db.setIcon(_api.get_icon('fa5s.database'))
        self.btn_refresh_db.setToolTip(
            "Открывает панель базы Shikimori: сколько в ней карточек аниме и "
            "манги, сколько узнаваемых франшиз и что накопилось за генерации, а "
            "заодно таблицы тайтлов и персонажей с их индексом и сложностью.\n"
            "Обновляется база оттуда же и по частям: только аниме, только манга, "
            "только узнаваемость франшиз — или всё подряд, как раньше. Каталог "
            "берётся ЦЕЛИКОМ, сколько бы тайтлов под текущие фильтры (год, типы, "
            "оценка, исключённые жанры) в нём ни было, поэтому идти может долго — "
            "минуты и десятки минут; остановить можно там же, набранное "
            "останется.\n"
            "Сохранённое переживает перезапуск программы: следующая генерация не "
            "тратит на каталог ни одного запроса.")
        self.btn_refresh_db.clicked.connect(self._open_db_table)
        v.addWidget(self.btn_refresh_db)

        self.box_users = _api.SettingsBox()
        uv = _api.QVBoxLayout(self.box_users)
        uv.setContentsMargins(0, 0, 0, 0); uv.setSpacing(6)
        # Строка «Аниме есть хотя бы у N чел.» живёт в своём контейнере.
        self.box_similar = _api.SettingsBox()
        sim_row = _api.QHBoxLayout(self.box_similar); sim_row.setSpacing(6)
        sim_row.setContentsMargins(0, 0, 0, 0)
        # Отдельной галочки «Похожие» больше нет: переключатель стоит на
        # «Из списков пользователя» — пак и так собирается по спискам.
        lab_sim = self._lab("Аниме есть хотя бы у")
        self.sp_similar = _api.QSpinBox(); self.sp_similar.setRange(1, 20)
        self.sp_similar.setValue(2); self.sp_similar.setMinimumWidth(44)
        self.sp_similar.setToolTip(
            "«1» — годится всё, что есть хотя бы у одного человека; «2» и "
            "больше — только тайтлы, которые есть у стольких сразу.")
        sim_row.addWidget(lab_sim, 1)
        sim_row.addWidget(self.sp_similar)
        sim_row.addWidget(self._lab("чел."))
        uv.addWidget(self.box_similar)
        self.box_cards = _api.SettingsBox()
        self.cards_layout = _api.QVBoxLayout(self.box_cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        uv.addWidget(self.box_cards)

        # Доли списков: сколько вопросов пака даёт каждый человек. Без них пак
        # заполнял тот, у кого список длиннее (просьба пользователя).
        self.box_shares = _api.SettingsBox()
        sh = _api.QVBoxLayout(self.box_shares)
        sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(2)
        self.chk_shares = _api.QCheckBox("Делить пак между списками")
        self.chk_shares.setToolTip(
            "Включено — каждый список даёт свою долю вопросов, как на полосе "
            "ниже. У кого 1500 тайтлов, а у кого 300 — неважно: доли считаются "
            "по проценту, а не по длине списка.\n"
            "Выключено — все списки просто складываются, и длинный список "
            "перевешивает остальные.")
        self.chk_shares.toggled.connect(self._on_shares_toggled)
        sh.addWidget(self.chk_shares)
        self.share_bar = _api._ShareBar()
        self.share_bar.setToolTip("Доля вопросов пака у каждого списка.")
        self.share_bar.changed.connect(self._on_share_bar_changed)
        sh.addWidget(self.share_bar)
        uv.addWidget(self.box_shares)
        self.box_shares.setVisible(False)

        btn_row = _api.QHBoxLayout(); btn_row.setSpacing(6)
        self.btn_add_user = _api.QPushButton("Добавить список")
        self.btn_add_user.setIcon(_api.get_icon('fa5s.plus'))
        self.btn_add_user.clicked.connect(lambda: self._add_user_card())
        self.btn_saved_users = _api.QPushButton("Из сохранённых")
        self.btn_saved_users.setIcon(_api.get_icon('fa5s.address-book'))
        self.btn_saved_users.setToolTip(
            "Ники, которые уже участвовали в генерации, запоминаются. Здесь их "
            "можно выбрать галочками и добавить сразу пачкой.")
        self.btn_saved_users.clicked.connect(self._open_saved_users)
        self.btn_clear_users = _api.QPushButton("Очистить")
        self.btn_clear_users.setIcon(_api.get_icon('fa5s.trash'))
        self.btn_clear_users.setToolTip(
            "Убрать все списки разом. Сами ники останутся в сохранённых.")
        self.btn_clear_users.clicked.connect(self._clear_user_cards)
        # Три кнопки в одну строку требовали 587 px: «Списки» переставали влезать
        # в колонку, и настройки схлопывались в одну колонку на всё окно.
        # Поэтому «Добавить список» — отдельной строкой, остальные две под ней.
        uv.addWidget(self.btn_add_user)
        btn_row.addWidget(self.btn_saved_users, 1)
        btn_row.addWidget(self.btn_clear_users, 1)
        uv.addLayout(btn_row)
        v.addWidget(self.box_users)
        self.box_users.setVisible(False)
        return grp

    # ── доли списков ──────────────────────────────────────────────────────
    def _on_shares_toggled(self, checked: bool):
        self.share_bar.setVisible(bool(checked))
        if not checked:
            for card in self._user_cards:
                card.set_share(0)
        else:
            self._refresh_share_bar()
            # Включили дележ — раздаём поровну, дальше двигайте руками.
            keys = self.share_bar.keys()
            if keys:
                self.share_bar.set_values({k: 1 for k in keys})
                self._on_share_bar_changed()
        self._fit_settings_width()

    def _on_share_bar_changed(self):
        """Полосу подвинули — разложили проценты обратно по карточкам."""
        for card in self._user_cards:
            card.set_share(self.share_bar.value_of(self._card_key(card)))

    @staticmethod
    def _share_key(user) -> str:
        """Ключ списка на полосе долей: ник + источник + раздел (у одного
        человека могут быть и аниме-список, и манга-список)."""
        return f"{user.username.strip().casefold()}|{user.source}|{user.target}"

    def _card_key(self, card) -> str:
        return self._share_key(card.value())

    def _refresh_share_bar(self):
        """Пересобирает полосу под текущий набор карточек.

        Хозяин долей — сама полоса: она их и раздаёт карточкам. Обратно, из
        карточек, значения не читаем — иначе доля только что добавленного
        списка (ноль) тут же затирала бы честный дележ из set_parts."""
        bar = getattr(self, "share_bar", None)
        if bar is None:
            return
        parts, seen = [], set()
        for card in self._user_cards:
            key = self._card_key(card)
            if not card.value().username.strip() or key in seen:
                continue
            seen.add(key)
            parts.append((key, card.value().username.strip()))
        random_mode = not self.src_switch.is_lists()
        self.box_shares.setVisible(len(parts) > 1 and not random_mode)
        if not parts:
            return
        bar.set_parts(parts)
        self._on_share_bar_changed()
        self.share_bar.setVisible(self.chk_shares.isChecked())

    # ── обновление базы (запускает панель «Обновить базу») ────────────────
    def _refresh_db(self, parts=None):
        """Собрать заново части базы. parts=None — всю, как прежняя кнопка.

        Повторное нажатие работает на остановку: каталог берётся целиком, а это
        долго — бросить на середине можно в любой момент, набранное всё равно
        сохранится (просьба пользователя)."""
        if self._db_task is not None:
            self._db_task.stop()
            self.btn_refresh_db.setText("Останавливаю базу…")
            self.log("Останавливаю обновление базы — набранное сохранится.")
            return
        if self._task is not None:
            return
        from si_hyx_parts.animepack.db_settings import database_settings
        self._db_parts = _api.db_refresh_parts(parts)
        task = _api._RefreshDbTask(database_settings(), self._db_parts)
        task.signals.log.connect(self.log)
        task.signals.finished.connect(self._on_db_refreshed)
        task.signals.failed.connect(self._on_db_failed)
        self._db_task = task
        self.btn_refresh_db.setText("База обновляется…")
        self.log("Обновляю базу Shikimori "
                 f"({', '.join(_api.DB_PART_NAMES.get(p, p) for p in self._db_parts)}). "
                 "Остановить можно в панели базы — набранное сохранится.")
        self._pool.start(task)

    def _on_db_refreshed(self, count: int):
        report = getattr(getattr(self, "_db_task", None), "report", {})
        partial = report.get("status") in ("PARTIAL", "STOPPED")
        message = f"В базе {count} карточек."
        if partial:
            message += (f" Недоступных счётчиков: {report.get('restricted', 0)}; "
                        f"неизвестных: {report.get('unknown', 0)}.")
        self._finish_db_ui()
        panel = _db_panel(self)
        if panel is not None:
            # Панель открыта и сама показывает свежие числа — окно поверх неё
            # только уводило фокус на главное окно, и панель пряталась за ним
            # (просьба пользователя). Хватит строки в журнале.
            self.log(("Сбор базы завершён с ограничениями. " if partial else "База обновлена. ")
                     + message)
            panel.raise_()
            panel.activateWindow()
            return
        _api.msgbox_information(self, "Сбор базы завершён" if partial else "База обновлена", message)

    def _on_db_failed(self, err: str):
        self._finish_db_ui()
        self.log(f"База Shikimori не обновилась: {err}")
        # Ошибку показываем поверх панели, если она открыта: иначе окно
        # сообщения поднимало главное окно, и панель оказывалась за ним.
        panel = _db_panel(self)
        _api.msgbox_critical(panel or self, "База не обновилась", err)
        if panel is not None:
            panel.raise_()
            panel.activateWindow()

    def _finish_db_ui(self):
        self._db_task = None
        if getattr(self, "_queue", None):
            _api.QTimer.singleShot(0, self._start_next)
        self._db_parts = ()
        self.btn_refresh_db.setEnabled(True)
        self.btn_refresh_db.setIcon(_api.get_icon('fa5s.database'))
        self.btn_refresh_db.setText("Обновить базу")
        # Панель открыта — показать в ней свежие числа и вернуть кнопкам блоков
        # их обычные подписи.
        dialog = getattr(self, "_db_table_dialog", None)
        if dialog is not None:
            try:
                dialog.refresh()
            except Exception:  # noqa: BLE001 — панель могли уже закрыть
                pass

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

        from .song_video_controls import build_controls as build_video
        build_video(self)

        # ── Манга/манхва/ранобэ ──────────────────────────────────────────
        # Без галочки доли манги на ползунке нет вовсе
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
            "Flash думает лучше, но запросов в сутки у него меньше. Gemma 4 — "
            "самые слабые, зато с отдельной большой квотой; рассуждение у них "
            "только «минимальное» или «высокое». Новые "
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
        # «Ваншот» и «Додзинси» — одной строкой в СВОЕЙ ячейке на все колонки.
        # Каждая на паре колонок сетки заставляла QGridLayout сложить их
        # минимум с шириной строки Gemini над ними (359 px вместо 290), и
        # «Состав пака» выталкивал настройки из трёх колонок в две.
        kinds_cell = _api.SettingsBox()
        kinds_row = _api.QHBoxLayout(kinds_cell)
        kinds_row.setContentsMargins(0, 0, 0, 0)
        kinds_row.setSpacing(16)
        for kind in extras:
            chk = _api.QCheckBox(_api.MANGA_KIND_LABELS[kind])
            chk.setChecked(False)
            self.chk_manga_kinds[kind] = chk
            kinds_row.addWidget(chk)
        kinds_row.addStretch(1)
        mg.addWidget(kinds_cell, 4, 0, 1, 4)
        place_manga(self, mg, 5)
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

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget {{ color: {_api.C['text']}; }}
            QTabWidget::pane {{ border: 1px solid {_api.C['border']}; background: {_api.C['bg']}; }}
            QTabBar::tab {{
                background: {_api.C['surface']}; color: {_api.C['text2']};
                padding: 8px 14px;
            }}
            QTabBar::tab:selected {{ background: {_api.C['surface3']}; color: {_api.C['accent']}; }}
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
                background: {_api.C['accent']}; color: #11111b; border: none; font-weight: 700;
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
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QFrame#userCard {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                background: {_api.C['surface2']};
            }}
            /* Внутри карточки списка всё тесное: общие отступы полей и кнопок
               раздували её на треть панели настроек. */
            QFrame#userCard QLineEdit, QFrame#userCard QComboBox {{
                padding: 1px 5px; font-size: 11px;
            }}
            QFrame#userCard QToolButton {{
                padding: 1px 4px; font-size: 11px;
            }}
            /* «♪» — переключатель, и нажатое состояние должно быть ВИДНО:
               без этого правила включённая пометка «в основном музыка» выглядела
               ровно как выключенная, и понять, стоит она или нет, было нельзя. */
            QFrame#userCard QToolButton#musicBtn {{ color: {_api.C['text3']}; }}
            QFrame#userCard QToolButton#musicBtn:checked {{
                background: {_api.C['accent']}; border-color: {_api.C['accent']};
                color: #11111b; font-weight: 700;
            }}
            QFrame#userCard QToolButton#musicBtn:checked:hover {{
                background: {_api.C['accent2']};
            }}
            /* Справа оставляем место под стрелку меню. */
            QFrame#userCard QToolButton#statusBtn {{ padding: 1px 16px 1px 6px; }}
            QTableWidget {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 6px; outline: none;
            }}
            QHeaderView::section {{
                background: {_api.C['surface2']}; color: {_api.C['text2']};
                border: none; padding: 3px 3px; font-size: 11px;
            }}
            /* Стрелка сортировки — маленькая и без своего места: иначе Qt
               резервирует под неё ~20 px в КАЖДОЙ колонке, и «Раунд» с «Ценой»
               выходили вчетверо шире содержимого. */
            QHeaderView::up-arrow, QHeaderView::down-arrow {{
                width: 7px; height: 7px; subcontrol-position: top center;
            }}
            QTableWidget::item:selected {{ background: {_api.C['surface3']}; color: {_api.C['text']}; }}
            QProgressBar {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; text-align: center; color: {_api.C['text']};
            }}
            QProgressBar::chunk {{ background: {_api.C['accent']}; border-radius: 4px; }}
        """)
