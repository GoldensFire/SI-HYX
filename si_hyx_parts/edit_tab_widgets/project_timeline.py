# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProjectTimeline — таймлайн проекта «Монтажа» (дорожки и клипы, как в
Filmora). Public namespace: edit_tab_widgets."""
import zlib

import edit_tab_widgets as _api
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPolygonF
from PyQt6.QtWidgets import QMenu

# Шаги делений линейки: подбирается первый, при котором подписи не теснее
# _RULER_MIN_PX.
_RULER_STEPS = (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)
_RULER_MIN_PX = 70


# Цвета файлов — приглушённые тона палитры приложения (Catppuccin): синий,
# лиловый, персиковый, бирюзовый, розовый, жёлтый, сапфировый, лавандовый.
_CLIP_HUES = ("#4f6fa8", "#7d5fa8", "#a8714f", "#3f8f86", "#a8587a", "#9a8640",
              "#3f7fa0", "#6b70b0")


def _clip_color(src, video):
    """Цвет клипа: у каждого файла свой, куски одного файла — одного цвета;
    звуковые клипы — темнее."""
    idx = zlib.crc32(str(src).encode("utf-8", "replace")) % len(_CLIP_HUES)
    col = _api.QColor(_CLIP_HUES[idx])
    return col if video else col.darker(125)


def _fmt_ruler(t, step=1.0):
    if step < 1.0:
        m, s = divmod(max(0.0, t), 60.0)
        return f"{int(m)}:{s:04.1f}"
    t = int(round(t))
    h, rest = divmod(t, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_len(t):
    t = max(0.0, float(t))
    m, s = divmod(t, 60.0)
    return f"{int(m)}:{s:04.1f}" if m >= 1 else f"{s:.1f} с"


class ProjectTimeline(_api.QWidget):
    """Дорожки проекта сверху вниз: видео (верхние перекрывают нижние),
    основная «Видео 1» (магнитная), затем звук.

    Мышь: клик по линейке или пустому месту — плейхед (и протяжка); клик по
    клипу — выделение; перетаскивание — перенос (на основной дорожке —
    смена порядка, можно и на другую дорожку того же рода); край клипа —
    подрезка; двойной клик — открыть кусок в источнике; ПКМ — меню. Колесо —
    прокрутка, Ctrl+колесо — масштаб, клик по заголовку дорожки — вкл/выкл.

    Правки модели делает сам (перенос, подрезка, вкл/выкл дорожки), объявляя
    editStarted ДО первой правки (вкладка снимает снимок для отмены) и edited
    после. Остальные команды уходят во вкладку через actionRequested."""

    seekRequested = _api.pyqtSignal(float)
    clipActivated = _api.pyqtSignal(str)
    selectionChanged = _api.pyqtSignal(str)
    editStarted = _api.pyqtSignal()
    edited = _api.pyqtSignal()
    actionRequested = _api.pyqtSignal(str, str)
    viewChanged = _api.pyqtSignal()

    HEADER_W = 64
    RULER_H = 20
    ROW_MAIN_H = 42
    ROW_VIDEO_H = 30
    ROW_AUDIO_H = 26
    EDGE_PX = 6
    SNAP_PX = 8
    DRAG_PX = 4

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.pps = 40.0              # пикселей на секунду
        self.offset = 0.0            # время у левого края дорожек
        self.playhead = 0.0
        self.selected = ""
        # thumb_provider(clip) -> QPixmap|None: миниатюра первого кадра клипа
        # (вкладка достаёт её фоном и зовёт update(), когда она готова).
        self.thumb_provider = None
        self._drag = None
        self._hover = None
        self.setMouseTracking(True)
        self.setFocusPolicy(_api.Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(self.content_height())
        self.setMaximumHeight(self.content_height())

    # ── Геометрия ────────────────────────────────────────────────────────────
    def set_project(self, project):
        self.project = project
        if self.project.clip(self.selected) is None:
            self.selected = ""
        self.refresh()

    def refresh(self):
        """Модель изменилась: высота (дорожки могли добавиться) и перерисовка."""
        h = self.content_height()
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self.viewChanged.emit()
        self.update()

    def _row_h(self, ti):
        if self.project.tracks[ti].kind == 'audio':
            return self.ROW_AUDIO_H
        return self.ROW_MAIN_H if ti == self.project.main_track else self.ROW_VIDEO_H

    def rows(self):
        """[(индекс дорожки, y, высота)] сверху вниз."""
        out, y = [], self.RULER_H
        for ti in self.project.display_order():
            h = self._row_h(ti)
            out.append((ti, y, h))
            y += h
        return out

    def content_height(self):
        return self.RULER_H + sum(self._row_h(ti) for ti in self.project.display_order()) + 2

    def lane_width(self):
        return max(1, self.width() - self.HEADER_W)

    def x_of(self, t):
        return self.HEADER_W + (t - self.offset) * self.pps

    def t_of(self, x):
        return self.offset + (x - self.HEADER_W) / self.pps

    def row_of(self, y):
        for ti, ry, rh in self.rows():
            if ry <= y < ry + rh:
                return ti, ry, rh
        return None

    def clip_rect(self, c, start=None, track=None):
        row = next((r for r in self.rows() if r[0] == (c.track if track is None else track)), None)
        if row is None:
            return QRectF()
        _ti, y, h = row
        x0 = self.x_of(c.start if start is None else start)
        return QRectF(x0, y + 2, max(2.0, c.length * self.pps), h - 4)

    def hit(self, pos):
        """(клип, край) под точкой: край — 'left'/'right' у границы, иначе None."""
        if pos.x() < self.HEADER_W or pos.y() < self.RULER_H:
            return None, None
        row = self.row_of(pos.y())
        if row is None:
            return None, None
        for c in self.project.clips_on(row[0]):
            r = self.clip_rect(c)
            if r.left() - 2 <= pos.x() <= r.right() + 2:
                edge = None
                if r.width() >= 3 * self.EDGE_PX:
                    if pos.x() - r.left() <= self.EDGE_PX:
                        edge = 'left'
                    elif r.right() - pos.x() <= self.EDGE_PX:
                        edge = 'right'
                return c, edge
        return None, None

    # ── Вид ──────────────────────────────────────────────────────────────────
    def visible_span(self):
        return self.lane_width() / self.pps

    def scroll_limit(self):
        """Докуда можно прокрутить: конец проекта и немного места за ним."""
        span = self.visible_span()
        return max(0.0, self.project.duration() + span * 0.1 - span)

    def set_offset(self, t):
        limit = self.scroll_limit()
        self.offset = max(0.0, min(float(t), limit))
        self.viewChanged.emit()
        self.update()

    def zoom_to_fit(self):
        dur = max(1.0, self.project.duration())
        self.pps = max(0.5, min(400.0, self.lane_width() * 0.92 / dur))
        self.offset = 0.0
        self.viewChanged.emit()
        self.update()

    def set_playhead(self, t, follow=True):
        t = max(0.0, float(t))
        if abs(t - self.playhead) < 1e-6:
            return
        self.playhead = t
        if follow and self._drag is None:
            span = self.visible_span()
            if t < self.offset or t > self.offset + span * 0.97:
                self.set_offset(t - span * 0.1)
                return
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.viewChanged.emit()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if not delta:
            ev.ignore()
            return
        if ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
            x = ev.position().x()
            t_at = self.t_of(max(self.HEADER_W, x))
            factor = 1.2 if delta > 0 else 1 / 1.2
            self.pps = max(0.5, min(400.0, self.pps * factor))
            self.set_offset(t_at - (max(self.HEADER_W, x) - self.HEADER_W) / self.pps)
        else:
            self.set_offset(self.offset - delta / 120.0 * self.visible_span() * 0.15)
        ev.accept()

    # ── Прилипание ───────────────────────────────────────────────────────────
    def _snap_points(self, exclude):
        pts = [0.0, self.playhead]
        for c in self.project.clips:
            if c.id != exclude:
                pts += [c.start, c.end]
        return pts

    def _snap(self, t, exclude):
        best, dist = t, self.SNAP_PX / self.pps
        for p in self._snap_points(exclude):
            if abs(p - t) < dist:
                best, dist = p, abs(p - t)
        return best

    # ── Мышь ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() != _api.Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
        pos = ev.position()
        if pos.x() < self.HEADER_W:
            row = self.row_of(pos.y())
            if row is not None:
                self.editStarted.emit()
                tr = self.project.tracks[row[0]]
                tr.enabled = not tr.enabled
                self.edited.emit()
                self.update()
            return
        clip, edge = self.hit(pos)
        if clip is None:
            if self.selected:
                self.selected = ""
                self.selectionChanged.emit("")
            self._drag = {'mode': 'scrub'}
            self.seekRequested.emit(max(0.0, self.t_of(pos.x())))
            self.update()
            return
        if clip.id != self.selected:
            self.selected = clip.id
            self.selectionChanged.emit(clip.id)
        self._drag = {'mode': 'trim' if edge else 'press', 'edge': edge,
                      'id': clip.id, 'x0': pos.x(), 'y0': pos.y(),
                      'grab': self.t_of(pos.x()) - clip.start, 'started': False}
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        d = self._drag
        if d is None:
            clip, edge = self.hit(pos)
            cur = (_api.Qt.CursorShape.SizeHorCursor if edge else
                   _api.Qt.CursorShape.OpenHandCursor if clip is not None else
                   _api.Qt.CursorShape.ArrowCursor)
            self.setCursor(cur)
            return
        if d['mode'] == 'scrub':
            self.seekRequested.emit(max(0.0, self.t_of(pos.x())))
            return
        clip = self.project.clip(d['id'])
        if clip is None:
            self._drag = None
            return
        if d['mode'] == 'press':
            if abs(pos.x() - d['x0']) < self.DRAG_PX and abs(pos.y() - d['y0']) < self.DRAG_PX:
                return
            d['mode'] = 'move'
            self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
        if d['mode'] == 'trim':
            if not d['started']:
                self.editStarted.emit()
                d['started'] = True
            t = self._snap(self.t_of(pos.x()), clip.id)
            self.project.trim(clip.id, d['edge'], t)
            self.viewChanged.emit()
            self.update()
            return
        # Перенос: клип-призрак идёт за мышью, модель меняется на отпускании.
        row = self.row_of(pos.y())
        kind = 'video' if clip.has_video else 'audio'
        track = clip.track
        if row is not None and self.project.tracks[row[0]].kind == kind:
            track = row[0]
        start = max(0.0, self.t_of(pos.x()) - d['grab'])
        if track != self.project.main_track:
            # Прилипает начало клипа, а если ему не к чему — конец.
            snapped = self._snap(start, clip.id)
            if abs(snapped - start) > 1e-9:
                start = snapped
            else:
                start = max(0.0, self._snap(start + clip.length, clip.id) - clip.length)
        d['track'], d['start'] = track, start
        self.update()

    def mouseReleaseEvent(self, ev):
        d = self._drag
        self._drag = None
        self.unsetCursor()
        if d is None:
            return
        if d['mode'] == 'trim' and d['started']:
            self.edited.emit()
        elif d['mode'] == 'move' and 'track' in d:
            clip = self.project.clip(d['id'])
            if clip is not None:
                self.editStarted.emit()
                self.project.move(clip.id, d['track'], d['start'])
                self.edited.emit()
        self.viewChanged.emit()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        clip, _edge = self.hit(ev.position())
        if clip is not None:
            self.clipActivated.emit(clip.id)

    def contextMenuEvent(self, ev):
        pos = ev.pos()
        clip, _edge = self.hit(_api.QPointF(pos))
        menu = QMenu(self)
        if clip is not None:
            if clip.id != self.selected:
                self.selected = clip.id
                self.selectionChanged.emit(clip.id)
                self.update()
            menu.addAction("Открыть в источнике",
                           lambda: self.actionRequested.emit('open', clip.id))
            act = menu.addAction("Разрезать у плейхеда\tCtrl+B",
                                 lambda: self.actionRequested.emit('split', clip.id))
            act.setEnabled(clip.start < self.playhead < clip.end)
            menu.addAction("Удалить\tDel", lambda: self.actionRequested.emit('delete', clip.id))
            menu.addSeparator()
            if clip.audio_path:
                act = menu.addAction("Без звука",
                                     lambda: self.actionRequested.emit('mute', clip.id))
                act.setCheckable(True)
                act.setChecked(clip.muted)
                menu.addAction(f"Громкость… ({int(round(clip.volume * 100))} %)",
                               lambda: self.actionRequested.emit('volume', clip.id))
            kind = 'video' if clip.has_video else 'audio'
            sub = menu.addMenu("На дорожку")
            for ti in self.project.display_order():
                if self.project.tracks[ti].kind != kind or ti == clip.track:
                    continue
                sub.addAction(self.project.track_name(ti),
                              lambda _t=ti: self.actionRequested.emit(f'track:{_t}', clip.id))
            sub.setEnabled(not sub.isEmpty())
        else:
            menu.addAction("Добавить видеодорожку",
                           lambda: self.actionRequested.emit('add_track:video', ''))
            menu.addAction("Добавить аудиодорожку",
                           lambda: self.actionRequested.emit('add_track:audio', ''))
            menu.addAction("Весь проект в окне", self.zoom_to_fit)
        menu.exec(ev.globalPos())

    def keyPressEvent(self, ev):
        if ev.key() in (_api.Qt.Key.Key_Delete, _api.Qt.Key.Key_Backspace) and self.selected:
            self.actionRequested.emit('delete', self.selected)
            ev.accept()
            return
        ev.ignore()

    def leaveEvent(self, ev):
        self.unsetCursor()
        super().leaveEvent(ev)

    # ── Отрисовка ────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = _api.QPainter(self)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
        C = _api.C
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), _api.QColor(C['surface']))
        rows = self.rows()
        for n, (ti, y, rh) in enumerate(rows):
            bg = _api.QColor(C['bg'] if ti == self.project.main_track else C['surface2'])
            p.fillRect(QRectF(self.HEADER_W, y, w - self.HEADER_W, rh), bg)
            p.setPen(_api.QPen(_api.QColor(C['surface']), 1))
            p.drawLine(self.HEADER_W, int(y + rh) - 1, w, int(y + rh) - 1)
        p.save()
        p.setClipRect(QRectF(self.HEADER_W, self.RULER_H, w - self.HEADER_W, h - self.RULER_H))
        d = self._drag or {}
        moving = d.get('id') if d.get('mode') == 'move' else None
        for c in self.project.clips:
            r = self.clip_rect(c)
            if r.right() < self.HEADER_W or r.left() > w:
                continue
            self._paint_clip(p, c, r, faded=(c.id == moving))
        if moving and 'track' in d:
            c = self.project.clip(moving)
            if c is not None:
                r = self.clip_rect(c, start=d['start'], track=d['track'])
                if d['track'] == self.project.main_track:
                    self._paint_insert_mark(p, c, d)
                self._paint_clip(p, c, r, ghost=True)
        if self.project.is_empty():
            p.setPen(_api.QColor(C['text3']))
            p.drawText(QRectF(self.HEADER_W + 12, self.RULER_H, w - self.HEADER_W - 24,
                              h - self.RULER_H),
                       int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
                       "Проект пуст. Выделите кусок на шкале источника выше и нажмите "
                       "«＋ В проект» (Insert) — так набираются куски из одного или "
                       "разных файлов. Здесь их можно резать (Ctrl+B), двигать и удалять.")
        p.restore()
        self._paint_ruler(p, w)
        self._paint_headers(p, rows)
        # Плейхед — жёлтая линия через все дорожки.
        x = self.x_of(self.playhead)
        if self.HEADER_W <= x <= w:
            col = _api.QColor(C['playhead'])
            p.setPen(_api.QPen(col, 2))
            p.drawLine(int(x), self.RULER_H - 4, int(x), h)
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(QPolygonF([_api.QPointF(x - 6, 2), _api.QPointF(x + 6, 2),
                                     _api.QPointF(x, self.RULER_H - 2)]))
        p.end()

    def _paint_insert_mark(self, p, clip, d):
        """Куда встанет клип на основной дорожке — вертикальная метка на стыке."""
        others = [o for o in self.project.clips_on(self.project.main_track) if o is not clip]
        at = sum(o.length for o in others
                 if d['start'] >= o.start + o.length / 2.0)
        x = self.x_of(at)
        row = next(r for r in self.rows() if r[0] == self.project.main_track)
        p.setPen(_api.QPen(_api.QColor(_api.C['accent']), 3))
        p.drawLine(int(x), int(row[1]) + 1, int(x), int(row[1] + row[2]) - 1)

    def _paint_clip(self, p, c, r, ghost=False, faded=False):
        C = _api.C
        enabled = self.project.tracks[c.track].enabled
        fill = _clip_color(c.src, c.has_video)
        if not enabled or faded:
            fill.setAlpha(70)
        if ghost:
            fill.setAlpha(170)
        body = r.adjusted(0.5, 0.5, -0.5, -0.5)
        path = _api.QPainterPath()
        path.addRoundedRect(body, 5, 5)
        p.fillPath(path, fill)
        text_left = body.left() + 6
        if c.has_video and self.thumb_provider is not None and body.width() > 30 and not ghost:
            pm = self.thumb_provider(c)
            if pm is not None and not pm.isNull():
                th = body.height() - 2
                tw = min(body.width() - 4, th * pm.width() / max(1, pm.height()))
                p.save()
                p.setClipPath(path)
                p.drawPixmap(QRectF(body.left() + 1, body.top() + 1, tw, th), pm,
                             QRectF(0, 0, pm.width(), pm.height()))
                p.restore()
                text_left = body.left() + tw + 6
        if body.right() - text_left > 18:
            font = _api.QFont(self.font())
            font.setPixelSize(11)
            p.setFont(font)
            fm = _api.QFontMetrics(font)
            label = f"{c.name}  ·  {_fmt_len(c.length)}"
            if c.muted and c.audio_path:
                label = "без звука · " + label
            elif c.audio_path and c.volume != 1.0:
                label = f"{int(round(c.volume * 100))}% " + label
            txt = fm.elidedText(label, _api.Qt.TextElideMode.ElideRight,
                                int(body.right() - text_left - 4))
            p.setPen(_api.QColor(0, 0, 0, 150))
            p.drawText(QRectF(text_left + 1, body.top() + 1, body.right() - text_left, 15),
                       int(_api.Qt.AlignmentFlag.AlignLeft | _api.Qt.AlignmentFlag.AlignVCenter), txt)
            p.setPen(_api.QColor("#ffffff"))
            p.drawText(QRectF(text_left, body.top(), body.right() - text_left, 15),
                       int(_api.Qt.AlignmentFlag.AlignLeft | _api.Qt.AlignmentFlag.AlignVCenter), txt)
            if body.height() > 30 and c.has_video:
                p.setPen(_api.QColor(255, 255, 255, 170))
                span = f"{_api.s_to_time(c.in_s)} – {_api.s_to_time(c.out_s)}"
                p.drawText(QRectF(text_left, body.top() + 15, body.right() - text_left, 14),
                           int(_api.Qt.AlignmentFlag.AlignLeft | _api.Qt.AlignmentFlag.AlignVCenter),
                           fm.elidedText(span, _api.Qt.TextElideMode.ElideRight,
                                         int(body.right() - text_left - 4)))
        if c.id == self.selected and not ghost:
            p.setPen(_api.QPen(_api.QColor(C['playhead']), 2))
        else:
            p.setPen(_api.QPen(fill.darker(160), 1))
        p.setBrush(_api.Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_ruler(self, p, w):
        C = _api.C
        p.fillRect(QRectF(0, 0, w, self.RULER_H), _api.QColor(C['surface']))
        step = next((s for s in _RULER_STEPS if s * self.pps >= _RULER_MIN_PX), _RULER_STEPS[-1])
        minor = step / 5.0
        font = _api.QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        t = (int(self.offset / minor)) * minor
        end = self.t_of(w)
        while t <= end:
            x = self.x_of(t)
            if x >= self.HEADER_W:
                major = abs(t / step - round(t / step)) < 1e-6
                p.setPen(_api.QPen(_api.QColor(C['text3'] if major else C['border']), 1))
                p.drawLine(int(x), self.RULER_H - (8 if major else 4), int(x), self.RULER_H)
                if major:
                    p.setPen(_api.QColor(C['text2']))
                    p.drawText(int(x) + 3, self.RULER_H - 7, _fmt_ruler(t, step))
            t += minor
        p.setPen(_api.QPen(_api.QColor(C['border']), 1))
        p.drawLine(0, self.RULER_H - 1, w, self.RULER_H - 1)

    def _paint_headers(self, p, rows):
        C = _api.C
        p.fillRect(QRectF(0, 0, self.HEADER_W, self.height()), _api.QColor(C['surface']))
        font = _api.QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        for ti, y, rh in rows:
            tr = self.project.tracks[ti]
            main = ti == self.project.main_track
            box = QRectF(4, y + 2, self.HEADER_W - 8, rh - 4)
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(_api.QColor(C['surface3'] if tr.enabled else C['surface2']))
            p.drawRoundedRect(box, 4, 4)
            if tr.kind == 'video':
                icon = 'fa5s.eye' if tr.enabled else 'fa5s.eye-slash'
            else:
                icon = 'fa5s.volume-up' if tr.enabled else 'fa5s.volume-mute'
            col = C['text'] if tr.enabled else C['text3']
            try:
                pm = _api.get_icon_pixmap(icon, 12, col)
                p.drawPixmap(int(box.right()) - 16, int(box.center().y()) - 6, pm)
            except Exception:
                pass
            p.setPen(_api.QColor(C['accent'] if main and tr.enabled else col))
            p.drawText(QRectF(box.left() + 6, box.top(), box.width() - 22, box.height()),
                       int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
                       self.project.track_short(ti))
        p.setPen(_api.QPen(_api.QColor(C['border']), 1))
        p.drawLine(self.HEADER_W - 1, 0, self.HEADER_W - 1, self.height())


ProjectTimeline.__module__ = _api.__name__
