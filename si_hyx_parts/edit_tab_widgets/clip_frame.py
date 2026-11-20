# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ClipFrameEditor — рамка размера и места клипа проекта прямо в окне
просмотра. Public namespace: edit_tab_widgets.

Не виджет: им пользуются оба экрана просмотра — холст плеера
(_PaintedVideoCanvas и его GPU-наследник) и FxPreviewView. Рамка хранится
в долях кадра проекта; `area` — где этот кадр лежит на экране. Уголки
меняют размер с сохранением пропорций (противоположный угол стоит на месте,
Alt — от центра), тело двигает клип, Shift при переносе — только по одной
оси."""
import edit_tab_widgets as _api

_HANDLE = 7.0          # полуразмер зоны захвата уголка, px
_MIN_PX = 12.0         # меньше рамку на экране не сжать


class ClipFrameEditor:
    """Рамка выбранного клипа: состояние, попадание мышью, перетаскивание и
    отрисовка."""

    def __init__(self):
        self.rect = None        # QRectF в долях кадра проекта или None
        self._drag = None       # {'handle', 'pos', 'rect'} на время перетаскивания

    # ── Состояние ────────────────────────────────────────────────────────────
    def set_rect(self, rect):
        """Новая рамка (None — спрятать). True — что-то поменялось."""
        if self._drag is not None:
            return False        # во время перетаскивания рамку ведёт мышь
        rect = _api.QRectF(rect) if rect is not None else None
        if rect == self.rect:
            return False
        self.rect = rect
        return True

    def dragging(self):
        return self._drag is not None

    def start_rect(self):
        """Рамка на начало перетаскивания (None — не тянут)."""
        return _api.QRectF(self._drag['rect']) if self._drag is not None else None

    @staticmethod
    def screen_rect(rect, area):
        return _api.QRectF(area.left() + rect.x() * area.width(),
                           area.top() + rect.y() * area.height(),
                           rect.width() * area.width(), rect.height() * area.height())

    # ── Мышь ─────────────────────────────────────────────────────────────────
    def hit(self, pos, area):
        """Ручка под курсором: tl/tr/bl/br, 'move' (тело) или None."""
        if self.rect is None or area.width() <= 0 or area.height() <= 0:
            return None
        r = self.screen_rect(self.rect, area)
        m = _HANDLE
        for name, pt in (('tl', r.topLeft()), ('tr', r.topRight()),
                         ('bl', r.bottomLeft()), ('br', r.bottomRight())):
            if abs(pos.x() - pt.x()) <= m and abs(pos.y() - pt.y()) <= m:
                return name
        return 'move' if r.contains(pos) else None

    @staticmethod
    def cursor(handle):
        return {
            'tl': _api.Qt.CursorShape.SizeFDiagCursor, 'br': _api.Qt.CursorShape.SizeFDiagCursor,
            'tr': _api.Qt.CursorShape.SizeBDiagCursor, 'bl': _api.Qt.CursorShape.SizeBDiagCursor,
            'move': _api.Qt.CursorShape.SizeAllCursor,
        }.get(handle, _api.Qt.CursorShape.ArrowCursor)

    def press(self, pos, area):
        """Захват ручки или тела; True — рамка взяла нажатие."""
        handle = self.hit(pos, area)
        if handle is None:
            return False
        self._drag = {'handle': handle, 'pos': _api.QPointF(pos),
                      'rect': _api.QRectF(self.rect)}
        return True

    def move(self, pos, area, modifiers=None):
        """Тянем захваченную ручку к pos. True — рамка изменилась."""
        d = self._drag
        if d is None or area.width() <= 0 or area.height() <= 0:
            return False
        mods = modifiers if modifiers is not None else _api.QApplication.keyboardModifiers()
        start = d['rect']
        dx = (pos.x() - d['pos'].x()) / area.width()
        dy = (pos.y() - d['pos'].y()) / area.height()
        if d['handle'] == 'move':
            if mods & _api.Qt.KeyboardModifier.ShiftModifier:
                if abs(dx * area.width()) >= abs(dy * area.height()):
                    dy = 0.0
                else:
                    dx = 0.0
            self.rect = _api.QRectF(start.x() + dx, start.y() + dy,
                                    start.width(), start.height())
            return True
        # Угол: размер по проекции курсора на диагональ, пропорции — как были.
        sr = self.screen_rect(start, area)
        h = d['handle']
        corner = {'tl': sr.topLeft(), 'tr': sr.topRight(),
                  'bl': sr.bottomLeft(), 'br': sr.bottomRight()}[h]
        center_mode = bool(mods & _api.Qt.KeyboardModifier.AltModifier)
        anchor = sr.center() if center_mode else {
            'tl': sr.bottomRight(), 'tr': sr.bottomLeft(),
            'bl': sr.topRight(), 'br': sr.topLeft()}[h]
        vx, vy = corner.x() - anchor.x(), corner.y() - anchor.y()
        length2 = vx * vx + vy * vy
        if length2 <= 1e-6:
            return False
        k = ((pos.x() - anchor.x()) * vx + (pos.y() - anchor.y()) * vy) / length2
        k = max(_MIN_PX / max(1.0, min(sr.width(), sr.height())), k)
        w, hh = sr.width() * k, sr.height() * k
        if center_mode:
            left, top = anchor.x() - w / 2.0, anchor.y() - hh / 2.0
        else:
            left = anchor.x() - w if 'l' in h else anchor.x()
            top = anchor.y() - hh if 't' in h else anchor.y()
        self.rect = _api.QRectF((left - area.left()) / area.width(),
                                (top - area.top()) / area.height(),
                                w / area.width(), hh / area.height())
        return True

    def release(self):
        """Конец перетаскивания: (рамка до, рамка после) или None."""
        d, self._drag = self._drag, None
        if d is None or self.rect is None or self.rect == d['rect']:
            return None
        return d['rect'], _api.QRectF(self.rect)

    def cancel(self):
        d, self._drag = self._drag, None
        if d is not None:
            self.rect = d['rect']

    # ── Отрисовка ────────────────────────────────────────────────────────────
    def paint(self, p, area):
        if self.rect is None or area.width() <= 0 or area.height() <= 0:
            return
        r = self.screen_rect(self.rect, area)
        accent = _api.QColor(_api.C['accent'])
        p.save()
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
        p.setBrush(_api.Qt.BrushStyle.NoBrush)
        # Тёмная подложка под пунктиром — рамку видно на любом кадре.
        p.setPen(_api.QPen(_api.QColor(0, 0, 0, 140), 3.0))
        p.drawRect(r)
        p.setPen(_api.QPen(accent, 1.5, _api.Qt.PenStyle.DashLine))
        p.drawRect(r)
        p.setPen(_api.QPen(_api.QColor(0, 0, 0, 160), 1.0))
        p.setBrush(accent)
        for pt in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            p.drawRect(_api.QRectF(pt.x() - 4.5, pt.y() - 4.5, 9.0, 9.0))
        p.restore()


ClipFrameEditor.__module__ = _api.__name__
