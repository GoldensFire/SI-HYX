# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _ensure_overlay. Public namespace: edit_tab."""
import edit_tab as _api


def _ensure_overlay(self):
    """Лениво создаёт окно-оверлей субтитров и подписывается на Move/Resize
        верхнеуровневого окна (чтобы оверлей следовал за видео)."""
    if self.sub_overlay is None:
        self.sub_overlay = _api.SubtitleOverlay(self.window())
        win = self.window()
        if win is not None and win is not self._overlay_win:
            try:
                win.installEventFilter(self)
                self._overlay_win = win
            except Exception:
                pass
        # Подписки на состояние приложения/фокус окна — ОДИН раз за жизнь
        # вкладки (оверлей может пересоздаваться при смене метода субтитров).
        if not getattr(self, "_overlay_signals_connected", False):
            self._overlay_signals_connected = True
            # Окно поверх всех → прячем, когда приложение неактивно, чтобы текст
            # субтитров не висел поверх других программ при Alt+Tab.
            try:
                _api.QApplication.instance().applicationStateChanged.connect(
                    self._on_app_state_changed)
            except Exception:
                pass
            # …и когда активно другое окно приложения (диалог настроек/консоль
            # и т.п.) — иначе субтитры висят поверх него.
            try:
                _api.QApplication.instance().focusWindowChanged.connect(
                    self._on_focus_window_changed)
            except Exception:
                pass
    return self.sub_overlay

def _on_focus_window_changed(self, *args):
    self._position_overlay()

def _on_app_state_changed(self, state):
    if self.sub_overlay is None:
        return
    if state == _api.Qt.ApplicationState.ApplicationActive:
        self._position_overlay()
    else:
        self.sub_overlay.hide()

def _position_overlay(self):
    """Подгоняет окно-оверлей под текущую область видео (в окне или в
        полноэкранном режиме) и показывает/прячет его.
        В frame-режиме окна-оверлея нет — субтитры рисует сам холст; здесь лишь
        перерисовываем кадр ASS при изменении геометрии."""
    if self._subs_in_frame:
        if self._sub_use_ass and self._ass is not None:
            try: self._update_subtitle(self._ui_time_s())
            except Exception: pass
        return
    ov = self.sub_overlay
    if ov is None:
        return
    fs = getattr(self, "_fs_window", None)
    if not self._sub_use_overlay or not self.isVisible():
        ov.hide()
        return
    # Если активно другое окно приложения (диалог настроек/консоль и т.п.) —
    # прячем оверлей, чтобы субтитры не висели поверх него.
    try:
        aw = _api.QApplication.activeWindow()
        allowed = {self.window(), fs}
        if aw is not None and aw not in allowed:
            ov.hide()
            return
    except Exception:
        pass
    target = (fs._video if (fs is not None and getattr(fs, "_video", None) is not None)
              else self.video_widget)
    # Оверлей субтитров — отдельное окно «поверх всех»; его владельцем должно
    # быть то окно, где сейчас видео. Иначе при показе оверлея в полноэкранном
    # режиме Windows вытягивает вперёд окно-владельца (главное окно) и его GUI
    # оказывается поверх видео. Привязываем владельца к текущему окну видео.
    self._reparent_overlay(target.window())
    ov.place_over(target)
    # ASS: подгоняем разрешение рендера под размер оверлея и перерисовываем.
    if self._sub_use_ass and self._ass is not None:
        try:
            self._ass.set_frame_size(ov.width(), ov.height())
            self._update_subtitle(self._ui_time_s())
        except Exception:
            pass
    if not ov.isVisible():
        ov.show()
    ov.raise_()

def _reparent_overlay(self, owner):
    ov = self.sub_overlay
    if ov is None or owner is None or ov.parent() is owner:
        return
    try:
        flags = ov.windowFlags()
        vis = ov.isVisible()
        ov.setParent(owner, flags)
        ov.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ov.setAttribute(_api.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ov.setAttribute(_api.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        ov.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if vis:
            ov.show()
    except Exception:
        pass

def on_sub_track_changed(self, idx):
    if self._loading_tracks:
        return
    # Пункт «Показать другие файлы…» — не дорожка, а команда: досыпать
    # отфильтрованные файлы в список и остаться на прежнем выборе (см.
    # _expand_external_subs / _populate_track_combos_subs_only). Список при
    # этом закрывается — его закрывает сам QComboBox на любом выборе, — но
    # раскрыли его ради того, чтобы ВЫБРАТЬ файл из досыпанных, поэтому
    # открываем снова: иначе после каждого клика приходилось лезть в список
    # заново. Через singleShot — сперва Qt должен закончить текущий выбор.
    if 0 < idx <= len(self._sub_entries) and self._sub_entries[idx - 1][0] == 'more':
        self._expand_external_subs()
        _api.QTimer.singleShot(0, self._reopen_subs_popup)
        return
    # Запоминаем РЕАЛЬНО выбранную дорожку: по ней список восстанавливает
    # выбор при перестроении (см. _populate_track_combos_subs_only).
    self._sub_sel_entry = (self._sub_entries[idx - 1]
                           if 0 < idx <= len(self._sub_entries) else None)
    self._stop_sub_extractor()
    self._stop_ass()
    self._sub_cues = []
    self._sub_use_overlay = False
    self._hide_sub_display()
    self.selected_sub_ext_path = None

    # Пункт 0 = «Выкл» → субтитры выключены.
    if idx <= 0 or (idx - 1) >= len(self._sub_entries):
        try: self.player.setActiveSubtitleTrack(-1)
        except Exception: pass
        return

    kind, ref = self._sub_entries[idx - 1]
    if kind == 'emb':
        sub_i = ref
        src = self.actual_source_file
        try:
            codec = (self._sub_streams[sub_i].get('codec_name') or '').lower()
        except Exception:
            codec = ''
    else:
        # Внешний файл субтитров: извлекаем/рендерим прямо из него (stream 0).
        self.selected_sub_ext_path = ref
        sub_i = 0
        src = ref
        codec = _api.os.path.splitext(ref)[1].lower().lstrip('.')

    is_bitmap = codec in self._BITMAP_SUB_CODECS
    if is_bitmap or not src:
        # Битмап-дорожка (или нет источника) → встроенный рендер. Для внешних
        # файлов битмап-кодеков нет, поэтому это только встроенные дорожки.
        if kind == 'emb':
            try: self.player.setActiveSubtitleTrack(sub_i)
            except Exception: pass
        return

    # Текстовые субтитры → свой рендер; встроенный (с плашкой) гасим.
    try: self.player.setActiveSubtitleTrack(-1)
    except Exception: pass
    self._sub_use_overlay = True
    self._prepare_sub_display()
    self._sub_token += 1
    tok = self._sub_token
    # Запоминаем источник субтитров (для отката ASS→SRT в _on_ass_extracted).
    self._cur_sub_src = src
    self._cur_sub_index = sub_i

    if _api.LIBASS_AVAILABLE and codec in ('ass', 'ssa'):
        # ASS/SSA → полный стиль и караоке через libass (рендер в фоне после
        # извлечения дорожки в .ass; при неудаче — откат на текстовый SRT).
        ex = _api.AssExtractor(src, sub_i, tok)
        ex.done.connect(self._on_ass_extracted)
        ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                            if e in self._sub_threads else None)
        self._sub_threads.append(ex)
        self._ass_extractor = ex
        ex.start()
        return

    # Прочие текстовые дорожки (srt/mov_text/webvtt) → чистый текст-оверлей.
    ex = _api.SubtitleExtractor(src, sub_i, tok)
    ex.done.connect(self._on_sub_cues)
    ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                        if e in self._sub_threads else None)
    self._sub_threads.append(ex)
    self._sub_extractor = ex
    ex.start()

def _reopen_subs_popup(self):
    """Снова раскрывает список дорожек субтитров после «Показать другие
        файлы…»: пользователь раскрывал его, чтобы выбрать файл, а команда
        досыпала их в тот же список."""
    cmb = getattr(self, "cmb_subs", None)
    if cmb is None or not cmb.isEnabled() or not cmb.isVisible():
        return
    try:
        cmb.showPopup()
    except Exception:
        pass

def _stop_sub_extractor(self):
    ex = getattr(self, "_sub_extractor", None)
    if ex is not None:
        try:
            ex.done.disconnect()
        except Exception:
            pass
        self._sub_extractor = None

def _stop_ass(self):
    """Останавливает ASS-рендер: таймер, libass, временный .ass и картинку."""
    self._sub_use_ass = False
    ex = getattr(self, "_ass_extractor", None)
    if ex is not None:
        try: ex.done.disconnect()
        except Exception: pass
        self._ass_extractor = None
    t = getattr(self, "_ass_timer", None)
    if t is not None:
        try: t.stop()
        except Exception: pass
    if getattr(self, "_ass", None) is not None:
        try: self._ass.close()
        except Exception: pass
        self._ass = None
    if getattr(self, "_ass_path", None):
        try: _api.os.remove(self._ass_path)
        except Exception: pass
        self._ass_path = None
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.set_subtitle_image(None)
    ov = getattr(self, "sub_overlay", None)
    if ov is not None:
        ov.set_image(None)

def _ensure_ass_timer(self):
    if self._ass_timer is None:
        t = _api.QTimer(self)
        t.setInterval(60)   # ~16 к/с — достаточно для плавного караоке
        t.timeout.connect(self._on_ass_tick)
        self._ass_timer = t
    if not self._ass_timer.isActive():
        self._ass_timer.start()

def _on_ass_tick(self):
    """Перерисовка libass во время воспроизведения (караоке, анимации).

        Время берём ТОЛЬКО через _ui_time_s. Раньше здесь стояла сырая
        player.position(), и это был единственный кусок интерфейса, который
        обходил защиту _ui_pinned_ms: во время беззвучного разбега прогрева
        плеер формально играет, а позиция бежит с отметки на полсекунды
        РАНЬШЕ плейхеда — libass честно рисовал субтитры из прошлого, и они
        вспыхивали на каждый покадровый шаг, а потом пропадали."""
    if not self._sub_use_ass or self._ass is None:
        return
    try:
        if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            self._update_subtitle(self._ui_time_s())
    except Exception:
        pass

def _on_ass_extracted(self, token, path):
    if token != self._sub_token:
        if path:
            try: _api.os.remove(path)
            except Exception: pass
        return
    if not path:
        # libass-извлечение не удалось → откат на текстовый SRT-оверлей.
        self._sub_use_ass = False
        src = getattr(self, "_cur_sub_src", None) or self.actual_source_file
        sub_i = getattr(self, "_cur_sub_index", -1)
        if sub_i >= 0 and src:
            ex = _api.SubtitleExtractor(src, sub_i, token)
            ex.done.connect(self._on_sub_cues)
            ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                if e in self._sub_threads else None)
            self._sub_threads.append(ex)
            self._sub_extractor = ex
            ex.start()
        return
    try:
        self._ass = _api._libass.AssRenderer()
        if not self._ass.load_ass_file(path):
            raise RuntimeError("load_ass_file failed")
        self._ass_path = path
        self._sub_use_ass = True
        self._prepare_sub_display()
        self._ensure_ass_timer()
        self._update_subtitle(self._ui_time_s())
    except Exception:
        self._sub_use_ass = False
        if self._ass is not None:
            try: self._ass.close()
            except Exception: pass
            self._ass = None
        try: _api.os.remove(path)
        except Exception: pass

def _on_sub_cues(self, token, cues):
    if token != self._sub_token:
        return   # пришёл результат от уже неактуального выбора — игнорируем
    self._sub_cues = cues or []
    try:
        self._update_subtitle(self._ui_time_s())
    except Exception:
        pass

def _subtitle_at(self, pos_s):
    for start, end, body in self._sub_cues:
        if start <= pos_s <= end:
            return body
        if start > pos_s:
            break
    return ""
