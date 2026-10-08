# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обработка: группы настроек видео и картинок, профили, папка вывода и быстрые действия с очередью."""
import tabs as _api


class MediaTabSettingsMixin:
    """Обработка: группы настроек видео и картинок, профили, папка вывода и быстрые действия с очередью."""

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

        # ── Продвинутые настройки кодирования (Тюнинг / Метрика-XPSNR / CQ-level) ─
        # Редко нужны и путают в базовом сценарии — скрыты по умолчанию, включаются
        # ОДНИМ переключателем в Настройках (см. set_advanced_encode_visible).

    def _build_footer(self, l, right_container, right_layout, rv_inner, rw, w):
        """Футер (счётчик потоков, кнопки) и финальная сборка правой панели."""
        self._adv_encode_widgets_fv = [self.c_tune, self.ck_metric_xpsnr,
                                        self.s_target_metric, self.lbl_target_metric,
                                        self._badge_metric]
        self._adv_encode_widgets_favi = [self.s_cq, self._lbl_cq]
        self._show_advanced_encode = False
        self.chk_enable_video.toggled.connect(lambda _c: self._apply_advanced_encode_visibility())
        self._apply_advanced_encode_visibility()

        rv_inner.addStretch(); w.setLayout(rv_inner); rw.setWidget(w); right_layout.addWidget(rw)

        # ── Низ правой панели: приоритет процесса + счётчик задействованных потоков ──
        foot = _api.QWidget(); foot_l = _api.QHBoxLayout(foot); foot_l.setContentsMargins(6, 0, 6, 2)
        foot_l.addWidget(_api.QLabel("Приоритет:"))
        self.c_priority = _api.InvertedWheelComboBox()
        self.c_priority.addItems(["Низкий", "Обычный", "Высокий"])
        self.c_priority.setCurrentText("Обычный")
        self.c_priority.setMaximumWidth(150)
        # Приоритет сохраняем СВОИМ изолированным write (read-modify-write только
        # ключа 'priority'), а не только общим _save_settings_now: тот собирает
        # ВЕСЬ словарь настроек и при любой ошибке сборки молча НИЧЕГО не пишет
        # (см. _collect_settings → {}), из-за чего смена приоритета терялась.
        self.c_priority.currentTextChanged.connect(self._persist_priority)
        foot_l.addWidget(self.c_priority)
        foot_l.addWidget(_api.info_badge("Приоритет процессов кодирования (ffmpeg) в системе. Высокий — кодирует быстрее; на Низком ПК отзывчивее."))
        foot_l.addStretch()
        # Всего логических потоков ЦП на этой машине — показываем сразу (0/N),
        # а не 0/0, чтобы было видно потенциал ещё до запуска обработки.
        self._cpu_threads = max(1, _api.cpu_thread_count())
        self.lbl_threads = _api.QLabel(f"Параллельных задач: 0/{self._cpu_threads}")
        self.lbl_threads.setToolTip(
            "Занятые логические потоки ЦП. Видео/аудио кодируются по одному файлу, "
            "но SVT-AV1 нагружает все ядра — поэтому показывается полное число потоков. "
            "Изображения обрабатываются параллельно (по числу ядер).")
        foot_l.addWidget(self.lbl_threads)
        right_layout.addWidget(foot)

        btn_box = _api.QWidget(); btn_layout = _api.QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 6, 0, 6)
        self.b_run = _api._icon_btn("НАЧАТЬ", 'fa5s.play', color='#1e1e2e'); self.b_run.setObjectName("b_run")
        self.b_stop = _api._icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.b_stop.setObjectName("b_stop"); self.b_stop.setEnabled(False)
        self.b_run.clicked.connect(self.run); self.b_stop.clicked.connect(self.stop)
        btn_layout.addWidget(self.b_run); btn_layout.addWidget(self.b_stop)

        right_layout.addWidget(btn_box); right_container.setLayout(right_layout); l.addWidget(right_container, 0)

        self.shortcut_paste = _api.QShortcut(_api.QKeySequence("Ctrl+V"), self.tree)
        self.shortcut_paste.activated.connect(self.paste_files)
        # Клавиша Delete — удалить выделенные файлы из очереди
        self.shortcut_delete = _api.QShortcut(_api.QKeySequence(_api.Qt.Key.Key_Delete), self.tree)
        self.shortcut_delete.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_delete.activated.connect(self.rem)
        self.tree.itemDoubleClicked.connect(self.on_double_click)

    def _persist_priority(self, text):
        """Изолированно пишет ТОЛЬКО ключ 'priority' (read-modify-write), не трогая
        остальные настройки. Нужен потому, что общий _save_settings_now собирает
        весь словарь разом и при любой ошибке сборки молча не сохраняет ничего —
        тогда смена приоритета не доживала до следующего запуска."""
        try:
            s = _api.load_settings()
            if isinstance(s, dict) and s:
                # Загрузили существующий словарь — дописываем только приоритет.
                s['priority'] = text
                _api.save_settings(s)
            else:
                # Файл пуст/нечитаем: НЕ пишем одинокий ключ (затёр бы остальное),
                # а просим общий сборщик собрать полный словарь.
                self.main._save_settings_now()
        except Exception:
            pass

    def _size_profile_toggle_buttons(self):
        """Резервирует под кнопки «Стандарт»/«Тёмные сцены» ширину, достаточную
        для их ЖИРНОГО (:checked, см. глобальный QSS) начертания — см. пояснение
        в __init__. Меряет реальный полированный шрифт виджета, а не константу."""
        for _b in (self.btn_mode_std, self.btn_mode_dark):
            _b.ensurePolished()
            _orig_font = _b.font()
            _bold_font = _api.QFont(_orig_font); _bold_font.setBold(True)
            _b.setFont(_bold_font)
            _bold_w = _b.sizeHint().width()
            _b.setFont(_orig_font)
            if _b.minimumWidth() < _bold_w:
                _b.setMinimumWidth(_bold_w)

    def _set_preset_mode(self, mode):
        """Переключает профиль кодирования без изменения preset и битрейта аудио."""
        is_dark = (mode == "dark")
        self.btn_mode_std.blockSignals(True);  self.btn_mode_dark.blockSignals(True)
        self.btn_mode_std.setChecked(not is_dark); self.btn_mode_dark.setChecked(is_dark)
        self.btn_mode_std.blockSignals(False); self.btn_mode_dark.blockSignals(False)
        try: self.main._save_settings_now()
        except Exception: pass

    def _video_metric_value(self):
        """'none' | 'xpsnr' — цель авто-подбора CRF (_metric_crf_search
        в workers.py). 'none' — ручной CRF без подбора."""
        return 'xpsnr' if self.ck_metric_xpsnr.isChecked() else 'none'

    @staticmethod
    def _set_form_row_visible(form, widgets, visible):
        """Показывает/скрывает виджеты формы И их лейбл (QFormLayout не двигает
        лейбл сам по себе — ищем строку, где поле — один из widgets или их
        layout-обёртка, см. _update_video_enc)."""
        for w in widgets:
            w.setVisible(visible)
        for row_idx in range(form.rowCount()):
            lbl = form.itemAt(row_idx, _api.QFormLayout.ItemRole.LabelRole)
            fld = form.itemAt(row_idx, _api.QFormLayout.ItemRole.FieldRole)
            if not fld:
                continue
            wgt = fld.widget()
            if wgt is None and fld.layout():
                wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
            matches = wgt in widgets or (
                fld.layout() and any(
                    fld.layout().itemAt(i).widget() in widgets
                    for i in range(fld.layout().count())
                    if fld.layout().itemAt(i).widget()
                )
            )
            if matches and lbl and lbl.widget():
                lbl.widget().setVisible(visible)

    def set_advanced_encode_visible(self, on: bool):
        """Настройки → единый переключатель «Тюнинг / Метрика (XPSNR) / CQ-level».
        Втроём скрыты по умолчанию (редко нужны, путают в базовом сценарии) —
        включаются/выключаются ОДНИМ чекбоксом в Настройках."""
        self._show_advanced_encode = bool(on)
        self._apply_advanced_encode_visibility()

    def _apply_advanced_encode_visibility(self):
        show = bool(getattr(self, '_show_advanced_encode', False))
        # Тюнинг/Метрика имеют смысл только пока включено само перекодирование видео.
        self._set_form_row_visible(self._fv_form, self._adv_encode_widgets_fv,
                                    show and self.chk_enable_video.isChecked())
        self._set_form_row_visible(self._favi_form, self._adv_encode_widgets_favi, show)
        # Колонка "Оценка XPSNR" в таблице файлов имеет смысл только вместе с
        # продвинутыми настройками — прячем её тем же переключателем. Пока она
        # скрыта, оценка и не считается (см. show_metric_col выше): её замер —
        # это отдельное пробное кодирование.
        self.tree.setColumnHidden(8, not show)

    def _video_tune_value(self):
        """Числовое значение SVT-AV1 --tune (0/1/2/4/5, см. c_tune в __init__)
        для финального кодирования (_av1_encoder_args в workers.py)."""
        data = self.c_tune.currentData()
        return int(data) if data is not None else 0

    def _set_tune_value(self, value):
        """Выставляет c_tune по числовому значению tune (обратная операция
        к _video_tune_value) — используется при загрузке сохранённых настроек."""
        idx = self.c_tune.findData(int(value))
        self.c_tune.setCurrentIndex(idx if idx >= 0 else 0)

    def on_url_ctx(self, pos):
        m = _api.QMenu()
        try: cb = _api.QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith("http"):
            a = _api.QAction("Скачать из буфера", self)
            a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(False)))
            a2 = _api.QAction("Скачать аудио из буфера", self)
            a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(True)))
            m.addAction(a); m.addAction(a2); m.addSeparator()
        m.addAction(_api.QAction("Вставить", self, triggered=self.url_edit.paste))
        m.exec(self.url_edit.mapToGlobal(pos))

    def on_double_click(self, item, column):
        """Двойной клик: по готовому файлу — открыть результат в плеере;
        по ещё не обработанному (только добавленному) — запустить
        перекодирование ТОЛЬКО этого файла."""
        try:
            iid = item.data(0, _api.Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            if entry.get('is_done'):
                out_path = entry.get('out_path')
                if out_path and _api.os.path.exists(out_path):
                    self.open_output_file(out_path)
                else:
                    self.open_file_location(item)
            else:
                # Файл ещё в очереди — перекодируем только его
                self._run_items([entry])
        except Exception: pass

    def open_output_file(self, path):
        """Открывает файл в ассоциированном приложении (плеер, просмотрщик)."""
        try:
            if _api.IS_WIN:
                _api.os.startfile(path)
            elif _api.sys.platform == 'darwin':
                _api.subprocess.Popen(['open', path])
            else:
                _api.subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self.main.log(f"Не удалось открыть файл: {e}")

    def _choose_export_dir(self):
        d = _api.QFileDialog.getExistingDirectory(self, "Папка экспорта", self.export_dir or _api.default_download_dir())
        if d:
            self.export_dir = d
            self._update_export_label()
            try: self.main._save_settings_now()
            except Exception: pass

    def _reset_export_dir(self):
        self.export_dir = ""
        self._update_export_label()
        try: self.main._save_settings_now()
        except Exception: pass

    def _update_export_label(self):
        """Обновляет подпись пути экспорта и видимость кнопки сброса."""
        try:
            if self.export_dir and _api.os.path.isdir(self.export_dir):
                self.lbl_export_dir.setText(self.export_dir)
                self.lbl_export_dir.setToolTip(self.export_dir)
                self.btn_export_reset.setEnabled(True)
            else:
                self.lbl_export_dir.setText("По умолчанию экспорт в папку исходника")
                self.lbl_export_dir.setToolTip("")
                self.btn_export_reset.setEnabled(False)
        except Exception: pass

    def download_url(self, audio_only=False):
        url = self.url_edit.text().strip()
        if not url: return
        self.url_edit.clear()

        try:
            dl_path = self.main.tab_ytdlp.out.text()
            if not dl_path or not _api.os.path.exists(dl_path): dl_path = _api.default_download_dir()
        except Exception: dl_path = _api.default_download_dir()

        self.main.tab_ytdlp.add_dl_direct(url, audio_only=audio_only, outdir=dl_path)

    def _quick_dl_stop(self):
        """СТОП в строке «Быстрая загрузка» — останавливает активные загрузки.
        Быстрые загрузки выполняются воркер-пулом вкладки «Скачать» (YtdlpTab),
        поэтому останавливаем их там же — как кнопкой СТОП на той вкладке."""
        try:
            self.main.tab_ytdlp.stop_all_dl()
        except Exception as e:
            self.main.log(f"quick stop error: {e}")

    def reset_status(self):
        for i in self.tree.selectedItems():
            iid = i.data(0, _api.Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if entry:
                entry['is_done'] = False
            i.setText(6, "Ожидание")
            i.setText(7, "—")                  # Время перекодирования
            self._proc_started.pop(iid, None)
            self._proc_running.discard(iid)
            # Сброс «новых» данных — оставляем только исходные (верхняя строка «было»)
            self._set_pair(i, 2, bottom="—")   # Размер: стало
            self._set_pair(i, 3, bottom="—")   # Битрейт: итог
            self._set_pair(i, 4, bottom="—")   # LUFS: после
            i.setData(0, _api.ITEM_STATUS_ROLE, None)
            i.setData(0, _api.ITEM_COMPARE_ROLE, None)   # снять значок «сравнить»
        self.tree.viewport().update()

    def dragEnterEvent(self, event):
        try:
            mime = event.mimeData()
            if mime and mime.hasUrls(): event.acceptProposedAction()
            else: event.ignore()
        except Exception: event.ignore()

    def dropEvent(self, event):
        try:
            self.window().raise_(); self.window().activateWindow()
            mime = event.mimeData()
            if not mime: return
            if mime.hasUrls():
                paths = [u.toLocalFile() for u in mime.urls() if u.toLocalFile()]
                if paths: self.add_paths(paths)
                event.acceptProposedAction()
            else: event.ignore()
        except Exception as e:
            self.main.log(f"dropEvent error: {e}")
            event.ignore()
