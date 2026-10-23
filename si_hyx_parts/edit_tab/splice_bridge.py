# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: стык кусков проекта на ходу без замирания картинки.

Куски одного файла (вырезали середину — остались два) просмотр проекта
играет одним плеером. Раньше на стыке плеер вставал на паузу, перематывался и
запускался заново: звук и декодер остывали, и картинка стояла ~0.3 с, а потом
проглатывала кадры, догоняя звук. Теперь плеер перематывается, не
останавливаясь (_proj_seamless_next), но и такая перемотка раскручивает GOP
от ключевого кадра: замер на 1080p H.264 с GOP 2 с — 0.29–0.32 с без новых
кадров, а у аниме-BDRip ключевые кадры реже. Поэтому за _LEAD_S до стыка
предекодер кадров (FramePrefetcher) заранее достаёт начало следующего куска,
и на стыке холст показывает эти кадры по часам, пока плеер не привезёт свои
(«мост»).

Пока плеер не показал ни одного кадра нового куска, границы проекта не
проверяются (_proj_seam_pending): позиция плеера и кадры, приехавшие из очереди
до перемотки, ещё относятся к прежнему месту — кусок, стоящий в файле раньше
прежнего, принял бы их за свой конец и перескочил бы дальше."""
import math

import edit_tab as _api

_LEAD_S = 2.0            # за сколько до конца куска заказывать кадры следующего
_SPAN_S = 0.6            # сколько начала следующего куска держать наготове
_SEAM_MAX_S = 2.0        # дольше кадров плеера не ждём (как _PLAY_SEEK_HOLD_MAX_S)


class EditTabSpliceBridgeMixin:
    """Монтаж: стык кусков проекта на ходу без замирания картинки."""

    def _proj_seamless_next(self):
        """Конец куска на ходу, а следующий кусок — видео того же открытого
        файла: перематываем, не останавливая плеер, и закрываем перемотку
        готовыми кадрами. True — переход сделан (другой файл, картинка или
        пустота идут прежним путём — паузой и запуском)."""
        plan = self._proj_play
        if plan is None or self._proj_transition:
            return False
        nxt = self._proj_idx + 1
        if not 0 <= nxt < len(plan):
            return False
        clip = plan[nxt]['clip']
        if clip is None or clip.is_image or not self._proj_ready_for(clip.src):
            return False
        try:
            if (self.player.playbackState() != _api.QMediaPlayer.PlaybackState.PlayingState
                    or getattr(self, "_prerolling", False)):
                return False
        except Exception:
            return False
        vw = self.video_widget
        canvas = isinstance(vw, _api.VideoCanvas)
        self._proj_seam = ((vw.player_frame_seq() if canvas else 0),
                           _api.time.monotonic(), canvas)
        self._proj_play_segment(nxt, 0.0, cont=True)
        hold = getattr(self, "_play_seek_hold", None)
        target_s = (hold[0] / 1000.0) if hold is not None else plan[nxt]['s0']
        self._bridge_begin(target_s, plan[nxt]['s1'])
        return True

    def _proj_seam_pending(self):
        """Плеер перемотан на стыке, но кадров нового куска ещё не показал."""
        seam = getattr(self, "_proj_seam", None)
        if seam is None:
            return False
        seq, at, canvas = seam
        if _api.time.monotonic() - at > _SEAM_MAX_S or (
                canvas and self.video_widget.player_frame_seq() != seq):
            self._proj_seam = None
            return False
        if not canvas:
            # Без холста кадров не видно — хватает того, что позиция плеера
            # ушла с прежнего места (_SEAM_MAX_S страхует).
            self._proj_seam = None
            return False
        return True

    # ── Кадры начала следующего куска ────────────────────────────────────────
    def _bridge_frames(self):
        fps = self._grid.fps if self._grid.valid else 0.0
        return max(2, min(_api.FramePrefetcher.MAX_WINDOW, int(math.ceil(_SPAN_S * fps))))

    def _bridge_prefetch(self, src_s):
        """Плеер играет кусок (_proj_tick): у его конца заказываем кадры
        начала следующего, если стык пойдёт на ходу внутри файла."""
        plan = self._proj_play
        if plan is None or not self._grid.valid or not isinstance(
                self.video_widget, _api.VideoCanvas):
            return
        cur = plan[self._proj_idx]
        nxt = self._proj_idx + 1
        speed = max(0.1, cur['clip'].speed) if cur['clip'] is not None else 1.0
        if (cur['clip'] is None or nxt >= len(plan)
                or (cur['s1'] - src_s) / speed > _LEAD_S):
            return
        clip = plan[nxt]['clip']
        if clip is None or clip.is_image or not self._proj_is_loaded(clip.src):
            return
        idx = self._grid.index_at(plan[nxt]['s0'])
        key = (id(plan), nxt, idx)
        if getattr(self, "_bridge_req", None) == key:
            return
        self._bridge_req = key
        try:
            self._frames_engine().request(idx, ahead=self._bridge_frames(), behind=0)
        except Exception:
            pass

    def _bridge_begin(self, start_s, end_s):
        """Плеер перематывается на ходу к start_s: показываем готовые кадры
        отсюда, пока не придёт его первый кадр."""
        self._bridge_stop()
        eng = getattr(self, "_frames", None)
        vw = self.video_widget
        if eng is None or not self._grid.valid or not isinstance(vw, _api.VideoCanvas):
            return
        idx0 = self._grid.index_at(start_s)
        if eng.frame(idx0) is None:
            return                      # не успели раскодировать — обычная перемотка
        last = max(idx0, self._grid.index_at(max(start_s, end_s - 1e-3)))
        plan = self._proj_play
        clip = (plan[self._proj_idx]['clip']
                if plan is not None and 0 <= self._proj_idx < len(plan) else None)
        speed = max(0.1, clip.speed) if clip is not None else 1.0
        self._bridge = {'idx0': idx0, 'last': last, 'shown': None, 'speed': speed,
                        't0': _api.time.monotonic(), 'seq': vw.player_frame_seq()}
        timer = getattr(self, "_bridge_timer", None)
        if timer is None:
            timer = self._bridge_timer = _api.QTimer(self)
            timer.setTimerType(_api.Qt.TimerType.PreciseTimer)
            timer.timeout.connect(self._bridge_tick)
        # Полкадра: кадр выходит не позже чем через полкадра после своего срока.
        timer.start(max(5, int(500.0 / self._grid.fps)))
        self._bridge_tick()

    def _bridge_tick(self):
        b = getattr(self, "_bridge", None)
        if b is None:
            return
        vw = self.video_widget
        eng = getattr(self, "_frames", None)
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        elapsed = _api.time.monotonic() - b['t0']
        if (not playing or self._proj_play is None or eng is None
                or not isinstance(vw, _api.VideoCanvas)
                or vw.player_frame_seq() != b['seq'] or elapsed > _SEAM_MAX_S):
            self._bridge_stop()         # плеер привёз свой кадр — дальше он
            return
        idx = min(b['idx0'] + int(elapsed * self._grid.fps * b.get('speed', 1.0)),
                  b['last'])
        if idx == b['shown']:
            return
        img = eng.frame(idx)
        if img is None:
            return                      # запас кончился — стоим на последнем
        b['shown'] = idx
        start = self._grid.start_of(idx)
        vw.show_bridge_frame(img, int(round(start * 1_000_000)))
        # Свой кадр плеер покажет, только догнав мост: тот же кадр или новее.
        vw.raise_play_floor(start - 0.5 / self._grid.fps)

    def _bridge_stop(self):
        self._bridge = None
        timer = getattr(self, "_bridge_timer", None)
        if timer is not None:
            timer.stop()

