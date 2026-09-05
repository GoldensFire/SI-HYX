# -*- coding: utf-8 -*-
"""Монтаж: прогрев конвейера есть, но снаружи его НЕ ВИДНО.

Две требования, которые легко удовлетворить по отдельности и очень легко
сломать вместе:

1. **Нет задержки звука.** QtMultimedia поднимает аудио-конвейер только на
   `play()`: после перемотки первый аудиобуфер приходит через 0.33–0.47 с,
   сколько ни жди на паузе. Лечится прогревом «с разбега» (`_preroll_at`):
   встаём на 500 мс РАНЬШЕ отметки, играем под mute и тормозим на отметке.
2. **Нет разгона.** Ровно этот разбег и уезжал раньше на шкалу: бегунок
   «догонял» отметку, а шаг стрелкой на ОДИН кадр сначала сдвигал плейхед, а
   через 160 мс тащил его назад к точке разбега — резать было невозможно.
   Лечится заморозкой часов интерфейса (`_ui_pinned_ms`): пока плеер занят
   собой, метка/бегунок/волна стоят на ЗАКАЗАННОЙ точке.

Здесь проверяется и то, и другое разом.
"""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab
FrameGrid = edit_tab.FrameGrid


class _Player:
    """Плеер, который запоминает ВСЁ, что ему сделали."""

    def __init__(self, pos=0, playing=False):
        self.pos = int(pos)
        self.seeks = []
        self.played = 0
        self.paused = 0
        self.playing = playing

    def position(self): return self.pos
    def play(self): self.played += 1; self.playing = True
    def pause(self): self.paused += 1; self.playing = False
    def setPosition(self, ms): self.seeks.append(int(ms)); self.pos = int(ms)

    def playbackState(self):
        S = edit_tab.QMediaPlayer.PlaybackState
        return S.PlayingState if self.playing else S.PausedState


def _stub(pos=10_000, playing=False, fps=25.0, duration=100.0):
    timer = SimpleNamespace(started=0, stopped=0)
    timer.start = lambda: setattr(timer, 'started', timer.started + 1)
    timer.stop = lambda: setattr(timer, 'stopped', timer.stopped + 1)
    out = SimpleNamespace(muted=False)
    out.setMuted = lambda v: setattr(out, 'muted', bool(v))
    out.isMuted = lambda: bool(out.muted)
    st = SimpleNamespace(
        player=_Player(pos, playing),
        audio_output=out,
        fps=fps,
        duration=duration,
        filepath="clip.mp4",
        _grid=FrameGrid(fps, duration),
        _frame_idx=None,
        _scrubbing=False,
        _scrub_target=None,
        _scrub_audio_ms=None,
        _frame_seek_busy=False,
        _frame_seek_pending=None,
        _frame_seek_target_ms=None,
        _frame_seek_gen=0,
        _prerolling=False,
        _preroll_handoff=False,
        _preroll_target_ms=None,
        _preroll_gen=1,
        _preroll_prev_muted=False,
        video_widget=None,
        pinned=[],
        released=0,
        _timer=timer,
    )
    st._show_exact_frame = lambda idx=None, direction=1: st.pinned.append(idx)
    st._dispatch_frame_seek = lambda ms: EditTab._dispatch_frame_seek(st, ms)
    st._ext_audio_seek = lambda ms: None
    st._release_frame_lock = lambda: setattr(st, 'released', st.released + 1)
    st._current_frame_index = lambda: EditTab._current_frame_index(st)
    st.step_frame = lambda step: EditTab.step_frame(st, step)
    st._end_scrub = lambda: None
    st._ui_pinned_ms = lambda: EditTab._ui_pinned_ms(st)
    st._preroll_timer = lambda: timer
    st._preroll_at = lambda t_s: EditTab._preroll_at(st, t_s)
    st._preroll_cancel = lambda: EditTab._preroll_cancel(st)
    st._preroll_finish = lambda *a, **k: EditTab._preroll_finish(st, *a, **k)
    st._preroll_handoff_finish = lambda: EditTab._preroll_handoff_finish(st)
    st.waveform = SimpleNamespace(set_playhead=lambda *a: None)
    st.lbl_current_time = SimpleNamespace(setText=lambda *a: None)
    st.on_playback_changed = lambda *a: None
    for name in ("_PREROLL_SNAP_MS", "_PREROLL_GUARD_MS", "_PREROLL_HANDOFF_MS",
                 "_PREROLL_POLL_MS", "_PREROLL_LEAD_MS", "_PREROLL_MIN_LEAD_MS",
                 "_SCRUB_BLIP_MIN_S", "_SCRUB_BLIP_MAX_S"):
        setattr(st, name, getattr(EditTab, name))
    return st


@pytest.fixture(autouse=True)
def no_singleshot(monkeypatch):
    """Ни один тест здесь не имеет права оставить после себя ЖИВОЙ Qt-таймер.

    Прогон всего набора падал «Windows fatal exception» именно из-за этого:
    _dispatch_frame_seek ставит запасной singleShot на 2.5 с, тесты идут без
    своего QApplication, и таймер выстреливал уже посреди ЧУЖОГО теста, дёргая
    лямбды несуществующего стаба."""
    monkeypatch.setattr(edit_tab.QTimer, "singleShot", staticmethod(lambda *a: None))


# ── 1. Прогрев делает своё дело ─────────────────────────────────────────────
def test_preroll_starts_with_lead_and_plays_muted():
    """Встаём на _PREROLL_LEAD_MS раньше цели и играем под mute — это и есть то,
    что поднимает аудио-конвейер к моменту «Воспроизвести»."""
    st = _stub(pos=10_000)
    EditTab._preroll_at(st, 60.0)
    assert st.player.seeks == [60_000 - EditTab._PREROLL_LEAD_MS]
    assert st.player.played == 1
    assert st.audio_output.muted is True
    assert st._preroll_target_ms == 60_000


def test_preroll_for_same_point_is_not_restarted():
    st = _stub()
    st._prerolling = True
    st._preroll_target_ms = 60_000
    EditTab._preroll_at(st, 60.0)
    assert st.player.seeks == []          # уже греем эту точку — не мешаем


def test_preroll_restarts_on_new_target():
    """Перемотали посреди разбега: старый разбег обязан быть отменён, иначе,
    дождавшись СВОЕЙ цели, он утащил бы позицию назад к прежней отметке."""
    st = _stub()
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_at(st, 60.0)
    assert st._preroll_target_ms == 60_000
    assert st.player.seeks == [60_000 - EditTab._PREROLL_LEAD_MS]


def test_small_overshoot_is_kept_warm():
    """Промах в несколько десятков миллисекунд НЕ правим: перемотка стоит
    ~0.35 с тишины, а промах — те же миллисекунды со старта отрезка."""
    st = _stub(pos=150_040, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_finish(st)
    assert st.player.seeks == []
    assert st._prerolling is False
    assert st.audio_output.muted is False


def test_gross_overshoot_is_corrected():
    st = _stub(pos=151_000, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_finish(st)
    assert st.player.seeks == [150_000]


def test_stale_generation_is_ignored():
    st = _stub(pos=150_000, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_finish(st, gen=99)
    assert st._prerolling is True


def test_tick_stops_slightly_before_target():
    """Сторож ловит цель с упреждением: промахнуться назад безопаснее."""
    st = _stub(pos=150_000 - EditTab._PREROLL_GUARD_MS, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_tick(st)
    assert st._prerolling is False


def test_tick_waits_while_far_from_target():
    st = _stub(pos=149_600, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_tick(st)
    assert st._prerolling is True


def test_play_mid_preroll_hands_off_instead_of_seeking():
    """«Воспроизвести» посреди разбега: доигрываем остаток под mute и снимаем
    mute на цели. Перемотка здесь остудила бы звук — ровно то, чего избегаем."""
    st = _stub(pos=149_900, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    st.current_in, st.current_out = 0.0, 100.0
    EditTab.toggle_play(st)
    assert st._preroll_handoff is True
    assert st.player.seeks == []
    assert st.player.paused == 0
    st.player.pos = 150_000               # разбег доехал до цели
    EditTab._preroll_tick(st)
    assert st._preroll_handoff is False
    assert st.audio_output.muted is False
    assert st.released == 1               # пин снят ровно на отметке


# ── 2. …и при этом его не видно ─────────────────────────────────────────────
def test_ui_frozen_on_target_while_prerolling():
    st = _stub(pos=149_500)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    assert EditTab._ui_pinned_ms(st) == 150_000


def test_ui_frozen_on_step_frame_while_scrubbing():
    """overlay-режим доставляет кадр коротким play(): плеер уезжает вперёд и
    возвращается. На шкале обязан стоять заказанный кадр."""
    st = _stub(pos=10_120)
    st._scrubbing = True
    st._scrub_audio_ms = 10_000
    assert EditTab._ui_pinned_ms(st) == 10_000


def test_ui_follows_real_clock_when_player_is_free():
    assert EditTab._ui_pinned_ms(_stub()) is None


def test_playhead_does_not_move_during_preroll():
    """Главный тест: разбег бежит от 149.5 к 150 с — на шкале ничего не едет."""
    st = _stub(pos=149_500)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    st.painted = []
    st._preroll_watch = lambda ms: None
    st._confirm_frame_seek = lambda ms: None
    st._clock_pos_s = lambda: st.player.position() / 1000.0
    st._paint_playhead = lambda t: st.painted.append(t)
    st._update_meter = lambda t, force=False: None
    st._update_subtitle = lambda t: None
    for ms in (149_500, 149_700, 149_900):
        st.player.pos = ms
        EditTab.on_position_changed(st, ms)
    assert st.painted == [150.0, 150.0, 150.0]


# ── 3. Прогрев не мешает точности ───────────────────────────────────────────
def test_frame_step_cancels_preroll_without_extra_seek():
    """Шаг стрелкой посреди разбега гасит его БЕЗ доводки до устаревшей цели:
    позицию сейчас поставит сам шаг. Лишний seek съел бы кадр времени."""
    st = _stub(pos=149_500)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    st._frame_idx = 250
    st._scrub_audio_blip = lambda painted: None
    st._update_meter = lambda *a, **k: None
    EditTab.step_frame_scrub(st, +1)
    assert st._prerolling is False
    assert st.player.paused == 1
    assert st.audio_output.muted is False
    assert st.player.seeks == [st._grid.ms_of(251)]   # ровно одна — от шага


def test_seek_to_cancels_preroll_first():
    """Клик по шкале посреди разбега: иначе плеер продолжил бы играть уже от
    новой отметки и уехал бы с неё."""
    st = _stub(pos=149_500)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    st._scrub_idle_timer = SimpleNamespace(start=lambda: None)
    st.main = SimpleNamespace(log=lambda *a: None)
    EditTab.seek_to(st, 20.0)
    assert st._prerolling is False
    assert st.player.paused == 1
    assert st.player.seeks == [20_000]


def test_single_frame_step_is_one_seek_and_stays_put():
    st = _stub(pos=10_000)                      # 10 c при 25 fps — кадр 250
    st._frame_idx = 250
    EditTab.step_frame(st, +1)
    assert st._frame_idx == 251
    assert st.player.seeks == [st._grid.ms_of(251)]
    assert st.pinned == [251]


def test_step_there_and_back_returns_to_same_frame():
    """«Влево-вправо» обязано возвращать ТОТ ЖЕ кадр, а не соседний."""
    st = _stub(pos=10_000)
    st._frame_idx = 250
    EditTab.step_frame(st, +1)
    EditTab._release_frame_seek(st, st._frame_seek_gen)
    EditTab.step_frame(st, -1)
    assert st._frame_idx == 250
    assert st.player.seeks[-1] == st._grid.ms_of(250)


def test_held_arrow_keeps_one_seek_in_flight():
    """Удержание стрелки: в полёте не больше одного seek'а — «догоняющего»
    скачка после отпускания клавиши быть не должно."""
    st = _stub(pos=10_000)
    st._frame_idx = 250
    for _ in range(5):
        EditTab.step_frame(st, +1)
    assert len(st.player.seeks) == 1              # остальные ушли в pending
    assert st._frame_idx == 255
    EditTab._release_frame_seek(st, st._frame_seek_gen)
    assert st.player.seeks[-1] == st._grid.ms_of(255)


# ── 4. Истина у интерфейса одна — КАДР ──────────────────────────────────────
def test_ui_clock_shows_frame_start_not_preroll_target():
    """Прогрев целится в СЕРЕДИНУ кадра (иначе плеер промахнётся мимо него), а
    показывать интерфейс обязан НАЧАЛО кадра — то же время, что у картинки.
    Пока сюда шла цель прогрева, метка после каждого шага дёргалась на полкадра
    туда-обратно (замерено на живом файле: .017 → .025 → .017)."""
    st = _stub(pos=149_500)
    st._frame_idx = 3750                       # 150.000 с при 25 fps
    st._prerolling = True
    st._preroll_target_ms = st._grid.ms_of(3750)
    assert st._preroll_target_ms != 150_000    # это середина кадра
    assert EditTab._ui_pinned_ms(st) == 150_000


def test_ui_clock_shows_frame_start_while_scrubbing():
    st = _stub(pos=149_500)
    st._frame_idx = 3750
    st._scrubbing = True
    st._scrub_target = st._grid.ms_of(3750)
    assert EditTab._ui_pinned_ms(st) == 150_000


def test_playhead_target_is_frame_center_not_player_position():
    """Куда целиться плееру, решает КАДР. player.position() тут врёт дважды:
    после перемотки он стоит где-то внутри кадра, а при удержании стрелки ещё
    и отстаёт на недоехавший seek."""
    st = _stub(pos=100_000)
    st._frame_idx = 3750
    assert EditTab._playhead_target_s(st) == pytest.approx(st._grid.center_of(3750))


def test_playhead_target_falls_back_to_player_without_grid():
    st = _stub(pos=100_000, fps=0.0)
    assert EditTab._playhead_target_s(st) == pytest.approx(100.0)


def test_preroll_after_step_series_aims_at_frame_not_lagging_player():
    """Серия шагов кончилась, а позиция плеера ещё догоняет плейхед (в полёте
    один seek, остальные ждут). Прогрев обязан целиться в кадр: считая от
    позиции плеера, он утаскивал туда же и номер кадра, и метку — картинка
    «пятилась назад» через 160 мс после шага."""
    st = _stub(pos=100_000)                    # плеер далеко позади плейхеда
    st._frame_idx = 3750
    st._playhead_target_s = lambda: EditTab._playhead_target_s(st)
    EditTab._end_scrub_painted(st)
    assert st._frame_idx == 3750               # кадр не сдвинулся
    assert st._preroll_target_ms == st._grid.ms_of(3750)
    assert st.player.seeks == [st._grid.ms_of(3750) - EditTab._PREROLL_LEAD_MS]


def test_preroll_does_not_recompute_frame_index():
    st = _stub(pos=0)
    st._frame_idx = 3750
    EditTab._preroll_at(st, 60.0)              # цель мимо текущего кадра
    assert st._frame_idx == 3750


def test_preroll_finish_paints_frame_start():
    """Конец прогрева не имеет права двигать метку на свою цель (середину
    кадра): на экране пришпилен кадр, метка обязана показывать его начало."""
    st = _stub(pos=150_030, playing=True)
    st._frame_idx = 3750
    st._prerolling = True
    st._preroll_target_ms = st._grid.ms_of(3750)
    painted = []
    st.waveform = SimpleNamespace(set_playhead=painted.append)
    EditTab._preroll_finish(st)
    assert painted == [150.0]
    assert st._frame_idx == 3750


# ── 5. Звук шага берётся у кадра ────────────────────────────────────────────
def test_scrub_audio_time_is_frame_start():
    """Звук шага начинается там же, где картинка, — с НАЧАЛА кадра (плееру мы
    отдаём середину). Считаем из номера кадра, а не из округлённых мс."""
    st = _stub()
    st._frame_idx = 3750
    assert EditTab._scrub_audio_time_s(st) == pytest.approx(150.0)


def test_scrub_audio_time_falls_back_to_scrub_ms():
    st = _stub(fps=0.0)
    st._scrub_audio_ms = 12_345
    assert EditTab._scrub_audio_time_s(st) == pytest.approx(12.345)


def test_scrub_blip_length_is_at_least_audible():
    """Блип — не короче слышимого и не длиннее, чем нужно: длинный хвост как
    раз и звучал как «звук уехал вперёд, а потом попятился назад»."""
    st = _stub(fps=60.0)
    assert (EditTab._SCRUB_BLIP_MIN_S
            <= EditTab._scrub_blip_seconds(st) <= EditTab._SCRUB_BLIP_MAX_S)
    st.fps = 12.0                              # кадр 83 мс — играем его целиком
    assert EditTab._scrub_blip_seconds(st) == pytest.approx(1 / 12.0)
    st.fps = 5.0                               # кадр 200 мс — режем по потолку
    assert EditTab._scrub_blip_seconds(st) == EditTab._SCRUB_BLIP_MAX_S


def test_no_preroll_without_room_to_run_up():
    """У самого начала файла разбегаться негде: play() и pause() попали бы в
    один такт, ffmpeg-бэкенд такую пару теряет — плеер оставался ИГРАТЬ и уезжал
    со стартового кадра сам (проверено вживую на нулевом кадре)."""
    st = _stub(pos=0)
    EditTab._preroll_at(st, 0.05)
    assert st._prerolling is False
    assert st.player.played == 0
    assert st.audio_output.muted is False


def test_preroll_tick_waits_until_player_really_plays():
    """Сторож не тормозит, пока play() не отработал: иначе pause() теряется."""
    st = _stub(pos=150_000, playing=False)
    st._prerolling = True
    st._preroll_target_ms = 150_000
    EditTab._preroll_tick(st)
    assert st._prerolling is True          # плеер ещё не заиграл — ждём
    st.player.playing = True
    EditTab._preroll_tick(st)
    assert st._prerolling is False


def test_stale_playing_signal_does_not_release_pin():
    """Устаревший playbackStateChanged(Playing) пришёл, когда плеер уже стоит:
    пин кадра снимать нельзя — картинка уехала бы с кадра монтажа."""
    st = _stub(pos=150_000, playing=False)
    st.video_widget = None
    EditTab.on_playback_changed(st, edit_tab.QMediaPlayer.PlaybackState.PlayingState)
    assert st.released == 0
