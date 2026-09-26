# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas: _update_crop_buttons. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


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
    super(_api._PaintedVideoCanvas, self).resizeEvent(ev)
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
    super(_api._PaintedVideoCanvas, self).keyPressEvent(ev)

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
    super(_api._PaintedVideoCanvas, self).wheelEvent(ev)

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
    super(_api._PaintedVideoCanvas, self).mousePressEvent(ev)

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
    super(_api._PaintedVideoCanvas, self).mouseMoveEvent(ev)
