# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget: show_tooltip_at_global_pos. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def show_tooltip_at_global_pos(self, gpos, t):
    try:
        if hasattr(gpos, 'toPoint'):
            gp = gpos.toPoint()
        elif hasattr(gpos, 'x'):
            gp = _api.QPoint(int(gpos.x()), int(gpos.y()))
        else:
            gp = gpos
    except Exception:
        gp = None
    txt = _api.s_to_time(t)
    if gp:
        _api.QToolTip.showText(gp, txt, self); self.tooltip_visible = True
    else:
        _api.QToolTip.hideText(); self.tooltip_visible = False

def wheelEvent(self, event):
    modifiers = _api.QApplication.keyboardModifiers()
    if not (modifiers & _api.Qt.KeyboardModifier.ControlModifier):
        event.ignore(); return
    delta = 0
    try:
        delta = event.angleDelta().y()
    except Exception:
        delta = event.delta()
    if delta == 0:
        return
    try:
        cursor_x = event.position().x()
    except Exception:
        cursor_x = event.x()
    w = max(1, self.width())
    visible_before = max(0.001, self.duration / self.zoom)
    t_at_cursor = self.view_offset + (cursor_x / w) * visible_before
    factor = 1.15 if delta > 0 else (1.0 / 1.15)
    # min 0.25 — можно отдалиться так, что клип займёт ~1/4 ширины (как в
    # типичных видеоредакторах), оставив свободное место справа.
    new_zoom = max(0.25, min(self.zoom * factor, 200.0))
    visible_after = max(0.001, self.duration / new_zoom)
    new_view = t_at_cursor - (cursor_x / w) * visible_after
    # Зум у самого края: «5%» считаем ВИЗУАЛЬНЫМИ — 5% от ширины видимого
    # окна, а не от всей длительности клипа. Иначе на длинном клипе порог
    # (5% длительности) огромен в секундах и при зуме где-то у начала окно
    # ни с того ни с сего «прыгало» в 0. Теперь снап срабатывает, только
    # когда край клипа реально близок к краю экрана (≤5% видимой части).
    edge = 0.05 * visible_after
    if t_at_cursor <= edge:
        new_view = 0.0
    elif t_at_cursor >= self.duration - edge:
        new_view = max(0.0, self.duration - visible_after)
    new_view = max(0.0, min(new_view, max(0.0, self.duration - visible_after)))
    self.zoom = new_zoom; self.view_offset = new_view
    self.viewChanged.emit(self.view_offset, visible_after)
    self.update(); event.accept()

def set_view_offset(self, offset):
    visible = max(0.001, self.duration / self.zoom)
    offset = max(0.0, min(offset, max(0.0, self.duration - visible)))
    self.view_offset = offset
    self._cache = None
    self.viewChanged.emit(self.view_offset, visible)
    self.update()

def set_zoom(self, zoom):
    self.zoom = max(0.25, min(zoom, 200.0))
    visible = max(0.001, self.duration / self.zoom)
    self.view_offset = max(0.0, min(self.view_offset, max(0.0, self.duration - visible)))
    self._cache = None
    self.viewChanged.emit(self.view_offset, visible)
    self.update()
