# -*- coding: utf-8 -*-
"""Имя результата режима «Перекодировать настройками «Обработки»».

Два РАЗНЫХ отрезка одного файла с одинаковыми настройками дают одно и то же
имя («clip_обрез_crf45_speed100.mp4»), и галочка «Перезаписать файл» (включена
по умолчанию) молча стирала первый клип вторым. Правило теперь такое же, как у
обычной обрезки: перезапись только для внутреннего пере-реза (out_path) и для
правки «на месте», иначе — «…_обрез_1», «_2», …
"""
import os
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab


class _Sig:
    def connect(self, *a, **k): pass
    def disconnect(self, *a, **k): pass


def _run(tmp_path, *, overwrite=True, out_path=None, loaded=None, temp_name=None):
    """Прогоняет _execute_cut_and_process со стабами и возвращает путь, по
    которому реально лёг результат «Обработки»."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"src")
    temp_out = tmp_path / (temp_name or "clip_crf45_speed100.mp4")
    temp_out.write_bytes(b"result")
    finished = {}

    def _run_items(items):
        items[0]['out_path'] = str(temp_out)
        items[0]['is_done'] = True

    worker = SimpleNamespace(progress=_Sig(), status=_Sig(), finished_all=_Sig(),
                             isRunning=lambda: False)
    tm = SimpleNamespace(worker=None, _run_items=_run_items)

    def _start(items):
        _run_items(items)
        tm.worker = worker

    tm._run_items = _start
    st = SimpleNamespace(
        actual_source_file=(loaded if loaded is not None else src),
        export_dir=str(tmp_path),
        main=SimpleNamespace(tab_media=tm),
        chk_overwrite=SimpleNamespace(isChecked=lambda: overwrite),
        selected_audio_abs_index=None, _audio_streams=[],
        _cut_ticker=SimpleNamespace(start=lambda: None, stop=lambda: None),
        _report_progress=lambda *a, **k: None,
        log_label=SimpleNamespace(setText=lambda *a: None),
        _set_cut_status=lambda *a, **k: None,
        _set_cut_btn_cancel=lambda *a, **k: None,
        _cancel_cut_and_process=lambda *a: None,
        _notify_busy_rename=lambda *a: None,
        _render_export_overlays=lambda: [],
        _overlay_pix_fmt=lambda src=None: "yuv420",
        load_file=lambda p: finished.setdefault('loaded', p),
        on_ffmpeg_finished=lambda ok, msg: finished.update(ok=ok, msg=msg),
    )
    st._replace_tolerant = EditTab._replace_tolerant
    st._move_tolerant = EditTab._move_tolerant

    captured = {}
    worker.finished_all = SimpleNamespace(
        connect=lambda cb: captured.setdefault('cb', cb),
        disconnect=lambda *a: None)

    EditTab._execute_cut_and_process(st, 1.0, 5.0, out_path=out_path, src=src)
    captured['cb']()
    assert finished.get('ok') is True, finished
    return sorted(p.name for p in tmp_path.iterdir())


def test_second_cut_does_not_overwrite_first(tmp_path):
    """Первый клип уже лежит на диске — второй уходит на «…_обрез_1»."""
    (tmp_path / "clip_обрез_crf45_speed100.mp4").write_bytes(b"first")
    names = _run(tmp_path, overwrite=True)
    assert "clip_обрез_crf45_speed100.mp4" in names
    assert "clip_обрез_crf45_speed100_1.mp4" in names
    # первый клип цел
    assert (tmp_path / "clip_обрез_crf45_speed100.mp4").read_bytes() == b"first"


def test_first_cut_takes_plain_name(tmp_path):
    names = _run(tmp_path, overwrite=True)
    assert "clip_обрез_crf45_speed100.mp4" in names


def test_internal_recut_reuses_name(tmp_path):
    """Пере-рез после быстрой обрезки (out_path) законно занимает то же имя."""
    (tmp_path / "clip_обрез_crf45_speed100.mp4").write_bytes(b"rough")
    names = _run(tmp_path, overwrite=True,
                 out_path=str(tmp_path / "clip_обрез.mp4"))
    assert "clip_обрез_crf45_speed100_1.mp4" not in names
    assert (tmp_path / "clip_обрез_crf45_speed100.mp4").read_bytes() == b"result"


def test_in_place_edit_overwrites_loaded_file(tmp_path):
    """Цель == открытый в Монтаже файл: «Перезаписать» работает как раньше."""
    target = tmp_path / "clip_обрез_crf45_speed100.mp4"
    target.write_bytes(b"old")
    names = _run(tmp_path, overwrite=True, loaded=target)
    assert "clip_обрез_crf45_speed100_1.mp4" not in names
    assert target.read_bytes() == b"result"
