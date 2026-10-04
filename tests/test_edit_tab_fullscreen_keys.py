# -*- coding: utf-8 -*-
"""Клавиши монтажа одинаковы во вкладке, полном экране и окне панели."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtTest import QTest

import edit_tab


class _Edit(edit_tab.EditTab):
    """Настоящие обработчики/сочетания Qt без запуска медиаплеера и потоков."""

    def resizeEvent(self, event): edit_tab.QWidget.resizeEvent(self, event)
    def showEvent(self, event): edit_tab.QWidget.showEvent(self, event)
    def hideEvent(self, event): edit_tab.QWidget.hideEvent(self, event)
    def closeEvent(self, event): edit_tab.QWidget.closeEvent(self, event)
    def eventFilter(self, obj, event): return edit_tab.QWidget.eventFilter(self, obj, event)

    def __init__(self):
        edit_tab.QWidget.__init__(self)
        self.calls = []
        self.main = SimpleNamespace(log=lambda message: pytest.fail(message))
        self.trim_start_seq = "Shift+C"
        self.trim_end_seq = "Shift+V"
        self._fs_window = None
        self.duration = 60.0
        self.current_in, self.current_out = 0.0, 60.0
        self.vol_slider = edit_tab.QSlider()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.register_shortcuts()

    def toggle_play(self): self.calls.append("play")
    def stop_playback(self): self.calls.append("stop")
    def step_frame_scrub(self, direction): self.calls.append(("step", direction))
    def toggle_fullscreen(self): self.calls.append("fullscreen")
    def exit_fullscreen(self): self.calls.append("exit")
    def set_in_point(self): self.calls.append("in")
    def set_out_point(self): self.calls.append("out")
    def start_cut(self): self.calls.append("cut")
    def undo(self): self.calls.append("undo")
    def redo(self): self.calls.append("redo")
    def save_frame(self): self.calls.append("frame")
    def toggle_mute(self): self.calls.append("mute")
    def seek_to(self, position): self.calls.append(("seek", position))
    def save_settings(self): pass
    def push_undo(self): pass
    def _clock_pos_s(self): return 10.0

    def set_in_out(self, start, end):
        self.current_in, self.current_out = start, end
        self.calls.append(("trim", start, end))


@pytest.fixture
def player(qapp):
    edit = _Edit()
    fs = edit_tab.FullscreenVideo(edit)
    edit._fs_window = fs
    edit.resize(900, 520)
    fs.resize(900, 520)
    edit.show()
    fs.show()
    fs._show_bar()
    yield edit, fs
    edit._fs_window = None
    fs._hide_timer.stop()
    fs.close()
    edit.close()
    fs.deleteLater()
    edit.deleteLater()
    qapp.processEvents()


def _activate(qapp, widget):
    widget.activateWindow()
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    assert widget.hasFocus()


@pytest.mark.parametrize("surface", ["tab", "video", "bar"])
def test_same_keyboard_commands(qapp, player, surface):
    edit, fs = player
    target = {"tab": edit, "video": fs, "bar": fs.bar}[surface]
    _activate(qapp, target)
    for sequence, expected in [
        ("Space", "play"), ("Left", ("step", -1)), ("Right", ("step", 1)),
        ("A", ("step", -1)), ("S", ("step", -1)),
        ("D", ("step", 1)), ("W", ("step", 1)),
        ("F", "fullscreen"), ("I", "in"), ("O", "out"),
        ("Ctrl+S", "cut"), ("Ctrl+Z", "undo"),
        ("Ctrl+Y", "redo"), ("Ctrl+Shift+Z", "redo"),
    ]:
        edit.calls.clear()
        QTest.keySequence(target, QKeySequence(sequence))
        assert edit.calls == [expected], sequence


@pytest.mark.parametrize("surface", ["video", "bar"])
def test_trim_rebinding_and_focus_after_button_click(qapp, player, surface):
    edit, fs = player
    target = fs if surface == "video" else fs.bar
    _activate(qapp, target)
    QTest.mouseClick(fs.btn_stop, Qt.MouseButton.LeftButton)
    # Настройки можно изменить уже после открытия полного экрана.
    edit.set_trim_shortcuts("Ctrl+K", "Ctrl+L", save=False)
    for sequence, expected in [
        ("Ctrl+K", ("trim", 10.0, 60.0)),
        ("Ctrl+L", ("trim", 10.0, 10.04)),
        ("Ctrl+Z", "undo"), ("Right", ("step", 1)),
    ]:
        edit.calls.clear()
        QTest.keySequence(target, QKeySequence(sequence))
        assert edit.calls == [expected], sequence
        assert target.hasFocus()
    edit.calls.clear()
    QTest.keySequence(target, QKeySequence("Shift+C"))
    QTest.keySequence(target, QKeySequence("Shift+V"))
    assert edit.calls == []


@pytest.mark.parametrize("surface", ["video", "bar"])
def test_default_trim_shortcuts(qapp, player, surface):
    edit, fs = player
    target = fs if surface == "video" else fs.bar
    _activate(qapp, target)
    QTest.keySequence(target, QKeySequence("Shift+C"))
    QTest.keySequence(target, QKeySequence("Shift+V"))
    assert edit.calls == [("trim", 10.0, 60.0), ("trim", 10.0, 10.04)]


@pytest.mark.parametrize("surface", ["video", "bar"])
def test_physical_keys_in_russian_layout(qapp, player, surface):
    edit, fs = player
    target = fs if surface == "video" else fs.bar
    _activate(qapp, target)
    for letter, vk, modifiers, expected in [
        ("ф", 0x41, Qt.KeyboardModifier.NoModifier, ("step", -1)),
        ("ц", 0x57, Qt.KeyboardModifier.NoModifier, ("step", 1)),
        ("ш", 0x49, Qt.KeyboardModifier.NoModifier, "in"),
        ("щ", 0x4F, Qt.KeyboardModifier.NoModifier, "out"),
        ("а", 0x46, Qt.KeyboardModifier.NoModifier, "fullscreen"),
        ("ы", 0x53, Qt.KeyboardModifier.ControlModifier, "cut"),
        ("я", 0x5A, Qt.KeyboardModifier.ControlModifier, "undo"),
        ("н", 0x59, Qt.KeyboardModifier.ControlModifier, "redo"),
        ("я", 0x5A, Qt.KeyboardModifier.ControlModifier
         | Qt.KeyboardModifier.ShiftModifier, "redo"),
    ]:
        edit.calls.clear()
        event = QKeyEvent(QEvent.Type.KeyPress, ord(letter.upper()), modifiers,
                          0, vk, 0, letter)
        qapp.sendEvent(target, event)
        assert edit.calls == [expected]
        assert event.isAccepted()


@pytest.mark.parametrize("surface", ["video", "bar"])
def test_modified_f_does_not_exit_and_escape_does(qapp, player, surface):
    edit, fs = player
    target = fs if surface == "video" else fs.bar
    _activate(qapp, target)
    for sequence in ("Ctrl+F", "Alt+F", "Shift+F"):
        QTest.keySequence(target, QKeySequence(sequence))
    assert edit.calls == []
    QTest.keyClick(target, Qt.Key.Key_Escape)
    assert edit.calls == ["exit"]


def test_shortcuts_do_not_intercept_other_windows(qapp, player):
    edit, fs = player
    other = edit_tab.QWidget()
    other.show()
    try:
        _activate(qapp, other)
        for sequence in ("Space", "Left", "Ctrl+Z", "Shift+C"):
            QTest.keySequence(other, QKeySequence(sequence))
        assert edit.calls == []
    finally:
        other.close()
