# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: просмотр проекта — стыки кусков без замирания картинки (деки).

Основной плеер вкладки на стыке с куском ДРУГОГО файла открывал этот файл сам,
в GUI-потоке: ffprobe, разбор прежнего декодера и (при аппаратном
декодировании) создание и уничтожение устройства D3D11. Картинка и весь
интерфейс стояли, потом чёрный кадр до первого кадра нового файла. Замер
31.10.2026 на живом окне (H.264 и HEVC 10 бит 1080p, d3d11va): кадров не было
0.55–1.04 с на каждом стыке.

Теперь следующие куски заранее открыты в «деках» (edit_tab_workers.VideoDeck:
QMediaPlayer в своём потоке, только картинка) и стоят на своём первом кадре.
На стыке холст показывает этот кадр, дека продолжает играть, а прежний
источник встаёт: ни загрузки, ни перемотки в GUI-потоке. Прототип на тех же
файлах (10 кусков по 0.5–2 с, три файла): все кадры, ни одного дольше 50 мс.

* Стык — по часам звука проекта (тракт project_sound): часы общие для всех
  кусков, и ошибка стыка не копится. Дека стоит на середине своего первого
  кадра; play() уходит так, чтобы её второй кадр пришёл ровно через кадр после
  первого (разгон деки меряется на каждом стыке, _deck_lat).
* Первый стык просмотра — из основного плеера; дальше картинку дают только
  деки: основной плеер стоит, его кадры холст не берёт (set_deck_mode).
  Остановка — плеер встаёт на кадр остановки (свой файл — перемотка, другой —
  загрузка, уже на паузе); до его кадра на холсте кадр деки, не чёрный.
* Картинка и пустота между кусками — прежним путём (таймер), видеокусок после
  них — снова декой. Дека не успела встать на кусок — картинка ждёт её до
  _WAIT_MAX_S, потом прежний путь (файл грузит основной плеер).
* На паузе деки заранее встают на куски после плейхеда (_deck_prepare): первые
  стыки просмотра не открывают файлов вовсе.
* Панель звука и субтитров на ходу — о файле куска деки (_deck_tracks_follow):
  его дорожки и озвучка рядом разобраны в потоке разбора дек, субтитры этого
  файла идут за кадрами деки. Звук и субтитры основного плеера не трогаются;
  выход из дек возвращает панель о его файле (_deck_tracks_restore).
* Звук не трактом (устройство отказало) или холст без сцены Qt Quick — прежний
  путь целиком: картинку деки некому озвучить или негде показать. Куски,
  которых живой плеер не играет как есть (реверс, стоп-кадр, кривая скорости),
  и AV1 (основной плеер играет его через прокси: аппаратного декодера AV1 у
  многих GPU нет) — тоже прежним путём."""
import threading

import edit_tab as _api
import montage_project as _mp

_DECKS = 3               # плееров-дек: одна играет, остальные стоят на следующих кусках
_FREE_DELAY_S = 0.3      # отыгравшая дека свободна через столько (сцена сменила её кадр)
_HORIZON_S = 30.0        # куски дальше этого (от конца текущего) заранее не открываем
_WAIT_MAX_S = 2.0        # дольше не ждём деку, не успевшую встать на кусок
_LATENCY0_S = 0.012      # разгон деки от play() до хода её часов (уточняется замером)
_LATENCY_MAX_S = 0.06
_LOOK_EVERY_S = 0.25     # как часто на ходу проверять заказы дек
_IDLE_UNLOAD_MS = 120000  # просмотра так долго не было — файлы дек закрываем
_SUB_EVERY_S = 0.06      # субтитры за кадрами деки — не чаще (как таймер ASS)


class EditTabProjectDecksMixin:
    """Монтаж: картинка просмотра проекта из дек на стыках кусков."""

    # ── Состояние ────────────────────────────────────────────────────────────
    def _deck_init(self):
        """Вызывается из _project_init."""
        self._decks = []               # VideoDeck (лениво)
        self._deck_on = False          # картинку просмотра дают деки
        self._deck_cur = None          # дека текущего куска (None — картинка, пустота)
        self._deck_seg = None          # её заказ (границы кадров, скорость)
        self._deck_shown = -1          # pts последнего показанного кадра деки
        self._deck_shown_at = 0.0      # когда он вышел на холст
        self._deck_lat = _LATENCY0_S
        self._deck_sent = None         # (дека, когда ушёл play, с какого места, скорость)
        self._deck_wait = None         # (кусок, с какого момента ждём его деку)
        self._deck_timer = None        # стык по часам звука
        self._deck_play_timer = None   # play() деки чуть позже стыка
        self._deck_play_pending = None
        self._deck_look_at = 0.0
        self._deck_look_armed = False
        self._deck_idle_timer = None
        self._deck_codecs = {}         # файл → кодек видео (разбор ffprobe в фоне)
        self._deck_probing = set()
        self._deck_tinfo = {}          # файл → его дорожки и файлы рядом (_deck_tracks_scan)
        self._deck_tv = None           # панель о файле куска на деке: {'src', 'saved', 'main'}
        self._deck_sub_at = 0.0        # когда субтитры последний раз шли за кадром деки

    def _deck_canvas_ok(self):
        vw = getattr(self, "video_widget", None)
        return isinstance(vw, _api.VideoCanvas) and vw.deck_capable()

    def _deck_usable(self):
        """Картинку просмотра можно отдать декам: звук играет тракт (картинку
        деки озвучивает он) и у холста есть сцена Qt Quick."""
        return (getattr(self, "_snd_active", False) and self._deck_canvas_ok()
                and not getattr(self, "_fx_mode", False)
                and not getattr(self, "_audio_only_mode", False))

    def _deck_pool(self):
        if not self._decks:
            for i in range(_DECKS):
                d = _api.VideoDeck(f"MontageDeck{i + 1}", self)
                d.ready.connect(self._deck_on_ready)
                d.frame.connect(self._deck_on_frame)
                d.failed.connect(self._deck_on_failed)
                self._decks.append(d)
        return self._decks

    # ── Заказы ───────────────────────────────────────────────────────────────
    def _deck_target(self, seg):
        """Заказ деке для куска плана (dict) или None: картинка, пустота, клип
        без частоты кадров."""
        clip = seg.get('clip')
        if (clip is None or clip.is_image or not clip.fps or 's0' not in seg
                or seg['s1'] <= seg['s0'] or clip.reverse or clip.frozen or clip.speed_curve):
            return None
        if self._deck_video_codec(clip.src) in (None, 'av1'):
            return None
        fps = float(clip.fps)
        first, last = self._proj_seg_frames(seg, fps)
        rate = max(_mp.MIN_SPEED, float(clip.speed))
        center = (first + 0.5) / fps
        return {
            'key': (self._proj_norm(clip.src), first, last, round(rate, 4)),
            'path': clip.src,
            # Середина первого кадра: округление до миллисекунд не перекинет
            # плеер на соседний (см. FrameGrid.center_of).
            'pos_ms': int(round(center * 1000.0)),
            # Плеер на паузе показывает кадр, накрывающий позицию, — он и есть
            # заказанный. Окно с запасом назад: у файла с плавающей частотой
            # (vfr) кадр начинается не на сетке среднего fps.
            'window': (int((center - 0.25) * 1_000_000), int(center * 1_000_000) + 1),
            'floor_us': int((first - 0.5) / fps * 1_000_000),
            # Кадр, начинающийся на s1, уже вырезан (_proj_seg_frames).
            'bound_us': int((last + 0.5) / fps * 1_000_000),
            'fps': fps,
            'rate': rate,
        }

    def _deck_video_codec(self, path):
        """Кодек видео файла или None, пока неизвестен: разбор ffprobe (кеш
        run_ffprobe) — в фоне, в GUI-потоке он стоил бы 80–110 мс на файл."""
        norm = self._proj_norm(path)
        codec = self._deck_codecs.get(norm)
        if codec is not None or norm in self._deck_probing:
            return codec
        self._deck_probing.add(norm)

        def probe(p=path, n=norm, codecs=self._deck_codecs, infos=self._deck_tinfo):
            meta = _api.run_ffprobe(p) or {}
            v = next((s for s in meta.get('streams', []) if s.get('codec_type') == 'video'), {})
            codecs[n] = str(v.get('codec_name') or '').lower()
            # Дорожки и файлы рядом — для панели, когда кусок заиграет дека.
            try:
                infos[n] = self._deck_tracks_scan(p, meta)
            except Exception:
                pass
        threading.Thread(target=probe, daemon=True, name="deck-probe").start()
        return None

    def _deck_wanted(self, plan, idx, n):
        """Видеокуски после idx, которым нужны деки: не больше n и не дальше
        _HORIZON_S после конца куска idx."""
        out = []
        if plan is None or not 0 <= idx < len(plan):
            return out
        limit = plan[idx]['t1'] + _HORIZON_S
        for j in range(idx + 1, len(plan)):
            if len(out) >= n or plan[j]['t0'] > limit:
                break
            tgt = self._deck_target(plan[j])
            if tgt is not None:
                out.append(tgt)
        return out

    def _deck_assign(self, wanted):
        """Раздать заказы декам — ближний кусок первым. Дека с тем же файлом
        встаёт перемоткой, без разбора декодера."""
        decks = self._deck_pool()
        keys = {t['key'] for t in wanted}
        now = _api.time.monotonic()
        for tgt in wanted:
            if any(d.key == tgt['key'] and d is not self._deck_cur for d in decks):
                continue
            free = [d for d in decks if d is not self._deck_cur
                    and (d.key is None or d.key not in keys)]
            ready = [d for d in free if d.free_at <= now]
            if not ready:
                if free:
                    # Отыгравшая дека освободится чуть позже — заказ тогда.
                    self._deck_look_later(min(d.free_at for d in free) - now)
                return
            norm = tgt['key'][0]
            same = [d for d in ready if d.path and self._proj_norm(d.path) == norm]
            d = same[0] if same else min(ready, key=lambda x: (x.key is not None, x.used_at))
            d.load(tgt['key'], tgt['path'], tgt['pos_ms'], tgt['window'], tgt['rate'])

    def _deck_lookahead(self):
        """На ходу: деки — на следующие видеокуски плана."""
        self._deck_look_armed = False
        self._deck_look_at = _api.time.monotonic()
        plan = self._proj_play
        if plan is None or not self._deck_usable():
            return
        n = _DECKS - (1 if self._deck_cur is not None else 0)
        self._deck_assign(self._deck_wanted(plan, self._proj_idx, n))

    def _deck_look_later(self, delay_s):
        if self._deck_look_armed:
            return
        self._deck_look_armed = True
        _api.QTimer.singleShot(max(0, int(delay_s * 1000)) + 10, self._deck_lookahead)

    def _deck_ready_for(self, plan, j):
        """Дека, уже стоящая на первом кадре куска j, или None."""
        if plan is None or not 0 <= j < len(plan):
            return None
        tgt = self._deck_target(plan[j])
        if tgt is None:
            return None
        for d in self._decks:
            if d.key == tgt['key'] and d.is_ready and d is not self._deck_cur:
                return d
        return None

    def _deck_loading_for(self, plan, j):
        """Дека, которой кусок j заказан, но она ещё не встала на него."""
        tgt = self._deck_target(plan[j]) if plan is not None and 0 <= j < len(plan) else None
        if tgt is None:
            return None
        return next((d for d in self._decks if d.key == tgt['key'] and not d.is_ready
                     and d is not self._deck_cur), None)

    # ── Пауза: деки заранее ──────────────────────────────────────────────────
    def _deck_prepare(self, t):
        """Пауза (project_sound._snd_prepare_now): деки встают на куски после
        плейхеда t — первые стыки просмотра не откроют ни одного файла, а
        рывок открытия случится сейчас, когда всё стоит."""
        if self._proj_play is not None or not self._deck_canvas_ok():
            return
        if getattr(self, "_fx_mode", False) or getattr(self, "_audio_only_mode", False):
            return
        plan = self._project_plan()
        idx = next((i for i, s in enumerate(plan) if s['t0'] <= t < s['t1']), None)
        if idx is None:
            return
        wanted = self._deck_wanted(plan, idx, _DECKS)
        if wanted or self._decks:
            self._deck_assign(wanted)
            self._deck_schedule_idle()

    def _deck_schedule_idle(self):
        t = self._deck_idle_timer
        if t is None:
            t = self._deck_idle_timer = _api.QTimer(self)
            t.setSingleShot(True)
            t.setInterval(_IDLE_UNLOAD_MS)
            t.timeout.connect(self._deck_idle_unload)
        t.start()

    def _deck_idle_unload(self):
        """Давно не смотрели проект — деки закрывают файлы (и декодеры)."""
        if self._proj_play is not None:
            self._deck_schedule_idle()
            return
        for d in self._decks:
            d.unload()

    # ── Ход просмотра ────────────────────────────────────────────────────────
    def _deck_tick(self):
        """Основной плеер играет кусок (_proj_tick): деки — на следующие куски,
        стык — по часам звука."""
        if _api.time.monotonic() - self._deck_look_at > _LOOK_EVERY_S:
            self._deck_lookahead()
        self._deck_arm()

    def _deck_arm(self):
        """Таймер на конец текущего куска по часам звука проекта. Пока играет
        основной плеер — только если следующий кусок ждёт готовая дека."""
        plan = self._proj_play
        if plan is None or not 0 <= self._proj_idx < len(plan) or not self._deck_usable():
            self._deck_timer_stop()
            return
        if not self._deck_on and self._deck_ready_for(plan, self._proj_idx + 1) is None:
            self._deck_timer_stop()
            return
        rem = self._deck_rem()
        if rem is not None:
            self._deck_timer_start(rem)

    def _deck_rem(self):
        """Сколько секунд до конца текущего куска (None — неизвестно): по
        часам звука, но на деке — не позже двух кадров после конца куска по
        её картинке. В самом конце проекта часы тракта встают чуть раньше его
        длины, и стык (а с ним и конец просмотра) иначе не наступал."""
        seg = self._proj_play[self._proj_idx]
        now_t = self._pmix_now()
        rem = seg['t1'] - now_t if now_t is not None else None
        tgt = self._deck_seg
        if self._deck_on and tgt is not None and self._deck_shown >= 0:
            frame_s = 1.0 / (tgt['fps'] * tgt['rate'])
            video_t = (seg['t0'] + (self._deck_shown / 1_000_000.0 - seg['s0']) / tgt['rate']
                       + (_api.time.monotonic() - self._deck_shown_at))
            rem_v = seg['t1'] - video_t + 2.0 * frame_s
            rem = rem_v if rem is None else min(rem, rem_v)
        return rem

    def _deck_timer_start(self, rem_s):
        t = self._deck_timer
        if t is None:
            t = self._deck_timer = _api.QTimer(self)
            t.setSingleShot(True)
            t.setTimerType(_api.Qt.TimerType.PreciseTimer)
            t.timeout.connect(self._deck_on_timer)
        t.start(max(0, int(rem_s * 1000)))

    def _deck_timer_stop(self):
        if self._deck_timer is not None:
            self._deck_timer.stop()

    def _deck_on_timer(self):
        plan = self._proj_play
        if plan is None or not 0 <= self._proj_idx < len(plan):
            return
        rem = self._deck_rem()
        if rem is not None and rem > 0.003:
            self._deck_timer_start(rem)         # часы ещё не дошли
            return
        self._deck_seam()

    def _deck_seam(self):
        """Конец текущего куска (часы звука или граница основного плеера).
        True — переход сделан здесь; False — делает основной плеер, как
        прежде (деки не готовы, просмотр не на деках)."""
        plan = self._proj_play
        if plan is None:
            return False
        nxt = self._proj_idx + 1
        if self._proj_replan_live(nxt, 0.0):
            return True                 # проект правят на ходу — план заново
        deck = self._deck_ready_for(plan, nxt)
        if deck is not None and self._deck_usable():
            self._deck_switch(nxt, deck)
            return True
        if not self._deck_on:
            return False
        if nxt < len(plan) and self._deck_target(plan[nxt]) is not None and self._deck_usable():
            self._deck_wait_for(nxt)
            return True
        # Картинка, пустота или конец просмотра — прежним путём, без плеера.
        self._deck_drop_current()
        self._proj_play_segment(nxt, 0.0, cont=True)
        return True

    def _deck_play_segment(self, idx, offset, cont):
        """Начало _proj_play_segment: True — кусок взяла дека. Картинку и
        пустоту играет прежний код (режим дек при этом не прерывается),
        видеокусок без готовой деки или прыжок — основной плеер."""
        plan = self._proj_play
        if plan is None or not 0 <= idx < len(plan):
            return False
        clip = plan[idx]['clip']
        if clip is None or clip.is_image:
            return False
        if cont and offset < 1e-3 and self._deck_usable():
            deck = self._deck_ready_for(plan, idx)
            if deck is not None:
                self._deck_switch(idx, deck)
                return True
            if self._deck_on and self._deck_loading_for(plan, idx) is not None:
                self._deck_wait_for(idx)
                return True
        self._deck_leave()
        return False

    def _deck_wait_for(self, idx):
        """Дека куска idx ещё грузится: картинка стоит на последнем кадре, пока
        она не встанет (не дольше _WAIT_MAX_S). Опоздание выправит следующий
        стык — он по часам звука."""
        if self._deck_wait is not None and self._deck_wait[0] == idx:
            return
        self._deck_wait = (idx, _api.time.monotonic())
        cur = self._deck_cur
        if cur is not None:
            cur.pause()
        self._deck_timer_stop()
        self._deck_lookahead()
        _api.QTimer.singleShot(int(_WAIT_MAX_S * 1000), lambda i=idx: self._deck_wait_expired(i))

    def _deck_wait_expired(self, idx):
        w = self._deck_wait
        if w is None or w[0] != idx or self._proj_play is None or not self._deck_on:
            return
        self._deck_wait = None
        self._deck_leave()
        self._proj_play_segment(idx, 0.0, cont=True)    # файл грузит основной плеер

    def _deck_on_ready(self, deck):
        w = self._deck_wait
        plan = self._proj_play
        if w is not None and plan is not None and self._deck_ready_for(plan, w[0]) is deck:
            self._deck_wait = None
            self._deck_switch(w[0], deck)
            return
        if plan is not None:
            self._deck_arm()

    def _deck_on_failed(self, deck):
        """Файл деке не открылся — кусок сыграет основной плеер (он и скажет,
        что не так)."""
        deck.release()
        w = self._deck_wait
        if w is not None and self._proj_play is not None and self._deck_on:
            self._deck_wait_expired(w[0])

    # ── Стык ─────────────────────────────────────────────────────────────────
    def _deck_switch(self, idx, deck):
        """Кусок idx дальше играет дека: её кадр места — на холст, play() — так,
        чтобы следующий кадр пришёл через кадр."""
        plan = self._proj_play
        seg = plan[idx]
        tgt = self._deck_target(seg)
        vw = self.video_widget
        self._deck_timer_stop()
        self._deck_wait = None
        if not self._deck_on:
            self._deck_enter()
        old = self._deck_cur
        if old is not None and old is not deck:
            old.release(_FREE_DELAY_S)
        self._deck_cur = deck
        self._deck_seg = tgt
        self._proj_idx = idx
        self._proj_limit_s = None
        self._pmix_hold = None
        self._proj_cur_id = self._proj_clip_at_source(seg, seg['s0']).id
        vw.set_deck_source(deck.sink, tgt['floor_us'], tgt['bound_us'])
        frame, deck.ready_frame = deck.ready_frame, None
        self._deck_shown = -1
        if frame is not None:
            self._deck_show(frame)
        self.project_timeline.set_playhead(seg['t0'])
        self._paint_project_time(seg['t0'])
        # Часы деки пойдут с середины первого кадра: второй кадр — через
        # полкадра после play(), а нужен через кадр после этого стыка.
        self._deck_start_later(deck, 0.5 / (tgt['fps'] * tgt['rate']) - self._deck_lat)
        self._deck_look_later(_FREE_DELAY_S)
        self._deck_lookahead()
        self._deck_arm()
        self._deck_tracks_follow(seg['clip'].src)
        self._deck_subtitle(force=True)

    def _deck_start_later(self, deck, delay_s):
        self._deck_play_pending = deck
        if delay_s <= 0.001:
            self._deck_start_now()
            return
        t = self._deck_play_timer
        if t is None:
            t = self._deck_play_timer = _api.QTimer(self)
            t.setSingleShot(True)
            t.setTimerType(_api.Qt.TimerType.PreciseTimer)
            t.timeout.connect(self._deck_start_now)
        t.start(int(round(delay_s * 1000)))

    def _deck_start_now(self):
        deck, self._deck_play_pending = self._deck_play_pending, None
        if deck is None or deck is not self._deck_cur or self._proj_play is None:
            return
        if deck.play():
            tgt = self._deck_seg
            self._deck_sent = (deck, _api.time.monotonic(), tgt['pos_ms'] / 1000.0, tgt['rate'])

    def _deck_show(self, frame):
        try:
            self._deck_shown = int(frame.startTime())
        except Exception:
            self._deck_shown = -1
        self._deck_shown_at = _api.time.monotonic()
        self.video_widget.present_deck_frame(frame)

    def _deck_on_frame(self, deck, frame):
        if deck is not self._deck_cur or not self._deck_on:
            return
        tgt = self._deck_seg
        try:
            pts = int(frame.startTime())
        except Exception:
            return
        if pts < tgt['floor_us'] or pts == self._deck_shown:
            return
        sent = self._deck_sent
        if sent is not None and sent[0] is deck and pts >= tgt['window'][1]:
            # Разгон: кадр пришёл позже, чем шли бы часы деки с момента play().
            due = sent[1] + (pts / 1_000_000.0 - sent[2]) / sent[3]
            lat = _api.time.monotonic() - due
            self._deck_lat = max(0.0, min(_LATENCY_MAX_S, 0.5 * self._deck_lat + 0.5 * lat))
            self._deck_sent = None
        if pts >= tgt['bound_us']:
            return                      # за концом куска — стык сделают часы звука
        self._deck_show(frame)
        seg = self._proj_play[self._proj_idx]
        t = seg['t0'] + (pts / 1_000_000.0 - seg['s0']) / tgt['rate']
        t = min(seg['t1'], max(seg['t0'], t))
        self.project_timeline.set_playhead(t)
        self._paint_project_time(t)
        self._deck_subtitle()
        self._deck_arm()
        if _api.time.monotonic() - self._deck_look_at > _LOOK_EVERY_S:
            self._deck_lookahead()

    # ── Вход и выход ─────────────────────────────────────────────────────────
    def _deck_enter(self):
        """Первый стык на деках: основной плеер встаёт, его кадры холст не берёт."""
        self._deck_on = True
        self._proj_transition = True    # пауза плеера — не остановка просмотра
        self._bridge_stop()
        self._proj_seam = None
        self._set_play_bound(False)
        self.video_widget.set_deck_mode(True)
        try:
            self.sync_timer.stop()      # интерфейс ведут кадры дек
        except Exception:
            pass
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        # Субтитры дальше идут за кадрами дек — файла её куска (_deck_switch).

    def _deck_drop_current(self):
        cur, self._deck_cur = self._deck_cur, None
        self._deck_seg = None
        self._deck_sent = None
        self._deck_play_pending = None
        if self._deck_play_timer is not None:
            self._deck_play_timer.stop()
        self._deck_timer_stop()
        if cur is not None:
            cur.release(_FREE_DELAY_S)
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.set_deck_source(None)

    def _deck_leave(self):
        """Картинку снова даёт основной плеер (прыжок, остановка, дека не встала)."""
        if not self._deck_on:
            return
        self._deck_on = False
        self._deck_wait = None
        self._deck_drop_current()
        self.video_widget.set_deck_mode(False)
        # Панель — о файле плеера, но после того, как он откроет (или нет)
        # файл места: открытие само перестроит панель.
        _api.QTimer.singleShot(0, self._deck_tracks_settle)

    def _deck_stop_begin(self):
        """Начало project_stop: время, на котором стоял просмотр на деках, или
        None (просмотр был не на деках)."""
        if not self._deck_on:
            return None
        t = self.project_timeline.playhead
        self._deck_leave()
        return t

    def _deck_stop_end(self, t):
        """Конец project_stop после дек: основной плеер и так стоит (сигнала
        паузы не будет) — интерфейс на паузу здесь, и плеер — на кадр
        остановки. До его кадра холст держит кадр деки."""
        self._sync_play_icon()
        self.video_widget.set_playing(False)
        self._project_seek(t)
        self._deck_tracks_settle()      # файл места открыт (или свой) — панель о нём
        self._deck_schedule_idle()

    def _deck_shutdown(self):
        decks, self._decks = self._decks, []
        for d in decks:
            try:
                d.shutdown()
            except Exception:
                pass

    # ── Панель звука и субтитров — о файле куска на деке ─────────────────────
    def _deck_tracks_scan(self, src, meta):
        """Дорожки файла и озвучка/субтитры рядом с ним. Зовётся из потока
        разбора дек: на стыке панель берёт готовое, без ffprobe и обхода папок
        в GUI-потоке."""
        streams = meta.get('streams', [])
        audio_ext, audio_hidden = self._external_audio_files(src)
        sub_ext, sub_hidden = self._external_sub_files(src)
        for p in audio_ext[:4]:
            _api.run_ffprobe(p)         # кодек и битрейт озвучки потом — из кеша
        return {
            'audio': [s for s in streams if s.get('codec_type') == 'audio'],
            'subs': [s for s in streams if s.get('codec_type') == 'subtitle'],
            'audio_ext': audio_ext, 'audio_hidden': audio_hidden,
            'sub_ext': sub_ext, 'sub_hidden': sub_hidden,
        }

    def _deck_tracks_state(self):
        """Панель о файле основного плеера — вернуть её, когда дека отыграет."""
        return {
            'audio': self._audio_streams, 'subs': self._sub_streams,
            'audio_ext': list(self._audio_ext),
            'audio_hidden': list(getattr(self, "_audio_ext_hidden", None) or []),
            'sub_ext': list(self._sub_ext),
            'sub_hidden': list(getattr(self, "_sub_ext_hidden", None) or []),
            'audio_sel': getattr(self, "_audio_sel_entry", None),
            'sub_sel': getattr(self, "_sub_sel_entry", None),
            'sub_ext_path': self.selected_sub_ext_path,
            'labels': (self.lbl_astream.text(), self.lbl_abitrate.text()),
        }

    def _deck_tracks_apply(self, st):
        self._audio_streams, self._sub_streams = st['audio'], st['subs']
        self._audio_ext, self._audio_ext_hidden = list(st['audio_ext']), list(st['audio_hidden'])
        self._sub_ext, self._sub_ext_hidden = list(st['sub_ext']), list(st['sub_hidden'])

    def _deck_tracks_follow(self, src):
        """Кусок заиграла дека: панель звука и субтитров — о его файле, и
        субтитры — его (по кадрам деки, _deck_subtitle). Основной плеер стоит
        на прошлом куске, и панель с субтитрами оставались от того файла до
        самой остановки просмотра. Звук и субтитры основного плеера не трогаем:
        панель про него вернёт _deck_tracks_restore."""
        cur = self.actual_source_file
        if not src or (cur is not None and self._proj_norm(src) == self._proj_norm(cur)):
            self._deck_tracks_restore()
            return
        norm = self._proj_norm(src)
        tv = self._deck_tv
        if tv is not None and self._proj_norm(tv['src']) == norm:
            return
        info = self._deck_tinfo.get(norm)
        if info is None:
            info = self._deck_tinfo[norm] = self._deck_tracks_scan(src, _api.run_ffprobe(src) or {})
        if tv is not None:
            saved, main = tv['saved'], tv['main']
        else:
            saved, main = self._deck_tracks_state(), (self._proj_norm(cur) if cur else "")
        self._deck_tv = {'src': src, 'saved': saved, 'main': main}
        self._deck_tracks_apply(info)
        rec = self._session_files.get(self._session_file_key()) or {}
        self._deck_tracks_fill(self._deck_tracks_audio_sel(src),
                               self._deck_tracks_sub_sel(rec.get('subs')))
        self._deck_tracks_labels()

    def _deck_tracks_restore(self):
        """Панель — снова о файле основного плеера (кусок его файла, выход из
        дек без загрузки другого файла)."""
        tv, self._deck_tv = self._deck_tv, None
        if tv is None:
            return
        cur = self.actual_source_file
        if cur is None or self._proj_norm(cur) != tv['main']:
            return      # плеер уже открывает другой файл — списки даст его загрузка
        st = tv['saved']
        self._deck_tracks_apply(st)
        self._deck_tracks_fill(st['audio_sel'], st['sub_sel'])
        self.selected_sub_ext_path = st['sub_ext_path']
        self.lbl_astream.setText(st['labels'][0])
        self.lbl_abitrate.setText(st['labels'][1])

    def _deck_tracks_settle(self):
        """После выхода из дек: если основной плеер не открыл другой файл
        (тот сам перестроит панель), панель — о его файле."""
        if not self._deck_on:
            self._deck_tracks_restore()

    def _deck_tracks_fill(self, audio_sel, sub_sel):
        """Списки звука и субтитров — из текущих дорожек, без смены звука
        плеера; выбранные субтитры показываются заново."""
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        self._loading_tracks = True
        try:
            self._fill_audio_combo()
            if audio_sel not in self._audio_entries:
                audio_sel = self._audio_entries[0] if self._audio_entries else None
            self._audio_sel_entry = audio_sel
            if audio_sel is not None:
                self.cmb_audio.setCurrentIndex(self._audio_entries.index(audio_sel))
        finally:
            self._loading_tracks = False
        self._sub_sel_entry = None
        self._populate_track_combos_subs_only()          # → «Выкл»
        if sub_sel is not None and sub_sel in self._sub_entries:
            self._session_restoring = True              # не выбор пользователя
            try:
                self.cmb_subs.setCurrentIndex(self._sub_entries.index(sub_sel) + 1)
            finally:
                self._session_restoring = False

    def _deck_tracks_audio_sel(self, src):
        """Пункт звука файла куска на деке — тот, которым звучат его куски
        в проекте (как _project_restore_audio при открытии файла)."""
        norm = self._proj_norm(src)
        clip = next((c for c in sorted(self.project.clips, key=lambda c: c.start)
                     if c.has_video and not c.is_image and not c.audio_detached
                     and self._proj_norm(c.src) == norm), None)
        if clip is None:
            return None
        if not clip.audio_path:
            return ('none', None)
        if self._proj_norm(clip.audio_path) != norm:
            want = self._proj_norm(clip.audio_path)
            p = next((p for p in self._audio_ext if self._proj_norm(p) == want), None)
            if p is None and _api.os.path.exists(clip.audio_path):
                p = clip.audio_path
                self._audio_ext.append(p)
                self._audio_ext_hidden = [h for h in self._audio_ext_hidden
                                          if self._proj_norm(h) != want]
            return ('ext', p) if p is not None else None
        for i, s in enumerate(self._audio_streams):
            if clip.audio_stream < 0 or s.get('index') == clip.audio_stream:
                return ('emb', i)
        return None

    def _deck_tracks_sub_sel(self, spec):
        """Пункт субтитров по записи выбора файла (session_state) или None."""
        if not isinstance(spec, list) or len(spec) < 2:
            return None
        if spec[0] == 'emb':
            return next((('emb', i) for i, s in enumerate(self._sub_streams)
                         if s.get('index') == spec[1]), None)
        if spec[0] != 'ext':
            return None
        p = next((p for p in self._sub_ext if self._session_same_path(p, spec[1])), None)
        if p is None and _api.os.path.exists(spec[1]):
            p = spec[1]
            self._sub_ext.append(p)
            self._sub_ext_hidden = [h for h in self._sub_ext_hidden
                                    if not self._session_same_path(h, p)]
        return ('ext', p) if p is not None else None

    def _deck_tracks_labels(self):
        """Кодек/каналы и битрейт выбранного звука файла куска на деке."""
        sel = self._audio_sel_entry
        info = None
        if sel is not None and sel[0] == 'emb':
            info = self._audio_streams[sel[1]]
        elif sel is not None and sel[0] == 'ext':
            meta = _api.run_ffprobe(sel[1]) or {}
            info = next((s for s in meta.get('streams', [])
                         if s.get('codec_type') == 'audio'), None)
        self._update_audio_info_labels(info)

    def _deck_tracks_audio_changed(self, kind, ref):
        """Звук выбран в панели, пока она о файле куска на деке: им звучат
        куски этого файла в проекте (звук основного плеера не трогаем)."""
        src = self._deck_tv['src']
        if kind == 'none':
            sound = ("", -1)
        elif kind == 'emb':
            sound = (str(src), int(self._audio_streams[ref].get('index', -1)))
        else:
            sound = (str(ref), -1)
        self._deck_tracks_labels()
        self._project_retarget_audio(src, sound)

    def _deck_subtitle(self, force=False):
        """Субтитры — за кадром деки: основной плеер стоит, и sync_ui их
        больше не ведёт. Не чаще _SUB_EVERY_S, как таймер ASS."""
        if self._deck_shown < 0 or not (getattr(self, "_sub_use_ass", False)
                                        or getattr(self, "_sub_use_overlay", False)):
            return
        now = _api.time.monotonic()
        if not force and now - self._deck_sub_at < _SUB_EVERY_S:
            return
        self._deck_sub_at = now
        try:
            self._update_subtitle(self._deck_shown / 1_000_000.0)
        except Exception:
            pass
