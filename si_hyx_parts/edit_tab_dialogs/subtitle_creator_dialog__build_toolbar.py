# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleCreatorDialog: _build_toolbar. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


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
