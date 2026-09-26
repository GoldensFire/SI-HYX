# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _confirm_frame_seek. Public namespace: edit_tab."""
import edit_tab as _api


def _confirm_frame_seek(self, pos_ms):
    """Вызывается из on_position_changed на каждое реальное изменение позиции:
        как только плеер довёл её до запрошенной цели — освобождаем «в полёте»
        сразу, не дожидаясь запасного таймера (и шлём накопившуюся свежую цель,
        если пользователь всё ещё держит стрелку)."""
    if not getattr(self, "_frame_seek_busy", False):
        return
    target = getattr(self, "_frame_seek_target_ms", None)
    if target is None:
        return
    tol_ms = max(20, int(1000.0 / self.fps)) if (self.fps and self.fps > 0) else 40
    if abs(pos_ms - target) <= tol_ms:
        self._release_frame_seek(self._frame_seek_gen)

def _release_frame_seek(self, gen=None):
    if gen is not None and gen != getattr(self, "_frame_seek_gen", None):
        return   # устаревший вызов — «в полёте» уже другая, более поздняя цель
    self._frame_seek_busy = False
    self._frame_seek_target_ms = None
    pending = getattr(self, "_frame_seek_pending", None)
    if pending is not None:
        self._frame_seek_pending = None
        self._dispatch_frame_seek(pending)

def step_frame_scrub(self, step):
    # Идёт беззвучный прогрев — гасим его ДО шага: иначе плеер играет (пусть
    # и под mute), а мы тут же дёргаем ему позицию, и они мешают друг другу.
    # Именно cancel, а не finish: доводить позицию до УСТАРЕВШЕЙ цели незачем,
    # шаг сейчас поставит свою — лишний seek только съел бы кадр времени.
    # Прогрев вернётся, когда серия шагов утихнет (см. _end_scrub_painted).
    if getattr(self, "_prerolling", False):
        self._preroll_cancel()
    playing = (self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState)
    painted = isinstance(self.video_widget, _api.VideoCanvas)
    # Серия шагов: при удержании ←/→ считаем от _scrub_target (детерминизм),
    # а на ПЕРВОМ шаге серии — от живой позиции плеера.
    if not playing and not getattr(self, "_scrubbing", False):
        self._scrub_target = None
        # Начало серии: первый шаг обязан дойти до плеера сразу (см.
        # _dispatch_frame_seek — дальше он троттлится).
        self._frame_seek_last_at = 0.0
    if not playing:
        self._scrubbing = True
        if painted:
            # Пока идёт перемотка, ЦП-копия кадров плеера не нужна: на экране
            # всё равно точный кадр предекодера, а toImage() каждого кадра
            # 1080p занимает главный поток на 8–9 мс (см. VideoCanvas.
            # _want_cpu_copy) — при удержании стрелки это и был видимый лаг.
            self.video_widget.set_scrub_active(True)
    self.step_frame(step)
    if playing:
        return
    # Скраб-звук (как в Filmora): короткий звуковой блип в новой позиции.
    # В painted-режиме видео уже доставлено setPosition'ом — звук добавляем,
    # не трогая кадр (см. _scrub_audio_blip).
    self._scrub_audio_blip(painted)
    # Оживляем индикатор уровня и на покадровом шаге (на паузе он иначе молчит,
    # из-за чего казалось, что звука нет).
    tgt_ms = getattr(self, "_scrub_audio_ms", None)
    if tgt_ms is None:
        tgt_ms = (self._scrub_target if self._scrub_target is not None
                  else self.player.position())
    self._update_meter((tgt_ms or 0) / 1000.0, force=True)
    if painted:
        # painted-режим (VideoCanvas + QVideoSink): пауза + setPosition сама
        # доставляет новый кадр в сink — короткий play() НЕ нужен (именно он
        # давал мерцание/скачок назад-вперёд). Флаг скраба снимаем таймером,
        # перезапускаемым на каждом шаге (серия удержания не рвётся).
        if not hasattr(self, "_scrub_reset_timer"):
            self._scrub_reset_timer = _api.QTimer(self)
            self._scrub_reset_timer.setSingleShot(True)
            self._scrub_reset_timer.timeout.connect(self._end_scrub_painted)
        self._scrub_reset_timer.start(160)
        return
    # overlay-режим (QVideoWidget): нативная поверхность без play() кадр не
    # перерисовывает — прежний приём с коротким play() и возвратом на цель.
    self._scrubbing = True
    self.player.play()
    _api.QTimer.singleShot(60, self._end_scrub)

def _end_scrub_painted(self):
    self._scrubbing = False
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.set_scrub_active(False)
    # Плееру — итоговая позиция серии (во время неё он получал её не чаще
    # _SCRUB_SEEK_MS, см. _dispatch_frame_seek). Обязательно ДО прогрева:
    # прогрев считает разбег от этой же точки.
    self._flush_frame_seek()
    # Серия покадровых шагов закончилась — прогреваем конвейер там, где
    # встали. Обычный сценарий монтажа «долистал кадрами → Пробел» после
    # этого стартует без заминки (см. _preroll_at). Ни звука (mute), ни
    # движения на шкале (часы заморожены на цели) прогрев не даёт.
    try:
        if (self.player.playbackState()
                != _api.QMediaPlayer.PlaybackState.PlayingState):
            self._preroll_at(self._playhead_target_s())
    except Exception:
        pass
