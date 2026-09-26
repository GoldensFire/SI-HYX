# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: _build_video_group. Public namespace: tabs."""
import tabs as _api


def _build_video_group(self, rv_inner):
    """Группа «Перекодирование видео»: CRF/preset, режим, метрика XPSNR, тюнинг."""
    gv = _api.QGroupBox("Перекодирование видео"); fv = _api.QFormLayout()
    self.chk_enable_video = _api.QCheckBox("Включить перекодирование"); self.chk_enable_video.setChecked(True)

    # --- Переключатель профиля: две кнопки-тогглы ---
    self.btn_mode_std  = _api.QPushButton("Стандарт");       self.btn_mode_std.setCheckable(True);  self.btn_mode_std.setChecked(True)
    self.btn_mode_dark = _api._icon_btn("Тёмные сцены", 'fa5s.moon'); self.btn_mode_dark.setCheckable(True); self.btn_mode_dark.setChecked(False)
    self.btn_mode_std.setToolTip("yuv420p, 1-pass")
    self.btn_mode_dark.setToolTip("10-бит (yuv420p10le), tune=0, 2-pass AV1\nCRF, preset и разрешение — без изменений")
    self.btn_mode_std.clicked.connect(lambda: self._set_preset_mode("std"))
    self.btn_mode_dark.clicked.connect(lambda: self._set_preset_mode("dark"))
    mode_h = _api.QHBoxLayout(); mode_h.addWidget(self.btn_mode_std); mode_h.addWidget(self.btn_mode_dark)
    mode_h.addStretch(1)
    # Ширину тоглов профиля резервируем под ЖИРНЫЙ текст: глобальный QSS
    # (QPushButton:checked → font-weight:bold) делает активную кнопку жирной,
    # из-за чего «Тёмные сцены» обрезалось до «…сцень». sizeHint() у Qt НЕ
    # учитывает font-weight, заданный CSS-псевдо-состоянием (:checked) —
    # только реальный .font() виджета — так что заранее посчитать нужную
    # ширину числом (как раньше) не выйдет, ЛЮБАЯ константа была подогнана
    # под неверный шрифт (при setMinimumWidth в __init__ кнопка ещё не
    # «располирована» глобальным QSS — .font() отдаёт временный дефолтный
    # шрифт, а не итоговый Segoe UI/13px). Меряем НАСТОЯЩИЙ размер: временно
    # выставляем жирный шрифт САМОМУ виджету (после ensurePolished — это уже
    # правильный шрифт), берём sizeHint() и возвращаем шрифт обратно —
    # bold остаётся исключительно на совести CSS :checked, как и было.
    _api.QTimer.singleShot(0, self._size_profile_toggle_buttons)

    # ── Метрика качества (AV1, всегда SVT-AV1) ────────────────────────────
    # Выкл — ручной CRF как есть, кодировщик просто тюнится под tune=0
    # (как и раньше). XPSNR — CRF на каждый файл подбирается
    # самостоятельно (_metric_crf_search в workers.py, без внешних
    # инструментов: короткий пробный сэмпл + бинарный поиск + встроенный
    # ffmpeg-фильтр xpsnr) так, чтобы результат достигал заданного
    # значения в дБ (см. s_target_metric ниже); сам кодировщик всё равно
    # тюнится под tune=0 — метрика здесь означает цель ПОДБОРА CRF, а не
    # тюнинг энкодера.
    self.ck_metric_xpsnr = _api.QCheckBox("XPSNR")
    self.ck_metric_xpsnr.setChecked(False)

    self.s_crf = _api.QSpinBox(); self.s_crf.setRange(0, 63); self.s_crf.setValue(45)
    self.s_pre = _api.QSpinBox(); self.s_pre.setRange(0, 13); self.s_pre.setValue(2)
    self.c_res = _api.QComboBox(); self.c_res.addItems(["Исходное", "1920x1080", "1280x720" + _api.DEFAULT_TAG, "854x480", "144x72"])
    self.c_res.setCurrentText("1280x720" + _api.DEFAULT_TAG)
    self.c_res.setMinimumWidth(210); self.c_res.setMaximumWidth(240)
    self.c_res.setSizeAdjustPolicy(_api.QComboBox.SizeAdjustPolicy.AdjustToContents)
    self.c_fps = _api.InvertedWheelComboBox(); self.c_fps.addItems(["Исходный", "Исходный (max 30)", "5", "12", "23.976", "24", "30", "60"])
    self.c_fps.setCurrentText("Исходный (max 30)")
    self.c_fps.setEditable(True)   # можно вводить своё число FPS, а пресеты — из выпадашки
    self.c_fps.setInsertPolicy(_api.QComboBox.InsertPolicy.NoInsert)
    try: self.c_fps.lineEdit().setPlaceholderText("напр. 48")
    except Exception: pass
    self.c_fps.setMinimumWidth(150); self.c_fps.setMaximumWidth(200)
    fv.addRow(_api.row_with_info(self.chk_enable_video, "Если выключено — видео не трогается, меняется только звук. Включено — перекодирование в AV1 (SVT-AV1)."))
    fv.addRow(_api.label_with_info("Профиль:", "Стандарт: Использовать по умолчанию. Тёмные сцены: Только в темных сценах."), mode_h)
    henc = _api.QHBoxLayout(); henc.addWidget(self.s_crf); henc.addWidget(self.s_pre)
    self._badge_crf = _api.info_badge("Preset — скорость кодирования (0 медленно и качественно … 13 быстро, но страдает качество (Рекомендуется 1, если позволяет процессор)).")
    henc.addWidget(self._badge_crf)
    henc.addStretch()
    fv.addRow(_api.label_with_info("CRF / Preset:", "CRF — качество (меньше = качественнее, но больше файл. Рекомендуется 40-45. Может принимать значения от 0 до 63)"), henc)

    # ── Тюнинг SVT-AV1 (--tune) — под какую метрику оптимизирует энкодер ──
    # Реально поддерживаемые SVT-AV1 режимы тюнинга (проверено на бандленном
    # ffmpeg/SVT-AV1): 0=VQ, 1=PSNR, 2=SSIM, 4=MS-SSIM, 5=VMAF. tune=3 (IQ)
    # сознательно пропущен — он поддерживает только all-intra/low-delay
    # предсказание и падает с ошибкой на нашей random-access GOP-структуре
    # (keyint=-1:scd=1, см. _av1_encoder_args в workers.py).
    self.c_tune = _api.InvertedWheelComboBox()
    self.c_tune.addItem("VQ (0)" + _api.DEFAULT_TAG, 0)
    self.c_tune.addItem("PSNR (1)", 1)
    self.c_tune.addItem("SSIM (2)", 2)
    self.c_tune.addItem("MS-SSIM (4)", 4)
    self.c_tune.addItem("VMAF (5)", 5)
    self.c_tune.setMinimumWidth(150); self.c_tune.setMaximumWidth(180)
    fv.addRow(_api.label_with_info(
        "Тюнинг:",
        "Под какую метрику качества оптимизирует SVT-AV1 при кодировании.\n"
        "VQ — субъективное визуальное качество (по умолчанию).\n"
        "PSNR / SSIM / MS-SSIM / VMAF — оптимизация под соответствующую объективную метрику."),
        self.c_tune)

    # ── Метрика: Выкл (ручной CRF) / XPSNR (авто-подбор CRF) ───────────
    self.s_target_metric = _api.QSlider(_api.Qt.Orientation.Horizontal)
    self.s_target_metric.setRange(15, 60); self.s_target_metric.setValue(40)
    self.s_target_metric.setSingleStep(1); self.s_target_metric.setPageStep(1)
    self.s_target_metric.setEnabled(False)
    self.s_target_metric.setMaximumWidth(140)

    self.lbl_target_metric = _api.QLabel("40 дБ")
    self.lbl_target_metric.setMinimumWidth(55)
    self.lbl_target_metric.setEnabled(False)

    def _on_metric_toggled(checked):
        self.s_target_metric.setEnabled(checked)
        self.lbl_target_metric.setEnabled(checked)
        try: self.main._save_settings_now()
        except Exception: pass
    def _on_target_changed(v):
        self.lbl_target_metric.setText(f"{v} дБ")
        try: self.main._save_settings_now()
        except Exception: pass
    self.ck_metric_xpsnr.toggled.connect(_on_metric_toggled)
    self.s_target_metric.valueChanged.connect(_on_target_changed)

    metric_h = _api.QHBoxLayout()
    metric_h.addWidget(self.ck_metric_xpsnr)
    metric_h.addWidget(self.s_target_metric)
    metric_h.addWidget(self.lbl_target_metric)
    self._badge_metric = _api.info_badge(
        "Выкл — CRF задаётся вручную выше, кодировщик просто кодирует с ним как есть.\n"
        "XPSNR — перед кодированием на коротком сэмпле подбирается CRF под каждый файл так, "
        "чтобы результат достигал указанного значения в дБ (выше — качественнее и крупнее файл). "
        "Ручной CRF выше остаётся резервным значением, если подбор не удался. "
        "Дольше по времени — на каждый файл делается до 6 пробных кодирований.")
    metric_h.addWidget(self._badge_metric)
    metric_h.addStretch()
    fv.addRow(_api.label_with_info("Метрика:", "Выкл — ручной CRF (по умолчанию). XPSNR — CRF подбирается автоматически под целевое значение в дБ."), metric_h)

    fv.addRow(_api.label_with_info("Разрешение:", "Масштаб выходного видео. «Исходное» — без изменений. Уменьшение сохраняет пропорции (без растяжения)."), self.c_res)
    fv.addRow(_api.label_with_info("FPS:", "Частота кадров на выходе. «Исходный (max 30)» — снижает только если выше 30."), self.c_fps)

    # Видео fade in / fade out (через чёрный экран)
    self.ck_vfade_in = _api.QCheckBox("Fade In (из чёрного)"); self.ck_vfade_in.setChecked(False)
    self.s_vfade_in = _api.QDoubleSpinBox(); self.s_vfade_in.setValue(1.0); self.s_vfade_in.setRange(0.0, 60.0); self.s_vfade_in.setSingleStep(0.1)
    self.s_vfade_in.setMaximumWidth(110)
    self.ck_vfade_out = _api.QCheckBox("Fade Out (в чёрный)"); self.ck_vfade_out.setChecked(False)
    self.s_vfade_out = _api.QDoubleSpinBox(); self.s_vfade_out.setValue(1.0); self.s_vfade_out.setRange(0.0, 60.0); self.s_vfade_out.setSingleStep(0.1)
    self.s_vfade_out.setMaximumWidth(110)
    fv.addRow(_api.row_with_info(self.ck_vfade_in, "Плавное появление картинки из чёрного экрана в начале (секунды)"), self.s_vfade_in)
    fv.addRow(_api.row_with_info(self.ck_vfade_out, "Плавный уход картинки в чёрный экран в конце (секунды)"), self.s_vfade_out)

    # Обрезка чёрных полос (cropdetect) — убирает letterbox/pillarbox при перекоде
    self.ck_crop_black = _api.QCheckBox("Обрезать чёрные полосы"); self.ck_crop_black.setChecked(False)
    self._crop_black_row = _api.row_with_info(self.ck_crop_black, "Автоматически определяет и вырезает чёрные поля (letterbox/pillarbox) при перекодировании. Рамка определяется по началу видео через cropdetect.")
    fv.addRow(self._crop_black_row)

    self._fv_form = fv
    gv.setLayout(fv); rv_inner.addWidget(gv)
    # Скрываем строки видео если перекодирование выключено
    self._video_enc_rows = [self.btn_mode_std, self.btn_mode_dark,
                             self.ck_metric_xpsnr,
                             self.s_crf, self.s_pre, self.c_tune, self.c_res, self.c_fps,
                             self._badge_crf,
                             self.s_target_metric, self.lbl_target_metric, self._badge_metric,
                             self.s_vfade_in, self.s_vfade_out, self._crop_black_row]
    def _update_video_enc(checked):
        for w in self._video_enc_rows:
            w.setVisible(checked)
        # Скрываем лейблы через FormLayout
        for row_idx in range(fv.rowCount()):
            lbl = fv.itemAt(row_idx, _api.QFormLayout.ItemRole.LabelRole)
            fld = fv.itemAt(row_idx, _api.QFormLayout.ItemRole.FieldRole)
            if fld:
                wgt = fld.widget()
                if wgt is None and fld.layout():
                    # layout-строка: проверяем первый виджет
                    wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
                if wgt in self._video_enc_rows or (
                    fld.layout() and any(
                        fld.layout().itemAt(i).widget() in self._video_enc_rows
                        for i in range(fld.layout().count())
                        if fld.layout().itemAt(i).widget()
                    )
                ):
                    if lbl and lbl.widget(): lbl.widget().setVisible(checked)
    self.chk_enable_video.toggled.connect(_update_video_enc)
    _update_video_enc(self.chk_enable_video.isChecked())

def _build_images_group(self, rv_inner):
    """Группа «Изображения»: формат, лимиты размера/разрешения, проходы подбора."""
    gavi = _api.QGroupBox("Изображения"); favi = _api.QFormLayout()
    # Выбор выходного формата
    self.c_img_fmt = _api.InvertedWheelComboBox()
    self.c_img_fmt.addItems(["avif" + _api.DEFAULT_TAG, "webp", "png", "jpg", "ico"])
    self.c_img_fmt.setCurrentText("avif" + _api.DEFAULT_TAG)
    self.c_img_fmt.setMinimumWidth(190); self.c_img_fmt.setMaximumWidth(220)
    self.c_img_fmt.setSizeAdjustPolicy(_api.QComboBox.SizeAdjustPolicy.AdjustToContents)
    favi.addRow(_api.label_with_info("Формат:", "Выходной формат изображений. avif — лучшее сжатие, на остальные форматы можно забить"), self.c_img_fmt)

    # Цветовая субдискретизация AVIF (только для avif; при альфе всегда 4:2:0)
    self.c_chroma = _api.InvertedWheelComboBox()
    self.c_chroma.addItems(["4:2:0" + _api.DEFAULT_TAG, "4:2:2", "4:4:4"])
    self.c_chroma.setCurrentText("4:2:0" + _api.DEFAULT_TAG)
    self.c_chroma.setMinimumWidth(140); self.c_chroma.setMaximumWidth(180)
    favi.addRow(_api.label_with_info(
        "Субдискретизация:",
        "Цветовая субдискретизация AVIF. 4:2:0 — минимальный размер файла (хватает для фото). "
        "4:4:4 — максимум цветовой чёткости (текст, графика, скриншоты), но файл крупнее. "
        "Для изображений с прозрачностью всегда 4:2:0."), self.c_chroma)

    # ── Лимит размера файла ──────────────────────────────────────────────
    hlim = _api.QHBoxLayout()
    self.ck_lim = _api.QCheckBox("Сжать до")
    self.ck_lim.setChecked(True)
    self.s_lim = _api.QSpinBox()
    self.s_lim.setRange(0, 50000); self.s_lim.setSuffix(" КБ")
    self.s_lim.setSingleStep(50); self.s_lim.setValue(100)
    hlim.addWidget(self.ck_lim); hlim.addWidget(self.s_lim)
    hlim.addWidget(_api.info_badge("Подбирает качество так, чтобы файл не превышал указанный размер (КБ). 100 для AVIF - достаточное для SiGame"))
    hlim.addStretch()
    # Привязка: спинбокс активен только если галочка включена
    self.ck_lim.toggled.connect(self.s_lim.setEnabled)
    favi.addRow(hlim)

    # ── Проходы подбора под лимит размера ────────────────────────────────
    hpass = _api.QHBoxLayout()
    self.s_passes = _api.QSpinBox()
    self.s_passes.setRange(1, 8); self.s_passes.setValue(4)
    hpass.addWidget(_api.QLabel("Проходы подбора:")); hpass.addWidget(self.s_passes)
    hpass.addWidget(_api.info_badge("Сколько проб качества делать при подборе под лимит размера (бинарный поиск). Больше — точнее под лимит, но дольше. Работает для avif / webp / jpg. По умолчанию 4, максимум 8."))
    hpass.addStretch()
    self.ck_lim.toggled.connect(self.s_passes.setEnabled)
    self.s_passes.setEnabled(self.ck_lim.isChecked())
    favi.addRow(hpass)

    # ── CQ-level: фиксированное качество AVIF (используется, когда лимит
    # размера выше выключен — при включённом лимите качество подбирается
    # автоматически бинарным поиском независимо от этого значения, поэтому
    # при включённом «Сжать до» поле визуально отключается) ─────────────
    self.s_cq = _api.QSpinBox()
    self.s_cq.setRange(0, 63); self.s_cq.setValue(30)
    self.s_cq.setMaximumWidth(80)
    self._lbl_cq = _api.label_with_info(
        "--cq-level:",
        "Уровень качества AVIF (libaom-av1, CQ-level: 0 — максимальное качество, 63 — максимальное сжатие). "
        "Применяется только когда выключен лимит «Сжать до» — при включённом лимите качество подбирается "
        "автоматически под нужный размер файла.")
    favi.addRow(self._lbl_cq, self.s_cq)
    # При включённом лимите размера CQ-level не участвует в кодировании —
    # отключаем визуально (темнее), чтобы не создавать видимость выбора.
    self.ck_lim.toggled.connect(lambda on: self.s_cq.setEnabled(not on))
    self.ck_lim.toggled.connect(lambda on: self._lbl_cq.setEnabled(not on))
    self.s_cq.setEnabled(not self.ck_lim.isChecked())
    self._lbl_cq.setEnabled(not self.ck_lim.isChecked())

    # ── Лимит разрешения ─────────────────────────────────────────────────
    hdim = _api.QHBoxLayout()
    self.ck_dim = _api.QCheckBox("Снизить до")
    self.ck_dim.setChecked(False)
    self.s_dim = _api.QSpinBox()
    self.s_dim.setRange(16, 8000); self.s_dim.setSuffix(" px")
    self.s_dim.setValue(1280); self.s_dim.setEnabled(False)
    hdim.addWidget(self.ck_dim); hdim.addWidget(self.s_dim)
    hdim.addWidget(_api.QLabel("(макс. сторона)"))
    hdim.addWidget(_api.info_badge("Ограничивает максимальную сторону изображения (px) с сохранением пропорций."))
    hdim.addStretch()
    self.ck_dim.toggled.connect(self.s_dim.setEnabled)
    favi.addRow(hdim)

    # ── Отдельные лимиты ширины / высоты (независимо от макс. стороны) ────
    # Применяются вместе с «макс. стороной»: итог — самый строгий предел,
    # пропорции сохраняются, увеличение никогда не делается.
    hwid = _api.QHBoxLayout()
    self.ck_width = _api.QCheckBox("Ширина до"); self.ck_width.setChecked(False)
    self.s_width = _api.QSpinBox(); self.s_width.setRange(16, 8000); self.s_width.setSuffix(" px")
    self.s_width.setValue(1280); self.s_width.setEnabled(False)
    hwid.addWidget(self.ck_width); hwid.addWidget(self.s_width)
    hwid.addWidget(_api.QLabel("(ширина)"))
    hwid.addWidget(_api.info_badge("Ограничивает ШИРИНУ изображения (px), высота подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
    hwid.addStretch()
    self.ck_width.toggled.connect(self.s_width.setEnabled)
    favi.addRow(hwid)

    hhei = _api.QHBoxLayout()
    self.ck_height = _api.QCheckBox("Высота до"); self.ck_height.setChecked(False)
    self.s_height = _api.QSpinBox(); self.s_height.setRange(16, 8000); self.s_height.setSuffix(" px")
    self.s_height.setValue(720); self.s_height.setEnabled(False)
    hhei.addWidget(self.ck_height); hhei.addWidget(self.s_height)
    hhei.addWidget(_api.QLabel("(высота)"))
    hhei.addWidget(_api.info_badge("Ограничивает ВЫСОТУ изображения (px), ширина подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
    hhei.addStretch()
    self.ck_height.toggled.connect(self.s_height.setEnabled)
    favi.addRow(hhei)

    self.sl_aspd = _api._JumpSlider(_api.Qt.Orientation.Horizontal); self.sl_aspd.setRange(0, 8); self.sl_aspd.setValue(2)
    # Перезаписывать ИСХОДНИК: результат сохраняется под именем оригинала
    # (без суффикса «_Сжатый»), а сам исходный файл удаляется. По умолчанию
    # ВЫКЛ — операция необратима (оригинал не восстановить).
    self.ck_overwrite_src = _api.QCheckBox("Перезаписывать исходник")
    self.ck_overwrite_src.setChecked(False)
    favi.addRow(_api.label_with_info("Скорость:", "левее — медленнее и компактнее файл, правее — быстрее, но больше"), self.sl_aspd)
    favi.addRow(_api.row_with_info(self.ck_overwrite_src, "ОПАСНО: удаляет исходное изображение и оставляет только сжатую версию (с именем оригинала, без «_Сжатый»). Оригинал не восстановить. По умолчанию выключено."))
    self._favi_form = favi
    gavi.setLayout(favi); rv_inner.addWidget(gavi)
