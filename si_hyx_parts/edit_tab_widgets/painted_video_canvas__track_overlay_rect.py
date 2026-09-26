# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas: _track_overlay_rect. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def _track_overlay_rect(self, vr):
    """Прямоугольник накладки НА ЭКРАНЕ (и рамка объекта) для текущего
        времени, либо (None, None), если сейчас накладку показывать не нужно."""
    spec = self._trk
    if spec is None or not self._has_frame():
        return None, None
    t = self._trk_t
    if t < spec["start_s"] - 1e-3 or t > spec["end_s"] + 1e-3:
        return None, None
    box = _api.track_box_at(spec.get("boxes"), t, spec["start_s"], spec["fps"])
    if box is None:
        return None, None
    ovl = spec.get("overlay")
    if ovl is None or ovl.isNull():
        return None, None
    ow, oh = float(ovl.width()), float(ovl.height())
    if spec.get("scale_with_box"):
        k = _api.math.sqrt(max(1.0, box[2] * box[3]) / spec["_base_area"])
        k = max(0.25, min(4.0, k))
        ow, oh = ow * k, oh * k
    ox, oy = _api.overlay_top_left(box, ow, oh, spec.get("anchor", "center"),
                              *spec.get("off", (0, 0)))
    # Из пикселей исходника — в пиксели холста (кадр вписан в vr).
    sx = vr.width() / float(max(1, spec["src_w"]))
    sy = vr.height() / float(max(1, spec["src_h"]))
    rect = _api.QRectF(vr.left() + ox * sx, vr.top() + oy * sy, ow * sx, oh * sy)
    brect = _api.QRectF(vr.left() + box[0] * sx, vr.top() + box[1] * sy,
                   box[2] * sx, box[3] * sy)
    return rect, brect

def _paint_track_preview(self, p, vr):
    rect, brect = self._track_overlay_rect(vr)
    if rect is None:
        return
    p.save()
    p.setClipRect(_api.QRectF(vr).intersected(_api.QRectF(self.rect())))
    p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawImage(rect, self._trk["overlay"])
    # Тонкая рамка отслеживаемого объекта — видно, за чем именно едет
    # накладка (в готовое видео она, разумеется, не попадает).
    pen = _api.QPen(_api.QColor(_api.C['accent']), 1, _api.Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(_api.Qt.BrushStyle.NoBrush)
    p.drawRect(brect)
    p.restore()

# ── Наложенные картинки (логотип/водяной знак/рамка) ─────────────────────
#
# Слои живут прямо на холсте: их видно поверх кадра, их же двигают/тянут/
# крутят мышью. Координаты — доли КАДРА (см. edit_tab_overlay.ImageOverlay),
# поэтому предпросмотр на прокси и итоговый файл совпадают попиксельно.

def image_overlays(self):
    return list(self._ovls)

def has_image_overlays(self):
    return bool(self._ovls)

def add_image_overlay(self, item):
    self._ovls.append(item)
    self._ovl_sel = len(self._ovls) - 1
    self.set_overlay_edit(True)
    self.update()
    self.overlaysChanged.emit()

def remove_image_overlay(self, idx):
    if not (0 <= idx < len(self._ovls)):
        return
    del self._ovls[idx]
    self._ovl_sel = min(idx, len(self._ovls) - 1)
    if not self._ovls:
        self.set_overlay_edit(False)
    self.update()
    self.overlaysChanged.emit()

def clear_image_overlays(self):
    if not self._ovls:
        return
    self._ovls = []
    self._ovl_sel = -1
    self.set_overlay_edit(False)
    self.update()
    self.overlaysChanged.emit()

def selected_overlay_index(self):
    return self._ovl_sel

def set_selected_overlay(self, idx):
    idx = int(idx)
    if idx == self._ovl_sel:
        return
    self._ovl_sel = idx if 0 <= idx < len(self._ovls) else -1
    self.update()

def set_overlay_edit(self, on):
    """Режим правки слоёв: рамка с ручками у выбранной картинки. Выключенный
        режим ничего не убирает — картинки остаются на кадре и в экспорте."""
    on = bool(on) and bool(self._ovls)
    if on == self._ovl_edit:
        return
    self._ovl_edit = on
    self._ovl_drag = None
    if on:
        self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        self.setFocus()
    else:
        self.unsetCursor()
    self.update()

def _ovl_rect_screen(self, ovl, vr):
    """Место накладки НА ЭКРАНЕ без учёта поворота (доли кадра → пиксели)."""
    r = ovl.rect
    return _api.QRectF(vr.left() + r.x() * vr.width(),
                  vr.top() + r.y() * vr.height(),
                  r.width() * vr.width(), r.height() * vr.height())

@staticmethod
def _ovl_transform(ovl, rect):
    """Поворот вокруг центра рамки (экранные координаты)."""
    t = _api.QTransform()
    c = rect.center()
    t.translate(c.x(), c.y())
    t.rotate(ovl.angle)
    t.translate(-c.x(), -c.y())
    return t

def _ovl_hit(self, pos, vr):
    """Что под курсором: (индекс слоя, ручка) или (-1, None). Ручки: угловые
        tl/tr/bl/br, боковые l/r/t/b, 'rot' (поворот) и 'move' (тело картинки).
        Ищем сверху вниз — верхний слой перехватывает клик первым."""
    order = list(range(len(self._ovls)))
    # Выбранный слой проверяем первым: его ручки должны ловиться даже когда
    # сверху лежит край соседней картинки.
    if 0 <= self._ovl_sel < len(self._ovls):
        order.remove(self._ovl_sel)
        order.insert(0, self._ovl_sel)
    else:
        order.reverse()
    for i in order:
        ovl = self._ovls[i]
        r = self._ovl_rect_screen(ovl, vr)
        inv, ok = self._ovl_transform(ovl, r).inverted()
        p = inv.map(pos) if ok else pos
        m = 7.0
        if i == self._ovl_sel:
            # Ручка поворота — «антенна» над серединой верхней стороны.
            rp = _api.QPointF(r.center().x(), r.top() - 22.0)
            if (abs(p.x() - rp.x()) <= m + 2) and (abs(p.y() - rp.y()) <= m + 2):
                return i, 'rot'
            nl = abs(p.x() - r.left()) <= m
            nr = abs(p.x() - r.right()) <= m
            nt = abs(p.y() - r.top()) <= m
            nb = abs(p.y() - r.bottom()) <= m
            inx = r.left() - m <= p.x() <= r.right() + m
            iny = r.top() - m <= p.y() <= r.bottom() + m
            if nl and nt: return i, 'tl'
            if nr and nt: return i, 'tr'
            if nl and nb: return i, 'bl'
            if nr and nb: return i, 'br'
            if nl and iny: return i, 'l'
            if nr and iny: return i, 'r'
            if nt and inx: return i, 't'
            if nb and inx: return i, 'b'
        if r.contains(p):
            return i, 'move'
    return -1, None

@staticmethod
def _ovl_cursor(handle):
    return {
        'tl': _api.Qt.CursorShape.SizeFDiagCursor, 'br': _api.Qt.CursorShape.SizeFDiagCursor,
        'tr': _api.Qt.CursorShape.SizeBDiagCursor, 'bl': _api.Qt.CursorShape.SizeBDiagCursor,
        'l': _api.Qt.CursorShape.SizeHorCursor, 'r': _api.Qt.CursorShape.SizeHorCursor,
        't': _api.Qt.CursorShape.SizeVerCursor, 'b': _api.Qt.CursorShape.SizeVerCursor,
        'rot': _api.Qt.CursorShape.CrossCursor,
        'move': _api.Qt.CursorShape.SizeAllCursor,
    }.get(handle, _api.Qt.CursorShape.ArrowCursor)

def _ovl_drag_to(self, pos, vr):
    """Тянем захваченную ручку/тело к точке `pos` (экранные координаты)."""
    d = self._ovl_drag
    if not d:
        return
    ovl = self._ovls[d['i']]
    start = d['rect']              # рамка (доли кадра) на момент захвата
    if vr.width() <= 0 or vr.height() <= 0:
        return
    if d['handle'] == 'rot':
        c = _api.QPointF(vr.left() + (start.x() + start.width() / 2) * vr.width(),
                    vr.top() + (start.y() + start.height() / 2) * vr.height())
        ang = _api.math.degrees(_api.math.atan2(pos.y() - c.y(), pos.x() - c.x())) + 90.0
        if _api.QApplication.keyboardModifiers() & _api.Qt.KeyboardModifier.ShiftModifier:
            ang = round(ang / 15.0) * 15.0      # Shift — шаг в 15°
        ovl.angle = ang
        self.update()
        return
    # Смещение курсора в долях кадра от точки захвата.
    dx = (pos.x() - d['pos'].x()) / vr.width()
    dy = (pos.y() - d['pos'].y()) / vr.height()
    if d['handle'] == 'move':
        ovl.set_rect(_api.QRectF(start.x() + dx, start.y() + dy,
                            start.width(), start.height()))
        self.update()
        return
    # Правка идёт в СИСТЕМЕ САМОЙ КАРТИНКИ: при повороте курсор надо
    # разложить по её осям, иначе рамка «убегает» от мыши.
    if abs(ovl.angle) > 0.01:
        a = _api.math.radians(ovl.angle)
        ca, sa = _api.math.cos(a), _api.math.sin(a)
        px = dx * vr.width(); py = dy * vr.height()
        lx = px * ca + py * sa
        ly = -px * sa + py * ca
        dx, dy = lx / vr.width(), ly / vr.height()
    h = d['handle']
    l, t = start.x(), start.y()
    r, b = start.x() + start.width(), start.y() + start.height()
    if 'l' in h: l += dx
    if 'r' in h: r += dx
    if 't' in h: t += dy
    if 'b' in h: b += dy
    w = max(_api.MIN_SIZE_NORM, r - l)
    hgt = max(_api.MIN_SIZE_NORM, b - t)
    if h in ('tl', 'tr', 'bl', 'br'):
        # Углы держат пропорции картинки (растянуть можно сторонами).
        k = start.height() / max(1e-6, start.width())
        if abs(w - start.width()) >= abs(hgt - start.height()):
            hgt = max(_api.MIN_SIZE_NORM, w * k)
        else:
            w = max(_api.MIN_SIZE_NORM, hgt / max(1e-6, k))
    if 'l' in h:
        l = r - w
    if 't' in h:
        t = b - hgt
    ovl.set_rect(_api.QRectF(l, t, w, hgt))
    self.update()

def _paint_image_overlays(self, p, vr):
    """Рисует накладки поверх кадра (и рамку правки у выбранной)."""
    clip = _api.QRectF(vr).intersected(_api.QRectF(self.rect()))
    for i, ovl in enumerate(self._ovls):
        img = ovl.cropped()
        if img is None or img.isNull():
            continue
        r = self._ovl_rect_screen(ovl, vr)
        p.save()
        p.setClipRect(clip)
        p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setTransform(self._ovl_transform(ovl, r), True)
        p.setOpacity(max(0.05, min(1.0, ovl.opacity)))
        p.drawImage(r, img)
        p.setOpacity(1.0)
        if self._ovl_edit and i == self._ovl_sel:
            p.setBrush(_api.Qt.BrushStyle.NoBrush)
            p.setPen(_api.QPen(_api.QColor(_api.C['accent']), 1.5, _api.Qt.PenStyle.DashLine))
            p.drawRect(r)
            # «Антенна» поворота над верхней стороной.
            top_c = _api.QPointF(r.center().x(), r.top())
            rot_c = _api.QPointF(r.center().x(), r.top() - 22.0)
            p.setPen(_api.QPen(_api.QColor(_api.C['accent']), 1.5))
            p.drawLine(top_c, rot_c)
            p.setBrush(_api.QColor(_api.C['accent']))
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.drawEllipse(rot_c, 5.0, 5.0)
            for hx, hy in ((r.left(), r.top()), (r.center().x(), r.top()),
                           (r.right(), r.top()), (r.left(), r.center().y()),
                           (r.right(), r.center().y()), (r.left(), r.bottom()),
                           (r.center().x(), r.bottom()), (r.right(), r.bottom())):
                p.drawRect(_api.QRectF(hx - 4, hy - 4, 8, 8))
        p.restore()
