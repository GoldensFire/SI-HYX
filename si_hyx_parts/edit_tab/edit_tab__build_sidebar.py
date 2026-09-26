# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _build_sidebar. Public namespace: edit_tab."""
import edit_tab as _api


def _build_sidebar(self):
    """Правая боковая панель (инфо/экспорт) внутри QScrollArea.
        Возвращает саму панель и её внутренние контейнеры — они нужны
        секциям «прокси» и «итог», которые дозаполняют ту же панель."""
    # ── Right sidebar (прокручиваемая) ────────────────────────────────
    # Содержимое (инфо/экспорт) живёт в QScrollArea — если по высоте не
    # умещается, появляется вертикальный скроллбар. Кнопки «Итог» и
    # «Обрезать» закреплены ВНЕ прокрутки, снизу (всегда видны).
    sidebar = _api.QFrame()
    sidebar.setObjectName("Sidebar")
    sidebar.setFixedWidth(264)
    sidebar.setStyleSheet(f"""
            #Sidebar {{
                background: {_api.C['surface']};
                border-left: 1px solid {_api.C['border']};
            }}
        """)
    sb_outer = _api.QVBoxLayout(sidebar)
    sb_outer.setContentsMargins(0, 0, 0, 0)
    sb_outer.setSpacing(0)

    sb_scroll = _api.QScrollArea()
    sb_scroll.setObjectName("SidebarScroll")
    sb_scroll.setWidgetResizable(True)
    sb_scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
    sb_scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sb_scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    # Никакого собственного стиля скроллбара — берём общий стиль приложения
    # (config.STYLESHEET), чтобы он совпадал со скроллбарами других вкладок.
    # Фон не задаём (глобальное правило делает контент прозрачным → виден
    # surface самого сайдбара; собственный фон давал серую «подложку»).
    sb_scroll.setStyleSheet("QScrollArea#SidebarScroll { border: none; }")
    sb_content = _api.QWidget()
    sb_layout = _api.QVBoxLayout(sb_content)
    # Правый отступ 14px — «дорожка» для вертикального скроллбара, чтобы он не
    # перекрывал содержимое (панель всегда видна полностью).
    sb_layout.setContentsMargins(16, 16, 14, 16)
    sb_layout.setSpacing(12)

    # File section
    self.lbl_file = _api.QLabel("Нет файла")
    self.lbl_file.setWordWrap(True)
    self.lbl_file.setStyleSheet(f"""
            color: {_api.C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {_api.C['surface2']};
            border: 1px dashed {_api.C['border2']};
            border-radius: 6px;
        """)
    self.lbl_file.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    sb_layout.addWidget(self.lbl_file)

    # Кнопки работы с файлом в одну строку: «Открыть» занимает половину
    # ширины, рядом — «Очистить» (убирает текущий файл и сбрасывает редактор).
    file_btn_row = _api.QHBoxLayout()
    file_btn_row.setSpacing(8)
    btn_open = _api.make_icon_btn("Открыть", accent=True, icon='fa5s.folder-open')
    self._relax_width(btn_open)  # не заставляем панель расширяться под текст
    btn_open.clicked.connect(self.open_file)
    btn_clear = _api.make_icon_btn("Очистить", icon='fa5s.trash')
    self._relax_width(btn_clear)
    btn_clear.setToolTip("Убрать текущий файл и очистить редактор")
    btn_clear.clicked.connect(self.clear_file)
    file_btn_row.addWidget(btn_open, 1)
    file_btn_row.addWidget(btn_clear, 1)
    sb_layout.addLayout(file_btn_row)

    sb_layout.addWidget(_api.make_divider())

    # Media info card
    info_card = _api.InfoCard("МЕДИА ИНФОРМАЦИЯ")
    self.lbl_duration = info_card.add_row("Длительность", "lbl_duration")
    self.lbl_fps      = info_card.add_row("FPS",          "lbl_fps")
    self.lbl_vstream  = info_card.add_row("Видео",        "lbl_vstream")
    self.lbl_astream  = info_card.add_row("Аудио",        "lbl_astream")
    self.lbl_abitrate = info_card.add_row("Битрейт аудио", "lbl_abitrate")
    sb_layout.addWidget(info_card)

    sb_layout.addWidget(_api.make_divider())

    # Export settings card
    export_card = _api.InfoCard("НАСТРОЙКИ ЭКСПОРТА")

    mode_lbl = _api.QLabel("Режим обрезки")
    mode_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
    export_card._body.addWidget(mode_lbl)

    self.cmb_mode = _api.QComboBox()
    self.cmb_mode.addItems([
        "Быстро (без потерь)",
        "Перекодировать",
        "Только аудио (MP3)",
        "Smart Cut (умная)",
        "Перекодировать настройками «Обработки»",
        "(Аудио) Перекодировать настройками «Обработки»",
    ])
    # По умолчанию — «Перекодировать» (кадрово точная обрезка).
    self.cmb_mode.setCurrentIndex(1)
    self.cmb_mode.setToolTip(
        "Быстро — copy без перекодировки (начало прилипает к ключевому кадру).\n"
        "Перекодировать — кадрово точно, но медленно и с потерями.\n"
        "Smart Cut — точные границы реза перекодируются, середина копируется "
        "без потерь (быстро и с сохранением качества).\n"
        "Перекодировать настройками «Обработки» — точный рез и текущие настройки "
        "вкладки «Обработка» (кодек/CRF/скорость/громкость/fps) ОДНИМ проходом, "
        "без двойной перекодировки. Наложенные картинки вшиваются тем же "
        "проходом; кодировщик и «Вшить субтитры»/кадрирование/пикселизация "
        "в этом режиме не применяются.\n"
        "(Аудио) Перекодировать настройками «Обработки» — то же самое, но "
        "видеоряд отбрасывается: на выходе ТОЛЬКО звуковая дорожка (.opus) с "
        "текущими настройками звука «Обработки» (битрейт/громкость/фейды/"
        "скорость).")
    # Не даём комбобоксу диктовать ширину панели по длине пункта (иначе панель
    # переполняется и обрезается). Закрытый комбо подстраивается под N символов,
    # полный текст пунктов виден в выпадающем списке.
    self.cmb_mode.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_mode.setMinimumContentsLength(8)
    self._relax_width(self.cmb_mode)
    self.cmb_mode.setStyleSheet(f"""
            QComboBox {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                selection-background-color: {_api.C['accent']};
                border: 1px solid {_api.C['border2']};
            }}
        """)
    export_card._body.addWidget(self.cmb_mode)

    # Кодировщик для перекодировки (режим «Перекодировать» и границы Smart Cut):
    # CPU (libx264) — лучшее качество/совместимость; GPU — быстрее, грузит
    # видеокарту. На «Быстро (без потерь)» не влияет (там copy без кодека).
    enc_lbl = _api.QLabel("Кодировщик (перекодировка)")
    enc_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
    export_card._body.addWidget(enc_lbl)

    self.cmb_encoder = _api.QComboBox()
    self.cmb_encoder.addItems([
        "Авто",
        "Процессор (CPU)",
        "Видеокарта (GPU)",
    ])
    self.cmb_encoder.setToolTip(
        "Чем перекодировать видео при обрезке с перекодировкой и на границах "
        "Smart Cut.\n"
        "Процессор (CPU) — libx264, лучшее качество и совместимость, медленнее.\n"
        "Видеокарта (GPU) — аппаратный кодек (NVENC/QSV/AMF), быстрее, "
        "нагружает видеокарту.\n"
        "Если выбранного варианта нет в сборке — автоматический откат.")
    self.cmb_encoder.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_encoder.setMinimumContentsLength(8)
    self._relax_width(self.cmb_encoder)
    self.cmb_encoder.setStyleSheet(self.cmb_mode.styleSheet())
    export_card._body.addWidget(self.cmb_encoder)

    self.chk_overwrite = _api.QCheckBox("Перезаписать файл")
    self.chk_overwrite.setChecked(True)
    self._relax_width(self.chk_overwrite)
    self.chk_overwrite.setStyleSheet(f"""
            QCheckBox {{
                color: {_api.C['text2']};
                font-size: 12px;
                spacing: 6px;
                /* Своя таблица стилей иначе красит строку цветом окна —
                   тёмная полоса поперёк карточки. */
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {_api.C['border2']};
                border-radius: 3px;
                background: {_api.C['surface3']};
            }}
            QCheckBox::indicator:checked {{
                background: {_api.C['accent']};
                border-color: {_api.C['accent']};
            }}
        """)
    export_card._body.addWidget(self.chk_overwrite)

    # Вшивание (hardsub) выбранных субтитров прямо в картинку. ВНИМАНИЕ:
    # это всегда требует ПЕРЕКОДИРОВКИ видео (пиксели субтитров рисуются на
    # кадрах) — без перекодировки можно лишь встроить субтитры отдельной
    # дорожкой, но не «вжечь» в изображение. Сам чекбокс размещаем НЕ здесь,
    # а в правой панели рядом с кнопками «Сохранить кадр»/«Удалить исходник»
    # (см. сборку side-панели ниже) — создаём заранее, добавим туда.
    self.chk_burn_subs = _api.QCheckBox("Вшить субтитры")
    self.chk_burn_subs.setChecked(False)
    self._relax_width(self.chk_burn_subs)
    self.chk_burn_subs.setToolTip(
        "Жёстко впечатывает выбранную дорожку субтитров в кадр.\n"
        "Требует перекодировки видео (режим обрезки будет проигнорирован).\n"
        "Субтитры выбираются в панели справа от видео.")
    self.chk_burn_subs.setStyleSheet(self.chk_overwrite.styleSheet())

    # Папка сохранения результата ("" = рядом с исходником)
    dst_lbl = _api.QLabel("Папка сохранения")
    dst_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
    self._relax_width(dst_lbl)
    export_card._body.addWidget(dst_lbl)
    self.lbl_export_dir = _api.QLabel("Рядом с исходником")
    # Без переноса (длинный путь не разрывается и распирал бы панель) — вместо
    # этого укорачиваем в середине в _update_export_dir_label; min width 0,
    # чтобы метка не диктовала ширину панели.
    self.lbl_export_dir.setWordWrap(False)
    self.lbl_export_dir.setMinimumWidth(0)
    self._relax_width(self.lbl_export_dir)
    self.lbl_export_dir.setStyleSheet(
        f"color: {_api.C['text2']}; font-size: 11px; padding: 4px 6px; "
        f"background: {_api.C['surface3']}; border: 1px solid {_api.C['border2']}; border-radius: 5px;")
    export_card._body.addWidget(self.lbl_export_dir)
    dst_row = _api.QHBoxLayout(); dst_row.setSpacing(6)
    btn_dst = _api.make_icon_btn("Выбрать", icon='fa5s.folder')
    self._relax_width(btn_dst)
    btn_dst.clicked.connect(self._choose_export_dir)
    btn_dst_reset = _api.make_icon_btn("", icon='fa5s.undo')
    # Узкая квадратная кнопка: убираем боковой паддинг make_icon_btn,
    # фиксируем размер.
    btn_dst_reset.setStyleSheet(btn_dst_reset.styleSheet()
                                + "\nQPushButton { padding: 5px 0; }")
    btn_dst_reset.setFixedSize(34, 32)
    btn_dst_reset.setToolTip("Сбросить — сохранять рядом с исходником")
    btn_dst_reset.clicked.connect(self._reset_export_dir)
    dst_row.addWidget(btn_dst, 1); dst_row.addWidget(btn_dst_reset, 0)
    export_card._body.addLayout(dst_row)

    sb_layout.addWidget(export_card)

    return sidebar, sb_outer, sb_scroll, sb_content, sb_layout

def _build_quality_card(self):
    """Карточка «Качество воспроизведения» в боковой панели. Возвращает карточку
        (следующая секция вставляет карточку прокси сразу после неё)."""
    # ── Качество воспроизведения (как в Filmora) ──────────────────────────
    # Понижает разрешение ТОЛЬКО предпросмотра (через прокси), чтобы плеер и
    # перемотка работали шустрее на слабом железе/тяжёлых файлах. На экспорт
    # не влияет — он всегда из оригинала.
    pbq_card = _api.InfoCard("ВОСПРОИЗВЕДЕНИЕ")
    pbq_lbl = _api.QLabel("Качество воспроизведения")
    pbq_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
    self.cmb_pb_quality = _api.QComboBox()
    self.cmb_pb_quality.addItems([
        "Полное качество",
        "1/2 — быстрее",
        "1/4 — ещё быстрее",
    ])
    self.cmb_pb_quality.setToolTip(
        "Качество предпросмотра (не влияет на экспорт).\n"
        "Полное — играет оригинал без прокси. Исключение — AV1: его "
        "QtMultimedia не тянет напрямую, поэтому для него прокси строится "
        "всегда (это единственный случай «не поддерживается»).\n"
        "1/2 и 1/4 — плеер всегда показывает уменьшенную копию (прокси): "
        "воспроизведение и перемотка работают быстрее на тяжёлых файлах.")
    self.cmb_pb_quality.setSizeAdjustPolicy(
        _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.cmb_pb_quality.setMinimumContentsLength(8)
    self._relax_width(self.cmb_pb_quality)
    self.cmb_pb_quality.setStyleSheet(self.cmb_mode.styleSheet())
    self.cmb_pb_quality.currentIndexChanged.connect(self._on_pb_quality_changed)
    pbq_card._body.addWidget(pbq_lbl)
    pbq_card._body.addWidget(self.cmb_pb_quality)

    return pbq_card
