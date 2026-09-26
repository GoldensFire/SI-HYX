# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _build_center_area. Public namespace: edit_tab."""
import edit_tab as _api


    # Сайдбар добавляется ПОСЛЕ центральной области (root.addWidget ниже),
    # чтобы видео и плеер были слева, а панель информации/экспорта — справа.

def _build_center_area(self):
    """Центральная область: холст видео и его оверлеи. Возвращает layout center."""
    # ── Center area ───────────────────────────────────────────────────
    center = _api.QVBoxLayout()
    center.setContentsMargins(0, 0, 0, 0)
    center.setSpacing(0)

    # Video player area + правая панель (дорожки/субтитры/индикатор звука).
    # Панель занимает место, где раньше были чёрные поля сбоку от видео.
    video_row = _api.QHBoxLayout()
    video_row.setContentsMargins(0, 0, 0, 0)
    video_row.setSpacing(0)

    self.video_container = _api.QFrame()
    self.video_container.setObjectName("VideoContainer")
    # Фон — цвет интерфейса (а не чёрный): пустота вокруг кадра сливается с UI.
    self.video_container.setStyleSheet(f"#VideoContainer {{ background: {_api.C['bg']}; }}")
    vc_layout = _api.QHBoxLayout(self.video_container)
    self.vc_layout = vc_layout
    vc_layout.setContentsMargins(0, 0, 0, 0)
    # Видео центрировано (по горизонтали и вертикали); точный аспект кадра
    # задаётся в _adjust_video_height → внутри виджета полей нет, а свободное
    # место по бокам — это фон цвета интерфейса.
    vc_layout.addWidget(self.video_widget, 0, _api.Qt.AlignmentFlag.AlignCenter)
    # Оверлей субтитров (VLC-стиль) создаётся лениво как отдельное окно поверх
    # видео — см. _ensure_overlay/_position_overlay (QVideoWidget нативный,
    # обычный дочерний виджет под ним не виден).
    video_row.addWidget(self.video_container, 1)

    # Правая панель
    side = _api.QFrame()
    side.setObjectName("SidePanel")
    side.setFixedWidth(196)
    side.setStyleSheet(f"#SidePanel {{ background: {_api.C['surface']}; border-left: 1px solid {_api.C['border']}; }}")
    side_outer = _api.QVBoxLayout(side)
    side_outer.setContentsMargins(0, 0, 0, 0)
    side_outer.setSpacing(0)
    # Содержимое панели — в прокрутке, как в правом сайдбаре. Панель растёт
    # динамически (список слоёв появляется вместе с наложенными картинками),
    # и в невысоком окне Qt раньше ужимал виджеты НИЖЕ их минимума: список
    # слоёв сплющивался в синюю полоску, а подпись «Прозрачность» налезала
    # на кнопки слоя. Со скроллом каждый элемент держит свой размер, а при
    # высоком окне поведение прежнее — widgetResizable растягивает
    # содержимое на всю высоту (шкала уровня звука по-прежнему тянется).
    side_scroll = _api.QScrollArea()
    side_scroll.setObjectName("SidePanelScroll")
    side_scroll.setWidgetResizable(True)
    side_scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
    side_scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    side_scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    side_scroll.setStyleSheet("QScrollArea#SidePanelScroll { border: none; }")
    side_content = _api.QWidget()
    side_l = _api.QVBoxLayout(side_content)
    # Правый отступ 4px — дорожка под вертикальный скроллбар, чтобы он не
    # наезжал на комбобоксы (общий стиль приложения даёт узкий ползунок).
    side_l.setContentsMargins(10, 10, 4, 10)
    side_l.setSpacing(6)
    side_scroll.setWidget(side_content)
    side_outer.addWidget(side_scroll)

    _combo_css = f"""
            QComboBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                selection-background-color: {_api.C['accent']};
                border: 1px solid {_api.C['border2']};
            }}
        """
    def _find_btn(tip, slot):
        b = _api.QPushButton()
        b.setIcon(_api.get_icon('fa5s.folder-open'))
        b.setIconSize(_api.QSize(20, 20))
        b.setToolTip(tip)
        b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(30, 28)
        b.setStyleSheet(f"""
                QPushButton {{ background: {_api.C['surface3']}; color: {_api.C['text']};
                    border: 1px solid {_api.C['border2']}; border-radius: 5px;
                    padding: 0; font-size: 13px; }}
                QPushButton:hover {{ background: {_api.C['border2']};
                    border-color: {_api.C['accent']}; }}
            """)
        b.clicked.connect(slot)
        return b

    lbl_at = _api.QLabel("Аудиодорожка")
    lbl_at.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
    side_l.addWidget(lbl_at)
    at_row = _api.QHBoxLayout(); at_row.setContentsMargins(0, 0, 0, 0); at_row.setSpacing(5)
    self.cmb_audio = _api.QComboBox()
    self.cmb_audio.setStyleSheet(_combo_css)
    self.cmb_audio.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_audio.setMinimumContentsLength(6)
    self.cmb_audio.currentIndexChanged.connect(self.on_audio_track_changed)
    at_row.addWidget(self.cmb_audio, 1)
    self.btn_find_audio = _find_btn(
        "Найти внешний аудиофайл (озвучку) на ПК", self.find_external_audio)
    at_row.addWidget(self.btn_find_audio, 0)
    side_l.addLayout(at_row)

    # Заголовок «Субтитры» + кнопка-карандаш (правка текста субтитров прямо тут).
    st_hdr = _api.QHBoxLayout(); st_hdr.setContentsMargins(0, 0, 0, 0); st_hdr.setSpacing(4)
    lbl_st = _api.QLabel("Субтитры")
    lbl_st.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
    st_hdr.addWidget(lbl_st)
    st_hdr.addStretch(1)
    self.btn_edit_subs = _api.QPushButton()
    self.btn_edit_subs.setIcon(_api.get_icon('fa5s.edit', color=_api.C['text2']))
    self.btn_edit_subs.setIconSize(_api.QSize(14, 14))
    self.btn_edit_subs.setFixedSize(24, 20)
    self.btn_edit_subs.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self.btn_edit_subs.setToolTip("Редактировать текст выбранных субтитров")
    self.btn_edit_subs.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background: {_api.C['surface3']}; }}
            QPushButton:pressed {{ background: {_api.C['border2']}; }}
        """)
    self.btn_edit_subs.clicked.connect(self.edit_subtitles)
    st_hdr.addWidget(self.btn_edit_subs)
    side_l.addLayout(st_hdr)
    st_row = _api.QHBoxLayout(); st_row.setContentsMargins(0, 0, 0, 0); st_row.setSpacing(5)
    self.cmb_subs = _api.QComboBox()
    self.cmb_subs.setStyleSheet(_combo_css)
    self.cmb_subs.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_subs.setMinimumContentsLength(6)
    self.cmb_subs.currentIndexChanged.connect(self.on_sub_track_changed)
    st_row.addWidget(self.cmb_subs, 1)
    self.btn_find_subs = _find_btn(
        "Найти внешний файл субтитров на ПК", self.find_external_subs)
    st_row.addWidget(self.btn_find_subs, 0)
    side_l.addLayout(st_row)

    # Стиль вшиваемых субтитров (hardsub): как в программе или как в оригинале.
    lbl_ss = _api.QLabel("Стиль вшитых субтитров")
    lbl_ss.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
    side_l.addWidget(lbl_ss)
    self.cmb_sub_style = _api.QComboBox()
    self.cmb_sub_style.addItems(["Авто", "Как в программе", "Как в оригинале"])
    # По умолчанию — «Как в оригинале» (стиль из самих субтитров, ничего не навязываем).
    self.cmb_sub_style.setCurrentIndex(2)
    self.cmb_sub_style.setToolTip(
        "Стиль субтитров при вшивании в кадр:\n"
        "Авто — стиль программы для SRT/VTT, у ASS/SSA остаётся собственный.\n"
        "Как в программе — крупный белый шрифт с обводкой даже поверх ASS/SSA.\n"
        "Как в оригинале — ничего не навязывать (стиль из самих субтитров).")
    self.cmb_sub_style.setStyleSheet(_combo_css)
    self.cmb_sub_style.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_sub_style.setMinimumContentsLength(6)
    side_l.addWidget(self.cmb_sub_style)

    # Чекбокс «Вшить субтитры» — НАД индикатором уровня звука (по просьбе
    # пользователя). Кнопки кадра/удаления переехали в самый низ панели.
    # Список наложенных картинок (появляется, только когда слои есть).
    self.overlay_panel = _api.OverlayLayersPanel()
    self.overlay_panel.selected.connect(self._on_overlay_selected)
    self.overlay_panel.cropRequested.connect(self._crop_image_overlay)
    self.overlay_panel.deleteRequested.connect(self._delete_image_overlay)
    self.overlay_panel.opacityChanged.connect(self._set_overlay_opacity)
    self.overlay_panel.resetRequested.connect(self._reset_image_overlay)
    side_l.addSpacing(6)
    side_l.addWidget(self.overlay_panel)

    side_l.addSpacing(6)
    side_l.addWidget(self.chk_burn_subs)

    # Низ боковой панели: СЛЕВА — кнопки «Сохранить кадр»/«Удалить исходник»
    # (столбиком), СПРАВА — индикатор уровня звука. Прежде кнопки лежали ПОД
    # индикатором и перекрывали подписи каналов L/R (см. скрин); теперь они
    # сбоку, и шкала уровня занимает всю доступную высоту панели.
    # «Кадрировать видео» — значок над «Сохранить кадр»: включаешь, выделяешь
    # область прямо на видео, и при «Обрезать» итоговое ВИДЕО кадрируется по
    # этой рамке (а не только сохраняемый кадр). Повторное нажатие выключает и
    # сбрасывает рамку. Кадрирование требует перекодировки (copy не умеет
    # crop), поэтому при активной рамке быстрый режим переключается на
    # «Перекодировать» автоматически.
    self.btn_crop_frame = _api.make_icon_btn("")
    self.btn_crop_frame.setIcon(_api.get_icon('fa5s.crop-alt'))
    self.btn_crop_frame.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_crop_frame)
    self.btn_crop_frame.setCheckable(True)
    self.btn_crop_frame.setToolTip("Кадрировать видео: выделите область на видео — "
                                   "при «Обрезать» сохранится только она "
                                   "(требует перекодировки)")
    self.btn_crop_frame.toggled.connect(self._toggle_frame_crop)
    self.btn_crop_frame.setEnabled(False)
    # «Пикселизация — проявление»: видео стартует крупными блоками и постепенно
    # проясняется (для угадайки). Параметры задаются в диалоге, эффект
    # применяется при «Обрезать» (требует перекодировки, как и кадрирование).
    self._pixelize_active = False
    self._pixelize_steps = 6
    self._pixelize_block = 64
    self.btn_pixelize = _api.make_icon_btn("")
    self.btn_pixelize.setIcon(_api.get_icon('fa5s.th'))
    self.btn_pixelize.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_pixelize)
    self.btn_pixelize.setCheckable(True)
    self.btn_pixelize.setToolTip("Пикселизация: видео начнётся крупными «пикселями» "
                                 "и постепенно станет чётким (для угадайки). "
                                 "Применяется при «Обрезать» (перекодировка)")
    self.btn_pixelize.toggled.connect(self._toggle_pixelize)
    self.btn_pixelize.setEnabled(False)
    # ВИДИМОЕ состояние «включено»: make_icon_btn не стилизует :checked, и
    # армированная пикселизация выглядела как обычная кнопка (пользователь не
    # видел, что эффект активен). Подсвечиваем активную кнопку акцентом.
    self.btn_pixelize.setStyleSheet(self.btn_pixelize.styleSheet() + f"""
            QPushButton:checked {{
                background: {_api.C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {_api.C['accent2']}; }}
        """)
    self.btn_save_frame = _api.make_icon_btn("")
    self.btn_save_frame.setIcon(_api.get_icon('fa5s.save'))
    self.btn_save_frame.setIconSize(_api.QSize(20, 20))
    self._relax_width(self.btn_save_frame)
    self.btn_save_frame.setToolTip("Сохранить текущий кадр в PNG (в папку сохранения)")
    self.btn_save_frame.clicked.connect(self.save_frame)
    self.btn_save_frame.setEnabled(False)   # активна только при загруженном видео
    # «Удалить объект» — покадровое удаление водяного знака/эмодзи с видео тем же
    # движком LaMa, что и в фоторедакторе (см. remove_object_from_video).
    self.btn_remove_object = _api.make_icon_btn("")
    self.btn_remove_object.setIcon(_api.get_icon('fa5s.magic'))
    self.btn_remove_object.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_remove_object)
    self.btn_remove_object.setToolTip(
        "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте его "
        "кистью на кадре — нейросеть LaMa уберёт его со всех кадров")
    self.btn_remove_object.clicked.connect(self.remove_object_from_video)
    self.btn_remove_object.setEnabled(False)
    # «Создать субтитры» — реплики (текст+тайминг) и позиция на экране задаются
    # в отдельном окне (SubtitleCreatorDialog), результат — новая .ass-дорожка.
    self.btn_create_subs = _api.make_icon_btn("")
    self.btn_create_subs.setIcon(_api.get_icon('fa5s.closed-captioning'))
    self.btn_create_subs.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_create_subs)
    self.btn_create_subs.setToolTip(
        "Создать субтитры: текст, тайминг и позиция на экране "
        "задаются в отдельном окне. Если сейчас выбрана дорожка "
        "субтитров — открывает её же на редактирование")
    self.btn_create_subs.clicked.connect(self.create_subtitles)
    self.btn_create_subs.setEnabled(False)
    # «Привязать к объекту» — отслеживание выбранной области (DyHiT/HiT, ONNX;
    # запасной трекер — CSRT из OpenCV) и накладка (текст/картинка), едущая
    # вместе с объектом. См. track_object_overlay.
    self.btn_track_object = _api.make_icon_btn("")
    self.btn_track_object.setIcon(_api.get_icon('fa5s.crosshairs'))
    self.btn_track_object.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_track_object)
    self.btn_track_object.setToolTip(
        "Привязать к объекту: обведите движущийся объект (руку, лицо, "
        "машину) — нейросеть проследит за ним, и выбранный текст или "
        "картинка поедут вместе с ним. Накладка сразу видна в плеере; "
        "в файл её вшивает «Обрезать», повторное нажатие — убирает")
    self.btn_track_object.clicked.connect(self.track_object_overlay)
    self.btn_track_object.setEnabled(False)
    # «Наложить картинку» — неподвижный логотип/водяной знак/рамка поверх
    # видео: картинка появляется прямо в плеере, её двигают/тянут/крутят
    # мышью, кадрируют отдельным окном, а «Обрезать» вшивает её в файл
    # (overlay=…, требует перекодировки — как кадрирование).
    self.btn_image_overlay = _api.make_icon_btn("")
    self.btn_image_overlay.setIcon(_api.get_icon('fa5s.image'))
    self.btn_image_overlay.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_image_overlay)
    self.btn_image_overlay.setToolTip(
        "Наложить картинку: выберите файл — он ляжет слоем поверх видео. "
        "Перетаскивайте мышью, тяните за уголки, крутите за «антенну» "
        "сверху (Shift — шаг 15°), Ctrl+стрелки — точная сдвижка, "
        "Delete — убрать слой; обрезать саму картинку и задать "
        "прозрачность — в списке слоёв справа. "
        "Вшивается при «Обрезать» (перекодировка)")
    self.btn_image_overlay.clicked.connect(self.add_image_overlay)
    self.btn_image_overlay.setEnabled(False)
    self.btn_delete_source = _api.make_icon_btn("", danger=True)
    self.btn_delete_source.setIcon(_api.get_icon('fa5s.trash-alt', color='#11111b'))
    self.btn_delete_source.setIconSize(_api.QSize(18, 18))
    self._relax_width(self.btn_delete_source)
    self.btn_delete_source.setToolTip("Удалить исходный файл с диска (без возможности отмены)")
    self.btn_delete_source.clicked.connect(self.delete_source_file)
    self.btn_delete_source.setEnabled(False)

    # Две колонки по 4 квадратные кнопки (место под 8 штук) — левая и правая,
    # каждая прижата к низу (симметрично высоте шкалы уровня звука справа).
    # Правая колонка нарочно короче: «Удалить исходник» (опасная, красная)
    # держим самой нижней — как и раньше в одной колонке.
    self._montage_side_btns = [self.btn_crop_frame, self.btn_pixelize,
                               self.btn_save_frame, self.btn_remove_object,
                               self.btn_create_subs, self.btn_track_object,
                               self.btn_image_overlay, self.btn_delete_source]
    col_l = _api.QVBoxLayout(); col_l.setContentsMargins(0, 0, 0, 0)
    col_l.setSpacing(self._MSIDE_GAP)
    col_l.addStretch(1)
    for _b in (self.btn_crop_frame, self.btn_pixelize,
               self.btn_save_frame, self.btn_remove_object):
        col_l.addWidget(_b)
    col_r = _api.QVBoxLayout(); col_r.setContentsMargins(0, 0, 0, 0)
    col_r.setSpacing(self._MSIDE_GAP)
    col_r.addStretch(1)
    for _b in (self.btn_create_subs, self.btn_track_object,
               self.btn_image_overlay, self.btn_delete_source):
        col_r.addWidget(_b)
    btn_col = _api.QHBoxLayout(); btn_col.setContentsMargins(0, 0, 0, 0)
    btn_col.setSpacing(self._MSIDE_GAP)
    btn_col.addLayout(col_l)
    btn_col.addLayout(col_r)
    btn_col.addStretch(1)   # не растягивать колонки шире квадратных кнопок

    # Правая колонка — подпись + шкала, отцентрованная под текстом.
    vu_col = _api.QVBoxLayout(); vu_col.setContentsMargins(0, 0, 0, 0); vu_col.setSpacing(3)
    lbl_vu = _api.QLabel("Уровень звука")
    lbl_vu.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
    lbl_vu.setAlignment(_api.Qt.AlignmentFlag.AlignHCenter)
    vu_col.addWidget(lbl_vu, 0)
    self.audio_meter = _api.AudioMeter()
    self.audio_meter.setFixedWidth(54)
    meter_row = _api.QHBoxLayout(); meter_row.setContentsMargins(0, 0, 0, 0)
    meter_row.addStretch(1)
    meter_row.addWidget(self.audio_meter)
    meter_row.addStretch(1)
    vu_col.addLayout(meter_row, 1)
    # Высота шкалы == высоте колонки кнопок → по её ресайзу пересчитываем кнопки.
    self.audio_meter.installEventFilter(self)

    bottom_row = _api.QHBoxLayout(); bottom_row.setContentsMargins(0, 0, 0, 0)
    bottom_row.setSpacing(10)
    bottom_row.addLayout(btn_col, 1)
    bottom_row.addLayout(vu_col, 0)
    side_l.addLayout(bottom_row, 1)

    video_row.addWidget(side, 0)
    center.addLayout(video_row, stretch=1)

    return center
