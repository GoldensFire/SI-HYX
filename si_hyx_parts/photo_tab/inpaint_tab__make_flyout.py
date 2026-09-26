# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: _make_flyout. Public namespace: photo_tab."""
import photo_tab as _api


# ── Всплывающие панели «Фигуры»/«Текст» (flyout, как в Photoshop) ─────────
def _make_flyout(self):
    """Создаёт пустую всплывающую панель, пристыкованную к вкладке. НЕ Qt.Popup —
        тот грэбит мышь и съедает самый первый клик (клик вне панели, например по
        холсту, тратился на её закрытие, а не доходил до холста), из-за чего нельзя
        было сразу же перетащить текст под панелью. Плавающее Tool-окно без грэба
        не мешает кликам по холсту; закрывается явно при смене инструмента
        (см. _set_tool)."""
    f = _api.QFrame(self, _api.Qt.WindowType.Tool | _api.Qt.WindowType.FramelessWindowHint)
    f.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating)
    f.setObjectName("toolFlyout")
    f.setStyleSheet(
        "QFrame#toolFlyout{background:#181825;border:1px solid #45475a;"
        "border-radius:8px;} QLabel{color:#cdd6f4;}")
    return f

def _build_shape_flyout(self):
    self._shape_flyout = self._make_flyout()
    v = _api.QVBoxLayout(self._shape_flyout)
    v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
    self._shape_btn_group = _api.QButtonGroup(self._shape_flyout)
    self._shape_btn_group.setExclusive(True)
    self._shape_tool_btns = {}
    defs = [("Прямоугольник", 'fa5s.square', _api.InpaintCanvas.TOOL_RECT),
            ("Эллипс", 'fa5s.circle', _api.InpaintCanvas.TOOL_ELLIPSE),
            ("Линия", 'fa5s.minus', _api.InpaintCanvas.TOOL_LINE),
            ("Стрелка", 'fa5s.long-arrow-alt-right', _api.InpaintCanvas.TOOL_ARROW)]
    for text, icon, tool in defs:
        b = _api._icon_btn(text, icon); b.setCheckable(True)
        self._shape_btn_group.addButton(b)
        self._shape_tool_btns[tool] = b
        b.clicked.connect(lambda _=False, t=tool: self._pick_shape(t))
        v.addWidget(b)
    self._shape_tool_btns[self._cur_shape_tool].setChecked(True)
    self.chk_fill = _api.QCheckBox("Заливка фигур")
    self.chk_fill.setToolTip("Заливать прямоугольник/эллипс цветом кисти "
                             "(иначе только контур).")
    self.chk_fill.toggled.connect(lambda val: self.canvas.set_shape_fill(val))
    v.addWidget(self.chk_fill)

def _build_text_flyout(self):
    self._text_flyout = self._make_flyout()
    v = _api.QVBoxLayout(self._text_flyout)
    v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
    frow = _api.QHBoxLayout(); frow.addWidget(_api.QLabel("Шрифт:"))
    self.cmb_font = _api.QFontComboBox()
    self.cmb_font.setToolTip("Системный шрифт для инструмента «Текст».")
    frow.addWidget(self.cmb_font, 1); v.addLayout(frow)
    srow = _api.QHBoxLayout(); srow.addWidget(_api.QLabel("Размер:"))
    self.spin_font = _api.QSpinBox()
    self.spin_font.setRange(6, 1000); self.spin_font.setValue(48)
    self.spin_font.setSuffix(" px")
    self.spin_font.setToolTip("Высота текста в пикселях изображения.")
    srow.addWidget(self.spin_font, 1); v.addLayout(srow)
    crow = _api.QHBoxLayout(); crow.addWidget(_api.QLabel("Цвет:"))
    self.btn_text_color = _api.QPushButton()
    self.btn_text_color.setFixedSize(28, 22)
    self.btn_text_color.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self.btn_text_color.setToolTip("Цвет текста. Клик по уже написанному тексту "
                                   "выделяет его — можно поменять цвет/шрифт/обводку.")
    self.btn_text_color.clicked.connect(self._pick_text_color)
    crow.addWidget(self.btn_text_color); crow.addStretch(1)
    v.addLayout(crow)
    self._text_color = _api.QColor(255, 255, 255)
    self._update_text_color_swatch(self._text_color)

    _sep = _api.QFrame(); _sep.setFrameShape(_api.QFrame.Shape.HLine)
    _sep.setStyleSheet("color:#45475a;")
    v.addWidget(_sep)
    self.chk_text_stroke = _api.QCheckBox("Обводка")
    self.chk_text_stroke.setToolTip("Контур текста (как в Photoshop).")
    v.addWidget(self.chk_text_stroke)
    strow = _api.QHBoxLayout(); strow.addWidget(_api.QLabel("Толщина:"))
    self.spin_stroke_w = _api.QSpinBox()
    self.spin_stroke_w.setRange(1, 60); self.spin_stroke_w.setValue(4)
    self.spin_stroke_w.setSuffix(" px")
    strow.addWidget(self.spin_stroke_w, 1); v.addLayout(strow)
    scrow = _api.QHBoxLayout(); scrow.addWidget(_api.QLabel("Цвет обводки:"))
    self.btn_stroke_color = _api.QPushButton()
    self.btn_stroke_color.setFixedSize(28, 22)
    self.btn_stroke_color.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self.btn_stroke_color.clicked.connect(self._pick_stroke_color)
    scrow.addWidget(self.btn_stroke_color); scrow.addStretch(1)
    v.addLayout(scrow)
    self._stroke_color = _api.QColor(0, 0, 0)
    self._update_stroke_color_swatch(self._stroke_color)

    self.cmb_font.currentFontChanged.connect(lambda *_: self._update_text_font())
    self.spin_font.valueChanged.connect(lambda *_: self._update_text_font())
    self.chk_text_stroke.toggled.connect(lambda *_: self._update_text_stroke())
    self.spin_stroke_w.valueChanged.connect(lambda *_: self._update_text_stroke())

def _update_text_color_swatch(self, color):
    self.btn_text_color.setStyleSheet(
        f"background-color: {color.name()}; border:1px solid #585b70; border-radius:3px;")

def _update_stroke_color_swatch(self, color):
    self.btn_stroke_color.setStyleSheet(
        f"background-color: {color.name()}; border:1px solid #585b70; border-radius:3px;")

def _active_text_obj(self):
    """Плавающий (ещё не вжатый) текстовый объект, если он сейчас выделен."""
    p = getattr(self.canvas, "_pending", None)
    return p if (p is not None and p.get('kind') == 'text') else None

def _on_text_selected(self):
    """Текст создан/выбран кликом — подтягиваем его текущие параметры в
        панель (иначе она показывала бы значения по умолчанию для СЛЕДУЮЩЕГО
        текста, а не выделенного) и открываем панель."""
    obj = self._active_text_obj()
    if obj is not None:
        f = obj['font']
        self.cmb_font.blockSignals(True); self.spin_font.blockSignals(True)
        self.cmb_font.setCurrentFont(f)
        self.spin_font.setValue(max(6, f.pixelSize() if f.pixelSize() > 0 else 48))
        self.cmb_font.blockSignals(False); self.spin_font.blockSignals(False)
        self._text_color = _api.QColor(obj['color'])
        self._update_text_color_swatch(self._text_color)
        sw = float(obj.get('stroke_width', 0) or 0)
        self._stroke_color = _api.QColor(obj.get('stroke_color', _api.QColor(0, 0, 0)))
        self.chk_text_stroke.blockSignals(True); self.spin_stroke_w.blockSignals(True)
        self.chk_text_stroke.setChecked(sw > 0)
        if sw > 0:
            self.spin_stroke_w.setValue(int(round(sw)))
        self.chk_text_stroke.blockSignals(False); self.spin_stroke_w.blockSignals(False)
        self._update_stroke_color_swatch(self._stroke_color)
    self.btn_text.setChecked(True)
    # Popup сам делает mouse-grab при show() — если он уже открыт, повторный
    # show() посреди перетаскивания текста срывает драг (грэб перехватывает
    # move/release у холста). Не переоткрываем, если панель и так на экране.
    if not self._text_flyout.isVisible():
        self._show_flyout(self._text_flyout, self.btn_text)

def _pick_text_color(self):
    col = _api.QColorDialog.getColor(self._text_color, self, "Цвет текста")
    if not col.isValid():
        return
    self._text_color = col
    self._update_text_color_swatch(col)
    self.canvas.set_text_color(col)
    obj = self._active_text_obj()
    if obj is not None:
        obj['color'] = _api.QColor(col)
        self.canvas.update()

def _pick_stroke_color(self):
    col = _api.QColorDialog.getColor(self._stroke_color, self, "Цвет обводки")
    if not col.isValid():
        return
    self._stroke_color = col
    self._update_stroke_color_swatch(col)
    self.canvas.set_text_stroke(self.canvas._text_stroke_width, col)
    obj = self._active_text_obj()
    if obj is not None and obj.get('stroke_width', 0):
        obj['stroke_color'] = _api.QColor(col)
        self.canvas.update()

def _update_text_stroke(self):
    width = float(self.spin_stroke_w.value()) if self.chk_text_stroke.isChecked() else 0.0
    self.canvas.set_text_stroke(width, self._stroke_color)
    obj = self._active_text_obj()
    if obj is not None:
        obj['stroke_width'] = width
        obj['stroke_color'] = _api.QColor(self._stroke_color)
        self.canvas.update()

def _on_shapes_btn(self):
    """Клик по «Фигуры»: активируем текущую фигуру и открываем выбор."""
    if hasattr(self, "_text_flyout"):
        self._text_flyout.hide()
    self._set_tool(self._cur_shape_tool)
    self.btn_shapes.setChecked(True)
    self._show_flyout(self._shape_flyout, self.btn_shapes)

def _on_text_btn(self):
    if hasattr(self, "_shape_flyout"):
        self._shape_flyout.hide()
    self._set_tool(_api.InpaintCanvas.TOOL_TEXT)
    self.btn_text.setChecked(True)
    self._show_flyout(self._text_flyout, self.btn_text)

def _pick_shape(self, tool):
    """Выбор конкретной фигуры во всплывающей панели."""
    self._cur_shape_tool = tool
    icons = {_api.InpaintCanvas.TOOL_RECT: 'fa5s.square',
             _api.InpaintCanvas.TOOL_ELLIPSE: 'fa5s.circle',
             _api.InpaintCanvas.TOOL_LINE: 'fa5s.minus',
             _api.InpaintCanvas.TOOL_ARROW: 'fa5s.long-arrow-alt-right'}
    self.btn_shapes.setIcon(_api.get_icon(icons.get(tool, 'fa5s.shapes')))
    self.btn_shapes.setChecked(True)
    self._set_tool(tool)
    if hasattr(self, "_shape_flyout"):
        self._shape_flyout.hide()

def _show_flyout(self, flyout, anchor):
    flyout.adjustSize()
    gpos = anchor.mapToGlobal(_api.QPoint(anchor.width() + 6, 0))
    scr = anchor.screen().availableGeometry() if anchor.screen() else None
    if scr is not None and gpos.x() + flyout.width() > scr.right():
        gpos = anchor.mapToGlobal(_api.QPoint(-flyout.width() - 6, 0))
    if scr is not None and gpos.y() + flyout.height() > scr.bottom():
        gpos.setY(scr.bottom() - flyout.height() - 2)
    flyout.move(gpos)
    flyout.show()
    flyout.raise_()

def insert_mode_switch(self, widget):
    """PhotoTab вставляет сюда переключатель режимов «Фото» (закреплён сверху
        левой панели, вместо верхней полосы вкладок)."""
    if hasattr(self, "_switch_holder"):
        self._switch_holder.addWidget(widget)

# ── Цвет кисти ────────────────────────────────────────────────────────────
def _update_color_swatch(self, color):
    self.btn_brush_color.setStyleSheet(
        f"background-color: {color.name()}; border:1px solid #585b70; "
        f"border-radius:3px;")

def _pick_brush_color(self):
    # Клик по образцу цвета открывает обычное окно выбора цвета (как в
    # Photoshop). Взять цвет прямо с картинки можно Alt+клик по холсту.
    col = _api.QColorDialog.getColor(self.canvas.brush_color(), self,
                                "Цвет кисти")
    if col.isValid():
        self.canvas.set_brush_color(col)
        self._update_color_swatch(col)

def _update_text_font(self):
    """Собирает QFont из выбранного системного шрифта + размера (px) и отдаёт
        холсту для инструмента «Текст» (по умолчанию для НОВОГО текста; если сейчас
        выделен плавающий текст — меняет и его, живьём, как в Photoshop)."""
    if not hasattr(self, "canvas"):
        return
    f = _api.QFont(self.cmb_font.currentFont())
    f.setPixelSize(int(self.spin_font.value()))
    self.canvas.set_text_font(f)
    obj = self._active_text_obj()
    if obj is not None:
        obj['font'] = _api.QFont(self.canvas._text_font)
        self.canvas.update()

def _on_color_picked(self, col):
    # Цвет, взятый Alt-пипеткой из холста: только обновляем образец (сам
    # цвет кисти холст уже выставил).
    if col.isValid():
        self._update_color_swatch(col)

def _activate_delete_tool(self):
    """«Удалить объект» — это кисть удаления (как Spot Healing Brush в
        Photoshop): просто включаем красную кисть-маску. Дальше закрашенное
        стирается автоматически на отпускании ЛКМ (см. _on_stroke_finished)."""
    if not self.canvas.has_image():
        return
    if not _api._HAS_ORT:
        # Без onnxruntime удаление не сработает — предупреждаем сразу при выборе
        # инструмента (раньше предупреждал клик по кнопке).
        _api.msgbox_warning(self, "Нет onnxruntime",
                            "Для удаления объектов установите onnxruntime:\n\n"
                            "pip install onnxruntime")
        self.btn_run.setChecked(False)
        return
    self._set_tool(_api.InpaintCanvas.TOOL_MASK)

def _on_stroke_finished(self):
    # Кисть удаления как в Photoshop: закрасил объект — сразу убираем закрашенное.
    # Без onnxruntime или во время уже идущей обработки молча ничего не делаем.
    if not _api._HAS_ORT:
        return
    if self._worker is not None and self._worker.isRunning():
        return
    self._run_inpaint()

# ── Реакции UI ───────────────────────────────────────────────────────────
def _set_tool(self, tool):
    # Панели «Фигуры»/«Текст» больше не Qt.Popup (не закрываются сами при клике
    # мимо) — закрываем их явно при смене инструмента, кроме случая, когда сам
    # инструмент — фигура/текст (тогда панель переоткрывает вызвавший метод).
    _flyout_tools = (_api.InpaintCanvas.TOOL_RECT, _api.InpaintCanvas.TOOL_ELLIPSE,
                     _api.InpaintCanvas.TOOL_LINE, _api.InpaintCanvas.TOOL_ARROW,
                     _api.InpaintCanvas.TOOL_TEXT)
    if tool not in _flyout_tools:
        for fly in (getattr(self, "_shape_flyout", None), getattr(self, "_text_flyout", None)):
            if fly is not None:
                fly.hide()
    self.canvas.set_tool(tool)
    # Возвращаем фокус холсту, чтобы WASD/стрелки (панорамирование) работали
    # сразу после клика по кнопке инструмента, а не уходили в кнопку.
    self.canvas.setFocus(_api.Qt.FocusReason.OtherFocusReason)
