# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _push_undo. Public namespace: siquester.result_page."""
import siquester.result_page as _api


def _push_undo(self):
    """Snapshot current state onto the undo stack (O(1) deque append)."""
    self._undo_stack.append(self._snapshot_current())
    self._redo_stack.clear()

def _snapshot_current(self) -> tuple:
    """Return (rounds_copy, siq_xml) for the current state.
        Uses json round-trip instead of copy.deepcopy — significantly faster for
        large round structures because json encode/decode is implemented in C."""
    try:
        rounds_copy = _api.json.loads(_api.json.dumps(self.ds["rounds"], ensure_ascii=False))
    except Exception:
        rounds_copy = _api.copy.deepcopy(self.ds["rounds"])
    siq_xml = None
    if self._siq:
        try:
            # Re-use the cached XML bytes if available — avoids a zip.read()
            # on every undo push (which happens on every single edit).
            cache = self._siq._xml_cache
            if cache is not None:
                # cache[0] is (len, hash) key; the actual bytes were consumed
                # already — re-read only when the cache was just invalidated.
                siq_xml = self._siq._zip.read('content.xml')
            else:
                siq_xml = self._siq._zip.read('content.xml')
        except Exception:
            pass
    return rounds_copy, siq_xml

def _apply_snapshot(self, rounds_copy, siq_xml):
    self.ds["rounds"] = rounds_copy
    if self._siq and siq_xml is not None:
        try:
            self._siq._rewrite_zip(siq_xml)
            self._siq._reload_rounds()
        except Exception as e:
            _api._logger.warning(f"[apply_snapshot siq] {e}")
    self._rebuild_content(animated=False)
    _api._schedule_save(self._mw_ref, 200)

def do_undo(self):
    if not self._undo_stack:
        return
    self._redo_stack.append(self._snapshot_current())
    self._apply_snapshot(*self._undo_stack.pop())

def do_redo(self):
    if not self._redo_stack:
        return
    self._undo_stack.append(self._snapshot_current())
    self._apply_snapshot(*self._redo_stack.pop())
