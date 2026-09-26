# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleCreatorDialog: keyPressEvent. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


def keyPressEvent(self, event):
    if event.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
        try:
            vk = event.nativeVirtualKey()
        except Exception:
            vk = 0
        is_z = vk == self._VK_Z or event.key() == _api.Qt.Key.Key_Z
        is_y = vk == self._VK_Y or event.key() == _api.Qt.Key.Key_Y
        if is_z:
            self.redo() if (event.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier) else self.undo()
            event.accept()
            return
        if is_y:
            self.redo()
            event.accept()
            return
    elif not (event.modifiers() & (_api.Qt.KeyboardModifier.AltModifier
                                    | _api.Qt.KeyboardModifier.ShiftModifier)):
        # WASD покадрового шага (та же логика, что и в основном Монтаже —
        # см. EditTab.keyPressEvent): по физической клавише через
        # nativeVirtualKey, с фолбэком на event.key() для латиницы.
        try:
            vk = event.nativeVirtualKey()
        except Exception:
            vk = 0
        if vk in (self._VK_A, self._VK_S) or event.key() in (_api.Qt.Key.Key_A, _api.Qt.Key.Key_S):
            self.btn_step_back_click()
            event.accept()
            return
        if vk in (self._VK_D, self._VK_W) or event.key() in (_api.Qt.Key.Key_D, _api.Qt.Key.Key_W):
            self.btn_step_fwd_click()
            event.accept()
            return
    super(_api.SubtitleCreatorDialog, self).keyPressEvent(event)

def _snapshot(self):
    return (_api.copy.deepcopy(self._cues), dict(self._default_style))

def _push_undo(self):
    snap = self._snapshot()
    if self._undo_stack and self._undo_stack[-1] == snap:
        return
    self._undo_stack.append(snap)
    self._redo_stack.clear()

def _restore_snapshot(self, snap):
    self._cues, self._default_style = _api.copy.deepcopy(snap[0]), dict(snap[1])
    if self._selected >= len(self._cues):
        self._selected = len(self._cues) - 1
    self._resync_all()

def undo(self):
    if not self._undo_stack:
        return
    self._redo_stack.append(self._snapshot())
    self._restore_snapshot(self._undo_stack.pop())

def redo(self):
    if not self._redo_stack:
        return
    self._undo_stack.append(self._snapshot())
    self._restore_snapshot(self._redo_stack.pop())
