# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: _build_ui. Public namespace: photo_tab."""
import photo_tab as _api


# ── Построение интерфейса ────────────────────────────────────────────────
def _build_ui(self):
    # СЛЕВА — все инструменты и кнопки; СПРАВА — холст.
    root = _api.QHBoxLayout(self)
    root.setContentsMargins(8, 8, 8, 8)
    root.setSpacing(8)

    # Левая колонка: ЗАКРЕПЛЁННЫЙ сверху переключатель режима (его вставляет
    # PhotoTab) + ПРОКРУЧИВАЕМАЯ панель инструментов под ним (раньше нижние
    # кнопки «Сохранение» не помещались — теперь появляется скроллбар).
    left_col = _api.QWidget(); left_col.setFixedWidth(264)
    self._left_col = left_col   # PhotoTab подгонит ширину под переключатель режима
    left_col_l = _api.QVBoxLayout(left_col)
    left_col_l.setContentsMargins(0, 0, 0, 0); left_col_l.setSpacing(8)
    self._switch_holder = _api.QVBoxLayout()
    self._switch_holder.setContentsMargins(0, 0, 0, 0)
    left_col_l.addLayout(self._switch_holder)

    scroll = _api.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    left_w = _api.QWidget()
    left = _api.QVBoxLayout(left_w)
    left.setContentsMargins(0, 0, 6, 0); left.setSpacing(8)

    self.btn_open = _api._icon_btn("Открыть изображение", 'fa5s.folder-open')
    self.btn_open.clicked.connect(self._open)
    left.addWidget(self.btn_open)

    # ── Инструменты ──────────────────────────────────────────────────────
    grp_tools = _api.QGroupBox("Инструменты")
    tl = _api.QVBoxLayout(grp_tools); tl.setSpacing(6)
    self.tool_group = _api.QButtonGroup(self)
    self.tool_group.setExclusive(True)
    self.btn_move = self._tool_btn("Курсор", 'fa5s.mouse-pointer',
                                   "Выделять и перемещать наложенное изображение (второй слой); "
                                   "тяните за уголки/стороны — меняется размер. Esc или клик вне — "
                                   "снять выделение, Enter — вжать слой. Инструмент по умолчанию.")
    self.btn_brush = self._tool_btn("Кисть", 'fa5s.paint-brush',
                                    "Рисуйте прямо по фото выбранным цветом — мазок вживается в "
                                    "картинку (обычная кисть, как в Paint). Цвет — в блоке «Кисть» "
                                    "ниже, Alt+клик — пипетка цвета. Это НЕ удаление объектов.")
    self.btn_erase = self._tool_btn("Ластик", 'fa5s.eraser',
                                    "Стирает мазки «Кисти» (то, что вы нарисовали поверх фото). "
                                    "Размер — ползунком «Кисть».")
    self.btn_crop = self._tool_btn("Кадрировать", 'fa5s.crop-alt',
                                   "Выделите прямоугольник и нажмите «Применить» прямо на холсте (или Enter)")
    self.btn_blur = self._tool_btn("Размытие", 'fa5s.tint',
                                   "Замыливает фото там, где провели кистью (лица, номера, "
                                   "фон). Размер — ползунком «Кисть», силу — ползунком "
                                   "«Степень размытия» ниже. Ctrl+Z отменяет мазок.")
    # «Удалить объект» — это инструмент-кисть удаления (как Spot Healing Brush в
    # Photoshop): выбрал → закрашиваешь красным объект/водяной знак → он сразу
    # стирается, а фон дорисовывает нейросеть. Отдельной кнопки «выделить»
    # больше нет — выделение и есть нажатие этой кнопки.
    self.btn_run = self._tool_btn("Удалить объект", 'fa5s.magic',
                                  "Кисть удаления (как в Photoshop): выберите и закрасьте объект/"
                                  "водяной знак — он сотрётся, а фон дорисует нейросеть.")
    # «Удалить фон» — одноразовое действие (НЕ инструмент-кисть): нейросеть
    # RMBG-2.0 отделяет объект от фона, фон становится прозрачным (как «Удалить
    # фон» в Photoshop). Поэтому НЕ кладём её в tool_group (не залипает).
    # «Удалить чёрные полосы» — тоже одноразовое действие (не инструмент-кисть):
    # находит чёрную рамку по краям и сразу кадрирует по ней. Детект общий с
    # вкладкой «Обработка» (ProcessWorker), чтобы картинка и видео резались
    # одинаково.
    self.btn_bars = _api._icon_btn("Удалить чёрные полосы", 'fa5s.compress-arrows-alt')
    self.btn_bars.setToolTip("Обрезать чёрные полосы по краям изображения "
                             "(тот же детект, что во вкладке «Обработка»).")
    self.btn_bg = _api._icon_btn("Удалить фон", 'fa5s.cut')
    self.btn_bg.setToolTip("Удалить фон автоматически (нейросеть RMBG-2.0): объект "
                           "остаётся, фон становится прозрачным. Сохраняйте в PNG.")
    # Фигуры и текст переехали в отдельный блок «Фигуры и текст» ниже (кнопки
    # «Фигуры»/«Текст» с всплывающими панелями, как flyout в Photoshop).
    # «Курсор» — инструмент по умолчанию и первый в списке.
    self.btn_move.setChecked(True)
    for b in (self.btn_move, self.btn_brush, self.btn_erase, self.btn_crop,
              self.btn_blur):
        self.tool_group.addButton(b); tl.addWidget(b)
    # Степень размытия — сразу под кнопкой «Размытие» (это её параметр).
    row_blur = _api.QHBoxLayout()
    row_blur.setContentsMargins(0, 0, 0, 0); row_blur.setSpacing(5)
    row_blur.addWidget(_api.QLabel("Степень:"))
    self.sld_blur = _api._JumpSlider(_api.Qt.Orientation.Horizontal)
    self.sld_blur.setRange(1, 60); self.sld_blur.setValue(12)
    self.sld_blur.setToolTip("Насколько сильно замыливать под кистью "
                             "(радиус размытия в пикселях изображения).")
    self.sld_blur.valueChanged.connect(self._on_blur_strength)
    row_blur.addWidget(self.sld_blur, 1)
    self.lbl_blur = _api.QLabel("12"); self.lbl_blur.setFixedWidth(30)
    row_blur.addWidget(self.lbl_blur)
    tl.addLayout(row_blur)
    # Рядом с «Кадрировать» по смыслу, но ставим после ползунка размытия, чтобы
    # не разрывать пару «Размытие» + его «Степень».
    tl.addLayout(self._tool_row(
        self.btn_bars,
        "Ищет чёрную рамку по краям (как «Обрезать чёрные полосы» во вкладке "
        "«Обработка») и сразу кадрирует по ней. Если полос нет — ничего не "
        "меняет. Ctrl+Z отменяет."))
    self.tool_group.addButton(self.btn_run)
    # «Удалить объект» и «Удалить фон» — со значком ⓘ и кратким описанием рядом
    # (по просьбе: что именно делает каждая кнопка).
    tl.addLayout(self._tool_row(
        self.btn_run,
        "«Удалить объект» — кисть удаления (как Spot Healing Brush в Photoshop). "
        "Выберите её и закрасьте красным лишний объект/водяной знак/надпись — на "
        "отпускании кнопки мыши закрашенное стирается, а фон под ним дорисовывает "
        "Используется нейросеть LaMa OnnX. Может медленно работать на слабом процессоре"))
    tl.addLayout(self._tool_row(
        self.btn_bg,
        "Нейросеть RMBG-2.0 находит "
        "главный объект и делает весь фон прозрачным. Первый запуск дольше — грузится модель (~360 МБ). "
        ))
    self.btn_move.clicked.connect(lambda: self._set_tool(_api.InpaintCanvas.TOOL_MOVE))
    self.btn_brush.clicked.connect(lambda: self._set_tool(_api.InpaintCanvas.TOOL_BRUSH))
    self.btn_erase.clicked.connect(lambda: self._set_tool(_api.InpaintCanvas.TOOL_ERASE))
    self.btn_crop.clicked.connect(lambda: self._set_tool(_api.InpaintCanvas.TOOL_CROP))
    self.btn_blur.clicked.connect(lambda: self._set_tool(_api.InpaintCanvas.TOOL_BLUR))
    self.btn_run.clicked.connect(self._activate_delete_tool)
    self.btn_bars.clicked.connect(self._remove_black_bars)
    self.btn_bg.clicked.connect(self._remove_bg)
    # «Применить кадрирование» теперь живёт ПРЯМО на холсте (как в Photoshop) —
    # см. InpaintCanvas._crop_apply_btn. Отдельной кнопки в панели больше нет.
    left.addWidget(grp_tools)

    # ── Фигуры и текст ───────────────────────────────────────────────────
    # Одна кнопка «Фигуры» прячет прямоугольник/эллипс/линию/стрелку во
    # всплывающей панели (flyout, как в Photoshop). Рядом — кнопка «Текст».
    # Параметры (заливка/шрифт/размер) и экранная пипетка живут ВНУТРИ
    # всплывающих панелей, открывающихся по клику на кнопку.
    grp_shape = _api.QGroupBox("Фигуры и текст")
    shl = _api.QVBoxLayout(grp_shape); shl.setSpacing(6)
    self._cur_shape_tool = _api.InpaintCanvas.TOOL_RECT
    self.btn_shapes = self._tool_btn(
        "Фигуры", 'fa5s.shapes',
        "Прямоугольник, эллипс, линия, стрелка — выбор во всплывающей панели. "
        "Толщина = размер кисти, цвет = цвет кисти. Нарисованную фигуру можно "
        "перетащить, пока не выбран другой инструмент.")
    self.btn_text = self._tool_btn(
        "Текст", 'fa5s.font',
        "Кликните по холсту и введите текст. Шрифт/размер — во всплывающей "
        "панели; размещённый текст можно перетащить мышью.")
    self.tool_group.addButton(self.btn_shapes)
    self.tool_group.addButton(self.btn_text)
    self.btn_shapes.clicked.connect(self._on_shapes_btn)
    self.btn_text.clicked.connect(self._on_text_btn)
    shl.addWidget(self.btn_shapes)
    shl.addWidget(self.btn_text)
    left.addWidget(grp_shape)
    # Всплывающие панели (создаём один раз, переиспользуем). Внутри —
    # self.chk_fill / self.cmb_font / self.spin_font (нужны коду ниже).
    self._build_shape_flyout()
    self._build_text_flyout()

    # ── Кисть: размер + цвет ─────────────────────────────────────────────
    grp_brush = _api.QGroupBox("Кисть")
    gb = _api.QVBoxLayout(grp_brush); gb.setSpacing(6)
    bl = _api.QHBoxLayout()
    # _JumpSlider: клик по дорожке СРАЗУ ставит значение в точку клика
    # (обычный QSlider лишь «полз» шагами — см. класс выше).
    self.sld_brush = _api._JumpSlider(_api.Qt.Orientation.Horizontal)
    self.sld_brush.setRange(4, 200); self.sld_brush.setValue(30)
    self.sld_brush.valueChanged.connect(self._on_brush)
    bl.addWidget(self.sld_brush, 1)
    self.lbl_brush = _api.QLabel("30"); self.lbl_brush.setFixedWidth(30)
    bl.addWidget(self.lbl_brush)
    gb.addLayout(bl)
    row_col = _api.QHBoxLayout()
    row_col.addWidget(_api.QLabel("Цвет:"))
    self.btn_brush_color = _api.QPushButton()
    self.btn_brush_color.setFixedSize(40, 22)
    self.btn_brush_color.setToolTip("Цвет мазка кисти — клик откроет окно выбора "
                                    "цвета (Alt+клик по картинке берёт цвет пипеткой).")
    self.btn_brush_color.clicked.connect(self._pick_brush_color)
    self._update_color_swatch(_api.QColor(235, 45, 45))
    row_col.addWidget(self.btn_brush_color)
    # Пипетка «взять цвет с экрана» убрана из постоянной панели — теперь она
    # живёт во всплывающих панелях «Фигуры»/«Текст». Цвет с картинки — Alt+клик.
    row_col.addStretch()
    gb.addLayout(row_col)
    left.addWidget(grp_brush)

    # ── Вид ──────────────────────────────────────────────────────────────
    # Кнопку «Сбросить маску» убрали: маска удаления теперь временная (стирается
    # сразу после удаления), отдельно сбрасывать нечего.
    grp_edit = _api.QGroupBox("Вид")
    el = _api.QVBoxLayout(grp_edit); el.setSpacing(6)
    self.btn_fit = _api._icon_btn("Вписать в окно", 'fa5s.expand-arrows-alt')
    self.btn_fit.setToolTip("Колесо мыши — зум; средняя кнопка, «Курсор» или "
                            "WASD/стрелки — двигать картинку при приближении")
    self.btn_fit.clicked.connect(lambda: self.canvas.fit())
    # «Очистить» (полностью очистить холст) — значком в ПРАВОМ верхнем углу
    # холста (canvas.clearRequested → self._clear_canvas). Отмена/возврат
    # (Ctrl+Z / Ctrl+Y) — значками в ЛЕВОМ верхнем углу холста.
    el.addWidget(self.btn_fit)
    left.addWidget(grp_edit)

    # ── Сохранение ───────────────────────────────────────────────────────
    # Эта группа НЕ добавляется в прокручиваемую область — она закрепляется
    # внизу панели (см. ниже, после scroll), чтобы «Выбрать папку» и
    # «Сохранить» всегда были видны рядом со скроллбаром.
    grp_save = _api.QGroupBox("Сохранение")
    sl = _api.QVBoxLayout(grp_save); sl.setSpacing(6)
    self.lbl_outdir = _api.QLabel("Папка: рядом с исходником")
    self.lbl_outdir.setWordWrap(True)
    self.lbl_outdir.setStyleSheet("color:#7f849c; font-size:11px;")
    sl.addWidget(self.lbl_outdir)
    self.btn_outdir = _api._icon_btn("Выбрать папку…", 'fa5s.folder')
    self.btn_outdir.setToolTip("Куда сохранять. Если не выбрано — рядом с исходником.")
    self.btn_outdir.clicked.connect(self._choose_out_dir)
    sl.addWidget(self.btn_outdir)
    # Зелёная, как кнопка «НАЧАТЬ» во вкладке «Обработка» (#b_run в config.py).
    self.btn_save = _api._icon_btn("Сохранить", 'fa5s.save', color='#1e1e2e')
    self.btn_save.setObjectName("b_run")
    self.btn_save.setToolTip("Сохранить <имя>_photo рядом с исходником (или в выбранную папку), без потерь")
    self.btn_save.clicked.connect(self._save)
    sl.addWidget(self.btn_save)

    # ── Статус ───────────────────────────────────────────────────────────
    # Подпись-инструкция убрана из панели (visible=False), но объект остаётся:
    # на него по-прежнему пишут _set_status/_save/_run_inpaint (без крэшей),
    # просто текст больше не занимает место в панели.
    self.lbl_status = _api.QLabel("")
    self.lbl_status.setVisible(False)
    self.lbl_device = _api.QLabel("Устройство: —")
    self.lbl_device.setStyleSheet("color:#7f849c; font-size:11px;")
    self.lbl_device.setToolTip(
        "На каком железе считает нейросеть. GPU (CUDA) — если есть видеокарта "
        "NVIDIA с драйверами CUDA, иначе автоматически CPU.")
    left.addWidget(self.lbl_device)
    left.addStretch(1)
    scroll.setWidget(left_w)
    left_col_l.addWidget(scroll, 1)
    # «Сохранение» закреплено внизу панели (вне прокрутки): «Выбрать папку»
    # и «Сохранить» всегда видны рядом со скроллбаром.
    left_col_l.addWidget(grp_save, 0)
    root.addWidget(left_col, 0)

    # СПРАВА — холст.
    self.canvas = _api.InpaintCanvas(self)
    self.canvas.statusChanged.connect(self._set_status)
    # Alt-пипетка из холста обновляет образец цвета в панели.
    self.canvas.colorPicked.connect(self._on_color_picked)
    # Завершён мазок кистью удаления → сразу убираем закрашенное (как в Photoshop).
    self.canvas.strokeFinished.connect(self._on_stroke_finished)
    # Кнопка «Очистить» в правом верхнем углу холста.
    self.canvas.clearRequested.connect(self._clear_canvas)
    # Undo/redo может вернуть/убрать картинку (напр. отмена «Очистить») —
    # пере-включаем инструменты и холст, иначе картинка видна, но «мёртвая».
    self.canvas.imageChanged.connect(self._refresh_enabled)
    # Текст создан/выделен кликом — открываем панель его свойств (цвет/шрифт/
    # размер/обводка), как выделение текстового слоя в Photoshop.
    self.canvas.textSelected.connect(self._on_text_selected)
    root.addWidget(self.canvas, 1)
    # Передаём холсту стартовый шрифт текста (из комбобокса + размера).
    self._update_text_font()
    self.canvas.set_shape_fill(self.chk_fill.isChecked())

    # Отмена/возврат на уровне вкладки (а не только холста) — чтобы Ctrl+Z/
    # Ctrl+Y работали даже когда фокус ушёл на кнопку (например, после клика
    # по «Применить кадрирование» или инструментам).
    self._sc_undo = _api.QShortcut(_api.QKeySequence("Ctrl+Z"), self)
    self._sc_undo.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    self._sc_undo.activated.connect(lambda: self.canvas.undo())
    self._sc_redo = _api.QShortcut(_api.QKeySequence("Ctrl+Y"), self)
    self._sc_redo.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    self._sc_redo.activated.connect(lambda: self.canvas.redo())
    self._sc_redo2 = _api.QShortcut(_api.QKeySequence("Ctrl+Shift+Z"), self)
    self._sc_redo2.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    self._sc_redo2.activated.connect(lambda: self.canvas.redo())

    self._refresh_enabled()

def _tool_btn(self, text, icon, tip):
    b = _api._icon_btn(text, icon)
    b.setCheckable(True)
    b.setToolTip(tip)
    return b

def _tool_row(self, btn, tip):
    """Строка «кнопка-инструмент (растягивается) + значок ⓘ». Значок ⓘ — тот же
        `info_badge` (widgets.py), что у заголовков вкладок сверху: fa5s.info-circle
        #89b4fa, свой попап без синего системного тултипа."""
    row = _api.QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0); row.setSpacing(5)
    row.addWidget(btn, 1)
    row.addWidget(_api.info_badge(tip), 0, _api.Qt.AlignmentFlag.AlignVCenter)
    return row
