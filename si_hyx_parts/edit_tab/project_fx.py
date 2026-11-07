# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: просмотр проекта с эффектами и текстом — так, как в собранном файле.

Живой плеер играет исходники кусками: эффекты, текст, наложения с масками,
переходы и отделку кадра он не показывает (live_preview_gaps). Когда в
проекте есть такое, вместо холста плеера всегда стоит
FxPreviewView, а кадры даёт FxPreview (edit_tab_workers) — тем же графом
ffmpeg, что и сборка, в кадре превью 540p:

* пауза, клик и протяжка по таймлайну, шаг кадра — кадр на плейхеде;
* игра — поток кадров по кускам, звук — тракт проекта (ProjectSoundEngine),
  часы — по звуку (нет устройства — по стене); старт ждёт первые кадры и
  звук, чтобы картинка не отставала с первой секунды;
* на паузе кэш кусков дорисовывается фоном, второй просмотр идёт из кэша.

Правка проекта сбрасывает план (ключи кусков — по графу, поэтому заново
рендерится только изменённое). Полный экран и «Только звук» идут прежним
плеером: режим на это время выключается."""
import edit_tab as _api

_FILL_DELAY_MS = 1500      # плейхед/проект успокоились — дорисовываем кэш
_PREPARE_DELAY_MS = 450    # звук с плейхеда заранее, как в project_sound
_START_TIMEOUT_S = 3.0     # дольше старт не ждёт кадры и звук
_START_FRAMES = 8          # столько кадров в очереди — можно стартовать
_TICK_MS = 8


class EditTabProjectFxMixin:
    """Монтаж: режим просмотра проекта с эффектами."""

    def _fx_init(self):
        """Из _project_init."""
        self._fx = None                  # FxPreview (лениво)
        self._fx_view = None             # FxPreviewView (лениво)
        self._fx_mode = False            # вместо холста плеера — кадры с эффектами
        self._fx_playing = False
        self._fx_starting = False
        self._fx_start_at = 0.0
        self._fx_t0 = 0.0                # время проекта старта игры
        self._fx_mono0 = 0.0             # часы стены на старте (если без звука)
        self._fx_sound = False           # игра со звуком тракта
        self._fx_timer = None
        self._fx_fill_timer = None
        self._fx_prep_timer = None
        self._fx_still_gen = 0
        self._fx_cache_note = ""

    # ── Включение ────────────────────────────────────────────────────────────
    def _fx_wanted(self):
        if getattr(self, "project_timeline", None) is None:
            return False
        if getattr(self, "_fs_window", None) is not None or getattr(self, "_audio_only_mode", False):
            return False
        p = self.project
        return p.has_video() and bool(p.live_preview_gaps())

    def _fx_update_mode(self):
        """Из _project_update_ui: режим — по проекту."""
        want = self._fx_wanted()
        if want and not self._fx_mode:
            self._fx_enter()
        elif not want and self._fx_mode:
            self._fx_leave()

    def _fx_engine(self):
        if self._fx is None:
            self._fx = _api.FxPreview(self)
            self._fx.stillReady.connect(self._fx_on_still)
            self._fx.cacheProgress.connect(self._fx_on_cache)
            self._fx.failed.connect(self._fx_on_failed)
        return self._fx

    def _fx_view_widget(self):
        if self._fx_view is None:
            view = _api.FxPreviewView(self.video_container)
            view.setAcceptDrops(True)
            view.installEventFilter(self)
            view.hide()
            self.video_container.layout().addWidget(view, 1)
            self._fx_view = view
        return self._fx_view

    def _fx_enter(self):
        if self._proj_play is not None:
            self.project_stop()
        self._fx_mode = True
        fx = self._fx_engine()
        fx.set_project(self.project)
        view = self._fx_view_widget()
        self.video_widget.hide()
        view.show()
        view.set_note("Просмотр с эффектами · рендер кадра…")
        self._fx_show_still(self.project_timeline.playhead)
        self._fx_schedule_fill()

    def _fx_leave(self):
        if not self._fx_mode:
            return
        self._fx_stop()
        if self._fx is not None:
            self._fx.stop_fill()
        self._fx_mode = False
        if self._fx_view is not None:
            self._fx_view.hide()
            self._fx_view.clear()
        self.video_widget.show()
        if not self.project.is_empty():
            self._project_seek(self.project_timeline.playhead)

    def _fx_project_changed(self):
        """Из _project_changed: план заново, кадр на плейхеде — заново."""
        if not self._fx_mode:
            return
        if self._fx_playing:
            self._fx_stop(show=False)
        fx = self._fx_engine()
        fx.set_project(self.project)
        self._fx_show_still(self.project_timeline.playhead)
        self._fx_schedule_fill()

    # ── Пауза: кадр на плейхеде ──────────────────────────────────────────────
    def _fx_seek(self, t):
        """Из _project_seek: плейхед в t, кадр с эффектами."""
        t = max(0.0, min(float(t), self._proj_last_frame_t()))
        tl = self.project_timeline
        tl.set_playhead(t, follow=False)
        self._paint_project_time(t)
        if self._fx_playing:
            self._fx_restart(t)
            return
        self._fx_show_still(t)

    def _fx_show_still(self, t):
        if self._fx is None:
            return
        self._fx_still_gen = self._fx.still(t)
        self._fx_schedule_prepare()

    def _fx_on_still(self, gen, t, img):
        if gen != self._fx_still_gen or self._fx_playing or self._fx_view is None:
            return
        self._fx_view.set_image(img)
        self._fx_view.set_note(self._fx_cache_note)

    def _fx_on_cache(self, done, total):
        self._fx_cache_note = ("" if done >= total else
                               f"Просмотр с эффектами · готово {done} из {total}")
        if self._fx_view is not None and not self._fx_playing:
            self._fx_view.set_note(self._fx_cache_note)

    def _fx_on_failed(self, msg):
        self._proj_status(f"просмотр с эффектами: {msg.splitlines()[-1] if msg else 'сбой'}")

    def _fx_schedule_fill(self):
        if self._fx_fill_timer is None:
            self._fx_fill_timer = _api.QTimer(self)
            self._fx_fill_timer.setSingleShot(True)
            self._fx_fill_timer.setInterval(_FILL_DELAY_MS)
            self._fx_fill_timer.timeout.connect(self._fx_fill_now)
        self._fx_fill_timer.start()

    def _fx_fill_now(self):
        if self._fx_mode and not self._fx_playing and self._fx is not None:
            self._fx.fill(self.project_timeline.playhead)

    def _fx_schedule_prepare(self):
        if self._fx_prep_timer is None:
            self._fx_prep_timer = _api.QTimer(self)
            self._fx_prep_timer.setSingleShot(True)
            self._fx_prep_timer.setInterval(_PREPARE_DELAY_MS)
            self._fx_prep_timer.timeout.connect(self._fx_prepare_sound)
        self._fx_prep_timer.start()

    def _fx_prepare_sound(self):
        """Звук с плейхеда — заранее: «Пробел» стартует без ожидания."""
        if not self._fx_mode or self._fx_playing or not self._snd_wanted():
            return
        t = self.project_timeline.playhead
        if t < self.project.duration() - 0.05 and not self._snd.prepared_for(self.project, t):
            self._snd.prepare(self.project, t)

    # ── Игра ─────────────────────────────────────────────────────────────────
    def _fx_toggle(self):
        if self._fx_playing:
            self._fx_stop()
        else:
            self._fx_play()

    def _fx_play(self):
        if self.project.is_empty() or self._fx is None:
            return
        t = self.project_timeline.playhead
        if t >= self._proj_last_frame_t() - 1e-3:
            t = 0.0                     # с последнего кадра — заново с начала
        self._fx_playing = True
        self._fx_restart(t)
        self._sync_play_icon()
        if self._fx_timer is None:
            self._fx_timer = _api.QTimer(self)
            self._fx_timer.setTimerType(_api.Qt.TimerType.PreciseTimer)
            self._fx_timer.setInterval(_TICK_MS)
            self._fx_timer.timeout.connect(self._fx_tick)
        self._fx_timer.start()

    def _fx_restart(self, t):
        """Игра (или прыжок на ходу) с t: кадры и звук заново, старт — когда
        готовы оба."""
        self._fx.stop_fill()
        self._fx.play(t)
        self._fx_t0 = t
        self._fx_sound = self._snd_wanted()
        if self._fx_sound:
            eng = self._snd
            if eng.is_playing():
                eng.stop()
            if not eng.prepared_for(self.project, t):
                eng.prepare(self.project, t)
        self._fx_starting = True
        self._fx_start_at = _api.time.monotonic()
        if self._fx_view is not None:
            self._fx_view.set_note("")

    def _fx_now(self):
        if self._fx_sound and self._snd is not None and self._snd.is_playing():
            now = self._snd.now()
            if now is not None:
                return now
        return self._fx_t0 + (_api.time.monotonic() - self._fx_mono0)

    def _fx_tick(self):
        fx = self._fx
        if not self._fx_playing or fx is None:
            return
        end = self._proj_last_frame_t()
        if self._fx_starting:
            frames_left = max(1, int((end - self._fx_t0) * fx.fps()))
            video_ok = fx.buffered() >= min(_START_FRAMES, frames_left) or fx.play_done()
            sound_ok = not self._fx_sound or self._snd.is_ready()
            waited = _api.time.monotonic() - self._fx_start_at > _START_TIMEOUT_S
            if not ((video_ok and sound_ok) or waited):
                return
            self._fx_starting = False
            if self._fx_sound:
                self._snd.play()
            self._fx_mono0 = _api.time.monotonic()
        now = self._fx_now()
        fr = fx.take(now)
        if fr is not None and self._fx_view is not None:
            self._fx_view.set_image(fr[1])
        t = min(now, end)
        self.project_timeline.set_playhead(t)
        self._paint_project_time(t)
        if now >= end or (fx.play_done() and now >= end - 2.0 / max(1.0, fx.fps())):
            self._fx_stop()

    def _fx_stop(self, show=True):
        if not self._fx_playing:
            return
        self._fx_playing = False
        self._fx_starting = False
        if self._fx_timer is not None:
            self._fx_timer.stop()
        if self._fx is not None:
            self._fx.stop()
        if self._fx_sound and self._snd is not None:
            self._snd.stop()
        self._fx_sound = False
        if not self._sync_play_icon():
            return                      # виджет уже удалён (закрытие окна)
        if show and self._fx_mode:
            # Точный кадр остановки и кэш дальше — как на паузе.
            self._fx_show_still(self.project_timeline.playhead)
            self._fx_schedule_fill()

    def _fx_step(self, step):
        """Шаг кадра проекта (стрелки) в режиме эффектов."""
        fps = self._fx.fps() if self._fx is not None else 30.0
        if self._fx_playing:
            self._fx_stop(show=False)
        self._fx_seek(self.project_timeline.playhead + int(step) / fps)

    def _fx_shutdown(self):
        for t in (self._fx_timer, self._fx_fill_timer, self._fx_prep_timer):
            if t is not None:
                t.stop()
        if self._fx is not None:
            self._fx.shutdown()
