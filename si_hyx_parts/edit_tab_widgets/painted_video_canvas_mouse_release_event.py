# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas: mouseReleaseEvent. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def mouseReleaseEvent(self, ev):
    if (self._crop_mode and self._crop_drag is not None
            and ev.button() == _api.Qt.MouseButton.LeftButton):
        self._crop_drag = None
        # Совсем крошечная рамка (случайный клик) = весь кадр, чтобы не остаться
        # с пустым выделением (правят дальше ручками или жмут «Применить»).
        n = self._crop_norm
        if n is not None and (n.width() < 0.02 or n.height() < 0.02):
            self._crop_norm = _api.QRectF(0.0, 0.0, 1.0, 1.0)
        else:
            self._crop_norm = _api.QRectF(n).normalized()
        self._update_crop_buttons()
        self.update()
        ev.accept()
        return
    if self._ovl_drag is not None and ev.button() == _api.Qt.MouseButton.LeftButton:
        self._ovl_drag = None
        self.update()
        # Геометрия слоя поменялась — вкладке пора пересобрать список/подпись.
        self.overlaysChanged.emit()
        ev.accept()
        return
    if self._panning and ev.button() == _api.Qt.MouseButton.LeftButton:
        self._panning = False
        self.unsetCursor()
        ev.accept()
        return
    super(_api._PaintedVideoCanvas, self).mouseReleaseEvent(ev)

def set_play_bound(self, out_seconds):
    """Граница OUT для блокировки кадров при воспроизведении (None — снять)."""
    self._bound_us = (int(out_seconds * 1_000_000)
                      if (out_seconds and out_seconds > 0) else None)

# ── Покадровый пин ───────────────────────────────────────────────────────
def arm_frame_pin(self, span_us):
    """Заявить, что холст стоит на кадре с pts из span_us=(lo, hi).

        Пока точной картинки нет, кадры плеера ПРИНИМАЮТСЯ (что-то лучше, чем
        застывший старый кадр); как только придёт точный (set_exact_frame),
        чужие pts начинают отбрасываться."""
    self._pin_span = span_us
    self._pin_has_img = False

def set_exact_frame(self, img, span_us=None, pts_us=None):
    """Показать точный кадр, декодированный вкладкой (FramePrefetcher).

        pts_us — время САМОГО кадра (начало показа): по нему вкладка ведёт метку
        таймлайна, поэтому оно должно быть точным, а не серединой диапазона."""
    if img is None or img.isNull():
        return
    if span_us is not None:
        self._pin_span = span_us
    self._pin_has_img = True
    self._frame_img = img
    if pts_us is not None and pts_us >= 0:
        self._last_pts_us = int(pts_us)
        self._last_frame_at = _api.time.monotonic()
    if self.isVisible():
        self.update()

def clear_frame_pin(self):
    """Снять пин — кадры плеера снова главные (воспроизведение)."""
    self._pin_span = None
    self._pin_has_img = False

def has_frame_pin(self):
    return self._pin_span is not None

def pinned_frame_pts(self):
    """pts (с) кадра, который РЕАЛЬНО пришпилен к холсту, иначе None.

        Пин без картинки (arm_frame_pin) — это только заявка «сейчас должен быть
        кадр N»: часы кадра при этом ещё показывают ПРОШЛЫЙ кадр — нередко вообще
        от прошлого файла (у аудио с обложкой точный кадр не придёт никогда).
        Поэтому наличия пина мало: требуем и картинку, и попадание часов в
        диапазон пина — тогда время кадра действительно = время на экране."""
    if self._pin_span is None or not self._pin_has_img:
        return None
    if self._last_pts_us < 0:
        return None
    lo, hi = self._pin_span
    if not (lo <= self._last_pts_us < hi):
        return None
    return self._last_pts_us / 1_000_000.0

def last_frame_pts(self):
    """pts последнего показанного кадра в секундах (None — кадров не было)."""
    return None if self._last_pts_us < 0 else (self._last_pts_us / 1_000_000.0)

def frame_clock_age(self):
    """Сколько секунд назад пришёл последний кадр (для проверки «часы живы»)."""
    if self._last_frame_at <= 0:
        return None
    return max(0.0, _api.time.monotonic() - self._last_frame_at)

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
    # Пин кадра N: пока на холсте стоит ТОЧНЫЙ кадр, чужие pts от плеера
    # (а после seek'а он нередко отдаёт соседний) на экран не пускаем —
    # иначе шаг стрелкой показывает не тот кадр, что просили.
    if self._pin_has_img and self._pin_span is not None:
        try:
            pts = frame.startTime() if frame is not None else -1
        except Exception:
            pts = -1
        if pts >= 0 and not (self._pin_span[0] <= pts < self._pin_span[1]):
            return
    img = None
    try:
        if frame is not None and frame.isValid():
            img = frame.toImage()
    except Exception:
        img = None
    if img is not None and not img.isNull():
        self._frame_img = img
        # Часы кадра — время картинки, которая СЕЙЧАС на экране.
        try:
            pts_us = frame.startTime()
        except Exception:
            pts_us = -1
        if pts_us is not None and pts_us >= 0:
            self._last_pts_us = pts_us
            self._last_frame_at = _api.time.monotonic()
        # Время для предпросмотра накладки берём из PTS самого кадра: так
        # накладка стоит ровно на своём кадре и при воспроизведении, и при
        # покадровой перемотке (positionChanged плеера приходит реже).
        if self._trk is not None:
            try:
                pts = frame.startTime()
            except Exception:
                pts = -1
            if pts is not None and pts >= 0:
                self._trk_t = pts / 1_000_000.0
        if self.isVisible():
            self.update()

def _paint_crop_overlay(self, p, vr):
    """Затемняет всё вне рамки кадрирования + рисует границу и сетку третей
        (в пределах видимой части кадра). vr — прямоугольник кадра на экране."""
    n = self._crop_norm
    r = _api.QRectF(vr.left() + n.left() * vr.width(),
               vr.top() + n.top() * vr.height(),
               n.width() * vr.width(), n.height() * vr.height())
    clip = _api.QRectF(vr).intersected(_api.QRectF(self.rect()))
    r = r.intersected(clip)
    p.save()
    p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, False)
    p.setPen(_api.Qt.PenStyle.NoPen)
    p.setBrush(_api.QColor(0, 0, 0, 120))
    p.drawRect(_api.QRectF(clip.left(), clip.top(), clip.width(), r.top() - clip.top()))
    p.drawRect(_api.QRectF(clip.left(), r.bottom(), clip.width(), clip.bottom() - r.bottom()))
    p.drawRect(_api.QRectF(clip.left(), r.top(), r.left() - clip.left(), r.height()))
    p.drawRect(_api.QRectF(r.right(), r.top(), clip.right() - r.right(), r.height()))
    p.setBrush(_api.Qt.BrushStyle.NoBrush)
    p.setPen(_api.QPen(_api.QColor(255, 255, 255, 80), 1))
    for i in (1, 2):
        gx = r.left() + r.width() * i / 3.0
        gy = r.top() + r.height() * i / 3.0
        p.drawLine(_api.QPointF(gx, r.top()), _api.QPointF(gx, r.bottom()))
        p.drawLine(_api.QPointF(r.left(), gy), _api.QPointF(r.right(), gy))
    p.setPen(_api.QPen(_api.QColor("#cdd6f4"), 1.5))
    p.drawRect(r)
    # Ручки по углам и серединам сторон (как в «Редактировании фото»).
    hs = 7.0
    p.setPen(_api.QPen(_api.QColor("#11111b"), 1))
    p.setBrush(_api.QColor("#cdd6f4"))
    cx, cy = (r.left() + r.right()) / 2.0, (r.top() + r.bottom()) / 2.0
    for hx, hy in ((r.left(), r.top()), (r.right(), r.top()),
                   (r.left(), r.bottom()), (r.right(), r.bottom()),
                   (cx, r.top()), (cx, r.bottom()),
                   (r.left(), cy), (r.right(), cy)):
        p.drawRect(_api.QRectF(hx - hs / 2, hy - hs / 2, hs, hs))
    p.restore()

def _paint_crop_indicator(self, p, vr):
    """Тонкая пунктирная рамка «вооружённого» кадрирования вне режима правки —
        показывает, какую область получит итоговое видео при «Обрезать»."""
    n = self._crop_norm
    r = _api.QRectF(vr.left() + n.left() * vr.width(),
               vr.top() + n.top() * vr.height(),
               n.width() * vr.width(), n.height() * vr.height())
    r = r.intersected(_api.QRectF(vr).intersected(_api.QRectF(self.rect())))
    p.save()
    p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, False)
    p.setBrush(_api.Qt.BrushStyle.NoBrush)
    p.setPen(_api.QPen(_api.QColor("#89b4fa"), 1.5, _api.Qt.PenStyle.DashLine))
    p.drawRect(r)
    p.restore()

def video_rect(self):
    """Прямоугольник, где реально показан кадр (letterbox + текущий зум/пан)."""
    base = self._base_video_rect()
    if not self._has_frame() or self._zoom == 1.0:
        return base
    rw = max(1, int(base.width() * self._zoom))
    rh = max(1, int(base.height() * self._zoom))
    cx = base.center().x() + self._pan.x()
    cy = base.center().y() + self._pan.y()
    return _api.QRect(int(cx - rw / 2.0), int(cy - rh / 2.0), rw, rh)

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

def _paint_overlays(self, p, vr):
    """Всё, что лежит ПОВЕРХ кадра: накладки-картинки → субтитры → рамка
        кадрирования → трек-превью. Порядок ровно такой же, как в фильтре
        экспорта (overlay → subtitles), поэтому плеер и файл совпадают.

        Вынесено из paintEvent отдельным методом: GPU-холст (VideoCanvas) сам
        кадр не рисует, но эти же слои кладёт поверх него в QML-сцене."""
    # Наложенные картинки — сразу поверх кадра и ПОД субтитрами.
    if self._ovls:
        self._paint_image_overlays(p, _api.QRectF(vr))
    # Субтитры рисуем в ВИДИМОЙ части кадра (пересечение зумированного vr
    # с областью виджета), а не во всём vr. Иначе при приближении кадра
    # низ vr уходит далеко за нижнюю границу виджета, и субтитры,
    # привязанные к низу кадра, «улетают» за экран (баг с приближением).
    sub_rect = vr.intersected(self.rect())
    if sub_rect.width() < 10 or sub_rect.height() < 10:
        sub_rect = self.rect()
    px = max(15, int(min(sub_rect.height(), self.height()) * 0.052))
    _api._paint_subtitle(p, sub_rect, self._text, px, self._image, self._image_pos)
    # Рамка кадрирования видео (как в «Редактировании фото»): в режиме
    # правки — затемнение/сетка/ручки, иначе (рамка «вооружена») — тонкая
    # пунктирная подсказка, что экспорт кадрируется по ней.
    if self._crop_mode and self._crop_norm is not None:
        self._paint_crop_overlay(p, vr)
    elif self._crop_norm is not None:
        self._paint_crop_indicator(p, vr)
    if self._trk is not None:
        self._paint_track_preview(p, vr)

def _paint_audio_only(self, p):
    """Видеоряда нет — иконка ноты и поясняющий текст по центру холста."""
    p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
    icon_px = max(28, int(min(self.width(), self.height()) * 0.16))
    pm = _api.get_icon_pixmap('fa5s.music', icon_px, _api.C['text3'])
    gap = 14
    font = p.font()
    font.setPointSize(11)
    font.setFamily("Segoe UI" if _api.os.name == 'nt' else "SF Pro Display")
    p.setFont(font)
    fm = _api.QFontMetrics(font)
    text_rect = fm.boundingRect(
        _api.QRect(0, 0, max(60, self.width() - 40), 1000),
        int(_api.Qt.AlignmentFlag.AlignHCenter | _api.Qt.TextFlag.TextWordWrap),
        self._audio_only_msg)
    ih = (icon_px + gap) if (pm is not None and not pm.isNull()) else 0
    total_h = ih + text_rect.height()
    top = (self.height() - total_h) // 2
    if pm is not None and not pm.isNull():
        ix = (self.width() - icon_px) // 2
        p.drawPixmap(_api.QRect(ix, top, icon_px, icon_px), pm)
    p.setPen(_api.QPen(_api.QColor(_api.C['text3'])))
    tr = _api.QRect((self.width() - text_rect.width()) // 2, top + ih,
               text_rect.width(), text_rect.height())
    p.drawText(tr, int(_api.Qt.AlignmentFlag.AlignHCenter
                       | _api.Qt.TextFlag.TextWordWrap), self._audio_only_msg)
