# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab. Public namespace: photo_tab."""
import photo_tab as _api


class InpaintTab(_api.QWidget):
    """Подвкладка «Удаление объектов»: закрашиваете кистью водяной знак/надпись —
    нейросеть LaMa аккуратно «дорисовывает» фон под ним."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        # Сессию держим в дочернем процессе: её создание удерживает GIL ~10–25 c
        # и в обычном QThread заморозило бы весь UI (см. lama_inpaint.py).
        self._inpainter = _api.LaMaProcessInpainter() if _api._HAS_INPAINT else None
        # Удаление фона (RMBG-2.0) — отдельная модель/процесс, грузится лениво при
        # первом нажатии «Удалить фон» (модель ~360 МБ — не держим зря в памяти).
        self._remover = _api.RMBGProcessRemover() if _api._HAS_RMBG else None
        self._worker = None
        self._bg_worker = None
        self._cancelling = False
        self._warmup = None
        # Длительность инференса нейросети заранее НЕ известна (один проход модели
        # не даёт сигнала прогресса), поэтому НЕ выдумываем «осталось N секунд» и не
        # рисуем фейковый бар. Показываем ЧЕСТНО: бесконечный индикатор занятости +
        # реально прошедшее время (счётчик вверх). У LaMa с НЕСКОЛЬКИМИ областями
        # прогресс настоящий (готово/всего) — там бар детерминированный.
        self._proc_start = 0.0          # time.monotonic() старта (для счётчика времени)
        self._proc_region_mode = False  # LaMa: прогресс ведут реальные области
        self._proc_timer = None
        self._warmed = False
        self._device = "—"
        self._src_path = None       # путь исходника (для имени и папки сохранения)
        self._out_dir = None        # выбранная папка сохранения (None → рядом с исходником)
        # Выгрузка моделей из ОЗУ при простое. Настройка «Не выгружать…» (по умолч.
        # выкл) держит их всегда. Иначе — таймер на минуту, сбрасывается при любом
        # взаимодействии; по срабатыванию убивает процессы LaMa/RMBG.
        self._keep_models = False
        self._idle_timer = _api.QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(60_000)
        self._idle_timer.timeout.connect(self._maybe_unload_models)
        if not _api._HAS_INPAINT:
            self._build_unavailable()
        else:
            self._build_ui()
            self.setAcceptDrops(True)
            self.canvas.installEventFilter(self)   # взаимодействие → сброс таймера

    # ── Заглушка при отсутствии зависимостей ─────────────────────────────────
    def _build_unavailable(self):
        lay = _api.QVBoxLayout(self)
        msg = ("Подвкладка «Удаление объектов» недоступна.\n\n"
               "Нужны пакеты: opencv-python, numpy, onnxruntime.\n"
               "Установка:  pip install opencv-python onnxruntime")
        if _api._INPAINT_ERR:
            msg += f"\n\n{_api._INPAINT_ERR}"
        lbl = _api.QLabel(msg)
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

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

    _VK_Z = 0x5A
    _VK_Y = 0x59

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        # Резерв Ctrl+Z/Ctrl+Y для кириллической раскладки: физическая Z/Y там
        # шлёт Qt-код кириллической буквы, и QShortcut("Ctrl+Z"/"Ctrl+Y") выше
        # (см. self._sc_undo/_sc_redo) на ней молча не срабатывает (та же
        # природа бага, что и с WASD — см. _pan_dir_from_event). Событие сюда
        # доходит, только если QShortcut его не поймал — для латиницы там уже
        # сработало, тут лишь докрывается случай перевода раскладкой.
        if mods & _api.Qt.KeyboardModifier.ControlModifier:
            try:
                vk = ev.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_Z:
                (self.canvas.redo() if (mods & _api.Qt.KeyboardModifier.ShiftModifier)
                 else self.canvas.undo())
                ev.accept()
                return
            if vk == self._VK_Y:
                self.canvas.redo()
                ev.accept()
                return
        # Резерв: WASD/стрелки панорамируют, даже если фокус не на холсте (клавиши
        # всплывают сюда от кнопок панели). Ctrl не трогаем (Ctrl+Z/Y и пр.).
        pan_dir = _api._pan_dir_from_event(ev)
        if (not (mods & _api.Qt.KeyboardModifier.ControlModifier)
                and pan_dir is not None and hasattr(self, "canvas")
                and self.canvas.has_image()):
            step = 120 if (mods & _api.Qt.KeyboardModifier.ShiftModifier) else 50
            sx, sy = pan_dir
            self.canvas._pan_by(sx * step, sy * step)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _on_brush(self, v):
        self.lbl_brush.setText(str(v))
        self.canvas.set_brush(v)

    def _on_blur_strength(self, v):
        self.lbl_blur.setText(str(v))
        self.canvas.set_blur_strength(v)

    def _set_status(self, text):
        self.lbl_status.setText(text)

    def set_left_width(self, w):
        """PhotoTab задаёт ширину левой панели под переключатель режима, чтобы
        обе подписи («Редактирование фото» / «Объединить фото») влезали целиком."""
        if hasattr(self, "_left_col"):
            self._left_col.setFixedWidth(int(w))

    def _refresh_enabled(self):
        has = self.canvas.has_image() if hasattr(self, "canvas") else False
        busy = ((self._worker is not None and self._worker.isRunning())
                or (self._bg_worker is not None and self._bg_worker.isRunning()))
        for b in (self.btn_run, self.btn_bg, self.btn_bars, self.btn_save, self.btn_fit):
            b.setEnabled(has and not busy)
        self.btn_open.setEnabled(not busy)
        self.btn_outdir.setEnabled(not busy)
        # «Ластик» стирает ТОЛЬКО ещё не вжатые мазки «Кисти» (см. _paint_image_to) —
        # пока их нет, стирать нечего, кнопка неактивна.
        self.btn_erase.setEnabled(has and not busy and bool(getattr(self.canvas, "_has_paint", False)))
        # Во время обработки холст не трогаем (мазки кистью всё равно сбросятся
        # результатом) — блокируем ввод, оставляя картинку видимой.
        self.canvas.setEnabled(has and not busy)

    # ── Открытие / сохранение / drag-n-drop ──────────────────────────────────
    def _open(self):
        # По умолчанию открываем папку, которую сейчас показывает общая лента
        # файлов сверху (RecentFilesStrip), иначе — папку прошлого исходника.
        start = self._ribbon_folder() or \
            (_api.os.path.dirname(self._src_path) if self._src_path else "")
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Открыть изображение", start,
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.tif *.avif *.heic *.heif)")
        if path:
            self._load(path)

    def _ribbon_folder(self) -> str:
        """Папка, которую показывает общая лента файлов сверху (если задана)."""
        try:
            strip = getattr(self.main, "recent_strip", None)
            folder = strip._effective_folder() if strip is not None else ""
            return folder if folder and _api.os.path.isdir(folder) else ""
        except Exception:
            return ""

    def _clear_canvas(self):
        self.canvas.clear_canvas()
        self._src_path = None
        self._refresh_enabled()

    def _load(self, path):
        try:
            if self.canvas.has_image():
                # Overlay-режим: загружаем с сохранением альфа-канала (PNG-прозрачность).
                arr = _api._load_image_alpha(path)
                self.canvas.add_overlay_image(arr)
                self._set_status(
                    f"Поверх — {_api.os.path.basename(path)}. "
                    "Перетащите на нужное место; Enter или клик вне — вжать.")
            else:
                # Сохраняем альфа-канал при первом открытии — иначе прозрачность
                # PNG/WEBP/AVIF терялась бы уже на этом шаге (cv2.IMREAD_COLOR
                # альфу отбрасывает), а «Удалить фон» потом рисовал бы поверх
                # чужого фона, оставшегося от исходника.
                arr = _api._load_image_alpha(path)
                if arr.ndim == 3 and arr.shape[2] == 4:
                    self.canvas.set_image_bgr(arr[:, :, :3])
                    self.canvas.apply_cutout(arr[:, :, 3])
                else:
                    self.canvas.set_image_bgr(arr)
                self._src_path = path
                self._set_status(f"Загружено: {_api.os.path.basename(path)}. "
                                 "Закрасьте объект кистью и нажмите «Удалить объект».")
                self._kick_warmup()
            self._refresh_enabled()
        except Exception as exc:
            _api.msgbox_warning(self, "Ошибка", f"Не удалось открыть изображение:\n{exc}")

    def add_paths(self, paths):
        imgs = [p for p in paths if _api.os.path.splitext(p)[1].lower() in
                {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff', '.tif',
                 '.avif', '.heic', '.heif'}]
        if imgs:
            self._load(imgs[0])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()
        else: e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
            self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def _choose_out_dir(self):
        start = self._out_dir or (_api.os.path.dirname(self._src_path) if self._src_path else "")
        d = _api.QFileDialog.getExistingDirectory(self, "Папка для сохранения", start)
        if d:
            self._out_dir = d
            self.lbl_outdir.setText(f"Папка: {d}")
            self.lbl_outdir.setToolTip(d)

    def _output_path(self, has_alpha=False):
        """Путь сохранения: <имя_исходника>_photo.<ext> в выбранной папке (или
        рядом с исходником). Расширение — БЕЗ ПОТЕРЬ: исходные png/bmp/tiff
        сохраняем как есть, остальное (jpg/webp/avif/heic…) → png, чтобы не было
        повторного сжатия и потери качества. Если удалён фон (есть прозрачность) —
        формат обязан её хранить (png/webp/tiff), иначе принудительно png."""
        if self._src_path:
            base = _api.os.path.splitext(_api.os.path.basename(self._src_path))[0]
            src_ext = _api.os.path.splitext(self._src_path)[1].lower().lstrip('.')
            src_dir = _api.os.path.dirname(self._src_path)
        else:
            base, src_ext, src_dir = "image", "png", _api.os.getcwd()
        if has_alpha:
            ext = src_ext if src_ext in ("png", "webp", "tif", "tiff") else "png"
        else:
            ext = src_ext if src_ext in ("png", "bmp", "tif", "tiff") else "png"
        out_dir = self._out_dir or src_dir or _api.os.getcwd()
        stem = f"{base}_photo"
        path = _api.os.path.join(out_dir, f"{stem}.{ext}")
        if not _api.os.path.exists(path):
            return path
        n = 1
        while True:
            path = _api.os.path.join(out_dir, f"{stem}_{n}.{ext}")
            if not _api.os.path.exists(path):
                return path
            n += 1

    def _save(self):
        if not self.canvas.has_image():
            return
        # Вжигаем незакреплённый плавающий объект (фигуру/текст) в картинку, чтобы
        # он попал в сохранённый файл.
        self.canvas.commit_pending()
        # composited_bgra: BGRA, если фон удалён (прозрачность), иначе BGR.
        arr = self.canvas.composited_bgra()
        has_alpha = arr is not None and arr.ndim == 3 and arr.shape[2] == 4
        out = self._output_path(has_alpha)
        try:
            _api.os.makedirs(_api.os.path.dirname(out) or ".", exist_ok=True)
            # Сохраняем фото с вжатыми мазками «Кисти» (и альфой прозрачности, если
            # удалён фон). Красная маска удаления — служебная, в файл не попадает.
            _api.save_bgr(out, arr)                            # png/webp/tiff — без потерь
            self._set_status(_api.status_html('fa5s.check-circle',
                             f"Сохранено: {_api.os.path.basename(out)}", '#a6e3a1'))
            self.lbl_status.setToolTip(out)
            # Всплывающее уведомление об успешном сохранении (по просьбе
            # пользователя) — показываем ТОЛЬКО если файл реально записан.
            if _api.os.path.exists(out):
                self._show_saved_toast(_api.os.path.basename(out))
        except Exception as exc:
            _api.msgbox_warning(self, "Ошибка", f"Не удалось сохранить:\n{exc}")

    def _show_saved_toast(self, name: str):
        """Зелёный плавающий баннер «Файл сохранён» по центру сверху вкладки."""
        self._show_toast(f"✅  Файл сохранён: {name}")

    def _show_toast(self, text: str, bg: str = "rgba(166,227,161,0.94)"):
        """Плавающий баннер по центру сверху вкладки, автоскрытие через 3 с
        (как в SiQuesterHYX). Создаётся лениво."""
        lbl = getattr(self, "_saved_toast", None)
        if lbl is None:
            lbl = _api.QLabel(self)
            lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
            lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._saved_toast = lbl
            self._saved_toast_timer = _api.QTimer(self)
            self._saved_toast_timer.setSingleShot(True)
            self._saved_toast_timer.timeout.connect(lbl.hide)
        lbl.setStyleSheet(
            f"background:{bg};color:#181825;font-size:13px;"
            "font-weight:700;border-radius:8px;padding:8px 24px;")
        lbl.setText(text)
        lbl.adjustSize()
        lbl.move(max(0, (self.width() - lbl.width()) // 2), 12)
        lbl.raise_(); lbl.show()
        self._saved_toast_timer.start(3000)

    # ── Прогрев модели ───────────────────────────────────────────────────────
    def showEvent(self, ev):
        super().showEvent(ev)
        # Грузим модель в фоне при первом показе вкладки (а не при старте приложения).
        if _api._HAS_INPAINT and not self._warmed:
            self._kick_warmup()
        self._touch()

    def hideEvent(self, ev):
        # Уход со вкладки = простой: запускаем отсчёт выгрузки (минута).
        super().hideEvent(ev)
        if _api._HAS_INPAINT and not self._keep_models:
            self._idle_timer.start()

    # ── Выгрузка моделей из ОЗУ при простое ──────────────────────────────────
    def set_keep_models(self, keep: bool):
        """Настройка «Не выгружать модели из ОЗУ»: True — держать всегда (таймер
        стоп), False — выгружать после минуты простоя."""
        self._keep_models = bool(keep)
        if self._keep_models:
            self._idle_timer.stop()
        elif self.isVisible():
            self._touch()
        else:
            self._idle_timer.start()

    def _touch(self):
        """Взаимодействие со вкладкой → сбрасываем отсчёт выгрузки. Модель тут НЕ
        подгружаем: загрузка только при открытии вкладки (showEvent) и при самом
        удалении объекта/фона. Клики/рисование лишь не дают выгрузить загруженную."""
        if not _api._HAS_INPAINT or self._keep_models:
            return
        self._idle_timer.start()

    def eventFilter(self, obj, ev):
        if ev.type() in (_api.QEvent.Type.MouseButtonPress, _api.QEvent.Type.MouseMove,
                         _api.QEvent.Type.KeyPress, _api.QEvent.Type.Wheel):
            self._touch()
        return super().eventFilter(obj, ev)

    def _models_busy(self) -> bool:
        return ((self._worker is not None and self._worker.isRunning())
                or (self._bg_worker is not None and self._bg_worker.isRunning())
                or self._warmup is not None)

    def _maybe_unload_models(self):
        if self._keep_models:
            return
        if self._models_busy():
            self._idle_timer.start()     # занят — отложим проверку
            return
        was_loaded = self._warmed
        for m in (self._inpainter, self._remover):
            if m is not None and hasattr(m, "unload"):
                try: m.unload()
                except Exception: pass
        self._warmed = False
        self._device = "—"
        if was_loaded and hasattr(self, "lbl_device"):
            self.lbl_device.setText("Устройство: модель выгружена из ОЗУ")

    def _kick_warmup(self):
        if not _api._HAS_INPAINT or self._warmed or self._warmup is not None:
            return
        if not _api._HAS_ORT:
            self.lbl_device.setText("Устройство: нет onnxruntime")
            return
        self.lbl_device.setText("Устройство: загрузка модели…")
        self._warmup = _api._WarmupWorker(self._inpainter)
        self._warmup.done.connect(self._on_warmed)
        self._warmup.failed.connect(self._on_warm_failed)
        self._warmup.start()

    def _on_warmed(self, device):
        self._warmed = True
        self._device = device
        self.lbl_device.setText(f"Устройство: {device}")
        self._warmup = None

    def _on_warm_failed(self, err):
        self.lbl_device.setText("Устройство: ошибка загрузки модели")
        self._set_status(_api.status_html('fa5s.exclamation-triangle',
                         f"Модель не загрузилась: {err}", '#f9e2af'))
        self._warmup = None

    # ── Запуск инференса ─────────────────────────────────────────────────────
    def _run_inpaint(self):
        self._touch()
        if not self.canvas.has_image():
            return
        # Закрепляем плавающий объект, чтобы нейросеть видела финальную картинку.
        self.canvas.commit_pending()
        # Незавершённое кадрирование применяем (иначе нарисованная рамка пропадала,
        # а нейросеть работала по полному изображению — «убирала кадрирование»).
        if self.canvas.has_crop():
            self.canvas.apply_crop()
        if not _api._HAS_ORT:
            _api.msgbox_warning(self, "Нет onnxruntime",
                                "Для удаления объектов установите onnxruntime:\n\n"
                                "pip install onnxruntime")
            return
        if not self.canvas.has_mask():
            # Сюда попадаем только при пустом выделении (кисть удаления не оставила
            # мазка) — тихо выходим: сама кнопка «Удалить объект» уже включает кисть.
            self._set_status("Закрасьте кистью удаления то, что нужно стереть.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
        # Снимок «до» (с отдельным слоем краски и маской) — для Ctrl+Z, затем
        # вживляем мазки кисти, чтобы нейросеть видела финальную картинку.
        self.canvas._push_history()
        self.canvas.bake_paint()
        mask = self.canvas.get_mask()
        img = self.canvas.img_bgr
        self._set_status(_api.status_html('fa5s.spinner',
                         "Обработка нейросетью… (первый запуск дольше — грузится модель)",
                         '#89b4fa'))
        self.setCursor(_api.Qt.CursorShape.WaitCursor)
        self._show_proc_chip(mask)          # мини-прогресс возле выделения/курсора
        self._worker = _api.InpaintWorker(self._inpainter, img, mask)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()
        self._refresh_enabled()

    # ── Мини-прогресс «удаляю…» возле курсора/выделения ──────────────────────
    def _show_proc_chip(self, mask=None, label="Удаляю…", icon='fa5s.magic'):
        chip = getattr(self, "_proc_chip", None)
        if chip is None:
            chip = _api.QFrame(self)
            chip.setObjectName("procChip")
            chip.setStyleSheet(
                "QFrame#procChip{background:rgba(30,30,46,235);"
                "border:1px solid #89b4fa;border-radius:9px;}"
                "QLabel{color:#cdd6f4;font-size:12px;font-weight:600;background:transparent;}"
                "QProgressBar{background:#11111b;border:1px solid #45475a;"
                "border-radius:5px;max-height:8px;min-height:8px;}"
                "QProgressBar::chunk{background:#89b4fa;border-radius:5px;}")
            lay = _api.QHBoxLayout(chip)
            lay.setContentsMargins(10, 7, 8, 7); lay.setSpacing(8)
            self._proc_ic = _api.QLabel()
            self._proc_ic.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(self._proc_ic)
            self._proc_lbl = _api.QLabel(label)
            self._proc_lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(self._proc_lbl)
            self._proc_bar = _api.QProgressBar()
            self._proc_bar.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._proc_bar.setTextVisible(False)
            self._proc_bar.setFixedWidth(80)
            lay.addWidget(self._proc_bar)
            self._proc_cancel_btn = _api.QPushButton("Отменить")
            self._proc_cancel_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            self._proc_cancel_btn.setToolTip("Отменить обработку")
            self._proc_cancel_btn.setStyleSheet(
                "QPushButton{background:#313244;border:1px solid #45475a;"
                "border-radius:5px;color:#f38ba8;font-size:11px;font-weight:600;"
                "padding:3px 8px;}"
                "QPushButton:hover{background:#45475a;border-color:#f38ba8;}")
            self._proc_cancel_btn.clicked.connect(self._cancel_proc)
            lay.addWidget(self._proc_cancel_btn)
            self._proc_chip = chip
        # Честный индикатор: бесконечный «бегунок» занятости. Длительность одного
        # прохода нейросети заранее неизвестна, поэтому НЕ выдумываем проценты и
        # «осталось N секунд» — подпись показывает реально ПРОШЕДШЕЕ время (счётчик
        # вверх). У LaMa с несколькими областями прогресс настоящий (готово/всего) —
        # там бар становится детерминированным (см. _on_progress).
        self._proc_base_label = label
        self._proc_status_text = label
        self._proc_mask = mask
        self._proc_region_mode = False
        self._proc_start = _api.time.monotonic()
        self._proc_ic.setPixmap(_api.get_icon(icon, color='#89b4fa').pixmap(14, 14))
        self._proc_lbl.setText(label)
        self._proc_bar.setRange(0, 0)        # 0,0 -> бесконечный индикатор занятости
        if self._proc_timer is None:
            self._proc_timer = _api.QTimer(self)
            self._proc_timer.setInterval(500)
            self._proc_timer.timeout.connect(self._proc_tick)
        self._proc_timer.start()
        self._proc_anchor = None        # пересчитать якорь под новое выделение/курсор
        self._proc_chip.adjustSize()
        self._position_proc_chip(mask)
        self._proc_chip.show(); self._proc_chip.raise_()

    def _proc_tick(self):
        """Тик: подпись = реально ПРОШЕДШЕЕ время (честный счётчик вверх). Бар —
        бесконечный индикатор занятости, кроме режима реальных областей LaMa."""
        chip = getattr(self, "_proc_chip", None)
        if chip is None or not chip.isVisible():
            return
        elapsed = int(max(0.0, _api.time.monotonic() - self._proc_start))
        if self._proc_region_mode:
            self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
        else:
            self._proc_lbl.setText(f"{self._proc_base_label} {elapsed} с")
        # Чип подгоняем под подпись и пере-центрируем (якорь стабилен), чтобы текст
        # не обрезался по мере роста счётчика.
        self._proc_chip.adjustSize()
        self._position_proc_chip(self._proc_mask)

    def _finish_proc(self):
        """Завершение: останавливаем счётчик времени (чип прячется следом)."""
        if self._proc_timer is not None:
            self._proc_timer.stop()

    def _position_proc_chip(self, mask=None):
        # Якорь (центр привязки) вычисляем ОДИН раз при показе чипа и кэшируем —
        # иначе при обновлении подписи (счётчик времени растит ширину) чип бы прыгал
        # за курсором (для фона mask=None фолбэк брал бы текущую позицию мыши).
        gp = getattr(self, "_proc_anchor", None)
        if gp is None:
            canvas = self.canvas
            pt = None
            try:
                if mask is not None:
                    ys, xs = _api._np.where(mask > 0)
                    if len(xs):
                        pt = canvas._i2w(_api.QPointF(float(xs.mean()), float(ys.mean())))
            except Exception:
                pt = None
            if pt is None:
                pt = canvas._mouse_w
            if pt is None:
                pt = _api.QPointF(canvas.width() / 2.0, canvas.height() / 2.0)
            gp = canvas.mapTo(self, _api.QPoint(int(pt.x()), int(pt.y())))
            self._proc_anchor = gp
        w, h = self._proc_chip.width(), self._proc_chip.height()
        x = max(4, min(gp.x() - w // 2, self.width() - w - 4))
        y = max(4, min(gp.y() - h - 14, self.height() - h - 4))
        self._proc_chip.move(x, y)

    def _hide_proc_chip(self):
        if self._proc_timer is not None:
            self._proc_timer.stop()
        chip = getattr(self, "_proc_chip", None)
        if chip is not None:
            chip.hide()

    def _cancel_proc(self):
        """Отмена текущей обработки (LaMa/RMBG). В процессном режиме kill дочернего
        процесса прерывает инференс за миллисекунды (воркер ловит обрыв пайпа и
        завершается сам). НО интерфейс приводим в «Отменено» СРАЗУ, не дожидаясь
        сигнала воркера: в редком in-process фолбэке одиночный sess.run() прервать
        нельзя, и иначе чип «Удаляю…» и курсор-«ожидание» висели бы до конца прохода
        («не останавливает / с задержкой»). Поздний результат осиротевшего воркера
        отбрасывается по флагу _cancelling (см. _on_done/_on_bg_done)."""
        running = ((self._worker is not None and self._worker.isRunning())
                   or (self._bg_worker is not None and self._bg_worker.isRunning()))
        if not running:
            return
        self._cancelling = True
        if self._worker is not None and self._worker.isRunning() and self._inpainter is not None:
            try: self._inpainter.cancel()
            except Exception: pass
        if self._bg_worker is not None and self._bg_worker.isRunning() and self._remover is not None:
            try: self._remover.cancel()
            except Exception: pass
        # Мгновенная реакция UI — не ждём, пока воркер domотает/разблокируется.
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
        self._refresh_enabled()

    def _on_progress(self, done, total):
        # Отменено — чип уже скрыт в _cancel_proc, поздний прогресс игнорируем.
        if getattr(self, "_cancelling", False):
            return
        # LaMa с НЕСКОЛЬКИМИ областями: показываем РЕАЛЬНЫЙ прогресс по областям —
        # переключаем чип в детерминированный «режим областей».
        chip = getattr(self, "_proc_chip", None)
        if total > 1:
            self._proc_region_mode = True
            if chip is not None and chip.isVisible():
                self._proc_bar.setRange(0, 1000)
                self._proc_bar.setValue(int(min(done + 1, total) / total * 1000))
                self._proc_status_text = f"Удаляю {min(done + 1, total)}/{total}"
                elapsed = int(max(0.0, _api.time.monotonic() - self._proc_start))
                self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
            self._set_status(_api.status_html('fa5s.spinner',
                             f"Обработка области {min(done + 1, total)} из {total}…",
                             '#89b4fa'))

    def _on_done(self, result):
        # Пользователь отменил, пока шёл инференс, — результат уже не нужен (UI
        # приведён в «Отменено» в _cancel_proc). Прибираемся и выходим, НЕ применяя
        # результат (иначе объект «удалялся» вопреки отмене — «не останавливает»).
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._worker = None
            self._hide_proc_chip()
            self.unsetCursor()
            self._refresh_enabled()
            return
        # Состояние сохранено в истории ещё до запуска, поэтому результат
        # применяем без повторного пуша.
        self.canvas.img_bgr = _api._np.ascontiguousarray(result)
        self.canvas._overlay.fill(0)
        self.canvas._has_strokes = False
        self.canvas._rebuild_base()
        self.canvas.update()
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        self._device = self._inpainter.device_label
        self.lbl_device.setText(f"Устройство: {self._device}")
        self._set_status(_api.status_html('fa5s.check-circle',
                         "Готово! Объект удалён.", '#a6e3a1'))
        self._worker = None
        self._refresh_enabled()
        try: _api.play_done_sound()
        except Exception: pass

    def _on_failed(self, err):
        self._hide_proc_chip()
        self.unsetCursor()
        self._worker = None
        self._refresh_enabled()
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
            return
        self._set_status(_api.status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
        _api.msgbox_warning(self, "Ошибка обработки", str(err))

    # ── Удаление фона (RMBG-2.0) ─────────────────────────────────────────────
    def _remove_black_bars(self):
        """«Удалить чёрные полосы»: тот же детект, что во вкладке «Обработка»
        (ProcessWorker._crop_from_counts), только по одной картинке. Работает
        мгновенно и локально — нейросети и фоновые потоки не нужны."""
        self._touch()
        if not self.canvas.has_image():
            return
        if (self._worker is not None and self._worker.isRunning()) or \
           (self._bg_worker is not None and self._bg_worker.isRunning()):
            return
        # Плавающий слой (наложенная картинка/фигура/текст) вжимаем — иначе он
        # остался бы висеть поверх уже обрезанного кадра со старыми координатами.
        self.canvas.commit_pending()
        size = self.canvas.crop_black_bars()
        if size is None:
            self._set_status(_api.status_html('fa5s.info-circle',
                             "Чёрные полосы не обнаружены.", '#89b4fa'))
            self._show_toast("Чёрные полосы не обнаружены",
                             bg="rgba(249,226,175,0.94)")
        else:
            self._set_status(_api.status_html('fa5s.check-circle',
                             f"Чёрные полосы обрезаны → {size[0]}×{size[1]}.", '#a6e3a1'))
            self._show_toast(f"✂  Чёрные полосы обрезаны → {size[0]}×{size[1]}")
        self._refresh_enabled()

    def _remove_bg(self):
        self._touch()
        if not self.canvas.has_image():
            return
        if not _api._HAS_RMBG or self._remover is None:
            _api.msgbox_warning(
                self, "Удаление фона недоступно",
                "Нужна модель models/model_uint8.onnx и пакет onnxruntime.\n\n"
                "Установка onnxruntime:  pip install onnxruntime")
            return
        if (self._worker is not None and self._worker.isRunning()) or \
           (self._bg_worker is not None and self._bg_worker.isRunning()):
            return
        self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
        # Вжигаем плавающий слой и мазки кисти, снимок «до» — для Ctrl+Z.
        self.canvas.commit_pending()
        # Незавершённое кадрирование применяем перед удалением фона (иначе рамка
        # кадрирования пропадала, а фон убирался с полного изображения).
        if self.canvas.has_crop():
            self.canvas.apply_crop()
        self.canvas._push_history()
        self.canvas.bake_paint()
        img = self.canvas.img_bgr
        self._set_status(_api.status_html(
            'fa5s.spinner',
            "Удаляю фон нейросетью… (первый запуск дольше — грузится модель ~360 МБ)",
            '#89b4fa'))
        self.setCursor(_api.Qt.CursorShape.WaitCursor)
        self._show_proc_chip(None, label="Удаляю фон…", icon='fa5s.cut')
        self._bg_worker = _api.BgRemoveWorker(self._remover, img)
        self._bg_worker.done.connect(self._on_bg_done)
        self._bg_worker.failed.connect(self._on_bg_failed)
        self._bg_worker.start()
        self._refresh_enabled()

    def _on_bg_done(self, alpha):
        # Отменено во время инференса — фон уже не убираем (UI в «Отменено»).
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._bg_worker = None
            self._hide_proc_chip()
            self.unsetCursor()
            self._refresh_enabled()
            return
        # Историю уже сохранили перед запуском — применяем без повторного пуша.
        self.canvas.apply_cutout(alpha)
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        try:
            self._device = self._remover.device_label
            self.lbl_device.setText(f"Устройство: {self._device}")
        except Exception:
            pass
        self._set_status(_api.status_html('fa5s.check-circle',
                         "Готово! Фон удалён — сохраняйте в PNG.", '#a6e3a1'))
        self._bg_worker = None
        self._refresh_enabled()
        try: _api.play_done_sound()
        except Exception: pass

    def _on_bg_failed(self, err):
        self._hide_proc_chip()
        self.unsetCursor()
        self._bg_worker = None
        self._refresh_enabled()
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
            return
        self._set_status(_api.status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
        _api.msgbox_warning(self, "Ошибка удаления фона", str(err))


InpaintTab.__module__ = _api.__name__
_api.InpaintTab = InpaintTab
