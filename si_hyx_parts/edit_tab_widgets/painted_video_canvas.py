# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class _PaintedVideoCanvas(_api.QWidget):
    """Холст видео на ЦП: сам рисует кадры (QVideoSink → frame.toImage() →
    QPainter) и накладывает субтитры ПРЯМО В КАДР, как VLC. Кадр вписывается с
    сохранением пропорций (letterbox). Совместим по API субтитров с
    SubtitleOverlay.

    ВНИМАНИЕ: во вкладке «Монтаж» этот класс больше НЕ используется — там кадр
    выводит GPU-путь (VideoCanvas ниже: QQuickWidget + QML VideoOutput), потому
    что toImage() каждого кадра занимал главный поток на 8-9 мс при бюджете
    кадра 16.7 мс (1080p60), и вкладка «лагала». Здесь остался ЦП-путь для
    мини-плеера диалога субтитров (_SubtitlePreview): у него поверх холста живёт
    обычный дочерний виджет-оверлей (_StyledSubtitleOverlay), и переезд на Quick
    ему ничего не даёт.

    Вся логика, не связанная с САМИМ выводом кадра (пин кадра, часы кадра,
    граница OUT, кадрирование, накладки, трек-превью, зум/панорама, мышь), живёт
    здесь же — GPU-холст наследует её и переопределяет только вывод."""

    # Кадр пришёл с PTS за границей OUT (см. set_play_bound) — плеер надо ставить
    # на паузу ДО показа этого кадра (защита от проскока правой границы).
    boundaryReached = _api.pyqtSignal()
    # Кадрирование видео завершено кнопкой «Применить»/«Отмена» на холсте (как в
    # «Редактировании фото») — вкладка снимает чек с кнопки «Кадрировать».
    cropApplied = _api.pyqtSignal()
    cropCancelled = _api.pyqtSignal()
    # Предпросмотр привязки к объекту снят с холста (Esc). Рендер в файл делает
    # обычная кнопка экспорта «Обрезать» — отдельной кнопки «Применить» нет.
    trackCancelled = _api.pyqtSignal()
    # Наложенные картинки: состав списка изменился (добавили/удалили) либо слой
    # подвинули/растянули/повернули мышью — вкладка обновляет список слоёв.
    overlaysChanged = _api.pyqtSignal()
    overlaySelected = _api.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
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

    def _update_crop_buttons(self):
        """Показывает/прячет и позиционирует «Применить/Отмена» у рамки (плавающая
        панель, как в Photoshop). Зовётся при любом изменении рамки/зума/размера."""
        show = (self._crop_mode and self.has_crop()
                and self._has_frame())
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
        # Правка слоёв: Delete убирает выбранную картинку, Esc выходит из режима
        # (сами картинки остаются), Ctrl+стрелки двигают на 1/200 кадра.
        # ИМЕННО Ctrl+стрелки: голые ←/→ заняты покадровым шагом, и он идёт
        # через QAction (WidgetWithChildrenShortcut), то есть срабатывает РАНЬШЕ
        # keyPressEvent холста — обработчик на голой стрелке был бы мёртвым.
        if self._ovl_edit and not self._crop_mode and self._ovls:
            k = ev.key()
            if k == _api.Qt.Key.Key_Delete:
                self.remove_image_overlay(self._ovl_sel); ev.accept(); return
            if k == _api.Qt.Key.Key_Escape:
                self.set_overlay_edit(False); ev.accept(); return
            step = 0.005
            d = ({_api.Qt.Key.Key_Left: (-step, 0.0), _api.Qt.Key.Key_Right: (step, 0.0),
                  _api.Qt.Key.Key_Up: (0.0, -step), _api.Qt.Key.Key_Down: (0.0, step)}.get(k)
                 if (ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier) else None)
            if d is not None and 0 <= self._ovl_sel < len(self._ovls):
                self._ovls[self._ovl_sel].move_by(*d)
                self.update(); self.overlaysChanged.emit(); ev.accept(); return
        if self._trk is not None and not self._crop_mode:
            if ev.key() == _api.Qt.Key.Key_Escape:
                self.trackCancelled.emit(); ev.accept(); return
        if self._crop_mode and self.has_crop():
            if ev.key() == _api.Qt.Key.Key_Escape:
                self.cancel_crop(); ev.accept(); return
            if ev.key() in (_api.Qt.Key.Key_Return, _api.Qt.Key.Key_Enter):
                self.apply_crop(); ev.accept(); return
        super().keyPressEvent(ev)

    def videoSink(self):
        return self._sink

    def setAspectRatioMode(self, *a, **k):   # совместимость с QVideoWidget
        pass

    def clear_frame(self):
        self._frame_img = None
        self.clear_frame_pin()
        self._last_pts_us = -1
        self._last_frame_at = 0.0
        self.update()

    def set_static_image(self, qimg):
        """Показывает СТАТИЧНУЮ картинку на холсте (режим «картинка → видео»):
        кадр рисуется как обычный видеокадр, но не от плеера, а напрямую. Сбрасывает
        субтитры/зум, чтобы картинка вписалась целиком."""
        self._text = ""
        self._image = None
        self._audio_only_msg = ""
        self.clear_frame_pin()
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
        changed = (self._zoom != 1.0) or (self._pan != _api.QPoint(0, 0))
        self._zoom = 1.0
        self._pan = _api.QPoint(0, 0)
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

    def _has_frame(self):
        """Стоит ли сейчас на холсте кадр. Здесь это просто «есть ЦП-копия»;
        GPU-холст переопределяет — там пиксели кадра в ЦП обычно не приезжают
        вовсе, а признак кадра — известный размер (см. VideoCanvas)."""
        return self._frame_img is not None

    def _frame_size(self):
        """Размер кадра в пикселях (QSize) — от него считается letterbox."""
        img = self._frame_img
        return img.size() if img is not None else _api.QSize()

    def _base_video_rect(self):
        """Прямоугольник кадра при зуме 100% (letterbox по пропорциям)."""
        w, h = self.width(), self.height()
        fs = self._frame_size()
        fw, fh = fs.width(), fs.height()
        if fw <= 0 or fh <= 0 or w <= 0 or h <= 0:
            return _api.QRect(0, 0, max(0, w), max(0, h))
        scale = min(w / fw, h / fh)
        rw = max(1, int(fw * scale))
        rh = max(1, int(fh * scale))
        return _api.QRect((w - rw) // 2, (h - rh) // 2, rw, rh)

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
        self._pan = _api.QPoint(int(x), int(y))

    def wheelEvent(self, ev):
        # Зум только с зажатым Ctrl (как в редакторах) и при наличии кадра.
        if (ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier
                and self._has_frame()):
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
                self._pan = _api.QPoint(0, 0)
            else:
                cx = new_left + new_w / 2.0
                cy = new_top + new_h / 2.0
                self._pan = _api.QPoint(int(cx - base.center().x()),
                                   int(cy - base.center().y()))
                self._clamp_pan()
            self._update_crop_buttons()   # рамка/кнопки следуют за зумом
            self.update()
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        if (self._crop_mode and ev.button() == _api.Qt.MouseButton.LeftButton
                and self._has_frame()):
            handle = self._crop_handle_at(ev.position())
            if handle is not None:
                # Захватили ручку/тело существующей рамки — тянем её.
                self._crop_drag = handle
                self._crop_anchor = self._widget_to_norm(ev.position(), clamp=False)
                self._crop_start_rect = _api.QRectF(self._crop_norm)
            else:
                # Клик вне рамки — рисуем НОВУЮ рамку от этой точки (тянем угол br).
                n = self._widget_to_norm(ev.position())
                if n is not None:
                    self._crop_norm = _api.QRectF(n.x(), n.y(), 0.0, 0.0)
                    self._crop_drag = 'br'
                    self._crop_anchor = n
                    self._crop_start_rect = _api.QRectF(self._crop_norm)
            self._update_crop_buttons()
            self.update()
            ev.accept()
            return
        if (self._ovl_edit and self._ovls and self._has_frame()
                and ev.button() == _api.Qt.MouseButton.LeftButton):
            vr = _api.QRectF(self.video_rect())
            i, handle = self._ovl_hit(ev.position(), vr)
            if i >= 0:
                if i != self._ovl_sel:
                    self._ovl_sel = i
                    self.overlaySelected.emit(i)
                self._ovl_drag = {'i': i, 'handle': handle,
                                  'pos': _api.QPointF(ev.position()),
                                  'rect': _api.QRectF(self._ovls[i].rect),
                                  'angle': self._ovls[i].angle}
                self.setCursor(self._ovl_cursor(handle))
                self.update()
                ev.accept()
                return
        if self._zoom > 1.0 and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._crop_mode and self._has_frame():
            if self._crop_drag and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
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
        if self._ovl_edit and self._ovls and self._has_frame():
            if self._ovl_drag is not None and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
                self._ovl_drag_to(ev.position(), _api.QRectF(self.video_rect()))
                ev.accept()
                return
            if not (ev.buttons() & _api.Qt.MouseButton.LeftButton):
                _i, _h = self._ovl_hit(ev.position(), _api.QRectF(self.video_rect()))
                self.setCursor(self._ovl_cursor(_h))
        if self._panning and self._pan_last is not None:
            d = ev.position() - self._pan_last
            self._pan_last = ev.position()
            self._pan = _api.QPoint(self._pan.x() + int(d.x()),
                               self._pan.y() + int(d.y()))
            self._clamp_pan()
            self.update()
            ev.accept()
            return
        super().mouseMoveEvent(ev)

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
        super().mouseReleaseEvent(ev)

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

    def paintEvent(self, ev):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), self._bg)
        img = self._frame_img
        if img is not None and not img.isNull():
            vr = self.video_rect()
            # Во время протяжки/воспроизведения — без сглаживания (быстрее, кадр всё
            # равно сейчас сменится); на устоявшемся стоп-кадре — со сглаживанием
            # (качество).
            p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform,
                            not (self._scrub_active or self._playing))
            p.drawImage(vr, img)
            self._paint_overlays(p, vr)
        elif self._audio_only_msg:
            self._paint_audio_only(p)
        p.end()


_PaintedVideoCanvas.__module__ = _api.__name__
_api._PaintedVideoCanvas = _PaintedVideoCanvas
