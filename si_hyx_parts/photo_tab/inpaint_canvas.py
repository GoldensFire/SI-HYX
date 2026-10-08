# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas. Public namespace: photo_tab."""
import photo_tab as _api
from si_hyx_parts.photo_tab.canvas_editing import InpaintCanvasEditingMixin
from si_hyx_parts.photo_tab.canvas_objects import InpaintCanvasObjectsMixin


# ════════════════════════════════════════════════════════════════════════════
#  Удаление объектов / водяных знаков (LaMa, ONNX)
# ════════════════════════════════════════════════════════════════════════════
# WASD-пан, независимый от раскладки: на кириллице ev.key() физической W даёт Key_Ц,
# поэтому WASD читаем по nativeVirtualKey (Windows VK W=0x57/A=0x41/S=0x53/D=0x44).

class InpaintCanvas(InpaintCanvasEditingMixin, InpaintCanvasObjectsMixin, _api.QWidget):
    """Холст редактора: показ изображения с зумом/панорамированием, рисование
    маски кистью/ластиком (полупрозрачным красным), инструмент кадрирования.

    Источник истины — numpy-массив BGR (self.img_bgr). Маска хранится как ARGB
    QImage-оверлей в РАЗРЕШЕНИИ изображения (а не экрана), поэтому точность не
    зависит от зума. Для инференса маска вынимается из альфа-канала оверлея."""

    TOOL_BRUSH = "brush"   # рисующая кисть ПО фото (мазок вживается в img_bgr)
    TOOL_MASK = "mask"     # кисть-маска: красным помечает область для удаления (LaMa)
    TOOL_ERASE = "erase"
    TOOL_CROP = "crop"
    TOOL_BLUR = "blur"     # кисть размытия: замыливает фото под мазком (в img_bgr)
    TOOL_MOVE = "move"   # перемещение наложенного (второго) изображения-слоя
    # Фигуры и текст (как в Paint) — рисуются прямо в изображение (self.img_bgr),
    # а не в маску-оверлей.
    TOOL_RECT = "rect"
    TOOL_ELLIPSE = "ellipse"
    TOOL_LINE = "line"
    TOOL_ARROW = "arrow"
    TOOL_TEXT = "text"
    _SHAPE_TOOLS = (TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE, TOOL_ARROW)

    # Толщина скроллбаров, всплывающих при сильном приближении.
    _SB_THICK = 12

    statusChanged = _api.pyqtSignal(str)
    colorPicked = _api.pyqtSignal(_api.QColor)     # Alt-пипетка взяла цвет из изображения
    strokeFinished = _api.pyqtSignal()        # завершён штрих кистью (для авто-удаления)
    clearRequested = _api.pyqtSignal()        # нажата кнопка «Очистить» в углу холста
    imageChanged = _api.pyqtSignal()          # появилось/исчезло изображение (undo/redo) — пере-включить инструменты
    textSelected = _api.pyqtSignal()          # плавающий текст создан/выделен — открыть панель его свойств

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img_bgr = None             # numpy (H,W,3) BGR — рабочее изображение
        self._overlay = None            # QImage ARGB32_Premult (H,W) — маска удаления (красная)
        # Слой краски «Кисти»: непрозрачные мазки поверх фото, НЕ вживляются сразу
        # (как в Photoshop), чтобы их можно было стирать Ластиком. Вживляются в
        # img_bgr только перед удалением объекта / кадрированием / сохранением.
        self._paint_layer = None        # QImage ARGB32_Premult (H,W) — мазки кисти
        self._has_paint = False
        # Маска прозрачности после «Удалить фон» (RMBG): numpy (H,W) uint8 [0..255],
        # 255 = объект (видимый), 0 = фон (прозрачный). None — фон не удалён.
        # Хранится ОТДЕЛЬНО от img_bgr (он всегда 3-канальный BGR); прозрачность
        # показываем шахматкой в _rebuild_base, а при сохранении склеиваем в BGRA.
        self._alpha = None
        self._base_pix = None           # QPixmap кэш изображения для отрисовки
        self._overlay_btns_state = None  # memo-ключ _sync_overlay_buttons (см. там)
        self._scale = 1.0
        self._off = _api.QPointF(0, 0)
        self._user_zoomed = False
        self._tool = self.TOOL_MOVE
        self._brush = 30                # диаметр кисти в ЭКРАННЫХ px
        self._brush_color = _api.QColor(235, 45, 45)   # цвет рисующей кисти (по фото)
        # «Размытие»: степень = сигма гауссова размытия в ПИКСЕЛЯХ ИЗОБРАЖЕНИЯ.
        # Замыленная копия и маска штриха живут только на время одного мазка
        # (см. _begin_blur_stroke): так повторный проход кистью по тому же месту
        # не «умножает» размытие внутри одного штриха, а между штрихами — да.
        self._blur_strength = 12
        self._blur_orig = None          # картинка на начало штриха (numpy BGR)
        self._blur_dst = None           # она же, размытая целиком
        self._blur_mask = None          # numpy (H,W) uint8 — где провели кистью
        self._painting = False
        self._panning = False
        self._last_img_pt = None        # последняя точка штриха (коорд. изображения)
        self._pan_start = None
        self._off_start = None
        self._mouse_w = None            # позиция мыши (виджет) для кольца-курсора
        self._alt = False               # зажат ли Alt (кисть → временная пипетка)
        self._has_strokes = False
        # Фигуры (Paint): тянем от _shape_start до _shape_cur (коорд. изображения),
        # коммитим в картинку на отпускании ЛКМ. _shape_fill — заливать ли фигуру.
        self._shape_start = None
        self._shape_cur = None
        self._shape_drawing = False
        self._shape_fill = False
        # Шрифт инструмента «Текст» (по умолчанию — системный, 48 px высотой).
        self._text_font = _api.QFont()
        self._text_font.setPixelSize(48)
        self._text_color = _api.QColor(255, 255, 255)     # цвет НОВОГО текста (не влияет на уже созданный)
        self._text_stroke_width = 0.0
        self._text_stroke_color = _api.QColor(0, 0, 0)
        self._crop_a = None             # верх-лев угол рамки кадрирования (коорд. изобр.)
        self._crop_b = None             # ниж-прав угол рамки кадрирования
        self._crop_drag = None          # активная «ручка»: tl/tr/bl/br/t/b/l/r/move
        self._crop_anchor = None        # точка-якорь (коорд. изобр.) при перетаскивании
        self._crop_start = None         # (a, b) на момент начала перетаскивания
        self._crop_aspect = None        # пропорция w/h рамки (None = свободно)
        self._history = []              # [(img_bgr, overlay QImage)] для отмены
        self._redo = []                 # стек возврата (Ctrl+Y)
        self._HISTORY_MAX = 8
        # Кэш PNG-кодирования img_bgr для _snapshot(): само фото не меняется во
        # время штриха кистью/ластиком (мазки идут в _paint_layer), а перекодировать
        # его целиком на КАЖДОЕ нажатие ЛКМ (_push_history) — это заметный фриз
        # на крупных фото (счёт на сотни мс). img_bgr всегда переприсваивается
        # новым массивом при реальном изменении (поворот/кроп/bake) — сравнение
        # по identity безопасно.
        self._bgr_snap_src = None
        self._bgr_snap_enc = None
        # Незакреплённый («плавающий») объект — фигура или текст, который только
        # что положили: его можно ПЕРЕТАСКИВАТЬ (как в Photoshop), пока не вжали в
        # картинку. Вжигается при клике вне него / смене инструмента / Enter / сейве.
        #   shape: {'kind':'shape','tool',a,b,'color','thickness','fill'}
        #   text:  {'kind':'text','pos','text','font','color'}
        self._pending = None
        self._pending_move = False      # тащим ли сейчас плавающий объект
        self._pending_anchor = None     # точка-якорь (коорд. изобр.) при перетаскивании
        self._pending_resize = None     # имя тянущейся ручки ('tl'..'r') или None
        self._pending_rs_rect0 = None   # bbox объекта на начало resize (коорд. изобр.)

        self.setMouseTracking(True)
        self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(_api.QSizePolicy.Policy.Expanding, _api.QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 280)
        self.setCursor(_api.Qt.CursorShape.CrossCursor)

        # Кнопки «Применить/Отмена» кадрирования живут ПРЯМО на холсте (как в
        # Photoshop): всплывают у рамки кадрирования, когда активен инструмент.
        self._crop_apply_btn = _api._icon_btn("Применить", 'fa5s.check', size=16)
        self._crop_apply_btn.setParent(self)
        self._crop_apply_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self._crop_apply_btn.setToolTip("Применить кадрирование (Enter)")
        self._crop_apply_btn.clicked.connect(self.apply_crop)
        self._crop_apply_btn.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;border:none;"
            "border-radius:5px;padding:5px 10px;font-weight:600;}"
            "QPushButton:hover{background:#b9f0b4;}")
        self._crop_cancel_btn = _api._icon_btn("Отмена", 'fa5s.times', size=16)
        self._crop_cancel_btn.setParent(self)
        self._crop_cancel_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self._crop_cancel_btn.setToolTip("Отменить кадрирование (Esc)")
        self._crop_cancel_btn.clicked.connect(self.cancel_crop)
        self._crop_cancel_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:5px;padding:5px 10px;}"
            "QPushButton:hover{background:#45475a;}")
        for _b in (self._crop_apply_btn, self._crop_cancel_btn):
            _b.setVisible(False)

        # Выбор пропорций кадрирования ПРЯМО на холсте (как в Photoshop): свободно
        # или фиксированное соотношение (1:1, 4:3, 16:9 …). Всплывает над рамкой.
        self._crop_aspect_combo = _api.QComboBox(self)
        self._crop_aspect_combo.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self._crop_aspect_combo.setToolTip("Пропорции рамки кадрирования")
        # (подпись, w/h или None=свободно). «Исходное» считается от размера картинки.
        self._crop_aspect_items = [
            ("Свободно", None), ("Исходное", 'orig'), ("1:1", 1.0),
            ("4:3", 4 / 3), ("3:4", 3 / 4), ("3:2", 3 / 2), ("2:3", 2 / 3),
            ("16:9", 16 / 9), ("9:16", 9 / 16), ("5:4", 5 / 4)]
        for name, _v in self._crop_aspect_items:
            self._crop_aspect_combo.addItem(name)
        self._crop_aspect_combo.setStyleSheet(
            "QComboBox{background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:5px;padding:3px 8px;font-weight:600;}"
            "QComboBox:hover{border:1px solid #89b4fa;}"
            "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;"
            "selection-background-color:#45475a;}")
        self._crop_aspect_combo.currentIndexChanged.connect(self._on_crop_aspect_changed)
        self._crop_aspect_combo.setVisible(False)

        # Отмена/возврат — компактные значки в левом верхнем углу холста (как в
        # фоторедакторах), без подписей. Прямые стрелки влево/вправо, как кнопки
        # «назад/вперёд» в браузере (а не закруглённые fa5s.undo/redo). Доступны,
        # пока есть изображение.
        self._undo_btn = _api.QPushButton(self)
        self._undo_btn.setIcon(_api.get_icon('fa5s.arrow-left'))
        self._undo_btn.setToolTip("Отменить (Ctrl+Z)")
        self._undo_btn.clicked.connect(self.undo)
        self._redo_btn = _api.QPushButton(self)
        self._redo_btn.setIcon(_api.get_icon('fa5s.arrow-right'))
        self._redo_btn.setToolTip("Вернуть (Ctrl+Y)")
        self._redo_btn.clicked.connect(self.redo)
        for _b in (self._undo_btn, self._redo_btn):
            _b.setParent(self)
            _b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            _b.setFixedSize(34, 30)
            _b.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
            _b.setStyleSheet(
                "QPushButton{background:rgba(30,30,46,0.82);color:#cdd6f4;"
                "border:1px solid #45475a;border-radius:6px;}"
                "QPushButton:hover{background:rgba(69,71,90,0.95);}"
                "QPushButton:disabled{color:#585b70;border-color:#313244;}")
            _b.setVisible(False)

        # «Очистить» — значок в ПРАВОМ верхнем углу холста (как кнопка закрытия
        # документа в фоторедакторах). Сам сброс делает вкладка (clearRequested).
        self._clear_btn = _api.QPushButton(self)
        self._clear_btn.setIcon(_api.get_icon('fa5s.trash'))
        self._clear_btn.setToolTip("Очистить холст — убрать изображение и все мазки")
        self._clear_btn.setParent(self)
        self._clear_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setFixedSize(34, 30)
        self._clear_btn.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self._clear_btn.setStyleSheet(
            "QPushButton{background:rgba(30,30,46,0.82);color:#f38ba8;"
            "border:1px solid #45475a;border-radius:6px;}"
            "QPushButton:hover{background:rgba(243,139,168,0.22);border-color:#f38ba8;}")
        self._clear_btn.clicked.connect(self.clearRequested.emit)
        self._clear_btn.setVisible(False)

        # Поворот/отражение — значки по центру сверху холста (видны при наличии
        # картинки; каждое действие в историю — см. rotate_image/flip_image).
        self._rotl_btn = _api.QPushButton(self)
        self._rotl_btn.setIcon(_api.get_icon('mdi6.rotate-left'))
        self._rotl_btn.setToolTip("Повернуть против часовой стрелки")
        self._rotl_btn.clicked.connect(lambda: self.rotate_image(False))
        self._rotr_btn = _api.QPushButton(self)
        self._rotr_btn.setIcon(_api.get_icon('mdi6.rotate-right'))
        self._rotr_btn.setToolTip("Повернуть по часовой стрелке")
        self._rotr_btn.clicked.connect(lambda: self.rotate_image(True))
        self._fliph_btn = _api.QPushButton(self)
        self._fliph_btn.setIcon(_api.get_icon('mdi6.flip-horizontal'))
        self._fliph_btn.setToolTip("Отразить по горизонтали (зеркально)")
        self._fliph_btn.clicked.connect(lambda: self.flip_image(True))
        self._flipv_btn = _api.QPushButton(self)
        self._flipv_btn.setIcon(_api.get_icon('mdi6.flip-vertical'))
        self._flipv_btn.setToolTip("Отразить по вертикали")
        self._flipv_btn.clicked.connect(lambda: self.flip_image(False))
        self._orient_btns = [self._rotl_btn, self._rotr_btn,
                             self._fliph_btn, self._flipv_btn]
        for _b in self._orient_btns:
            _b.setParent(self)
            _b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            _b.setFixedSize(34, 30)
            _b.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
            _b.setStyleSheet(
                "QPushButton{background:rgba(30,30,46,0.82);color:#cdd6f4;"
                "border:1px solid #45475a;border-radius:6px;}"
                "QPushButton:hover{background:rgba(69,71,90,0.95);}"
                "QPushButton:disabled{color:#585b70;border-color:#313244;}")
            _b.setVisible(False)

        # Скроллбары всплывают при сильном приближении (когда картинка не влезает
        # в холст) — как в Photoshop/Paint. Перетаскивание ползунка двигает кадр.
        self._syncing_bars = False
        self._hbar = _api.QScrollBar(_api.Qt.Orientation.Horizontal, self)
        self._vbar = _api.QScrollBar(_api.Qt.Orientation.Vertical, self)
        for _sb in (self._hbar, self._vbar):
            _sb.setCursor(_api.Qt.CursorShape.ArrowCursor)
            _sb.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
            _sb.setVisible(False)
        self._hbar.valueChanged.connect(self._on_hbar)
        self._vbar.valueChanged.connect(self._on_vbar)

    def _sync_overlay_buttons(self):
        """Показ/позиция/доступность значков отмены-возврата (слева сверху) и
        кнопки «Очистить» (справа сверху) на холсте.
        Вызывается из paintEvent на КАЖДЫЙ репейнт (в т.ч. на каждый мазок кисти
        при рисовании) — но фактическая раскладка зависит только от небольшого
        набора значений; если ни один не изменился с прошлого вызова, репозиция
        виджетов (десяток .move()/.setEnabled() на кадр) не нужна."""
        has = self.img_bgr is not None
        state = (has, self.width(),
                 bool(self._history), bool(self._redo),
                 self._vbar.isVisible() if has else False)
        if state == self._overlay_btns_state:
            return
        self._overlay_btns_state = state
        all_btns = [self._undo_btn, self._redo_btn, self._clear_btn] + self._orient_btns
        for b in all_btns:
            b.setVisible(has)
        if not has:
            return
        x, y, gap = 8, 8, 6
        self._undo_btn.move(x, y)
        self._redo_btn.move(x + self._undo_btn.width() + gap, y)
        self._undo_btn.setEnabled(bool(self._history))
        self._redo_btn.setEnabled(bool(self._redo))
        # «Очистить» — у правого края холста (с учётом возможного скроллбара).
        sb = self._SB_THICK if self._vbar.isVisible() else 0
        self._clear_btn.move(self.width() - self._clear_btn.width() - 8 - sb, y)
        # Поворот/отражение — по центру верхней кромки холста, в ряд.
        ob = self._orient_btns
        bw = ob[0].width()
        total = bw * len(ob) + gap * (len(ob) - 1)
        ox = max(0, (self.width() - total) // 2)
        for i, b in enumerate(ob):
            b.move(ox + i * (bw + gap), y)
        for b in all_btns:
            b.raise_()

    # ── Состояние / загрузка ────────────────────────────────────────────────
    def has_image(self) -> bool:
        return self.img_bgr is not None

    def has_mask(self) -> bool:
        return self._has_strokes

    def set_image_bgr(self, arr):
        self.img_bgr = _api._np.ascontiguousarray(arr)
        h, w = self.img_bgr.shape[:2]
        self._overlay = _api.QtGuiImage(w, h, _api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
        self._overlay.fill(0)
        self._paint_layer = _api.QtGuiImage(w, h, _api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
        self._paint_layer.fill(0)
        self._has_paint = False
        self._alpha = None          # новая картинка — прозрачности нет
        self._has_strokes = False
        self._history.clear()
        self._redo.clear()
        self._pending = None
        self._pending_move = False
        self._crop_a = self._crop_b = None
        self._rebuild_base()
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()

    def _sync_scrollbars(self):
        """Показывает/прячет и настраивает скроллбары под текущий зум/смещение."""
        if self.img_bgr is None:
            self._hbar.setVisible(False)
            self._vbar.setVisible(False)
            return
        self._syncing_bars = True
        try:
            cw, ch = self._content_size()
            W, H = self.width(), self.height()
            t = self._SB_THICK
            # Бар по одной оси «съедает» место у встречной — учитываем взаимно.
            need_h = cw > W
            need_v = ch > H
            need_h = cw > (W - (t if need_v else 0))
            need_v = ch > (H - (t if need_h else 0))
            vw = W - (t if need_v else 0)
            vh = H - (t if need_h else 0)
            self._clamp_off()
            if need_h:
                self._hbar.setGeometry(0, H - t, vw, t)
                self._hbar.setPageStep(max(1, int(vw)))
                self._hbar.setSingleStep(max(1, int(vw * 0.1)))
                self._hbar.setRange(0, max(0, int(round(cw - vw))))
                self._hbar.setValue(int(round(-self._off.x())))
                self._hbar.setVisible(True)
                self._hbar.raise_()
            else:
                self._hbar.setVisible(False)
            if need_v:
                self._vbar.setGeometry(W - t, 0, t, vh)
                self._vbar.setPageStep(max(1, int(vh)))
                self._vbar.setSingleStep(max(1, int(vh * 0.1)))
                self._vbar.setRange(0, max(0, int(round(ch - vh))))
                self._vbar.setValue(int(round(-self._off.y())))
                self._vbar.setVisible(True)
                self._vbar.raise_()
            else:
                self._vbar.setVisible(False)
        finally:
            self._syncing_bars = False

    def _on_hbar(self, v):
        if self._syncing_bars or self.img_bgr is None:
            return
        self._off.setX(-float(v))
        self._update_crop_buttons()
        self.update()

    def _on_vbar(self, v):
        if self._syncing_bars or self.img_bgr is None:
            return
        self._off.setY(-float(v))
        self._update_crop_buttons()
        self.update()

    # ── Рисование штриха ─────────────────────────────────────────────────────
    def _paint_to(self, img_pt):
        # «Кисть» рисует по слою краски (поверх фото), «Ластик» стирает ИМЕННО
        # этот слой (мазки кисти), а не маску удаления. TOOL_MASK — красная маска
        # удаления в отдельном оверлее.
        if self._tool == self.TOOL_BRUSH:
            self._paint_image_to(img_pt, erase=False)
            return
        if self._tool == self.TOOL_ERASE:
            self._paint_image_to(img_pt, erase=True)
            return
        if self._tool == self.TOOL_BLUR:
            self._blur_to(img_pt)
            return
        # TOOL_MASK — красная маска удаления (вход для нейросети).
        p = _api.QPainter(self._overlay)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
        width = max(1.0, self._brush / self._scale)
        col = _api.QColor(235, 45, 45, 150)
        a = self._last_img_pt if self._last_img_pt is not None else img_pt
        if a == img_pt:
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(img_pt, width / 2.0, width / 2.0)
        else:
            pen = _api.QPen(col)
            pen.setWidthF(width)
            pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(a, img_pt)
        p.end()
        self._last_img_pt = img_pt
        self._has_strokes = True

    def _paint_image_to(self, img_pt, erase=False):
        """«Кисть» (erase=False) кладёт непрозрачные мазки в слой краски
        _paint_layer поверх фото; «Ластик» (erase=True) стирает их из этого слоя
        (CompositionMode_Clear). Слой НЕ вживается в img_bgr сразу — только перед
        удалением объекта/кадрированием/сохранением (bake_paint), поэтому мазки
        можно свободно стирать, как в Photoshop."""
        if self._paint_layer is None:
            return
        p = _api.QPainter(self._paint_layer)
        if erase:
            # Жёсткий край без сглаживания и чуть шире штриха — иначе остаётся
            # полупрозрачная «бахрома» и кажется, что ластик не дотирает.
            p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, False)
            p.setCompositionMode(_api.QPainter.CompositionMode.CompositionMode_Clear)
            width = max(1.0, (self._brush + 2) / self._scale)
            col = _api.QColor(0, 0, 0, 255)
        else:
            p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
            width = max(1.0, self._brush / self._scale)
            c = self._brush_color
            col = _api.QColor(c.red(), c.green(), c.blue())   # непрозрачная краска
        a = self._last_img_pt if self._last_img_pt is not None else img_pt
        if a == img_pt:
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = width / 2.0 + (1.5 if erase else 0.0)
            p.drawEllipse(img_pt, r, r)
        else:
            pen = _api.QPen(col)
            pen.setWidthF(width)
            pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(a, img_pt)
        p.end()
        self._last_img_pt = img_pt
        if not erase:
            self._has_paint = True

    # ── Кисть «Размытие» ─────────────────────────────────────────────────────
    def _begin_blur_stroke(self):
        """Готовит один мазок размытия: замыленная копия всей картинки + пустая
        маска штриха. Сама картинка заменяется НОВЫМ массивом (копией) — так кэш
        PNG-кодирования истории (_bgr_snap_src сравнивает по identity) не
        протухает, пока мы правим пиксели на месте."""
        if self.img_bgr is None:
            return
        sigma = float(self._blur_strength)
        self._blur_orig = self.img_bgr
        self._blur_dst = _api._cv2.GaussianBlur(self.img_bgr, (0, 0), sigma)
        h, w = self.img_bgr.shape[:2]
        self._blur_mask = _api._np.zeros((h, w), _api._np.uint8)
        self.img_bgr = self.img_bgr.copy()

    def _end_blur_stroke(self):
        self._blur_orig = self._blur_dst = self._blur_mask = None

    def _blur_to(self, img_pt):
        if self._blur_mask is None or self.img_bgr is None:
            return
        h, w = self.img_bgr.shape[:2]
        width = max(1, int(round(self._brush / self._scale)))
        a = self._last_img_pt if self._last_img_pt is not None else img_pt
        p0 = (int(round(a.x())), int(round(a.y())))
        p1 = (int(round(img_pt.x())), int(round(img_pt.y())))
        if p0 == p1:
            _api._cv2.circle(self._blur_mask, p1, max(1, width // 2), 255, -1,
                        _api._cv2.LINE_AA)
        else:
            _api._cv2.line(self._blur_mask, p0, p1, 255, width, _api._cv2.LINE_AA)
        # Пересчитываем только прямоугольник вокруг сегмента — иначе на крупных
        # фото каждое движение мыши пережёвывало бы весь кадр.
        pad = width // 2 + 2
        x0 = max(0, min(p0[0], p1[0]) - pad); x1 = min(w, max(p0[0], p1[0]) + pad + 1)
        y0 = max(0, min(p0[1], p1[1]) - pad); y1 = min(h, max(p0[1], p1[1]) + pad + 1)
        if x1 <= x0 or y1 <= y0:
            return
        m = (self._blur_mask[y0:y1, x0:x1].astype(_api._np.float32) / 255.0)[..., None]
        src = self._blur_orig[y0:y1, x0:x1].astype(_api._np.float32)
        dst = self._blur_dst[y0:y1, x0:x1].astype(_api._np.float32)
        self.img_bgr[y0:y1, x0:x1] = (src * (1.0 - m) + dst * m).astype(_api._np.uint8)
        self._blit_base_region(x0, y0, x1, y1)
        self._last_img_pt = img_pt

    def _blit_base_region(self, x0, y0, x1, y1):
        """Обновляет в кэше-пиксмапе только изменённый прямоугольник (полный
        _rebuild_base на 4K-фото — десятки мс на каждое движение мыши)."""
        if self._base_pix is None or self._alpha is not None:
            self._rebuild_base()
            return
        qi = _api.np_bgr_to_qimage(self.img_bgr[y0:y1, x0:x1])
        p = _api.QPainter(self._base_pix)
        p.drawImage(x0, y0, qi)
        p.end()

    # ── События мыши/колеса/клавиатуры ───────────────────────────────────────
    def mousePressEvent(self, ev):
        if self.img_bgr is None:
            return
        if ev.button() == _api.Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = ev.position()
            self._off_start = _api.QPointF(self._off)
            self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != _api.Qt.MouseButton.LeftButton:
            return
        ipt = self._w2i(ev.position())
        # Плавающий объект (фигура/текст/картинка, ещё не вжатый): сначала ручки
        # размера (как free-transform в Photoshop), затем клик ВНУТРИ — перенос,
        # клик ВНЕ — закрепить (вжать). Геометрия от вжигания не меняется.
        if self._pending is not None:
            handle = self._pending_handle_at(ev.position())
            if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
                self._pending_resize = handle
                self._pending_rs_rect0 = self._object_bbox(self._pending)
                self.setCursor(self._crop_cursor(handle))
                return
            if self._object_bbox(self._pending).contains(ipt):
                self._pending_move = True
                self._pending_anchor = ipt
                self.setCursor(_api.Qt.CursorShape.SizeAllCursor)
                if self._pending.get('kind') == 'text':
                    self.textSelected.emit()
                return
            # Клик ВНЕ рамки — закрепляем слой (снимает выделение, как клик мимо
            # рамки free-transform в Photoshop). Дальше клик НЕ продолжаем в кисть
            # и т.п., чтобы не рисовать тем же кликом, которым «применили» слой.
            self._commit_pending()
            return
        if self._tool == self.TOOL_MOVE:
            # Нет плавающего объекта под курсором → «Курсор» работает как рука в
            # Photoshop: тянем — двигаем «камеру». Только при приближении (когда
            # картинка больше холста), иначе на вписанной картинке не сдвигаем.
            cw, ch = self._content_size()
            if cw > self.width() or ch > self.height():
                self._panning = True
                self._pan_start = ev.position()
                self._off_start = _api.QPointF(self._off)
                self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
            return
        # Alt + кисть = пипетка: берём цвет из изображения, не рисуя мазок.
        if (self._tool == self.TOOL_BRUSH
                and (ev.modifiers() & _api.Qt.KeyboardModifier.AltModifier)):
            self._pick_color_at(ipt)
            return
        if self._tool == self.TOOL_CROP:
            if not self.has_crop():
                h, w = self.img_bgr.shape[:2]
                self._crop_a = _api.QPointF(0, 0); self._crop_b = _api.QPointF(w, h)
                if self._crop_aspect:
                    self._reshape_crop_to_aspect()
            handle = self._crop_handle_at(ev.position())
            # Клик мимо рамки — игнорируем (рамка остаётся как есть).
            self._crop_drag = handle
            self._crop_anchor = ipt
            self._crop_start = (_api.QPointF(self._crop_a), _api.QPointF(self._crop_b))
            self.update()
            return
        if self._tool == self.TOOL_TEXT:
            # Текст: клик задаёт верх-левый угол, далее спрашиваем строку.
            self._draw_text_at(ipt)
            return
        if self._tool in self._SHAPE_TOOLS:
            # Фигура: начинаем тянуть от точки клика.
            self._shape_start = ipt
            self._shape_cur = ipt
            self._shape_drawing = True
            self.update()
            return
        # Кисть/ластик/размытие — новый штрих: фиксируем состояние для отмены.
        self._push_history()
        if self._tool == self.TOOL_BLUR:
            # Мазки «Кисти» лежат отдельным слоем — вжигаем их, иначе размытие
            # ушло бы ПОД них (как и при кадрировании/удалении объекта).
            self.bake_paint()
            self._begin_blur_stroke()
        self._painting = True
        self._last_img_pt = None
        self._paint_to(ipt)
        self.update()

    def mouseMoveEvent(self, ev):
        self._mouse_w = ev.position()
        if self._panning and self._pan_start is not None:
            d = ev.position() - self._pan_start
            self._off = self._off_start + d
            self._clamp_off()
            self._update_crop_buttons()
            self.update()
            return
        if self.img_bgr is None:
            self.update()
            return
        # Изменение размера наложенного изображения тяганием ручки.
        if self._pending_resize and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
            keep = bool(ev.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier)
            self._resize_pending(self._w2i(ev.position()), keep_aspect=keep)
            self.update()
            return
        # Перетаскивание плавающего объекта (фигура/текст/картинка).
        if self._pending_move and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
            ipt = self._w2i(ev.position())
            if self._pending_anchor is not None:
                self._translate_pending(ipt - self._pending_anchor)
            self._pending_anchor = ipt
            self.update()
            return
        if self._shape_drawing:
            self._shape_cur = self._w2i(ev.position())
            self.update()
            return
        # Наведение на плавающий объект: курсор-стрелки на ручках размера, «лапа»
        # внутри. Работает в любом инструменте, пока есть незакреплённый объект
        # (а в TOOL_MOVE — ещё и стрелка вне объекта).
        if self._pending is not None and not self._pending_move:
            handle = self._pending_handle_at(ev.position())
            if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
                self.setCursor(self._crop_cursor(handle))
                self.update()
                return
            if handle == 'move':
                self.setCursor(_api.Qt.CursorShape.SizeAllCursor)
                self.update()
                return
            if self._tool == self.TOOL_MOVE:
                self.setCursor(_api.Qt.CursorShape.OpenHandCursor)
                self.update()
                return
        if self._tool == self.TOOL_MOVE:
            # Пустое место под «Курсором» — рука (готов панорамировать, как в Photoshop).
            self.setCursor(_api.Qt.CursorShape.OpenHandCursor)
            self.update()
            return
        # Пока не рисуем — отслеживаем Alt для подсказки «пипетка» у кисти.
        if not self._painting:
            self._set_alt(bool(ev.modifiers() & _api.Qt.KeyboardModifier.AltModifier))
        if self._painting:
            self._paint_to(self._w2i(ev.position()))
            self.update()
            return
        if self._tool == self.TOOL_CROP:
            if self._crop_drag and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
                self._drag_crop(self._w2i(ev.position()))
                self._update_crop_buttons()
            else:
                # Подсказка курсором: над какой ручкой находимся.
                self.setCursor(self._crop_cursor(
                    self._crop_handle_at(ev.position())))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if (ev.button() == _api.Qt.MouseButton.LeftButton and self._pending is not None
                and self._pending.get('kind') == 'text'):
            self.edit_pending_text(self._w2i(ev.position()))
            return
        super().mouseDoubleClickEvent(ev)

    def mouseReleaseEvent(self, ev):
        _default_cursor = (_api.Qt.CursorShape.OpenHandCursor if self._tool == self.TOOL_MOVE
                           else _api.Qt.CursorShape.CrossCursor)
        # Любое панорамирование (средняя кнопка ИЛИ «Курсор»-рука) завершаем здесь.
        if self._panning:
            self._panning = False
            self.setCursor(_default_cursor)
            return
        # Завершили изменение размера наложенного изображения.
        if self._pending_resize and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._pending_resize = None
            self._pending_rs_rect0 = None
            self.setCursor(_default_cursor)
            self.update()
            return
        # Завершили перетаскивание плавающего объекта — он остаётся выделенным.
        if self._pending_move and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._pending_move = False
            self._pending_anchor = None
            self.setCursor(_default_cursor)
            self.update()
            return
        if self._shape_drawing and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._shape_cur = self._w2i(ev.position())
            a, b = self._shape_start, self._shape_cur
            self._shape_drawing = False
            self._shape_start = self._shape_cur = None
            self._make_pending_shape(a, b)
            self.update()
            return
        if self._painting:
            self._painting = False
            self._last_img_pt = None
            was_mask = self._tool == self.TOOL_MASK
            # Ластик стирает мазки кисти (слой краски) — пересчитываем флаг краски.
            if self._tool == self.TOOL_ERASE:
                self._recompute_paint_flag()
            if self._tool == self.TOOL_BLUR:
                self._end_blur_stroke()
                self.imageChanged.emit()
            # Кисть/ластик могли изменить _has_paint — сигналим вкладке пере-включить
            # кнопки (кнопка «Ластик» неактивна, пока нечего стирать, см. _refresh_enabled).
            if self._tool in (self.TOOL_BRUSH, self.TOOL_ERASE):
                self.imageChanged.emit()
            # Завершено выделение для удаления — сигналим вкладке: убрать закрашенное
            # (как Photoshop Spot Healing Brush: пометил — сразу убралось).
            if was_mask and self._has_strokes:
                self.strokeFinished.emit()
        if self._crop_drag:
            self._crop_drag = None

    def leaveEvent(self, ev):
        self._mouse_w = None
        self.update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        if self.img_bgr is None:
            return
        # Зум мышью — забираем фокус холсту, чтобы WASD/стрелки сразу панорамировали.
        self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
        dy = ev.angleDelta().y()
        if dy == 0:
            return
        factor = 1.2 if dy > 0 else 1 / 1.2
        old = self._scale
        new = max(0.02, min(40.0, old * factor))
        if new == old:
            return
        cur = ev.position()
        # Зум вокруг курсора: точка под курсором остаётся на месте.
        self._off = _api.QPointF(cur.x() - (cur.x() - self._off.x()) * (new / old),
                            cur.y() - (cur.y() - self._off.y()) * (new / old))
        self._scale = new
        self._user_zoomed = True
        self._clamp_off()
        self._update_crop_buttons()
        self.update()

    def _pan_by(self, dx, dy):
        """Сдвигает «камеру» (видимую область) на dx,dy экранных px. Двигаем только
        по оси, где картинка больше холста (при приближении), иначе не даём ей
        бесцельно ездить по пустому полю."""
        if self.img_bgr is None:
            return
        cw, ch = self._content_size()
        if dx and cw <= self.width():
            dx = 0
        if dy and ch <= self.height():
            dy = 0
        if not dx and not dy:
            return
        self._off = _api.QPointF(self._off.x() + dx, self._off.y() + dy)
        self._user_zoomed = True
        self._clamp_off()
        self._update_crop_buttons()
        self.update()

    def keyPressEvent(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & _api.Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & _api.Qt.KeyboardModifier.ShiftModifier)
        # WASD/стрелки — панорамирование при приближении (без Ctrl, чтобы не
        # конфликтовать с Ctrl+Z/Y). Шаг крупнее с Shift. WASD читаются по физической
        # клавише → работают на любой раскладке (см. _pan_dir_from_event).
        pan_dir = _api._pan_dir_from_event(ev)
        if not ctrl and pan_dir is not None and self.img_bgr is not None:
            step = 120 if shift else 50
            sx, sy = pan_dir
            self._pan_by(sx * step, sy * step)
            return
        if k == _api.Qt.Key.Key_Alt:
            self._set_alt(True)
        if k == _api.Qt.Key.Key_Escape and self._pending is not None:
            # Esc убирает незакреплённый объект (фигуру/текст) без вжигания.
            self.cancel_pending()
        elif k in (_api.Qt.Key.Key_Return, _api.Qt.Key.Key_Enter) and self._pending is not None:
            # Enter закрепляет плавающий объект.
            self._commit_pending()
        elif k == _api.Qt.Key.Key_Escape and self._tool == self.TOOL_CROP:
            self.cancel_crop()
        elif k in (_api.Qt.Key.Key_Return, _api.Qt.Key.Key_Enter) and self.has_crop():
            self.apply_crop()
        elif k == _api.Qt.Key.Key_Y and ctrl:
            self.redo()
        elif k == _api.Qt.Key.Key_Z and ctrl and shift:
            self.redo()
        elif k == _api.Qt.Key.Key_Z and ctrl:
            self.undo()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == _api.Qt.Key.Key_Alt:
            self._set_alt(False)
        super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        if self.img_bgr is not None and not self._user_zoomed:
            self._fit()
        self._update_crop_buttons()
        super().resizeEvent(ev)

    # ── Отрисовка ────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        self._sync_overlay_buttons()
        self._sync_scrollbars()
        painter = _api.QPainter(self)
        painter.fillRect(self.rect(), _api.QColor("#11111b"))
        if self.img_bgr is None or self._base_pix is None:
            painter.setPen(_api.QColor("#585b70"))
            f = painter.font(); f.setPointSize(11); painter.setFont(f)
            painter.drawText(self.rect(), _api.Qt.AlignmentFlag.AlignCenter,
                             "Откройте изображение для удаления объектов\n"
                             "(кнопка «Открыть» сверху или перетащите файл)")
            return
        painter.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
        ih, iw = self.img_bgr.shape[:2]
        target = self._img_rect_w()
        src = _api.QRectF(0, 0, iw, ih)
        painter.drawPixmap(target, self._base_pix, src)
        # Слой краски «Кисти» поверх фото (ещё не вжатый — чтобы Ластик мог стирать).
        if self._paint_layer is not None:
            painter.drawImage(target, self._paint_layer, src)
        painter.drawImage(target, self._overlay, src)

        # Рамка кадрирования (стиль Paint/Photoshop): затемняем всё ВНЕ рамки,
        # рисуем границу, сетку третей и квадратные ручки на углах/серединах сторон.
        if self._tool == self.TOOL_CROP and self.has_crop():
            r = self._crop_rect_w().intersected(target)
            # 4 затемняющих полосы вокруг рамки (в пределах изображения).
            painter.setPen(_api.Qt.PenStyle.NoPen)
            painter.setBrush(_api.QColor(0, 0, 0, 120))
            painter.drawRect(_api.QRectF(target.left(), target.top(),
                                    target.width(), r.top() - target.top()))
            painter.drawRect(_api.QRectF(target.left(), r.bottom(),
                                    target.width(), target.bottom() - r.bottom()))
            painter.drawRect(_api.QRectF(target.left(), r.top(),
                                    r.left() - target.left(), r.height()))
            painter.drawRect(_api.QRectF(r.right(), r.top(),
                                    target.right() - r.right(), r.height()))
            # Сетка третей.
            painter.setBrush(_api.Qt.BrushStyle.NoBrush)
            painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 80), 1))
            for i in (1, 2):
                gx = r.left() + r.width() * i / 3.0
                gy = r.top() + r.height() * i / 3.0
                painter.drawLine(_api.QPointF(gx, r.top()), _api.QPointF(gx, r.bottom()))
                painter.drawLine(_api.QPointF(r.left(), gy), _api.QPointF(r.right(), gy))
            # Граница рамки.
            painter.setPen(_api.QPen(_api.QColor("#cdd6f4"), 1.5))
            painter.drawRect(r)
            # Квадратные ручки.
            painter.setPen(_api.QPen(_api.QColor("#1e1e2e"), 1))
            painter.setBrush(_api.QColor("#cdd6f4"))
            hs = 4.0
            cx, cy = r.center().x(), r.center().y()
            for p in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
                      _api.QPointF(cx, r.top()), _api.QPointF(cx, r.bottom()),
                      _api.QPointF(r.left(), cy), _api.QPointF(r.right(), cy)):
                painter.drawRect(_api.QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

        # Предпросмотр тянущейся фигуры (в экранных координатах поверх картинки).
        if (self._shape_drawing and self._shape_start is not None
                and self._shape_cur is not None):
            painter.save()
            painter.setClipRect(target)
            painter.translate(self._off)
            painter.scale(self._scale, self._scale)
            self._draw_shape(painter, self._shape_start, self._shape_cur, self._tool)
            painter.restore()

        # Плавающий объект (фигура/текст) + пунктирная рамка выделения вокруг него —
        # видно, что его ещё можно перетащить (как выделенный слой в Photoshop).
        if self._pending is not None:
            painter.save()
            painter.setClipRect(target)
            painter.translate(self._off)
            painter.scale(self._scale, self._scale)
            self._draw_object(painter, self._pending)
            painter.restore()
            bb = self._object_bbox(self._pending)
            sel = _api.QRectF(self._i2w(bb.topLeft()), self._i2w(bb.bottomRight())).normalized()
            painter.setBrush(_api.Qt.BrushStyle.NoBrush)
            painter.setPen(_api.QPen(_api.QColor(0, 0, 0, 160), 2, _api.Qt.PenStyle.DashLine))
            painter.drawRect(sel)
            painter.setPen(_api.QPen(_api.QColor("#89b4fa"), 1, _api.Qt.PenStyle.DashLine))
            painter.drawRect(sel)
            # Квадратные ручки размера (только у картинки — её можно ресайзить).
            if self._pending_resizable():
                painter.setPen(_api.QPen(_api.QColor("#1e1e2e"), 1))
                painter.setBrush(_api.QColor("#89b4fa"))
                hs = 4.0
                cx, cy = sel.center().x(), sel.center().y()
                for p in (sel.topLeft(), sel.topRight(), sel.bottomLeft(),
                          sel.bottomRight(), _api.QPointF(cx, sel.top()),
                          _api.QPointF(cx, sel.bottom()), _api.QPointF(sel.left(), cy),
                          _api.QPointF(sel.right(), cy)):
                    painter.drawRect(_api.QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

        # Кольцо-курсор кисти/ластика (не показываем под Alt-пипеткой).
        if (self._mouse_w is not None and not self._panning and not self._alt
                and self._tool in (self.TOOL_BRUSH, self.TOOL_MASK,
                                   self.TOOL_ERASE, self.TOOL_BLUR)):
            rad = self._brush / 2.0
            painter.setBrush(_api.Qt.BrushStyle.NoBrush)
            painter.setPen(_api.QPen(_api.QColor(0, 0, 0, 160), 2))
            painter.drawEllipse(self._mouse_w, rad, rad)
            painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 220), 1))
            painter.drawEllipse(self._mouse_w, rad, rad)


InpaintCanvas.__module__ = _api.__name__
_api.InpaintCanvas = InpaintCanvas
