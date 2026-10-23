# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: звук всех дорожек в просмотре проекта.

Просмотр проекта (EditTabProjectMixin) играет картинку цепочкой кусков в
основном плеере, и его звук годится только для видимого куска: он идёт из
того же файла, что и картинка, и синхронен с ней без всякой подгонки. Всё
остальное, что слышно в собранном файле, — клипы звуковых дорожек, звук
нижнего видео под наложением на «Видео 2», клип со звуком из другой дорожки
или озвучки — играют «голоса»: по своему QMediaPlayer на клип. Громкость и
«без звука» клипа действуют и на голос, и на основной плеер.

Часы проекта: пока основной плеер играет кусок — его позиция (звук к звуку,
как у внешней озвучки в sync_ui); на картинке, в пустоте и в переходе внутри
файла — стена от последней отметки; пока грузится другой видеофайл — стоят,
голоса на паузе, и после загрузки часы ждут, пока плеер тронется. На стыке
внутри файла голоса не останавливаются, а картинка следующего куска
начинается с того места, куда они успели доиграть.

Замерено WASAPI-метром (Qt 6.10, ffmpeg-бэкенд): первый старт плеера
разгоняется 0.02–0.4 с (смотря по загрузке машины, из видеофайла дольше),
перемотка на ходу — ≈0.1 с, пауза и продолжение — без повтора звука; позиция
плеера идёт ступеньками по 40–85 мс. Поэтому голос стартует с опережением на
свой разгон (уточняется замером на каждом старте), а рассинхрон правится
перемоткой только выше 130 мс по сглаженному среднему (порог озвучки).
После смены видеофайла звук самого видео молчит ≈0.6–0.8 с (холодный старт
плеера) — так было и до голосов, музыка дорожек в это время слышна."""
import math
import time

import edit_tab as _api
from sip_notify import prime_disconnect_notify

_TICK_MS = 40            # шаг сверки голосов с часами проекта
_LOOKAHEAD_S = 2.5       # за сколько до клипа голос открывает файл
_RUNUP_S = 0.8           # беззвучный разбег голоса перед началом клипа
_DRIFT_S = 0.13          # порог рассинхрона голоса (как у озвучки в sync_ui)
_SETTLE_S = 0.5          # после старта/перемотки позиция плеера ещё не верна
_FOLLOW_S = 0.06         # часы проекта догоняют основной плеер выше этого
_ROLL_WAIT_S = 1.5       # дольше не ждём, пока основной плеер тронется
_CATCH_UP_MAX_S = 0.3    # переход внутри файла: картинка догоняет голоса
_START_LAG_S = 0.05      # разгон основного плеера на стыке (уточняется замером)
# Разгон голоса — на сколько позиция отстаёт от заказанной после старта:
# первый старт плеера медленнее (замерено 0.02–0.4 с, смотря по загрузке
# машины), перемотка на ходу — ≈0.1 с. Начальные значения уточняются
# замером на каждом старте (_pmix_drive).
_LAG_START = {'fresh': 0.12, 'seek': 0.1}


class _Voice:
    """Звук одного клипа: свой плеер и аудиовыход."""
    __slots__ = ("cid", "player", "output", "ready", "failed", "started", "since",
                 "gain", "drift_n", "drift_avg", "stale", "check")

    def __init__(self, cid, player, output):
        self.cid = cid
        self.player = player
        self.output = output
        self.ready = False        # файл открыт (LoadedMedia), дорожка выбрана
        self.failed = False
        self.started = False      # уже играл: следующий старт быстрый
        self.since = 0.0          # когда стартовал или перематывался
        self.gain = None          # множитель громкости клипа, None — не задан
        self.drift_n = 0          # замеров рассинхрона после старта
        self.drift_avg = 0.0      # сглаженный рассинхрон, с (+ — голос впереди)
        self.stale = False        # часы прыгнули (клик по таймлайну) — перемотать сразу
        self.check = None         # (род разгона, заложенное опережение) — замерить

    def playing(self):
        return self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState


class EditTabProjectAudioMixin:
    """Монтаж: звук дорожек проекта в просмотре — голоса и громкость клипов."""

    def _pmix_init(self):
        """Вызывается из _project_init."""
        self._pmix_voices = {}        # id клипа → _Voice
        self._pmix_parts = {}         # id → клип, чей звук попадает в итог
        self._pmix_need = set()       # id клипов, которым голос понадобится заранее
        self._pmix_vis = []           # [(t0, t1, клип|None)] — что в кадре проекта
        self._pmix_clock = None       # (t, monotonic, идут ли часы)
        self._pmix_main_since = 0.0
        self._pmix_follow_ticks = 0
        self._pmix_gain = None        # множитель громкости основного плеера
        self._pmix_hold = None        # (t0, t1): картинка или пустота, плеер стоит
        self._pmix_streams = {}       # путь → абсолютные индексы звуковых потоков
        self._pmix_timer = None
        self._pmix_wait = None        # (позиция, с которой тронется плеер, когда заказали)
        self._pmix_lag = {}           # разгон голосов по родам (см. _LAG_START)
        self._pmix_main_lag = _START_LAG_S
        self._pmix_main_check = False # замерить разгон основного плеера на стыке

    # ── Запуск и остановка ───────────────────────────────────────────────────
    def _pmix_start(self):
        """Просмотр проекта начался: что слышно и что видно — снимок проекта."""
        self._pmix_release_all()
        p = self.project
        parts = p.audio_parts()
        self._pmix_parts = {c.id: c for c in parts}
        self._pmix_vis = list(p.preview_segments())
        # Звук своим трактом (project_sound) сводит все дорожки сам — голоса
        # не нужны; часы проекта тогда — его часы (_pmix_now).
        self._pmix_need = (set() if getattr(self, "_snd_active", False)
                           else {c.id for c in parts if self._pmix_needs_voice(c)})
        self._pmix_clock = None
        self._pmix_hold = None
        self._pmix_wait = None
        if self._pmix_timer is None:
            self._pmix_timer = _api.QTimer(self)
            self._pmix_timer.setTimerType(_api.Qt.TimerType.PreciseTimer)
            self._pmix_timer.setInterval(_TICK_MS)
            self._pmix_timer.timeout.connect(self._pmix_tick)
        self._pmix_timer.start()

    def _pmix_stop(self):
        """Просмотр окончен: голоса закрыты (файлы свободны), громкость
        основного плеера — снова по ползунку."""
        if self._pmix_timer is not None:
            self._pmix_timer.stop()
        self._pmix_release_all()
        self._pmix_clock = None
        self._pmix_hold = None
        self._pmix_set_main_gain(None)

    # ── Часы проекта ─────────────────────────────────────────────────────────
    def _pmix_now(self):
        if getattr(self, "_snd_active", False):
            t = self._snd_now()
            if t is not None:
                return t
        clk = self._pmix_clock
        if clk is None:
            return None
        t, at, running = clk
        return t + (time.monotonic() - at) if running else t

    def _pmix_running(self):
        if getattr(self, "_snd_active", False) and self._snd_now() is not None:
            return True
        return self._pmix_clock is not None and self._pmix_clock[2]

    def _pmix_anchor(self, t, running=True, main=False, jump=False, src_ms=None):
        """Отметка часов: время проекта t сейчас. main — основной плеер
        стартует кусок с позиции src_ms; jump — время прыгнуло (клик по
        таймлайну, начало просмотра), голоса перематываются сразу.

        Если часы стояли (загрузка файла) или прыгнули, они ждут, пока
        основной плеер тронется с места: после загрузки он разгоняется
        заметно дольше вызова play() (0.1–0.15 с, под нагрузкой больше), и
        голоса, пущенные сразу, уходили бы вперёд — часы потом тянуло бы
        назад, а голоса перематывало."""
        now = time.monotonic()
        self._pmix_wait = None
        if main and not jump and self._pmix_running():
            # Стык внутри файла: часы идут как шли, картинка стартует с
            # опережением на разгон (_pmix_catch_up).
            self._pmix_main_since = now
            return
        if main and src_ms is not None:
            self._pmix_wait = (int(src_ms), now)
            running = False
        self._pmix_clock = (float(t), now, bool(running))
        self._pmix_main_check = False
        if main:
            self._pmix_main_since = now
        if jump:
            for v in self._pmix_voices.values():
                v.stale = True
        if not running:
            for v in self._pmix_voices.values():
                if v.ready and v.playing():
                    v.player.pause()

    def _pmix_follow_main(self):
        """Пока основной плеер играет кусок, часы проекта — его позиция."""
        plan = self._proj_play
        if plan is None or self._proj_transition or self._pmix_hold is not None:
            return
        if getattr(self, "_snd_active", False):
            return                      # часы проекта — часы звука тракта
        if not (0 <= self._proj_idx < len(plan)):
            return
        seg = plan[self._proj_idx]
        clip = seg['clip']
        if clip is None or clip.is_image or getattr(self, "_prerolling", False):
            return
        try:
            if self.player.playbackState() != _api.QMediaPlayer.PlaybackState.PlayingState:
                return
            pos_ms = self.player.position()
        except Exception:
            return
        now = time.monotonic()
        speed = max(0.1, clip.speed)
        t_main = seg['t0'] + (pos_ms / 1000.0 - seg['s0']) / speed
        wait = self._pmix_wait
        if wait is not None:
            if pos_ms < wait[0] + 15 and now - wait[1] < _ROLL_WAIT_S:
                return
            # Тронулся — часы пошли. Позиция ступенчатая и могла уже
            # убежать на шаг: считаем, что плеер тронулся только что.
            self._pmix_wait = None
            t_req = seg['t0'] + (wait[0] / 1000.0 - seg['s0']) / speed
            self._pmix_clock = (min(t_main, t_req + _TICK_MS / 2000.0), now, True)
            self._pmix_main_since = now
            return
        if now - self._pmix_main_since < _SETTLE_S:
            return
        cur = self._pmix_now()
        if self._pmix_main_check and cur is not None:
            # Картинку пустили с опережением lag, плеер отстал от часов на
            # lag - (t_main - cur): столько он и разгоняется на стыке.
            self._pmix_main_check = False
            seen = self._pmix_main_lag - (t_main - cur)
            self._pmix_main_lag = max(0.0, min(0.25, 0.5 * self._pmix_main_lag + 0.5 * seen))
        # Между стартами часы идут по стене и подтягиваются к плееру, только
        # если разошлись устойчиво: его позиция идёт ступеньками по 40–100 мс,
        # и часы, прыгающие за каждой, дёргали бы голоса на перемотку.
        if cur is None or abs(t_main - cur) <= _FOLLOW_S:
            self._pmix_follow_ticks = 0
            return
        self._pmix_follow_ticks += 1
        if self._pmix_follow_ticks >= 3:
            self._pmix_clock = (t_main, now, True)
            self._pmix_follow_ticks = 0

    def _pmix_catch_up(self, seg, offset, lag=None):
        """Переход к следующему куску: пока плеер вставал на новое место,
        голоса играли дальше. Картинка начинает с того места, где они сейчас
        (lag — поправка на разгон плеера), а не стоит на месте — иначе звук
        дорожек уходил бы вперёд на каждом стыке."""
        if getattr(self, "_snd_active", False):
            return self._pmix_catch_up_sound(seg, offset)
        if not self._pmix_running() or not any(
                v.ready and v.gain and v.playing() for v in self._pmix_voices.values()):
            return offset
        late = self._pmix_now() - seg['t0'] + (self._pmix_main_lag if lag is None else lag)
        if late <= offset or late > _CATCH_UP_MAX_S:
            return offset
        fps = seg['clip'].fps
        speed = max(0.1, seg['clip'].speed)
        if fps and fps > 0:
            # На начало кадра: плейхед иначе откатывался бы к нему на ходу.
            frame = math.ceil((seg['s0'] + late * speed) * fps - 1e-3) / fps
            late = (frame - seg['s0']) / speed
        self._pmix_main_check = True     # замерим, угадали ли разгон плеера
        return min(late, max(0.0, seg['t1'] - seg['t0'] - 0.05))

    def _pmix_catch_up_sound(self, seg, offset):
        """То же для звука своим трактом: он не ждёт ни перемотки, ни загрузки
        файла, и картинка начинает с того места, где звучит звук, — без
        предела: картинка без аудиовыхода плеера идёт ровно по стене и потом
        от звука не отстаёт. До ближайшего кадра (не вверх): на стыке звук и
        картинка расходятся на миллисекунды, и округление вверх съедало бы
        первый кадр куска."""
        now = self._snd_now()
        if now is None:
            return offset
        late = now - seg['t0']
        if late <= offset:
            return offset
        fps = seg['clip'].fps if seg['clip'] is not None else 0.0
        speed = max(0.1, seg['clip'].speed) if seg['clip'] is not None else 1.0
        if fps and fps > 0:
            frame = round((seg['s0'] + late * speed) * fps) / fps
            late = (frame - seg['s0']) / speed
        return min(max(offset, late), max(0.0, seg['t1'] - seg['t0'] - 0.05))

    # ── Основной плеер ───────────────────────────────────────────────────────
    def _pmix_norm(self, path):
        try:
            return _api.os.path.normcase(_api.os.path.abspath(str(path)))
        except Exception:
            return str(path)

    def _pmix_audio_streams(self, path):
        """Абсолютные индексы звуковых потоков файла (по порядку — это и
        порядок audioTracks() у QMediaPlayer)."""
        key = self._pmix_norm(path)
        if key in self._pmix_streams:
            return self._pmix_streams[key]
        if self._proj_is_loaded(path) and getattr(self, "_audio_streams", None):
            found = [s.get('index') for s in self._audio_streams]
        else:
            meta = _api.run_ffprobe(path) or {}
            found = [s.get('index') for s in meta.get('streams') or []
                     if s.get('codec_type') == 'audio']
        self._pmix_streams[key] = found
        return found

    def _pmix_main_carries(self, clip):
        """Основной плеер играет ровно звук клипа: тот же файл и тот же поток
        (выбор дорожки/озвучки в источнике мог быть другим)."""
        if clip is None or clip.is_image or not clip.audio_path:
            return False
        if not self._proj_is_loaded(clip.src) or getattr(self, "is_still_image", False):
            return False
        path, idx = self._source_audio()
        if not path or self._pmix_norm(path) != self._pmix_norm(clip.audio_path):
            return False
        want = int(clip.audio_stream)
        if idx == want:
            return True
        if idx >= 0 and want >= 0:
            return False
        streams = self._pmix_audio_streams(path)
        first = streams[0] if streams else -1
        return (idx < 0 and want == first) or (want < 0 and idx == first)

    def _pmix_visible_at(self, t):
        for t0, t1, c in self._pmix_vis:
            if t0 <= t < t1:
                return c
        return None

    def _pmix_on_segment(self, t):
        """Основной плеер играет кусок плана, в который попадает t (а не
        доигрывает прошлый за стыком и не ждёт файл следующего)."""
        plan = self._proj_play
        seg = plan[self._proj_idx] if plan and 0 <= self._proj_idx < len(plan) else None
        return (seg is not None and seg['clip'] is not None and not self._proj_transition
                and self._pmix_hold is None and seg['t0'] - 1e-3 <= t < seg['t1']
                and self._proj_is_loaded(seg['clip'].src))

    def _pmix_main_has(self, clip, t):
        """Звук клипа в момент t уже идёт из основного плеера."""
        vis = self._pmix_visible_at(t)
        if vis is None or vis.id != clip.id or self._pmix_hold is not None:
            return False
        if not self._pmix_on_segment(t) or not self._proj_is_loaded(clip.src):
            # Плеер ещё не перешёл на этот кусок (часы проекта чуть впереди
            # стыка, грузится файл): звук придёт из него, если это звук самого
            # файла, — голос ради этих долей секунды не заводим.
            return self._pmix_norm(clip.audio_path) == self._pmix_norm(clip.src)
        return self._pmix_main_carries(clip)

    def _pmix_main_gain_at(self, t):
        """Громкость основного плеера под клип в кадре: громкость клипа, а
        если звук клипа выключен (или идёт из голоса) — тишина."""
        vis = self._pmix_visible_at(t)
        part = self._pmix_parts.get(vis.id) if vis is not None else None
        if part is not None and self._pmix_main_carries(part):
            self._pmix_set_main_gain(float(part.volume))
        else:
            self._pmix_set_main_gain(0.0)

    def _pmix_base_volume(self):
        try:
            return self.vol_slider.value() / 100.0
        except Exception:
            return 1.0

    def _pmix_set_main_gain(self, gain, force=False):
        """gain=None — громкость основного плеера снова по ползунку.

        Множитель живёт в _output_volume: ползунок и плавный возврат звука
        после перемотки на ходу (timeline_seek) пересчитывают громкость с ним
        и не включают звук, выключенный в проекте (дорожка, клип, отделённый
        звук). Иначе возврат громкости после клика по шкале обходил эту
        настройку — и звук выключенной дорожки снова играл из плеера."""
        if gain is not None:
            gain = max(0.0, min(1.0, float(gain)))
        self._pmix_gain = gain
        # Ставим каждый раз, даже если множитель тот же: громкость выхода могли
        # тронуть мимо нас (ползунок, возврат после перемотки на ходу) — она
        # должна снова считаться с тем, что выключено в проекте.
        self._apply_output_volume()

    def _pmix_apply_volume(self):
        """Ползунок громкости сдвинули во время просмотра."""
        if self._pmix_gain is not None:
            self._pmix_set_main_gain(self._pmix_gain, force=True)
        for v in self._pmix_voices.values():
            if v.gain is not None:
                self._pmix_set_voice_gain(v, v.gain, force=True)

    # ── Голоса ───────────────────────────────────────────────────────────────
    def _pmix_needs_voice(self, clip):
        """Понадобится ли клипу голос: звуковой клип, клип со звуком не из
        своего файла, видео, которое где-то перекрыто сверху."""
        if not clip.has_video or clip.is_image:
            return True
        if self._pmix_norm(clip.audio_path) != self._pmix_norm(clip.src):
            return True
        shown = sum(t1 - t0 for t0, t1, c in self._pmix_vis
                    if c is not None and c.id == clip.id)
        return shown < clip.length - 1e-3

    def _pmix_voice(self, clip):
        v = self._pmix_voices.get(clip.id)
        if v is not None:
            return v
        player = _api.QMediaPlayer(self)
        output = prime_disconnect_notify(_api.QAudioOutput(self))
        output.setVolume(0.0)
        player.setAudioOutput(output)
        v = _Voice(clip.id, player, output)
        player.mediaStatusChanged.connect(lambda st, v=v: self._pmix_on_status(v, st))
        self._pmix_voices[clip.id] = v
        player.setSource(_api.QUrl.fromLocalFile(str(clip.audio_path)))
        return v

    def _pmix_on_status(self, v, status):
        if self._pmix_voices.get(v.cid) is not v:
            return
        S = _api.QMediaPlayer.MediaStatus
        if status == S.InvalidMedia:
            v.failed = True
            return
        if v.ready or status not in (S.LoadedMedia, S.BufferedMedia):
            return
        clip = self._pmix_parts.get(v.cid)
        if clip is None:
            return
        try:
            # Картинку голос не выводит — и не декодирует: с видеодорожкой
            # первый старт плеера был на 0.05–0.15 с медленнее.
            if v.player.videoTracks():
                v.player.setActiveVideoTrack(-1)
            if clip.audio_stream >= 0 and len(v.player.audioTracks()) > 1:
                streams = self._pmix_audio_streams(clip.audio_path)
                if clip.audio_stream in streams:
                    v.player.setActiveAudioTrack(streams.index(clip.audio_stream))
            # Встаём на нужное место заранее: старт по часам будет быстрее.
            t = self._pmix_now()
            off = 0.0 if t is None else min(max(0.0, t - clip.start), clip.length)
            v.player.setPosition(int((clip.in_s + off * max(0.1, clip.speed)) * 1000))
            self._pmix_set_rate(v.player, clip.speed)
        except Exception:
            pass
        v.ready = True
        self._pmix_tick()

    def _pmix_set_voice_gain(self, v, gain, force=False):
        if gain == v.gain and not force:
            return
        v.gain = gain
        try:
            v.output.setVolume(max(0.0, min(1.0, self._pmix_base_volume() * gain)))
        except Exception:
            pass

    def _pmix_release(self, cid):
        v = self._pmix_voices.pop(cid, None)
        if v is None:
            return
        try:
            v.player.stop()
            v.player.setSource(_api.QUrl())
        except Exception:
            pass
        v.player.deleteLater()
        v.output.deleteLater()

    def _pmix_release_all(self):
        for cid in list(getattr(self, "_pmix_voices", {})):
            self._pmix_release(cid)

    @staticmethod
    def _pmix_set_rate(player, speed):
        """Скорость голоса под ускоренный клип (1 — обычная)."""
        try:
            rate = max(0.1, min(8.0, float(speed)))
            if abs(player.playbackRate() - rate) > 1e-3:
                player.setPlaybackRate(rate)
        except Exception:
            pass

    def _pmix_drive(self, v, target, gain, now):
        """Голос играет место target (с) исходника с громкостью клипа gain."""
        clip = self._pmix_parts.get(v.cid)
        if clip is not None:
            self._pmix_set_rate(v.player, clip.speed)
        if not v.playing():
            if not v.started:
                self._pmix_seek(v, target, 'fresh')
            elif v.stale or abs(v.player.position() / 1000.0 - target) > _DRIFT_S:
                self._pmix_seek(v, target, 'seek')
            else:
                # Голос стоит, где его застала пауза (ждали файл следующего
                # куска): продолжаем без перемотки — та дала бы повтор звука.
                v.check = None
            v.player.play()
            v.started = True
            v.since, v.drift_n, v.stale = now, 0, False
        elif v.stale:
            self._pmix_seek(v, target, 'seek')
            v.since, v.drift_n, v.stale = now, 0, False
        elif now - v.since > _SETTLE_S:
            drift = v.player.position() / 1000.0 - target
            if v.check is not None:
                # Заложили опережение k, голос отстал на k - drift: так и
                # разгоняется этот плеер — следующий старт учтёт.
                kind, k = v.check
                v.check = None
                seen = max(0.0, min(0.5, k - drift))
                self._pmix_lag[kind] = max(0.02, min(0.4, 0.5 * k + 0.5 * seen))
            # Позиция плеера идёт ступеньками по 40–85 мс (кратно аудиокадру)
            # раз в 50 мс: одиночный замер шумит на ±25 мс — судим по среднему.
            v.drift_avg = drift if v.drift_n == 0 else 0.7 * v.drift_avg + 0.3 * drift
            v.drift_n += 1
            if v.drift_n >= 3 and abs(v.drift_avg) > _DRIFT_S:
                self._pmix_seek(v, target, 'seek')
                v.since, v.drift_n = now, 0
        self._pmix_set_voice_gain(v, gain)

    def _pmix_seek(self, v, target, kind):
        """Перемотка голоса с опережением на его разгон (kind — первый старт
        плеера или перемотка уже игравшего)."""
        # Из видеофайла плеер разгоняется дольше, чем из звукового.
        clip = self._pmix_parts.get(v.cid)
        key = f"{kind}:v" if clip is not None and clip.has_video else kind
        k = self._pmix_lag.get(key, _LAG_START[kind])
        v.player.setPosition(int((target + k) * 1000))
        v.check = (key, k)

    def _pmix_covers(self, t0, t1):
        """Звучит ли что-нибудь из голосов в [t0, t1) — пустоту в кадре тогда
        не пропускаем, а выдерживаем (в собранном файле там чёрный кадр со
        звуком)."""
        return any(c.start < t1 - 1e-3 and c.end > t0 + 1e-3
                   for c in self._pmix_parts.values())

    def _pmix_tick(self):
        """Сверка голосов с часами проекта (свой таймер: пока стоит основной
        плеер, sync_ui не тикает, а картинка/пустота/переход — тоже время)."""
        if self._proj_play is None:
            self._pmix_stop()
            return
        self._pmix_follow_main()
        t = self._pmix_now()
        if t is None:
            return
        hold = self._pmix_hold
        running = self._pmix_running()
        if hold is not None and running:
            self.project_timeline.set_playhead(min(hold[1], max(hold[0], t)))
        if getattr(self, "_snd_active", False):
            if hold is None and self._proj_transition and running:
                # Грузится файл следующего куска: звук тракта не ждёт загрузки
                # — и плейхед идёт за ним, а не стоит.
                self.project_timeline.set_playhead(t)
            return                      # звук всех дорожек — у тракта, голосов нет
        if self._pmix_on_segment(t):
            # Громкость основного плеера — только пока он на своём куске: на
            # «перебеге» за стык и в загрузке не трогаем (замерено: громкость
            # 0, выставленная на перебеге перед загрузкой другого файла, порой
            # оставляла немым весь следующий кусок).
            self._pmix_main_gain_at(t)
        now = time.monotonic()
        nearest = None
        for c in self._pmix_parts.values():
            v = self._pmix_voices.get(c.id)
            lead = c.start - t
            if t >= c.end - 0.005 or lead > _LOOKAHEAD_S:
                # Клип кончился. Голос закрываем не сразу: часы, подтянутые к
                # основному плееру, могут шагнуть чуть назад — и голос снова
                # нужен на месте, а не открытым заново.
                if v is not None:
                    if lead > _LOOKAHEAD_S or t >= c.end + 0.5:
                        self._pmix_release(c.id)
                    elif v.ready and v.playing():
                        v.player.pause()
                continue
            if lead > 1e-3:
                # Клип впереди: голос заранее открывает файл, а за _RUNUP_S до
                # начала беззвучно идёт «с разбега», если в файле есть откуда.
                # К началу клипа он уже прогрет и выверен по часам: первый старт
                # плеера медленный, а поправка перемоткой — дыра в звуке.
                if running:
                    nearest = lead if nearest is None else min(nearest, lead)
                if v is None and running and c.id in self._pmix_need:
                    v = self._pmix_voice(c)
                if v is None or not v.ready:
                    continue
                speed = max(0.1, c.speed)
                if running and lead <= _RUNUP_S and c.in_s - lead * speed >= 0.0:
                    self._pmix_drive(v, c.in_s - lead * speed, 0.0, now)
                elif v.playing():
                    v.player.pause()          # перемотали назад, до клипа
                    v.player.setPosition(int(c.in_s * 1000))
                continue
            audible = not self._pmix_main_has(c, t)
            if v is None:
                # Клип, который дальше перекроют сверху, пока слышен из
                # основного плеера — голос ведём молча, чтобы к перекрытию он
                # уже шёл в такт, а не стартовал с опозданием.
                if not running or not (audible or c.id in self._pmix_need):
                    continue
                v = self._pmix_voice(c)
            if v.ready and not v.failed and running:
                self._pmix_drive(v, c.in_s + (t - c.start) * max(0.1, c.speed),
                                 float(c.volume) if audible else 0.0, now)
        # Клип начинается раньше следующего тика — стартуем голос ровно в срок.
        if nearest is not None and nearest * 1000 < _TICK_MS:
            _api.QTimer.singleShot(int(nearest * 1000) + 1, self._pmix_tick)
