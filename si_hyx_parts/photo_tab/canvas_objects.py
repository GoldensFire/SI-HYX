# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Холст фото: инструменты, кисть, фигуры, текст и отложенные объекты."""
import photo_tab as _api


class InpaintCanvasObjectsMixin:
    """Холст фото: инструменты, кисть, фигуры, текст и отложенные объекты."""

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

    def _resize_pending(self, ipt, keep_aspect=False):
        """Меняет размер наложенного изображения тяганием ручки self._pending_resize.
        ipt — позиция мыши в коорд. изображения. keep_aspect (Shift) — сохранять
        пропорции (для угловых ручек)."""
        if (self._pending is None or self._pending_resize is None
                or self._pending_rs_rect0 is None):
            return
        d = self._pending_resize
        r0 = self._pending_rs_rect0
        l, t, r, b = r0.left(), r0.top(), r0.right(), r0.bottom()
        minsz = 12.0
        x, y = ipt.x(), ipt.y()
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, b - minsz)
        if 'b' in d: b = max(y, t + minsz)
        new_w = r - l; new_h = b - t
        # Пропорции (Shift) для угловых ручек: подгоняем по доминирующей оси,
        # удерживая противоположный угол на месте.
        if keep_aspect and d in ('tl', 'tr', 'bl', 'br') and r0.width() > 0 and r0.height() > 0:
            ar = r0.width() / r0.height()
            if new_w / max(1e-6, new_h) > ar:
                new_w = new_h * ar
            else:
                new_h = new_w / ar
            if 'l' in d: l = r - new_w
            else: r = l + new_w
            if 't' in d: t = b - new_h
            else: b = t + new_h
        self._pending['pos'] = _api.QPointF(l, t)
        self._pending['w'] = max(minsz, new_w)
        self._pending['h'] = max(minsz, new_h)

    def _bake_object(self, obj):
        """Вжигает объект в изображение (с записью в историю отмены)."""
        if self.img_bgr is None:
            return
        self._push_history()
        img = _api.np_bgr_to_qimage(self.img_bgr).convertToFormat(
            _api.QtGuiImage.Format.Format_RGB888)
        p = _api.QPainter(img)
        self._draw_object(p, obj)
        p.end()
        self.img_bgr = _api.qimage_to_np_bgr(img)
        self._rebuild_base()

    def _commit_pending(self):
        """Закрепляет (вжигает) плавающий объект в картинку, если он есть."""
        if self._pending is None:
            return
        obj = self._pending
        self._pending = None
        self._pending_move = False
        self._pending_resize = None
        self._pending_rs_rect0 = None
        # Вырожденную линию/стрелку (клик без движения) не вжигаем.
        if obj['kind'] == 'shape' and obj['tool'] in (self.TOOL_LINE, self.TOOL_ARROW):
            a, b = obj['a'], obj['b']
            if (abs(a.x() - b.x()) + abs(a.y() - b.y())) < 1.5:
                self.update()
                return
        self._bake_object(obj)
        if obj['kind'] == 'text':
            msg = "Текст вжат."
        elif obj['kind'] == 'image':
            msg = "Изображение вжато."
        else:
            msg = "Фигура вжата."
        self.statusChanged.emit(msg)
        self.update()

    def commit_pending(self):
        """Публичный вызов: вкладка вжигает плавающий объект перед сохранением/
        запуском нейросети, чтобы он попал в результат."""
        self._commit_pending()

    def cancel_pending(self):
        """Убирает плавающий объект без вжигания (Esc)."""
        if self._pending is None:
            return
        self._pending = None
        self._pending_move = False
        self._pending_resize = None
        self._pending_rs_rect0 = None
        self.update()
        self.statusChanged.emit("Объект отменён.")

    def _set_alt(self, on):
        """Включает/выключает режим «временной пипетки» (Alt при активной кисти):
        курсор и подсказка меняются, кольцо-курсор кисти не рисуется."""
        on = bool(on) and self._tool == self.TOOL_BRUSH and self.img_bgr is not None
        if on != self._alt:
            self._alt = on
            self.setCursor(_api.eyedropper_cursor() if on
                           else _api.Qt.CursorShape.CrossCursor)
            self.update()

    def _pick_color_at(self, ipt):
        """Берёт цвет пикселя изображения под точкой ipt (коорд. изображения) —
        Alt-пипетка как в Photoshop: цвет кисти становится взятым."""
        if self.img_bgr is None:
            return
        h, w = self.img_bgr.shape[:2]
        x = int(min(max(ipt.x(), 0), w - 1))
        y = int(min(max(ipt.y(), 0), h - 1))
        px = self.img_bgr[y, x]
        col = _api.QColor(int(px[2]), int(px[1]), int(px[0]))   # BGR → RGB
        self.set_brush_color(col)
        self.colorPicked.emit(col)
        self.statusChanged.emit(f"Цвет взят пипеткой: {col.name().upper()}")

    def clear_mask(self):
        self._commit_pending()
        if self._overlay is None:
            return
        self._push_history()
        self._overlay.fill(0)
        self._has_strokes = False
        self.update()
        self.statusChanged.emit("Маска очищена.")

    def clear_canvas(self):
        """Полностью очищает холст. Состояние «до» кладём в историю, чтобы Ctrl+Z
        вернул очищенную картинку (раньше история стиралась — вернуть было нельзя)."""
        self._commit_pending()
        had_image = self.img_bgr is not None
        if had_image:
            self._push_history()        # снимок «до очистки» для Ctrl+Z
        self.img_bgr = None
        self._overlay = None
        self._paint_layer = None
        self._alpha = None
        self._has_paint = False
        self._base_pix = None
        self._has_strokes = False
        self._pending = None
        self._pending_move = False
        self._crop_a = self._crop_b = None
        self._crop_drag = None
        self._user_zoomed = False
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit("Холст очищен." +
                                (" Ctrl+Z — вернуть." if had_image else ""))

    def composited_bgr(self):
        """То, что видит пользователь: фото с вжатыми мазками «Кисти» (слой краски).
        Маску удаления (красную) НЕ вжигаем — это служебное выделение. Без краски
        возвращает само изображение. Не мутирует состояние (для сохранения)."""
        if self.img_bgr is None:
            return None
        if not self._has_paint or self._paint_layer is None:
            return self.img_bgr
        img = _api.np_bgr_to_qimage(self.img_bgr).convertToFormat(
            _api.QtGuiImage.Format.Format_RGB888)
        p = _api.QPainter(img)
        p.drawImage(0, 0, self._paint_layer)
        p.end()
        return _api.qimage_to_np_bgr(img)

    def bake_paint(self):
        """Вжигает слой краски в img_bgr и очищает слой. Зовём перед удалением
        объекта/кадрированием, чтобы мазки попали в результат. Историю НЕ трогаем —
        её снимает вызывающий код (apply_crop/_run_inpaint)."""
        if self.img_bgr is None or self._paint_layer is None or not self._has_paint:
            return
        # Если фон удалён — закрашенные кистью пиксели становятся непрозрачными
        # (рисуем «поверх пустоты»), иначе мазок не был бы виден.
        if self._alpha is not None:
            pa = self._layer_alpha(self._paint_layer)
            self._alpha = _api._np.maximum(self._alpha,
                                      (pa > 10).astype(_api._np.uint8) * 255)
        self.img_bgr = self.composited_bgr()
        self._paint_layer.fill(0)
        self._has_paint = False
        self._rebuild_base()

    def fit(self):
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()
