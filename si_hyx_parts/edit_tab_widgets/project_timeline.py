# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProjectTimeline — таймлайн «Монтажа»: единственная шкала вкладки (дорожки
и клипы, как в Filmora). Public namespace: edit_tab_widgets."""
import math
import zlib

import edit_tab_widgets as _api
from PyQt6.QtCore import QRect, QRectF
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

# Маркеры проекта (montage_project.Marker) на линейке — цвет по виду.
_MARKER_COLORS = {'scene': 'accent', 'beat': 'yellow', 'onset': 'text3',
                  'silence': 'border2', 'speech': 'green', 'word': 'accent2',
                  'custom': 'red', 'downbeat': 'yellow', 'phrase': 'accent2',
                  'kick': 'red2', 'snare': 'green2', 'hat': 'text3', 'slot': 'green'}
# Части песни (маркер section, label «chorus A») — полоса у верха линейки.
_SECTION_COLORS = {'intro': 'text3', 'verse': 'accent', 'build': 'yellow',
                   'chorus': 'red2', 'drop': 'red', 'bridge': 'green2', 'outro': 'text3'}
# Удары барабанов видны только при крупном масштабе (пикселей на секунду):
# в песне их тысячи, мельче они сливаются в серую полосу.
_HIT_MIN_PPS = {'kick': 30.0, 'snare': 30.0, 'hat': 80.0}


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


def _fmt_speed(speed):
    """Подпись скорости клипа: 2×, 0.5× — без лишних нулей."""
    try:
        v = float(speed)
    except (TypeError, ValueError):
        return "1×"
    txt = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{txt}×"


class ProjectTimeline(_api.QWidget):
    """Дорожки проекта сверху вниз: видео (верхние перекрывают нижние),
    основная «Видео 1» (магнитная), затем звук.

    Мышь: клик по линейке или пустому месту — плейхед (по линейке — и
    протяжка); перетаскивание по пустому месту дорожек — рамка выделения, как
    в Filmora (выделяются все клипы, которых она коснулась; с Ctrl — к уже
    выделенным); клик по клипу — выделение, Ctrl+клик — добавить/убрать клип
    из выделения; перетаскивание клипа — перенос (на основной дорожке —
    смена порядка, можно и на другую дорожку того же рода); край клипа —
    подрезка; двойной клик — плейхед в эту точку клипа; ПКМ — меню. Колесо —
    прокрутка, Ctrl+колесо — масштаб, клик по заголовку дорожки — вкл/выкл;
    у видеодорожки со звуком в заголовке ещё динамик — звук дорожки вкл/выкл
    (картинка остаётся). На клипах со звуком — волна (wave_provider).

    Правки модели делает сам (перенос, подрезка, вкл/выкл дорожки и её звука), объявляя
    editStarted ДО первой правки (вкладка снимает снимок для отмены) и edited
    после. Остальные команды уходят во вкладку через actionRequested.

    Неподвижный слой (дорожки, клипы с кадрами и волной, линейка, заголовки)
    рисуется в кэш и пересобирается, только когда меняется вид или модель:
    плейхед во время игры двигается десятки раз в секунду, и полная отрисовка
    (~15 мс, больше всего — волна) на каждый его шаг занимала главный поток
    вкладки почти целиком — звук после перемотки запаздывал, интерфейс лагал.
    Шаг плейхеда перерисовывает две узкие полоски."""

    seekRequested = _api.pyqtSignal(float)
    # Плейхед потянули мышью (первое движение после нажатия) и отпустили —
    # на время протяжки вкладка ставит воспроизведение на паузу.
    scrubStarted = _api.pyqtSignal()
    scrubFinished = _api.pyqtSignal()
    selectionChanged = _api.pyqtSignal(str)
    editStarted = _api.pyqtSignal()
    edited = _api.pyqtSignal()
    actionRequested = _api.pyqtSignal(str, str)
    viewChanged = _api.pyqtSignal()

    HEADER_W = 64
    RULER_H = 20
    ROW_MAIN_H = 66
    ROW_VIDEO_H = 30
    ROW_AUDIO_H = 30
    EDGE_PX = 6
    SNAP_PX = 8
    DRAG_PX = 4

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.pps = 40.0              # пикселей на секунду
        self.offset = 0.0            # время у левого края дорожек
        self.playhead = 0.0
        # Выделение: selected — «главный» клип (с ним работают правки у
        # плейхеда и меню), _sel_ids — все выделенные (рамкой или Ctrl+клик).
        # Присваивание selected выделяет ровно этот клип.
        self._sel_ids = set()
        self.selected = ""
        # thumb_provider(clip, время файла, высота в px) -> QPixmap|None: кадр
        # для полосы превью вдоль клипа, как в Filmora (вкладка достаёт кадры
        # фоном и зовёт invalidate(), когда они приехали; пока кадра нет —
        # отдаёт ближайший готовый).
        self.thumb_provider = None
        # wave_provider(clip) -> (сэмплы 0..1 на весь файл, длительность файла)
        # или None: волна звука на клипе.
        self.wave_provider = None
        # can_paste() -> bool: в буфере вкладки есть клипы (пункт «Вставить»).
        self.can_paste = None
        self._drag = None
        self._hover = None
        self._static = None          # кэш неподвижного слоя (см. докстроку класса)
        self._static_key = None
        self._version = 0            # invalidate(): кадры или волна приехали
        self.setMouseTracking(True)
        self.setFocusPolicy(_api.Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(self.content_height())
        self.setMaximumHeight(self.content_height())

    # ── Выделение ────────────────────────────────────────────────────────────
    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, cid):
        self._selected = cid or ""
        self._sel_ids = {self._selected} if self._selected else set()

    def selected_ids(self):
        """Все выделенные клипы — id в порядке модели."""
        return [c.id for c in self.project.clips if c.id in self._sel_ids]

    def select(self, ids, primary=None):
        """Выделить клипы ids (например, только что вставленные), главный —
        primary."""
        self._set_selection(ids, primary)

    def _set_selection(self, ids, primary=None):
        """Выделяет набор клипов; главный — primary, если он в наборе, иначе
        прежний главный, если он остался, иначе первый по времени."""
        ids = {i for i in ids if self.project.clip(i) is not None}
        if primary not in ids:
            primary = self._selected if self._selected in ids else None
        if primary is None and ids:
            primary = min(ids, key=lambda i: (self.project.clip(i).start, i))
        changed = (primary or "") != self._selected
        self._selected = primary or ""
        self._sel_ids = ids
        if changed:
            self.selectionChanged.emit(self._selected)
        self.update()

    # ── Геометрия ────────────────────────────────────────────────────────────
    def set_project(self, project):
        self.project = project
        if self.project.clip(self._selected) is None:
            self.selected = ""
        else:
            self._sel_ids = {i for i in self._sel_ids if self.project.clip(i) is not None}
        self.refresh()

    def refresh(self):
        """Модель изменилась: высота (дорожки могли добавиться) и перерисовка."""
        h = self.content_height()
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self.viewChanged.emit()
        self.invalidate()

    def invalidate(self):
        """Неподвижный слой устарел (приехали кадры превью или волна) —
        пересобрать при следующей отрисовке."""
        self._version += 1
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

    def _header_box(self, y, rh):
        return QRectF(4, y + 2, self.HEADER_W - 8, rh - 4)

    def _mute_rect(self, ti, y, rh):
        """Кнопка звука дорожки в заголовке: только у видеодорожки, на которой
        есть клипы со звуком (или звук уже выключен). У основной дорожки — под
        глазом, на уровне волны клипа; у узких — слева от глаза. None — нет."""
        tr = self.project.tracks[ti]
        if tr.kind != 'video' or not (tr.muted or self.project.track_has_audio(ti)):
            return None
        box = self._header_box(y, rh)
        if rh >= 44:
            return QRectF(box.right() - 19, box.bottom() - 17, 16, 16)
        return QRectF(box.right() - 35, box.center().y() - 8, 16, 16)

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

    def _fit_pps(self):
        return self.lane_width() * 0.92 / max(1.0, self.project.duration())

    def min_pps(self):
        """Предел отдаления: 0.5 px/с, но длинный проект (серия, фильм в узком
        окне) всё равно должен целиком помещаться — тогда предел ниже."""
        return min(0.5, self._fit_pps())

    def zoom_to_fit(self):
        self.pps = max(self.min_pps(), min(400.0, self._fit_pps()))
        self.offset = 0.0
        self.viewChanged.emit()
        self.update()

    def set_playhead(self, t, follow=True):
        t = max(0.0, float(t))
        if abs(t - self.playhead) < 1e-6:
            return
        old_x = self.x_of(self.playhead)
        self.playhead = t
        if follow and self._drag is None:
            span = self.visible_span()
            if t < self.offset or t > self.offset + span * 0.97:
                self.set_offset(t - span * 0.1)
                return
        # Всё остальное лежит в кэше — перерисовываем только полоски плейхеда.
        self._update_playhead_strip(old_x)
        self._update_playhead_strip(self.x_of(t))

    def _update_playhead_strip(self, x):
        if -8 <= x <= self.width() + 8:
            self.update(QRect(int(x) - 8, 0, 17, self.height()))

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
            self.pps = max(self.min_pps(), min(400.0, self.pps * factor))
            self.set_offset(t_at - (max(self.HEADER_W, x) - self.HEADER_W) / self.pps)
        else:
            self.set_offset(self.offset - delta / 120.0 * self.visible_span() * 0.15)
        ev.accept()

    # ── Прилипание ───────────────────────────────────────────────────────────
    def _snap_points(self, exclude):
        """exclude — id клипа или набор id (переносимая группа)."""
        if isinstance(exclude, str):
            exclude = {exclude}
        pts = [0.0, self.playhead]
        for c in self.project.clips:
            if c.id not in exclude:
                pts += [c.start, c.end]
        # Маркеры (сцены, биты, речь…) — только видимые: битов в песне сотни.
        lo, hi = self.offset, self.t_of(self.width())
        for m in self._visible_markers(lo, hi):
            if self.pps < _HIT_MIN_PPS.get(m.kind, 0.0):
                continue                 # невидимые при этом масштабе удары
            pts.append(m.t)
            if m.end is not None:
                pts.append(m.end)
        return pts

    def _visible_markers(self, lo, hi):
        """Маркеры, задевающие [lo, hi] (список проекта отсортирован по t)."""
        for m in getattr(self.project, "markers", ()):
            if m.t > hi:
                break
            if (m.end if m.end is not None else m.t) >= lo:
                yield m

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
                mute = self._mute_rect(*row)
                if mute is not None and mute.contains(pos):
                    tr.muted = not tr.muted
                else:
                    tr.enabled = not tr.enabled
                self.edited.emit()
                self.update()
            return
        ctrl = bool(ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier)
        clip, edge = self.hit(pos)
        if clip is None and pos.y() >= self.RULER_H:
            # Пустое место дорожек: рамка выделения. Клик без сдвига мыши —
            # прежний клик (плейхед сюда), его шлём на отпускании.
            if not ctrl and self._sel_ids:
                self._set_selection(())
            self._drag = {'mode': 'marquee', 't0': self.t_of(pos.x()), 'y0': pos.y(),
                          'x1': pos.x(), 'y1': pos.y(), 'moved': False,
                          'base': set(self._sel_ids) if ctrl else set()}
            return
        if clip is None:
            if self._sel_ids:
                self._set_selection(())
            self._drag = {'mode': 'scrub', 'x0': pos.x(), 'moved': False}
            self.seekRequested.emit(max(0.0, self.t_of(pos.x())))
            self.update()
            return
        if ctrl and not edge:
            # Ctrl+клик — клип в выделение или из него, без переноса.
            ids = set(self._sel_ids)
            if clip.id in ids:
                ids.discard(clip.id)
                self._set_selection(ids)
            else:
                ids.add(clip.id)
                self._set_selection(ids, clip.id)
            return
        # Клик по клипу из нескольких выделенных не сбрасывает выделение сразу
        # (это может быть начало переноса) — сбросит отпускание без переноса.
        collapse = clip.id in self._sel_ids and len(self._sel_ids) > 1
        if not collapse and (clip.id != self.selected or len(self._sel_ids) > 1):
            self._set_selection({clip.id}, clip.id)
        self._drag = {'mode': 'trim' if edge else 'press', 'edge': edge,
                      'id': clip.id, 'x0': pos.x(), 'y0': pos.y(),
                      'grab': self.t_of(pos.x()) - clip.start, 'started': False,
                      'collapse': collapse}
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        d = self._drag
        if d is None:
            clip, edge = self.hit(pos)
            header = pos.x() < self.HEADER_W and self.row_of(pos.y()) is not None
            cur = (_api.Qt.CursorShape.SizeHorCursor if edge else
                   _api.Qt.CursorShape.OpenHandCursor if clip is not None else
                   _api.Qt.CursorShape.PointingHandCursor if header else
                   _api.Qt.CursorShape.ArrowCursor)
            self.setCursor(cur)
            return
        if d['mode'] == 'scrub':
            if not d['moved']:
                if abs(pos.x() - d['x0']) < self.DRAG_PX:
                    return
                d['moved'] = True
                self.scrubStarted.emit()
            self.seekRequested.emit(max(0.0, self.t_of(pos.x())))
            return
        if d['mode'] == 'marquee':
            d['x1'], d['y1'] = pos.x(), pos.y()
            if not d['moved']:
                x0 = self.x_of(d['t0'])
                if abs(pos.x() - x0) < self.DRAG_PX and abs(pos.y() - d['y0']) < self.DRAG_PX:
                    return
                d['moved'] = True
            band = self._marquee_rect(d)
            hit = {c.id for c in self.project.clips if self.clip_rect(c).intersects(band)}
            self._set_selection(d['base'] | hit)
            self.update()
            return
        clip = self.project.clip(d['id'])
        if clip is None:
            self._drag = None
            return
        if d['mode'] == 'press':
            if abs(pos.x() - d['x0']) < self.DRAG_PX and abs(pos.y() - d['y0']) < self.DRAG_PX:
                return
            d['mode'] = 'move'
            # Тянут клип из нескольких выделенных — едет вся группа.
            sel = self._sel_ids
            d['group'] = frozenset(sel) if len(sel) > 1 and d['id'] in sel else None
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
        group = d.get('group')
        exclude = group or clip.id
        if track != self.project.main_track:
            # Прилипает начало клипа, а если ему не к чему — конец.
            snapped = self._snap(start, exclude)
            if abs(snapped - start) > 1e-9:
                start = snapped
            else:
                start = max(0.0, self._snap(start + clip.length, exclude) - clip.length)
        if group:
            # Группа не уходит левее нуля: упор по самому левому свободному клипу.
            free = [c.start for c in self.project.clips
                    if c.id in group and c.id != clip.id
                    and c.track != self.project.main_track]
            if free:
                start = max(start, clip.start - min(free))
        d['track'], d['start'] = track, start
        self.update()

    def mouseReleaseEvent(self, ev):
        d = self._drag
        self._drag = None
        self.unsetCursor()
        if d is None:
            return
        if d['mode'] == 'marquee' and not d['moved']:
            self.seekRequested.emit(max(0.0, d['t0']))
        elif d['mode'] == 'press' and d.get('collapse'):
            self._set_selection({d['id']}, d['id'])
        elif d['mode'] == 'scrub' and d['moved']:
            self.scrubFinished.emit()
        elif d['mode'] == 'trim' and d['started']:
            self.edited.emit()
        elif d['mode'] == 'move' and 'track' in d:
            clip = self.project.clip(d['id'])
            if clip is not None:
                self.editStarted.emit()
                if d.get('group'):
                    self.project.move_group(d['group'], clip.id, d['track'], d['start'])
                else:
                    self.project.move(clip.id, d['track'], d['start'])
                self.edited.emit()
        self.viewChanged.emit()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        clip, _edge = self.hit(ev.position())
        if clip is not None:
            self.seekRequested.emit(max(0.0, self.t_of(ev.position().x())))

    def contextMenuEvent(self, ev):
        pos = ev.pos()
        clip, _edge = self.hit(_api.QPointF(pos))
        menu = QMenu(self)
        if clip is not None:
            if clip.id not in self._sel_ids:
                self._set_selection({clip.id}, clip.id)
            elif clip.id != self.selected:
                self._set_selection(self._sel_ids, clip.id)
            act = menu.addAction("Разрезать у плейхеда\tCtrl+B",
                                 lambda: self.actionRequested.emit('split', clip.id))
            under = clip.start < self.playhead < clip.end
            act.setEnabled(under)
            act = menu.addAction("Обрезать начало до плейхеда",
                                 lambda: self.actionRequested.emit('trim:left', clip.id))
            act.setEnabled(under)
            act = menu.addAction("Обрезать конец до плейхеда",
                                 lambda: self.actionRequested.emit('trim:right', clip.id))
            act.setEnabled(under)
            n_sel = len(self._sel_ids)
            menu.addAction(f"Удалить выделенные ({n_sel})\tDel" if n_sel > 1 else "Удалить\tDel",
                           lambda: self.actionRequested.emit('delete', clip.id))
            menu.addAction(f"Копировать выделенные ({n_sel})\tCtrl+C" if n_sel > 1
                           else "Копировать\tCtrl+C",
                           lambda: self.actionRequested.emit('copy', clip.id))
            self._add_paste_action(menu)
            menu.addSeparator()
            if clip.audio_path:
                act = menu.addAction("Без звука",
                                     lambda: self.actionRequested.emit('mute', clip.id))
                act.setCheckable(True)
                act.setChecked(clip.muted)
                menu.addAction(f"Громкость… ({int(round(clip.volume * 100))} %)",
                               lambda: self.actionRequested.emit('volume', clip.id))
                if clip.has_video and not clip.is_image:
                    menu.addAction("Отделить звук",
                                   lambda: self.actionRequested.emit('detach_audio', clip.id))
            if not clip.is_image:
                sub = menu.addMenu("Скорость")
                for val in (0.25, 0.5, 1.0, 1.5, 2.0, 4.0):
                    act = sub.addAction(_fmt_speed(val))
                    act.setCheckable(True)
                    act.setChecked(abs(clip.speed - val) < 1e-6)
                    act.triggered.connect(
                        lambda _checked=False, v=val:
                        self.actionRequested.emit(f'speed:{v}', clip.id))
                sub.addSeparator()
                sub.addAction("Другая…",
                              lambda: self.actionRequested.emit('speed:custom', clip.id))
        else:
            self._add_paste_action(menu)
            menu.addSeparator()
            menu.addAction("Добавить видеодорожку",
                           lambda: self.actionRequested.emit('add_track:video', ''))
            menu.addAction("Добавить аудиодорожку",
                           lambda: self.actionRequested.emit('add_track:audio', ''))
            menu.addAction("Весь проект в окне", self.zoom_to_fit)
        menu.exec(ev.globalPos())

    def _add_paste_action(self, menu):
        """«Вставить у плейхеда» — доступно, когда в буфере вкладки есть клипы."""
        act = menu.addAction("Вставить у плейхеда\tCtrl+V",
                             lambda: self.actionRequested.emit('paste', ''))
        act.setEnabled(bool(self.can_paste()) if self.can_paste is not None else False)

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
    def _static_signature(self):
        """Всё, от чего зависит неподвижный слой: размер, вид, модель (её правят
        и сам виджет, и вкладка — поэтому сверяем сами клипы), перетаскивание
        и номер invalidate()."""
        proj = self.project
        clips = tuple((c.id, c.track, c.start, c.in_s, c.out_s, c.speed, c.muted, c.volume)
                      for c in proj.clips)
        tracks = tuple((t.kind, t.enabled, t.muted) for t in proj.tracks)
        markers = getattr(proj, "markers", [])
        d = self._drag or {}
        drag = (d.get('id'), d.get('track'), d.get('start')) if d.get('mode') == 'move' else None
        return (self.width(), self.height(), self.devicePixelRatioF(), self.offset,
                self.pps, self.selected, frozenset(self._sel_ids), id(proj), clips,
                tracks, (id(markers), len(markers)), drag, self._version)

    def paintEvent(self, ev):
        key = self._static_signature()
        if self._static is None or key != self._static_key:
            self._static = self._render_static()
            self._static_key = key
        p = _api.QPainter(self)
        p.drawPixmap(0, 0, self._static)
        d = self._drag
        if d is not None and d['mode'] == 'marquee' and d['moved']:
            band = self._marquee_rect(d)
            col = _api.QColor(_api.C['accent'])
            p.setPen(_api.QPen(col, 1))
            col.setAlpha(40)
            p.setBrush(col)
            p.drawRect(band)
        self._paint_playhead(p)
        p.end()

    def _marquee_rect(self, d):
        """Рамка выделения: от точки нажатия (по времени — она едет вместе с
        прокруткой) до мыши, в пределах дорожек."""
        x0 = self.x_of(d['t0'])
        lane = QRectF(self.HEADER_W, self.RULER_H, self.lane_width(),
                      self.height() - self.RULER_H)
        return QRectF(_api.QPointF(min(x0, d['x1']), min(d['y0'], d['y1'])),
                      _api.QPointF(max(x0, d['x1']), max(d['y0'], d['y1']))).intersected(lane)

    def _paint_playhead(self, p):
        """Плейхед — жёлтая линия через все дорожки."""
        x = self.x_of(self.playhead)
        if not (self.HEADER_W <= x <= self.width()):
            return
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
        col = _api.QColor(_api.C['playhead'])
        p.setPen(_api.QPen(col, 2))
        p.drawLine(int(x), self.RULER_H - 4, int(x), self.height())
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(QPolygonF([_api.QPointF(x - 6, 2), _api.QPointF(x + 6, 2),
                                 _api.QPointF(x, self.RULER_H - 2)]))

    def _render_static(self):
        """Неподвижный слой — в картинку размером с виджет."""
        dpr = self.devicePixelRatioF()
        w, h = max(1, self.width()), max(1, self.height())
        pm = _api.QPixmap(int(math.ceil(w * dpr)), int(math.ceil(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        C = _api.C
        pm.fill(_api.QColor(C['surface']))
        p = _api.QPainter(pm)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
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
        group = (d.get('group') or {moving}) if moving else set()
        for c in self.project.clips:
            r = self.clip_rect(c)
            if r.right() < self.HEADER_W or r.left() > w:
                continue
            self._paint_clip(p, c, r, faded=(c.id in group))
        lead = self.project.clip(moving) if moving and 'track' in d else None
        if lead is not None:
            # Призраки: ведущий — под мышью, остальные — с тем же сдвигом.
            delta = d['start'] - lead.start
            ghosts = [(c, c.start + delta, c.track) for c in self.project.clips
                      if c.id in group and c is not lead]
            ghosts.append((lead, d['start'], d['track']))
            main = self.project.main_track
            on_main = [s for c, s, ti in ghosts if ti == main]
            if on_main:
                self._paint_insert_mark(p, group, min(on_main))
            for c, start, ti in ghosts:
                self._paint_clip(p, c, self.clip_rect(c, start=start, track=ti), ghost=True)
        if self.project.is_empty():
            p.setPen(_api.QColor(C['text3']))
            p.drawText(QRectF(self.HEADER_W + 12, self.RULER_H, w - self.HEADER_W - 24,
                              h - self.RULER_H),
                       int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
                       "Откройте или перетащите сюда файл — он ляжет на дорожку целиком.  "
                       "Ctrl+B — разрезать,  Shift+C / Shift+V — обрезать начало/конец до "
                       "плейхеда,  Delete — удалить.")
        p.restore()
        self._paint_ruler(p, w)
        self._paint_headers(p, rows)
        p.end()
        return pm

    def _paint_insert_mark(self, p, moving_ids, start):
        """Куда встанут переносимые клипы на основной дорожке — вертикальная
        метка на стыке."""
        others = [o for o in self.project.clips_on(self.project.main_track)
                  if o.id not in moving_ids]
        at = sum(o.length for o in others
                 if start >= o.start + o.length / 2.0)
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
        strip = False
        if not ghost:
            self._paint_wave(p, c, body, path)
            if c.has_video and self.thumb_provider is not None:
                strip = self._paint_filmstrip(p, c, body, path, dim=(not enabled or faded))
        if body.width() > 24:
            self._paint_clip_label(p, c, body, over_frames=strip)
        if c.id in self._sel_ids and not ghost:
            p.setPen(_api.QPen(_api.QColor(C['playhead']), 2))
        else:
            p.setPen(_api.QPen(fill.darker(160), 1))
        p.setBrush(_api.Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_clip_label(self, p, c, body, over_frames=False):
        """Имя и длина клипа. Поверх полосы кадров — на тёмной плашке (как в
        Filmora); без кадров — тенью, со второй строкой «откуда–докуда»."""
        font = _api.QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        fm = _api.QFontMetrics(font)
        label = f"{c.name}  ·  {_fmt_len(c.length)}"
        if abs(c.speed - 1.0) > 1e-6:
            label = f"{c.name}  ·  {_fmt_len(c.length)}  ·  {_fmt_speed(c.speed)}"
        if c.muted and c.audio_path:
            label = "без звука · " + label
        elif c.audio_path and c.volume != 1.0:
            label = f"{int(round(c.volume * 100))}% " + label
        left = max(body.left(), float(self.HEADER_W)) + 6
        avail = int(body.right() - left - 6)
        if avail < 18:
            return
        txt = fm.elidedText(label, _api.Qt.TextElideMode.ElideRight, avail)
        align = int(_api.Qt.AlignmentFlag.AlignLeft | _api.Qt.AlignmentFlag.AlignVCenter)
        if over_frames:
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(_api.QColor(0, 0, 0, 150))
            p.drawRoundedRect(QRectF(left - 4, body.top() + 2,
                                     fm.horizontalAdvance(txt) + 8, 14), 3, 3)
        else:
            p.setPen(_api.QColor(0, 0, 0, 150))
            p.drawText(QRectF(left + 1, body.top() + 2, avail, 15), align, txt)
        p.setPen(_api.QColor("#ffffff"))
        p.drawText(QRectF(left, body.top() + 1, avail, 15), align, txt)
        if not over_frames and body.height() > 30 and c.has_video:
            p.setPen(_api.QColor(255, 255, 255, 170))
            span = f"{_api.s_to_time(c.in_s)} – {_api.s_to_time(c.out_s)}"
            p.drawText(QRectF(left, body.top() + 16, avail, 14), align,
                       fm.elidedText(span, _api.Qt.TextElideMode.ElideRight, avail))

    def _paint_filmstrip(self, p, c, body, path, dim=False):
        """Полоса кадров вдоль клипа, как в Filmora: ячейки в пропорциях кадра,
        в каждой — кадр из её середины. Время ячейки прилипает к сетке шагом
        2^n секунд: при соседнем масштабе половина кадров уже готова. True —
        нарисован хотя бы один кадр."""
        th = self._thumb_h(c, body)
        if th < 12 or body.width() < 8:
            return False
        aspect = (c.width / c.height) if (c.width > 0 and c.height > 0) else 16.0 / 9.0
        tw = max(12.0, th * aspect)
        vis_l = max(body.left(), float(self.HEADER_W))
        vis_r = min(body.right(), float(self.width()))
        if vis_r <= vis_l:
            return False
        k0 = max(0, int((vis_l - body.left()) // tw))
        k1 = int((vis_r - body.left()) // tw)
        tile_s = tw / self.pps
        speed = max(0.01, c.speed)
        step = 2.0 ** round(math.log2(max(0.25, tile_s * speed)))
        last = max(c.in_s, c.out_s - 0.05)
        height = int(round(th))
        drew = False
        p.save()
        p.setClipPath(path)
        if dim:
            p.setOpacity(0.4)
        for k in range(k0, k1 + 1):
            t = c.in_s + (k + 0.5) * tile_s * speed
            t = min(max(c.in_s, round(t / step) * step), last)
            pm = self.thumb_provider(c, t, height)
            if pm is None or pm.isNull():
                continue
            cell = QRectF(body.left() + k * tw, body.top() + 1, tw, th)
            p.drawPixmap(cell, pm, self._cover_rect(pm, cell))
            drew = True
        p.restore()
        return drew

    @staticmethod
    def _cover_rect(pm, cell):
        """Часть картинки в пропорциях ячейки (по центру) — без растяжения."""
        pw, ph = float(pm.width()), float(pm.height())
        if pw <= 0 or ph <= 0 or cell.width() <= 0 or cell.height() <= 0:
            return QRectF(0, 0, max(1.0, pw), max(1.0, ph))
        want = cell.width() / cell.height()
        if pw / ph > want:
            w = ph * want
            return QRectF((pw - w) / 2.0, 0, w, ph)
        h = pw / want
        return QRectF(0, (ph - h) / 2.0, pw, h)

    def _wave_band(self, c, body):
        """Где рисуется волна клипа: нижняя часть клипа основной дорожки,
        клип звуковой дорожки — целиком; у верхних видеодорожек волны нет."""
        if not c.has_video:
            return QRectF(body.left(), body.top() + 2, body.width(), body.height() - 4)
        if c.track == self.project.main_track and body.height() >= 44:
            h = body.height() * 0.36
            return QRectF(body.left(), body.bottom() - h, body.width(), h)
        return None

    def _thumb_h(self, c, body):
        band = self._wave_band(c, body) if c.audio_path else None
        return (band.top() - body.top() - 1) if band is not None else body.height() - 2

    def _paint_wave(self, p, c, body, path):
        """Волна звука клипа — по сэмплам всего файла, срез in..out."""
        if self.wave_provider is None or not c.audio_path:
            return
        data = self.wave_provider(c)
        if not data:
            return
        samples, dur = data
        band = self._wave_band(c, body)
        if band is None or not samples or dur <= 0:
            return
        n = len(samples)
        w = int(self.width())
        x0 = max(int(band.left()), self.HEADER_W)
        x1 = min(int(band.right()), w)
        if x1 - x0 < 2:
            return
        mid = band.center().y()
        half = band.height() / 2.0 - 1
        top, bottom = [], []
        per_s = n / dur
        speed = max(0.01, c.speed)
        for x in range(x0, x1 + 1):
            t0 = c.in_s + (x - band.left()) / self.pps * speed
            t1 = t0 + 1.0 / self.pps * speed
            i0 = max(0, min(n - 1, int(t0 * per_s)))
            i1 = max(i0 + 1, min(n, int(t1 * per_s) + 1))
            v = max(samples[i0:i1])
            top.append(_api.QPointF(x, mid - v * half))
            bottom.append(_api.QPointF(x, mid + v * half))
        poly = QPolygonF(top + list(reversed(bottom)))
        p.save()
        p.setClipPath(path)
        if c.has_video:
            p.fillRect(band, _api.QColor(0, 0, 0, 70))
        p.setPen(_api.Qt.PenStyle.NoPen)
        # Звук не звучит (клип или вся дорожка без звука) — волна бледная.
        silent = c.muted or self.project.tracks[c.track].muted
        p.setBrush(_api.QColor(255, 255, 255, 45 if silent else 120 if c.has_video else 150))
        p.drawPolygon(poly)
        p.restore()

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
        self._paint_markers(p, w)

    def _paint_markers(self, p, w):
        """Маркеры проекта у низа линейки: точка — штрих, чем сильнее (бит,
        уверенность сцены), тем выше; отрезок (тишина, речь, слово) — полоса."""
        C = _api.C
        p.save()
        p.setClipRect(QRectF(self.HEADER_W, 0, w - self.HEADER_W, self.RULER_H))
        for m in self._visible_markers(self.offset, self.t_of(w)):
            if self.pps < _HIT_MIN_PPS.get(m.kind, 0.0):
                continue
            col = _api.QColor(C[_MARKER_COLORS.get(m.kind, 'text3')])
            x = self.x_of(m.t)
            if m.kind == 'section':
                # Часть песни — полоса у верха линейки цветом подписи, с
                # просветом в 1 px на границе частей.
                col = _api.QColor(C[_SECTION_COLORS.get(m.label.split(' ')[0], 'border2')])
                col.setAlpha(170)
                end = m.end if m.end is not None else m.t
                p.fillRect(QRectF(x + 1, 0, max(1.0, self.x_of(end) - x - 1), 3), col)
                continue
            if m.kind == 'phrase':
                # Фраза — штрих у начала (длиннее у восьмитактовой), не полоса:
                # фразы идут встык и слились бы в одну.
                h = 8 if m.label == '8' else 5
                p.setPen(_api.QPen(col, 1))
                p.drawLine(_api.QPointF(x, 3), _api.QPointF(x, 3 + h))
                continue
            if m.end is not None and m.end > m.t:
                col.setAlpha(150)
                p.fillRect(QRectF(x, self.RULER_H - 4, max(1.0, self.x_of(m.end) - x), 3), col)
                continue
            if m.kind == 'slot':
                # Место для реза — треугольник у верха линейки.
                p.setPen(_api.Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawPolygon(QPolygonF([_api.QPointF(x - 3, 3), _api.QPointF(x + 3, 3),
                                         _api.QPointF(x, 8)]))
                continue
            if m.kind in _HIT_MIN_PPS:
                h = 2 + 4 * max(0.0, min(1.0, m.strength))
            else:
                h = 3 + 9 * max(0.0, min(1.0, m.strength))
            wide = m.kind in ('scene', 'custom', 'downbeat')
            p.setPen(_api.QPen(col, 2 if wide else 1))
            p.drawLine(_api.QPointF(x, self.RULER_H - 1 - h), _api.QPointF(x, self.RULER_H - 1))
        p.restore()

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
            box = self._header_box(y, rh)
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
            mute = self._mute_rect(ti, y, rh)
            if mute is not None:
                # Выключенный звук — красным: видно и у выключенной дорожки.
                mcol = C['red'] if tr.muted else col
                try:
                    pm = _api.get_icon_pixmap(
                        'fa5s.volume-mute' if tr.muted else 'fa5s.volume-up', 12, mcol)
                    p.drawPixmap(int(mute.center().x()) - 6, int(mute.center().y()) - 6, pm)
                except Exception:
                    pass
            text_w = box.width() - (38 if mute is not None and rh < 44 else 22)
            p.setPen(_api.QColor(C['accent'] if main and tr.enabled else col))
            p.drawText(QRectF(box.left() + 6, box.top(), text_w, box.height()),
                       int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
                       self.project.track_short(ti))
        p.setPen(_api.QPen(_api.QColor(C['border']), 1))
        p.drawLine(self.HEADER_W - 1, 0, self.HEADER_W - 1, self.height())


ProjectTimeline.__module__ = _api.__name__
