# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: __init__. Public namespace: photo_tab."""
import photo_tab as _api


def __init__(self, parent=None):
    super(_api.InpaintCanvas, self).__init__(parent)
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

