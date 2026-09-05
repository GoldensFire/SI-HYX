# -*- coding: utf-8 -*-
"""Режим «Только звук» в Монтаже (кнопка 🎧 в панели плеера).

Зачем он есть: на тяжёлых исходниках (AV1/HEVC 1080p60, ЦП-декод) отрисовка
кадров съедает главный поток и монтаж лагает, а картинка нужна не всегда —
половину работы режут по волне и на слух. Кнопка снимает видеодорожку с плеера.

Что здесь стерегут:
  • видео действительно снимается с ПЛЕЕРА (а не просто прячется картинка);
  • позиция плейхеда переживает смену дорожек — она в Монтаже священна
    (см. test_edit_tab_seek_precision);
  • пока режим включён, ffmpeg не декодирует точные кадры впустую;
  • часы интерфейса переключаются на плеер: часы кадра застыли бы, кадров нет;
  • режим переживает загрузку следующего файла (дорожки известны только после
    LoadedMedia, поэтому применяется он там).
"""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab
FrameGrid = edit_tab.FrameGrid


class _Player:
    def __init__(self, pos=0, track=0):
        self.pos = int(pos)
        self.track = track
        self.track_calls = []
        self.seeks = []
        # ffmpeg-бэкенд после смены набора дорожек может сбросить позицию —
        # ровно это и воспроизводим, чтобы проверить восстановление.
        self.resets_on_track_change = False

    def position(self): return self.pos
    def setPosition(self, ms): self.seeks.append(int(ms)); self.pos = int(ms)
    def activeVideoTrack(self): return self.track

    def setActiveVideoTrack(self, i):
        self.track_calls.append(i)
        self.track = i
        if self.resets_on_track_change:
            self.pos = 0

    def playbackState(self):
        return edit_tab.QMediaPlayer.PlaybackState.PausedState


def _stub(pos=42_000, has_video=True):
    st = SimpleNamespace(
        player=_Player(pos),
        duration=100.0,
        fps=25.0,
        filepath="clip.mkv",
        actual_source_file="clip.mkv",
        video_stream_index=0 if has_video else None,
        is_still_image=False,
        _grid=FrameGrid(25.0, 100.0),
        _frame_idx=1050,
        _audio_only_mode=False,
        _audio_only_prev_track=0,
        _prerolling=False,
        _frames=SimpleNamespace(cancelled=0),
        messages=[],
        pinned=[],
        buttons_refreshed=0,
    )
    st._frames.cancel = lambda: setattr(st._frames, 'cancelled',
                                        st._frames.cancelled + 1)
    st.video_widget = SimpleNamespace(
        set_audio_only_message=lambda t: st.messages.append(t))
    st.main = SimpleNamespace(log=lambda *a: None)
    st._show_exact_frame = lambda idx=None, direction=1: st.pinned.append(idx)
    st._preroll_cancel = lambda: setattr(st, '_prerolling', False)
    st._apply_audio_only_to_player = lambda: EditTab._apply_audio_only_to_player(st)
    st._update_audio_only_placeholder = \
        lambda: EditTab._update_audio_only_placeholder(st)
    st._update_media_buttons = lambda: setattr(st, 'buttons_refreshed',
                                               st.buttons_refreshed + 1)
    return st


# ── Включение / выключение ──────────────────────────────────────────────────
def test_enabling_drops_video_track_from_player():
    st = _stub()
    EditTab._toggle_audio_only(st, True)
    assert st._audio_only_mode is True
    assert st.player.track_calls == [-1]
    assert st._frames.cancelled == 1          # предекодер заглушён
    assert "Только звук" in st.messages[-1]


def test_disabling_restores_previous_track_and_frame():
    st = _stub()
    st.player.track = 1                       # у файла видео вторым потоком
    EditTab._toggle_audio_only(st, True)
    EditTab._toggle_audio_only(st, False)
    assert st.player.track_calls == [-1, 1]
    assert st._audio_only_mode is False
    assert st.messages[-1] == ""              # надпись убрана
    assert st.pinned == [1050]                # кадр вернулся на холст


def test_toggle_to_same_state_is_noop():
    st = _stub()
    EditTab._toggle_audio_only(st, False)
    assert st.player.track_calls == []


def test_position_survives_track_switch():
    """Плейхед в Монтаже священен: смена дорожек не имеет права его сдвинуть."""
    st = _stub(pos=42_000)
    st.player.resets_on_track_change = True
    EditTab._toggle_audio_only(st, True)
    assert st.player.pos == 42_000
    assert st.player.seeks == [42_000]


def test_preroll_is_cancelled_before_switching():
    """Разбег играет плеером, а мы плееру меняем набор дорожек — не должны
    столкнуться."""
    st = _stub()
    st._prerolling = True
    EditTab._toggle_audio_only(st, True)
    assert st._prerolling is False


# ── Пока режим включён ──────────────────────────────────────────────────────
def test_exact_frames_are_not_decoded_in_audio_only():
    """Ровно от этой работы пользователь и уходит, включая режим."""
    st = _stub()
    st._audio_only_mode = True
    st.video_widget = None
    EditTab._show_exact_frame(st, 1050)       # не должно упасть и ничего не ждёт


def test_clock_follows_player_in_audio_only():
    """Часы кадра застыли бы на последнем показанном — ведём время по плееру."""
    st = _stub(pos=42_000)
    st._audio_only_mode = True
    assert EditTab._clock_pos_s(st) == pytest.approx(42.0)


def test_placeholder_prefers_real_audio_file_message():
    """У настоящего аудиофайла причина другая — и текст должен быть про неё."""
    st = _stub(has_video=False)
    st._audio_only_mode = True
    EditTab._update_audio_only_placeholder(st)
    assert "аудиофайл" in st.messages[-1]


# ── Новый файл ──────────────────────────────────────────────────────────────
def test_mode_is_reapplied_when_media_loads():
    """Дорожки известны только у загруженного медиа, поэтому режим доводится до
    плеера в on_media_status_changed — иначе у нового файла видео возвращалось."""
    st = _stub()
    st._audio_only_mode = True
    st._pending_pb_seek = None
    st.waveform = SimpleNamespace(set_playhead=lambda *a: None)
    st.lbl_current_time = SimpleNamespace(setText=lambda *a: None)
    EditTab.on_media_status_changed(st, edit_tab.QMediaPlayer.MediaStatus.LoadedMedia)
    assert st.player.track_calls == [-1]
