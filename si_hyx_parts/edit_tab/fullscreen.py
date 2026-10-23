# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: полноэкранный режим видео."""
import edit_tab as _api


class EditTabFullscreenMixin:
    """Монтаж: вход в полный экран и выход из него, кадр после переезда."""

    # ── Полноэкранный режим ─────────────────────────────────────────────────
    def toggle_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            return
        if self.duration <= 0.1:   # нет загруженного видео
            return
        try:
            fs = _api.FullscreenVideo(self)
            # fs — самостоятельное окно без родителя (иначе showFullScreen на
            # дочернем виджете ведёт себя иначе), поэтому Qt может открыть его
            # fullscreen'ом на ПЕРВИЧНОМ мониторе, даже если само приложение
            # (и мышь пользователя) сейчас на другом. Явно ставим тот же экран,
            # где сейчас окно приложения — заодно фиксирует QScreen ДО первого
            # show(), от чего зависит и корректный клэмп tooltip'ов панели
            # управления (см. FullscreenVideo._relayout).
            try:
                src_screen = self.window().windowHandle().screen()
            except Exception:
                src_screen = None
            if src_screen is not None:
                fs.winId()   # форсирует создание нативного хэндла ДО setScreen
                wh = fs.windowHandle()
                if wh is not None:
                    wh.setScreen(src_screen)
            # Снимаем фиксированные размеры с видео и переносим его в окно.
            self.video_widget.setMinimumSize(0, 0)
            self.video_widget.setMaximumSize(16777215, 16777215)
            fs.attach_video(self.video_widget)
            self._fs_window = fs
            self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=False))
            self.btn_fullscreen.setToolTip("Свернуть (Esc / двойной клик по видео)")
            fs.showFullScreen()
            # Без этого клавиши (F/Esc/Space/стрелки) не доходили до окна: после
            # showFullScreen() фокус клавиатуры мог оставаться на виджете, у
            # которого он был ДО входа в полноэкранный режим (например, на
            # волне/поле ссылки в основном окне) — F там ничего не делал.
            fs.activateWindow()
            fs.setFocus(_api.Qt.FocusReason.OtherFocusReason)
            fs.sync_from_player()
            fs.sync_volume()
            fs.update_play_icon(
                self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState)
            # Холст переехал в другое окно, а с ним и его сцена Qt Quick:
            # графический контекст пересоздан, и показанный кадр в нём не
            # переживает переезд. На паузе кадров от плеера больше не будет —
            # ставим точный кадр заново (на воспроизведении метод сам ничего не
            # делает: там следующий кадр приедет через ~16 мс).
            _api.QTimer.singleShot(0, self._restore_canvas_frame)
            try:
                self._update_subtitle(self._ui_time_s())
                _api.QTimer.singleShot(0, self._position_overlay)
            except Exception:
                pass
        except Exception as e:
            self.main.log(f"enter_fullscreen error: {e}")
            self._fs_window = None

    def exit_fullscreen(self):
        fs = getattr(self, "_fs_window", None)
        if fs is None:
            return
        self._fs_window = None
        try:
            # Возвращаем видео обратно в контейнер вкладки.
            self.vc_layout.insertWidget(0, self.video_widget, 0, _api.Qt.AlignmentFlag.AlignCenter)
            self.video_widget.show()
        except Exception:
            pass
        # Оверлей субтитров мог стать дочерним к окну fs — вернём его главному
        # окну ДО удаления fs, иначе Qt удалит оверлей вместе с fs.
        try:
            if self.sub_overlay is not None:
                self._reparent_overlay(self.window())
        except Exception:
            pass
        try:
            fs.close(); fs.deleteLater()
        except Exception:
            pass
        try:
            self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=True))
            self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
            self._adjust_video_height()
            _api.QTimer.singleShot(0, self._position_overlay)
            # Обратный переезд — та же история, что и при входе (см. там).
            _api.QTimer.singleShot(0, self._restore_canvas_frame)
        except Exception:
            pass

    def _restore_canvas_frame(self):
        """Возвращает кадр на холст после переезда в другое окно.

        Нужен только на паузе: сцена холста теряет показанный кадр вместе с
        графическим контекстом, а новых кадров плеер на паузе не шлёт. Точный
        кадр берётся из того же предекодера, что и при покадровом шаге, так что
        на экране оказывается ровно тот кадр, на котором стояли."""
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                return
        except Exception:
            return
        try:
            self._show_exact_frame(self._frame_idx)
        except Exception:
            pass

    def _fs_sync_position(self):
        """Обновляет полосу/тайминги в полноэкранном окне (вызывается из
        _paint_playhead и _paint_project_time, когда оно открыто)."""
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_from_player()
            except Exception:
                pass

    # ── Шкала полноэкранной панели ──────────────────────────────────────────
    # Та же, что под видео: время и длина ПРОЕКТА (обрезанные куски, порядок
    # клипов), а без проекта — файла. Прежде панель жила по файлу целиком:
    # длина, полоса и превью показывали необрезанное видео, а клик по полосе
    # уводил плеер в вырезанные места.
    def _fs_on_project(self):
        return (getattr(self, "project_timeline", None) is not None
                and not self.project.is_empty())

    def _fs_span(self):
        """Длина шкалы полноэкранной панели, с."""
        if self._fs_on_project():
            return self.project.duration()
        return self.duration or 0.0

    def _fs_time(self):
        """Время для полноэкранной панели, с — то же, что у метки под видео."""
        if self._fs_on_project():
            return self.project_timeline.playhead
        return self._ui_time_s()

    def _fs_seek(self, frac):
        """Клик или протяжка по полосе полноэкранной панели (доля 0..1) — как
        по таймлайну."""
        frac = max(0.0, min(1.0, float(frac)))
        if self._fs_on_project():
            # Край полосы — последний кадр проекта (как «В конец»): сама длина
            # проекта лежит ЗА ним, и там плееру показать нечего.
            self._project_seek(min(frac * self.project.duration(),
                                   self._proj_last_frame_t()))
            return
        if self.duration > 0:
            self.seek_to(frac * self.duration)

    def _fs_preview_locate(self, t):
        """Кадр превью над полосой для времени шкалы t: (файл, время в нём)
        или None — там пусто (чёрный кадр проекта)."""
        if not self._fs_on_project():
            src = self.actual_source_file
            return (str(src), t) if src else None
        segs = self.project.preview_segments()
        if not segs:
            return None
        t = min(max(0.0, t), segs[-1][1] - 1e-3)
        for t0, t1, clip in segs:
            if t0 <= t < t1:
                if clip is None or not clip.has_video:
                    return None
                return clip.src, (0.0 if clip.is_image else clip.source_time(t))
        return None
