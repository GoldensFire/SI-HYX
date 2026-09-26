# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas: __init__. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def __init__(self, parent=None):
    super(_api._PaintedVideoCanvas, self).__init__(parent)
    self.setAttribute(_api.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    self.setAutoFillBackground(False)
    self._sink = _api.QVideoSink(self)
    self._sink.videoFrameChanged.connect(self._on_frame)
    self._bound_us = None          # граница OUT (µs) для блокировки кадров
    self._frame_img = None
    # ── Покадровая точность (см. edit_tab_frames.py) ──────────────────────
    # «Пин» — заявка «на холсте стоит кадр N»: пока он держится, кадры
    # плеера с ЧУЖИМ pts (а плеер после seek'а любит отдать соседний)
    # игнорируются, и на экране не может оказаться не тот кадр. Пин снимает
    # вкладка на воспроизведении (там кадры плеера и есть истина).
    self._pin_span = None          # (lo_us, hi_us) — pts, считающиеся кадром N
    self._pin_has_img = False      # точный кадр уже нарисован (не только заявка)
    # Часы кадра: pts последнего ПОКАЗАННОГО кадра. Это единственное время,
    # которое реально совпадает с картинкой на экране, поэтому по нему
    # вкладка и ведёт метку таймлайна во время воспроизведения.
    self._last_pts_us = -1
    self._last_frame_at = 0.0
    self._text = ""
    self._image = None
    self._image_pos = (0, 0)
    self._bg = _api.QColor(_api.C["bg"])
    # Текст-заглушка, когда у файла нет видеоряда (редактируем чистое аудио).
    self._audio_only_msg = ""
    # Зум/панорама превью (Ctrl+колесо приближает, ЛКМ-перетаскивание двигает).
    self._zoom = 1.0
    self._pan = _api.QPoint(0, 0)
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
    self._crop_apply_btn = _api.make_icon_btn("Применить", icon='fa5s.check', accent=True)
    self._crop_apply_btn.setParent(self)
    self._crop_apply_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self._crop_apply_btn.setToolTip("Применить кадрирование (Enter)")
    self._crop_apply_btn.clicked.connect(self.apply_crop)
    self._crop_cancel_btn = _api.make_icon_btn("Отмена", icon='fa5s.times')
    self._crop_cancel_btn.setParent(self)
    self._crop_cancel_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self._crop_cancel_btn.setToolTip("Отменить кадрирование (Esc)")
    self._crop_cancel_btn.clicked.connect(self.cancel_crop)
    # Предпросмотр привязки к объекту (как в монтажках вроде Filmora): путь
    # объекта уже посчитан, накладка рисуется поверх кадра ПРЯМО В ПЛЕЕРЕ —
    # можно смотреть и крутить, а в файл это попадёт обычным экспортом
    # («Обрезать»), поэтому своих кнопок у предпросмотра нет.
    self._trk = None            # словарь-задание (см. set_track_preview)
    self._trk_t = 0.0           # текущее время видео, с (из PTS кадра)
    # Наложенные картинки (edit_tab_overlay.ImageOverlay) — статичный слой
    # поверх кадра: перетаскивание, ручки размера, поворот. В файл их вшивает
    # экспорт («Обрезать») фильтром overlay=… по тем же долям кадра.
    self._ovls = []
    self._ovl_sel = -1
    self._ovl_edit = False
    self._ovl_drag = None
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
            self._crop_norm = _api.QRectF(0.0, 0.0, 1.0, 1.0)
        self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        self.setFocus()
    else:
        self._crop_drag = None
    self.setCursor(_api.Qt.CursorShape.CrossCursor if on else _api.Qt.CursorShape.ArrowCursor)
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
        if not on and self._has_frame():
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

def apply_crop(self):
    """«Применить»: фиксируем рамку (её прочитает экспорт/«Сохранить кадр»),
        выходим из режима правки. Полный кадр трактуем как сброс кадрирования."""
    n = self._crop_norm
    if n is not None and n.width() >= 0.999 and n.height() >= 0.999:
        self._crop_norm = None     # рамка = весь кадр → кадрирования нет
    self._crop_mode = False
    self._crop_drag = None
    self.setCursor(_api.Qt.CursorShape.ArrowCursor)
    self._update_crop_buttons()
    self.update()
    self.cropApplied.emit()

def cancel_crop(self):
    """«Отмена»: сбрасываем рамку и выходим из режима правки."""
    self._crop_norm = None
    self._crop_mode = False
    self._crop_drag = None
    self.setCursor(_api.Qt.CursorShape.ArrowCursor)
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
    return _api.QPointF(nx, ny)

def _crop_rect_screen(self):
    """Текущая рамка кадрирования в ЭКРАННЫХ координатах (для ручек/кнопок)."""
    n = self._crop_norm
    vr = self.video_rect()
    if n is None or vr.width() <= 0:
        return _api.QRectF()
    return _api.QRectF(vr.left() + n.left() * vr.width(),
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
        'tl': _api.Qt.CursorShape.SizeFDiagCursor, 'br': _api.Qt.CursorShape.SizeFDiagCursor,
        'tr': _api.Qt.CursorShape.SizeBDiagCursor, 'bl': _api.Qt.CursorShape.SizeBDiagCursor,
        't': _api.Qt.CursorShape.SizeVerCursor,  'b': _api.Qt.CursorShape.SizeVerCursor,
        'l': _api.Qt.CursorShape.SizeHorCursor,  'r': _api.Qt.CursorShape.SizeHorCursor,
        'move': _api.Qt.CursorShape.SizeAllCursor,
    }
    return cur.get(handle, _api.Qt.CursorShape.CrossCursor)

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
        self._crop_norm = _api.QRectF(nl, nt, bw, bh)
        return
    x = min(max(npt.x(), 0.0), 1.0)
    y = min(max(npt.y(), 0.0), 1.0)
    if 'l' in d: l = min(x, r - minsz)
    if 'r' in d: r = max(x, l + minsz)
    if 't' in d: t = min(y, bo - minsz)
    if 'b' in d: bo = max(y, t + minsz)
    self._crop_norm = _api.QRectF(l, t, r - l, bo - t)

# ── Предпросмотр привязки к объекту ──────────────────────────────────────
def set_track_preview(self, spec):
    """Включает/выключает показ накладки, едущей за объектом.

        spec: словарь с готовым заданием (None — выключить):
          overlay  — QImage накладки в пикселях ИСХОДНОГО кадра;
          boxes    — траектория рамки (список [x, y, w, h], тоже в px исходника);
          src_w/src_h — размер исходного кадра (на холсте может идти прокси в
                     меньшем разрешении — пересчитываем по пропорции);
          fps, start_s, end_s, anchor, off (x, y), scale_with_box.
        Рендера здесь нет: это ровно то же вычисление позиции, что и в
        TrackOverlayWorker (общая функция overlay_top_left)."""
    self._trk = spec or None
    if self._trk is not None:
        b0 = (self._trk.get("boxes") or [[0, 0, 1, 1]])[0]
        self._trk["_base_area"] = max(1.0, float(b0[2]) * float(b0[3]))
    self.update()

def has_track_preview(self):
    return self._trk is not None

def set_track_time(self, t_s):
    """Время, на котором показываем накладку (секунды исходника)."""
    if self._trk is None:
        return
    t = max(0.0, float(t_s))
    if abs(t - self._trk_t) < 1e-4:
        return
    self._trk_t = t
    self.update()
