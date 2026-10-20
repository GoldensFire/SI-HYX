# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: перемещение по таймлайну — звук после перемотки на ходу, протяжка
плейхеда мышью, кадр остановки и прогрев после прихода кадра.

Замеры на BDRemux 1080p (H.264 36 Мбит/с, PCM) записью звука самого процесса
(WASAPI process loopback) против исходной дорожки:

* перемотка НА ХОДУ у QtMultimedia пересоздаёт декодеры: прежний звук играет
  ещё ~40 мс и обрывается, ~150–250 мс тишины, затем звук нового места —
  с рваным началом (очередь устройства пуста, бэкенд подстраивает звук под
  часы и перескакивает на 3–15 мс). Новое место поднимается плавно: громкость
  0 с момента перемотки и нарастание после первых десятков миллисекунд.
  Громкость QAudioOutput доходит до колонок через ~110 мс (она применяется
  при записи в устройство), поэтому момент «пошёл звук нового места» берём у
  копии буферов плеера (QAudioBufferOutput), а не у часов позиции — те
  двигаются ступеньками по 50 мс. С аппаратным декодером (AMD Vega, d3d11va)
  после каждой перемотки на ходу производство звука ещё и замирает на
  60–170 мс через 0.4–0.7 с — это слышно как короткий провал; с программным
  декодером замираний нет (настройка «Аппаратное ускорение видео»);
* протяжка плейхеда на ходу перематывала плеер на каждое движение мыши — звук
  рассыпался на обрывки. Теперь на время протяжки воспроизведение встаёт, а
  после отпускания продолжается с новой точки (как в монтажках);
* перемотка на паузе с аппаратным декодером приносит кадр через 0.3–0.7 с, и
  каждая новая перемотка выбрасывает начатую. Во время протяжки в полёте не
  больше одной перемотки, новая цель заменяет отложенную;
* прогрев звука (EditTab._preroll_at) сам перематывает плеер — он запускается
  только когда кадр нового места уже на экране, иначе отменял его декодирование
  и картинка стояла на прежнем месте до 0.8 с."""
import edit_tab as _api


class EditTabTimelineSeekMixin:
    """Монтаж: звук и картинка при перемещении по таймлайну."""

    # Сколько ещё держать звук приглушённым после первого буфера нового места:
    # рваное начало (недобор очереди устройства и подстройка бэкенда) — первые
    # десятки миллисекунд. Дольше держать — это уже заметная лишняя тишина.
    _SEEK_FADE_HOLD_MS = 30
    # Нарастание громкости после этого — ступени (доля от ползунка) раз в 15 мс.
    _SEEK_FADE_STEPS = (0.25, 0.5, 0.75, 1.0)
    _SEEK_FADE_STEP_MS = 15
    # Если звук нового места так и не пришёл (нет звуковой дорожки, звук
    # выключен) — громкость возвращается сама.
    _SEEK_FADE_MAX_MS = 1500
    # Перемотка во время протяжки, не принёсшая кадр за это время, считается
    # законченной — следующая цель уходит плееру без ожидания.
    _DRAG_SEEK_TIMEOUT_S = 0.8
    # Прогрев ждёт кадр нового места не дольше этого.
    _PREROLL_WAIT_MAX_S = 1.5

    def _seek_audio_init(self):
        """Из __init__ сразу после создания плеера."""
        self._seek_gain = 1.0          # множитель громкости ползунка на время перехода
        self._seek_fade = None
        self._seek_fade_gen = 0
        self._tl_dragging = False      # плейхед тянут мышью по таймлайну
        self._tl_drag_resume = False   # до протяжки шло воспроизведение
        self._drag_seek_want = None    # последняя цель протяжки, ещё не отданная плееру
        self._drag_seek_busy = None    # (мс, когда отдали) — перемотка в полёте
        self._drag_seek_timer = None
        self._preroll_wait = None      # (кадр, с какого времени ждём его на экране)
        self._preroll_wait_timer = None
        self._abuf_out = None
        if _api.QAudioBufferOutput is None:
            return
        try:
            out = _api.QAudioBufferOutput(self)
            self.player.setAudioBufferOutput(out)
            out.audioBufferReceived.connect(self._on_player_audio_buffer)
            self._abuf_out = out
        except Exception:
            self._abuf_out = None

    # ── Громкость выходов ────────────────────────────────────────────────────
    def _output_volume(self):
        """Громкость звука видео и внешней озвучки: ползунок × переход."""
        try:
            v = self.vol_slider.value() / 100.0
        except Exception:
            v = 1.0
        return max(0.0, min(1.0, v * float(getattr(self, "_seek_gain", 1.0))))

    def _apply_output_volume(self):
        v = self._output_volume()
        try:
            self.audio_output.setVolume(v)
        except Exception:
            pass
        ext = getattr(self, "_ext_audio_output", None)
        if ext is not None:
            try:
                ext.setVolume(v)
            except Exception:
                pass

    def _set_seek_gain(self, gain):
        self._seek_gain = max(0.0, min(1.0, float(gain)))
        self._apply_output_volume()

    # ── Звук после перемотки на ходу ─────────────────────────────────────────
    def _seek_fade_begin(self, target_ms):
        """Перед перемоткой на ходу: звук нового места поднимется плавно, когда
        отыграет его рваное начало (см. докстроку модуля)."""
        self._seek_fade_gen += 1
        gen = self._seek_fade_gen
        self._seek_fade = {'gen': gen, 'target': int(target_ms),
                           'at': _api.time.monotonic(), 'heard': False, 'ramping': False}
        self._set_seek_gain(0.0)
        _api.QTimer.singleShot(self._SEEK_FADE_MAX_MS, lambda g=gen: self._seek_fade_ramp(g))

    def _seek_fade_cancel(self):
        """Воспроизведение встало — громкость сразу к ползунку."""
        if self._seek_fade is None and self._seek_gain >= 1.0:
            return
        self._seek_fade = None
        self._seek_fade_gen += 1
        self._set_seek_gain(1.0)

    def _on_player_audio_buffer(self, buf):
        fade = self._seek_fade
        if fade is None or fade['heard']:
            return
        # Буферы прежнего места ещё могут стоять в очереди событий, а новое место
        # раньше ~0.1 с после перемотки не звучит.
        if _api.time.monotonic() - fade['at'] < 0.04:
            return
        try:
            t_ms = buf.startTime() / 1000.0
        except Exception:
            return
        if not (fade['target'] - 250 <= t_ms <= fade['target'] + 2000):
            return
        fade['heard'] = True
        # Сигнал мог прийти с опозданием (главный поток занят выводом кадров):
        # сколько звук уже идёт, видно по часам плеера — их и вычитаем.
        try:
            played = max(0.0, self.player.position() - t_ms)
        except Exception:
            played = 0.0
        hold = max(0, int(self._SEEK_FADE_HOLD_MS - played))
        _api.QTimer.singleShot(hold, lambda g=fade['gen']: self._seek_fade_ramp(g))

    def _seek_fade_ramp(self, gen, step=0):
        fade = self._seek_fade
        if fade is None or fade['gen'] != gen:
            return
        if step == 0:
            if fade['ramping']:
                return              # и буфер, и страховочный таймер — нарастаем один раз
            fade['ramping'] = True
        steps = self._SEEK_FADE_STEPS
        self._set_seek_gain(steps[step])
        if step + 1 < len(steps):
            _api.QTimer.singleShot(self._SEEK_FADE_STEP_MS,
                                   lambda: self._seek_fade_ramp(gen, step + 1))
        else:
            self._seek_fade = None

    # ── Протяжка плейхеда мышью ──────────────────────────────────────────────
    def _project_scrub_started(self):
        """Плейхед потянули по таймлайну. Шло воспроизведение — встаём на паузу
        до отпускания: перемотка плеера на каждое движение мыши рассыпала звук
        на обрывки, а картинка не успевала за мышью."""
        self._tl_dragging = True
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState
                       and not getattr(self, "_prerolling", False))
        except Exception:
            playing = False
        self._tl_drag_resume = playing
        if not playing:
            return
        if getattr(self, "_proj_play", None) is not None:
            self.project_stop()
        else:
            self.player.pause()

    def _project_scrub_finished(self):
        """Отпустили плейхед: последнюю точку — плееру, и воспроизведение
        продолжается оттуда, если шло до протяжки."""
        self._tl_dragging = False
        self._drag_seek_flush()
        resume = self._tl_drag_resume
        self._tl_drag_resume = False
        if resume:
            if getattr(self, "project_timeline", None) is not None and not self.project.is_empty():
                self.project_play()
            else:
                self._play_from_here()
            return
        # На паузе: точный кадр, окно звука скраба и прогрев — тем же путём, что
        # после любой перемотки (_on_scrub_idle), пока кнопку держали — ждали.
        try:
            self._scrub_idle_timer.start()
        except Exception:
            pass

    def _drag_seek(self, ms):
        """Перемотка плеера во время протяжки: в полёте не больше одной, новая
        цель заменяет отложенную (см. докстроку модуля)."""
        self._drag_seek_want = int(ms)
        if self._drag_seek_busy is None:
            self._drag_seek_send()

    def _drag_seek_send(self):
        ms = self._drag_seek_want
        self._drag_seek_want = None
        if ms is None:
            self._drag_seek_busy = None
            return
        self._drag_seek_busy = (ms, _api.time.monotonic())
        self.player.setPosition(ms)
        self._ext_audio_seek(ms)
        t = self._drag_seek_timer
        if t is None:
            t = _api.QTimer(self)
            t.setInterval(15)
            t.timeout.connect(self._drag_seek_poll)
            self._drag_seek_timer = t
        t.start()

    def _drag_seek_poll(self):
        busy = self._drag_seek_busy
        if busy is None:
            if self._drag_seek_timer is not None:
                self._drag_seek_timer.stop()
            return
        _ms, at = busy
        waited = _api.time.monotonic() - at
        done = waited > self._DRAG_SEEK_TIMEOUT_S
        if not done:
            vw = getattr(self, "video_widget", None)
            if (not isinstance(vw, _api.VideoCanvas) or self.video_stream_index is None
                    or getattr(self, "_audio_only_mode", False)):
                done = True                 # кадров не будет — ждать нечего
            else:
                last = getattr(vw, "_last_player_frame_at", None)
                if last is None:
                    age = vw.frame_clock_age()
                else:
                    age = (_api.time.monotonic() - last) if last > 0 else None
                done = age is not None and age < waited   # кадр пришёл после перемотки
        if not done:
            return
        self._drag_seek_busy = None
        if self._drag_seek_want is not None:
            self._drag_seek_send()
        elif self._drag_seek_timer is not None:
            self._drag_seek_timer.stop()

    def _drag_seek_flush(self):
        """Кнопку отпустили: последняя точка протяжки уходит плееру сразу, не
        дожидаясь кадра предыдущей."""
        if self._drag_seek_want is not None:
            self._drag_seek_busy = None
            self._drag_seek_send()

    # ── Кадр остановки ───────────────────────────────────────────────────────
    def _stop_frame_index(self, keep=None):
        """Кадр, на котором встал плеер (пауза, конец прогрева).

        Обычно это показанный кадр — часы холста. Но показанный кадр бывает
        ЧУЖИМ: после перемотки плеер тяжёлого файла ещё не прислал ни одного
        кадра нового места (BDRemux с аппаратным декодером — ни одного кадра за
        0.7 с прогрева), и на холсте висит кадр, где стояли ДО перемотки. Раньше
        по нему и вставали: через полсекунды после клика по шкале плейхед и
        картинка прыгали обратно, а «Пробел» играл не оттуда, куда кликнули.
        Чужой кадр видно по расхождению с позицией плеера — тогда верим
        заказанному кадру (keep) или самой позиции."""
        grid = self._grid
        idx = self._current_frame_index()
        try:
            pos_s = self.player.position() / 1000.0
        except Exception:
            return idx
        tol = max(0.5, 3.0 / grid.fps) if grid.fps > 0 else 0.5
        if abs(grid.start_of(idx) - pos_s) <= tol:
            return idx
        if keep is not None and abs(grid.start_of(keep) - pos_s) <= tol + 1.0:
            return grid.clamp(keep)
        return grid.index_at(pos_s)

    # ── Прогрев после кадра ──────────────────────────────────────────────────
    def _preroll_when_shown(self):
        """Прогрев звука — когда кадр нового места уже на экране (или ждать его
        дольше _PREROLL_WAIT_MAX_S): прогрев перематывает плеер на разбег и
        отменил бы ещё не законченное декодирование этого кадра."""
        idx = self._frame_idx
        if idx is None:
            self._preroll_at(self._playhead_target_s())
            return
        self._preroll_wait = (idx, _api.time.monotonic())
        t = self._preroll_wait_timer
        if t is None:
            t = _api.QTimer(self)
            t.setInterval(25)
            t.timeout.connect(self._preroll_wait_tick)
            self._preroll_wait_timer = t
        t.start()
        self._preroll_wait_tick()

    def _preroll_wait_cancel(self):
        self._preroll_wait = None
        if self._preroll_wait_timer is not None:
            self._preroll_wait_timer.stop()

    def _preroll_wait_tick(self):
        wait = self._preroll_wait
        if wait is None:
            self._preroll_wait_cancel()
            return
        idx, at = wait
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if (playing or getattr(self, "_prerolling", False) or getattr(self, "_scrubbing", False)
                or self._tl_dragging or self._frame_idx != idx):
            self._preroll_wait_cancel()       # ушли с этого кадра — прогреет следующая остановка
            return
        vw = getattr(self, "video_widget", None)
        shown = (not isinstance(vw, _api.VideoCanvas) or self.video_stream_index is None
                 or getattr(self, "_audio_only_mode", False)
                 or vw.pinned_frame_pts() is not None)
        if not shown and _api.time.monotonic() - at < self._PREROLL_WAIT_MAX_S:
            return
        self._preroll_wait_cancel()
        self._preroll_at(self._playhead_target_s())
