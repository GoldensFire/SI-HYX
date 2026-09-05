# -*- coding: utf-8 -*-
"""Наложенные картинки в режиме «Перекодировать настройками «Обработки»».

Раньше этот путь (ProcessWorker одним проходом) о накладках не знал и молча
предлагал обрезать без них. Теперь PNG слоёв уезжают в элемент очереди
(item['overlays']) и вшиваются тем же кодированием — ровно перед фильтрами
«Обработки» (crop чёрных полос / scale / fade), как накладка видна в плеере.

Проверяем всю цепочку:
  • start_cut со слоями больше не спрашивает — уходит прямо в «Обработку»;
  • …но спрашивает, когда «Обработка» видео НЕ перекодирует (там `-c:v copy`,
    фильтров нет) и в аудио-режиме (видеоряда нет вовсе);
  • _execute_cut_and_process кладёт PNG и формат в элемент очереди;
  • process_media собирает из них -vf, ставя накладку ПЕРЕД своей цепочкой.
"""
import os
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab


class _Sig:
    def connect(self, *a, **k): pass
    def disconnect(self, *a, **k): pass


# ── start_cut: спрашивать или нет ────────────────────────────────────────────
def _stub(tmp_path, mode=4, overlays=True, encodes_video=True):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    calls = {'process': [], 'cut': []}
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
        _process_tab_encodes_video=lambda: encodes_video,
        _subs_present_in_range=lambda *a: True,
        main=None,
        log_label=SimpleNamespace(setText=lambda *a: None,
                                  setStyleSheet=lambda *a: None),
    )
    st._execute_cut = lambda *a, **k: calls['cut'].append((a, k))
    st._execute_cut_and_process = lambda *a, **k: calls['process'].append((a, k))
    return st, calls


def test_overlays_go_to_processing_without_question(tmp_path, monkeypatch):
    """Накладки этот режим теперь умеет — лишнего диалога быть не должно."""
    asked = []
    monkeypatch.setattr(edit_tab, "msgbox_question",
                        lambda *a, **k: asked.append(a) or
                        edit_tab.QMessageBox.StandardButton.No)
    st, calls = _stub(tmp_path)
    EditTab.start_cut(st)
    assert asked == []
    assert calls['cut'] == []
    assert len(calls['process']) == 1


def test_overlays_ask_when_processing_copies_video(tmp_path, monkeypatch):
    """«Перекодировать видео» в «Обработке» выключено → там `-c:v copy`, и
    накладку вшивать нечем: честно спрашиваем, а не теряем слой молча."""
    asked = []
    monkeypatch.setattr(edit_tab, "msgbox_question",
                        lambda *a, **k: asked.append(a) or
                        edit_tab.QMessageBox.StandardButton.No)
    st, calls = _stub(tmp_path, encodes_video=False)
    EditTab.start_cut(st)
    assert len(asked) == 1
    assert "наложенные картинки" in asked[0][2]
    # «Нет» — уходим на обычную перекодировку Монтажа (она слой вшивает).
    assert calls['process'] == [] and calls['cut'] and calls['cut'][0][0][2] == 1


def test_audio_mode_reports_overlays_as_lost(tmp_path, monkeypatch):
    """В аудио-режиме видеоряда нет — накладки честно попадают в лог потерь."""
    monkeypatch.setattr(edit_tab, "icon_html", lambda *a, **k: "")
    logged = []
    st, calls = _stub(tmp_path, mode=5)
    st.main = SimpleNamespace(log=lambda m: logged.append(m))
    EditTab.start_cut(st)
    assert len(calls['process']) == 1
    assert logged and "наложенные картинки" in logged[0]


# ── _execute_cut_and_process: PNG в элементе очереди ─────────────────────────
def _run_cut_and_process(tmp_path, *, audio_only=False, rendered=None):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"src")
    sent = {}

    def _start(items):
        sent['item'] = dict(items[0])

    tm = SimpleNamespace(worker=None, _run_items=_start)
    st = SimpleNamespace(
        actual_source_file=src, export_dir=str(tmp_path),
        main=SimpleNamespace(tab_media=tm),
        chk_overwrite=SimpleNamespace(isChecked=lambda: False),
        selected_audio_abs_index=None, _audio_streams=[],
        _cut_ticker=SimpleNamespace(start=lambda: None, stop=lambda: None),
        _report_progress=lambda *a, **k: None,
        log_label=SimpleNamespace(setText=lambda *a: None),
        _set_cut_status=lambda *a, **k: None,
        _set_cut_btn_cancel=lambda *a, **k: None,
        _cancel_cut_and_process=lambda *a: None,
        on_ffmpeg_finished=lambda ok, msg: None,
        _render_export_overlays=lambda: list(rendered or []),
        _overlay_pix_fmt=lambda s=None: "yuv420p10",
    )
    EditTab._execute_cut_and_process(st, 1.0, 5.0, audio_only=audio_only)
    return sent.get('item', {})


def test_item_carries_overlays_and_format(tmp_path):
    item = _run_cut_and_process(tmp_path, rendered=[("a.png", 10, 20)])
    assert item['overlays'] == [("a.png", 10, 20)]
    assert item['overlay_format'] == "yuv420p10"


def test_item_without_overlays_has_no_key(tmp_path):
    assert 'overlays' not in _run_cut_and_process(tmp_path, rendered=[])


def test_audio_only_item_never_carries_overlays(tmp_path):
    item = _run_cut_and_process(tmp_path, audio_only=True,
                                rendered=[("a.png", 1, 2)])
    assert 'overlays' not in item


# ── process_media: накладка попадает в -vf ───────────────────────────────────
workers = pytest.importorskip("workers")
ProcessWorker = workers.ProcessWorker


def _video_worker(tmp_path, monkeypatch, settings):
    cmds = []

    def _run(cmd, est, cb, label=None, eta_calc=None, cancel_check=None):
        cmds.append(list(cmd))
        with open(cmd[-1], "wb") as f:
            f.write(b"\0" * 16)
        return 0

    monkeypatch.setattr(workers, "get_video_codec", lambda p: "h264")
    monkeypatch.setattr(workers, "get_video_codec_label", lambda p: "H.264")
    monkeypatch.setattr(workers, "get_media_info",
                        lambda p: (4.0, "1000 kbps", 30.0, "128 kbps", "opus"))
    monkeypatch.setattr(workers, "get_fps_float", lambda p: 30.0)
    monkeypatch.setattr(workers, "human_size", lambda n: f"{n} B")
    monkeypatch.setattr(workers, "fmt_bitrate_with_codec", lambda c, b: f"{c} {b}")
    # ffprobe в тестах не зовём: цвет/альфа/оценка к проверяемому графу
    # отношения не имеют.
    monkeypatch.setattr(ProcessWorker, "_bt709_color_args", staticmethod(lambda p: []))
    monkeypatch.setattr(ProcessWorker, "_source_has_alpha", staticmethod(lambda p: False))

    sig = SimpleNamespace(emit=lambda *a: None)
    st = SimpleNamespace(
        settings=settings, stop_flag=False, removed_ids=set(), svt_available=True,
        log=sig, update_item_sig=sig, update_lufs_sig=sig, update_dur_sig=sig,
        measure_loudness=lambda *a, **k: -14.0,
        get_target_bitrate_str=lambda path, sel: "128k",
        run_ffmpeg_capture=_run,
        _out_dir_for=lambda p: str(tmp_path),
        _resolve_crf=lambda item, sv, crf, *a: crf,
        _estimate_total_frames=lambda *a, **k: 0,
        _detect_crop=lambda *a, **k: None,
    )
    # __get__ на атрибуте КЛАССА даёт для обычного метода связанный с нашим
    # «self» вызов, а для staticmethod — просто функцию: одна строка на оба вида.
    for name in ('_sanitize_name', '_out_suffix', '_af_arg', '_map_av_args',
                 '_build_audio_filters', '_trim_seek_args', '_fps_args',
                 '_build_video_filters', '_overlay_vf', '_av1_encoder_args',
                 '_choose_pix_fmt', '_source_has_alpha', '_bt709_color_args',
                 '_wants_metric_score', '_make_metric_sample', '_scale_vf'):
        setattr(st, name, ProcessWorker.__dict__[name].__get__(st, ProcessWorker))
    return st, cmds


def _vf_of(tmp_path, monkeypatch, item_extra, settings=None):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\0" * 32)
    settings = settings or {'video': {'enabled': True, 'crf': 40}, 'audio': {}}
    st, cmds = _video_worker(tmp_path, monkeypatch, settings)
    item = {'iid': 'i1', 'path': str(src), 'type': 'MEDIA', 'dur': 4.0,
            'is_done': False, 'trim': (1.0, 5.0), 'audio_index': None}
    item.update(item_extra)
    ProcessWorker.process_media(st, item, lambda *a, **k: None)
    cmd = cmds[-1]
    return cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None


def test_process_media_burns_overlays(tmp_path, monkeypatch):
    vf = _vf_of(tmp_path, monkeypatch,
                {'overlays': [("ovl.png", 7, 9)], 'overlay_format': "yuv420"})
    assert "movie='ovl.png'" in vf
    assert "overlay=x=7:y=9" in vf
    assert "format=auto" not in vf


def test_process_media_overlay_precedes_own_filters(tmp_path, monkeypatch):
    """Координаты накладки посчитаны в пикселях ИСХОДНОГО кадра — значит scale
    «Обработки» обязан идти уже ПОСЛЕ overlay, иначе слой уедет."""
    settings = {'video': {'enabled': True, 'crf': 40, 'res': '720p'}, 'audio': {}}
    vf = _vf_of(tmp_path, monkeypatch,
                {'overlays': [("ovl.png", 0, 0)], 'overlay_format': "yuv420"},
                settings)
    assert "scale=" in vf
    assert vf.index("overlay=") < vf.index("scale=")


def test_process_media_without_overlays_keeps_plain_chain(tmp_path, monkeypatch):
    """Обычная «Обработка» (не из Монтажа) остаётся без графа накладок."""
    settings = {'video': {'enabled': True, 'crf': 40, 'res': '720p'}, 'audio': {}}
    vf = _vf_of(tmp_path, monkeypatch, {}, settings)
    assert vf is not None and "movie=" not in vf and ";" not in vf
