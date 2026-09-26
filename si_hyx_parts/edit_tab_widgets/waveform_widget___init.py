# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget: __init__. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def __init__(self, parent=None):
    super(_api.WaveformWidget, self).__init__(parent)
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
