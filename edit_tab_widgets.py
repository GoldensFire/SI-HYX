# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_widgets.py — виджеты вкладки «Монтаж»: звуковая волна, таймлайн
# субтитров, холст видео, полноэкранный режим, превью перемотки, индикаторы.
# Слой поверх edit_tab_base / edit_tab_workers.

import math
import os
import time
from functools import partial
from config import (
    QApplication, QColor, QEvent, QFont, QFontMetrics, QFrame,
    QHBoxLayout, QLabel, QPainter, QPen, QPixmap, QPoint, QPointF,
    QPushButton, QRectF, QSize, QSlider, QTimer, QVBoxLayout, QWidget, Qt,
    get_icon, get_icon_pixmap, pyqtSignal
)
from edit_tab_base import (
    C, QAudioOutput, QMediaPlayer, QVideoSink, _fullscreen_icon,
    _paint_subtitle, _paint_subtitle_styled, make_icon_btn, s_to_time
)
from edit_tab_workers import (_SeekThumbnailer)
from PyQt6.QtCore import (QRect, QUrl)
from PyQt6.QtGui import (QBrush, QLinearGradient, QPainterPath)
from PyQt6.QtWidgets import (QSizePolicy, QStyle, QStyleOptionSlider, QToolTip)



# ─── Waveform Widget ──────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    seekRequested       = pyqtSignal(float)
    playSeekRequested   = pyqtSignal(float)
    inSetRequested      = pyqtSignal(float)
    outSetRequested     = pyqtSignal(float)
    selectionChanged    = pyqtSignal(float, float)
    viewChanged         = pyqtSignal(float, float)
    interactionStarted  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.disp_samples = []   # нормированные+перцептивные значения для рисовки
        self.l_samples = []      # сырые огибающие каналов (для индикатора уровня)
        self.r_samples = []
        self.disp_l = []         # те же огибающие, нормированные как disp_samples
        self.disp_r = []
        self._norm = 1.0
        self.duration = 0.0
        self.in_s = 0.0
        self.out_s = 0.0
        self.playhead_s = 0.0
        self.setMinimumHeight(90)
        # ClickFocus: при клике/перетаскивании по волне фокус уходит на сам виджет
        # (а не остаётся на нативной видео-поверхности, которая исключена из
        # WidgetWithChildrenShortcut) — иначе Ctrl+Z/Ctrl+Y после работы с волной
        # не доходили до undo/redo.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.hover_x = None
        self.dragging = None
        self.drag_start_x = None
        self.orig_in = 0.0
        self.orig_out = 0.0
        self.tooltip_visible = False
        self.zoom = 1.0
        self.view_offset = 0.0
        self.loading_text = None
        self._anim_dots = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._cache: QPixmap | None = None
        self._cache_key = None

    def _tick_anim(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        self.update()

    def set_loading(self, text, animated=True):
        """Текст по центру полосы вместо волны. animated=True — «бегущие» точки
        (идёт процесс: создание превью/извлечение аудио). animated=False — статичная
        подсказка БЕЗ анимации точек (напр. «включите Пикселизацию» для картинки):
        бегущие точки там выглядят как несуществующий процесс и раздражают."""
        self.loading_text = text
        self.samples = []
        if animated:
            self._anim_timer.start(400)
        else:
            self._anim_timer.stop()
            self._anim_dots = 0
        self.update()

    def _compute_display_samples(self):
        """Готовит значения для рисовки: нормирует амплитуду по 97-му перцентилю
        (устойчиво к одиночным щелчкам) и прогоняет через перцептивную кривую.
        У типичного контента линейный пик низкий, поэтому без этого волна «прибита»
        к центру и кажется, что звука нет — хотя он есть. Так волна заполняет полосу
        там, где звук реально присутствует."""
        s = self.samples
        if not s:
            self.disp_samples = []
            self.disp_l = []
            self.disp_r = []
            self._norm = 1.0
            return
        ordered = sorted(s)
        ref = ordered[min(len(ordered) - 1, int(len(ordered) * 0.97))]
        ref = max(ref, 0.06)   # пол: чтобы тишина/фон не раздувались на всю высоту
        norm = 1.0 / ref
        self._norm = norm
        self.disp_samples = [min(1.0, (v * norm) ** 0.62) for v in s]
        # Каналы нормируем тем же эталоном/кривой, что и общую волну — иначе шкалы
        # L/R «жили» бы в своём масштабе и не сравнивались между собой.
        self.disp_l = [min(1.0, (v * norm) ** 0.62) for v in self.l_samples]
        self.disp_r = [min(1.0, (v * norm) ** 0.62) for v in self.r_samples]

    def level_at(self, t):
        """Перцептивный уровень (0..1) на позиции t — кормит индикатор громкости."""
        ds = self.disp_samples
        if not ds or self.duration <= 0:
            return 0.0
        idx = int(t / self.duration * len(ds))
        idx = max(0, min(len(ds) - 1, idx))
        return ds[idx]

    def level_at_lr(self, t):
        """Перцептивные уровни (L, R) на позиции t — для честного стерео-индикатора.
        Если поканальных данных нет (старый путь/моно) — оба равны общему уровню."""
        if self.duration <= 0:
            return 0.0, 0.0
        dl, dr = self.disp_l, self.disp_r
        if not dl or not dr:
            lvl = self.level_at(t)
            return lvl, lvl
        il = max(0, min(len(dl) - 1, int(t / self.duration * len(dl))))
        ir = max(0, min(len(dr) - 1, int(t / self.duration * len(dr))))
        return dl[il], dr[ir]

    def set_data(self, samples, duration, samples_l=None, samples_r=None):
        self.loading_text = None
        self._anim_timer.stop()
        self.samples = samples
        self.l_samples = samples_l or []
        self.r_samples = samples_r or []
        self._compute_display_samples()
        self.duration = max(0.0, float(duration))
        if self.duration <= 0:
            self.in_s = 0.0; self.out_s = 0.0
        else:
            if not (0.0 <= self.in_s < self.out_s <= self.duration):
                self.in_s = 0.0; self.out_s = max(0.001, self.duration)
        self.zoom = 1.0
        self.view_offset = 0.0
        self.viewChanged.emit(self.view_offset, max(0.001, self.duration / self.zoom))
        self.update()

    def set_partial_data(self, samples, seg_in, seg_out, duration, samples_l=None, samples_r=None):
        """Быстрый предпросмотр: заполняет реальными данными только отрезок
        seg_in..seg_out (обычно текущее выделение IN/OUT), остальная шкала
        остаётся пустой (тишина) до прихода полной волны через set_data —
        так пользователь сразу видит/слышит нужный кусок при смене дорожки,
        не дожидаясь полного прохода по всему файлу. Зум/окно обзора не трогаем."""
        duration = max(0.0, float(duration))
        if duration <= 0 or not samples:
            return
        samples_l = samples_l or []
        samples_r = samples_r or []

        # Нормируем/приводим к перцептивной кривой ТОЛЬКО по самому отрезку —
        # иначе 97-й перцентиль утонул бы в окружающих нулях-заглушках.
        ordered = sorted(samples)
        ref = ordered[min(len(ordered) - 1, int(len(ordered) * 0.97))]
        ref = max(ref, 0.06)
        norm = 1.0 / ref
        disp_seg = [min(1.0, (v * norm) ** 0.62) for v in samples]
        disp_seg_l = [min(1.0, (v * norm) ** 0.62) for v in samples_l]
        disp_seg_r = [min(1.0, (v * norm) ** 0.62) for v in samples_r]

        n = 8000   # тот же таргет, что и у полной волны (target_samples в AudioWaveformLoader)
        full = [0.0] * n
        full_l = [0.0] * n
        full_r = [0.0] * n
        seg_in = max(0.0, min(seg_in, duration))
        seg_out = max(seg_in, min(seg_out, duration))
        i0 = min(n - 1, int((seg_in / duration) * n))
        i1 = max(i0 + 1, min(n, int((seg_out / duration) * n)))
        seg_n = i1 - i0
        src_n = len(disp_seg)
        for k in range(seg_n):
            src_idx = min(src_n - 1, int(k / seg_n * src_n))
            full[i0 + k] = disp_seg[src_idx]
            if disp_seg_l:
                full_l[i0 + k] = disp_seg_l[min(len(disp_seg_l) - 1, src_idx)]
            if disp_seg_r:
                full_r[i0 + k] = disp_seg_r[min(len(disp_seg_r) - 1, src_idx)]

        self.loading_text = None
        self._anim_timer.stop()
        self.samples = full
        self.disp_samples = full
        self.l_samples = full_l
        self.disp_l = full_l
        self.r_samples = full_r
        self.disp_r = full_r
        self.duration = duration
        if not (0.0 <= self.in_s < self.out_s <= self.duration):
            self.in_s = 0.0; self.out_s = max(0.001, self.duration)
        self.update()

    def reset_markers(self):
        """Полный сброс волны к «пустому» состоянию при загрузке НОВОГО файла:
        границы IN/OUT (красная/зелёная полоски), плейхед, зум и окно обзора.
        Без этого при добавлении нового файла маркеры предыдущего оставались
        на месте (старые in/out + старая длительность задавали их пиксельную
        позицию), пока не догрузится новая волна — выглядело как «не сбросились»."""
        self.samples = []
        self.disp_samples = []
        self.l_samples = []
        self.r_samples = []
        self.disp_l = []
        self.disp_r = []
        self.duration = 0.0
        self.in_s = 0.0
        self.out_s = 0.0
        self.playhead_s = 0.0
        self.zoom = 1.0
        self.view_offset = 0.0
        self._cache = None
        self._cache_key = None
        self.update()

    def prime_duration(self, duration):
        """Сообщает волне длительность файла РАНЬШЕ, чем достроятся семплы.
        Длительность уже известна из ffprobe/контейнера сразу при загрузке файла,
        но до этого метода self.duration оставалась 0.0 (см. reset_markers) —
        из-за этого клик по полосе волны во время «Загрузка волны…»/«Создание
        превью…» ВСЕГДА сикал в начало (mousePressEvent считал волну неготовой),
        хотя сам плеер уже мог играть с любой позиции. Семплы/loading_text не
        трогаем — визуально полоса остаётся в состоянии загрузки."""
        d = max(0.0, float(duration or 0.0))
        if d <= 0:
            return
        self.duration = d
        if not (0.0 <= self.in_s < self.out_s <= self.duration):
            self.in_s = 0.0
            self.out_s = self.duration
        self.update()

    def set_in_out(self, in_s, out_s, keep_view=False):
        self.in_s = max(0.0, min(in_s, self.duration))
        self.out_s = max(0.0, min(out_s, self.duration))
        if self.out_s <= self.in_s:
            self.out_s = min(self.duration, self.in_s + 0.001)
        # keep_view=True: не дёргаем окно обзора при ручной обрезке (иначе при
        # зуме виджет каждый раз перецентрируется на выделение).
        if not keep_view:
            self.ensure_view_contains(self.in_s, self.out_s)
        self.selectionChanged.emit(self.in_s, self.out_s)
        self.update()

    def set_playhead(self, t):
        self.playhead_s = max(0.0, min(t, self.duration))
        self.update()

    def ensure_view_contains(self, a, b):
        if self.duration <= 0:
            return
        visible = max(0.001, self.duration / self.zoom)
        sel_center = (a + b) / 2.0
        left = self.view_offset; right = self.view_offset + visible
        if a < left or b > right:
            new_left = sel_center - visible / 2.0
            new_left = max(0.0, min(new_left, max(0.0, self.duration - visible)))
            self.view_offset = new_left
            self.viewChanged.emit(self.view_offset, visible)

    def _draw_static(self, painter, w, h):
        """Draw all static elements (everything except playhead and hover cursor)."""
        mid = h / 2.0

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(30, 30, 46))   # base
        grad.setColorAt(1.0, QColor(24, 24, 37))   # mantle
        painter.fillRect(0, 0, w, h, QBrush(grad))

        painter.setPen(QPen(QColor(69, 71, 90), 1))  # surface1
        painter.drawLine(0, int(mid), w, int(mid))

        if self.loading_text:
            dots = "." * self._anim_dots
            txt = f"{self.loading_text}{dots}"
            painter.setPen(QPen(QColor(137, 180, 250)))  # blue
            font = painter.font()
            font.setPointSize(10)
            font.setFamily("Segoe UI" if os.name == 'nt' else "SF Pro Display")
            painter.setFont(font)
            painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, txt)
            return

        visible_duration = max(0.001, self.duration / self.zoom)

        def time_to_x(t):
            rel = (t - self.view_offset) / visible_duration
            return int(rel * w)

        if self.disp_samples and self.duration > 0:
            n = len(self.disp_samples)
            scale_bg = (h / 2) * 0.86
            for i in range(0, w):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                if t > self.duration:
                    break  # за пределами клипа (при отдалении zoom<1) — пусто
                idx = int((t / self.duration) * n)
                idx = max(0, min(n - 1, idx))
                val = self.disp_samples[idx]
                v = val * 0.92
                y1 = int(mid - v * scale_bg)
                y2 = int(mid + v * scale_bg)
                alpha = int(110 + val * 70)
                painter.setPen(QPen(QColor(108, 117, 161, alpha)))  # muted blue/overlay
                painter.drawLine(i, y1, i, y2)
        else:
            if self.duration > 0:
                painter.setPen(QPen(QColor(C["text3"])))
                font = painter.font(); font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Нет аудио данных")
            else:
                painter.setPen(QPen(QColor(C["text3"])))
                font = painter.font(); font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                                 "Перетащите видео или аудио файл сюда")

        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.drawLine(0, 0, w, 0)
        painter.drawLine(0, h - 1, w, h - 1)

        if self.duration <= 0:
            return

        x_in  = time_to_x(self.in_s)
        x_out = time_to_x(self.out_s)
        if x_out < x_in:
            x_in, x_out = x_out, x_in

        sel_w = max(1, x_out - x_in)
        painter.setBrush(QBrush(QColor(137, 180, 250, 28)))  # blue selection wash
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(x_in, 0, sel_w, h)

        if self.disp_samples and self.duration > 0:
            n = len(self.disp_samples)
            scale_sel = (h / 2) * 0.92
            left_i = max(0, x_in); right_i = min(w - 1, x_out)
            for i in range(left_i, right_i + 1):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                idx = int((t / self.duration) * n)
                if idx >= n:
                    break
                val = self.disp_samples[idx]
                v = val * 1.04
                y1 = int(mid - v * scale_sel)
                y2 = int(mid + v * scale_sel)
                alpha = int(180 + val * 60)
                painter.setPen(QPen(QColor(137, 180, 250, alpha)))  # blue
                painter.drawLine(i, y1, i, y2)

        painter.setPen(QPen(QColor(C["red"]), 2))
        painter.drawLine(x_in, 0, x_in, h)
        painter.setPen(QPen(QColor(C["green"]), 2))
        painter.drawLine(x_out, 0, x_out, h)

        handle_r = max(5, int(h * 0.055))
        painter.setBrush(QBrush(QColor(C["red"])))
        painter.setPen(QPen(QColor(C["bg"]), 1))
        painter.drawEllipse(QPoint(x_in, int(mid)), handle_r, handle_r)
        painter.setBrush(QBrush(QColor(C["green"])))
        painter.setPen(QPen(QColor(C["bg"]), 1))
        painter.drawEllipse(QPoint(x_out, int(mid)), handle_r, handle_r)

        painter.setPen(QPen(QColor(C["text"])))
        font = painter.font(); font.setPointSize(6); font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        for label, x_pos, col in [("I", x_in, C["red"]), ("O", x_out, C["green"])]:
            lw = fm.horizontalAdvance(label)
            painter.setPen(QPen(QColor(col)))
            painter.drawText(x_pos - lw // 2, int(mid) + fm.ascent() // 2, label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width(); h = self.height()

        # Cache key covers everything that affects static drawing.
        # Playhead and hover cursor are drawn dynamically on top.
        cache_key = (w, h, id(self.samples), len(self.samples),
                     self.duration, self.zoom, self.view_offset,
                     self.in_s, self.out_s, self.loading_text, self._anim_dots)
        if self._cache is None or self._cache_key != cache_key:
            self._cache = QPixmap(w, h)
            self._cache_key = cache_key
            cp = QPainter(self._cache)
            cp.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_static(cp, w, h)
            cp.end()

        painter.drawPixmap(0, 0, self._cache)

        if self.loading_text or self.duration <= 0:
            return

        visible_duration = max(0.001, self.duration / self.zoom)

        def time_to_x(t):
            rel = (t - self.view_offset) / visible_duration
            return int(rel * w)

        # Playhead
        if 0.0 <= self.playhead_s <= self.duration:
            vis_end = self.view_offset + visible_duration
            if self.view_offset <= self.playhead_s <= vis_end:
                x_ph = time_to_x(self.playhead_s)
                painter.setPen(QPen(QColor(C["playhead"]), 2, Qt.PenStyle.SolidLine))
                painter.drawLine(x_ph, 0, x_ph, h)
                path = QPainterPath()
                path.moveTo(x_ph - 5, 0)
                path.lineTo(x_ph + 5, 0)
                path.lineTo(x_ph, 8)
                path.closeSubpath()
                painter.setBrush(QBrush(QColor(C["playhead"])))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)

        # Hover cursor
        if self.hover_x is not None:
            hx = int(self.hover_x)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DotLine))
            painter.drawLine(hx, 0, hx, h)

    # ── Mouse events ───────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        # ПКМ — не сик/перетаскивание, а контекстное меню обрезки (его поднимает
        # customContextMenuRequested). Иначе правый клик дёргал бы плейхед.
        if ev.button() == Qt.MouseButton.RightButton:
            ev.ignore(); return
        # Забираем клавиатурный фокус НА СЕБЯ: метод переопределён и не зовёт
        # super().mousePressEvent(), поэтому штатный перехват фокуса по ClickFocus
        # не срабатывает, и фокус оставался на нативной видео-поверхности
        # (исключена из WidgetWithChildrenShortcut) → Ctrl+Z/Ctrl+Y после
        # перетаскивания полоски не доходили до undo/redo.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        try:
            x = ev.position().x()
        except Exception:
            x = ev.x()
        if self.duration <= 0:
            self.seekRequested.emit(0.0); return
        w = max(1, self.width()); x = max(0, min(w, x))

        def time_to_x_local(t):
            visible = max(0.001, self.duration / self.zoom)
            rel = (t - self.view_offset) / visible
            return int(rel * w)

        x_in  = time_to_x_local(self.in_s)
        x_out = time_to_x_local(self.out_s)
        threshold = 8
        modifiers = QApplication.keyboardModifiers()
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            if abs(x - x_in) <= threshold:
                self.interactionStarted.emit()
                self.dragging = 'in'; self.drag_start_x = x; self.orig_in = self.in_s
                self.show_tooltip_for_pos(ev); return
            if abs(x - x_out) <= threshold:
                self.interactionStarted.emit()
                self.dragging = 'out'; self.drag_start_x = x; self.orig_out = self.out_s
                self.show_tooltip_for_pos(ev); return
            left = min(x_in, x_out); right = max(x_in, x_out)
            if (right - left) > (threshold * 3) and (left + threshold < x < right - threshold):
                self.interactionStarted.emit()
                self.dragging = 'maybe_move'; self.drag_start_x = x
                self.orig_in = self.in_s; self.orig_out = self.out_s
                self.show_tooltip_for_pos(ev); return
        rel = x / w
        t = self.view_offset + rel * max(0.001, self.duration / self.zoom)
        t = max(0.0, min(self.duration, t))
        self.seekRequested.emit(t)

    def mouseMoveEvent(self, ev):
        try:
            mx = ev.position().x(); gpos = ev.globalPosition()
        except Exception:
            mx = ev.x(); gpos = ev.globalPos()
        self.hover_x = mx
        if self.dragging and self.duration > 0:
            w = max(1, self.width()); mx = max(0, min(w, mx))
            if self.dragging == 'maybe_move':
                if abs(mx - (self.drag_start_x if self.drag_start_x is not None else mx)) < 6:
                    self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
                    self.update(); return
                else:
                    self.dragging = 'move'; self.orig_in = self.in_s; self.orig_out = self.out_s
            visible = max(0.001, self.duration / self.zoom)
            if self.dragging == 'in':
                t = self.view_offset + (mx / w) * visible
                new_in = max(0.0, min(t, self.out_s - (1.0 / 1000.0)))
                self.in_s = new_in
                self.inSetRequested.emit(self.in_s); self.selectionChanged.emit(self.in_s, self.out_s)
            elif self.dragging == 'out':
                t = self.view_offset + (mx / w) * visible
                new_out = min(self.duration, max(t, self.in_s + (1.0 / 1000.0)))
                self.out_s = new_out
                self.outSetRequested.emit(self.out_s); self.selectionChanged.emit(self.in_s, self.out_s)
            elif self.dragging == 'move':
                start_t = self.view_offset + ((self.drag_start_x if self.drag_start_x is not None else mx) / w) * visible
                cur_t   = self.view_offset + (mx / w) * visible
                shift = cur_t - start_t
                new_in = self.orig_in + shift; new_out = self.orig_out + shift
                if new_in < 0:
                    shift_c = -new_in; new_in += shift_c; new_out += shift_c
                if new_out > self.duration:
                    shift_c = new_out - self.duration; new_in -= shift_c; new_out -= shift_c
                self.in_s = new_in; self.out_s = new_out
                self.inSetRequested.emit(self.in_s)
                self.outSetRequested.emit(self.out_s)
                self.selectionChanged.emit(self.in_s, self.out_s)
            self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
            self.update(); return
        self.update()

    def mouseReleaseEvent(self, ev):
        try:
            rx = ev.position().x()
        except Exception:
            rx = ev.x()
        if self.dragging == 'maybe_move':
            w = max(1, self.width()); rx = max(0, min(w, rx))
            visible = max(0.001, self.duration / self.zoom)
            t = self.view_offset + (rx / w) * visible
            t = max(0.0, min(self.duration, t))
            self.playSeekRequested.emit(t)
        self.dragging = None; self.drag_start_x = None
        self.orig_in = 0.0; self.orig_out = 0.0
        QToolTip.hideText(); self.tooltip_visible = False

    def leaveEvent(self, ev):
        self.hover_x = None; QToolTip.hideText(); self.tooltip_visible = False; self.update()

    def hover_time_from_x(self, x):
        w = max(1, self.width())
        rel = max(0.0, min(1.0, x / w))
        visible = max(0.001, self.duration / self.zoom)
        return self.view_offset + rel * visible

    def show_tooltip_for_pos(self, ev):
        try:
            gpos = ev.globalPosition(); x = ev.position().x()
        except Exception:
            gpos = ev.globalPos(); x = ev.x()
        t = self.hover_time_from_x(x)
        self.show_tooltip_at_global_pos(gpos, t)

    def show_tooltip_at_global_pos(self, gpos, t):
        try:
            if hasattr(gpos, 'toPoint'):
                gp = gpos.toPoint()
            elif hasattr(gpos, 'x'):
                gp = QPoint(int(gpos.x()), int(gpos.y()))
            else:
                gp = gpos
        except Exception:
            gp = None
        txt = s_to_time(t)
        if gp:
            QToolTip.showText(gp, txt, self); self.tooltip_visible = True
        else:
            QToolTip.hideText(); self.tooltip_visible = False

    def wheelEvent(self, event):
        modifiers = QApplication.keyboardModifiers()
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
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


class _SubtitleTimeline(QWidget):
    """Таймлайн реплик субтитров для SubtitleCreatorDialog: линейка с засечками
    времени, плейхед и дорожка с перетаскиваемыми/растягиваемыми блоками — по
    одному на реплику. Обобщение единственной пары IN/OUT из WaveformWidget
    (coord-математика/hit-testing/Ctrl+wheel-зум скопированы оттуда) на N
    произвольных интервалов с ограничением о несоседних столкновениях."""

    seekRequested       = pyqtSignal(float)
    cueChanged          = pyqtSignal(int, float, float)   # index, start, end
    cueSelected         = pyqtSignal(int)
    viewChanged         = pyqtSignal(float, float)        # offset, visible_duration
    interactionStarted  = pyqtSignal()   # начало drag'а блока — снимок для undo

    RULER_H = 20
    _EDGE_TOL = 8
    _ROW_H = 26
    _ROW_GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0     # длина ВИДИМОГО диапазона (не всего видео)
        self.range_start = 0.0  # начало диапазона (абсолютное время исходника)
        self.cues = []          # [(start, end)] — только тайминг, без текста/стиля
        self.selected = -1
        self.playhead_s = 0.0
        self.zoom = 1.0
        self.view_offset = 0.0
        self.setMinimumHeight(self.RULER_H + self._ROW_H + 2 * self._ROW_GAP)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.dragging = None       # None | 'start' | 'end' | 'move' | 'maybe_move'
        self.drag_index = -1
        self.drag_start_x = None
        self.orig_start = 0.0
        self.orig_end = 0.0

    # ── Данные ──────────────────────────────────────────────────────────────
    def set_cues(self, cues):
        self.cues = [(float(s), float(e)) for s, e in cues]
        if self.selected >= len(self.cues):
            self.selected = len(self.cues) - 1
        self.update()

    def set_duration(self, dur):
        self.duration = max(0.0, float(dur))
        self.update()

    def set_range(self, start_s, end_s):
        """Ограничивает таймлайн диапазоном [start_s, end_s] (абсолютное время
        исходника) — тем самым, что выделен в Монтаже, а не всем видео."""
        self.range_start = max(0.0, float(start_s))
        self.duration = max(0.001, float(end_s) - self.range_start)
        self.zoom = 1.0
        self.view_offset = self.range_start
        self.update()

    def set_playhead(self, t):
        self.playhead_s = max(0.0, float(t))
        self.update()

    def set_selected(self, idx):
        self.selected = idx
        self.update()

    # ── Коорд. математика (как в WaveformWidget: view_offset/zoom) ──────────
    def _visible(self):
        return max(0.001, self.duration / self.zoom) if self.duration > 0 else 1.0

    def time_to_x(self, t):
        w = max(1, self.width())
        return (t - self.view_offset) / self._visible() * w

    def x_to_time(self, x):
        w = max(1, self.width())
        return self.view_offset + (x / w) * self._visible()

    # ── Рисование ────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C['surface3']))
        self._draw_ruler(p)
        self._draw_cues(p)
        self._draw_playhead(p)
        p.end()

    @staticmethod
    def _nice_tick_step(px_per_s):
        for c in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600):
            if c * px_per_s >= 70:
                return c
        return 3600

    def _draw_ruler(self, p):
        w = max(1, self.width())
        p.fillRect(0, 0, w, self.RULER_H, QColor(C['surface2']))
        if self.duration <= 0:
            return
        visible = self._visible()
        step = self._nice_tick_step(w / visible)
        p.setPen(QPen(QColor(C['text3'])))
        t = math.floor(self.view_offset / step) * step
        end_t = self.view_offset + visible + step
        while t <= end_t:
            x = self.time_to_x(t)
            if 0 <= x <= w:
                p.drawLine(int(x), self.RULER_H - 6, int(x), self.RULER_H)
                p.drawText(int(x) + 3, self.RULER_H - 7, s_to_time(max(0.0, t))[:8])
            t += step

    def _draw_cues(self, p):
        y = self.RULER_H + self._ROW_GAP
        w = max(1, self.width())
        for i, (s, e) in enumerate(self.cues):
            x0 = self.time_to_x(s); x1 = self.time_to_x(e)
            if x1 < 0 or x0 > w:
                continue
            r = QRect(int(x0), y, max(2, int(x1 - x0)), self._ROW_H)
            selected = (i == self.selected)
            bg = QColor(C['accent'] if selected else C['wave_sel'])
            bg.setAlpha(230 if selected else 160)
            p.fillRect(r, bg)
            p.setPen(QPen(QColor(C['accent'] if selected else C['border2'])))
            p.drawRect(r)

    def _draw_playhead(self, p):
        if self.duration <= 0:
            return
        x = self.time_to_x(self.playhead_s)
        if 0 <= x <= self.width():
            pen = QPen(QColor(C['playhead'])); pen.setWidth(2)
            p.setPen(pen)
            p.drawLine(int(x), 0, int(x), self.height())

    # ── Hit-testing (по образцу WaveformWidget.mousePressEvent) ─────────────
    def _row_bounds(self):
        top = self.RULER_H + self._ROW_GAP
        return top, top + self._ROW_H

    def _hit_test(self, x, y=None):
        # Блоки реплик рисуются ТОЛЬКО в полосе дорожки (см. _draw_cues) — выше
        # неё линейка времени, ниже пустой остаток фиксированной высоты виджета.
        # Раньше hit-test смотрел только на X, и клик ВЫШЕ/НИЖЕ дорожки (по тем
        # же X-координатам, что и реплика) тоже считался попаданием в блок —
        # кликнуть «просто перейти на этот момент» там было нельзя, вместо
        # этого всегда предлагалось перетащить реплику.
        if y is not None:
            row_top, row_bottom = self._row_bounds()
            if y < row_top or y > row_bottom:
                return -1, None
        for i, (s, e) in enumerate(self.cues):
            x0 = self.time_to_x(s); x1 = self.time_to_x(e)
            if abs(x - x0) <= self._EDGE_TOL:
                return i, 'start'
            if abs(x - x1) <= self._EDGE_TOL:
                return i, 'end'
            if x0 + self._EDGE_TOL < x < x1 - self._EDGE_TOL:
                return i, 'move'
        return -1, None

    def _neighbor_bounds(self, i):
        lo = self.range_start; hi = self.range_start + self.duration
        if i > 0:
            lo = self.cues[i - 1][1]
        if i < len(self.cues) - 1:
            hi = self.cues[i + 1][0]
        return lo, hi

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            ev.ignore(); return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        x = ev.position().x(); y = ev.position().y()
        if self.duration <= 0:
            return
        idx, mode = self._hit_test(x, y)
        if idx >= 0:
            self.selected = idx
            self.cueSelected.emit(idx)
            self.orig_start, self.orig_end = self.cues[idx]
            self.drag_index = idx
            self.drag_start_x = x
            self.dragging = 'maybe_move' if mode == 'move' else mode
            self.interactionStarted.emit()
            self.update()
            return
        t = max(self.range_start, min(self.range_start + self.duration, self.x_to_time(x)))
        self.seekRequested.emit(t)

    def mouseMoveEvent(self, ev):
        x = ev.position().x(); y = ev.position().y()
        if self.dragging and self.drag_index >= 0:
            if self.dragging == 'maybe_move':
                if abs(x - (self.drag_start_x or x)) < 6:
                    return
                self.dragging = 'move'
            i = self.drag_index
            lo, hi = self._neighbor_bounds(i)
            s0, e0 = self.cues[i]
            if self.dragging == 'start':
                t = max(lo, min(self.x_to_time(x), e0 - 0.05))
                self.cues[i] = (t, e0)
            elif self.dragging == 'end':
                t = min(hi, max(self.x_to_time(x), s0 + 0.05))
                self.cues[i] = (s0, t)
            elif self.dragging == 'move':
                shift = self.x_to_time(x) - self.x_to_time(self.drag_start_x)
                ns = self.orig_start + shift; ne = self.orig_end + shift
                if ns < lo:
                    d = lo - ns; ns += d; ne += d
                if ne > hi:
                    d = ne - hi; ns -= d; ne -= d
                self.cues[i] = (ns, ne)
            s, e = self.cues[i]
            self.cueChanged.emit(i, s, e)
            self.update()
            return
        idx, mode = self._hit_test(x, y)
        cur = {'start': Qt.CursorShape.SizeHorCursor, 'end': Qt.CursorShape.SizeHorCursor,
               'move': Qt.CursorShape.SizeAllCursor}.get(mode)
        if cur is not None:
            self.setCursor(cur)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, ev):
        self.dragging = None; self.drag_index = -1; self.drag_start_x = None

    def leaveEvent(self, ev):
        self.unsetCursor()

    # ── Зум (Ctrl+колесо, как в WaveformWidget) ──────────────────────────────
    def wheelEvent(self, event):
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
            event.ignore(); return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        cursor_x = event.position().x()
        w = max(1, self.width())
        t_at_cursor = self.view_offset + (cursor_x / w) * self._visible()
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        self.set_zoom(self.zoom * factor, anchor_t=t_at_cursor, anchor_frac=cursor_x / w)
        event.accept()

    def set_zoom(self, zoom, anchor_t=None, anchor_frac=0.5):
        self.zoom = max(0.25, min(zoom, 200.0))
        visible_after = self._visible()
        if anchor_t is not None:
            new_view = anchor_t - anchor_frac * visible_after
        else:
            new_view = self.view_offset
        lo = self.range_start
        new_view = max(lo, min(new_view, lo + max(0.0, self.duration - visible_after)))
        self.view_offset = new_view
        self.viewChanged.emit(self.view_offset, visible_after)
        self.update()

    def set_view_offset(self, offset):
        visible = self._visible()
        lo = self.range_start
        self.view_offset = max(lo, min(offset, lo + max(0.0, self.duration - visible)))
        self.viewChanged.emit(self.view_offset, visible)
        self.update()


class VolumeSlider(QSlider):
    """Ползунок громкости: колёсико над ним всегда меняет громкость шагом 5
    (как и над значком динамика), независимо от глобальной опции «колесо меняет
    значения». Помечен свойством wheelAlways, чтобы WheelBlocker его не глушил."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setProperty("wheelAlways", True)

    def wheelEvent(self, ev):
        step = 5 if ev.angleDelta().y() > 0 else -5
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + step)))
        ev.accept()


class VolumeLabel(QLabel):
    """Значок динамика: прокрутка колёсиком над ним меняет громкость.
    slider_getter — функция, возвращающая связанный QSlider громкости."""

    def __init__(self, slider_getter, parent=None):
        super().__init__(parent)
        self._slider_getter = slider_getter
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Громкость — прокрутите колёсиком над динамиком")
        self.update_glyph(100)

    def update_glyph(self, vol):
        name = ('fa5s.volume-mute' if vol <= 0
                else ('fa5s.volume-down' if vol < 55 else 'fa5s.volume-up'))
        self.setPixmap(get_icon_pixmap(name, 18))

    def wheelEvent(self, ev):
        sl = self._slider_getter() if self._slider_getter else None
        if sl is None:
            super().wheelEvent(ev)
            return
        step = 5 if ev.angleDelta().y() > 0 else -5
        sl.setValue(max(sl.minimum(), min(sl.maximum(), sl.value() + step)))
        ev.accept()


# ─── Info Card ────────────────────────────────────────────────────────────────
class InfoCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self.setStyleSheet(f"""
            #InfoCard {{
                background: {C['surface2']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        # Заголовок не должен распирать карточку/панель по своей длине.
        _sp = title_lbl.sizePolicy(); _sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        title_lbl.setSizePolicy(_sp)
        layout.addWidget(title_lbl)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        layout.addLayout(self._body)

    def add_row(self, label, value_attr):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        val = QLabel("—")
        val.setStyleSheet(f"color: {C['text']}; font-size: 12px; font-weight: 500;")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        self._body.addLayout(row)
        setattr(self, value_attr, val)
        return val


# ─── Audio level meter (VU) ────────────────────────────────────────────────────
class AudioMeter(QWidget):
    """Стерео-индикатор уровня звука: две вертикальные шкалы (зелёный→жёлтый→
    красный) с пик-маркерами и плавным спадом. Уровни 0..1 подаёт плеер во время
    воспроизведения (берутся из аудиоволны на позиции плейхеда)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(56)
        self.setMaximumWidth(96)
        self.setMinimumHeight(120)
        self._l = 0.0
        self._r = 0.0
        self._pk_l = 0.0
        self._pk_r = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._decay)
        self._timer.start()

    def set_levels(self, l, r=None):
        if r is None:
            r = l
        self._l = max(0.0, min(1.0, float(l)))
        self._r = max(0.0, min(1.0, float(r)))
        if self._l > self._pk_l: self._pk_l = self._l
        if self._r > self._pk_r: self._pk_r = self._r
        self.update()

    def reset(self):
        self._l = self._r = self._pk_l = self._pk_r = 0.0
        self.update()

    def _decay(self):
        changed = False
        for a, d in (('_l', 0.08), ('_r', 0.08), ('_pk_l', 0.02), ('_pk_r', 0.02)):
            v = getattr(self, a)
            if v > 0:
                setattr(self, a, max(0.0, v - d)); changed = True
        if changed:
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        w = self.width(); h = self.height()
        p.fillRect(0, 0, w, h, QColor(C["bg"]))
        m_top, m_bot = 10, 16
        bar_h = max(1, h - m_top - m_bot)
        gap = 6
        bw = max(6, int((w - gap * 3) / 2))
        data = [(self._l, self._pk_l, "L"), (self._r, self._pk_r, "R")]
        for i, (lvl, pk, label) in enumerate(data):
            x = gap + i * (bw + gap)
            y = m_top
            grad = QLinearGradient(0, y, 0, y + bar_h)
            grad.setColorAt(0.0, QColor(C["red"]))
            grad.setColorAt(0.45, QColor(C["yellow"]))
            grad.setColorAt(1.0, QColor(C["green"]))
            # Тусклый «трек» во всю высоту
            p.setOpacity(0.16); p.fillRect(x, y, bw, bar_h, QBrush(grad)); p.setOpacity(1.0)
            # Яркая заполненная часть снизу до текущего уровня
            fill_h = int(bar_h * lvl)
            if fill_h > 0:
                p.setClipRect(x, y + bar_h - fill_h, bw, fill_h)
                p.fillRect(x, y, bw, bar_h, QBrush(grad))
                p.setClipping(False)
            # Пик-маркер
            if pk > 0:
                py = y + bar_h - int(bar_h * pk)
                p.setPen(QPen(QColor(C["text"]), 1))
                p.drawLine(x, py, x + bw, py)
            # Подпись канала
            p.setPen(QPen(QColor(C["text3"])))
            f = p.font(); f.setPointSize(8); p.setFont(f)
            p.drawText(QRect(x, h - m_bot + 1, bw, m_bot - 1),
                       Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class SubtitleOverlay(QWidget):
    """Оверлей субтитров в стиле VLC/PotPlayer: белый жирный текст с чёрной
    обводкой, без подложки.

    ВАЖНО: QVideoWidget рендерит видео через нативную поверхность (RHI), поэтому
    обычный дочерний/соседний виджет рисуется ПОД видео и не виден. Чтобы текст
    стабильно был поверх кадра, оверлей сделан отдельным БЕСРАМОЧНЫМ полупрозрачным
    окном-«насадкой» со сквозным вводом, которое подгоняется под экранную область
    видео (см. EditTab._position_overlay)."""

    def __init__(self, parent=None):
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowTransparentForInput)
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._text = ""
        self._px = 28
        self._image = None       # кадр субтитров от libass (QImage) — приоритетнее текста
        self._image_pos = (0, 0) # позиция левого верхнего угла картинки в оверлее

    def place_over(self, widget):
        """Подгоняет окно-оверлей под экранную область целевого виджета (видео)."""
        if widget is None or not widget.isVisible():
            self.hide()
            return
        tl = widget.mapToGlobal(QPoint(0, 0))
        w, h = widget.width(), widget.height()
        if w <= 1 or h <= 1:
            self.hide()
            return
        self.setGeometry(tl.x(), tl.y(), w, h)
        self.set_video_height(h)

    def set_text(self, text):
        text = text or ""
        if text != self._text:
            self._text = text
            self.update()

    def set_image(self, qimg, x=0, y=0):
        """Кадр субтитров от libass (обрезанный QImage) с позицией (x,y) в кадре,
        или None."""
        self._image = qimg
        self._image_pos = (int(x), int(y))
        self.update()

    # Единый API субтитров (совместим с VideoCanvas, см. EditTab._update_subtitle).
    def set_subtitle_image(self, qimg, x=0, y=0):
        self.set_image(qimg, x, y)

    def set_subtitle_text(self, text):
        self.set_image(None)
        self.set_text(text)

    def clear_subtitle(self):
        self._text = ""
        self.set_image(None)

    def subtitle_area_size(self):
        return self.width(), self.height()

    def set_video_height(self, h):
        px = max(15, int(h * 0.052))   # ~5% высоты кадра, как в плеерах
        if px != self._px:
            self._px = px
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        _paint_subtitle(p, self.rect(), self._text, self._px,
                        self._image, self._image_pos)
        p.end()


class VideoCanvas(QWidget):
    """Холст видео: сам рисует кадры (через QVideoSink + QPainter) и накладывает
    субтитры ПРЯМО В КАДР, как VLC. В отличие от QVideoWidget не использует
    нативную RHI-поверхность, поэтому субтитры корректно обрезаются по видео и
    перекрываются любыми панелями/окнами сверху. Кадр вписывается с сохранением
    пропорций (letterbox). Совместим по API субтитров с SubtitleOverlay.

    Чуть дороже QVideoWidget (кадр конвертируется в QImage на ЦП), поэтому в
    настройках можно вернуть старый метод (QVideoWidget + окно-оверлей)."""

    # Кадр пришёл с PTS за границей OUT (см. set_play_bound) — плеер надо ставить
    # на паузу ДО показа этого кадра (защита от проскока правой границы).
    boundaryReached = pyqtSignal()
    # Кадрирование видео завершено кнопкой «Применить»/«Отмена» на холсте (как в
    # «Редактировании фото») — вкладка снимает чек с кнопки «Кадрировать».
    cropApplied = pyqtSignal()
    cropCancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._bound_us = None          # граница OUT (µs) для блокировки кадров
        self._frame_img = None
        self._text = ""
        self._image = None
        self._image_pos = (0, 0)
        self._bg = QColor(C["bg"])
        # Текст-заглушка, когда у файла нет видеоряда (редактируем чистое аудио).
        self._audio_only_msg = ""
        # Зум/панорама превью (Ctrl+колесо приближает, ЛКМ-перетаскивание двигает).
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_last = None
        # Кадрирование видео — РОВНО как в «Редактировании фото» (InpaintCanvas):
        # рамку с 8 ручками (углы/стороны) и «ручкой-перемещением» правят прямо на
        # холсте, плавающие кнопки «Применить»/«Отмена» всплывают у рамки. При
        # «Обрезать» итоговое видео кадрируется по рамке (и «Сохранить кадр» тоже).
        # Храним нормализованно (QRectF 0..1 от кадра) — не зависит от разрешения
        # (важно для превью-прокси и crop=… через ffmpeg по iw/ih).
        self._crop_mode = False
        self._crop_norm = None          # QRectF 0..1 или None
        self._crop_drag = None          # активная ручка: tl/tr/bl/br/t/b/l/r/move
        self._crop_anchor = None        # позиция мыши (norm) на момент захвата
        self._crop_start_rect = None    # рамка (QRectF) на момент захвата
        # Во время активной перемотки (протяжка слайдера/волны) кадры сыпятся
        # часто и ненадолго — плавное (билинейное) масштабирование каждого из них
        # даёт заметную лишнюю нагрузку без пользы (кадр всё равно тут же сменится).
        # На это время рисуем ближайшим соседом (быстрее), а как только перемотка
        # утихла — возвращаем сглаживание для финального кадра. См. set_scrub_active.
        self._scrub_active = False
        # То же и во время ВОСПРОИЗВЕДЕНИЯ: кадр сменится через ~16 мс, сглаживание
        # на нём не разглядеть, зато билинейный ресайз каждого кадра зря грузит ЦП
        # (главный поток и так занят frame.toImage()). На паузе/стопе — сглаживаем
        # (чёткий стоп-кадр). См. set_playing.
        self._playing = False
        self.setMouseTracking(True)
        # Плавающие кнопки «Применить/Отмена» прямо на холсте (как в Photoshop).
        self._crop_apply_btn = make_icon_btn("Применить", icon='fa5s.check', accent=True)
        self._crop_apply_btn.setParent(self)
        self._crop_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_apply_btn.setToolTip("Применить кадрирование (Enter)")
        self._crop_apply_btn.clicked.connect(self.apply_crop)
        self._crop_cancel_btn = make_icon_btn("Отмена", icon='fa5s.times')
        self._crop_cancel_btn.setParent(self)
        self._crop_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_cancel_btn.setToolTip("Отменить кадрирование (Esc)")
        self._crop_cancel_btn.clicked.connect(self.cancel_crop)
        for _b in (self._crop_apply_btn, self._crop_cancel_btn):
            _b.setVisible(False)

    # ── Кадрирование видео (как в «Редактировании фото») ──────────────────────
    def set_crop_mode(self, on):
        on = bool(on)
        if on == self._crop_mode:
            return
        self._crop_mode = on
        if on:
            # При входе в режим — рамка СРАЗУ на весь кадр (как в InpaintCanvas),
            # если ещё не задана (можно тут же тянуть за ручки). Если рамка уже
            # «вооружена» прошлым применением — продолжаем её правку.
            if self._crop_norm is None:
                self._crop_norm = QRectF(0.0, 0.0, 1.0, 1.0)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocus()
        else:
            self._crop_drag = None
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()

    def set_scrub_active(self, on: bool):
        """Включает/выключает быстрый (без сглаживания) режим отрисовки на время
        активной перемотки — см. комментарий у self._scrub_active."""
        on = bool(on)
        if on != self._scrub_active:
            self._scrub_active = on

    def set_playing(self, on: bool):
        """Быстрый (без сглаживания) ресайз кадра во время воспроизведения — см.
        комментарий у self._playing. На паузе/стопе возвращаем сглаживание и
        перерисовываем текущий кадр уже сглаженно (чёткий стоп-кадр)."""
        on = bool(on)
        if on != self._playing:
            self._playing = on
            if not on and self._frame_img is not None:
                self.update()

    def has_crop(self) -> bool:
        return self._crop_norm is not None

    def crop_norm(self):
        """Нормализованная рамка кадрирования (QRectF 0..1) или None. Полный кадр
        (≈ весь экран) трактуем как «без кадрирования»."""
        n = self._crop_norm
        if n is None:
            return None
        if n.width() >= 0.999 and n.height() >= 0.999:
            return None
        return n

    def clear_crop(self):
        if self._crop_norm is not None or self._crop_drag is not None:
            self._crop_norm = None
            self._crop_drag = None
            self._update_crop_buttons()
            self.update()

    def apply_crop(self):
        """«Применить»: фиксируем рамку (её прочитает экспорт/«Сохранить кадр»),
        выходим из режима правки. Полный кадр трактуем как сброс кадрирования."""
        n = self._crop_norm
        if n is not None and n.width() >= 0.999 and n.height() >= 0.999:
            self._crop_norm = None     # рамка = весь кадр → кадрирования нет
        self._crop_mode = False
        self._crop_drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()
        self.cropApplied.emit()

    def cancel_crop(self):
        """«Отмена»: сбрасываем рамку и выходим из режима правки."""
        self._crop_norm = None
        self._crop_mode = False
        self._crop_drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()
        self.cropCancelled.emit()

    def _widget_to_norm(self, wpt, clamp=True):
        vr = self.video_rect()
        if vr.width() <= 0 or vr.height() <= 0:
            return None
        nx = (wpt.x() - vr.left()) / vr.width()
        ny = (wpt.y() - vr.top()) / vr.height()
        if clamp:
            nx = min(1.0, max(0.0, nx)); ny = min(1.0, max(0.0, ny))
        return QPointF(nx, ny)

    def _crop_rect_screen(self):
        """Текущая рамка кадрирования в ЭКРАННЫХ координатах (для ручек/кнопок)."""
        n = self._crop_norm
        vr = self.video_rect()
        if n is None or vr.width() <= 0:
            return QRectF()
        return QRectF(vr.left() + n.left() * vr.width(),
                      vr.top() + n.top() * vr.height(),
                      n.width() * vr.width(), n.height() * vr.height())

    def _crop_handle_at(self, wpt):
        """Какую «ручку» рамки задевает курсор (коорд. виджета): tl/tr/bl/br/t/b/
        l/r/move или None."""
        if not self.has_crop():
            return None
        r = self._crop_rect_screen()
        tol = 10.0
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

    @staticmethod
    def _crop_cursor(handle):
        cur = {
            'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
            't': Qt.CursorShape.SizeVerCursor,  'b': Qt.CursorShape.SizeVerCursor,
            'l': Qt.CursorShape.SizeHorCursor,  'r': Qt.CursorShape.SizeHorCursor,
            'move': Qt.CursorShape.SizeAllCursor,
        }
        return cur.get(handle, Qt.CursorShape.CrossCursor)

    def _drag_crop(self, npt):
        """Двигает активную ручку рамки. npt — позиция мыши в НОРМ. координатах."""
        d = self._crop_drag
        sr = self._crop_start_rect
        if sr is None:
            return
        l, t, r, bo = sr.left(), sr.top(), sr.right(), sr.bottom()
        minsz = 0.02
        if d == 'move':
            bw, bh = r - l, bo - t
            dx = npt.x() - self._crop_anchor.x()
            dy = npt.y() - self._crop_anchor.y()
            nl = min(max(l + dx, 0.0), 1.0 - bw)
            nt = min(max(t + dy, 0.0), 1.0 - bh)
            self._crop_norm = QRectF(nl, nt, bw, bh)
            return
        x = min(max(npt.x(), 0.0), 1.0)
        y = min(max(npt.y(), 0.0), 1.0)
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, bo - minsz)
        if 'b' in d: bo = max(y, t + minsz)
        self._crop_norm = QRectF(l, t, r - l, bo - t)

    def _update_crop_buttons(self):
        """Показывает/прячет и позиционирует «Применить/Отмена» у рамки (плавающая
        панель, как в Photoshop). Зовётся при любом изменении рамки/зума/размера."""
        show = (self._crop_mode and self.has_crop()
                and self._frame_img is not None)
        if not show:
            if self._crop_apply_btn.isVisible():
                self._crop_apply_btn.setVisible(False)
                self._crop_cancel_btn.setVisible(False)
            return
        r = self._crop_rect_screen()
        aw = self._crop_apply_btn.sizeHint()
        cw = self._crop_cancel_btn.sizeHint()
        gap = 6
        h = max(aw.height(), cw.height())
        total = aw.width() + cw.width() + gap
        x = int(r.right() - total)
        y = int(r.bottom() + gap)
        if y + h > self.height():
            y = int(r.bottom() - h - gap)
        x = max(2, min(x, self.width() - total - 2))
        y = max(2, min(y, self.height() - h - 2))
        self._crop_apply_btn.setGeometry(x, y, aw.width(), h)
        self._crop_cancel_btn.setGeometry(x + aw.width() + gap, y, cw.width(), h)
        self._crop_apply_btn.setVisible(True)
        self._crop_cancel_btn.setVisible(True)
        self._crop_apply_btn.raise_()
        self._crop_cancel_btn.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_crop_buttons()

    def keyPressEvent(self, ev):
        if self._crop_mode and self.has_crop():
            if ev.key() == Qt.Key.Key_Escape:
                self.cancel_crop(); ev.accept(); return
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.apply_crop(); ev.accept(); return
        super().keyPressEvent(ev)

    def videoSink(self):
        return self._sink

    def setAspectRatioMode(self, *a, **k):   # совместимость с QVideoWidget
        pass

    def clear_frame(self):
        self._frame_img = None
        self.update()

    def set_static_image(self, qimg):
        """Показывает СТАТИЧНУЮ картинку на холсте (режим «картинка → видео»):
        кадр рисуется как обычный видеокадр, но не от плеера, а напрямую. Сбрасывает
        субтитры/зум, чтобы картинка вписалась целиком."""
        self._text = ""
        self._image = None
        self._audio_only_msg = ""
        self._frame_img = qimg if (qimg is not None and not qimg.isNull()) else None
        self.reset_view()
        self.update()

    def current_frame_image(self):
        """Точная копия кадра, который СЕЙЧАС показан на холсте (полное
        разрешение видео, без субтитров — они рисуются отдельно). Нужна для
        «Сохранить кадр»: берём ровно то, что видит пользователь, а не
        пере-извлекаем кадр через ffmpeg по позиции (там seek по HEVC мог
        отдать СЛЕДУЮЩИЙ кадр)."""
        img = self._frame_img
        if img is not None and not img.isNull():
            return img.copy()
        return None

    def set_audio_only_message(self, text):
        """Текст по центру холста, когда видеоряда нет (редактируется аудио).
        Пустая строка — обычный режим (показ кадров)."""
        text = text or ""
        # Включаем режим «нет видео» — стираем последний кадр ПРЕДЫДУЩЕГО файла.
        # paintEvent рисует _frame_img в приоритете над сообщением, поэтому без
        # сброса старое видео «зависало» на холсте при загрузке аудиофайла
        # (менялась только волна, а картинка оставалась прежней).
        if text:
            self._frame_img = None
        if text == self._audio_only_msg:
            return
        self._audio_only_msg = text
        self.update()

    # ── Зум / панорама ───────────────────────────────────────────────────────
    def reset_view(self):
        """Сброс зума/панорамы (на 100%). Вызывается при загрузке нового файла."""
        changed = (self._zoom != 1.0) or (self._pan != QPoint(0, 0))
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        # Рамку кадрирования сбрасываем, чтобы не переносить её на новый файл
        # (режим кадрирования при этом не выключаем — кнопкой управляет вкладка).
        if self._crop_norm is not None or self._crop_drag is not None:
            self._crop_norm = None
            self._crop_drag = None
            self._update_crop_buttons()
            changed = True
        self.unsetCursor()
        if changed:
            self.update()

    def _base_video_rect(self):
        """Прямоугольник кадра при зуме 100% (letterbox по пропорциям)."""
        w, h = self.width(), self.height()
        img = self._frame_img
        if img is None or w <= 0 or h <= 0 or img.width() <= 0 or img.height() <= 0:
            return QRect(0, 0, max(0, w), max(0, h))
        scale = min(w / img.width(), h / img.height())
        rw = max(1, int(img.width() * scale))
        rh = max(1, int(img.height() * scale))
        return QRect((w - rw) // 2, (h - rh) // 2, rw, rh)

    def _clamp_pan(self):
        """Не даём утащить кадр так, чтобы по краям появился фон (когда кадр
        крупнее окна). По осям, где кадр меньше окна, держим его по центру."""
        base = self._base_video_rect()
        rw = base.width() * self._zoom
        rh = base.height() * self._zoom
        mx = max(0, (rw - self.width()) / 2.0)
        my = max(0, (rh - self.height()) / 2.0)
        x = max(-mx, min(mx, self._pan.x()))
        y = max(-my, min(my, self._pan.y()))
        self._pan = QPoint(int(x), int(y))

    def wheelEvent(self, ev):
        # Зум только с зажатым Ctrl (как в редакторах) и при наличии кадра.
        if (ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self._frame_img is not None):
            old = self._zoom
            new = (min(8.0, old * 1.2) if ev.angleDelta().y() > 0
                   else max(1.0, old / 1.2))
            if abs(new - old) < 1e-6:
                ev.accept(); return
            vr = self.video_rect()
            px = ev.position().x(); py = ev.position().y()
            s = new / old
            # Масштабируем текущий прямоугольник относительно точки под курсором,
            # чтобы она оставалась на месте при приближении/отдалении.
            new_left = px - (px - vr.left()) * s
            new_top = py - (py - vr.top()) * s
            new_w = vr.width() * s
            new_h = vr.height() * s
            base = self._base_video_rect()
            self._zoom = new
            if new <= 1.0001:
                self._pan = QPoint(0, 0)
            else:
                cx = new_left + new_w / 2.0
                cy = new_top + new_h / 2.0
                self._pan = QPoint(int(cx - base.center().x()),
                                   int(cy - base.center().y()))
                self._clamp_pan()
            self._update_crop_buttons()   # рамка/кнопки следуют за зумом
            self.update()
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        if (self._crop_mode and ev.button() == Qt.MouseButton.LeftButton
                and self._frame_img is not None):
            handle = self._crop_handle_at(ev.position())
            if handle is not None:
                # Захватили ручку/тело существующей рамки — тянем её.
                self._crop_drag = handle
                self._crop_anchor = self._widget_to_norm(ev.position(), clamp=False)
                self._crop_start_rect = QRectF(self._crop_norm)
            else:
                # Клик вне рамки — рисуем НОВУЮ рамку от этой точки (тянем угол br).
                n = self._widget_to_norm(ev.position())
                if n is not None:
                    self._crop_norm = QRectF(n.x(), n.y(), 0.0, 0.0)
                    self._crop_drag = 'br'
                    self._crop_anchor = n
                    self._crop_start_rect = QRectF(self._crop_norm)
            self._update_crop_buttons()
            self.update()
            ev.accept()
            return
        if self._zoom > 1.0 and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._crop_mode and self._frame_img is not None:
            if self._crop_drag and (ev.buttons() & Qt.MouseButton.LeftButton):
                npt = self._widget_to_norm(ev.position(), clamp=False)
                if npt is not None:
                    self._drag_crop(npt)
                    self._update_crop_buttons()
                    self.update()
                ev.accept()
                return
            # Без зажатой кнопки — курсор подсказывает доступную ручку.
            self.setCursor(self._crop_cursor(self._crop_handle_at(ev.position())))
            ev.accept()
            return
        if self._panning and self._pan_last is not None:
            d = ev.position() - self._pan_last
            self._pan_last = ev.position()
            self._pan = QPoint(self._pan.x() + int(d.x()),
                               self._pan.y() + int(d.y()))
            self._clamp_pan()
            self.update()
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if (self._crop_mode and self._crop_drag is not None
                and ev.button() == Qt.MouseButton.LeftButton):
            self._crop_drag = None
            # Совсем крошечная рамка (случайный клик) = весь кадр, чтобы не остаться
            # с пустым выделением (правят дальше ручками или жмут «Применить»).
            n = self._crop_norm
            if n is not None and (n.width() < 0.02 or n.height() < 0.02):
                self._crop_norm = QRectF(0.0, 0.0, 1.0, 1.0)
            else:
                self._crop_norm = QRectF(n).normalized()
            self._update_crop_buttons()
            self.update()
            ev.accept()
            return
        if self._panning and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self.unsetCursor()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def set_play_bound(self, out_seconds):
        """Граница OUT для блокировки кадров при воспроизведении (None — снять)."""
        self._bound_us = (int(out_seconds * 1_000_000)
                          if (out_seconds and out_seconds > 0) else None)

    def _on_frame(self, frame):
        # Аудиофайл (видеоряда нет): игнорируем любые «поздние» кадры от плеера
        # (например, финальный кадр прошлого источника при смене файла), иначе
        # старое видео вновь заполнит _frame_img и перекроет сообщение «нет видео».
        if self._audio_only_msg:
            return
        # Граница OUT по PTS кадра — ПРОВЕРЯЕМ ДО конвертации в QImage и показа.
        # Кадр за границей не рисуем и просим плеер на паузу (анти-overshoot).
        if frame is not None and self._bound_us is not None:
            try: pts = frame.startTime()    # µs, -1 если неизвестно
            except Exception: pts = -1
            if pts >= 0 and pts >= self._bound_us:
                self.boundaryReached.emit()
                return
        img = None
        try:
            if frame is not None and frame.isValid():
                img = frame.toImage()
        except Exception:
            img = None
        if img is not None and not img.isNull():
            self._frame_img = img
            if self.isVisible():
                self.update()

    def _paint_crop_overlay(self, p, vr):
        """Затемняет всё вне рамки кадрирования + рисует границу и сетку третей
        (в пределах видимой части кадра). vr — прямоугольник кадра на экране."""
        n = self._crop_norm
        r = QRectF(vr.left() + n.left() * vr.width(),
                   vr.top() + n.top() * vr.height(),
                   n.width() * vr.width(), n.height() * vr.height())
        clip = QRectF(vr).intersected(QRectF(self.rect()))
        r = r.intersected(clip)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRect(QRectF(clip.left(), clip.top(), clip.width(), r.top() - clip.top()))
        p.drawRect(QRectF(clip.left(), r.bottom(), clip.width(), clip.bottom() - r.bottom()))
        p.drawRect(QRectF(clip.left(), r.top(), r.left() - clip.left(), r.height()))
        p.drawRect(QRectF(r.right(), r.top(), clip.right() - r.right(), r.height()))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            gx = r.left() + r.width() * i / 3.0
            gy = r.top() + r.height() * i / 3.0
            p.drawLine(QPointF(gx, r.top()), QPointF(gx, r.bottom()))
            p.drawLine(QPointF(r.left(), gy), QPointF(r.right(), gy))
        p.setPen(QPen(QColor("#cdd6f4"), 1.5))
        p.drawRect(r)
        # Ручки по углам и серединам сторон (как в «Редактировании фото»).
        hs = 7.0
        p.setPen(QPen(QColor("#11111b"), 1))
        p.setBrush(QColor("#cdd6f4"))
        cx, cy = (r.left() + r.right()) / 2.0, (r.top() + r.bottom()) / 2.0
        for hx, hy in ((r.left(), r.top()), (r.right(), r.top()),
                       (r.left(), r.bottom()), (r.right(), r.bottom()),
                       (cx, r.top()), (cx, r.bottom()),
                       (r.left(), cy), (r.right(), cy)):
            p.drawRect(QRectF(hx - hs / 2, hy - hs / 2, hs, hs))
        p.restore()

    def _paint_crop_indicator(self, p, vr):
        """Тонкая пунктирная рамка «вооружённого» кадрирования вне режима правки —
        показывает, какую область получит итоговое видео при «Обрезать»."""
        n = self._crop_norm
        r = QRectF(vr.left() + n.left() * vr.width(),
                   vr.top() + n.top() * vr.height(),
                   n.width() * vr.width(), n.height() * vr.height())
        r = r.intersected(QRectF(vr).intersected(QRectF(self.rect())))
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#89b4fa"), 1.5, Qt.PenStyle.DashLine))
        p.drawRect(r)
        p.restore()

    def video_rect(self):
        """Прямоугольник, где реально показан кадр (letterbox + текущий зум/пан)."""
        base = self._base_video_rect()
        if self._frame_img is None or self._zoom == 1.0:
            return base
        rw = max(1, int(base.width() * self._zoom))
        rh = max(1, int(base.height() * self._zoom))
        cx = base.center().x() + self._pan.x()
        cy = base.center().y() + self._pan.y()
        return QRect(int(cx - rw / 2.0), int(cy - rh / 2.0), rw, rh)

    # ── Единый API субтитров (как у SubtitleOverlay) ─────────────────────────
    def subtitle_area_size(self):
        r = self.video_rect()
        return r.width(), r.height()

    def set_subtitle_image(self, qimg, x=0, y=0):
        self._image = qimg
        self._image_pos = (int(x), int(y))
        self.update()

    def set_subtitle_text(self, text):
        text = text or ""
        if self._image is None and text == self._text:
            return
        self._image = None
        self._text = text
        self.update()

    def clear_subtitle(self):
        if self._image is None and not self._text:
            return
        self._image = None
        self._text = ""
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        img = self._frame_img
        if img is not None and not img.isNull():
            vr = self.video_rect()
            # Во время протяжки/воспроизведения — без сглаживания (быстрее, кадр всё
            # равно сейчас сменится); на устоявшемся стоп-кадре — со сглаживанием
            # (качество).
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                            not (self._scrub_active or self._playing))
            p.drawImage(vr, img)
            # Субтитры рисуем в ВИДИМОЙ части кадра (пересечение зумированного vr
            # с областью виджета), а не во всём vr. Иначе при приближении кадра
            # низ vr уходит далеко за нижнюю границу виджета, и субтитры,
            # привязанные к низу кадра, «улетают» за экран (баг с приближением).
            sub_rect = vr.intersected(self.rect())
            if sub_rect.width() < 10 or sub_rect.height() < 10:
                sub_rect = self.rect()
            px = max(15, int(min(sub_rect.height(), self.height()) * 0.052))
            _paint_subtitle(p, sub_rect, self._text, px, self._image, self._image_pos)
            # Рамка кадрирования видео (как в «Редактировании фото»): в режиме
            # правки — затемнение/сетка/ручки, иначе (рамка «вооружена») — тонкая
            # пунктирная подсказка, что экспорт кадрируется по ней.
            if self._crop_mode and self._crop_norm is not None:
                self._paint_crop_overlay(p, vr)
            elif self._crop_norm is not None:
                self._paint_crop_indicator(p, vr)
        elif self._audio_only_msg:
            # Видеоряда нет — рисуем иконку ноты и поясняющий текст по центру.
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            icon_px = max(28, int(min(self.width(), self.height()) * 0.16))
            pm = get_icon_pixmap('fa5s.music', icon_px, C['text3'])
            gap = 14
            font = p.font()
            font.setPointSize(11)
            font.setFamily("Segoe UI" if os.name == 'nt' else "SF Pro Display")
            p.setFont(font)
            fm = QFontMetrics(font)
            text_rect = fm.boundingRect(
                QRect(0, 0, max(60, self.width() - 40), 1000),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                self._audio_only_msg)
            ih = (icon_px + gap) if (pm is not None and not pm.isNull()) else 0
            total_h = ih + text_rect.height()
            top = (self.height() - total_h) // 2
            if pm is not None and not pm.isNull():
                ix = (self.width() - icon_px) // 2
                p.drawPixmap(QRect(ix, top, icon_px, icon_px), pm)
            p.setPen(QPen(QColor(C['text3'])))
            tr = QRect((self.width() - text_rect.width()) // 2, top + ih,
                       text_rect.width(), text_rect.height())
            p.drawText(tr, int(Qt.AlignmentFlag.AlignHCenter
                               | Qt.TextFlag.TextWordWrap), self._audio_only_msg)
        p.end()


# ─── Полоса воспроизведения с мгновенной перемоткой по клику ────────────────────
class SeekSlider(QSlider):
    """Полоса воспроизведения как в обычных плеерах: клик/перетаскивание мгновенно
    перематывает в точку под курсором (стандартный QSlider лишь «подкрадывается»
    page-step'ами). Пока пользователь держит ползунок, плеер не перебивает его
    значение (см. is_user_seeking)."""

    # Максимальная частота РЕАЛЬНЫХ seek'ов (sliderMoved → player.setPosition) во
    # время протяжки мышью — на тяжёлом H.264/HEVC (редкие кейфреймы) плеер не
    # успевает отрабатывать seek на каждый пиксель движения курсора (mouseMoveEvent
    # может сыпаться намного чаще) и «копит» очередь — перемотка ощущается с
    # запозданием, хотя каждый отдельный seek сам по себе быстрый. Ручку слайдера
    # (setValue) НЕ троттлим — она остаётся под курсором мгновенно, как обычно;
    # троттлится только фактическая перемотка видео. Покадрового шага стрелками
    # (step_frame/step_frame_scrub) это не касается — тот путь вызывает
    # player.setPosition() напрямую, минуя sliderMoved.
    _SEEK_THROTTLE_S = 0.05

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._seeking = False
        self._last_seek_emit = 0.0
        self._seek_pending_v = None
        self._seek_flush_timer = QTimer(self)
        self._seek_flush_timer.setSingleShot(True)
        self._seek_flush_timer.timeout.connect(self._flush_pending_seek)

    def is_user_seeking(self):
        return self._seeking

    def _emit_seek(self, v):
        """Троттлит sliderMoved во время протяжки (см. _SEEK_THROTTLE_S); клик и
        отпускание кнопки — всегда мгновенно, без троттлинга."""
        now = time.monotonic()
        if now - self._last_seek_emit >= self._SEEK_THROTTLE_S:
            self._last_seek_emit = now
            self._seek_pending_v = None
            self._seek_flush_timer.stop()
            self.sliderMoved.emit(v)
        else:
            self._seek_pending_v = v
            if not self._seek_flush_timer.isActive():
                remaining = max(1, int((self._SEEK_THROTTLE_S - (now - self._last_seek_emit)) * 1000))
                self._seek_flush_timer.start(remaining)

    def _flush_pending_seek(self):
        if self._seek_pending_v is not None and self._seeking:
            self._last_seek_emit = time.monotonic()
            v, self._seek_pending_v = self._seek_pending_v, None
            self.sliderMoved.emit(v)

    def _value_at(self, x):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        span = (groove.right() - groove.left() - handle.width())
        pos = x - groove.left() - handle.width() // 2
        if span <= 0:
            return self.minimum()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, span)

    def mousePressEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and self.orientation() == Qt.Orientation.Horizontal):
            self._seeking = True
            self._last_seek_emit = time.monotonic()  # свежее окно троттлинга для нового драга
            v = self._value_at(int(ev.position().x()))
            self.setValue(v)
            self.sliderMoved.emit(v)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        # Превью обновляем на КАЖДОЕ движение курсора по полосе (а не только при
        # входе) — иначе чтобы увидеть другой кадр, приходилось уводить курсор и
        # наводиться заново.
        try: self._show_preview(ev)
        except Exception: pass
        if (self._seeking
                and self.orientation() == Qt.Orientation.Horizontal):
            v = self._value_at(int(ev.position().x()))
            self.setValue(v)        # ручка следует за курсором мгновенно, без троттлинга
            self._emit_seek(v)      # а сам seek видео — троттлится (см. _SEEK_THROTTLE_S)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._seeking and ev.button() == Qt.MouseButton.LeftButton:
            self._seeking = False
            # Финальную позицию отпускания отдаём немедленно, не дожидаясь
            # отложенного флаша троттлера — иначе итоговый кадр «доедет» с задержкой.
            self._seek_flush_timer.stop()
            if self._seek_pending_v is not None:
                v, self._seek_pending_v = self._seek_pending_v, None
                self._last_seek_emit = time.monotonic()
                self.sliderMoved.emit(v)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    # ── Превью кадров при наведении (как на YouTube) ──────────────────────────
    def attach_preview(self, preview):
        """Привязывает общий контроллер превью (SeekPreview). Включает отслеживание
        мыши, чтобы показывать миниатюру кадра под курсором без зажатой кнопки."""
        self._preview = preview
        self.setMouseTracking(True)

    def _show_preview(self, ev):
        pv = getattr(self, "_preview", None)
        if pv is None or self.orientation() != Qt.Orientation.Horizontal:
            return
        x = int(ev.position().x())
        pv.show_at(self, x, self._value_at(x))

    def enterEvent(self, ev):
        # При входе курсора покажем превью сразу (положение возьмём из события).
        try: self._show_preview(ev)
        except Exception: pass
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        pv = getattr(self, "_preview", None)
        if pv is not None:
            try: pv.hide()
            except Exception: pass
        super().leaveEvent(ev)


class SeekPreview:
    """Превью кадра под курсором над полосой воспроизведения (как на YouTube).
    Один экземпляр обслуживает обе полосы — в окне и в полноэкранном режиме.

    Устройство попапа: миниатюра СВЕРХУ, время — отдельным лейблом СНИЗУ (в самой
    картинке цифры не рисуются). Фон попапа прозрачный — никакого серого
    «паспарту»: где нет картинки, остаётся пусто (как превью в проводнике Windows).

    Чтобы не было рывка «сначала цифры, потом кадр»: при переходе на новую
    позицию предыдущая миниатюра остаётся на экране, пока ffmpeg извлекает
    новую; время при этом обновляется мгновенно. Кадры кэшируются."""

    _QUANT = 1.0   # шаг квантования позиции (сек) — ограничивает число кадров

    def __init__(self, get_duration):
        self._get_duration = get_duration
        self._cache = {}
        self._cur_q = None
        self._anchor = None   # (slider, local_x)
        self._popup = QWidget(None, Qt.WindowType.ToolTip
                              | Qt.WindowType.FramelessWindowHint)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self._popup)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._img_lbl = QLabel()
        self._img_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._img_lbl.setStyleSheet("background:transparent;")
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl = QLabel()
        self._time_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl.setStyleSheet(
            "color:#ffffff;background:rgba(11,11,18,0.88);border:1px solid #585b70;"
            "border-radius:5px;padding:2px 10px;font-weight:bold;font-size:13px;")
        lay.addWidget(self._img_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._time_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        self._th = _SeekThumbnailer()
        self._th.ready.connect(self._on_ready)
        self._th.start()

    def set_source(self, src):
        self._cache.clear()
        self._cur_q = None
        self._img_lbl.clear()
        self._img_lbl.setFixedSize(0, 0)
        self._th.set_source(src)
        # Префетч одного кадра, чтобы первое наведение уже имело картинку.
        try:
            dur = float(self._get_duration() or 0.0)
            if dur > 0:
                self._th.request(self._quant(dur / 2.0))
        except Exception:
            pass

    def _quant(self, sec):
        return round(sec / self._QUANT) * self._QUANT

    def show_at(self, slider, local_x, value):
        dur = 0.0
        try: dur = float(self._get_duration() or 0.0)
        except Exception: dur = 0.0
        if dur <= 0:
            self.hide(); return
        sec = max(0.0, min(dur, (value / 1000.0) * dur))
        q = self._quant(sec)
        self._cur_q = q
        self._anchor = (slider, local_x)
        # Время — всегда мгновенно.
        self._time_lbl.setText(self._fmt(sec))
        # Картинку обновляем только из кэша; если её нет — оставляем предыдущую
        # (никаких «сначала цифры, потом кадр») и заказываем извлечение.
        pm = self._cache.get(q)
        if pm is not None and not pm.isNull():
            self._set_image(pm)
        elif q not in self._cache:
            self._th.request(q)
        self._reposition()
        self._popup.show(); self._popup.raise_()

    def _set_image(self, pm):
        self._img_lbl.setFixedSize(pm.width(), pm.height())
        self._img_lbl.setPixmap(pm)

    def _on_ready(self, sec, img):
        try:
            pm = QPixmap.fromImage(img)
            if not pm.isNull():
                self._cache[sec] = pm
                # Если курсор всё ещё на этой позиции — показываем кадр.
                if self._cur_q == sec and self._popup.isVisible() and self._anchor:
                    self._set_image(pm)
                    self._reposition()
        except Exception:
            pass

    def _reposition(self):
        if self._anchor is None:
            return
        slider, local_x = self._anchor
        try:
            self._popup.adjustSize()
            gp = slider.mapToGlobal(QPoint(local_x, 0))
            x = gp.x() - self._popup.width() // 2
            y = gp.y() - self._popup.height() - 10
            scr = slider.screen().availableGeometry()
            if x < scr.left() + 2: x = scr.left() + 2
            if x + self._popup.width() > scr.right(): x = scr.right() - self._popup.width() - 2
            if y < scr.top() + 2:
                y = gp.y() + 18   # не помещается сверху — показываем снизу
            self._popup.move(x, y)
        except Exception:
            pass

    @staticmethod
    def _fmt(sec):
        sec = int(max(0, sec))
        h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    def hide(self):
        try: self._popup.hide()
        except Exception: pass

    def shutdown(self):
        try: self._th.stop(); self._th.wait(1500)
        except Exception: pass


# ─── Полноэкранное окно видео ──────────────────────────────────────────────────
class FullscreenVideo(QWidget):
    """Отдельное полноэкранное окно для видео вкладки «Монтаж».

    Внизу — панель управления как в обычных видеоплеерах: кнопка play/pause,
    текущее/общее время и полоса воспроизведения. Панель и курсор авто-скрываются
    при бездействии и снова появляются при движении мыши. Esc / F / двойной клик —
    выход из полноэкранного режима."""

    def __init__(self, edit_tab):
        super().__init__()
        self.edit = edit_tab
        self.setWindowTitle("SI-HYX — Полный экран")
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Видео занимает всё окно; панель управления накладывается поверх снизу.
        # Субтитры рисует общий оверлей EditTab (отдельное окно), он подгоняется
        # под видео этого окна — см. EditTab._position_overlay.
        self._video = None

        # ── Панель управления ────────────────────────────────────────────
        # ВАЖНО: QVideoWidget рисует видео через нативную поверхность и
        # перекрывает обычные дочерние виджеты (та же причина, по которой не было
        # видно субтитров). Поэтому панель — отдельное БЕЗРАМОЧНОЕ окно «поверх
        # всех», но КЛИКАБЕЛЬНОЕ (кнопки/полоса), привязанное к этому окну.
        self.bar = QFrame(self, Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.Tool
                          | Qt.WindowType.WindowStaysOnTopHint)
        self.bar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.bar.setObjectName("FsBar")
        self.bar.setStyleSheet(
            "#FsBar { background: rgba(15,15,18,0.88); "
            "border-top: 1px solid rgba(255,255,255,0.10); }"
            # Та же тёмная подсказка, что и во вкладке (см. EditTab.apply_theme) —
            # чтобы штатные tooltip'ы кнопок панели выглядели одинаково.
            f"QToolTip {{ background: {C['surface3']}; color: {C['text']}; "
            f"border: 1px solid {C['border2']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}")
        # Подсказки кнопок панели — СВОИМ лейблом, ребёнком self.bar, а НЕ
        # штатным QToolTip.showText: тот рисует ОТДЕЛЬНОЕ нативное окно
        # (popup), и на некоторых системах/раскладках экранов оно упорно
        # оказывалось «за пределами экрана» (или под fullscreen-видео),
        # НЕЗАВИСИМО от того, какую позицию мы ему передавали. Дочерний
        # QLabel гарантированно живёт в ТОМ ЖЕ окне, что и сама панель
        # (а она уже точно видна) — так надёжнее. См. eventFilter/_show_fs_tip.
        self._tip = QLabel(self.bar)
        self._tip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._tip.setStyleSheet(
            f"background: {C['surface3']}; color: {C['text']}; "
            f"border: 1px solid {C['border2']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px;")
        self._tip.hide()
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(22, 10, 22, 12)
        bl.setSpacing(8)

        # Полоса воспроизведения + тайминги в одной строке (клик по полосе —
        # мгновенная перемотка; SeekSlider это уже умеет).
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(12)
        _mono = QFont("Courier New" if os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(12)
        self.lbl_cur = QLabel("00:00:00.000", self.bar)
        self.lbl_cur.setFont(_mono)
        self.lbl_cur.setStyleSheet("color:#a6e3a1; background:transparent;")
        seek_row.addWidget(self.lbl_cur)
        self.slider = SeekSlider(Qt.Orientation.Horizontal, self.bar)
        self.slider.setRange(0, 1000)
        self.slider.setStyleSheet(self._fs_slider_style())
        # Полоса не должна перехватывать фокус — иначе Пробел уходит ей, а не окну.
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        # Тот же контроллер превью кадров, что и у полосы в окне.
        try:
            pv = getattr(self.edit, "seek_preview", None)
            if pv is not None:
                self.slider.attach_preview(pv)
        except Exception:
            pass
        seek_row.addWidget(self.slider, 1)
        self.lbl_tot = QLabel("00:00:00.000", self.bar)
        self.lbl_tot.setFont(_mono)
        self.lbl_tot.setStyleSheet("color:#bac2de; background:transparent;")
        seek_row.addWidget(self.lbl_tot)
        bl.addLayout(seek_row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        _fsbtn_css = (
            "QPushButton { background: rgba(255,255,255,0.08); border: none;"
            " border-radius: 7px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.18); } "
            "QPushButton:pressed { background: rgba(255,255,255,0.30); }")
        _fsbtn_accent_css = (
            "QPushButton { background: rgba(137,180,250,0.85); border: none;"
            " border-radius: 7px; } "
            "QPushButton:hover { background: rgba(180,190,254,0.95); } "
            "QPushButton:pressed { background: rgba(137,180,250,0.65); }")

        def _fsbtn(icon_std, tip, slot, size=(42, 34), accent=False, icon=None):
            b = QPushButton(self.bar)
            b.setIcon(icon if icon is not None
                      else self.style().standardIcon(icon_std))
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(*size)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            # Подсказка — ШТАТНЫМ механизмом Qt (setToolTip), ровно как у кнопки
            # «Сохранить кадр» на боковой панели. Раньше здесь была самописная
            # подсказка через QToolTip.showText на Enter/Leave (см. eventFilter):
            # она МЕРЦАЛА (повторные show/hide при каждом входе курсора) и рисовала
            # инородную рамку. НЕ ВОЗВРАЩАТЬ — стиль подсказки задаётся через
            # QToolTip в self.bar.setStyleSheet (тёмная тема, как во вкладке).
            b.setToolTip(tip)
            b.setStyleSheet(_fsbtn_accent_css if accent else _fsbtn_css)
            # Кнопки не держат фокус: после клика по «Стоп» Пробел должен идти
            # окну (воспроизведение/пауза), а не повторно жать ту же кнопку.
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            # Панель (self.bar) — отдельное топ-левел окно у самого низа экрана,
            # чей QScreen иногда остаётся привязан к чужому монитору (см.
            # _relayout) — штатный клэмп QToolTip тогда считает границы не того
            # экрана, и подсказка рисуется «за пределами экрана» (невидимой).
            # Перехватываем QEvent.ToolTip (единичное событие показа, НЕ
            # Enter/Leave — значит, без мерцания) и сами ставим позицию рядом
            # с РЕАЛЬНЫМ экраном под курсором — см. eventFilter.
            b.installEventFilter(self)
            row.addWidget(b)
            return b

        self.btn_stop = _fsbtn(QStyle.StandardPixmap.SP_MediaStop,
                               "Стоп — к началу зоны", self.edit.stop_playback)
        self.btn_step_back = _fsbtn(QStyle.StandardPixmap.SP_MediaSeekBackward,
                                    "Кадр назад (←)",
                                    partial(self.edit.step_frame_scrub, -1))
        self.btn_play = _fsbtn(QStyle.StandardPixmap.SP_MediaPlay,
                               "Воспроизвести / пауза (Пробел)",
                               self.edit.toggle_play, size=(50, 34), accent=True)
        self.btn_step_fwd = _fsbtn(QStyle.StandardPixmap.SP_MediaSeekForward,
                                   "Кадр вперёд (→)",
                                   partial(self.edit.step_frame_scrub, 1))
        self.btn_jump_end = _fsbtn(QStyle.StandardPixmap.SP_MediaSkipForward,
                                   "Перейти к концу зоны (OUT)",
                                   lambda: self.edit.seek_to(self.edit.current_out))

        row.addSpacing(10)
        self.btn_save_frame = _fsbtn(None,
                                     "Сохранить текущий кадр в PNG",
                                     self.edit.save_frame,
                                     icon=get_icon('fa5s.save', color='#ffffff'))

        row.addStretch(1)

        # Громкость — связана с основным ползунком вкладки (он управляет звуком).
        self.vol_lbl = VolumeLabel(lambda: getattr(self, "vol_slider", None), self.bar)
        self.vol_lbl.setStyleSheet("color:#cdd6f4; font-size:15px; background:transparent;")
        row.addWidget(self.vol_lbl)
        self.vol_slider = VolumeSlider(Qt.Orientation.Horizontal, self.bar)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self.edit.vol_slider.value()))
        self.vol_slider.setFixedWidth(120)
        # Прозрачный жёлоб (а не тёмный surface3) и белый бегунок без чёрной
        # окантовки — чтобы за ползунком громкости не было чёрного прямоугольника.
        self.vol_slider.setStyleSheet(
            "QSlider { background: transparent; }"
            "QSlider::groove:horizontal { background: rgba(255,255,255,0.22);"
            " height: 6px; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #cdd6f4; border-radius: 3px; }"
            "QSlider::add-page:horizontal { background: rgba(255,255,255,0.22);"
            " border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #ffffff; width: 13px;"
            " height: 13px; margin: -4px 0; border-radius: 7px; }")
        self.vol_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.vol_slider)

        row.addSpacing(10)
        self.btn_exit = _fsbtn(QStyle.StandardPixmap.SP_TitleBarNormalButton,
                               "Выйти из полноэкранного режима (Esc)",
                               self.edit.exit_fullscreen,
                               icon=_fullscreen_icon(expand=False))

        bl.addLayout(row)

        # Авто-скрытие панели/курсора при бездействии.
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(2500)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_bar)
        # Клавиши (Esc/пробел/стрелки), пойманные окном панели, шлём в это окно.
        self.bar.installEventFilter(self)

    @staticmethod
    def _fs_slider_style():
        """Полоса воспроизведения для полноэкранного режима: высокий жёлоб с
        закруглёнными концами, видимая заполненная часть и заметный бегунок."""
        ph = C["playhead"]
        return f"""
            QSlider {{ min-height: 18px; background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
                height: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ph};
                border-radius: 4px;
            }}
            QSlider::add-page:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {ph};
                width: 16px; height: 16px;
                margin: -5px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{ background: {ph}; }}
        """

    # ── Видео ──────────────────────────────────────────────────────────────
    def attach_video(self, video_widget):
        self._video = video_widget
        video_widget.setParent(self)
        video_widget.show()
        self._relayout()
        self._show_bar()

    def _relayout(self):
        if self._video is not None:
            self._video.setGeometry(0, 0, self.width(), self.height())
        # Субтитры рисует общий оверлей EditTab — переподгоняем под это окно.
        try:
            self.edit._position_overlay()
        except Exception:
            pass
        # Панель — отдельное окно: позиционируем в ГЛОБАЛЬНЫХ координатах внизу.
        bar_h = max(64, self.bar.sizeHint().height())
        tl = self.mapToGlobal(QPoint(0, self.height() - bar_h))
        self.bar.setGeometry(tl.x(), tl.y(), self.width(), bar_h)
        if self.bar.isVisible():
            self.bar.raise_()   # поверх оверлея субтитров
        # self.bar — WA_TranslucentBackground + WindowType.Tool получает нативный
        # хэндл сразу при создании (до первого setGeometry), поэтому его QScreen
        # застревает на том экране, где он появился на свет (обычно первичный
        # монитор) — даже когда полноэкранное окно реально открыто на ДРУГОМ
        # мониторе. Из-за этого стандартный hover-tooltip кнопок панели считает
        # границы экрана по чужому монитору и получается «за пределами экрана».
        # Перепривязываем окно панели к экрану, где она физически оказалась.
        try:
            scr = QApplication.screenAt(tl)
            wh = self.bar.windowHandle()
            if scr is not None and wh is not None and wh.screen() is not scr:
                wh.setScreen(scr)
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    # ── Синхронизация со плеером ─────────────────────────────────────────────
    def sync_from_player(self):
        e = self.edit
        dur = e.duration or 0.0
        pos_s = e.player.position() / 1000.0
        self.lbl_cur.setText(s_to_time(pos_s))
        self.lbl_tot.setText(s_to_time(dur))
        if dur > 0 and not self.slider.is_user_seeking():
            # Плеер авто-паузится за кадр до конца, поэтому у самого конца
            # «дотягиваем» полосу до 100%, чтобы она доходила до края.
            frac = 1.0 if pos_s >= (dur - 0.08) else (pos_s / dur)
            self.slider.blockSignals(True)
            self.slider.setValue(int(frac * 1000))
            self.slider.blockSignals(False)

    def update_play_icon(self, playing):
        ic = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(ic))

    def _on_slider_moved(self, value):
        dur = self.edit.duration or 0.0
        if dur > 0:
            self.edit.seek_to((value / 1000.0) * dur)
        self._show_bar()

    def _on_volume_changed(self, v):
        # Звуком управляет основной ползунок вкладки — отражаем туда значение
        # (он применит его к audio_output и обновит свой значок).
        try:
            self.edit.vol_slider.setValue(int(v))
        except Exception:
            pass
        try:
            self.vol_lbl.update_glyph(int(v))
        except Exception:
            pass
        self._show_bar()

    def sync_volume(self):
        """Подтягивает текущую громкость из основного ползунка вкладки."""
        try:
            v = int(self.edit.vol_slider.value())
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass

    # ── Авто-скрытие панели/курсора ──────────────────────────────────────────
    def _show_bar(self):
        self._relayout()
        self.bar.show(); self.bar.raise_()
        self.unsetCursor()
        self._hide_timer.start()

    def _hide_bar(self):
        # Не прячем, пока курсор над самой панелью (пользователь ей пользуется).
        # geometry() панели теперь в глобальных координатах (отдельное окно).
        if self.bar.geometry().contains(self.cursor().pos()):
            self._hide_timer.start()
            return
        self.bar.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, ev):
        self._show_bar()
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.edit.exit_fullscreen()

    def eventFilter(self, obj, ev):
        # Esc/стрелки, нажатые когда активно окно панели, перенаправляем сюда.
        if obj is self.bar and ev.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(ev)
            if ev.isAccepted():
                return True
        # Подсказки кнопок панели — СВОИМ лейблом (self._tip, дочерний виджет
        # self.bar), см. _show_fs_tip. Штатный QToolTip.showText здесь себя не
        # оправдал: это ОТДЕЛЬНОЕ нативное popup-окно, и подобранная позиция
        # всё равно не помогала — подсказка стабильно оказывалась невидимой
        # (за экраном / под fullscreen-видео). Дочерний QLabel гарантированно
        # рисуется в ТОМ ЖЕ окне, что и сама панель, а она уже точно видна.
        # QEvent.ToolTip — штатное ОДНОКРАТНОЕ событие показа (не Enter/Leave,
        # то мерцало раньше); Leave только прячет лейбл, показ им не управляет.
        if (ev.type() == QEvent.Type.ToolTip and isinstance(obj, QPushButton)
                and obj.toolTip()):
            self._show_fs_tip(obj, obj.toolTip())
            return True
        if ev.type() == QEvent.Type.Leave and isinstance(obj, QPushButton):
            self._tip.hide()
            return super().eventFilter(obj, ev)
        return super().eventFilter(obj, ev)

    def _show_fs_tip(self, btn, text):
        self._tip.setText(text)
        self._tip.adjustSize()
        x = btn.x() + (btn.width() - self._tip.width()) // 2
        x = max(4, min(x, self.bar.width() - self._tip.width() - 4))
        y = btn.y() - self._tip.height() - 8
        self._tip.move(x, max(0, y))
        self._tip.show()
        self._tip.raise_()

    _VK_F = 0x46

    def keyPressEvent(self, ev):
        k = ev.key()
        # F — по физической клавише через nativeVirtualKey, независимо от
        # раскладки: на кириллице event.key() для физической F даёт код
        # буквы «А», и один только `k == Qt.Key.Key_F` молча не срабатывает
        # (тот же баг, что и с Ctrl+Z/Y/WASD — см. EditTab.keyPressEvent).
        try:
            vk = ev.nativeVirtualKey()
        except Exception:
            vk = 0
        if k == Qt.Key.Key_Escape or k == Qt.Key.Key_F or vk == self._VK_F:
            self.edit.exit_fullscreen()
        elif k == Qt.Key.Key_Space:
            self.edit.toggle_play()
        elif k == Qt.Key.Key_Left:
            self.edit.step_frame_scrub(-1)
        elif k == Qt.Key.Key_Right:
            self.edit.step_frame_scrub(1)
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        # Панель — отдельное окно: прячем явно, чтобы не зависла на экране.
        try: self.bar.hide()
        except Exception: pass
        # Если окно закрыли системно (Alt+F4) — аккуратно вернём видео обратно.
        if getattr(self.edit, "_fs_window", None) is self:
            self.edit.exit_fullscreen()
        super().closeEvent(ev)


class _StyledSubtitleOverlay(QWidget):
    """Прозрачный оверлей поверх _SubtitlePreview.canvas — рисует ТЕКУЩУЮ реплику
    выбранным пользователем стилем (_paint_subtitle_styled), а не фиксированным
    VLC-стилем основного приложения (_paint_subtitle, его не трогаем)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._style = None

    def set_content(self, text, style):
        self._text = text or ""
        self._style = style
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        _paint_subtitle_styled(p, self.rect(), self._text, self._style)
        p.end()


class _SubtitlePreview(QWidget):
    """Мини-плеер для SubtitleCreatorDialog: собственный QMediaPlayer + VideoCanvas
    (независимо от плеера основной вкладки монтажа — второй набор player+canvas,
    как _build_video_output собирает первый), поверх кадра — свой прозрачный
    оверлей со стилизованным текстом текущей реплики."""

    positionChanged = pyqtSignal(float)
    durationChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)

        self.canvas = VideoCanvas(self)
        self.canvas.setMinimumHeight(220)
        # По умолчанию QWidget без явного focusPolicy фокус не берёт — сюда
        # его отдаём осознанно, чтобы было куда деть начальный фокус диалога
        # (см. SubtitleCreatorDialog.__init__): без этого он проваливался в
        # QFontComboBox (первый в layout), а тот сам глотает пробел как ввод
        # текста раньше, чем до глобального шортката Space доходит очередь.
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay.addWidget(self.canvas, 1)
        self._overlay = _StyledSubtitleOverlay(self.canvas)

        transport = QHBoxLayout(); transport.setSpacing(6)
        # Порядок кнопок — как в основном плеере Монтажа (pctrl_row): Стоп,
        # кадр назад, Play, кадр вперёд.
        self.btn_stop = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaStop)
        self.btn_step_back = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.btn_play = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaPlay, accent=True)
        self.btn_step_fwd = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekForward)
        # make_icon_btn — общий стиль для ТЕКСТОВЫХ кнопок (padding 7px/14px,
        # прозрачная рамка только у accent) — на маленьких квадратных иконках
        # без текста это давало заметно разный по факту размер контента у play
        # (без рамки) и step-кнопок (с рамкой в 1px с каждой стороны), плюс
        # немного отличающийся размер значка. Явно выравниваем все четыре.
        for b in (self.btn_stop, self.btn_step_back, self.btn_play, self.btn_step_fwd):
            b.setFixedSize(30, 26)
            b.setIconSize(QSize(16, 16))
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 0px; border: 1px solid transparent; }")
        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time.setStyleSheet(f"color: {C['text2']}; font-size: 11px;")
        transport.addWidget(self.btn_stop)
        transport.addWidget(self.btn_step_back)
        transport.addWidget(self.btn_play)
        transport.addWidget(self.btn_step_fwd)
        transport.addWidget(self.slider, 1)
        transport.addWidget(self.lbl_time)
        lay.addLayout(transport)

        self.duration_s = 0.0
        self._active_cue_getter = None   # callable(pos_s) -> (text, style) | None
        # Диапазон показа/воспроизведения (абсолютное время исходника) — равен
        # обрезке, выделенной в Монтаже, а не всему видео (см. set_range).
        # Тайминги реплик остаются АБСОЛЮТНЫМИ (как и весь остальной таймлайн
        # монтажа) — так они совпадают и с превью, и со вшиванием (output-seek).
        self._range_start = 0.0
        self._range_end = None
        # Цель seek(), отложенная до тех пор, пока плеер реально не загрузит
        # медиа (см. seek()/_on_media_status) — до этого setPosition()
        # ненадёжен: durationChanged может прилететь ДО готовности пайплайна,
        # и любой seek к этому моменту backend молча роняет/переопределяет —
        # позиция откатывается на 0 при переходе Loading→Loaded→Buffered.
        self._pending_seek = None
        self._media_ready = False
        # Отдельный немой (без видео) плеер для короткого звукового блипа при
        # покадровом шаге (WASD/стрелки) — как _scrub_audio_blip в EditTab.
        # Через ОСНОВНОЙ self.player звук на паузе не идёт (setPosition на
        # паузе не проигрывает буфер), а короткий play()/pause() на painted-
        # холсте (VideoCanvas) даёт мерцание/скачок кадра — отдельный плеер
        # (видео не подключено ни к какому sink'у) звучит без побочных эффектов.
        self._src_path = None
        self._blip_player = None
        self._blip_output = None
        self._blip_timer = None
        # Дорожка звука превью — та же, что выбрана в Монтаже, а не дефолтная
        # первая дорожка источника (см. set_audio_selection/_on_media_status).
        self._audio_track_index = None
        self._ext_audio_path = None
        self._ext_audio_player = None
        self._ext_audio_output = None

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoSink(self.canvas.videoSink())
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop)
        fps_guess = 25
        self._step_s = 1.0 / fps_guess
        self.btn_step_back.clicked.connect(lambda: self.step_ms(-1000 // fps_guess))
        self.btn_step_fwd.clicked.connect(lambda: self.step_ms(1000 // fps_guess))
        self.slider.sliderMoved.connect(self._on_slider_seek)

    def set_active_cue_provider(self, fn):
        """fn(pos_s) -> (text, style_dict) | None — диалог передаёт свою логику
        поиска активной реплики (учитывает live-правки в списке реплик)."""
        self._active_cue_getter = fn

    def set_audio_selection(self, track_index=None, ext_path=None):
        """Звук превью — та же дорожка, что выбрана в Монтаже (cmb_audio), а
        не первая дефолтная дорожка source_path. track_index — относительный
        индекс встроенной дорожки (см. EditTab._audio_entries); ext_path —
        путь внешней озвучки (тогда звук самого видео глушится, играет
        отдельный синхронный плеер — как _ensure_ext_audio_player в EditTab).
        Вызывать ДО load() или сразу после — применяется в _on_media_status,
        когда пайплайн реально готов принимать setActiveAudioTrack/позицию."""
        self._audio_track_index = track_index
        self._ext_audio_path = ext_path

    def load(self, path):
        self._src_path = str(path)
        self._pending_seek = self._range_start
        self._media_ready = False
        try:
            self.player.setSource(QUrl.fromLocalFile(str(path)))
        except Exception:
            pass
        # Подстраховка: на некоторых файлах/бэкендах (особенно с HW-декодом)
        # один seek+pause на первом «готовом» статусе иногда не успевает
        # протолкнуть кадр в VideoSink вовремя — кадр так и не появляется, пока
        # пользователь сам не потрогает плеер. Несколько раз повторяем
        # seek+pause в первые ~2с после загрузки, пока кадр не появится.
        self._frame_watchdog_tries = 0
        if not hasattr(self, '_frame_watchdog'):
            self._frame_watchdog = QTimer(self)
            self._frame_watchdog.setInterval(150)
            self._frame_watchdog.timeout.connect(self._on_frame_watchdog)
        self._frame_watchdog.start()

    def _on_frame_watchdog(self):
        self._frame_watchdog_tries += 1
        if self.canvas._frame_img is not None:
            self._frame_watchdog.stop()
            return
        if self._frame_watchdog_tries > 14:
            self._frame_watchdog.stop()
            return
        if not self._media_ready:
            return
        try:
            cur = self.player.position()
            # setPosition на ТО ЖЕ САМОЕ значение бэкенд может тихо счесть
            # no-op'ом и не запросить новый кадр — небольшой чёт/нечет джиттер
            # гарантирует РЕАЛЬНОЕ изменение позиции перед возвратом на место.
            jitter = 1 if (self._frame_watchdog_tries % 2) else -1
            self.player.setPosition(max(0, cur + jitter))
            self.player.setPosition(cur)
            self.player.pause()
        except Exception:
            pass

    def set_range(self, start_s, end_s):
        """Ограничивает показ/скраб/воспроизведение диапазоном [start_s, end_s]
        (абсолютное время исходника) — тем самым, что выделен в Монтаже."""
        self._range_start = max(0.0, float(start_s))
        self._range_end = (max(self._range_start + 0.05, float(end_s))
                            if end_s is not None else None)
        self.seek(self._range_start)

    def _range_bounds(self):
        rs = self._range_start
        re_ = self._range_end if self._range_end is not None else self.duration_s
        return rs, max(rs + 0.05, re_)

    def _on_duration(self, dur_ms):
        self.duration_s = max(0.0, dur_ms / 1000.0)
        self.durationChanged.emit(self.duration_s)

    def _on_media_status(self, status):
        # durationChanged может прилететь РАНЬШЕ, чем пайплайн реально готов
        # принимать seek (иногда даже пока status ещё LoadingMedia) — надёжный
        # момент «можно сикать» — первый переход в Loaded/Buffering/Buffered.
        # Более ранние seek() (см. set_range/load) до сих пор только копились
        # в _pending_seek — применяем накопленную цель здесь.
        if self._media_ready:
            return
        ready_states = (QMediaPlayer.MediaStatus.LoadedMedia,
                        QMediaPlayer.MediaStatus.BufferingMedia,
                        QMediaPlayer.MediaStatus.BufferedMedia)
        if status not in ready_states:
            return
        self._media_ready = True
        if self._audio_track_index is not None:
            try:
                self.player.setActiveAudioTrack(self._audio_track_index)
            except Exception:
                pass
        if self._pending_seek is not None:
            target = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(int(max(0.0, target) * 1000))
        self.player.pause()
        self._sync_play_icon()
        if self._ext_audio_path:
            self._start_ext_audio_preview()

    def _start_ext_audio_preview(self):
        """Внешняя озвучка выбрана в Монтаже — глушим звук самого видео и
        играем отдельный синхронный плеер поверх него (как _ensure_ext_audio_
        player в EditTab), иначе превью звучало бы дорожкой из видеофайла."""
        try:
            self.audio_output.setMuted(True)
        except Exception:
            pass
        if self._ext_audio_player is None:
            self._ext_audio_player = QMediaPlayer(self)
            self._ext_audio_output = QAudioOutput(self)
            self._ext_audio_player.setAudioOutput(self._ext_audio_output)
        try:
            self._ext_audio_output.setVolume(self.audio_output.volume())
            self._ext_audio_player.setSource(QUrl.fromLocalFile(self._ext_audio_path))
            self._ext_audio_player.setPosition(self.player.position())
        except Exception:
            pass

    def _on_slider_seek(self, v):
        rs, re_ = self._range_bounds()
        self.seek(rs + (v / 1000.0) * (re_ - rs))

    def _on_position(self, pos_ms):
        pos_s = pos_ms / 1000.0
        rs, re_ = self._range_bounds()
        if pos_s >= re_ - 0.02:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause(); self._sync_play_icon()
            pos_s = re_
        span = max(0.001, re_ - rs)
        if not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int(max(0.0, min(1.0, (pos_s - rs) / span)) * 1000))
            self.slider.blockSignals(False)
        self.lbl_time.setText(f"{s_to_time(pos_s)} / {s_to_time(re_)}")
        self._refresh_subtitle(pos_s)
        self.positionChanged.emit(pos_s)

    def _refresh_subtitle(self, pos_s):
        text, style = "", None
        if self._active_cue_getter is not None:
            found = self._active_cue_getter(pos_s)
            if found:
                text, style = found
        self._sync_overlay_geometry()
        self._overlay.set_content(text, style)

    def _sync_overlay_geometry(self):
        try:
            self._overlay.setGeometry(self.canvas.video_rect())
        except Exception:
            pass

    def seek(self, pos_s):
        # Пока пайплайн не готов (см. _on_media_status), setPosition() молча
        # роняется/переопределяется бэкендом — копим цель, применяем позже.
        if not self._media_ready:
            self._pending_seek = pos_s
            return
        try:
            self.player.setPosition(int(max(0.0, pos_s) * 1000))
        except Exception:
            pass
        if self._ext_audio_player is not None:
            try:
                self._ext_audio_player.setPosition(int(max(0.0, pos_s) * 1000))
            except Exception:
                pass

    def position(self):
        try:
            return self.player.position() / 1000.0
        except Exception:
            return 0.0

    def _sync_play_icon(self):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        std = (QStyle.StandardPixmap.SP_MediaPause if playing
               else QStyle.StandardPixmap.SP_MediaPlay)
        self.btn_play.setIcon(QApplication.style().standardIcon(std))

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            if self._ext_audio_player is not None:
                self._ext_audio_player.pause()
        else:
            rs, re_ = self._range_bounds()
            if self.position() >= re_ - 0.02:
                self.seek(rs)
            self.player.play()
            if self._ext_audio_player is not None:
                self._ext_audio_player.setPosition(self.player.position())
                self._ext_audio_player.play()
        self._sync_play_icon()

    def step_ms(self, delta_ms):
        self.player.pause(); self._sync_play_icon()
        if self._ext_audio_player is not None:
            self._ext_audio_player.pause()
        rs, re_ = self._range_bounds()
        target = max(rs, min(re_, self.position() + delta_ms / 1000.0))
        self.seek(target)
        self._play_step_blip(target)

    def _ensure_blip_player(self):
        if self._blip_player is None:
            self._blip_player = QMediaPlayer(self)
            self._blip_output = QAudioOutput(self)
            self._blip_player.setAudioOutput(self._blip_output)
        try:
            self._blip_output.setVolume(self.audio_output.volume())
        except Exception:
            pass
        cur = self._blip_player.source().toLocalFile()
        if self._src_path and cur != self._src_path:
            try:
                self._blip_player.setSource(QUrl.fromLocalFile(self._src_path))
            except Exception:
                pass
        return self._blip_player

    def _play_step_blip(self, pos_s):
        """Короткий звуковой блип (~150мс) в новой позиции покадрового шага."""
        if not self._src_path:
            return
        player = self._ensure_blip_player()
        try:
            player.setPosition(int(max(0.0, pos_s) * 1000))
            player.play()
        except Exception:
            return
        if self._blip_timer is None:
            self._blip_timer = QTimer(self)
            self._blip_timer.setSingleShot(True)
            self._blip_timer.timeout.connect(lambda: player.pause())
        self._blip_timer.start(150)

    def stop(self):
        self.player.stop()
        if self._ext_audio_player is not None:
            self._ext_audio_player.stop()
        # player.stop() сбрасывает позицию на АБСОЛЮТНЫЙ 0 (начало всего файла),
        # а не на начало выделенного диапазона — доводим до rs, как и положено
        # в ограниченном диапазоном превью.
        rs, _re = self._range_bounds()
        self.seek(rs)
        self._sync_play_icon()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._sync_overlay_geometry()
