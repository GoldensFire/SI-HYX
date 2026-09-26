# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _build_player_bar. Public namespace: edit_tab."""
import edit_tab as _api


def _build_player_bar(self, center):
    """Панель плеера под видео: play/pause, время, громкость, покадровый шаг."""
    # ── Player bar (прямо под видео) ──────────────────────────────────
    # Компактный плеер как в обычном видеоплеере: полоса воспроизведения,
    # тайминги (текущее/общее), кнопки и громкость — всё под самим видео.
    player_bar = _api.QFrame()
    player_bar.setObjectName("PlayerBar")
    player_bar.setStyleSheet(f"#PlayerBar {{ background: {_api.C['surface']}; border-top: 1px solid {_api.C['border']}; }}")
    pb_layout = _api.QVBoxLayout(player_bar)
    pb_layout.setContentsMargins(12, 6, 12, 7)
    pb_layout.setSpacing(6)

    # Верхняя строка: полоса воспроизведения + тайминги (текущее / общее)
    seek_row = _api.QHBoxLayout()
    seek_row.setContentsMargins(0, 0, 0, 0)
    seek_row.setSpacing(10)

    self.slider = _api.SeekSlider(_api.Qt.Orientation.Horizontal)
    self.slider.setRange(0, 1000)
    self.slider.sliderMoved.connect(self.on_slider_moved)
    self.slider.setStyleSheet(self._slider_style(_api.C["playhead"]))
    # Превью кадров при наведении на полосу (как на YouTube). Один контроллер
    # на обе полосы — в окне и в полноэкранном режиме (см. FullscreenVideo).
    self.seek_preview = _api.SeekPreview(lambda: getattr(self, "duration", 0.0) or 0.0)
    self.slider.attach_preview(self.seek_preview)
    seek_row.addWidget(self.slider, 1)

    time_frame = _api.QFrame()
    time_frame.setStyleSheet(f"""
            background: {_api.C['bg']};
            border: 1px solid {_api.C['border']};
            border-radius: 6px;
        """)
    time_fl = _api.QHBoxLayout(time_frame)
    time_fl.setContentsMargins(8, 3, 8, 3)
    time_fl.setSpacing(3)
    _mono = _api.QFont("Courier New" if _api.os.name == 'nt' else "Courier")
    _mono.setBold(True); _mono.setPointSize(11)
    self.lbl_current_time = _api.QLabel("00:00:00.000")
    self.lbl_current_time.setFont(_mono)
    self.lbl_current_time.setStyleSheet(f"color: {_api.C['green2']}; background: transparent;")
    sep_time = _api.QLabel("/")
    sep_time.setStyleSheet(f"color: {_api.C['text3']}; background: transparent;")
    self.lbl_total_time = _api.QLabel("00:00:00.000")
    self.lbl_total_time.setFont(_mono)
    self.lbl_total_time.setStyleSheet(f"color: {_api.C['text3']}; background: transparent;")
    time_fl.addWidget(self.lbl_current_time)
    time_fl.addWidget(sep_time)
    time_fl.addWidget(self.lbl_total_time)
    seek_row.addWidget(time_frame)
    pb_layout.addLayout(seek_row)

    # Нижняя строка: кнопки управления + громкость
    pctrl_row = _api.QHBoxLayout()
    pctrl_row.setContentsMargins(0, 0, 0, 0)
    pctrl_row.setSpacing(6)

    # Кнопки плеера — только иконки, без подписей (квадратные).
    self.btn_stop = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaStop)
    self.btn_stop.setFixedWidth(40)
    self.btn_stop.setToolTip("Стоп — к началу зоны")
    self.btn_stop.clicked.connect(self.stop_playback)
    pctrl_row.addWidget(self.btn_stop)

    self.btn_step_back = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekBackward)
    self.btn_step_back.setFixedWidth(40)
    self.btn_step_back.setToolTip("Кадр назад (←)")
    self.btn_step_back.clicked.connect(_api.partial(self.step_frame_scrub, -1))
    pctrl_row.addWidget(self.btn_step_back)

    self.btn_play = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaPlay, accent=True)
    self.btn_play.setFixedWidth(48)
    self.btn_play.setToolTip("Воспроизвести / пауза (Пробел)")
    self.btn_play.clicked.connect(self.toggle_play)
    pctrl_row.addWidget(self.btn_play)

    self.btn_step_fwd = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekForward)
    self.btn_step_fwd.setFixedWidth(40)
    self.btn_step_fwd.setToolTip("Кадр вперёд (→)")
    self.btn_step_fwd.clicked.connect(_api.partial(self.step_frame_scrub, 1))
    pctrl_row.addWidget(self.btn_step_fwd)

    self.btn_jump_end = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSkipForward)
    self.btn_jump_end.setFixedWidth(40)
    self.btn_jump_end.setToolTip("Перейти к концу зоны (OUT)")
    self.btn_jump_end.clicked.connect(lambda: self.seek_to(self.current_out))
    pctrl_row.addWidget(self.btn_jump_end)

    pctrl_row.addSpacing(14)

    # Поля ввода таймкода IN/OUT убраны по запросу — вместо них кнопки
    # «Обрезать старт/конец» (до плейхеда) и длительность выделения. Сами
    # объекты in_time_edit/out_time_edit/in_frame_spin/out_frame_spin остаются
    # СКРЫТЫМИ держателями: на них завязан остальной код (set_in_out и т.п.).
    io_holder = _api.QWidget(player_bar)
    io_h = _api.QHBoxLayout(io_holder); io_h.setContentsMargins(0, 0, 0, 0)
    self.in_time_edit = _api.QLineEdit("00:00:00.000")
    self.in_time_edit.returnPressed.connect(self.set_in_point)
    self.in_frame_spin = _api.QSpinBox(); self.in_frame_spin.setMaximum(100000000)
    self.in_frame_spin.valueChanged.connect(self.on_in_frame_changed)
    self.out_time_edit = _api.QLineEdit("00:00:05.000")
    self.out_time_edit.returnPressed.connect(self.set_out_point)
    self.out_frame_spin = _api.QSpinBox(); self.out_frame_spin.setMaximum(100000000)
    self.out_frame_spin.valueChanged.connect(self.on_out_frame_changed)
    for _w in (self.in_time_edit, self.in_frame_spin,
               self.out_time_edit, self.out_frame_spin):
        io_h.addWidget(_w)
    io_holder.hide()

    _trim_btn_css = f"""
            QPushButton {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {_api.C['surface2']}; border-color: {_api.C['accent']}; }}
            QPushButton:pressed {{ background: {_api.C['surface']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
        """
    _ss = getattr(self, "trim_start_seq", "Shift+C")
    _es = getattr(self, "trim_end_seq", "Shift+V")
    self.btn_trim_start = _api.QPushButton("Обрезать старт")
    self.btn_trim_start.setToolTip(
        f"Поставить начало (старт) на жёлтую полосу воспроизведения ({_ss})")
    self.btn_trim_start.setStyleSheet(_trim_btn_css)
    # NoFocus: иначе клик мыши уводил клавиатурный фокус на кнопку, и потом
    # Space/Ctrl+Z воспринимались как нажатие кнопки/уходили мимо вкладки
    # (баг «после кнопок Обрезать Ctrl+Z не работает»). Фокус оставляем на
    # вкладке монтажа — там висят все хоткеи (WidgetWithChildrenShortcut).
    self.btn_trim_start.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
    self.btn_trim_start.clicked.connect(self.trim_start_to_playhead)
    pctrl_row.addWidget(self.btn_trim_start)

    self.btn_trim_end = _api.QPushButton("Обрезать конец")
    self.btn_trim_end.setToolTip(
        f"Поставить конец на жёлтую полосу воспроизведения ({_es})")
    self.btn_trim_end.setStyleSheet(_trim_btn_css)
    self.btn_trim_end.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
    self.btn_trim_end.clicked.connect(self.trim_end_to_playhead)
    pctrl_row.addWidget(self.btn_trim_end)

    # Длительность отрезка от старта (IN) до жёлтой полосы воспроизведения.
    seg_frame = _api.QFrame()
    seg_frame.setObjectName("SegFrame")
    seg_frame.setStyleSheet(f"#SegFrame {{ background: {_api.C['surface3']}; border: 1px solid {_api.C['border2']}; border-radius: 6px; }}")
    seg_l = _api.QHBoxLayout(seg_frame)
    seg_l.setContentsMargins(8, 4, 8, 4); seg_l.setSpacing(6)
    seg_cap = _api.QLabel("⏱ старт→плейхед")
    seg_cap.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
    self.lbl_seg_dur = _api.QLabel("00:00:00.000")
    self.lbl_seg_dur.setStyleSheet(f"color: {_api.C['text']}; font-size: 12px; font-weight: 700;")
    self.lbl_seg_dur.setToolTip(
        "Длительность от начала (старта) до жёлтой полосы воспроизведения")
    seg_l.addWidget(seg_cap); seg_l.addWidget(self.lbl_seg_dur)
    pctrl_row.addWidget(seg_frame)

    pctrl_row.addStretch()

    # «Только звук» — снимает видеодорожку с ПЛЕЕРА. На тяжёлых исходниках
    # (AV1/HEVC 1080p60, ЦП-декод) отрисовка кадров съедает главный поток и
    # монтаж начинает лагать, а картинка нужна не всегда: половину работы
    # режут по волне и на слух. Кнопка убирает видео из превью целиком —
    # на РЕЗУЛЬТАТ обрезки это не влияет (её гонит отдельный ffmpeg).
    self.btn_audio_only = _api.make_icon_btn("")
    self.btn_audio_only.setIcon(_api.get_icon('fa5s.headphones'))
    self.btn_audio_only.setIconSize(_api.QSize(18, 18))
    self.btn_audio_only.setFixedWidth(40)
    self.btn_audio_only.setCheckable(True)
    # NoFocus — иначе клик уводит фокус с вкладки и Пробел начинает жать
    # кнопку вместо воспроизведения (та же беда, что у «Обрезать старт»).
    self.btn_audio_only.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
    self.btn_audio_only.setToolTip(
        "Только звук: отключить видео в плеере, чтобы не лагало.\n"
        "На обрезку и экспорт не влияет — там видео остаётся.")
    # make_icon_btn не стилизует :checked — подсвечиваем включённый режим
    # акцентом, иначе не видно, что видео отключено намеренно.
    self.btn_audio_only.setStyleSheet(self.btn_audio_only.styleSheet() + f"""
            QPushButton:checked {{
                background: {_api.C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {_api.C['accent2']}; }}
        """)
    self.btn_audio_only.toggled.connect(self._toggle_audio_only)
    self.btn_audio_only.setEnabled(False)   # активна только при видео
    pctrl_row.addWidget(self.btn_audio_only)

    pctrl_row.addSpacing(8)

    # Регулятор громкости — у правого края, рядом с полноэкранным режимом.
    # (Кнопки «Сохранить кадр»/«Удалить исходник» — внизу боковой панели.)
    self.vol_lbl = _api.VolumeLabel(lambda: getattr(self, "vol_slider", None))
    self.vol_lbl.setStyleSheet(f"color: {_api.C['text2']}; font-size: 14px;")
    # Клик по динамику — mute/unmute с возвратом прежнего уровня.
    self.vol_lbl.clicked.connect(self.toggle_mute)
    pctrl_row.addWidget(self.vol_lbl)
    self.vol_slider = _api.VolumeSlider(_api.Qt.Orientation.Horizontal)
    self.vol_slider.setRange(0, 100)
    self.vol_slider.setValue(100)
    self.vol_slider.setFixedWidth(96)
    self.vol_slider.setStyleSheet(self._slider_style(_api.C["text2"], compact=True))
    self.vol_slider.valueChanged.connect(self._on_volume_changed)
    pctrl_row.addWidget(self.vol_slider)

    pctrl_row.addSpacing(8)
    self.btn_fullscreen = _api.make_icon_btn("", accent=True)
    # Стартует без видео → disabled и приглушённая иконка (станет белой при
    # загрузке видео в _update_media_buttons).
    self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=True, color=_api.C['text3']))
    self.btn_fullscreen.setIconSize(_api.QSize(20, 20))
    self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
    self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
    self.btn_fullscreen.setEnabled(False)   # активна только при загруженном видео
    pctrl_row.addWidget(self.btn_fullscreen)

    pb_layout.addLayout(pctrl_row)
    center.addWidget(player_bar)

    # Состояние полноэкранного режима (окно создаётся по запросу).
    self._fs_window = None
