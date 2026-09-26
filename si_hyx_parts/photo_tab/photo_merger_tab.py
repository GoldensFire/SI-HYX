# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PhotoMergerTab. Public namespace: photo_tab."""
import photo_tab as _api


class PhotoMergerTab(_api.QWidget):
    # Форматы сохранения: (расширение, PIL-формат, параметры сохранения)
    _FMT_MAP = [
        ("tiff", "TIFF",  {"compression": "tiff_deflate"}),
        ("jpg",  "JPEG",  {"quality": 95}),
        ("png",  "PNG",   {}),
        ("webp", "WEBP",  {"quality": 90}),
    ]

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._build_ui()

    def insert_mode_switch(self, widget):
        """PhotoTab вставляет сюда переключатель режимов «Фото» (сверху левой
        панели, вместо верхней полосы вкладок)."""
        if hasattr(self, "_left_layout"):
            self._left_layout.insertWidget(0, widget)

    def set_left_width(self, w):
        """PhotoTab задаёт ширину левой панели под переключатель режима, чтобы
        обе подписи влезали целиком (как и в подвкладке редактирования)."""
        if hasattr(self, "_left_w"):
            self._left_w.setFixedWidth(int(w))

    def _build_ui(self):
        root = _api.QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        # ЛЕВО (1/3) — список файлов + настройки + кнопка объединения.
        # ПРАВО (2/3) — крупный просмотр результата.
        left_w = _api.QWidget(); left = _api.QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)
        left_w.setMinimumWidth(220)
        self._left_w = left_w      # PhotoTab подгонит ширину под переключатель режима
        self._left_layout = left   # сюда PhotoTab вставит переключатель режима
        right_w = _api.QWidget(); right = _api.QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0); right.setSpacing(8)
        # Пропорция ~1/3 : 2/3.
        root.addWidget(left_w, 1); root.addWidget(right_w, 2)

        # ── Status bar ─────────────────────────────────────
        # Только подсказка статуса; кнопки добавления/удаления вынесены ВНИЗ,
        # под список файлов.
        top = _api.QHBoxLayout()
        self.lbl_status = _api.QLabel("")
        self.lbl_status.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
        self.lbl_status.setSizePolicy(_api.QSizePolicy.Policy.Ignored, _api.QSizePolicy.Policy.Preferred)
        top.addWidget(self.lbl_status, 1)
        left.addLayout(top)

        # ── File list (зона, куда кидать файлы) ──────────────
        self.file_list = _api.PhotoDragList()
        left.addWidget(self.file_list, 1)
        # Клавиша Delete — удалить выделенные фото из списка
        self._sc_delete = _api.QShortcut(_api.QKeySequence(_api.Qt.Key.Key_Delete), self.file_list)
        self._sc_delete.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self._remove_selected)

        # ── Кнопки добавления/удаления (ПОД списком) ─────────
        # Без setFixedWidth — крупный шрифт обрезал подписи («Добави…», «Очистить вс…»).
        # Кнопки берут ширину по содержимому; замыкающий stretch держит их слева.
        btns = _api.QHBoxLayout()
        btn_open = _api._icon_btn("Добавить", 'fa5s.folder-open')
        btn_open.clicked.connect(self._open_files)

        btn_clear_sel = _api._icon_btn("Удалить", 'fa5s.times')
        btn_clear_sel.clicked.connect(self._remove_selected)

        btn_clear_all = _api._icon_btn("Очистить", 'fa5s.trash', color='#1e1e2e')
        btn_clear_all.setObjectName("b_stop")
        btn_clear_all.clicked.connect(self._clear_all)

        btns.addWidget(btn_open)
        btns.addWidget(btn_clear_sel)
        btns.addWidget(btn_clear_all)
        btns.addStretch()
        left.addLayout(btns)

        # ── Настройки объединения (под списком) ──────────────
        grp_set = _api.QGroupBox("Настройки"); set_l = _api.QVBoxLayout(grp_set)
        self.rb_horiz = _api._icon_btn("Горизонт.", 'fa5s.arrow-right')
        self.rb_vert  = _api._icon_btn("Вертикал.", 'fa5s.arrow-down')
        self.rb_horiz.setCheckable(True); self.rb_horiz.setChecked(True)
        self.rb_vert.setCheckable(True)
        self.rb_horiz.clicked.connect(lambda: self.rb_vert.setChecked(False))
        self.rb_vert.clicked.connect(lambda: self.rb_horiz.setChecked(False))
        row_mode = _api.QHBoxLayout(); row_mode.addWidget(_api.QLabel("Режим:"))
        row_mode.addWidget(self.rb_horiz); row_mode.addWidget(self.rb_vert)
        row_mode.addWidget(_api.info_badge(
            "Как складывать картинки: «Горизонт.» — в ряд слева направо "
            "(выравниваются по высоте), «Вертикал.» — стопкой сверху вниз "
            "(выравниваются по ширине)."))
        row_mode.addStretch()
        set_l.addLayout(row_mode)

        self.cmb_fmt = _api.QComboBox()
        self.cmb_fmt.addItems(["TIFF", "JPEG", "PNG", "WEBP"])
        self.cmb_fmt.setFixedWidth(90)
        row_fmt = _api.QHBoxLayout(); row_fmt.addWidget(_api.QLabel("Формат:"))
        row_fmt.addWidget(self.cmb_fmt)
        row_fmt.addWidget(_api.info_badge(
            "Формат сохранения склейки: TIFF — без потерь (крупный файл); "
            "PNG — без потерь со сжатием; JPEG/WEBP — с потерями, файл меньше."))
        row_fmt.addStretch()
        set_l.addLayout(row_fmt)

        # SVG обычно имеет прозрачный фон — при объединении прозрачность заливается
        # чёрным. Галочка заливает прозрачный фон SVG белым перед склейкой.
        self.ck_svg_white = _api.QCheckBox("SVG: сделать белым фон")
        self.ck_svg_white.setChecked(True)
        row_svg = _api.QHBoxLayout(); row_svg.addWidget(self.ck_svg_white)
        row_svg.addWidget(_api.info_badge(
            "Только для SVG: прозрачный фон вектора заливается белым перед "
            "объединением (иначе прозрачные области становятся чёрными)."))
        row_svg.addStretch()
        set_l.addLayout(row_svg)
        left.addWidget(grp_set)

        # Одна кнопка на всё: объединяет ВСЕ файлы из списка.
        self.btn_merge_new = _api._icon_btn("Объединить", 'fa5s.object-group', color='#1e1e2e')
        self.btn_merge_new.setObjectName("b_run")
        self.btn_merge_new.clicked.connect(lambda: self._do_merge(force_all=True))
        left.addWidget(self.btn_merge_new)

        # ── ПРАВО: крупный просмотр результата (2/3) ─────────
        # Холст справа одинаков с подвкладкой «Редактирование фото»: тот же тёмный
        # фон (#11111b) без светлой рамки/заголовка, чтобы при переключении
        # режимов правая область не «прыгала» (просьба пользователя). Результат
        # склейки по-прежнему показывается прямо в этом холсте.
        scroll = _api.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea{background-color:#11111b; border:none;} "
            "QScrollArea > QWidget > QWidget{background-color:#11111b;}")
        self.lbl_preview = _api.QLabel("Здесь появится результат")
        self.lbl_preview.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet(
            "color: #585b70; font-size: 13px; background-color:#11111b;")
        scroll.setWidget(self.lbl_preview)
        right.addWidget(scroll, 1)

        # Плавающая кнопка «на весь экран» в правом нижнем углу превью результата.
        self._preview_scroll = scroll
        self._last_result_path = ""
        self.btn_preview_fs = _api.QToolButton(scroll)
        self.btn_preview_fs.setIcon(_api.get_icon('fa5s.expand'))
        self.btn_preview_fs.setToolTip("Открыть результат на весь экран")
        self.btn_preview_fs.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_preview_fs.setFixedSize(34, 34)
        self.btn_preview_fs.setIconSize(_api.QSize(18, 18))
        self.btn_preview_fs.setStyleSheet(
            "QToolButton{background:rgba(24,24,37,210);border:1px solid #45475a;"
            "border-radius:6px;} QToolButton:hover{background:rgba(49,50,68,235);"
            "border:1px solid #585b70;}")
        self.btn_preview_fs.clicked.connect(self._open_result_fullscreen)
        self.btn_preview_fs.hide()
        scroll.installEventFilter(self)

        # ── Accept drops on the whole widget ───────────────
        self.setAcceptDrops(True)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, '_preview_scroll', None) and ev.type() == _api.QEvent.Type.Resize:
            self._reposition_preview_fs()
        return super().eventFilter(obj, ev)

    def _reposition_preview_fs(self):
        """Держит плавающую кнопку в правом нижнем углу области превью."""
        try:
            s = self._preview_scroll
            m = 12
            self.btn_preview_fs.move(s.width() - self.btn_preview_fs.width() - m,
                                     s.height() - self.btn_preview_fs.height() - m)
            self.btn_preview_fs.raise_()
        except Exception:
            pass

    def _open_result_fullscreen(self):
        p = getattr(self, '_last_result_path', "")
        if p and _api.os.path.exists(p):
            _api.show_image_fullscreen(p, self)

    # ── Drag-and-drop forwarding ────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            links = [str(u.toLocalFile()) for u in event.mimeData().urls()]
            self.file_list.add_files(links)

    # ── Helpers ─────────────────────────────────────────────
    def add_paths(self, paths):
        _img = {'.png','.jpg','.jpeg','.bmp','.gif','.tiff','.tif',
                '.webp','.avif','.heic','.heif','.ico','.svg'}
        valid = [p for p in paths if _api.os.path.splitext(p)[1].lower() in _img]
        if valid:
            self.file_list.add_files(valid)

    def _open_files(self):
        files, _ = _api.QFileDialog.getOpenFileNames(
            self, "Выбрать изображения", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp *.avif *.heic *.heif *.ico *.svg)"
        )
        if files:
            self.file_list.add_files(files)

    def _remove_selected(self):
        for it in self.file_list.selectedItems():
            idx = self.file_list.indexOfTopLevelItem(it)
            if idx >= 0:
                self.file_list.takeTopLevelItem(idx)

    def _clear_all(self):
        self.file_list.clear()
        self.lbl_preview.clear()
        self.lbl_preview.setText("Здесь появится результат")
        self.lbl_status.setText("Список очищен")
        self._last_result_path = ""
        self.btn_preview_fs.hide()

    # ── Core merge ──────────────────────────────────────────
    def _do_merge(self, force_all: bool):
        if not _api.Image:
            self.lbl_status.setText(_api.status_html('fa5s.times-circle', "Pillow не установлен (pip install Pillow)", '#f38ba8'))
            return

        items = self.file_list.get_all_items() if force_all else self.file_list.get_new_items()

        if not items:
            self.lbl_status.setText("Список пуст!")
            return

        try:
            paths = [it.data(0, _api.Qt.ItemDataRole.UserRole) for it in items]
            svg_white = self.ck_svg_white.isChecked()
            imgs = []
            for p in paths:
                im = _api.open_image_any(p)
                # Прозрачный фон SVG по умолчанию станет чёрным при склейке —
                # по галочке заливаем его белым.
                if (svg_white and _api.os.path.splitext(p)[1].lower() == '.svg'
                        and im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa')):
                    rgba = im.convert('RGBA')
                    bg = _api.Image.new('RGB', rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[3])
                    im = bg
                imgs.append(im)

            vertical = self.rb_vert.isChecked()

            # Сохраняем прозрачность, если ВЫХОДНОЙ формат её поддерживает
            # (PNG/WEBP/TIFF) и хотя бы у одной картинки есть альфа. Тогда холст —
            # RGBA с прозрачным фоном. Иначе RGB на чёрном фоне (как раньше; JPEG
            # альфу не умеет).
            ext, pil_fmt, save_kwargs = self._FMT_MAP[self.cmb_fmt.currentIndex()]

            def _has_alpha(im):
                return (im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa')
                        or (im.mode == 'P' and 'transparency' in im.info))

            keep_alpha = (pil_fmt in ('PNG', 'WEBP', 'TIFF')
                          and any(_has_alpha(im) for im in imgs))
            cmode = 'RGBA' if keep_alpha else 'RGB'
            bg = (0, 0, 0, 0) if keep_alpha else (0, 0, 0)
            # Приводим к режиму холста ДО ресайза (ресайз RGBA сохраняет альфу).
            imgs = [im if im.mode == cmode else im.convert(cmode) for im in imgs]

            if vertical:
                max_w = max(im.width for im in imgs)
                processed = []
                total_h = 0
                for im in imgs:
                    r = max_w / im.width
                    new_h = int(im.height * r)
                    processed.append(im.resize((max_w, new_h), _api.Image.Resampling.LANCZOS))
                    total_h += new_h
                canvas = _api.Image.new(cmode, (max_w, total_h), bg)
                y = 0
                for im in processed:
                    canvas.paste(im, (0, y)); y += im.height
            else:
                max_h = max(im.height for im in imgs)
                processed = []
                total_w = 0
                for im in imgs:
                    r = max_h / im.height
                    new_w = int(im.width * r)
                    processed.append(im.resize((new_w, max_h), _api.Image.Resampling.LANCZOS))
                    total_w += new_w
                canvas = _api.Image.new(cmode, (total_w, max_h), bg)
                x = 0
                for im in processed:
                    canvas.paste(im, (x, 0)); x += im.width

            # ── Output path: всегда рядом с исходными файлами ──
            out_dir = _api.os.path.dirname(paths[0]) or "."

            out_path = _api.os.path.join(out_dir, f"merged_{_api.random.randint(1000, 9999)}.{ext}")
            canvas.save(out_path, format=pil_fmt, **save_kwargs)

            # ── Mark items ─────────────────────────────────
            self.file_list.mark_processed(items)

            # ── Preview ────────────────────────────────────
            pix = _api.QPixmap(out_path)
            prev_w = self.lbl_preview.parent().width() - 30
            if prev_w < 80: prev_w = 80
            self.lbl_preview.setPixmap(
                pix.scaledToWidth(prev_w, _api.Qt.TransformationMode.SmoothTransformation))
            # Запоминаем результат и показываем кнопку «на весь экран».
            self._last_result_path = out_path
            self.btn_preview_fs.show()
            self._reposition_preview_fs()

            self.lbl_status.setText(_api.status_html('fa5s.check-circle',
                f"Готово! {len(imgs)} фото → {_api.os.path.basename(out_path)}", '#a6e3a1'))
            self.main.log(f"[Фото] Объединено {len(imgs)} файлов → {out_path}")

            # ── Отправить результат в очередь первой вкладки ──
            try:
                self.main.tab_media.add_paths([out_path])
                self.main.tabs.setCurrentWidget(self.main.tab_media)
                self.main.log(f"[Фото] Файл добавлен в очередь обработки: {_api.os.path.basename(out_path)}")
            except Exception as send_exc:
                self.main.log(f"[Фото] Не удалось добавить в очередь: {send_exc}")

            try: _api.play_done_sound()
            except Exception: pass

        except Exception as exc:
            try: self.file_list.mark_failed(items)
            except Exception: pass
            self.lbl_status.setText(_api.status_html('fa5s.times-circle', f"Ошибка: {exc}", '#f38ba8'))
            self.main.log(f"[Фото] Ошибка объединения: {exc}")
        finally:
            # Закрываем все PIL-изображения, чтобы избежать утечки памяти
            for im in imgs if 'imgs' in dir() else []:
                try: im.close()
                except Exception: pass

PhotoMergerTab.__module__ = _api.__name__
_api.PhotoMergerTab = PhotoMergerTab
