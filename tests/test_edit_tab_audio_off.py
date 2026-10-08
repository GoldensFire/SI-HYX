# -*- coding: utf-8 -*-
"""Пункт «Нет» в списке аудиодорожек Монтажа: превью молчит, экспорт без звука."""
from types import SimpleNamespace

import pytest

edit_tab = pytest.importorskip("edit_tab")
from si_hyx_parts.edit_tab import tracks as audio_off  # noqa: E402
from si_hyx_parts.edit_tab_workers.smart_cut_worker import SmartCutWorker  # noqa: E402


def test_drop_audio_puts_an_right_before_output():
    cmd = ["ffmpeg", "-i", "a.mkv", "-c:a", "copy", "out.mkv"]
    assert audio_off.drop_audio(cmd, "out.mkv")[-2:] == ["-an", "out.mkv"]
    # Чужой последний аргумент — команду не трогаем.
    assert audio_off.drop_audio(cmd, "other.mkv") == cmd


class _Combo:
    def __init__(self):
        self.items = []

    def addItem(self, *args):
        self.items.append(args[-1])

    def insertItem(self, at, *args):
        self.items.insert(at, args[-1])


class _Player:
    def __init__(self):
        self.output = "out"

    def setAudioOutput(self, output):
        self.output = output


def test_none_entry_mutes_preview_and_comes_back(qapp):
    tab = SimpleNamespace(_audio_entries=[('emb', 0)], cmb_audio=_Combo(),
                          player=_Player(), audio_output="out")
    audio_off.EditTabTracksMixin._add_audio_off_entry(tab)
    assert tab.cmb_audio.items[-1] == audio_off.AUDIO_OFF_LABEL
    assert tab._audio_entries[-1] == ('none', None)
    # Внешняя озвучка встаёт перед «Нет».
    assert audio_off.EditTabTracksMixin._external_audio_insert_at(tab) == 1
    audio_off.EditTabTracksMixin._set_audio_disabled(tab, True)
    assert tab.player.output is None
    audio_off.EditTabTracksMixin._set_audio_disabled(tab, False)
    assert tab.player.output == "out"


def test_no_entry_without_any_audio():
    tab = SimpleNamespace(_audio_entries=[], cmb_audio=_Combo())
    audio_off.EditTabTracksMixin._add_audio_off_entry(tab)
    assert tab.cmb_audio.items == []


def test_smart_cut_without_audio(monkeypatch):
    worker = SmartCutWorker("in.mp4", 1.0, 3.0, "out.mp4", ["-c:v", "libx264"],
                            audio_index=2, no_audio=True)
    ran = []
    monkeypatch.setattr(worker, "_run", lambda cmd: ran.append(cmd) or 0)
    assert worker._encode_audio(2.0, "a.m4a") is False
    worker._full_reencode("out.mp4")
    cmd = ran[-1]
    assert "-an" in cmd and "0:2" not in cmd
