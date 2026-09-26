# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _notify_busy_rename. Public namespace: edit_tab."""
import edit_tab as _api


def _notify_busy_rename(self, wanted, saved):
    """Сообщает, что целевой файл был занят и обрезка сохранена под другим
        именем (а не потеряна с ошибкой WinError 32)."""
    msg = (f"Файл «{_api.os.path.basename(wanted)}» был занят другим процессом "
           f"(скорее всего, его перекодирует вкладка «Обработка»).\n\n"
           f"Обрезка сохранена под именем «{_api.os.path.basename(saved)}».")
    try:
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(msg.replace("\n\n", " "))
    except Exception:
        pass
    try:
        _api.msgbox_information(self, "Файл был занят", msg)
    except Exception:
        pass

@staticmethod
def _fmt_mmss(sec):
    sec = int(max(0, sec))
    return f"{sec // 60:d}:{sec % 60:02d}"

def _report_progress(self, pct, text=""):
    """Прогресс вкладки → общий прогрессбар окна (main.pbar). В standalone-
        режиме (без главного окна) обновляет собственный скрытый прогрессбар.
        pct < 0 → неопределённый («busy») режим — полоса пульсирует."""
    busy = (pct is not None and pct < 0)
    if not busy:
        pct = int(max(0, min(100, pct)))
    try:
        if self.main is not None and hasattr(self.main, 'update_global_progress'):
            if not busy and pct <= 0 and hasattr(self.main, 'clear_global_result'):
                self.main.clear_global_result()
            self.main.update_global_progress(
                -1 if busy else pct,
                text or ("Монтаж" if busy else ("Готово" if pct >= 100 else "Монтаж")))
            return
    except Exception:
        pass
    try:
        if busy:
            self.progress.setRange(0, 0)
        else:
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
            self.progress.setValue(pct)
    except Exception:
        pass

# ── Видеовыход и метод субтитров ─────────────────────────────────────────
def _read_subs_in_frame_pref(self):
    """Метод субтитров теперь зафиксирован значением по умолчанию (рендер
        прямо в кадр, как в VLC) — настройка убрана из UI по просьбе пользователя."""
    return True

def _build_video_output(self):
    """Создаёт виджет видео под текущий метод субтитров и подключает плеер.
        frame-режим: VideoCanvas (рисуем кадр сами + субтитры в кадр).
        overlay-режим: QVideoWidget (нативная поверхность) + окно-оверлей."""
    if self._subs_in_frame:
        self.video_widget = _api.VideoCanvas()
        try:
            self.player.setVideoSink(self.video_widget.videoSink())
        except Exception:
            pass
    else:
        self.video_widget = _api.QVideoWidget()
        try:
            self.video_widget.setAspectRatioMode(_api.Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass
        self.player.setVideoOutput(self.video_widget)
    self.video_widget.setStyleSheet(f"background: {_api.C['bg']};")
    # Анти-overshoot: VideoCanvas сам ловит кадр за OUT по PTS → просит паузу.
    if isinstance(self.video_widget, _api.VideoCanvas):
        self.video_widget.boundaryReached.connect(self._on_play_boundary)
        # Кадрирование завершено кнопкой на холсте — снимаем чек с «Кадрировать».
        self.video_widget.cropApplied.connect(self._on_crop_applied)
        self.video_widget.cropCancelled.connect(self._on_crop_cancelled)
        self.video_widget.overlaysChanged.connect(self._on_overlays_changed)
        self.video_widget.overlaySelected.connect(self._on_overlay_picked)
    try:
        self.video_widget.setAcceptDrops(True)
        self.video_widget.installEventFilter(self)
    except Exception:
        pass
    # Кадр выводит сцена Qt Quick (GPU). Если она не поднялась (нет модулей
    # в сборке, не создался графический контекст), холст молча переходит на
    # ЦП-отрисовку — она в разы дороже, и об этом надо знать, а не гадать,
    # почему «Монтаж вдруг лагает».
    if (isinstance(self.video_widget, _api.VideoCanvas)
            and getattr(self.video_widget, "_quick", None) is None):
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Монтаж: сцена Qt Quick не поднялась — кадры "
                              "рисуются на ЦП (заметно медленнее)")
        except Exception:
            pass

def _prepare_sub_display(self):
    """Готовит цель для показа субтитров: окно-оверлей (overlay-режим) либо
        ничего (frame-режим — рисует сам холст)."""
    if self._subs_in_frame:
        return
    self._ensure_overlay()
    self._position_overlay()

def _hide_sub_display(self):
    """Сбрасывает показанные субтитры в текущей цели."""
    if self._subs_in_frame:
        vw = self.video_widget
        if isinstance(vw, _api.VideoCanvas):
            vw.clear_subtitle()
    else:
        ov = self.sub_overlay
        if ov is not None:
            ov.clear_subtitle(); ov.hide()

def _adjust_video_height(self):
    """Подгоняет окно видео ровно под аспект кадра (без чёрных полей внутри
        QVideoWidget), вписывая его в доступную область. «Максимум 16:9»: если
        кадр шире 16:9, бокс не растягивается выше этого соотношения по высоте."""
    # В полноэкранном режиме видео живёт в отдельном окне — не навязываем ему
    # фиксированный размер контейнера вкладки.
    if getattr(self, "_fs_window", None) is not None:
        return
    try:
        cont = getattr(self, "video_container", None)
        cw = cont.width() if cont is not None else self.video_widget.width()
        ch = cont.height() if cont is not None else int(self.height() * 0.55)
        if cw <= 0:
            cw = max(320, int(self.width() * 0.55))
        if ch <= 0:
            ch = max(180, int(self.height() * 0.55))
        # Кадр не должен занимать слишком много по высоте на больших окнах.
        ch = min(ch, int(self.height() * 0.62)) or ch
        aspect = self.video_aspect if (self.video_aspect and self.video_aspect > 0) else (16.0 / 9.0)
        # «Не более 16:9»: ограничиваем минимальный аспект (для очень узких
        # вертикалок бокс не становится чрезмерно высоким — режется по ch).
        fit_w = cw
        fit_h = int(round(fit_w / aspect))
        if fit_h > ch:
            fit_h = ch
            fit_w = int(round(fit_h * aspect))
        fit_w = max(80, min(fit_w, cw))
        fit_h = max(60, min(fit_h, ch))
        self.video_widget.setMinimumSize(fit_w, fit_h)
        self.video_widget.setMaximumSize(fit_w, fit_h)
        # Оверлей субтитров подгоняем под экранную область видео.
        self._position_overlay()
    except Exception:
        pass

# ── Resize ────────────────────────────────────────────────────────────
def resizeEvent(self, ev):
    super(_api.EditTab, self).resizeEvent(ev)
    if self._ready:
        self._adjust_video_height()

def showEvent(self, ev):
    super(_api.EditTab, self).showEvent(ev)
    # Пересчитать размер холста ДО отрисовки — иначе виджет мигает старым
    # размером и лишь на resizeEvent долетает до нужного (визуальный сдвиг).
    if self._ready:
        self._adjust_video_height()
    # Вкладку показали (вернулись на «Монтаж») — вернуть оверлей субтитров.
    _api.QTimer.singleShot(0, self._position_overlay)
    # QTabWidget помнит, какой дочерний виджет был в фокусе на этой странице
    # в прошлый раз (например, кнопка «Открыть» или комбобокс «Режим
    # обрезки») и возвращает фокус ЕМУ при переключении на вкладку. Из-за
    # этого мгновенный Space сразу после переключения на «Монтаж» не играл
    # видео (шорткат Space зарегистрирован на self), а активировал
    # сфокусированный виджет — жал кнопку/раскрывал комбобокс. Перехватываем
    # фокус на себя при каждом показе вкладки, чтобы Space гарантированно
    # доставался toggle_play, а не случайному виджету боковой панели.
    if self._ready:
        _api.QTimer.singleShot(0, self.setFocus)

def hideEvent(self, ev):
    super(_api.EditTab, self).hideEvent(ev)
    # Ушли с вкладки — прячем оверлей-окно, чтобы оно не висело поверх других.
    ov = getattr(self, "sub_overlay", None)
    if ov is not None:
        ov.hide()

def _adjust_video_aspect_once(self):
    self._adjust_video_height()

# ── Drag & Drop ───────────────────────────────────────────────────────
def enable_global_drag_drop(self):
    for w in self.findChildren(_api.QWidget):
        try:
            w.setAcceptDrops(True)
            w.installEventFilter(self)
        except Exception:
            pass
    self.installEventFilter(self)
