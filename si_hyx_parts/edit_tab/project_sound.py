# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: звук просмотра проекта своим трактом (ProjectSoundEngine).

На время просмотра проекта звук играет не основной плеер, а ProjectSoundEngine
(edit_tab_workers): звук проекта тем же графом, что у сборки, без пауз на
стыках кусков. Основной плеер играет только картинку — без аудиовыхода его
часы идут по стене, и после перемотки на ходу картинка не отстаёт от звука.

* На паузе звук заранее готовится с плейхеда (_snd_schedule_prepare): старт
  «Пробелом» мгновенный, и звук с картинкой стартуют вместе.
* Не успел подготовиться (нажали сразу после шага) — картинка ждёт звук
  (_snd_start_with), а не убегает от него.
* Часы проекта для пустот и картинок, догонялка картинки после загрузки
  другого файла — по часам звука (project_audio в режиме тракта).
* Прогрев звука плеера (_preroll_at) в этом режиме не нужен и не делается:
  звук плеера в просмотре не звучит.
* Аудиовыход плеера снят и на паузе, пока звук проекта — трактом (_snd_stop):
  иначе каждый «Пробел» пересобирал конвейер плеера, и картинка стартовала
  на 0.2–0.5 с позже звука.
* Тракт не поднялся (нет устройства) — прежний путь: звук плеера и голоса.
  Отказ устройства на ходу не навсегда: следующий старт пробует тракт снова."""
import edit_tab as _api
from si_hyx_parts.edit_tab.tracks import route_player_audio

_PREPARE_DELAY_MS = 450   # плейхед на паузе успокоился — готовим звук (реже шагов)
_START_WAIT_MS = 1500     # дольше не держим картинку, ожидая звук


class EditTabProjectSoundMixin:
    """Монтаж: звук просмотра проекта — свой тракт вместо звука плеера."""

    def _snd_init(self):
        """Вызывается из _project_init."""
        self._snd = None                # ProjectSoundEngine (лениво)
        self._snd_active = False        # просмотр проекта идёт со звуком тракта
        self._snd_detached = False      # у плеера снят аудиовыход
        self._snd_waiting = None        # (поколение ожидания, что запустить)
        self._snd_wait_gen = 0
        self._snd_prep_timer = None
        self._snd_failed_msg = None     # отказ уже в журнале (до следующего успеха)

    # ── Тракт ────────────────────────────────────────────────────────────────
    def _snd_engine(self):
        eng = self._snd
        if eng is None:
            try:
                eng = _api.ProjectSoundEngine(self)
            except Exception:
                return None
            eng.ready.connect(self._snd_on_ready)
            eng.failed.connect(self._snd_on_failed)
            eng.set_volume(self._snd_volume())
            self._snd = eng
        return eng

    def _snd_wanted(self):
        """Звук просмотра проекта — трактом: проект есть, тракт жив, и плеер
        не в режиме «Только звук» (там у плеера нет картинки, и часы просмотра
        держит его собственный звук)."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return False
        if getattr(self, "_audio_only_mode", False):
            return False
        eng = self._snd_engine()
        return eng is not None and eng.usable()

    def _snd_volume(self):
        try:
            return max(0.0, min(1.0, self.vol_slider.value() / 100.0))
        except Exception:
            return 1.0

    def _snd_apply_volume(self):
        if self._snd is not None:
            self._snd.set_volume(self._snd_volume())

    def _snd_audio_time(self, t):
        """Время звука для старта с плейхеда t: после шага плеер стоит на
        СЕРЕДИНЕ кадра (FrameGrid.center_of) и продолжит оттуда — звук тоже."""
        fps = self._grid.fps if self._grid.valid else 0.0
        return t + (0.5 / fps if fps > 0 else 0.0)

    def _snd_play_time(self):
        """Время проекта, с которого пойдёт картинка: позиция плеера на
        паузе. После остановки воспроизведения плеер стоит там, где его
        застала пауза (дальше показанного кадра на десятки миллисекунд), и
        звук, начатый с плейхеда, отставал от картинки на ~60 мс."""
        tl = self.project_timeline
        t = tl.playhead
        c = self.project.clip(getattr(self, "_proj_cur_id", ""))
        if c is not None and not c.is_image and self._proj_ready_for(c.src):
            try:
                tp = c.start + (self.player.position() / 1000.0 - c.in_s) / max(
                    0.1, c.speed)
            except Exception:
                tp = None
            if tp is not None and abs(tp - t) < 0.25:
                return max(0.0, tp)
        return self._snd_audio_time(t)

    # ── Плеер: только картинка ───────────────────────────────────────────────
    def _snd_detach_player(self):
        if self._snd_detached:
            return
        self._snd_detached = True
        try:
            # Копия звука для плавной перемотки (timeline_seek) — тоже прочь:
            # с ней у плеера остаются аудиочасы, а с ними и отставание
            # картинки после перемотки на ходу. Перемотку на паузе (клик по
            # шкале перед «Пробелом») плеер при этом теряет —
            # route_player_audio её возвращает.
            abuf = None if getattr(self, "_abuf_out", None) is not None else False
            route_player_audio(self.player, None, abuf)
        except Exception:
            pass

    def _snd_attach_player(self):
        if not self._snd_detached:
            return
        self._snd_detached = False
        try:
            # Пункт «Нет» в списке дорожек: у плеера звука нет и без нас.
            # Через route_player_audio: выход возвращается не сразу после игры,
            # а когда звук снова нужен самому плееру — на паузе он к тому
            # времени мог уйти на другое место (шаги, клики по шкале).
            out = None if getattr(self, "audio_disabled", False) else self.audio_output
            abuf = self._abuf_out if getattr(self, "_abuf_out", None) is not None else False
            route_player_audio(self.player, out, abuf)
        except Exception:
            pass

    # ── Просмотр ─────────────────────────────────────────────────────────────
    def _snd_begin(self, t):
        """Начало просмотра проекта с времени t. True — звук ведёт тракт."""
        self._snd_cancel_wait()
        if not self._snd_wanted():
            self._snd_active = False
            self._snd_attach_player()   # звук играет сам плеер — выход ему нужен
            return False
        eng = self._snd
        ta = self._snd_play_time()
        if not eng.prepared_for(self.project, ta):
            eng.prepare(self.project, ta)
        self._snd_active = True
        self._snd_detach_player()
        return True

    def _snd_jump(self, t):
        """Прыжок во время просмотра (клик по шкале): звук — с нового места
        (ровно с t: туда же встанет плеер), картинка его подождёт."""
        if not self._snd_active or self._snd is None:
            return
        self._snd_cancel_wait()
        self._snd.prepare(self.project, t)

    def _snd_start_with(self, start_video):
        """Пустить звук и картинку вместе. Звук готов — сразу; нет — картинка
        стартует, когда он будет готов (не дольше _START_WAIT_MS)."""
        eng = self._snd
        if not self._snd_active or eng is None:
            start_video()
            return
        if not eng.is_playing():
            # Картинка пойдёт с позиции плеера; звук, подготовленный с другого
            # места (плеер успели перемотать), готовим заново — иначе они
            # разошлись бы на эту разницу до конца куска.
            ta = self._snd_play_time()
            t0 = eng.start_time()
            if t0 is None or abs(ta - t0) > 0.012:
                eng.prepare(self.project, ta)
            eng.play()                  # звук пойдёт, как только наполнит устройство
        if eng.is_ready():
            start_video()
            return
        self._snd_wait_gen += 1
        gen = self._snd_wait_gen
        self._snd_waiting = (gen, start_video)
        _api.QTimer.singleShot(_START_WAIT_MS, lambda g=gen: self._snd_release_wait(g))

    def _snd_ensure_playing(self):
        """Звук идёт и тогда, когда плеер стоит (картинка, пустота)."""
        if self._snd_active and self._snd is not None and not self._snd.is_playing():
            self._snd.play()

    def _snd_on_ready(self):
        self._snd_failed_msg = None
        if self._snd_waiting is not None:
            self._snd_release_wait(self._snd_waiting[0])

    def _snd_release_wait(self, gen):
        w = self._snd_waiting
        if w is None or w[0] != gen:
            return
        self._snd_waiting = None
        if self._snd_active and getattr(self, "_proj_play", None) is not None:
            w[1]()

    def _snd_cancel_wait(self):
        self._snd_waiting = None
        self._snd_wait_gen += 1

    def _snd_stop(self):
        """Просмотр окончен: тишина; на паузе тракт готовит звук с нового места.

        Аудиовыход плееру НЕ возвращаем, пока звук проекта играет тракт: на
        паузе звук плеера не нужен (шаг кадра звучит скраббером, прогрева в
        этом режиме нет), а снятие выхода на каждом «Пробеле» пересобирало
        конвейер плеера и перематывало его заново. Замер на живом окне: первый
        кадр после старта приходил через 0.18–0.32 с (у клипа 8× — 0.52 с), а
        без пересборки — через 0.03 с; звук тракта шёл сразу, и картинка его
        догоняла. Выход вернётся, когда звук снова нужен самому плееру
        (_snd_begin, _play_from_here, _preroll_at)."""
        self._snd_cancel_wait()
        was = self._snd_active
        self._snd_active = False
        if self._snd is not None and was:
            self._snd.stop()
        if self._snd is None or not self._snd_wanted():
            self._snd_attach_player()
        self._snd_schedule_prepare()

    def _snd_now(self):
        """Время проекта, которое сейчас слышно (часы тракта), или None."""
        if not self._snd_active or self._snd is None or not self._snd.is_playing():
            return None
        return self._snd.now()

    def _snd_on_failed(self, msg):
        """Устройство звука отказало — этот просмотр доигрывает прежним путём
        (звук плеера); следующий старт снова пробует тракт, и тот откроет
        устройство заново (например, уже подключённые наушники)."""
        if msg != self._snd_failed_msg:
            self._snd_failed_msg = msg
            try:
                self.main.log(f"Монтаж: звук просмотра проекта — {msg}; звук плеера")
            except Exception:
                pass
        if self._snd_active:
            self._snd_active = False
            self._snd_attach_player()
            w, self._snd_waiting = self._snd_waiting, None
            if w is not None:
                w[1]()

    def _snd_align_player(self):
        """Пауза: плеер — на показанный кадр (его середину). Без звука его
        часы идут по стене, а холст под нагрузкой GPU показывает кадры с
        опозданием: на паузе плеер стоял на 2–7 кадров дальше показанного, и
        «Пробел» начинал картинку оттуда — скачок вперёд, а звук, готовый с
        показанного кадра, отставал. Кадр пришпилен — картинка не дрогнет."""
        if not self._grid.valid or self._frame_idx is None or not self._snd_wanted():
            return
        try:
            target = self._grid.ms_of(self._frame_idx)
            if abs(self.player.position() - target) > 0.6 * 1000.0 / self._grid.fps:
                self.player.setPosition(target)
        except Exception:
            pass

    # ── Подготовка на паузе ──────────────────────────────────────────────────
    def _snd_schedule_prepare(self):
        """Плейхед на паузе сдвинулся — через _PREPARE_DELAY_MS тишины готовим
        звук с него (перезапуск таймера на каждом сдвиге)."""
        if self._snd_active:
            return
        t = self._snd_prep_timer
        if t is None:
            t = self._snd_prep_timer = _api.QTimer(self)
            t.setSingleShot(True)
            t.setInterval(_PREPARE_DELAY_MS)
            t.timeout.connect(self._snd_prepare_now)
        t.start()

    def _snd_prepare_now(self):
        if self._snd_active or not self._snd_wanted():
            return
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                return
        except Exception:
            return
        if not (getattr(self, "_tl_dragging", False) or getattr(self, "_scrubbing", False)):
            # Выход плеера снимаем заранее, на паузе (см. _snd_stop): тогда и
            # первый «Пробел» после загрузки файла не ждёт пересборки конвейера.
            self._snd_detach_player()
        ta = self._snd_play_time()
        if ta >= self.project.duration() - 0.05:
            return
        if not self._snd.prepared_for(self.project, ta):
            self._snd.prepare(self.project, ta)

    def _snd_shutdown(self):
        eng, self._snd = self._snd, None
        if eng is not None:
            try:
                eng.shutdown()
            except Exception:
                pass
