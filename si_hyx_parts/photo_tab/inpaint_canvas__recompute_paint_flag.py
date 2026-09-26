# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: _recompute_paint_flag. Public namespace: photo_tab."""
import photo_tab as _api


def _recompute_paint_flag(self):
    try:
        self._has_paint = (self._paint_layer is not None
                           and self._layer_alpha(self._paint_layer).max() > 10)
    except Exception:
        self._has_paint = False

# ── Инструменты / параметры ─────────────────────────────────────────────
def set_tool(self, tool):
    # Смена инструмента закрепляет ещё не вжатый плавающий объект (как в
    # Photoshop: переключился на другой инструмент — текущий слой «лёг»).
    # Исключение: TOOL_MOVE специально нужен, чтобы двигать этот слой, —
    # коммитить при переключении на него нельзя.
    if tool != self.TOOL_MOVE:
        self._commit_pending()
    self._tool = tool
    self._crop_drag = None
    # При входе в режим кадрирования сразу показываем рамку на ВЕСЬ кадр —
    # как в Paint/Photoshop: тяните за стороны/углы, чтобы обрезать.
    if tool == self.TOOL_CROP and self.img_bgr is not None:
        h, w = self.img_bgr.shape[:2]
        self._crop_a = _api.QPointF(0, 0)
        self._crop_b = _api.QPointF(w, h)
        if self._crop_aspect:           # учитываем ранее выбранную пропорцию
            self._reshape_crop_to_aspect()
    else:
        self._crop_a = self._crop_b = None
    # Смена инструмента прерывает незавершённую фигуру.
    self._shape_drawing = False
    self._shape_start = self._shape_cur = None
    self.setCursor(_api.Qt.CursorShape.ArrowCursor if tool == self.TOOL_MOVE
                   else _api.Qt.CursorShape.CrossCursor)
    self._update_crop_buttons()
    self.update()

def set_brush(self, diameter):
    self._brush = max(2, int(diameter))
    self.update()

def set_blur_strength(self, v):
    """Степень размытия кисти «Размытие» (сигма гаусса в пикселях изображения)."""
    self._blur_strength = max(1, int(v))

def set_brush_color(self, color):
    if color is not None and color.isValid():
        self._brush_color = _api.QColor(color.red(), color.green(), color.blue())
        self.update()

def brush_color(self):
    return _api.QColor(self._brush_color)

def set_shape_fill(self, on):
    self._shape_fill = bool(on)

def set_text_font(self, font):
    if font is not None:
        self._text_font = _api.QFont(font)
        # Размер задаём в пикселях изображения (см. _draw_text_at); если у
        # шрифта только pointSize — переносим в pixelSize по текущему DPI.
        if self._text_font.pixelSize() <= 0:
            ps = self._text_font.pointSizeF()
            self._text_font.setPixelSize(max(6, int(round(ps * 1.6))))

def set_text_color(self, color):
    if color is not None and color.isValid():
        self._text_color = _api.QColor(color.red(), color.green(), color.blue())

def set_text_stroke(self, width, color=None):
    self._text_stroke_width = max(0.0, float(width))
    if color is not None and color.isValid():
        self._text_stroke_color = _api.QColor(color.red(), color.green(), color.blue())

# ── Фигуры и текст (рисуются прямо в изображение) ────────────────────────
def _shape_pen(self):
    c = self._brush_color
    pen = _api.QPen(_api.QColor(c.red(), c.green(), c.blue()))
    pen.setWidthF(max(1.0, float(self._brush)))   # толщина = размер кисти (px изобр.)
    pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
    return pen

def _draw_shape(self, painter, a, b, tool):
    """Рисует фигуру tool из точки a в точку b (коорд. изображения) на
        переданном QPainter. Цвет/толщина — из кисти; заливка — _shape_fill."""
    painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
    pen = self._shape_pen()
    painter.setPen(pen)
    c = self._brush_color
    if self._shape_fill and tool in (self.TOOL_RECT, self.TOOL_ELLIPSE):
        painter.setBrush(_api.QColor(c.red(), c.green(), c.blue()))
    else:
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
    rect = _api.QRectF(a, b).normalized()
    if tool == self.TOOL_RECT:
        painter.drawRect(rect)
    elif tool == self.TOOL_ELLIPSE:
        painter.drawEllipse(rect)
    elif tool == self.TOOL_LINE:
        painter.drawLine(a, b)
    elif tool == self.TOOL_ARROW:
        painter.drawLine(a, b)
        self._draw_arrow_head(painter, a, b, pen.widthF())

def _draw_arrow_head(self, painter, a, b, width):
    import math
    dx = b.x() - a.x(); dy = b.y() - a.y()
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return
    ux, uy = dx / length, dy / length
    size = max(8.0, width * 3.2)        # длина «крыльев» наконечника
    ang = math.radians(26)
    ca, sa = math.cos(ang), math.sin(ang)
    # Два крыла, повёрнутые на ±ang от обратного направления стрелки.
    for s in (1, -1):
        rx = -ux * ca + s * (-uy) * sa
        ry = -uy * ca + s * (ux) * sa
        tip = _api.QPointF(b.x() + rx * size, b.y() + ry * size)
        painter.drawLine(b, tip)

def _make_pending_shape(self, a, b):
    """Делает из только что протянутой фигуры ПЛАВАЮЩИЙ объект (его можно
        перетащить мышью, пока не вжали — клик вне/смена инструмента/Enter)."""
    if self.img_bgr is None or a is None or b is None:
        return
    # Клик без движения фигуры не оставляет (как и раньше у _commit_shape).
    if (abs(a.x() - b.x()) + abs(a.y() - b.y())) < 1.5:
        return
    c = self._brush_color
    self._pending = {'kind': 'shape', 'tool': self._tool,
                     'a': _api.QPointF(a), 'b': _api.QPointF(b),
                     'color': _api.QColor(c.red(), c.green(), c.blue()),
                     'thickness': float(self._brush), 'fill': self._shape_fill}
    self._pending_move = False
    self.statusChanged.emit("Фигура добавлена — перетащите, чтобы сдвинуть.")

def _draw_text_at(self, ipt):
    """Спрашивает строку и кладёт её как ПЛАВАЮЩИЙ объект (можно перетащить),
        начиная от точки ipt (верх-левый угол текста, коорд. изображения). Текст
        вжигается позже — при клике вне него / смене инструмента / Enter / сейве."""
    if self.img_bgr is None:
        return
    text, ok = _api.QInputDialog.getMultiLineText(
        self, "Текст", "Введите текст (системный шрифт выбирается в панели):", "")
    if not ok or not text.strip():
        return
    c = self._text_color
    self._pending = {'kind': 'text', 'pos': _api.QPointF(ipt), 'text': text,
                     'font': _api.QFont(self._text_font),
                     'color': _api.QColor(c.red(), c.green(), c.blue()),
                     'stroke_width': float(self._text_stroke_width),
                     'stroke_color': _api.QColor(self._text_stroke_color)}
    self._pending_move = False
    self.update()
    self.textSelected.emit()
    self.statusChanged.emit("Текст добавлен — перетащите, чтобы сдвинуть, "
                            "или настройте цвет/шрифт/обводку в панели слева.")

def edit_pending_text(self, ipt):
    """Двойной клик по плавающему тексту — меняем саму строку (остальные
        параметры: шрифт/цвет/обводка — остаются, редактируются в панели)."""
    if self._pending is None or self._pending.get('kind') != 'text':
        return
    if not self._object_bbox(self._pending).contains(ipt):
        return
    text, ok = _api.QInputDialog.getMultiLineText(
        self, "Текст", "Измените текст:", self._pending['text'])
    if ok and text.strip():
        self._pending['text'] = text
        self.update()

# ── Плавающие объекты (фигура/текст): перетаскивание и вжигание ──────────
def _draw_object(self, painter, obj):
    """Рисует плавающий объект obj (фигура/текст/картинка) на painter, коорд. изобр.,
        своими сохранёнными параметрами."""
    if obj['kind'] == 'image':
        pix = obj['pix']
        w = float(obj.get('w', pix.width()))
        h = float(obj.get('h', pix.height()))
        painter.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(
            _api.QRectF(obj['pos'].x(), obj['pos'].y(), w, h), pix,
            _api.QRectF(0, 0, pix.width(), pix.height()))
        return
    painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
    if obj['kind'] == 'text':
        fm = _api.QFontMetrics(obj['font'])
        x = obj['pos'].x()
        y = obj['pos'].y() + fm.ascent()
        stroke_w = float(obj.get('stroke_width', 0) or 0)
        if stroke_w > 0:
            # Обводка (как в Photoshop): путь текста, обвод + заливка —
            # даёт чёткий контур в любой толщине (в отличие от много-теневого трюка).
            path = _api.QPainterPath()
            for i, line in enumerate(obj['text'].split("\n")):
                path.addText(_api.QPointF(x, y + i * fm.lineSpacing()), obj['font'], line)
            pen = _api.QPen(obj.get('stroke_color', _api.QColor(0, 0, 0)))
            pen.setWidthF(stroke_w)
            pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(obj['color'])
            painter.drawPath(path)
        else:
            painter.setRenderHint(_api.QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(obj['font'])
            painter.setPen(obj['color'])
            for i, line in enumerate(obj['text'].split("\n")):
                painter.drawText(_api.QPointF(x, y + i * fm.lineSpacing()), line)
        return
    c = obj['color']
    pen = _api.QPen(c)
    pen.setWidthF(max(1.0, float(obj['thickness'])))
    pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    tool = obj['tool']
    if obj.get('fill') and tool in (self.TOOL_RECT, self.TOOL_ELLIPSE):
        painter.setBrush(c)
    else:
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
    a, b = obj['a'], obj['b']
    rect = _api.QRectF(a, b).normalized()
    if tool == self.TOOL_RECT:
        painter.drawRect(rect)
    elif tool == self.TOOL_ELLIPSE:
        painter.drawEllipse(rect)
    elif tool == self.TOOL_LINE:
        painter.drawLine(a, b)
    elif tool == self.TOOL_ARROW:
        painter.drawLine(a, b)
        self._draw_arrow_head(painter, a, b, pen.widthF())

def _object_bbox(self, obj):
    """Габаритный прямоугольник объекта в коорд. изображения (для хит-теста и
        рамки выделения)."""
    if obj['kind'] == 'image':
        p = obj['pos']
        w = float(obj.get('w', obj['pix'].width()))
        h = float(obj.get('h', obj['pix'].height()))
        return _api.QRectF(p.x(), p.y(), w, h)
    if obj['kind'] == 'text':
        fm = _api.QFontMetrics(obj['font'])
        lines = obj['text'].split("\n")
        w = max((fm.horizontalAdvance(l) for l in lines), default=1)
        h = fm.lineSpacing() * max(1, len(lines))
        r = _api.QRectF(obj['pos'].x(), obj['pos'].y(), max(1, w), max(1, h))
        sw = float(obj.get('stroke_width', 0) or 0) / 2.0
        return r.adjusted(-sw, -sw, sw, sw) if sw else r
    r = _api.QRectF(obj['a'], obj['b']).normalized()
    t = float(obj.get('thickness', 1)) / 2.0 + 4.0   # запас под толщину/наконечник
    return r.adjusted(-t, -t, t, t)

def _translate_pending(self, d):
    """Сдвигает плавающий объект на вектор d (коорд. изображения)."""
    if self._pending is None:
        return
    if self._pending['kind'] in ('text', 'image'):
        self._pending['pos'] = self._pending['pos'] + d
    else:
        self._pending['a'] = self._pending['a'] + d
        self._pending['b'] = self._pending['b'] + d

def _pending_resizable(self) -> bool:
    """Можно ли менять размер плавающего объекта тяганием ручек (только картинка)."""
    return self._pending is not None and self._pending.get('kind') == 'image'

def _pending_handle_at(self, wpt):
    """Какую ручку рамки выделения наложенного изображения задевает курсор
        (коорд. виджета). Возвращает 'tl','tr','bl','br','t','b','l','r','move' или
        None (мимо). Ручки рисуются/ловятся только для картинки."""
    if not self._pending_resizable():
        return None
    bb = self._object_bbox(self._pending)
    tl = self._i2w(bb.topLeft()); br = self._i2w(bb.bottomRight())
    r = _api.QRectF(tl, br).normalized()
    tol = 9.0
    mx, my = wpt.x(), wpt.y()
    if not (r.left() - tol <= mx <= r.right() + tol
            and r.top() - tol <= my <= r.bottom() + tol):
        return None
    near_l = abs(mx - r.left()) <= tol
    near_r = abs(mx - r.right()) <= tol
    near_t = abs(my - r.top()) <= tol
    near_b = abs(my - r.bottom()) <= tol
    if near_t and near_l: return 'tl'
    if near_t and near_r: return 'tr'
    if near_b and near_l: return 'bl'
    if near_b and near_r: return 'br'
    if near_t: return 't'
    if near_b: return 'b'
    if near_l: return 'l'
    if near_r: return 'r'
    if r.left() < mx < r.right() and r.top() < my < r.bottom():
        return 'move'
    return None
