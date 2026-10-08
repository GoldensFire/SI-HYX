# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleCreatorDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


class SubtitleCreatorDialog(_api.QDialog):
    """Создание субтитров с нуля — интерфейс в духе Filmora: тулбар стиля текста
    сверху, слева живое превью с транспортом, справа вкладки Субтитр/Пресет/
    Настройка/Анимация, снизу таймлайн с перетаскиваемыми блоками реплик.

    Стиль/позиция/анимация хранятся ПО РЕПЛИКЕ (self._cues[i]['style']) поверх
    общего стиля по умолчанию (self._default_style) — см. _effective_style.
    Правка тулбара/вкладок пишет в стиль ВЫБРАННОЙ реплики, а если ничего не
    выбрано — в общий стиль по умолчанию; «Применить ко всем» копирует
    эффективный стиль текущей реплики на все остальные."""

    _POS_LABELS = {
        7: "↖", 8: "↑", 9: "↗",
        4: "←", 5: "•", 6: "→",
        1: "↙", 2: "↓", 3: "↘",
    }
    _ANIM_CHOICES = [
        ('none', 'Без анимации'),
        ('fade', 'Появление (fade)'),
        ('slide', 'Выезд (slide)'),
        ('pop', 'Всплытие (pop)'),
    ]

    def __init__(self, source_path=None, cues=None, start_hint=0.0,
                 range_start=0.0, range_end=None, ignore_media_duration=False,
                 default_style=None, audio_track_index=None, audio_ext_path=None,
                 parent=None):
        super().__init__(parent)
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

    # ── Undo/redo (Ctrl+Z/Ctrl+Y, ЛЮБАЯ раскладка клавиатуры) ────────────────
    # QKeySequence/QShortcut сопоставляют события по УЖЕ переведённому раскладкой
    # Qt-коду клавиши: на кириллице физическая Z даёт Qt-код кириллической «Я», а
    # не Key_Z, и никакой QKeySequence("Ctrl+Я")-строкой это надёжно не ловится
    # (что и подтвердил повторный баг-репорт — QKeySequence-подход в Монтаже был
    # исправлен только для латиницы). Настоящее решение — как WASD-пан в photo-
    # редакторе (tabs.py, _pan_dir_from_event): читать ФИЗИЧЕСКУЮ клавишу через
    # nativeVirtualKey (Windows VK_Z=0x5A, VK_Y=0x59), это не зависит от раскладки.
    # Событие сюда доходит только если фокусный виджет его НЕ обработал сам —
    # у QPlainTextEdit/QLineEdit есть свой Ctrl+Z для текста, и они событие
    # поглощают раньше, так что предпочтение отдаётся штатному текстовому undo.
    _VK_Z = 0x5A
    _VK_Y = 0x59
    _VK_W = 0x57
    _VK_A = 0x41
    _VK_S = 0x53
    _VK_D = 0x44

    def keyPressEvent(self, event):
        if event.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            is_z = vk == self._VK_Z or event.key() == _api.Qt.Key.Key_Z
            is_y = vk == self._VK_Y or event.key() == _api.Qt.Key.Key_Y
            if is_z:
                self.redo() if (event.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier) else self.undo()
                event.accept()
                return
            if is_y:
                self.redo()
                event.accept()
                return
        elif not (event.modifiers() & (_api.Qt.KeyboardModifier.AltModifier
                                        | _api.Qt.KeyboardModifier.ShiftModifier)):
            # WASD покадрового шага (та же логика, что и в основном Монтаже —
            # см. EditTab.keyPressEvent): по физической клавише через
            # nativeVirtualKey, с фолбэком на event.key() для латиницы.
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk in (self._VK_A, self._VK_S) or event.key() in (_api.Qt.Key.Key_A, _api.Qt.Key.Key_S):
                self.btn_step_back_click()
                event.accept()
                return
            if vk in (self._VK_D, self._VK_W) or event.key() in (_api.Qt.Key.Key_D, _api.Qt.Key.Key_W):
                self.btn_step_fwd_click()
                event.accept()
                return
        super().keyPressEvent(event)

    def _snapshot(self):
        return (_api.copy.deepcopy(self._cues), dict(self._default_style))

    def _push_undo(self):
        snap = self._snapshot()
        if self._undo_stack and self._undo_stack[-1] == snap:
            return
        self._undo_stack.append(snap)
        self._redo_stack.clear()

    def _restore_snapshot(self, snap):
        self._cues, self._default_style = _api.copy.deepcopy(snap[0]), dict(snap[1])
        if self._selected >= len(self._cues):
            self._selected = len(self._cues) - 1
        self._resync_all()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())

    # ── Тулбар стиля текста ──────────────────────────────────────────────────
    # Все элементы тулбара — ОДНОЙ высоты (_TOOLBAR_H), иначе QFontComboBox/
    # QSpinBox (высокие по natural sizeHint из-за padding в QSS) и QToolButton
    # (раньше был ниже, 24px) выстраивались по верхнему краю неровно.
    _TOOLBAR_H = 28

    def _build_toolbar(self):
        h = self._TOOLBAR_H
        bar = _api.QHBoxLayout(); bar.setSpacing(6)
        bar.setAlignment(_api.Qt.AlignmentFlag.AlignVCenter)
        self.cmb_font = _api.QFontComboBox(); self.cmb_font.setFixedSize(150, h)
        self.cmb_font.currentFontChanged.connect(self._on_font_changed)
        bar.addWidget(self.cmb_font)
        self.spin_size = _api.QSpinBox(); self.spin_size.setRange(6, 200); self.spin_size.setFixedSize(60, h)
        self.spin_size.valueChanged.connect(lambda v: self._style_edit('size', v))
        bar.addWidget(self.spin_size)
        bar.addSpacing(4)
        self.btn_bold = _api.QToolButton(); self.btn_bold.setIcon(_api.get_icon('fa5s.bold'))
        self.btn_italic = _api.QToolButton(); self.btn_italic.setIcon(_api.get_icon('fa5s.italic'))
        self.btn_underline = _api.QToolButton(); self.btn_underline.setIcon(_api.get_icon('fa5s.underline'))
        self.btn_bold.toggled.connect(lambda v: self._style_edit('bold', v))
        self.btn_italic.toggled.connect(lambda v: self._style_edit('italic', v))
        self.btn_underline.toggled.connect(lambda v: self._style_edit('underline', v))
        for b in (self.btn_bold, self.btn_italic, self.btn_underline):
            b.setCheckable(True); b.setFixedSize(h, h)
            b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            bar.addWidget(b)
        bar.addSpacing(6)
        self._halign_btns = {}
        for col, icon_name in ((0, 'fa5s.align-left'), (1, 'fa5s.align-center'),
                               (2, 'fa5s.align-right')):
            b = _api.QToolButton(); b.setIcon(_api.get_icon(icon_name)); b.setCheckable(True)
            b.setFixedSize(h, h); b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(_api.partial(self._on_halign_clicked, col))
            bar.addWidget(b)
            self._halign_btns[col] = b
        bar.addSpacing(6)
        lbl_spacing = _api.QLabel("Интервал:"); lbl_spacing.setFixedHeight(h)
        lbl_spacing.setAlignment(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft)
        bar.addWidget(lbl_spacing)
        self.spin_spacing = _api.QSpinBox(); self.spin_spacing.setRange(-20, 60)
        self.spin_spacing.setFixedSize(55, h)
        self.spin_spacing.valueChanged.connect(lambda v: self._style_edit('spacing', v))
        bar.addWidget(self.spin_spacing)
        bar.addStretch(1)
        return bar

    def _on_media_duration(self, dur_s):
        """Уточняет верхнюю границу диапазона по реальной длительности файла
        (durationChanged превью), если конец диапазона не был передан явно —
        сам диапазон всегда равен обрезке, выделенной в Монтаже, не всему видео."""
        end = self._range_end
        if end is None:
            end = dur_s if dur_s > 0 else self._range_start + 0.001
        elif dur_s > 0 and not self._ignore_media_duration:
            end = min(end, dur_s)
        self.timeline.set_range(self._range_start, end)
        # Сикать на start_hint можно только ПОСЛЕ того, как плеер реально узнал
        # длительность/метаданные файла — QMediaPlayer.setPosition(), вызванный
        # раньше (сразу после setSource), молча сбрасывался бы обратно на 0,
        # когда асинхронная загрузка домета завершится (баг «превью открывается
        # с начала видео, а не с выделенного диапазона»).
        if dur_s > 0 and not getattr(self, '_did_initial_seek', False):
            self._did_initial_seek = True
            self.preview.set_range(self._range_start, end)
            self.preview.seek(self._start_hint)

    def _on_font_changed(self, qfont):
        self._style_edit('font', qfont.family())

    def _on_halign_clicked(self, col):
        if self._syncing:
            return
        style = self._effective_style(self._selected)
        row = (int(style.get('align') or 2) - 1) // 3
        self._style_edit('align', row * 3 + col + 1)
        self._refresh_all_style_ui()

    # ── Вкладка «Субтитр» — список реплик с поиском ─────────────────────────
    def _build_subtitle_tab(self):
        w = _api.QWidget(); lay = _api.QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)
        self.search_box = _api.QLineEdit()
        self.search_box.setPlaceholderText("Введите содержимое для поиска")
        self.search_box.textChanged.connect(lambda _t: self._rebuild_list())
        lay.addWidget(self.search_box)
        self.list_cues = _api.QListWidget()
        self.list_cues.currentItemChanged.connect(self._on_list_current_changed)
        lay.addWidget(self.list_cues, 1)
        row = _api.QHBoxLayout(); row.setSpacing(6)
        btn_add = _api.QPushButton("+ Добавить реплику")
        btn_add.clicked.connect(self._add_cue)
        row.addWidget(btn_add); row.addStretch(1)
        lay.addLayout(row)
        return w

    def _rebuild_list(self):
        self._syncing = True
        try:
            self.list_cues.clear()
            filt = self.search_box.text().strip().lower()
            for i, c in enumerate(self._cues):
                if filt and filt not in c['text'].lower():
                    continue
                item = _api.QListWidgetItem()
                row_w = self._build_row_widget(i, c)
                item.setSizeHint(row_w.sizeHint())
                item.setData(_api.Qt.ItemDataRole.UserRole, i)
                self.list_cues.addItem(item)
                self.list_cues.setItemWidget(item, row_w)
                if i == self._selected:
                    self.list_cues.setCurrentItem(item)
        finally:
            self._syncing = False

    def _build_row_widget(self, idx, cue):
        w = _api.QWidget()
        row = _api.QHBoxLayout(w); row.setContentsMargins(6, 4, 6, 4); row.setSpacing(6)
        lbl_time = _api.QLabel(f"{_api.s_to_time(cue['start'])[:8]}\n{_api.s_to_time(cue['end'])[:8]}")
        lbl_time.setStyleSheet(f"color: {_api.C['text3']}; font-size: 10px;")
        lbl_time.setFixedWidth(56)
        row.addWidget(lbl_time)
        txt = _api.QPlainTextEdit(cue['text'])
        txt.setFixedHeight(44)
        txt.textChanged.connect(_api.partial(self._on_row_text_changed, txt, idx))
        orig_focus_in = txt.focusInEvent

        def _on_focus(ev, _orig=orig_focus_in, _i=idx):
            _orig(ev)
            self._select_cue(_i)
        txt.focusInEvent = _on_focus
        row.addWidget(txt, 1)
        btn_dup = _api.QPushButton(); btn_dup.setIcon(_api.get_icon('fa5s.copy')); btn_dup.setFixedSize(24, 24)
        btn_dup.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_dup.setToolTip("Дублировать реплику")
        btn_dup.clicked.connect(_api.partial(self._duplicate_cue, idx))
        btn_del = _api.QPushButton(); btn_del.setIcon(_api.get_icon('fa5s.trash-alt')); btn_del.setFixedSize(24, 24)
        btn_del.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_del.setToolTip("Удалить реплику")
        btn_del.clicked.connect(_api.partial(self._delete_cue, idx))
        row.addWidget(btn_dup); row.addWidget(btn_del)
        return w

    def _on_row_text_changed(self, txt_widget, idx):
        if self._syncing or not (0 <= idx < len(self._cues)):
            return
        self._cues[idx]['text'] = txt_widget.toPlainText()

    def _on_list_current_changed(self, cur, _prev):
        if cur is None or self._syncing:
            return
        idx = cur.data(_api.Qt.ItemDataRole.UserRole)
        if idx is not None:
            self._select_cue(idx)

    # ── Вкладка «Пресет» ─────────────────────────────────────────────────────
    def _build_preset_tab(self):
        w = _api.QWidget(); lay = _api.QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)
        self.list_presets = _api.QListWidget()
        lay.addWidget(self.list_presets, 1)
        row = _api.QHBoxLayout(); row.setSpacing(6)
        btn_apply = _api.QPushButton("Применить"); btn_apply.clicked.connect(self._apply_selected_preset)
        btn_del = _api.QPushButton("Удалить"); btn_del.clicked.connect(self._delete_selected_preset)
        row.addWidget(btn_apply); row.addWidget(btn_del)
        lay.addLayout(row)
        self._refresh_preset_list()
        return w

    def _refresh_preset_list(self):
        self.list_presets.clear()
        for name in sorted(self._presets.keys()):
            self.list_presets.addItem(name)

    def _save_as_preset(self):
        name, ok = _api.QInputDialog.getText(self, "Сохранить пресет", "Название пресета:")
        name = (name or "").strip()
        if not ok or not name:
            return
        self._presets[name] = self._effective_style(self._selected)
        _api._save_subtitle_presets(self._presets)
        self._refresh_preset_list()

    def _apply_selected_preset(self):
        item = self.list_presets.currentItem()
        if item is None:
            return
        style = self._presets.get(item.text())
        if not style:
            return
        self._push_undo()
        if 0 <= self._selected < len(self._cues):
            self._cues[self._selected]['style'] = dict(style)
        else:
            self._default_style = dict(style)
        self._refresh_all_style_ui()

    def _delete_selected_preset(self):
        item = self.list_presets.currentItem()
        if item is None:
            return
        self._presets.pop(item.text(), None)
        _api._save_subtitle_presets(self._presets)
        self._refresh_preset_list()

    # ── Вкладка «Настройка» — позиция + цвета ────────────────────────────────
    def _build_settings_tab(self):
        w = _api.QWidget(); lay = _api.QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(12)
        lay.addWidget(_api.QLabel("Позиция на видео:"))
        grid = _api.QGridLayout(); grid.setSpacing(4)
        self._pos_btns = {}
        for r, prow in enumerate(([7, 8, 9], [4, 5, 6], [1, 2, 3])):
            for c, val in enumerate(prow):
                b = _api.QToolButton(); b.setText(self._POS_LABELS[val]); b.setCheckable(True)
                b.setFixedSize(30, 26); b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(_api.partial(self._pick_pos, val))
                grid.addWidget(b, r, c)
                self._pos_btns[val] = b
        grid_wrap = _api.QHBoxLayout(); grid_wrap.addLayout(grid); grid_wrap.addStretch(1)
        lay.addLayout(grid_wrap)

        lay.addWidget(_api.make_divider())
        color_row = _api.QHBoxLayout(); color_row.setSpacing(8)
        color_row.addWidget(_api.QLabel("Цвет текста:"))
        self.btn_color = self._make_color_btn('#FFFFFF')
        self.btn_color.clicked.connect(self._pick_text_color)
        color_row.addWidget(self.btn_color)
        color_row.addSpacing(16)
        color_row.addWidget(_api.QLabel("Цвет обводки:"))
        self.btn_outline_color = self._make_color_btn('#000000')
        self.btn_outline_color.clicked.connect(self._pick_outline_color)
        color_row.addWidget(self.btn_outline_color)
        color_row.addStretch(1)
        lay.addLayout(color_row)
        lay.addStretch(1)
        return w

    def _pick_pos(self, val):
        if self._syncing:
            return
        self._style_edit('align', val)
        self._refresh_all_style_ui()

    @staticmethod
    def _make_color_btn(initial):
        b = _api.QPushButton(); b.setFixedSize(28, 22)
        b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        _api.SubtitleCreatorDialog._set_color_swatch(b, initial)
        return b

    @staticmethod
    def _set_color_swatch(btn, hex_color):
        btn.setStyleSheet(
            f"QPushButton {{ background: {hex_color}; border: 1px solid {_api.C['border2']}; "
            f"border-radius: 4px; }}")

    def _pick_text_color(self):
        style = self._effective_style(self._selected)
        col = _api.QColorDialog.getColor(_api.QColor(style.get('color') or '#FFFFFF'), self, "Цвет текста")
        if col.isValid():
            self._style_edit('color', col.name())
            self._set_color_swatch(self.btn_color, col.name())

    def _pick_outline_color(self):
        style = self._effective_style(self._selected)
        col = _api.QColorDialog.getColor(_api.QColor(style.get('outline_color') or '#000000'),
                                    self, "Цвет обводки")
        if col.isValid():
            self._style_edit('outline_color', col.name())
            self._set_color_swatch(self.btn_outline_color, col.name())

    # ── Вкладка «Анимация» ───────────────────────────────────────────────────
    def _build_animation_tab(self):
        w = _api.QWidget(); lay = _api.QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)
        info = _api.QLabel("Анимация появления/исчезновения — для выбранной реплики, "
                       "либо для всех новых, если ничего не выбрано:")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.list_anim = _api.QListWidget()
        for key, label in self._ANIM_CHOICES:
            it = _api.QListWidgetItem(label)
            it.setData(_api.Qt.ItemDataRole.UserRole, key)
            self.list_anim.addItem(it)
        self.list_anim.currentItemChanged.connect(self._on_anim_changed)
        lay.addWidget(self.list_anim, 1)
        return w

    def _on_anim_changed(self, cur, _prev):
        if cur is None or self._syncing:
            return
        self._style_edit('animation', cur.data(_api.Qt.ItemDataRole.UserRole))

    # ── Модель стилей (переопределение реплики поверх общего по умолчанию) ──
    def _effective_style(self, idx):
        base = dict(self._default_style)
        if 0 <= idx < len(self._cues):
            ov = self._cues[idx].get('style')
            if ov:
                base.update(ov)
        return base

    def _style_edit(self, key, value):
        if self._syncing:
            return
        if 0 <= self._selected < len(self._cues):
            cue = self._cues[self._selected]
            if cue.get('style') is None:
                cue['style'] = {}
            cue['style'][key] = value
        else:
            self._default_style[key] = value

    def _apply_style_to_all(self):
        self._push_undo()
        style = self._effective_style(self._selected)
        self._default_style = dict(style)
        for c in self._cues:
            c['style'] = dict(style)
        self._refresh_all_style_ui()

    def _refresh_all_style_ui(self):
        style = self._effective_style(self._selected)
        self._syncing = True
        try:
            self.cmb_font.setCurrentFont(_api.QFont(style.get('font') or 'Arial'))
            self.spin_size.setValue(int(style.get('size') or 20))
            self.btn_bold.setChecked(bool(style.get('bold')))
            self.btn_italic.setChecked(bool(style.get('italic')))
            self.btn_underline.setChecked(bool(style.get('underline')))
            align = int(style.get('align') or 2)
            col = (align - 1) % 3
            for c, b in self._halign_btns.items():
                b.setChecked(c == col)
            self.spin_spacing.setValue(int(style.get('spacing') or 0))
            for v, b in self._pos_btns.items():
                b.setChecked(v == align)
            self._set_color_swatch(self.btn_color, style.get('color') or '#FFFFFF')
            self._set_color_swatch(self.btn_outline_color,
                                   style.get('outline_color') or '#000000')
            anim = style.get('animation') or 'none'
            for i in range(self.list_anim.count()):
                it = self.list_anim.item(i)
                if it.data(_api.Qt.ItemDataRole.UserRole) == anim:
                    self.list_anim.setCurrentItem(it)
                    break
        finally:
            self._syncing = False

    # ── Реплики: добавление/дублирование/удаление/выбор ─────────────────────
    def _add_cue(self):
        self._push_undo()
        start = self._cues[-1]['end'] if self._cues else self._start_hint
        self._cues.append({'start': start, 'end': start + 2.0, 'text': '', 'style': None})
        self._resync_all()
        self._select_cue(len(self._cues) - 1)

    def _duplicate_cue(self, idx):
        if not (0 <= idx < len(self._cues)):
            return
        self._push_undo()
        src = self._cues[idx]
        dur = max(0.1, src['end'] - src['start'])
        lo = src['end']
        range_end = self._range_end if self._range_end is not None else self.preview.duration_s
        hi = (self._cues[idx + 1]['start'] if idx + 1 < len(self._cues)
              else max(lo + dur, range_end or (lo + dur)))
        new_end = min(hi, lo + dur)
        if new_end <= lo:
            new_end = lo + 0.1
        new_cue = {'start': lo, 'end': new_end, 'text': src['text'],
                  'style': dict(src['style']) if src.get('style') else None}
        self._cues.insert(idx + 1, new_cue)
        self._resync_all()
        self._select_cue(idx + 1)

    def _delete_cue(self, idx):
        if not (0 <= idx < len(self._cues)):
            return
        self._push_undo()
        del self._cues[idx]
        if self._selected == idx:
            self._selected = -1
        elif self._selected > idx:
            self._selected -= 1
        self._resync_all()

    def _select_cue(self, idx):
        if idx == self._selected:
            return
        self._selected = idx
        self.timeline.set_selected(idx)
        if 0 <= idx < len(self._cues):
            self.preview.seek(self._cues[idx]['start'])
        self._refresh_all_style_ui()
        for i in range(self.list_cues.count()):
            item = self.list_cues.item(i)
            if item.data(_api.Qt.ItemDataRole.UserRole) == idx:
                self._syncing = True
                self.list_cues.setCurrentItem(item)
                self._syncing = False
                break

    def _resync_all(self):
        self.timeline.set_cues([(c['start'], c['end']) for c in self._cues])
        self.timeline.set_selected(self._selected)
        self._rebuild_list()
        self._refresh_all_style_ui()

    def _on_timeline_cue_changed(self, idx, start, end):
        if not (0 <= idx < len(self._cues)):
            return
        self._cues[idx]['start'] = start
        self._cues[idx]['end'] = end
        for i in range(self.list_cues.count()):
            item = self.list_cues.item(i)
            if item.data(_api.Qt.ItemDataRole.UserRole) == idx:
                row_w = self.list_cues.itemWidget(item)
                lbl = row_w.findChild(_api.QLabel)
                if lbl is not None:
                    lbl.setText(f"{_api.s_to_time(start)[:8]}\n{_api.s_to_time(end)[:8]}")
                break

    def _on_timeline_view_changed(self, offset, visible):
        # Как update_wave_scroll в основном Монтаже: скроллбар СКРЫВАЕТСЯ
        # (не просто disabled), когда прокручивать нечего.
        dur = self.timeline.duration
        if dur <= visible:
            self.tl_scroll.setVisible(False)
            return
        self.tl_scroll.setVisible(True)
        maxv = max(1.0, dur - visible)
        rel_offset = offset - self.timeline.range_start
        self.tl_scroll.blockSignals(True)
        self.tl_scroll.setPageStep(max(1, int(visible / dur * 1000)))
        self.tl_scroll.setValue(int(max(0.0, min(1.0, rel_offset / maxv)) * 1000))
        self.tl_scroll.blockSignals(False)

    def _on_tl_scroll_changed(self, v):
        dur = self.timeline.duration
        visible = self.timeline._visible()
        maxv = max(0.0, dur - visible)
        self.timeline.set_view_offset(self.timeline.range_start + v / 1000.0 * maxv)

    # ── Превью: активная реплика под плейхедом ──────────────────────────────
    def _active_cue_at(self, pos_s):
        for i, c in enumerate(self._cues):
            if c['start'] <= pos_s < c['end']:
                return c['text'], self._effective_style(i)
        return None

    # ── Итог ─────────────────────────────────────────────────────────────────
    def _on_accept(self):
        if not self.cues():
            _api.msgbox_warning(self, "Субтитры", "Добавьте хотя бы одну реплику с текстом.")
            return
        self.accept()

    def last_style(self):
        """Эффективный стиль на момент закрытия — то, что последним стояло в
        тулбаре (стиль выбранной реплики, либо общий стиль по умолчанию, если
        ничего не выбрано). Вызывающая сторона (EditTab.create_subtitles)
        сохраняет это как «последние настройки сабов» для следующего открытия."""
        if 0 <= self._selected < len(self._cues):
            return self._effective_style(self._selected)
        return dict(self._default_style)

    def cues(self):
        """Список словарей {start,end,text,style} с уже разрешённым (эффективным)
        стилем — только непустые реплики, start < end. Передаётся в _cues_to_ass."""
        out = []
        for i, c in enumerate(self._cues):
            text = (c.get('text') or '').strip()
            if not text or c['end'] <= c['start']:
                continue
            out.append({'start': c['start'], 'end': c['end'], 'text': text,
                       'style': self._effective_style(i)})
        out.sort(key=lambda c: c['start'])
        return out


SubtitleCreatorDialog.__module__ = _api.__name__
_api.SubtitleCreatorDialog = SubtitleCreatorDialog
