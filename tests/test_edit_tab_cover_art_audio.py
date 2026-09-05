# -*- coding: utf-8 -*-
"""Аудиофайл с ОБЛОЖКОЙ в «Монтаже» и «часы кадра» при смене файла.

Живая жалоба: mp3 (Sabaton, картинка альбома внутри) — жёлтая полоска не
ставится по клику на волне, а стоит в самом конце; «обрезать старт до плейхеда»
уводит зелёную и красную полоски туда же.

Причин было две, и обе проверяются здесь:
  • обложка (attached_pic, mjpeg 1000×1000, r_frame_rate 90000/1) считалась
    видеорядом — отсюда fps 90000, сетка на 20 млн кадров и «часы кадра» у
    файла, у которого кадров нет вовсе (сам QtMultimedia обложку игнорирует);
  • «часы кадра» холста (pts последнего показанного кадра) не сбрасывались при
    загрузке нового файла, а пин, заявленный перемоткой, заставлял интерфейс им
    доверять — время застывало на кадре ПРОШЛОГО файла (обрезаясь по
    длительности нового — то есть ровно «в самый конец»).
"""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
edit_tab_widgets = pytest.importorskip("edit_tab_widgets")
EditTab = edit_tab.EditTab
VideoCanvas = edit_tab_widgets.VideoCanvas


# ── обложка ≠ видеоряд ───────────────────────────────────────────────────────
def _cover_stream(index=1):
    return {'index': index, 'codec_type': 'video', 'codec_name': 'mjpeg',
            'width': 1000, 'height': 1000, 'r_frame_rate': '90000/1',
            'disposition': {'attached_pic': 1}}


def _video_stream(index=0):
    return {'index': index, 'codec_type': 'video', 'codec_name': 'h264',
            'width': 1920, 'height': 1080, 'r_frame_rate': '24000/1001',
            'disposition': {'attached_pic': 0}}


def _audio_stream(index=0):
    return {'index': index, 'codec_type': 'audio', 'codec_name': 'mp3',
            'channels': 2}


def test_is_attached_pic_detects_cover():
    assert edit_tab._is_attached_pic(_cover_stream())
    assert not edit_tab._is_attached_pic(_video_stream())
    assert not edit_tab._is_attached_pic({'codec_type': 'video'})   # без disposition
    assert not edit_tab._is_attached_pic({})


def test_mp3_with_cover_has_no_video_stream():
    """mp3 с картинкой альбома — чистое аудио: видеопоток не выбирается вовсе."""
    vinfo, ainfo = EditTab._pick_av_streams([_audio_stream(0), _cover_stream(1)])
    assert vinfo is None
    assert ainfo is not None and ainfo['index'] == 0


def test_real_video_still_picked_even_with_cover():
    """У видео с обложкой (mkv/mp4 с превью) видеоряд по-прежнему находится."""
    streams = [_cover_stream(0), _video_stream(1), _audio_stream(2)]
    vinfo, ainfo = EditTab._pick_av_streams(streams)
    assert vinfo is not None and vinfo['index'] == 1
    assert ainfo['index'] == 2


def test_cover_fps_never_reaches_frame_grid():
    """Прямая причина «сетки на 20 млн кадров»: fps обложки — 90000."""
    assert EditTab._parse_fps(_cover_stream()) == 90000.0
    vinfo, _ = EditTab._pick_av_streams([_audio_stream(), _cover_stream()])
    assert vinfo is None                      # значит fps остаётся None


# ── часы кадра: пин без картинки им не даёт доверять ─────────────────────────
@pytest.fixture
def canvas(qapp):
    c = VideoCanvas()
    c.resize(320, 180)
    return c


def _frame_img():
    from PyQt6.QtGui import QImage
    img = QImage(8, 8, QImage.Format.Format_RGB888)
    img.fill(0)
    return img


def test_pinned_pts_none_without_image(canvas):
    """Заявка «должен быть кадр N» (перемотка) — не повод считать её временем:
    картинки ещё нет, часы показывают ПРОШЛЫЙ кадр."""
    canvas.set_exact_frame(_frame_img(), (0, 10 ** 12), 350_000_000)
    canvas.arm_frame_pin((115_000_000, 115_100_000))
    assert canvas.last_frame_pts() == 350.0        # часы ещё старые
    assert canvas.has_frame_pin()
    assert canvas.pinned_frame_pts() is None


def test_pinned_pts_returned_when_frame_is_ours(canvas):
    canvas.set_exact_frame(_frame_img(), (115_000_000, 115_100_000), 115_040_000)
    assert canvas.pinned_frame_pts() == pytest.approx(115.04)


def test_pinned_pts_none_when_clock_outside_span(canvas):
    """Часы вне диапазона пина — на экране кадр не наш (смена источника)."""
    canvas.set_exact_frame(_frame_img(), (0, 1_000_000), 350_000_000)
    assert canvas.pinned_frame_pts() is None


def test_clear_frame_resets_frame_clock(canvas):
    """load_file зовёт clear_frame() — часы нового файла не наследуют прошлый."""
    canvas.set_exact_frame(_frame_img(), (0, 10 ** 12), 350_000_000)
    canvas.clear_frame()
    assert canvas.last_frame_pts() is None
    assert not canvas.has_frame_pin()
    assert canvas.pinned_frame_pts() is None


# ── _clock_pos_s: время интерфейса на паузе ──────────────────────────────────
def _stub_tab(canvas, pos_ms):
    from PyQt6.QtMultimedia import QMediaPlayer
    return SimpleNamespace(
        player=SimpleNamespace(
            position=lambda: pos_ms,
            playbackState=lambda: QMediaPlayer.PlaybackState.PausedState),
        video_widget=canvas,
        video_stream_index=0)


def test_clock_falls_back_to_player_when_pin_has_no_frame(canvas):
    """Тот самый баг: после клика по волне плеер УЖЕ на 115 c, а интерфейс брал
    pts кадра прошлого файла (350 c) — полоска улетала в конец волны."""
    canvas.set_exact_frame(_frame_img(), (0, 10 ** 12), 350_000_000)
    canvas.arm_frame_pin((115_000_000, 115_100_000))
    st = _stub_tab(canvas, 115_040)
    assert EditTab._clock_pos_s(st) == pytest.approx(115.04)


def test_clock_uses_frame_when_exact_frame_is_shown(canvas):
    """Когда точный кадр реально на холсте — время ведём по нему (покадровая
    точность, ради которой пин и существует)."""
    canvas.set_exact_frame(_frame_img(), (115_000_000, 115_100_000), 115_040_000)
    st = _stub_tab(canvas, 115_090)        # позиция плеера отличается на доли кадра
    assert EditTab._clock_pos_s(st) == pytest.approx(115.04)
