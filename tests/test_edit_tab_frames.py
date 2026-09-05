# -*- coding: utf-8 -*-
"""Покадровая точность «Монтажа» (edit_tab_frames.FrameGrid + EditTab.step_frame).

Что здесь проверяется и почему именно это:
  • раньше шаг считался как «позиция плеера ± 1000/fps» в ЦЕЛЫХ миллисекундах,
    поэтому при 23.976 fps шаг был 41 мс вместо 41.708 — за полсотни шагов
    набегал лишний кадр, и стрелка показывала «не тот» кадр;
  • попадание РОВНО на границу кадра неоднозначно (плеер берёт кадр с pts ≤
    позиции, ffmpeg — первый с pts ≥ -ss), поэтому цель шага обязана лежать в
    СЕРЕДИНЕ кадра, а -ss для ffmpeg — четвертью кадра НИЖЕ его pts;
  • метка таймлайна должна идти по времени ПОКАЗАННОГО кадра, иначе она живёт
    отдельно от картинки.
"""
from types import SimpleNamespace

import pytest

frames = pytest.importorskip("edit_tab_frames")
FrameGrid = frames.FrameGrid

FPS_LIST = [23.976023976023978, 24.0, 25.0, 29.97002997002997, 30.0,
            50.0, 59.94005994005994, 60.0, 119.88011988011988]


# ── Сетка кадров ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fps", FPS_LIST)
def test_ms_target_round_trips_to_same_frame(fps):
    """Ключевое свойство: цель шага в МИЛЛИСЕКУНДАХ обязана опознаваться как
    тот же самый кадр. Именно здесь ломался старый код."""
    g = FrameGrid(fps, 3600.0)
    for i in range(0, 20000, 7):
        ms = g.ms_of(i)
        assert g.index_at(ms / 1000.0) == i, (fps, i, ms)


@pytest.mark.parametrize("fps", FPS_LIST)
def test_no_drift_over_long_series(fps):
    """1000 шагов вперёд и столько же назад — ровно исходный кадр."""
    g = FrameGrid(fps, 3600.0)
    idx = 500
    for _ in range(1000):
        idx = g.clamp(g.index_at(g.ms_of(idx) / 1000.0) + 1)
    assert idx == 1500
    for _ in range(1000):
        idx = g.clamp(g.index_at(g.ms_of(idx) / 1000.0) - 1)
    assert idx == 500


@pytest.mark.parametrize("fps", FPS_LIST)
def test_pts_maps_to_its_own_frame(fps):
    """pts кадра (то, что приходит от плеера) — это ровно его номер."""
    g = FrameGrid(fps, 600.0)
    for i in (0, 1, 2, 97, 1000, 5000):
        assert g.index_of_pts(g.start_of(i)) == i


@pytest.mark.parametrize("fps", FPS_LIST)
def test_seek_lands_between_frames(fps):
    """-ss для ffmpeg лежит СТРОГО между предыдущим кадром и нужным: значит
    «первый кадр с pts ≥ ss» — это именно нужный, а не следующий."""
    g = FrameGrid(fps, 600.0)
    for i in (1, 2, 50, 1234):
        ss = g.seek_of(i)
        assert g.start_of(i - 1) < ss < g.start_of(i)


def test_center_is_half_frame_from_borders():
    g = FrameGrid(25.0, 100.0)
    assert g.center_of(10) == pytest.approx(10.5 / 25.0)
    assert g.start_of(10) == pytest.approx(10 / 25.0)


def test_clamp_and_last_frame():
    g = FrameGrid(25.0, 4.0)          # 100 кадров: 0..99
    assert g.last == 99
    assert g.clamp(150) == 99
    assert g.clamp(-3) == 0


def test_invalid_grid_is_inert():
    """fps неизвестен — сетка не притворяется, что что-то знает."""
    g = FrameGrid(0.0, 10.0)
    assert not g.valid
    assert g.index_at(5.0) == 0 and g.ms_of(3) == 0 and g.seek_of(3) == 0.0


def test_first_frame_seek_not_negative():
    g = FrameGrid(24.0, 10.0)
    assert g.seek_of(0) == 0.0


# ── EditTab.step_frame поверх сетки ─────────────────────────────────────────
edit_tab = pytest.importorskip("edit_tab")


class _Player:
    def __init__(self, pos_ms=0, playing=False):
        self._pos = pos_ms
        self._playing = playing

    def position(self):
        return self._pos

    def playbackState(self):
        st = edit_tab.QMediaPlayer.PlaybackState
        return st.PlayingState if self._playing else st.PausedState


def _tab(fps=23.976023976023978, dur=600.0, pos_ms=0, playing=False):
    seeks = []
    shown = []
    st = SimpleNamespace(
        duration=dur, fps=fps,
        _grid=FrameGrid(fps, dur),
        _frame_idx=None,
        _scrubbing=False, _scrub_target=None, _scrub_audio_ms=None,
        video_widget=None, video_stream_index=0,
        player=_Player(pos_ms, playing),
    )
    st._dispatch_frame_seek = lambda ms: seeks.append(ms)
    st._show_exact_frame = lambda idx, direction=1: shown.append((idx, direction))
    # Определение текущего кадра — настоящее (его и проверяем заодно).
    st._current_frame_index = lambda: edit_tab.EditTab._current_frame_index(st)
    return st, seeks, shown


def test_step_frame_moves_exactly_one_frame():
    st, seeks, shown = _tab()
    st._frame_idx = 100
    edit_tab.EditTab.step_frame(st, 1)
    assert st._frame_idx == 101
    assert shown == [(101, 1)]
    # Плееру ушла СЕРЕДИНА кадра, а звуку скраба — его начало.
    assert seeks == [st._grid.ms_of(101)]
    assert st._scrub_audio_ms == int(round(st._grid.start_of(101) * 1000))


def test_step_series_is_exact_at_fractional_fps():
    """Сотня шагов вперёд = ровно сто кадров (старая арифметика на 23.976
    теряла кадр примерно каждый 60-й шаг)."""
    st, seeks, _ = _tab()
    st._frame_idx = 0
    for _ in range(100):
        edit_tab.EditTab.step_frame(st, 1)
    assert st._frame_idx == 100
    assert st._grid.index_at(seeks[-1] / 1000.0) == 100


def test_step_back_returns_to_same_frame():
    st, _, _ = _tab()
    st._frame_idx = 42
    edit_tab.EditTab.step_frame(st, 1)
    edit_tab.EditTab.step_frame(st, -1)
    assert st._frame_idx == 42


def test_step_clamped_at_start():
    st, _, _ = _tab()
    st._frame_idx = 0
    edit_tab.EditTab.step_frame(st, -1)
    assert st._frame_idx == 0


def test_step_without_fps_falls_back_to_time():
    """Битые метаданные (fps нет) — работает старый путь по миллисекундам."""
    st, seeks, shown = _tab(fps=0.0)
    st._grid = FrameGrid(0.0, 600.0)
    st.player._pos = 1000
    edit_tab.EditTab.step_frame(st, 1)
    assert seeks == [1040] and shown == []


def test_step_from_player_position_when_index_unknown():
    """Первый шаг после воспроизведения: номер кадра берётся из позиции."""
    st, _, _ = _tab(pos_ms=5000)
    st._frame_idx = None
    edit_tab.EditTab.step_frame(st, 1)
    assert st._frame_idx == st._grid.index_at(5.0) + 1


# ── Мастер-часы ────────────────────────────────────────────────────────────
class _Canvas(edit_tab.VideoCanvas):
    """Настоящий холст (важно: проверяем реальный фильтр кадров), но без окна."""
    pass


@pytest.fixture
def canvas(qapp):
    return _Canvas()


def _frame(pts_us, img):
    """Утиный «кадр плеера»: холсту от QVideoFrame нужны ровно эти три метода."""
    return SimpleNamespace(startTime=lambda: pts_us, isValid=lambda: True,
                           toImage=lambda: img)


def _img(qapp, w=4, h=4):
    from PyQt6.QtGui import QImage
    im = QImage(w, h, QImage.Format.Format_RGB888)
    im.fill(0)
    return im


def test_canvas_ignores_foreign_frame_while_pinned(canvas, qapp):
    g = FrameGrid(25.0, 100.0)
    exact = _img(qapp)
    canvas.set_exact_frame(exact, g.pts_span_us(10), int(g.start_of(10) * 1e6))
    other = _img(qapp, 8, 8)
    canvas._on_frame(_frame(int(g.start_of(11) * 1e6), other))   # чужой кадр
    assert canvas.current_frame_image().width() == 4              # остался наш
    assert canvas.last_frame_pts() == pytest.approx(g.start_of(10))


def test_canvas_accepts_same_frame_from_player(canvas, qapp):
    """Кадр плеера с ТЕМ ЖЕ номером — законный (он же от настоящего декодера)."""
    g = FrameGrid(25.0, 100.0)
    canvas.set_exact_frame(_img(qapp), g.pts_span_us(10), int(g.start_of(10) * 1e6))
    canvas._on_frame(_frame(int(g.start_of(10) * 1e6), _img(qapp, 8, 8)))
    assert canvas.current_frame_image().width() == 8


def test_canvas_takes_player_frame_before_exact_arrives(canvas, qapp):
    """Пока точного кадра нет, кадр плеера показать ЛУЧШЕ, чем застывший старый."""
    g = FrameGrid(25.0, 100.0)
    canvas.arm_frame_pin(g.pts_span_us(10))
    canvas._on_frame(_frame(int(g.start_of(11) * 1e6), _img(qapp, 8, 8)))
    assert canvas.current_frame_image().width() == 8


def test_clock_follows_frame_on_pause(canvas, qapp):
    g = FrameGrid(25.0, 100.0)
    canvas.set_exact_frame(_img(qapp), g.pts_span_us(10), int(g.start_of(10) * 1e6))
    st = SimpleNamespace(player=_Player(9999), video_widget=canvas,
                         video_stream_index=0, _grid=g)
    assert edit_tab.EditTab._clock_pos_s(st) == pytest.approx(0.4)  # 10/25


def test_clock_falls_back_to_player_for_audio_only(qapp):
    st = SimpleNamespace(player=_Player(2500), video_widget=None,
                         video_stream_index=None, _grid=FrameGrid(0, 0))
    assert edit_tab.EditTab._clock_pos_s(st) == pytest.approx(2.5)


def test_clock_falls_back_when_frames_stalled(canvas, qapp, monkeypatch):
    """Кадры перестали приходить во время игры — метка не должна замирать."""
    g = FrameGrid(25.0, 100.0)
    canvas.set_exact_frame(_img(qapp), g.pts_span_us(10), int(g.start_of(10) * 1e6))
    monkeypatch.setattr(canvas, "frame_clock_age", lambda: 5.0)
    st = SimpleNamespace(player=_Player(9000, playing=True), video_widget=canvas,
                         video_stream_index=0, _grid=g)
    assert edit_tab.EditTab._clock_pos_s(st) == pytest.approx(9.0)


def test_no_pin_while_playing(canvas, qapp):
    """Стрелка нажата на ходу: пин ставить нельзя — иначе картинка встанет."""
    g = FrameGrid(25.0, 100.0)
    st = SimpleNamespace(player=_Player(1000, playing=True), video_widget=canvas,
                         video_stream_index=0, _grid=g,
                         is_still_image=False, _frame_idx=5, filepath=None,
                         _frames_src=None)
    edit_tab.EditTab._show_exact_frame(st, 5)
    assert not canvas.has_frame_pin()


# ── Буфер кадров: не перебиваем сами себя ───────────────────────────────────
def test_request_does_not_preempt_running_window(qapp):
    """Удержание стрелки шлёт запрос на каждый шаг. Если нужный кадр уже
    декодируется текущим запуском ffmpeg — новый запрос не ставится, иначе
    процесс убивался бы по 30 раз в секунду и буфер не наполнялся никогда."""
    pf = frames.FramePrefetcher()
    pf.set_source("clip.mp4", 25.0)
    pf._running = (100, 108)
    pf.request(102, ahead=8, behind=3)
    assert pf._queue == []


def test_request_enqueues_outside_running_window(qapp):
    pf = frames.FramePrefetcher()
    pf.set_source("clip.mp4", 25.0)
    pf._running = (100, 108)
    pf.request(300, ahead=8, behind=3)
    assert pf._queue and pf._queue[0][0] == 300


def test_request_without_source_is_noop(qapp):
    pf = frames.FramePrefetcher()
    pf.request(10)
    assert pf._queue == []


# ── Размер кадра: разбор вывода ffprobe ─────────────────────────────────────
class _ProbeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


@pytest.mark.parametrize("out, expect", [
    ("960x540x\n", (960, 540)),      # ffprobe 2026: разделитель И В КОНЦЕ
    ("960x540\n", (960, 540)),       # прежний формат
    ("1920x1080x", (1920, 1080)),
    ("", (0, 0)),
    ("мусор", (0, 0)),
])
def test_probe_frame_size_tolerates_trailing_separator(monkeypatch, out, expect):
    """Свежие сборки ffprobe печатают `csv=p=0:s=x` с ХВОСТОВЫМ разделителем:
    «960x540x». Старый разбор давал int(«540x») → исключение → (0, 0), а без
    размера кадра предекодер не мог разобрать сырой поток и молча не отдавал НИ
    ОДНОГО точного кадра: холст оставался на кадрах плеера, и шаг стрелкой
    показывал то кадр разбега прогрева, то кадр «около» цели. Разбор обязан
    быть терпимым к лишнему разделителю."""
    monkeypatch.setattr(frames.subprocess, "run",
                        lambda *a, **k: _ProbeProc(stdout=out))
    assert frames.probe_frame_size("clip.mp4") == expect


def test_probe_frame_size_survives_crash(monkeypatch):
    def boom(*a, **k):
        raise OSError("нет ffprobe")
    monkeypatch.setattr(frames.subprocess, "run", boom)
    assert frames.probe_frame_size("clip.mp4") == (0, 0)


# ── Звук покадрового шага (AudioScrubber) ───────────────────────────────────
def _scrubber(qapp, rate=48000, ch=2, sample_bytes=2, start=10.0, seconds=8.0):
    """Скрабер с ГОТОВЫМ окном PCM: ffmpeg не зовём, проверяем арифметику."""
    sc = frames.AudioScrubber()
    sc.configure(rate, ch, sample_bytes)
    n = int(seconds * rate) * ch * sample_bytes
    # Ненулевой «звук», чтобы затухание краёв было видно.
    sc._win = (start, bytes([0x40, 0x40]) * (n // 2))
    return sc


def test_audio_slice_starts_at_asked_moment(qapp):
    """Срез обязан начинаться РОВНО в заказанный момент: звук шага играет с
    начала кадра, а не «где-то рядом» (у прежнего плеера точность была по
    границе аудиопакета — 21 мс при кадре 16.7 мс)."""
    sc = _scrubber(qapp)
    fb = sc.frame_bytes()
    data = sc.slice_at(10.5, 0.045, fade_s=0.0)
    assert len(data) == int(0.045 * 48000) * fb
    # тот же момент из «сырого» окна
    off = int(0.5 * 48000) * fb
    assert data == sc._win[1][off:off + len(data)]


def test_audio_slice_outside_window_is_none(qapp):
    sc = _scrubber(qapp, start=10.0, seconds=2.0)
    assert sc.slice_at(9.0, 0.045) is None      # раньше окна
    assert sc.slice_at(99.0, 0.045) is None     # позже окна


def test_audio_slice_fades_edges(qapp):
    """Края среза приглушаются, иначе на стыке срезов (удержание клавиши)
    слышен щелчок."""
    sc = _scrubber(qapp)
    data = sc.slice_at(10.5, 0.045, fade_s=0.004)
    raw = sc.slice_at(10.5, 0.045, fade_s=0.0)
    assert data[:4] != raw[:4] and data[-4:] != raw[-4:]
    mid = len(data) // 2
    assert data[mid:mid + 64] == raw[mid:mid + 64]   # середина нетронута


def test_audio_window_requested_only_when_needed(qapp):
    """Окно перекачиваем, только если плейхед ушёл к его краю: иначе каждый шаг
    удержания запускал бы новый ffmpeg."""
    sc = _scrubber(qapp)
    sc._src = "clip.mp4"
    sc.request(10.5)
    assert sc._want is None                  # внутри окна — ничего не заказали
    sc.request(17.9)                         # у самого конца окна
    assert sc._want == pytest.approx(17.9 - frames.AudioScrubber.LEAD_S)


def test_audio_window_not_requested_twice(qapp):
    sc = _scrubber(qapp, seconds=0.5)
    sc._src = "clip.mp4"
    sc._busy = max(0.0, 30.0 - frames.AudioScrubber.LEAD_S)
    sc.request(30.0)
    assert sc._want is None                  # ровно это окно уже декодируется


def test_audio_scrubber_without_source_is_noop(qapp):
    sc = frames.AudioScrubber()
    sc.request(10.0)
    assert sc._want is None
    assert sc.slice_at(10.0, 0.045) is None
