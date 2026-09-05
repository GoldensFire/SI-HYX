# -*- coding: utf-8 -*-
"""Режим обрезки «(Аудио) Перекодировать настройками «Обработки»» (пункт 5).

Два звена одной цепочки:
  • start_cut уводит режим 5 в _execute_cut_and_process(audio_only=True) и НЕ
    задаёт вопрос про эффекты картинки (видеоряда на выходе нет по определению);
  • ProcessWorker.process_media с item['audio_only'] гонит источник аудио-онли
    веткой: `-vn`, libopus, расширение .opus, обрезка на месте — даже когда в
    файле есть видео.
"""
import os
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab


# ── start_cut: маршрутизация режима ──────────────────────────────────────────
def _stub(tmp_path, mode=5, **over):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    calls = {'process': [], 'cut': []}
    st = SimpleNamespace(
        actual_source_file=src,
        ffmpeg_thread=None,
        is_still_image=False,
        current_in=1.0, current_out=5.0,
        duration=30.0,
        in_time_edit=SimpleNamespace(text=lambda: edit_tab.s_to_time(1.0)),
        out_time_edit=SimpleNamespace(text=lambda: edit_tab.s_to_time(5.0)),
        video_stream_index=None, fps=None,
        has_track_preview=lambda: False,
        cmb_mode=SimpleNamespace(currentIndex=lambda: mode),
        chk_burn_subs=SimpleNamespace(isChecked=lambda: False),
        cmb_subs=SimpleNamespace(currentIndex=lambda: 0),
        selected_sub_ext_path=None,
        _pixelize_active=False,
        _video_crop_filter=lambda: None,
        has_image_overlays=lambda: False,
        _subs_present_in_range=lambda *a: True,
        main=None,
        log_label=SimpleNamespace(setText=lambda *a: None,
                                  setStyleSheet=lambda *a: None),
    )
    st._execute_cut_and_process = lambda *a, **k: calls['process'].append((a, k))
    st._execute_cut = lambda *a, **k: calls['cut'].append((a, k))
    st._execute_smartcut = lambda *a, **k: calls.setdefault('smart', []).append(a)
    for k, v in over.items():
        setattr(st, k, v)
    return st, calls


def test_mode_5_goes_to_processing_settings_audio_only(tmp_path):
    st, calls = _stub(tmp_path)
    EditTab.start_cut(st)
    assert calls['cut'] == []
    assert len(calls['process']) == 1
    (in_s, out_s), kw = calls['process'][0]
    assert (round(in_s, 3), round(out_s, 3)) == (1.0, 5.0)
    assert kw.get('audio_only') is True


def test_mode_4_stays_video(tmp_path):
    """Соседний режим не должен внезапно стать аудио-онли."""
    st, calls = _stub(tmp_path, mode=4)
    EditTab.start_cut(st)
    assert len(calls['process']) == 1
    assert calls['process'][0][1].get('audio_only') is False


def test_mode_5_with_pixelize_does_not_ask(tmp_path, monkeypatch):
    """Эффекты картинки в аудио-режиме неприменимы по определению — диалога нет,
    экспорт идёт сразу (а не откатывается на перекодировку Монтажа)."""
    asked = []
    monkeypatch.setattr(edit_tab, "msgbox_question",
                        lambda *a, **k: asked.append(a) or
                        edit_tab.QMessageBox.StandardButton.No)
    # icon_html рисует значок в пиксмап — без QApplication это падение процесса,
    # а сам значок к проверяемой логике отношения не имеет.
    monkeypatch.setattr(edit_tab, "icon_html", lambda *a, **k: "")
    logged = []
    st, calls = _stub(tmp_path, _pixelize_active=True,
                      main=SimpleNamespace(log=lambda m: logged.append(m)))
    EditTab.start_cut(st)
    assert asked == []
    assert calls['cut'] == []
    assert len(calls['process']) == 1 and calls['process'][0][1]['audio_only'] is True
    assert logged and "пикселизация" in logged[0]


# ── process_media: аудио-онли ветка ──────────────────────────────────────────
workers = pytest.importorskip("workers")
ProcessWorker = workers.ProcessWorker


def _worker_stub(tmp_path, monkeypatch, settings=None, vcodec="h264"):
    """«self» для ProcessWorker.process_media: чистые хелперы настоящие, всё
    внешнее (ffmpeg/ffprobe/сигналы) — заглушки. Возвращает (stub, cmds)."""
    cmds = []

    def _run(cmd, est, cb, label=None, eta_calc=None, cancel_check=None):
        cmds.append(list(cmd))
        out = cmd[-1]                      # последний аргумент ffmpeg — выход
        with open(out, "wb") as f:
            f.write(b"\0" * 16)
        return 0

    monkeypatch.setattr(workers, "get_video_codec", lambda p: vcodec)
    monkeypatch.setattr(workers, "get_video_codec_label", lambda p: "H.264")
    monkeypatch.setattr(workers, "get_media_info",
                        lambda p: (4.0, "1000 kbps", 30.0, "128 kbps", "opus"))
    monkeypatch.setattr(workers, "human_size", lambda n: f"{n} B")
    monkeypatch.setattr(workers, "fmt_bitrate_with_codec", lambda c, b: f"{c} {b}")

    sig = SimpleNamespace(emit=lambda *a: None)
    st = SimpleNamespace(
        settings=settings or {'video': {}, 'audio': {}},
        stop_flag=False, removed_ids=set(), svt_available=True,
        log=sig, update_item_sig=sig, update_lufs_sig=sig, update_dur_sig=sig,
        measure_loudness=lambda *a, **k: -14.0,
        get_target_bitrate_str=lambda path, sel: "128k",
        run_ffmpeg_capture=_run,
        _out_dir_for=lambda p: str(tmp_path),
    )
    for name in ('_sanitize_name', '_out_suffix', '_af_arg', '_map_av_args',
                 '_build_audio_filters', '_trim_seek_args', '_fps_args',
                 '_source_has_alpha', '_choose_pix_fmt'):
        setattr(st, name, getattr(ProcessWorker, name))
    return st, cmds


def _run_media(tmp_path, monkeypatch, item_extra, settings=None, vcodec="h264"):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\0" * 32)
    st, cmds = _worker_stub(tmp_path, monkeypatch, settings, vcodec)
    item = {'iid': 'i1', 'path': str(src), 'type': 'MEDIA', 'dur': 4.0,
            'is_done': False, 'trim': (1.0, 5.0), 'audio_index': None}
    item.update(item_extra)
    out = ProcessWorker.process_media(st, item, lambda *a, **k: None)
    return out, cmds


def test_audio_only_item_produces_opus_without_video(tmp_path, monkeypatch):
    out, cmds = _run_media(tmp_path, monkeypatch, {'audio_only': True})
    assert out.endswith(".opus"), out
    assert len(cmds) == 1
    cmd = cmds[0]
    assert "-vn" in cmd                      # видеоряд отброшен
    assert "libopus" in cmd and "-b:a" in cmd
    assert "-c:v" not in cmd                 # видео не кодируется и не копируется
    # Обрезка на месте: диапазон [1,5) режется тем же проходом.
    assert "-t" in cmd and cmd[cmd.index("-t") + 1].startswith("4.0")


def test_audio_only_keeps_selected_track_and_loudnorm(tmp_path, monkeypatch):
    """Выбранная в Монтаже дорожка и настройки звука «Обработки» доезжают
    до ffmpeg и в аудио-режиме."""
    settings = {'video': {}, 'audio': {'norm': True, 'bitrate': '192'}}
    out, cmds = _run_media(tmp_path, monkeypatch,
                           {'audio_only': True, 'audio_index': 3}, settings)
    cmd = cmds[0]
    assert "0:3" in cmd
    af = cmd[cmd.index("-af") + 1]
    assert "loudnorm" in af
    assert out.endswith("_norm.opus"), out    # суффикс применённых настроек


def test_video_item_untouched_by_audio_flag(tmp_path, monkeypatch):
    """Без флага источник с видео остаётся видео: .mp4 и копия видеопотока
    (перекодирование видео в настройках выключено)."""
    settings = {'video': {'enabled': False}, 'audio': {}}
    out, cmds = _run_media(tmp_path, monkeypatch, {}, settings)
    assert out.endswith(".mp4"), out
    cmd = cmds[0]
    assert "-vn" not in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"


def test_audio_only_on_audio_source_still_works(tmp_path, monkeypatch):
    """Файл вообще без видео (vcodec=None) — путь тот же, флаг ничего не ломает."""
    out, cmds = _run_media(tmp_path, monkeypatch, {'audio_only': True}, vcodec=None)
    assert out.endswith(".opus")
    assert "-vn" in cmds[0]


# ── путь результата: его отдаёт process_media, а не угадайка по настройкам ────
def _process_item_stub(tmp_path, monkeypatch, produced, item, settings=None):
    """«self» для ProcessWorker._process_item: считаем только то, что попало в
    item['out_path'] после успешной обработки."""
    import threading
    sig = SimpleNamespace(emit=lambda *a: None)
    st = SimpleNamespace(
        stop_flag=False, removed_ids=set(), queue=[item],
        settings=settings or {'video': {}, 'audio': {}},
        status=sig, progress=sig, log=sig, global_progress=sig,
        _prog_lock=threading.Lock(), _done_count=0,
        _inc_active=lambda w=1: None, _dec_active=lambda w=1: None,
        _fmt_eta=lambda frac, start: "0с",
        _fmt_eta_rate=lambda frac, t, f: "0с",
        process_media=lambda it, cb: produced,
        _out_dir_for=lambda p: str(tmp_path),
    )
    st._total_now = lambda: 1
    st._guess_out_path = lambda it, p: ProcessWorker._guess_out_path(st, it, p)
    return st


def test_out_path_comes_from_process_media(tmp_path, monkeypatch):
    """Аудио-режим Монтажа: угадайка искала бы «clip_crf35_speed100.mp4», а на
    диске лежит .opus. Раньше промах = пустой out_path, и Монтаж честно ругался
    «Обработка не создала результат», хотя файл был на месте."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\0" * 32)
    produced = str(tmp_path / "clip_norm_fade.opus")
    open(produced, "wb").write(b"\0" * 16)
    item = {'iid': 'i1', 'path': str(src), 'type': 'MEDIA', 'dur': 4.0,
            'is_done': False, 'audio_only': True}
    st = _process_item_stub(tmp_path, monkeypatch, produced, item)
    ProcessWorker._process_item(st, item, True, 0.0)
    assert item['is_done'] is True
    assert item.get('out_path') == produced


def test_guess_out_path_knows_audio_only(tmp_path, monkeypatch):
    """Страховка-угадайка тоже больше не ждёт .mp4 в аудио-режиме."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\0" * 32)
    guessed = tmp_path / "clip_norm.opus"
    guessed.write_bytes(b"\0" * 16)
    monkeypatch.setattr(workers, "get_video_codec", lambda p: "h264")
    item = {'iid': 'i1', 'path': str(src), 'audio_only': True}
    st = SimpleNamespace(settings={'video': {'crf': 35, 'speed': 100},
                                   'audio': {'norm': True}},
                         _out_dir_for=lambda p: str(tmp_path),
                         _sanitize_name=ProcessWorker._sanitize_name)
    ProcessWorker._guess_out_path(st, item, str(src))
    assert item.get('out_path') == str(guessed)
