# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_ExportSettingsDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api

# Режимы обрезки, которые кодируют настройками «Обработки» (см. cmb_mode).
_PROCESS_MODES = (4, 5)


def _value(w):
    """Значение виджета-настройки в одном виде для обеих сторон зеркала."""
    if isinstance(w, _api.QAbstractButton):
        return w.isChecked()
    if isinstance(w, _api.QComboBox):
        return w.currentText() if w.isEditable() else w.currentIndex()
    return w.value()


def _set_value(w, v):
    if isinstance(w, _api.QAbstractButton):
        w.setChecked(bool(v))
    elif isinstance(w, _api.QComboBox):
        if w.isEditable():
            w.setCurrentText(str(v))
        else:
            w.setCurrentIndex(int(v))
    else:
        w.setValue(v)


def _changed_signal(w):
    if isinstance(w, _api.QAbstractButton):
        return w.toggled
    if isinstance(w, _api.QComboBox):
        # У редактируемого (FPS) значение — текст: ввод своего числа тоже правка.
        return w.currentTextChanged if w.isEditable() else w.currentIndexChanged
    return w.valueChanged


class _ExportSettingsDialog(_api.QDialog):
    """Настройки экспорта «Монтажа» для «Перекодировать настройками
    «Обработки»»: звук, скорость и видео вкладки «Обработка». Это не копия, а
    зеркало её виджетов: правка здесь ставит значение виджету «Обработки» (с
    его реакциями и сохранением настроек), правка там сразу видна здесь.

    Окно одно на вкладку и живёт вместе с ней (скрывается, а не удаляется):
    связи с виджетами «Обработки» заводятся один раз и не висят на удалённом
    окне."""

    def __init__(self, media_tab, mode_combo=None, parent=None):
        super().__init__(parent)
        self._tm = media_tab
        self._pairs = []             # (виджет «Обработки» или Монтажа, зеркало)
        # Пока окно строится, зеркала шлют сигналы сами (addItem, setRange) —
        # в «Обработку» их не пускаем; значения подтянет pull_all в конце.
        self._syncing = True
        self.setWindowTitle("Настройки экспорта")
        # Своего стиля у окна нет: расцветка — общий стиль приложения, ровно
        # как у самой «Обработки» (синие заголовки групп, светлые подписи,
        # залитая выбранная кнопка профиля). Поэтому и родитель — главное
        # окно, а не вкладка «Монтаж» (см. EditTab._open_export_settings).
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)

        info = _api.QLabel(
            "Те же настройки, что во вкладке «Обработка», — правка здесь меняет их "
            "и там, и наоборот. Применяются в режимах «Перекодировать настройками "
            "«Обработки»» (видео и звук) и «(Аудио) …» (только звук).")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.cmb_mode = None
        self.lbl_mode_hint = _api.QLabel()
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setStyleSheet(f"color: {_api.C['yellow']}; font-size: 11px;")
        if mode_combo is not None:
            row = _api.QHBoxLayout(); row.setSpacing(8)
            row.addWidget(_api.QLabel("Режим обрезки"))
            self.cmb_mode = self._mirror(mode_combo)
            self.cmb_mode.setStyleSheet(mode_combo.styleSheet())
            self.cmb_mode.setSizeAdjustPolicy(
                _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.cmb_mode.setMinimumContentsLength(20)
            row.addWidget(self.cmb_mode, 1)
            lay.addLayout(row)
        lay.addWidget(self.lbl_mode_hint)

        cols = _api.QHBoxLayout(); cols.setSpacing(12)
        left = _api.QVBoxLayout(); left.setSpacing(8)
        left.addWidget(self._build_audio())
        left.addWidget(self._build_speed())
        left.addStretch(1)
        cols.addLayout(left, 1)
        cols.addWidget(self._build_video(), 1)
        lay.addLayout(cols, 1)

        # Правка применяется сразу (зеркало виджетов «Обработки»), кнопка лишь
        # закрывает окно — но подпись и цвет как у сохранения в других окнах.
        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Save)
        btn_save = bb.button(_api.QDialogButtonBox.StandardButton.Save)
        btn_save.setText("Сохранить")
        btn_save.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(f"""
            QPushButton {{ background: {_api.C['green']}; color: #11111b; border: none;
                border-radius: 6px; padding: 6px 16px; font-weight: 600; }}
            QPushButton:hover {{ background: {_api.C['green2']}; }}
        """)
        bb.accepted.connect(self.hide)
        lay.addWidget(bb)
        self._syncing = False
        self.pull_all()

    # ── Зеркало ──────────────────────────────────────────────────────────────
    def _mirror(self, src, text=None):
        """Виджет того же типа и с теми же пределами, что src, связанный с
        ним в обе стороны."""
        if isinstance(src, _api.QCheckBox):
            dst = _api.QCheckBox(src.text() if text is None else text)
        elif isinstance(src, _api.QComboBox):
            dst = type(src)()
            for i in range(src.count()):
                dst.addItem(src.itemIcon(i), src.itemText(i), src.itemData(i))
            if src.isEditable():
                dst.setEditable(True)
                dst.setInsertPolicy(_api.QComboBox.InsertPolicy.NoInsert)
                if src.lineEdit() is not None:
                    dst.lineEdit().setPlaceholderText(src.lineEdit().placeholderText())
            # Пункты короткие (кроме режима обрезки — его ширину держит строка):
            # видны целиком, без «по умо…».
            dst.setSizeAdjustPolicy(_api.QComboBox.SizeAdjustPolicy.AdjustToContents)
            if src.isEditable():
                dst.setMinimumWidth(src.minimumWidth() + 20)
        elif isinstance(src, _api.QSlider):
            dst = _api.QSlider(src.orientation())
            dst.setRange(src.minimum(), src.maximum())
            dst.setSingleStep(src.singleStep()); dst.setPageStep(src.pageStep())
        else:                                     # QSpinBox / QDoubleSpinBox
            dst = type(src)()
            if isinstance(src, _api.QDoubleSpinBox):
                dst.setDecimals(src.decimals())
            dst.setRange(src.minimum(), src.maximum())
            dst.setSingleStep(src.singleStep())
            dst.setPrefix(src.prefix()); dst.setSuffix(src.suffix())
            dst.setMaximumWidth(max(80, src.maximumWidth() if src.maximumWidth() < 1000 else 110))
        dst.setToolTip(src.toolTip())
        self._pairs.append((src, dst))
        _changed_signal(dst).connect(lambda *_a, s=src, d=dst: self._push(s, d))
        _changed_signal(src).connect(lambda *_a, s=src, d=dst: self._pull(s, d))
        return dst

    def _push(self, src, dst):
        """Правка здесь → виджет «Обработки» (без глушения сигналов: пусть
        сработает всё, что там завязано на правку, — сохранение, видимость)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            if _value(src) != _value(dst):
                _set_value(src, _value(dst))
        finally:
            self._syncing = False
        self._refresh_states()

    def _pull(self, src, dst):
        """Правка в «Обработке» → здесь."""
        if self._syncing:
            return
        try:
            v = _value(src)
            if _value(dst) != v:
                dst.blockSignals(True)
                try:
                    _set_value(dst, v)
                finally:
                    dst.blockSignals(False)
            self._refresh_states()
        except RuntimeError:
            pass                                  # окно или виджет уже удалены (выход)

    def pull_all(self):
        """Всё — заново из «Обработки». Нужен при показе окна: часть правок
        там идёт с заглушёнными сигналами (профиль, загрузка настроек)."""
        for src, dst in self._pairs:
            self._pull(src, dst)
        self._pull_profile()
        self._refresh_states()

    # ── Группы ───────────────────────────────────────────────────────────────
    @staticmethod
    def _row(*widgets, stretch=True):
        h = _api.QHBoxLayout(); h.setSpacing(6)
        for w in widgets:
            if isinstance(w, str):
                w = _api.QLabel(w)
            h.addWidget(w)
        if stretch:
            h.addStretch(1)
        return h

    def _build_audio(self):
        tm = self._tm
        g = _api.QGroupBox("Звук"); f = _api.QVBoxLayout(g); f.setSpacing(6)
        self.ck_no_audio = self._mirror(tm.ck_no_audio)
        self.ck_norm = self._mirror(tm.ck_norm)
        self.s_tgt = self._mirror(tm.s_tgt)
        self.s_lra = self._mirror(tm.s_lra)
        self.s_tp = self._mirror(tm.s_tp)
        self.ck_fade_in = self._mirror(tm.ck_fade_in)
        self.s_fade_in = self._mirror(tm.s_fade_in)
        self.ck_fade = self._mirror(tm.ck_fade)
        self.s_fade = self._mirror(tm.s_fade)
        self.c_abitrate = self._mirror(tm.c_abitrate)
        self.ck_deg = self._mirror(tm.ck_deg)
        self.s_hz = self._mirror(tm.s_hz)
        self.ck_u8 = self._mirror(tm.ck_u8)
        self.s_lp = self._mirror(tm.s_lp)
        self.s_hp = self._mirror(tm.s_hp)
        self.s_deg_gain = self._mirror(tm.s_deg_gain)
        f.addLayout(self._row(self.ck_norm))
        f.addLayout(self._row("LUFS:", self.s_tgt, "LRA:", self.s_lra, "TP:", self.s_tp))
        f.addLayout(self._row(self.ck_fade_in, self.s_fade_in))
        f.addLayout(self._row(self.ck_fade, self.s_fade))
        f.addLayout(self._row("Битрейт аудио (Opus), кбит/с:", self.c_abitrate))
        f.addLayout(self._row(self.ck_deg))
        self._deg_box = _api.QWidget()
        dl = _api.QVBoxLayout(self._deg_box); dl.setContentsMargins(18, 0, 0, 0); dl.setSpacing(6)
        dl.addLayout(self._row("Hz:", self.s_hz, self.ck_u8))
        dl.addLayout(self._row("Lowpass:", self.s_lp, "Highpass:", self.s_hp))
        dl.addLayout(self._row("Degrade vol (dB):", self.s_deg_gain))
        f.addWidget(self._deg_box)
        f.addLayout(self._row(self.ck_no_audio))
        self._audio_widgets = [self.ck_norm, self.s_tgt, self.s_lra, self.s_tp,
                               self.ck_fade_in, self.s_fade_in, self.ck_fade, self.s_fade,
                               self.c_abitrate, self.ck_deg, self._deg_box]
        return g

    def _build_speed(self):
        w = _api.QWidget(); h = _api.QHBoxLayout(w); h.setContentsMargins(8, 2, 8, 2)
        self.s_spd = self._mirror(self._tm.s_spd)
        self.s_spd.setToolTip("Изменение скорости видео и звука. 100% = без изменений")
        h.addWidget(_api.QLabel("Скорость:")); h.addWidget(self.s_spd); h.addStretch(1)
        return w

    def _build_video(self):
        tm = self._tm
        g = _api.QGroupBox("Видео"); f = _api.QVBoxLayout(g); f.setSpacing(6)
        self.chk_enable_video = self._mirror(tm.chk_enable_video)
        self.chk_enable_video.setToolTip(
            "Выключено — видео копируется как есть, меняется только звук. "
            "Включено — перекодирование в AV1 (SVT-AV1).")
        f.addLayout(self._row(self.chk_enable_video))

        self._video_box = _api.QWidget()
        vl = _api.QVBoxLayout(self._video_box); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(6)
        self.btn_mode_std = _api.QPushButton(tm.btn_mode_std.text())
        self.btn_mode_dark = _api.QPushButton(tm.btn_mode_dark.icon(), tm.btn_mode_dark.text())
        for b, mode in ((self.btn_mode_std, "std"), (self.btn_mode_dark, "dark")):
            b.setCheckable(True)
            b.setToolTip(getattr(tm, "btn_mode_" + mode).toolTip())
            b.clicked.connect(lambda _c=False, m=mode: self._set_profile(m))
        vl.addLayout(self._row("Профиль:", self.btn_mode_std, self.btn_mode_dark))

        self.s_crf = self._mirror(tm.s_crf)
        self.s_pre = self._mirror(tm.s_pre)
        self.s_crf.setToolTip("CRF — качество: меньше = качественнее, но больше файл (1–63)")
        self.s_pre.setToolTip("Preset — скорость кодирования: 0 медленно и качественно … 13 быстро")
        vl.addLayout(self._row("CRF / Preset:", self.s_crf, self.s_pre))
        self.c_tune = self._mirror(tm.c_tune)
        vl.addLayout(self._row("Тюнинг:", self.c_tune))
        self.ck_metric_xpsnr = self._mirror(tm.ck_metric_xpsnr)
        self.s_target_metric = self._mirror(tm.s_target_metric)
        self.s_target_metric.setMaximumWidth(140)
        self.lbl_target_metric = _api.QLabel()
        self.lbl_target_metric.setMinimumWidth(48)
        self.s_target_metric.valueChanged.connect(
            lambda v: self.lbl_target_metric.setText(f"{v} дБ"))
        vl.addLayout(self._row("Метрика:", self.ck_metric_xpsnr, self.s_target_metric,
                               self.lbl_target_metric))
        self.c_res = self._mirror(tm.c_res)
        vl.addLayout(self._row("Разрешение:", self.c_res))
        self.c_fps = self._mirror(tm.c_fps)
        vl.addLayout(self._row("FPS:", self.c_fps))
        self.ck_vfade_in = self._mirror(tm.ck_vfade_in)
        self.s_vfade_in = self._mirror(tm.s_vfade_in)
        self.ck_vfade_out = self._mirror(tm.ck_vfade_out)
        self.s_vfade_out = self._mirror(tm.s_vfade_out)
        vl.addLayout(self._row(self.ck_vfade_in, self.s_vfade_in))
        vl.addLayout(self._row(self.ck_vfade_out, self.s_vfade_out))
        self.ck_crop_black = self._mirror(tm.ck_crop_black)
        vl.addLayout(self._row(self.ck_crop_black))
        f.addWidget(self._video_box)
        f.addStretch(1)
        return g

    # ── Профиль и состояние ──────────────────────────────────────────────────
    def _set_profile(self, mode):
        try:
            self._tm._set_preset_mode(mode)
        except Exception:
            pass
        self._pull_profile()

    def _pull_profile(self):
        try:
            dark = bool(self._tm.btn_mode_dark.isChecked())
        except RuntimeError:
            return
        self.btn_mode_std.setChecked(not dark)
        self.btn_mode_dark.setChecked(dark)

    def _refresh_states(self):
        """Что доступно — как в «Обработке»: «Удалить аудио» гасит звук,
        «Ухудшить» открывает свои параметры, без перекодирования видео его
        настройки не действуют, цель XPSNR — только с метрикой."""
        no_audio = self.ck_no_audio.isChecked()
        for w in self._audio_widgets:
            w.setEnabled(not no_audio)
        self._deg_box.setVisible(self.ck_deg.isChecked() and not no_audio)
        self._video_box.setEnabled(self.chk_enable_video.isChecked())
        xp = self.ck_metric_xpsnr.isChecked()
        self.s_target_metric.setEnabled(xp)
        self.lbl_target_metric.setEnabled(xp)
        self.lbl_target_metric.setText(f"{self.s_target_metric.value()} дБ")
        if self.cmb_mode is not None:
            idx = self.cmb_mode.currentIndex()
            if idx in _PROCESS_MODES:
                self.lbl_mode_hint.setVisible(False)
            else:
                self.lbl_mode_hint.setText(
                    f"Сейчас режим «{self.cmb_mode.currentText()}» — эти настройки "
                    "при экспорте не применяются.")
                self.lbl_mode_hint.setVisible(True)
        else:
            self.lbl_mode_hint.setVisible(False)

    def _size_profile_buttons(self):
        """Ширина «Стандарт»/«Тёмные сцены» — под жирное начертание (:checked
        в глобальном QSS), иначе активная подпись обрезается; как
        _size_profile_toggle_buttons в «Обработке»."""
        for b in (self.btn_mode_std, self.btn_mode_dark):
            b.ensurePolished()
            font = b.font()
            bold = _api.QFont(font); bold.setBold(True)
            b.setFont(bold)
            w = b.sizeHint().width()
            b.setFont(font)
            b.setMinimumWidth(max(b.minimumWidth(), w))

    def showEvent(self, ev):
        self.pull_all()
        self._size_profile_buttons()
        super().showEvent(ev)

_ExportSettingsDialog.__module__ = _api.__name__
_api._ExportSettingsDialog = _ExportSettingsDialog
