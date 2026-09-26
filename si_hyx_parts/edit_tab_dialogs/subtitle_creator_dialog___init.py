# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleCreatorDialog: __init__. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


def __init__(self, source_path=None, cues=None, start_hint=0.0,
             range_start=0.0, range_end=None, ignore_media_duration=False,
             default_style=None, audio_track_index=None, audio_ext_path=None,
             parent=None):
    super(_api.SubtitleCreatorDialog, self).__init__(parent)
    self.setWindowTitle("Создать субтитры")
    self.resize(1060, 700)
    self._source_path = source_path
    self._audio_track_index = audio_track_index
    self._audio_ext_path = audio_ext_path
    # Усечённый (партиальный, «N минут») прокси-источник короче реального
    # диапазона — не даём его длительности перетереть уже известный
    # range_end (см. _on_media_duration), как _proxy_partial в EditTab.
    self._ignore_media_duration = bool(ignore_media_duration)
    # Диапазон видео, выделенный в Монтаже (current_in/current_out) —
    # превью/таймлайн показывают ТОЛЬКО его, а не весь исходник (см.
    # _on_media_duration). Тайминги реплик остаются абсолютными.
    self._range_start = max(0.0, float(range_start))
    self._range_end = float(range_end) if range_end is not None else None
    self._start_hint = max(self._range_start, float(start_hint))
    # default_style — стиль, оставшийся с прошлого раза (шрифт/размер/цвет/…,
    # см. last_style()/EditTab.create_subtitles) — так каждая НОВАЯ реплика
    # по умолчанию наследует то, что пользователь выбирал в прошлый раз, а
    # не жёстко зашитый DEFAULT_SUBTITLE_STYLE.
    self._default_style = dict(default_style) if default_style else dict(_api.DEFAULT_SUBTITLE_STYLE)
    self._cues = []          # [{'start','end','text','style'(override|None)}]
    self._selected = -1
    self._presets = _api._load_subtitle_presets()
    # Undo/redo (Ctrl+Z/Ctrl+Y) — снимки (реплики + общий стиль) перед
    # структурными изменениями (добавить/дублировать/удалить/перетащить
    # блок на таймлайне/применить пресет или стиль ко всем). Правки текста
    # реплики и точечные правки одного поля стиля (спинбоксы/цвет) НЕ
    # снимаются по каждому символу/клику — это создало бы нечитаемую кучу
    # микро-шагов; для текста уже есть встроенный undo самого QPlainTextEdit.
    self._undo_stack = []
    self._redo_stack = []
    # Подавляет запись стилей при программных апдейтах UI. Включено с САМОГО
    # начала: конструирование QFontComboBox само по себе спонтанно шлёт
    # currentFontChanged со своим служебным начальным шрифтом (на некоторых
    # системах — случайный шрифт из загруженных qtawesome-иконок), и без
    # этой защиты он тихо затирал бы self._default_style['font'] ещё ДО
    # того, как появится первая реплика. Снимается позже, в конце __init__,
    # когда виджеты стиля уже засинхронизированы с реальным умолчанием.
    self._syncing = True
    self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QLineEdit, QPlainTextEdit, QSpinBox, QFontComboBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 5px;
                padding: 3px 6px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QFontComboBox:focus {{
                border-color: {_api.C['accent']};
            }}
            QListWidget {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
            }}
            QListWidget::item:selected {{ background: {_api.C['border2']}; }}
            QToolButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 5px;
                font-size: 13px;
            }}
            QToolButton:hover {{ border-color: {_api.C['accent']}; }}
            QToolButton:checked {{
                background: {_api.C['accent']}; color: #11111b; border-color: transparent;
            }}
            QPushButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {_api.C['border2']}; border-color: {_api.C['accent']}; }}
            QTabWidget::pane {{ border: 1px solid {_api.C['border2']}; border-radius: 6px; top: -1px; }}
            /* surface2 (#24273a) почти неотличим от фона диалога (#1e1e2e) —
               с прозрачным QTabBar и таким же прозрачным фоном НЕвыбранных
               вкладок вся полоса вкладок визуально сливалась с фоном, и
               выделялся только один активный «Субтитр», отчего вся строка
               казалась «пустой» вокруг него. Красим саму полосу заливкой —
               теперь она читается ОДНОЙ видимой планкой сразу под тулбаром,
               а не набором текста, плавающего в пустоте. */
            QTabBar {{ background: {_api.C['surface2']}; }}
            QTabBar::tab {{
                background: transparent; color: {_api.C['text2']};
                height: 30px; padding: 0px 8px; margin: 0px; border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{ background: {_api.C['surface3']}; color: {_api.C['text']};
                border-bottom: 2px solid {_api.C['accent']}; }}
            QTabBar::tab:hover {{ color: {_api.C['text']}; }}
            QScrollBar:horizontal {{ background: {_api.C['surface2']}; height: 10px; border-radius: 5px; }}
            QScrollBar::handle:horizontal {{ background: {_api.C['border2']}; border-radius: 5px; min-width: 20px; }}
            QScrollBar::handle:horizontal:hover {{ background: {_api.C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """)

    lay = _api.QVBoxLayout(self)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(4)

    # НАЙДЕНА настоящая причина «пустоты над вкладками»: тулбар стиля текста
    # был ОТДЕЛЬНОЙ строкой на всю ширину диалога, но его виджеты (шрифт/
    # размер/Ж/К/Ч/выравнивание/интервал) собраны только СЛЕВА — правая
    # часть той строки (над колонкой вкладок) была просто addStretch(1),
    # то есть буквально пустая. Над видео тулбар стоит вплотную, а над
    # «Субтитр/Пресет/...» — голый пустой промежуток шириной в тулбар.
    # Кладём тулбар ВНУТРЬ левой колонки (только над превью) — тогда
    # вкладки справа начинаются сразу под заголовком окна, без зазора.
    mid = _api.QHBoxLayout(); mid.setSpacing(10)
    left = _api.QVBoxLayout(); left.setSpacing(4)
    left.addLayout(self._build_toolbar())
    self.preview = _api._SubtitlePreview()
    self.preview.set_active_cue_provider(self._active_cue_at)
    left.addWidget(self.preview, 1)
    mid.addLayout(left, 3)

    self.tabs = _api.QTabWidget()
    self.tabs.addTab(self._build_subtitle_tab(), "Субтитр")
    self.tabs.addTab(self._build_preset_tab(), "Пресет")
    self.tabs.addTab(self._build_settings_tab(), "Настройка")
    self.tabs.addTab(self._build_animation_tab(), "Анимация")
    self.tabs.setDocumentMode(True)
    self.tabs.tabBar().setExpanding(True)
    self.tabs.tabBar().setDocumentMode(True)
    # QSS "height: 30px" на ::tab само по себе не всегда выигрывает у
    # внутреннего расчёта высоты полосы вкладок (стиль может резервировать
    # больше места сверху под собственное оформление «флажка» вкладки,
    # оставляя пустую полосу НАД текстом) — фиксируем РЕАЛЬНУЮ высоту
    # виджета QTabBar явно, чтобы лишнего места просто неоткуда было взяться.
    self.tabs.tabBar().setFixedHeight(30)
    mid.addWidget(self.tabs, 2)
    lay.addLayout(mid, 1)

    # Скроллбар таймлайна — НАД дорожкой реплик (как прокрутка волны в
    # Монтаже — см. wave_scroll/tp_layout в EditTab), не под ней.
    tl_top = _api.QHBoxLayout(); tl_top.setSpacing(6)
    self.tl_scroll = _api.QScrollBar(_api.Qt.Orientation.Horizontal)
    self.tl_scroll.setRange(0, 1000)
    # Видна только когда таймлайн увеличен и есть что прокручивать — как
    # wave_scroll в основном Монтаже (EditTab.tp_layout), не просто disabled.
    self.tl_scroll.setVisible(False)
    self.tl_scroll.setStyleSheet(f"""
            QScrollBar:horizontal {{ background: {_api.C['surface2']}; height: 12px;
                border-radius: 6px; margin: 0; }}
            QScrollBar::handle:horizontal {{ background: {_api.C['border2']};
                border-radius: 5px; min-width: 28px; }}
            QScrollBar::handle:horizontal:hover {{ background: {_api.C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
        """)
    tl_top.addWidget(self.tl_scroll, 1)
    lay.addLayout(tl_top)

    self.timeline = _api._SubtitleTimeline()
    self.timeline.setFixedHeight(90)
    lay.addWidget(self.timeline)

    bottom = _api.QHBoxLayout(); bottom.setSpacing(8)
    btn_save_preset = _api.QPushButton("Сохранить как пресет")
    btn_save_preset.clicked.connect(self._save_as_preset)
    btn_apply_all = _api.QPushButton("Применить ко всем")
    btn_apply_all.clicked.connect(self._apply_style_to_all)
    bottom.addWidget(btn_save_preset)
    bottom.addWidget(btn_apply_all)
    bottom.addStretch(1)
    bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Save
                          | _api.QDialogButtonBox.StandardButton.Cancel)
    btn_save = bb.button(_api.QDialogButtonBox.StandardButton.Save)
    btn_cancel = bb.button(_api.QDialogButtonBox.StandardButton.Cancel)
    btn_save.setText("Сохранить")
    btn_cancel.setText("Отменить")
    btn_save.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    btn_cancel.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    btn_save.setStyleSheet(f"""
            QPushButton {{ background: {_api.C['green']}; color: #11111b; border: none;
                border-radius: 6px; padding: 6px 16px; font-weight: 600; }}
            QPushButton:hover {{ background: {_api.C['green2']}; }}
        """)
    btn_cancel.setStyleSheet(f"""
            QPushButton {{ background: {_api.C['red']}; color: #11111b; border: none;
                border-radius: 6px; padding: 6px 16px; font-weight: 600; }}
            QPushButton:hover {{ background: {_api.C['red2']}; }}
        """)
    bb.accepted.connect(self._on_accept)
    bb.rejected.connect(self.reject)
    bottom.addWidget(bb)
    lay.addLayout(bottom)

    self.timeline.seekRequested.connect(self.preview.seek)
    self.timeline.cueChanged.connect(self._on_timeline_cue_changed)
    self.timeline.cueSelected.connect(self._select_cue)
    self.timeline.viewChanged.connect(self._on_timeline_view_changed)
    self.timeline.interactionStarted.connect(self._push_undo)
    self.tl_scroll.valueChanged.connect(self._on_tl_scroll_changed)
    self.preview.positionChanged.connect(self.timeline.set_playhead)
    self.preview.durationChanged.connect(self._on_media_duration)
    # Диапазон уже известен из выделения в Монтаже (range_start/range_end) —
    # таймлайн не обязан ждать сигнала о полной длительности файла, так
    # видно сразу; durationChanged потом (см. _on_media_duration) уточнит
    # верхнюю границу, если она не была передана явно, И выполнит
    # первичный seek на start_hint (ТОЛЬКО там — раньше нельзя, см. ниже).
    self.timeline.set_range(self._range_start, self._range_end
                             if self._range_end is not None
                             else self._range_start + 0.001)

    if source_path:
        # Дорожка звука превью — та же, что выбрана в Монтаже (не дефолтная
        # первая дорожка файла) — см. EditTab.create_subtitles.
        self.preview.set_audio_selection(self._audio_track_index, self._audio_ext_path)
        self.preview.load(source_path)
        self.preview.set_range(self._range_start, self._range_end)
    if cues:
        for c in cues:
            self._cues.append({'start': float(c[0]), 'end': float(c[1]),
                               'text': str(c[2]), 'style': None})
        self._resync_all()
    else:
        self._add_cue()

    self._register_shortcuts()
    # Без этого Qt отдаёт начальный фокус первому виджету в layout'е —
    # QFontComboBox, а тот сам глотает пробел как ввод текста в поле
    # фильтра шрифтов раньше, чем событие дойдёт до глобального шортката
    # Space (toggle_play). Отдаём фокус холсту превью — там пробел никак
    # не перехватывается и сразу срабатывает воспроизведение/пауза.
    self.preview.canvas.setFocus(_api.Qt.FocusReason.OtherFocusReason)

# ── Клавиатура: пробел/стрелки — как в основном плеере, но ТОЛЬКО когда
# фокус не в поле ввода текста (иначе пробел должен печататься в реплике) ──
def _register_shortcuts(self):
    # WindowShortcut: срабатывает, пока активно окно диалога, независимо от
    # того, какой именно дочерний виджет внутри держит фокус (video-канвас,
    # список реплик, спинбоксы) — в отличие от WidgetWithChildrenShortcut,
    # не важна принадлежность фокуса конкретному поддереву. Текстовые поля
    # (QPlainTextEdit/QLineEdit) сами перехватывают пробел как ввод текста
    # раньше, чем до них доходит сочетание (Qt ShortcutOverride) — конфликта
    # с набором текста реплики нет.
    def add(seq, handler):
        sc = _api.QShortcut(_api.QKeySequence(seq), self)
        sc.setContext(_api.Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(handler)
        return sc
    self._sc_space = add(_api.Qt.Key.Key_Space, self.preview.toggle_play)
    self._sc_left = add(_api.Qt.Key.Key_Left, self.btn_step_back_click)
    self._sc_right = add(_api.Qt.Key.Key_Right, self.btn_step_fwd_click)

def btn_step_back_click(self):
    self.preview.btn_step_back.click()

def btn_step_fwd_click(self):
    self.preview.btn_step_fwd.click()
