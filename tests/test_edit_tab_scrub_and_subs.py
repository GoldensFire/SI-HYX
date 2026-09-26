# -*- coding: utf-8 -*-
"""Монтаж: покадровый шаг не мигает субтитрами, не звучит дважды и не лагает.

Живые жалобы, разобранные здесь:

1. **Субтитры вспыхивают на шаг стрелкой.** Прогрев конвейера играет с отметки
   на 500 мс РАНЬШЕ плейхеда, и ASS-таймер рисовал libass по сырой
   `player.position()` — то есть выводил реплики из этого полусекундного
   прошлого. Всё время интерфейса обязано идти через `_ui_time_s`.
2. **Звук на шаге слышен дважды.** После `pause()` аудиоустройство ещё ~130 мс
   доигрывает очередь (замерено щупом WASAPI), а mute снимался в том же такте —
   хвост прогрева и был вторым звуком. Возврат звука отложен.
3. **Жёлтая полоса уезжает после остановки.** На паузе истина — номер кадра, а
   не позиция плеера (та живёт по аудио-часам).
4. **Лаги при удержании ←/→.** Плееру на серии шагов не нужен каждый шаг:
   картинку даёт предекодер, а его `setPosition` на тяжёлом источнике — полная
   раскрутка GOP параллельно с предекодером.

Плюс вшивание субтитров в режиме «перекодировать настройками «Обработки»» и
пункт «Показать другие файлы в папке…» в списке дорожек.
"""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
workers = pytest.importorskip("workers")
EditTab = edit_tab.EditTab
FrameGrid = edit_tab.FrameGrid


class _Player:
    def __init__(self, pos=0, playing=False):
        self.pos = int(pos)
        self.seeks = []
        self.playing = playing

    def position(self): return self.pos
    def play(self): self.playing = True
    def pause(self): self.playing = False
    def setPosition(self, ms): self.seeks.append(int(ms)); self.pos = int(ms)

    def playbackState(self):
        S = edit_tab.QMediaPlayer.PlaybackState
        return S.PlayingState if self.playing else S.PausedState


def _tab(pos_ms=60_000, fps=25.0, duration=200.0, playing=False):
    out = SimpleNamespace(muted=False)
    out.setMuted = lambda v: setattr(out, 'muted', bool(v))
    out.isMuted = lambda: bool(out.muted)
    st = SimpleNamespace(
        player=_Player(pos_ms, playing),
        audio_output=out,
        fps=fps, duration=duration, filepath="clip.mp4",
        _grid=FrameGrid(fps, duration),
        _frame_idx=None,
        _scrubbing=False, _scrub_target=None, _scrub_audio_ms=None,
        _prerolling=False, _preroll_handoff=False, _preroll_target_ms=None,
        _preroll_prev_muted=False, _preroll_gen=1,
        _preroll_unmute_pending=False, _preroll_unmute_gen=0,
        _frame_seek_busy=False, _frame_seek_pending=None,
        _frame_seek_target_ms=None, _frame_seek_gen=0,
        _frame_seek_deferred_ms=None, _frame_seek_last_at=0.0,
        video_widget=None, video_stream_index=0,
        _PREROLL_UNMUTE_MS=EditTab._PREROLL_UNMUTE_MS,
        _SCRUB_SEEK_MS=EditTab._SCRUB_SEEK_MS,
    )
    st._ext_audio_seek = lambda ms: None
    st._finish_preroll_unmute = lambda gen=None: EditTab._finish_preroll_unmute(st, gen)
    st._ui_pinned_ms = lambda: EditTab._ui_pinned_ms(st)
    st._clock_pos_s = lambda: st.player.position() / 1000.0
    st._ui_time_s = lambda: EditTab._ui_time_s(st)
    st._show_exact_frame = lambda idx=None, direction=1: None
    st._current_frame_index = lambda: EditTab._current_frame_index(st)
    st._send_frame_seek = lambda ms: EditTab._send_frame_seek(st, ms)
    st._dispatch_frame_seek = lambda ms: EditTab._dispatch_frame_seek(st, ms)
    st._flush_frame_seek = lambda: EditTab._flush_frame_seek(st)
    st.step_frame = lambda step: EditTab.step_frame(st, step)
    return st


@pytest.fixture(autouse=True)
def no_singleshot(monkeypatch):
    """Запасные Qt-таймеры (_dispatch_frame_seek, отложенный unmute) не должны
    стрелять посреди чужого теста — своего QApplication здесь нет."""
    fired = []
    monkeypatch.setattr(edit_tab.QTimer, "singleShot",
                        staticmethod(lambda ms, cb=None: fired.append((ms, cb))))
    return fired


# ── 1. Время интерфейса ──────────────────────────────────────────────────────
def test_ui_time_on_pause_follows_frame_not_player():
    """На паузе плеер стоит по аудио-часам где-то ВНУТРИ кадра — интерфейс
    обязан показывать сам кадр, иначе полоса дёргается после остановки."""
    st = _tab(pos_ms=60_137)
    st._frame_idx = st._grid.index_at(60.0)
    assert EditTab._ui_time_s(st) == pytest.approx(60.0, abs=0.001)


def test_ui_time_while_prerolling_ignores_running_player():
    """Разбег прогрева уехал на полсекунды назад — ровно это и рисовалось в
    субтитрах. Наружу прогрева не существует."""
    st = _tab(pos_ms=59_500, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 60_000
    st._frame_idx = st._grid.index_at(60.0)
    assert EditTab._ui_time_s(st) == pytest.approx(60.0, abs=0.001)


def test_ui_time_while_playing_uses_clock():
    """Во время настоящего воспроизведения — часы кадра (_clock_pos_s)."""
    st = _tab(pos_ms=61_000, playing=True)
    st._frame_idx = None
    assert EditTab._ui_time_s(st) == pytest.approx(61.0)


def test_ass_tick_draws_by_ui_time_not_player_position():
    """Тот самый баг: во время разбега libass рисовал реплики из прошлого."""
    st = _tab(pos_ms=59_500, playing=True)
    st._prerolling = True
    st._preroll_target_ms = 60_000
    st._frame_idx = st._grid.index_at(60.0)
    st._sub_use_ass = True
    st._ass = object()
    drawn = []
    st._update_subtitle = drawn.append
    EditTab._on_ass_tick(st)
    assert drawn and drawn[0] == pytest.approx(60.0, abs=0.001)


# ── 2. Второй звук ───────────────────────────────────────────────────────────
def test_unmute_is_deferred_after_pause(no_singleshot):
    """Хвост очереди аудиоустройства доигрывается уже после pause(); снятый в
    том же такте mute открывал его — это и был второй звук на шаге."""
    st = _tab()
    st.audio_output.setMuted(True)
    EditTab._restore_preroll_mute(st)
    assert st.audio_output.muted is True           # ещё молчим
    assert st._preroll_unmute_pending is True
    delay, cb = no_singleshot[-1]
    assert delay == EditTab._PREROLL_UNMUTE_MS
    cb()                                           # таймер выстрелил
    assert st.audio_output.muted is False


def test_unmute_back_to_muted_is_immediate(no_singleshot):
    """Возврат В mute (выбрана внешняя озвучка) ничего не озвучивает — ждать
    незачем."""
    st = _tab()
    st._preroll_prev_muted = True
    EditTab._restore_preroll_mute(st)
    assert st.audio_output.muted is True
    assert st._preroll_unmute_pending is False


def test_play_during_deferred_unmute_returns_sound_at_once(no_singleshot):
    """«Воспроизвести» в окне отложенного возврата: ждать нельзя, иначе
    воспроизведение началось бы немым."""
    st = _tab()
    st.audio_output.setMuted(True)
    EditTab._restore_preroll_mute(st)
    EditTab._flush_preroll_mute(st)
    assert st.audio_output.muted is False
    assert st._preroll_unmute_pending is False


def test_stale_unmute_timer_does_not_open_new_preroll(no_singleshot):
    """Таймер прошлого прогрева не имеет права снять mute у нового."""
    st = _tab()
    st.audio_output.setMuted(True)
    EditTab._restore_preroll_mute(st)
    _, stale_cb = no_singleshot[-1]
    st.audio_output.setMuted(True)                 # начался новый разбег
    EditTab._restore_preroll_mute(st)              # он же поднял поколение
    stale_cb()                                     # опоздавший таймер
    assert st.audio_output.muted is True


# ── 3. Удержание стрелки: плееру не каждый шаг ───────────────────────────────
def test_held_arrow_does_not_seek_player_every_step():
    """20 шагов подряд — плеер получает позицию не чаще _SCRUB_SEEK_MS."""
    st = _tab(pos_ms=60_000)
    st._scrubbing = True
    st._frame_idx = st._grid.index_at(60.0)
    for _ in range(20):
        EditTab.step_frame(st, +1)
    assert len(st.player.seeks) == 1               # только первый шаг серии
    assert st._frame_seek_deferred_ms == st._grid.ms_of(st._frame_idx)


def test_series_end_delivers_final_position():
    """…но итоговая точка серии обязана дойти до плеера, иначе
    «Воспроизвести» стартовало бы не оттуда, где стоит монтаж."""
    st = _tab(pos_ms=60_000)
    st._scrubbing = True
    st._frame_idx = st._grid.index_at(60.0)
    for _ in range(20):
        EditTab.step_frame(st, +1)
    st._scrubbing = False
    EditTab._flush_frame_seek(st)
    # Первый seek серии ещё «в полёте» — итоговая цель ждёт его в pending
    # (прежний механизм: больше одного setPosition одновременно не шлём).
    assert st._frame_seek_deferred_ms is None
    EditTab._release_frame_seek(st, st._frame_seek_gen)
    assert st.player.seeks[-1] == st._grid.ms_of(st._grid.index_at(60.0) + 20)


def test_single_step_reaches_player_immediately():
    """Одиночный шаг НЕ откладывается: троттлинг включается только внутри серии
    и только после первой отдачи."""
    st = _tab(pos_ms=60_000)
    st._frame_idx = st._grid.index_at(60.0)
    EditTab.step_frame(st, +1)
    assert st.player.seeks == [st._grid.ms_of(st._grid.index_at(60.0) + 1)]


def test_flush_without_deferred_is_noop():
    st = _tab(pos_ms=60_000)
    EditTab._flush_frame_seek(st)
    assert st.player.seeks == []


# ── 4. Вшивание субтитров настройками «Обработки» ────────────────────────────
def _pw_stub():
    return SimpleNamespace(
        _detect_crop=lambda *a, **k: None,
        _scale_vf=lambda res: "",
        log=SimpleNamespace(emit=lambda *a: None),
    )


def _vf_list(item, t0, speed=1.0, sv=None):
    return workers.ProcessWorker._build_video_filters(
        _pw_stub(), sv or {}, item, "in.mkv", (18.0, 24.0), t0, t0, speed)


def test_burn_subs_filter_is_time_corrected_for_preseek():
    """«Обработка» режет входным pre-seek'ом, а он обнуляет тайминги в своей
    точке; subtitles же ищет реплики по времени самого файла субтитров.
    Проверено живым ffmpeg: без поправки текст уезжает из клипа целиком."""
    item = {'burn_subs': {'vf': "subtitles='a.ass'", 'src_in': 18.0}}
    vf = _vf_list(item, t0=3.0)
    assert vf == ["setpts=PTS+15.000000/TB", "subtitles='a.ass'",
                  "setpts=PTS-15.000000/TB"]


def test_burn_subs_without_preseek_needs_no_correction():
    """in_s ≤ 2*PRESEEK — pre-seek'а нет, шкала фильтров и есть время файла."""
    item = {'burn_subs': {'vf': "subtitles='a.ass'", 'src_in': 4.0}}
    assert _vf_list(item, t0=4.0) == ["subtitles='a.ass'"]


def test_burn_subs_goes_before_speed_setpts():
    """Субтитры вшиваются ДО смены скорости: setpts меняет то самое время, по
    которому фильтр ищет реплики."""
    item = {'burn_subs': {'vf': "subtitles='a.ass'", 'src_in': 4.0}}
    vf = _vf_list(item, t0=4.0, speed=2.0)
    assert vf.index("subtitles='a.ass'") < vf.index("setpts=0.5*PTS")


def test_no_burn_subs_key_changes_nothing():
    assert _vf_list({}, t0=3.0) == []


# ── 5. «Показать другие файлы в папке…» в списке дорожек ─────────────────────
class _Combo:
    """Достаточно комбобокса, чтобы проверить состав списка и выбор."""

    def __init__(self, idx=0):
        self.items = []
        self.idx = idx
        self.popups = 0

    def clear(self): self.items = []
    def addItem(self, *a): self.items.append(a[-1])
    def currentIndex(self): return self.idx
    def setCurrentIndex(self, i): self.idx = int(i)
    def setEnabled(self, v): self.enabled = bool(v)
    def isEnabled(self): return True
    def isVisible(self): return True
    def showPopup(self): self.popups += 1


def _subs_tab(monkeypatch, hidden=("/x/other1.srt", "/x/other2.srt")):
    monkeypatch.setattr(edit_tab, "get_icon", lambda *a, **k: None)
    combo = _Combo(idx=2)                     # выбран пункт «Показать другие…»
    st = SimpleNamespace(
        cmb_subs=combo,
        _sub_streams=[{'index': 2, 'codec_name': 'ass', 'tags': {}}],
        _sub_ext=[],
        _sub_ext_hidden=list(hidden),
        _sub_entries=[('emb', 0), ('more', None)],
        _sub_sel_entry=('emb', 0),            # РЕАЛЬНО выбрана встроенная дорожка
        _loading_tracks=False,
    )
    st._track_label = lambda *a, **k: "1. Субтитры"
    st._populate_track_combos_subs_only = \
        lambda: EditTab._populate_track_combos_subs_only(st)
    return st, combo


def test_show_more_keeps_selected_track(monkeypatch):
    """Клик по «Показать другие файлы…» не имеет права сбрасывать выбранную
    дорожку: пункт-команда сам стоит выбранным, и именно его раньше пытались
    восстановить — список молча вставал на «Выкл»."""
    st, combo = _subs_tab(monkeypatch)
    EditTab._expand_external_subs(st)
    assert combo.items[0] == "Выкл"
    assert len(combo.items) == 4              # Выкл + дорожка + два файла
    assert st._sub_entries[combo.idx - 1] == ('emb', 0)
    assert st._sub_ext_hidden == []           # пункта «ещё» больше нет


def test_show_more_reopens_the_list(monkeypatch, no_singleshot):
    """…и список открывается снова — его ведь раскрывали, чтобы ВЫБРАТЬ файл."""
    st, combo = _subs_tab(monkeypatch)
    st._expand_external_subs = lambda: EditTab._expand_external_subs(st)
    st._reopen_subs_popup = lambda: EditTab._reopen_subs_popup(st)
    EditTab.on_sub_track_changed(st, 2)
    assert combo.popups == 0                  # не в том же такте
    for _, cb in no_singleshot:
        if cb is not None:
            cb()
    assert combo.popups == 1
