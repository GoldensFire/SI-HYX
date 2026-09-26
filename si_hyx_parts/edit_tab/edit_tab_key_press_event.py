# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: keyPressEvent. Public namespace: edit_tab."""
import edit_tab as _api


def keyPressEvent(self, event):
    if event.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
        try:
            vk = event.nativeVirtualKey()
        except Exception:
            vk = 0
        if vk == self._VK_Z:
            self.redo() if (event.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier) else self.undo()
            event.accept()
            return
        if vk == self._VK_Y:
            self.redo()
            event.accept()
            return
        # Ctrl+S («Обрезать») — тот же баг, что и Ctrl+Z/Y на кириллице:
        # QShortcut("Ctrl+S") на переведённом коде клавиши не срабатывает.
        if vk == self._VK_S or event.key() == _api.Qt.Key.Key_S:
            self.start_cut()
            event.accept()
            return
    elif not (event.modifiers() & (_api.Qt.KeyboardModifier.AltModifier
                                    | _api.Qt.KeyboardModifier.ShiftModifier)):
        # WASD покадрового шага + F/I/O — по физической клавише
        # (nativeVirtualKey), с фолбэком на event.key() для латиницы (см.
        # register_shortcuts выше и _pan_dir_from_event в tabs.py — тот же приём).
        try:
            vk = event.nativeVirtualKey()
        except Exception:
            vk = 0
        if vk in (self._VK_A, self._VK_S) or event.key() in (_api.Qt.Key.Key_A, _api.Qt.Key.Key_S):
            self.step_frame_scrub(-1)
            event.accept()
            return
        if vk in (self._VK_D, self._VK_W) or event.key() in (_api.Qt.Key.Key_D, _api.Qt.Key.Key_W):
            self.step_frame_scrub(1)
            event.accept()
            return
        if vk == self._VK_F or event.key() == _api.Qt.Key.Key_F:
            self.toggle_fullscreen()
            event.accept()
            return
        if vk == self._VK_I or event.key() == _api.Qt.Key.Key_I:
            self.set_in_point()
            event.accept()
            return
        if vk == self._VK_O or event.key() == _api.Qt.Key.Key_O:
            self.set_out_point()
            event.accept()
            return
    super(_api.EditTab, self).keyPressEvent(event)

# ── Обрезка до точки воспроизведения (плейхеда) ─────────────────────────
def trim_start_to_playhead(self):
    """Ставит точку IN на текущую позицию воспроизведения (обрезает старт)."""
    if self.duration <= 0:
        return
    self.push_undo()
    # Берём время ПОКАЗАННОГО кадра, а не «сырую» позицию плеера: они могут
    # отличаться на доли кадра, а рез обязан совпадать с тем, что видно.
    t = self._clock_pos_s()
    new_in = max(0.0, min(t, self.duration))
    if new_in >= self.current_out:
        new_in = max(0.0, self.current_out - 0.04)
    self.set_in_out(new_in, self.current_out)
    # Возвращаем фокус на вкладку: если он был на нативной видео-поверхности
    # (overlay-режим, исключена из WidgetWithChildrenShortcut), Ctrl+Z после
    # обрезки иначе не доходил до undo. Кнопка с NoFocus фокус не перехватит.
    self.setFocus(_api.Qt.FocusReason.OtherFocusReason)

def trim_end_to_playhead(self):
    """Ставит точку OUT на текущую позицию воспроизведения (обрезает конец)."""
    if self.duration <= 0:
        return
    self.push_undo()
    t = self._clock_pos_s()
    new_out = max(0.0, min(t, self.duration))
    if new_out <= self.current_in:
        new_out = min(self.duration, self.current_in + 0.04)
    self.set_in_out(self.current_in, new_out)
    self.setFocus(_api.Qt.FocusReason.OtherFocusReason)

def _trim_ctx_menu(self, pos=None):
    """Контекстное меню аудио-визуализации (ПКМ): обрезка старт/конец до
        плейхеда. Сочетания показываются справа как подсказка (через \\t), но НЕ
        регистрируются повторно — настоящие хоткеи висят на QShortcut."""
    if self.duration <= 0:
        return
    menu = _api.QMenu(self)
    a_start = menu.addAction(
        f"Обрезать старт до точки воспроизведения\t{self.trim_start_seq}")
    a_start.triggered.connect(self.trim_start_to_playhead)
    a_end = menu.addAction(
        f"Обрезать конец до точки воспроизведения\t{self.trim_end_seq}")
    a_end.triggered.connect(self.trim_end_to_playhead)
    menu.exec(_api.QCursor.pos())

def get_trim_shortcuts(self):
    """(start_seq, end_seq) — для отображения/редактирования в Настройках."""
    return (self.trim_start_seq, self.trim_end_seq)

def set_trim_shortcuts(self, start_seq, end_seq, save=True):
    """Переназначает сочетания обрезки. Пустое значение → дефолт."""
    self.trim_start_seq = (start_seq or "Shift+C").strip() or "Shift+C"
    self.trim_end_seq   = (end_seq or "Shift+V").strip() or "Shift+V"
    try:
        if getattr(self, "_sc_trim_start", None) is not None:
            self._sc_trim_start.setKey(_api.QKeySequence(self.trim_start_seq))
        if getattr(self, "_sc_trim_end", None) is not None:
            self._sc_trim_end.setKey(_api.QKeySequence(self.trim_end_seq))
    except Exception:
        pass
    if save:
        self.save_settings()

# ── Pan slider ────────────────────────────────────────────────────────
def on_wave_view_changed(self, view_offset, visible_duration):
    self.update_pan_slider_values()
    self.update_wave_scroll()

# ── Horizontal scrollbar over the waveform ─────────────────────────────
def on_wave_scroll(self, value):
    """Пользователь двигает горизонтальную прокрутку → смещаем окно обзора волны."""
    duration = self.waveform.duration or self.duration or 0.0
    if duration <= 0:
        return
    self.waveform.set_view_offset(value / 1000.0)

def update_wave_scroll(self):
    """Синхронизирует горизонтальную прокрутку с масштабом/положением волны.
        Прячется, когда прокручивать нечего (волна целиком помещается)."""
    sb = getattr(self, "wave_scroll", None)
    if sb is None:
        return
    duration = self.waveform.duration or self.duration or 0.0
    visible = max(0.001, duration / self.waveform.zoom)
    pan_range = max(0.0, duration - visible)
    if duration <= 0 or pan_range <= 1e-6:
        sb.setVisible(False)
        return
    sb.setVisible(True)
    sb.blockSignals(True)
    sb.setMinimum(0)
    sb.setMaximum(int(pan_range * 1000))
    sb.setPageStep(max(1, int(visible * 1000)))
    sb.setSingleStep(max(1, int(visible * 100)))
    sb.setValue(int(self.waveform.view_offset * 1000))
    sb.blockSignals(False)

def update_pan_slider_values(self):
    pan_row = getattr(self, 'pan_row_w', None)
    duration = self.waveform.duration or self.duration or 0.0
    if duration <= 0:
        self.pan_slider.setEnabled(False)
        if pan_row is not None:
            pan_row.setVisible(False)
        return
    visible = max(0.001, duration / self.waveform.zoom)
    pan_range = max(0.0, duration - visible)
    if pan_range <= 0.0:
        self.pan_slider.setEnabled(False); self.pan_slider.setValue(0)
        if pan_row is not None:
            pan_row.setVisible(False)
        return
    self.pan_slider.setEnabled(True)
    if pan_row is not None:
        pan_row.setVisible(True)
    val = int((self.waveform.view_offset / pan_range) * 1000) if pan_range > 0 else 0
    self.pan_slider.blockSignals(True)
    self.pan_slider.setValue(max(0, min(1000, val)))
    self.pan_slider.blockSignals(False)

def on_pan_moved(self, value):
    duration = self.waveform.duration or self.duration or 0.0
    if duration <= 0:
        return
    visible = max(0.001, duration / self.waveform.zoom)
    pan_range = max(0.0, duration - visible)
    offset = (value / 1000.0) * pan_range if pan_range > 0 else 0.0
    self.waveform.set_view_offset(offset)

# ── Settings ──────────────────────────────────────────────────────────
def save_settings(self):
    try:
        settings = {
            'mode_index': int(self.cmb_mode.currentIndex()),
            'encoder_index': int(self.cmb_encoder.currentIndex()),
            'sub_style_index': int(self.cmb_sub_style.currentIndex()),
            'overwrite':  bool(self.chk_overwrite.isChecked()),
            'burn_subs':  bool(self.chk_burn_subs.isChecked()),
            'zoom':       float(self.waveform.zoom),
            'view_offset': float(self.waveform.view_offset),
            'volume':     int(self.vol_slider.value()),   # громкость теперь сохраняется (пункт B)
            'trim_start_seq': self.trim_start_seq,
            'trim_end_seq':   self.trim_end_seq,
            'export_dir':     self.export_dir or "",
            'subs_in_frame':  bool(getattr(self, '_subs_in_frame', True)),
            'scrub_audio':    bool(getattr(self, '_scrub_audio_enabled', True)),
            'pb_quality_index': int(self.cmb_pb_quality.currentIndex())
                if hasattr(self, 'cmb_pb_quality') else 0,
            'proxy_min': int(self.spin_proxy_min.value())
                if hasattr(self, 'spin_proxy_min') else 0,
            'subtitle_style': dict(getattr(self, '_last_subtitle_style', None) or {}) or None,
        }
        # Атомарно (временный файл + подмена): прямая запись обрезала файл
        # ДО того, как в него ляжет новое содержимое, и жёсткое завершение
        # процесса в этот момент теряло настройки Монтажа целиком.
        _api.save_json_atomic(_api.EDITOR_SETTINGS_PATH, settings)
    except Exception:
        pass

def load_settings(self):
    if not _api.os.path.exists(_api.EDITOR_SETTINGS_PATH):
        return
    try:
        with open(_api.EDITOR_SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = _api.json.load(f)
        self.cmb_mode.setCurrentIndex(int(settings.get('mode_index', 1)))
        self.cmb_encoder.setCurrentIndex(int(settings.get('encoder_index', 0)))
        if hasattr(self, 'cmb_pb_quality'):
            # Без сигнала: файла ещё нет, применится при загрузке.
            self.cmb_pb_quality.blockSignals(True)
            self.cmb_pb_quality.setCurrentIndex(int(settings.get('pb_quality_index', 0)))
            self.cmb_pb_quality.blockSignals(False)
        if hasattr(self, 'spin_proxy_min'):
            self.spin_proxy_min.blockSignals(True)
            self.spin_proxy_min.setValue(int(settings.get('proxy_min', 0)))
            self.spin_proxy_min.blockSignals(False)
        self.cmb_sub_style.setCurrentIndex(int(settings.get('sub_style_index', 2)))
        self.chk_overwrite.setChecked(bool(settings.get('overwrite', True)))
        self.chk_burn_subs.setChecked(bool(settings.get('burn_subs', False)))
        self.waveform.zoom        = max(0.25, min(200.0, float(settings.get('zoom', 1.0))))
        self.waveform.view_offset = max(0.0, float(settings.get('view_offset', 0.0)))
        vol = max(0, min(100, int(settings.get('volume', 100))))
        self.vol_slider.setValue(vol)
        self.audio_output.setVolume(vol / 100.0)
        self.set_trim_shortcuts(
            settings.get('trim_start_seq', self.trim_start_seq),
            settings.get('trim_end_seq', self.trim_end_seq),
            save=False)
        self.export_dir = settings.get('export_dir', "") or ""
        self._update_export_dir_label()
        # Покадровый скраб-звук теперь всегда включён (настройка убрана из UI).
        self._scrub_audio_enabled = True
        # Последние настройки стиля «Создать субтитры» (шрифт/размер/цвет/…) —
        # см. create_subtitles/SubtitleCreatorDialog.default_style.
        self._last_subtitle_style = settings.get('subtitle_style') or None
    except Exception:
        pass
