# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


# ─── Waveform Widget ──────────────────────────────────────────────────────────
class WaveformWidget(_api.QWidget):
    seekRequested       = _api.pyqtSignal(float)
    playSeekRequested   = _api.pyqtSignal(float)
    inSetRequested      = _api.pyqtSignal(float)
    outSetRequested     = _api.pyqtSignal(float)
    selectionChanged    = _api.pyqtSignal(float, float)
    viewChanged         = _api.pyqtSignal(float, float)
    interactionStarted  = _api.pyqtSignal()

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
        self.setFocusPolicy(_api.Qt.FocusPolicy.ClickFocus)
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
        self._anim_timer = _api.QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._cache: _api.QPixmap | None = None
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

        grad = _api.QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, _api.QColor(30, 30, 46))   # base
        grad.setColorAt(1.0, _api.QColor(24, 24, 37))   # mantle
        painter.fillRect(0, 0, w, h, _api.QBrush(grad))

        painter.setPen(_api.QPen(_api.QColor(69, 71, 90), 1))  # surface1
        painter.drawLine(0, int(mid), w, int(mid))

        if self.loading_text:
            dots = "." * self._anim_dots
            txt = f"{self.loading_text}{dots}"
            painter.setPen(_api.QPen(_api.QColor(137, 180, 250)))  # blue
            font = painter.font()
            font.setPointSize(10)
            font.setFamily("Segoe UI" if _api.os.name == 'nt' else "SF Pro Display")
            painter.setFont(font)
            painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter, txt)
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
                painter.setPen(_api.QPen(_api.QColor(108, 117, 161, alpha)))  # muted blue/overlay
                painter.drawLine(i, y1, i, y2)
        else:
            if self.duration > 0:
                painter.setPen(_api.QPen(_api.QColor(_api.C["text3"])))
                font = painter.font(); font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter, "Нет аудио данных")
            else:
                painter.setPen(_api.QPen(_api.QColor(_api.C["text3"])))
                font = painter.font(); font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter,
                                 "Перетащите видео или аудио файл сюда")

        painter.setPen(_api.QPen(_api.QColor(_api.C["border"]), 1))
        painter.drawLine(0, 0, w, 0)
        painter.drawLine(0, h - 1, w, h - 1)

        if self.duration <= 0:
            return

        x_in  = time_to_x(self.in_s)
        x_out = time_to_x(self.out_s)
        if x_out < x_in:
            x_in, x_out = x_out, x_in

        sel_w = max(1, x_out - x_in)
        painter.setBrush(_api.QBrush(_api.QColor(137, 180, 250, 28)))  # blue selection wash
        painter.setPen(_api.Qt.PenStyle.NoPen)
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
                painter.setPen(_api.QPen(_api.QColor(137, 180, 250, alpha)))  # blue
                painter.drawLine(i, y1, i, y2)

        painter.setPen(_api.QPen(_api.QColor(_api.C["red"]), 2))
        painter.drawLine(x_in, 0, x_in, h)
        painter.setPen(_api.QPen(_api.QColor(_api.C["green"]), 2))
        painter.drawLine(x_out, 0, x_out, h)

        handle_r = max(5, int(h * 0.055))
        painter.setBrush(_api.QBrush(_api.QColor(_api.C["red"])))
        painter.setPen(_api.QPen(_api.QColor(_api.C["bg"]), 1))
        painter.drawEllipse(_api.QPoint(x_in, int(mid)), handle_r, handle_r)
        painter.setBrush(_api.QBrush(_api.QColor(_api.C["green"])))
        painter.setPen(_api.QPen(_api.QColor(_api.C["bg"]), 1))
        painter.drawEllipse(_api.QPoint(x_out, int(mid)), handle_r, handle_r)

        painter.setPen(_api.QPen(_api.QColor(_api.C["text"])))
        font = painter.font(); font.setPointSize(6); font.setBold(True)
        painter.setFont(font)
        fm = _api.QFontMetrics(font)
        for label, x_pos, col in [("I", x_in, _api.C["red"]), ("O", x_out, _api.C["green"])]:
            lw = fm.horizontalAdvance(label)
            painter.setPen(_api.QPen(_api.QColor(col)))
            painter.drawText(x_pos - lw // 2, int(mid) + fm.ascent() // 2, label)

    def paintEvent(self, event):
        painter = _api.QPainter(self)
        painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        w = self.width(); h = self.height()

        # Cache key covers everything that affects static drawing.
        # Playhead and hover cursor are drawn dynamically on top.
        # Кэш рисуется в ФИЗИЧЕСКИХ пикселях экрана: картинка w×h при масштабе
        # Windows 125 % растягивалась, и текст на таймлайне выходил мыльным.
        dpr = max(1.0, float(self.devicePixelRatioF()))
        cache_key = (w, h, dpr, id(self.samples), len(self.samples),
                     self.duration, self.zoom, self.view_offset,
                     self.in_s, self.out_s, self.loading_text, self._anim_dots)
        if self._cache is None or self._cache_key != cache_key:
            self._cache = _api.QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
            self._cache.setDevicePixelRatio(dpr)
            self._cache_key = cache_key
            cp = _api.QPainter(self._cache)
            cp.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
            cp.setRenderHint(_api.QPainter.RenderHint.TextAntialiasing)
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
                painter.setPen(_api.QPen(_api.QColor(_api.C["playhead"]), 2, _api.Qt.PenStyle.SolidLine))
                painter.drawLine(x_ph, 0, x_ph, h)
                path = _api.QPainterPath()
                path.moveTo(x_ph - 5, 0)
                path.lineTo(x_ph + 5, 0)
                path.lineTo(x_ph, 8)
                path.closeSubpath()
                painter.setBrush(_api.QBrush(_api.QColor(_api.C["playhead"])))
                painter.setPen(_api.Qt.PenStyle.NoPen)
                painter.drawPath(path)

        # Hover cursor
        if self.hover_x is not None:
            hx = int(self.hover_x)
            painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 40), 1, _api.Qt.PenStyle.DotLine))
            painter.drawLine(hx, 0, hx, h)

    # ── Mouse events ───────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        # ПКМ — не сик/перетаскивание, а контекстное меню обрезки (его поднимает
        # customContextMenuRequested). Иначе правый клик дёргал бы плейхед.
        if ev.button() == _api.Qt.MouseButton.RightButton:
            ev.ignore(); return
        # Забираем клавиатурный фокус НА СЕБЯ: метод переопределён и не зовёт
        # super().mousePressEvent(), поэтому штатный перехват фокуса по ClickFocus
        # не срабатывает, и фокус оставался на нативной видео-поверхности
        # (исключена из WidgetWithChildrenShortcut) → Ctrl+Z/Ctrl+Y после
        # перетаскивания полоски не доходили до undo/redo.
        self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
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
        modifiers = _api.QApplication.keyboardModifiers()
        if not (modifiers & _api.Qt.KeyboardModifier.ControlModifier):
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
        _api.QToolTip.hideText(); self.tooltip_visible = False

    def leaveEvent(self, ev):
        self.hover_x = None; _api.QToolTip.hideText(); self.tooltip_visible = False; self.update()

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


WaveformWidget.__module__ = _api.__name__
_api.WaveformWidget = WaveformWidget
