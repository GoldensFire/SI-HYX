# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SeekSlider. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


# ─── Полоса воспроизведения с мгновенной перемоткой по клику ────────────────────
class SeekSlider(_api.QSlider):
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
        self._seek_flush_timer = _api.QTimer(self)
        self._seek_flush_timer.setSingleShot(True)
        self._seek_flush_timer.timeout.connect(self._flush_pending_seek)

    def is_user_seeking(self):
        return self._seeking

    def _emit_seek(self, v):
        """Троттлит sliderMoved во время протяжки (см. _SEEK_THROTTLE_S); клик и
        отпускание кнопки — всегда мгновенно, без троттлинга."""
        now = _api.time.monotonic()
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
            self._last_seek_emit = _api.time.monotonic()
            v, self._seek_pending_v = self._seek_pending_v, None
            self.sliderMoved.emit(v)

    def _value_at(self, x):
        return _api.slider_value_at(self, x)

    def mousePressEvent(self, ev):
        if (ev.button() == _api.Qt.MouseButton.LeftButton
                and self.orientation() == _api.Qt.Orientation.Horizontal):
            self._seeking = True
            self._last_seek_emit = _api.time.monotonic()  # свежее окно троттлинга для нового драга
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
                and self.orientation() == _api.Qt.Orientation.Horizontal):
            v = self._value_at(int(ev.position().x()))
            self.setValue(v)        # ручка следует за курсором мгновенно, без троттлинга
            self._emit_seek(v)      # а сам seek видео — троттлится (см. _SEEK_THROTTLE_S)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._seeking and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._seeking = False
            # Финальную позицию отпускания отдаём немедленно, не дожидаясь
            # отложенного флаша троттлера — иначе итоговый кадр «доедет» с задержкой.
            self._seek_flush_timer.stop()
            if self._seek_pending_v is not None:
                v, self._seek_pending_v = self._seek_pending_v, None
                self._last_seek_emit = _api.time.monotonic()
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
        if pv is None or self.orientation() != _api.Qt.Orientation.Horizontal:
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

SeekSlider.__module__ = _api.__name__
_api.SeekSlider = SeekSlider

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
        self._popup = _api.QWidget(None, _api.Qt.WindowType.ToolTip
                              | _api.Qt.WindowType.FramelessWindowHint)
        self._popup.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._popup.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setAttribute(_api.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = _api.QVBoxLayout(self._popup)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._img_lbl = _api.QLabel()
        self._img_lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._img_lbl.setStyleSheet("background:transparent;")
        self._img_lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self._time_lbl = _api.QLabel()
        self._time_lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._time_lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self._time_lbl.setStyleSheet(
            "color:#ffffff;background:rgba(11,11,18,0.88);border:1px solid #585b70;"
            "border-radius:5px;padding:2px 10px;font-weight:bold;font-size:13px;")
        lay.addWidget(self._img_lbl, 0, _api.Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._time_lbl, 0, _api.Qt.AlignmentFlag.AlignHCenter)
        self._th = _api._SeekThumbnailer()
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
            pm = _api.QPixmap.fromImage(img)
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
            gp = slider.mapToGlobal(_api.QPoint(local_x, 0))
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

SeekPreview.__module__ = _api.__name__
_api.SeekPreview = SeekPreview
