# -*- coding: utf-8 -*-
"""Наложение картинки поверх видео («Монтаж»).

Проверяем то, от чего зависит совпадение предпросмотра и файла:
  • геометрия слоя считается в ДОЛЯХ кадра (прокси-превью ≠ исходник);
  • кадрирование картинки меняет и её пропорции на кадре;
  • граф -vf собирается без спец-меток [in]/[out] и ставит накладку ПЕРЕД
    остальными фильтрами Монтажа;
  • «Обрезать» с активным слоем уходит на перекодировку (copy накладку не умеет).
"""
from types import SimpleNamespace

import pytest

overlay = pytest.importorskip("edit_tab_overlay")
edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab

from PyQt6.QtCore import QRectF          # noqa: E402
from PyQt6.QtGui import QImage           # noqa: E402


def _img(w=100, h=50, qapp=None):
    im = QImage(w, h, QImage.Format.Format_ARGB32)
    im.fill(0xFF3366CC)
    return im


def _ovl(qapp, w=100, h=50, frame=(1920, 1080)):
    return overlay.ImageOverlay("logo.png", _img(w, h), frame[0], frame[1])


# ── геометрия ────────────────────────────────────────────────────────────────
def test_fit_rect_keeps_image_aspect(qapp):
    """Стартовый прямоугольник даёт картинке её собственные пропорции: 100×50 на
    кадре 1920×1080 при ширине 0.28 кадра = 537×269 px (2:1)."""
    r = overlay.fit_rect_norm(100, 50, 1920, 1080, width_frac=0.28)
    px_w = r.width() * 1920
    px_h = r.height() * 1080
    assert px_w / px_h == pytest.approx(2.0, rel=1e-3)


def test_pixel_rect_scales_with_frame(qapp):
    """Одни и те же доли на прокси (960×540) и на исходнике (1920×1080) дают
    пропорционально одинаковое место — иначе накладка «съезжает» в файле."""
    o = _ovl(qapp)
    o.set_rect(QRectF(0.25, 0.5, 0.2, 0.1))
    assert o.pixel_rect(1920, 1080) == (480, 540, 384, 108)
    assert o.pixel_rect(960, 540) == (240, 270, 192, 54)


def test_crop_changes_aspect_on_frame(qapp):
    """Обрезали половину ширины картинки — на кадре она стала вдвое «выше» при
    той же ширине (пропорции идут за обрезкой)."""
    o = _ovl(qapp)
    o.set_rect(QRectF(0.0, 0.0, 0.4, 0.4))
    assert o.set_crop(QRectF(0.0, 0.0, 0.5, 1.0))
    assert o.cropped_size() == (50, 50)
    px_w = o.rect.width() * 1920
    px_h = o.rect.height() * 1080
    assert px_w / px_h == pytest.approx(1.0, rel=1e-3)


def test_crop_rejects_degenerate(qapp):
    o = _ovl(qapp)
    before = QRectF(o.crop)
    assert o.set_crop(QRectF(0.2, 0.2, 0.001, 0.001)) is False
    assert o.crop == before


def test_rendered_applies_crop_scale_and_rotation(qapp):
    o = _ovl(qapp)
    o.set_rect(QRectF(0.1, 0.1, 0.25, 0.25))
    img, x, y = o.rendered(1000, 1000)
    assert (img.width(), img.height()) == (250, 250)
    assert (x, y) == (100, 100)
    o.angle = 90.0
    rimg, rx, ry = o.rendered(1000, 1000)
    # Поворот вокруг ЦЕНТРА: сам центр остаётся на месте.
    assert rx + rimg.width() / 2 == pytest.approx(x + img.width() / 2, abs=1.5)
    assert ry + rimg.height() / 2 == pytest.approx(y + img.height() / 2, abs=1.5)


def test_save_png_has_alpha_from_opacity(qapp, tmp_path):
    o = _ovl(qapp)
    o.opacity = 0.5
    got = o.save_png(tmp_path / "ovl.png", 1000, 1000)
    assert got is not None
    saved = QImage(str(tmp_path / "ovl.png"))
    assert not saved.isNull()
    # Полупрозрачность вжата в альфу самой картинки (ffmpeg получает её готовой).
    assert 100 < saved.pixelColor(1, 1).alpha() < 160


# ── ffmpeg-граф ──────────────────────────────────────────────────────────────
def test_filter_graph_without_overlays_is_untouched():
    assert overlay.overlay_filter_graph("crop=10:10:0:0", []) == "crop=10:10:0:0"
    assert overlay.overlay_filter_graph("", []) == ""


def test_filter_graph_puts_overlay_before_base_chain():
    g = overlay.overlay_filter_graph("crop=100:100:0:0", [("a.png", 5, 7)],
                                     escape_path=lambda p: p)
    parts = g.split(";")
    assert parts[0] == "movie='a.png',format=rgba[sihyxovl0]"
    assert parts[1] == "null[sihyxbase0]"
    assert parts[2].startswith("[sihyxbase0][sihyxovl0]overlay=x=5:y=7")
    assert parts[2].endswith("[sihyxbase1]")
    assert parts[3] == "[sihyxbase1]crop=100:100:0:0"
    # Спец-меток [in]/[out] в графе быть не должно — их поддержка у ffmpeg плавала.
    assert "[in]" not in g and "[out]" not in g


def test_filter_graph_without_base_ends_unlabeled():
    g = overlay.overlay_filter_graph("", [("a.png", 0, 0), ("b.png", 1, 2)],
                                     escape_path=lambda p: p)
    last = g.split(";")[-1]
    assert last.startswith("[sihyxbase1][sihyxovl1]overlay=")
    assert not last.endswith("]")


def test_render_overlays_writes_png_per_layer(qapp, tmp_path):
    items = [_ovl(qapp), _ovl(qapp)]
    got = overlay.render_overlays(items, tmp_path, 640, 360)
    assert len(got) == 2
    assert all(str(tmp_path) in p for p, _x, _y in got)


# ── интеграция со вкладкой ───────────────────────────────────────────────────
def _stub_cut(tmp_path, mode=0, overlays=True):
    """Минимальный «self» для start_cut (см. test_edit_tab_process_mode)."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    calls = {'cut': [], 'smart': []}
    st = SimpleNamespace(
        actual_source_file=src, ffmpeg_thread=None, is_still_image=False,
        current_in=1.0, current_out=5.0, duration=30.0,
        in_time_edit=SimpleNamespace(text=lambda: edit_tab.s_to_time(1.0)),
        out_time_edit=SimpleNamespace(text=lambda: edit_tab.s_to_time(5.0)),
        video_stream_index=0, fps=25.0,
        has_track_preview=lambda: False,
        cmb_mode=SimpleNamespace(currentIndex=lambda: mode),
        chk_burn_subs=SimpleNamespace(isChecked=lambda: False),
        cmb_subs=SimpleNamespace(currentIndex=lambda: 0),
        selected_sub_ext_path=None,
        _pixelize_active=False,
        _video_crop_filter=lambda: None,
        has_image_overlays=lambda: overlays,
        _subs_present_in_range=lambda *a: True,
        main=None,
        log_label=SimpleNamespace(setText=lambda *a: None,
                                  setStyleSheet=lambda *a: None),
    )
    st._execute_cut = lambda *a, **k: calls['cut'].append(a)
    st._execute_smartcut = lambda *a, **k: calls['smart'].append(a)
    return st, calls


def test_start_cut_forces_reencode_with_overlay(tmp_path):
    """«Быстро (без потерь)» + слой картинки = перекодировка: copy накладку не
    умеет, иначе слой молча потерялся бы."""
    st, calls = _stub_cut(tmp_path, mode=0, overlays=True)
    EditTab.start_cut(st)
    assert calls['cut'] and calls['cut'][0][2] == 1


def test_start_cut_keeps_fast_copy_without_overlay(tmp_path):
    st, calls = _stub_cut(tmp_path, mode=0, overlays=False)
    EditTab.start_cut(st)
    assert calls['cut'] and calls['cut'][0][2] == 0


def test_start_cut_smartcut_falls_back_to_reencode(tmp_path):
    """Smart Cut копирует середину — со слоем он неприменим."""
    st, calls = _stub_cut(tmp_path, mode=3, overlays=True)
    EditTab.start_cut(st)
    assert not calls['smart']
    assert calls['cut'] and calls['cut'][0][2] == 1


def _vf_stub(rendered, fmt="yuv420"):
    return SimpleNamespace(_render_export_overlays=lambda: list(rendered),
                           _overlay_pix_fmt=lambda src=None: fmt,
                           _escape_filter_path=EditTab._escape_filter_path)


def test_wrap_vf_without_overlays_returns_chain(tmp_path):
    st = _vf_stub([])
    assert EditTab._wrap_vf(st, "crop=2:2:0:0") == "crop=2:2:0:0"
    assert EditTab._wrap_vf(st, "") == ""


def test_wrap_vf_escapes_windows_path(tmp_path):
    st = _vf_stub([(r"C:\tmp\ovl.png", 1, 2)])
    vf = EditTab._wrap_vf(st, "")
    # Двоеточие диска обязано быть экранировано, иначе фильтр не инициализируется.
    assert "movie='C\\:/tmp/ovl.png'" in vf


# ── Цвет: overlay обязан работать в YUV ──────────────────────────────────────
def test_overlay_never_negotiates_rgb(tmp_path):
    """`format=auto` уводил ВЕСЬ граф в RGB (libx264 писал gbrp) — и цвет видео
    после Монтажа уезжал в кислотно-зелёный. Формат обязан быть явным YUV."""
    vf = EditTab._wrap_vf(_vf_stub([("a.png", 0, 0)]), "crop=2:2:0:0")
    assert "format=auto" not in vf
    assert "overlay=x=0:y=0:eof_action=repeat:format=yuv420" in vf


def test_overlay_format_follows_source_pix_fmt():
    """Формат берётся по исходнику: 10-битное и 4:4:4 видео накладка не роняет."""
    assert overlay.overlay_chroma_format("yuv420p") == "yuv420"
    assert overlay.overlay_chroma_format("yuvj420p") == "yuv420"
    assert overlay.overlay_chroma_format("yuv420p10le") == "yuv420p10"
    assert overlay.overlay_chroma_format("yuv444p10le") == "yuv444p10"
    assert overlay.overlay_chroma_format("yuv422p") == "yuv422"
    # Кадр из картинки (RGB) и неизвестный формат → самый совместимый вариант.
    assert overlay.overlay_chroma_format("rgba") == "yuv420"
    assert overlay.overlay_chroma_format("") == "yuv420"


def test_wrap_vf_passes_deep_format_through(tmp_path):
    vf = EditTab._wrap_vf(_vf_stub([("a.png", 3, 4)], fmt="yuv420p10"), "")
    assert "format=yuv420p10" in vf
