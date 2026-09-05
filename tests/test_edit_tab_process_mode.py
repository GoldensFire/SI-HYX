# -*- coding: utf-8 -*-
"""Режим обрезки «Перекодировать настройками «Обработки»» (пункт 4 cmb_mode).

start_cut обязан уводить этот режим в _execute_cut_and_process (один проход
ProcessWorker текущими настройками вкладки «Обработка»), а при включённых
эффектах Монтажа (вшивание субтитров / кадрирование / пикселизация), которых тот
путь не знает, — спрашивать, а не выкидывать их молча.
"""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab


def _stub(tmp_path, mode=4, **over):
    """Минимальный «self» для start_cut: только то, что читает её путь до
    выбора режима."""
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
        cmb_sub_style=SimpleNamespace(currentIndex=lambda: 0),
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


def test_mode_4_goes_to_processing_settings(tmp_path):
    st, calls = _stub(tmp_path)
    EditTab.start_cut(st)
    assert calls['cut'] == []
    assert len(calls['process']) == 1
    (in_s, out_s), _ = calls['process'][0]
    assert (round(in_s, 3), round(out_s, 3)) == (1.0, 5.0)


def test_mode_4_with_crop_asks_and_falls_back(tmp_path, monkeypatch):
    """Ответ «Нет» — обычная перекодировка средствами Монтажа (mode 1) со всеми
    эффектами, а не тихая потеря кадрирования."""
    st, calls = _stub(tmp_path, _video_crop_filter=lambda: "crop=100:100:0:0")
    asked = []
    monkeypatch.setattr(edit_tab, "msgbox_question",
                        lambda *a, **k: (asked.append(a[2]),
                                         edit_tab.QMessageBox.StandardButton.No)[1])
    EditTab.start_cut(st)
    assert asked and "кадрирование" in asked[0]
    assert calls['process'] == []
    assert len(calls['cut']) == 1 and calls['cut'][0][0][2] == 1


def test_mode_4_with_pixelize_continues_on_yes(tmp_path, monkeypatch):
    st, calls = _stub(tmp_path, _pixelize_active=True)
    asked = []
    monkeypatch.setattr(edit_tab, "msgbox_question",
                        lambda *a, **k: (asked.append(a[2]),
                                         edit_tab.QMessageBox.StandardButton.Yes)[1])
    EditTab.start_cut(st)
    assert asked and "пикселизация" in asked[0]
    assert len(calls['process']) == 1 and calls['cut'] == []


def test_other_modes_untouched(tmp_path):
    """Обычная перекодировка (1) по-прежнему идёт своим путём."""
    st, calls = _stub(tmp_path, mode=1)
    EditTab.start_cut(st)
    assert calls['process'] == []
    assert len(calls['cut']) == 1 and calls['cut'][0][0][2] == 1
