# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_TrackAttachDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


class _TrackAttachDialog(_api.QDialog):
    """«Привязать к объекту»: пользователь обводит рамкой объект на кадре
    (движущуюся руку, лицо, машину), выбирает, что к нему привязать — текст или
    картинку, — и как эта накладка стоит относительно рамки.

    Диалог НЕ отслеживает движение: он только собирает задание. Само отслеживание
    делает трекер DyHiT (dyhit_tracker.py) в фоновом воркере TrackOverlayWorker.
    Накладка рендерится здесь, в главном потоке (Qt-шрифты/QPainter), и уходит в
    воркер готовой BGRA-картинкой в разрешении ИСХОДНОГО кадра."""

    ANCHORS = (("center", "По центру области"),
               ("top", "Над областью"),
               ("bottom", "Под областью"),
               ("left", "Слева от области"),
               ("right", "Справа от области"))

    def __init__(self, frame_bgr, parent=None, start_s=0.0, end_s=None,
                 zone_end_s=None):
        super().__init__(parent)
        from photo_tab import np_bgr_to_qimage, np_bgra_to_qimage
        from edit_tab_widgets import _TrackSelectCanvas
        import dyhit_tracker

        self._np_bgra_to_qimage = np_bgra_to_qimage
        self._frame = frame_bgr
        self._fh, self._fw = frame_bgr.shape[:2]
        self._start_s = float(start_s)
        self._video_end_s = float(end_s) if end_s else 0.0
        self._zone_end_s = float(zone_end_s) if zone_end_s else 0.0
        self._img_bgra = None            # исходная картинка-накладка (BGRA)
        self._img_path = ""
        self._overlay_bgra = None        # готовая накладка в пикселях кадра
        self._text_color = "#ffffff"
        self._outline_color = "#000000"

        self.setWindowTitle("Привязать к объекту")
        self.resize(1120, 720)
        self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QRadioButton {{ color: {_api.C['text']}; font-size: 12px; }}
        """)

        root = _api.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        hint = _api.QLabel(
            "Обведите рамкой объект, за которым нужно следить (например, руку). "
            "Нейросеть найдёт его на каждом следующем кадре, и выбранная накладка "
            "поедет вместе с ним. Рамку можно перетаскивать, а протяжкой по "
            "свободному месту — нарисовать заново. Накладка сразу появится в "
            "плеере, а в файл её сохранит кнопка «Обрезать».")
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = _api.QHBoxLayout(); body.setSpacing(12)
        self.canvas = _TrackSelectCanvas()
        self.canvas.set_image(np_bgr_to_qimage(frame_bgr))
        self.canvas.boxChanged.connect(self._rebuild_overlay)
        body.addWidget(self.canvas, 3)

        side = _api.QVBoxLayout(); side.setSpacing(8)
        body.addLayout(side, 2)
        root.addLayout(body, 1)

        # ── Что привязываем ──────────────────────────────────────────────────
        side.addWidget(self._section("Что привязать"))
        kind_row = _api.QHBoxLayout(); kind_row.setSpacing(12)
        self.rb_text = _api.QRadioButton("Текст")
        self.rb_image = _api.QRadioButton("Картинку")
        self.rb_text.setChecked(True)
        self._kind_group = _api.QButtonGroup(self)
        self._kind_group.addButton(self.rb_text, 0)
        self._kind_group.addButton(self.rb_image, 1)
        kind_row.addWidget(self.rb_text); kind_row.addWidget(self.rb_image)
        kind_row.addStretch(1)
        side.addLayout(kind_row)

        # Текст
        self.text_box = _api.QWidget()
        tb = _api.QVBoxLayout(self.text_box); tb.setContentsMargins(0, 0, 0, 0); tb.setSpacing(6)
        self.ed_text = _api.QLineEdit("Текст")
        self.ed_text.setPlaceholderText("Что написать рядом с объектом")
        tb.addWidget(self.ed_text)
        r1 = _api.QHBoxLayout(); r1.setSpacing(8)
        r1.addWidget(_api.QLabel("Размер, px"))
        self.sp_size = _api.QSpinBox(); self.sp_size.setRange(8, 400)
        self.sp_size.setValue(max(16, int(self._fh * 0.06)))
        r1.addWidget(self.sp_size)
        r1.addWidget(_api.QLabel("Цвет"))
        self.btn_color = self._color_btn(self._text_color)
        self.btn_color.clicked.connect(self._pick_text_color)
        r1.addWidget(self.btn_color)
        r1.addStretch(1)
        tb.addLayout(r1)
        r2 = _api.QHBoxLayout(); r2.setSpacing(8)
        r2.addWidget(_api.QLabel("Обводка, px"))
        self.sp_outline = _api.QSpinBox(); self.sp_outline.setRange(0, 20); self.sp_outline.setValue(3)
        r2.addWidget(self.sp_outline)
        self.btn_outline_color = self._color_btn(self._outline_color)
        self.btn_outline_color.clicked.connect(self._pick_outline_color)
        r2.addWidget(self.btn_outline_color)
        self.chk_bold = _api.QCheckBox("Жирный"); self.chk_bold.setChecked(True)
        r2.addWidget(self.chk_bold)
        r2.addStretch(1)
        tb.addLayout(r2)
        side.addWidget(self.text_box)

        # Картинка
        self.image_box = _api.QWidget()
        ib = _api.QVBoxLayout(self.image_box); ib.setContentsMargins(0, 0, 0, 0); ib.setSpacing(6)
        pick_row = _api.QHBoxLayout(); pick_row.setSpacing(8)
        self.lbl_img = _api.QLabel("Файл не выбран")
        self.lbl_img.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px;")
        btn_pick = _api.make_icon_btn("Выбрать…", icon='fa5s.image')
        btn_pick.clicked.connect(self._pick_image)
        pick_row.addWidget(self.lbl_img, 1); pick_row.addWidget(btn_pick, 0)
        ib.addLayout(pick_row)
        r3 = _api.QHBoxLayout(); r3.setSpacing(8)
        r3.addWidget(_api.QLabel("Ширина, % от рамки"))
        self.sp_img_pct = _api.QSpinBox(); self.sp_img_pct.setRange(5, 500); self.sp_img_pct.setValue(100)
        r3.addWidget(self.sp_img_pct); r3.addStretch(1)
        ib.addLayout(r3)
        self.image_box.setVisible(False)
        side.addWidget(self.image_box)

        # ── Расположение ─────────────────────────────────────────────────────
        side.addWidget(self._section("Где держать накладку"))
        r4 = _api.QHBoxLayout(); r4.setSpacing(8)
        r4.addWidget(_api.QLabel("Привязка"))
        self.cmb_anchor = _api.QComboBox()
        for _key, title in self.ANCHORS:
            self.cmb_anchor.addItem(title)
        self.cmb_anchor.setCurrentIndex(1)          # «Над областью» — как подпись
        r4.addWidget(self.cmb_anchor, 1)
        side.addLayout(r4)
        r5 = _api.QHBoxLayout(); r5.setSpacing(8)
        r5.addWidget(_api.QLabel("Сдвиг X"))
        self.sp_off_x = _api.QSpinBox(); self.sp_off_x.setRange(-4000, 4000)
        r5.addWidget(self.sp_off_x)
        r5.addWidget(_api.QLabel("Y"))
        self.sp_off_y = _api.QSpinBox(); self.sp_off_y.setRange(-4000, 4000)
        r5.addWidget(self.sp_off_y)
        r5.addStretch(1)
        side.addLayout(r5)
        self.chk_scale = _api.QCheckBox("Менять размер вместе с объектом")
        self.chk_scale.setToolTip(
            "Объект приближается — накладка растёт, удаляется — уменьшается")
        side.addWidget(self.chk_scale)
        self.chk_smooth = _api.QCheckBox("Сглаживать движение")
        self.chk_smooth.setChecked(True)
        self.chk_smooth.setToolTip(
            "Гасит дрожание накладки. Фильтр адаптивный: на стоящем объекте "
            "давит шум сильно, на быстром движении почти не отстаёт — выключать "
            "стоит разве что для сравнения")
        side.addWidget(self.chk_smooth)

        # ── Отрезок и движок ─────────────────────────────────────────────────
        side.addWidget(self._section("Отрезок"))
        self.chk_zone = _api.QCheckBox("Только до конца выделенной зоны")
        self.chk_zone.setChecked(bool(self._zone_end_s
                                      and self._zone_end_s < self._video_end_s - 0.05))
        self.chk_zone.setEnabled(bool(self._zone_end_s))
        side.addWidget(self.chk_zone)
        self.lbl_range = _api.QLabel("")
        self.lbl_range.setWordWrap(True)
        side.addWidget(self.lbl_range)

        engine = dyhit_tracker.active_backend_label()
        lbl_engine = _api.QLabel(f"Трекер: {engine}")
        lbl_engine.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        side.addWidget(lbl_engine)
        if not dyhit_tracker.dyhit_available():
            note = _api.QLabel(
                "Модель DyHiT не найдена — используется запасной трекер OpenCV. "
                "Чтобы включить нейросеть, положите .onnx-файл DyHiT/HiT в папку "
                "models (ожидается имя dyhit.onnx).")
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px;")
            side.addWidget(note)
        side.addStretch(1)

        bb = _api.QDialogButtonBox()
        self.btn_ok = bb.addButton("Показать предпросмотр",
                                   _api.QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Отмена", _api.QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Любая правка — сразу пересобирает накладку и превью на кадре.
        self.rb_text.toggled.connect(self._on_kind_changed)
        self.ed_text.textChanged.connect(self._rebuild_overlay)
        self.chk_zone.toggled.connect(self._update_range_label)
        for w in (self.sp_size, self.sp_outline, self.sp_off_x, self.sp_off_y,
                  self.sp_img_pct):
            w.valueChanged.connect(self._rebuild_overlay)
        self.chk_bold.toggled.connect(self._rebuild_overlay)
        self.cmb_anchor.currentIndexChanged.connect(self._rebuild_overlay)

        self._update_range_label()
        self._rebuild_overlay()

    # ── мелкие помощники интерфейса ──────────────────────────────────────────
    @staticmethod
    def _section(title):
        lbl = _api.QLabel(title)
        lbl.setStyleSheet(f"color: {_api.C['text']}; font-size: 12px; font-weight: 700;")
        return lbl

    @staticmethod
    def _color_btn(hex_color):
        # Курсор-«рука» ставит глобальный HoverTipManager — вручную не трогаем.
        b = _api.QPushButton()
        b.setFixedSize(34, 26)
        b.setStyleSheet(f"QPushButton {{ background: {hex_color}; "
                        f"border: 1px solid {_api.C['border2']}; border-radius: 5px; }}")
        return b

    def _pick_text_color(self):
        col = _api.QColorDialog.getColor(_api.QColor(self._text_color), self, "Цвет текста")
        if col.isValid():
            self._text_color = col.name()
            self.btn_color.setStyleSheet(
                f"QPushButton {{ background: {self._text_color}; "
                f"border: 1px solid {_api.C['border2']}; border-radius: 5px; }}")
            self._rebuild_overlay()

    def _pick_outline_color(self):
        col = _api.QColorDialog.getColor(_api.QColor(self._outline_color), self, "Цвет обводки")
        if col.isValid():
            self._outline_color = col.name()
            self.btn_outline_color.setStyleSheet(
                f"QPushButton {{ background: {self._outline_color}; "
                f"border: 1px solid {_api.C['border2']}; border-radius: 5px; }}")
            self._rebuild_overlay()

    def _on_kind_changed(self, _checked=False):
        is_text = self.rb_text.isChecked()
        self.text_box.setVisible(is_text)
        self.image_box.setVisible(not is_text)
        self._rebuild_overlay()

    def _pick_image(self):
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Картинка для привязки", "",
            "Изображения (*.png *.webp *.jpg *.jpeg *.bmp *.gif);;Все файлы (*.*)")
        if not path:
            return
        try:
            from photo_tab import _load_image_alpha
            import numpy as np
            img = _load_image_alpha(path)
            if img is None:
                raise ValueError("не удалось прочитать файл")
            if img.shape[2] == 3:      # без альфы — добиваем непрозрачным каналом
                img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
            self._img_bgra = np.ascontiguousarray(img)
            self._img_path = path
        except Exception as e:
            _api.msgbox_warning(self, "Не удалось открыть картинку", str(e))
            return
        self.lbl_img.setText(_api.os.path.basename(path))
        self.lbl_img.setStyleSheet(f"color: {_api.C['text2']}; font-size: 11px;")
        self._rebuild_overlay()

    def _update_range_label(self):
        end = self._effective_end()
        self.lbl_range.setText(
            f"С {_api.s_to_time(self._start_s)} до {_api.s_to_time(end)} — накладка видна "
            f"только на этом отрезке, остальное видео не меняется.")

    def _effective_end(self):
        if self.chk_zone.isChecked() and self._zone_end_s:
            return self._zone_end_s
        return self._video_end_s or self._zone_end_s or 0.0

    # ── сборка накладки ──────────────────────────────────────────────────────
    def _render_text_bgra(self):
        """Текст с обводкой → BGRA numpy в пикселях исходного кадра."""
        import numpy as np
        from PyQt6.QtGui import QFontMetrics, QImage, QPainter, QPainterPath, QPen
        text = self.ed_text.text()
        if not text.strip():
            return None
        font = _api.QFont()
        font.setPixelSize(int(self.sp_size.value()))
        font.setBold(self.chk_bold.isChecked())
        fm = QFontMetrics(font)
        ow = int(self.sp_outline.value())
        pad = ow + 4
        w = fm.horizontalAdvance(text) + 2 * pad
        h = fm.height() + 2 * pad
        img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32)
        img.fill(_api.QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addText(float(pad), float(pad + fm.ascent()), font, text)
        if ow > 0:
            pen = QPen(_api.QColor(self._outline_color))
            pen.setWidthF(ow * 2.0)          # штрих идёт по центру контура
            pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
        p.fillPath(path, _api.QColor(self._text_color))
        p.end()
        # Format_ARGB32 на little-endian лежит в памяти как B,G,R,A — ровно BGRA.
        # Учитываем bytesPerLine: при ширине не кратной 4 строки выровнены, и без
        # этого картинка «съезжает». .copy() ОБЯЗАТЕЛЕН: без него numpy остаётся
        # видом на буфер QImage, который умрёт вместе с локальной img на выходе
        # из функции, — и накладка превращается в цветной мусор.
        bpl = img.bytesPerLine()
        ptr = img.constBits(); ptr.setsize(bpl * img.height())
        buf = np.frombuffer(ptr, np.uint8).reshape(img.height(), bpl)
        return buf[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()

    def _render_image_bgra(self):
        """Картинка, приведённая к ширине «% от рамки» (или от кадра, если рамки
        ещё нет), → BGRA numpy."""
        if self._img_bgra is None:
            return None
        import cv2
        box = self.canvas.box_px()
        base_w = box[2] if box else self._fw * 0.25
        target_w = max(4.0, base_w * self.sp_img_pct.value() / 100.0)
        oh, ow = self._img_bgra.shape[:2]
        scale = target_w / max(1, ow)
        nw, nh = max(1, int(round(ow * scale))), max(1, int(round(oh * scale)))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        return cv2.resize(self._img_bgra, (nw, nh), interpolation=interp)

    def _rebuild_overlay(self):
        try:
            self._overlay_bgra = (self._render_text_bgra() if self.rb_text.isChecked()
                                  else self._render_image_bgra())
        except Exception:
            self._overlay_bgra = None
        qimg = (self._np_bgra_to_qimage(self._overlay_bgra)
                if self._overlay_bgra is not None else None)
        self.canvas.set_overlay(qimg, self.anchor_key(),
                                (self.sp_off_x.value(), self.sp_off_y.value()))

    # ── результат ────────────────────────────────────────────────────────────
    def anchor_key(self):
        return self.ANCHORS[max(0, self.cmb_anchor.currentIndex())][0]

    def _accept(self):
        if self.canvas.box_px() is None:
            _api.msgbox_information(self, "Область не выбрана",
                               "Сначала обведите рамкой объект, за которым нужно "
                               "следить.")
            return
        if self._overlay_bgra is None:
            _api.msgbox_information(
                self, "Нечего привязывать",
                "Введите текст или выберите картинку — её и привяжем к объекту.")
            return
        self.accept()

    def values(self):
        """Задание для TrackOverlayWorker."""
        return {
            "box": self.canvas.box_px(),
            "overlay_bgra": self._overlay_bgra,
            "anchor": self.anchor_key(),
            "off_x": int(self.sp_off_x.value()),
            "off_y": int(self.sp_off_y.value()),
            "scale_with_box": bool(self.chk_scale.isChecked()),
            "smooth": 1.0 if self.chk_smooth.isChecked() else 0.0,
            "start_s": self._start_s,
            "end_s": self._effective_end(),
        }

_TrackAttachDialog.__module__ = _api.__name__
_api._TrackAttachDialog = _TrackAttachDialog
