# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubtitleCreatorDialog: _style_edit. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


def _style_edit(self, key, value):
    if self._syncing:
        return
    if 0 <= self._selected < len(self._cues):
        cue = self._cues[self._selected]
        if cue.get('style') is None:
            cue['style'] = {}
        cue['style'][key] = value
    else:
        self._default_style[key] = value

def _apply_style_to_all(self):
    self._push_undo()
    style = self._effective_style(self._selected)
    self._default_style = dict(style)
    for c in self._cues:
        c['style'] = dict(style)
    self._refresh_all_style_ui()

def _refresh_all_style_ui(self):
    style = self._effective_style(self._selected)
    self._syncing = True
    try:
        self.cmb_font.setCurrentFont(_api.QFont(style.get('font') or 'Arial'))
        self.spin_size.setValue(int(style.get('size') or 20))
        self.btn_bold.setChecked(bool(style.get('bold')))
        self.btn_italic.setChecked(bool(style.get('italic')))
        self.btn_underline.setChecked(bool(style.get('underline')))
        align = int(style.get('align') or 2)
        col = (align - 1) % 3
        for c, b in self._halign_btns.items():
            b.setChecked(c == col)
        self.spin_spacing.setValue(int(style.get('spacing') or 0))
        for v, b in self._pos_btns.items():
            b.setChecked(v == align)
        self._set_color_swatch(self.btn_color, style.get('color') or '#FFFFFF')
        self._set_color_swatch(self.btn_outline_color,
                               style.get('outline_color') or '#000000')
        anim = style.get('animation') or 'none'
        for i in range(self.list_anim.count()):
            it = self.list_anim.item(i)
            if it.data(_api.Qt.ItemDataRole.UserRole) == anim:
                self.list_anim.setCurrentItem(it)
                break
    finally:
        self._syncing = False

# ── Реплики: добавление/дублирование/удаление/выбор ─────────────────────
def _add_cue(self):
    self._push_undo()
    start = self._cues[-1]['end'] if self._cues else self._start_hint
    self._cues.append({'start': start, 'end': start + 2.0, 'text': '', 'style': None})
    self._resync_all()
    self._select_cue(len(self._cues) - 1)

def _duplicate_cue(self, idx):
    if not (0 <= idx < len(self._cues)):
        return
    self._push_undo()
    src = self._cues[idx]
    dur = max(0.1, src['end'] - src['start'])
    lo = src['end']
    range_end = self._range_end if self._range_end is not None else self.preview.duration_s
    hi = (self._cues[idx + 1]['start'] if idx + 1 < len(self._cues)
          else max(lo + dur, range_end or (lo + dur)))
    new_end = min(hi, lo + dur)
    if new_end <= lo:
        new_end = lo + 0.1
    new_cue = {'start': lo, 'end': new_end, 'text': src['text'],
              'style': dict(src['style']) if src.get('style') else None}
    self._cues.insert(idx + 1, new_cue)
    self._resync_all()
    self._select_cue(idx + 1)

def _delete_cue(self, idx):
    if not (0 <= idx < len(self._cues)):
        return
    self._push_undo()
    del self._cues[idx]
    if self._selected == idx:
        self._selected = -1
    elif self._selected > idx:
        self._selected -= 1
    self._resync_all()

def _select_cue(self, idx):
    if idx == self._selected:
        return
    self._selected = idx
    self.timeline.set_selected(idx)
    if 0 <= idx < len(self._cues):
        self.preview.seek(self._cues[idx]['start'])
    self._refresh_all_style_ui()
    for i in range(self.list_cues.count()):
        item = self.list_cues.item(i)
        if item.data(_api.Qt.ItemDataRole.UserRole) == idx:
            self._syncing = True
            self.list_cues.setCurrentItem(item)
            self._syncing = False
            break

def _resync_all(self):
    self.timeline.set_cues([(c['start'], c['end']) for c in self._cues])
    self.timeline.set_selected(self._selected)
    self._rebuild_list()
    self._refresh_all_style_ui()

def _on_timeline_cue_changed(self, idx, start, end):
    if not (0 <= idx < len(self._cues)):
        return
    self._cues[idx]['start'] = start
    self._cues[idx]['end'] = end
    for i in range(self.list_cues.count()):
        item = self.list_cues.item(i)
        if item.data(_api.Qt.ItemDataRole.UserRole) == idx:
            row_w = self.list_cues.itemWidget(item)
            lbl = row_w.findChild(_api.QLabel)
            if lbl is not None:
                lbl.setText(f"{_api.s_to_time(start)[:8]}\n{_api.s_to_time(end)[:8]}")
            break

def _on_timeline_view_changed(self, offset, visible):
    # Как update_wave_scroll в основном Монтаже: скроллбар СКРЫВАЕТСЯ
    # (не просто disabled), когда прокручивать нечего.
    dur = self.timeline.duration
    if dur <= visible:
        self.tl_scroll.setVisible(False)
        return
    self.tl_scroll.setVisible(True)
    maxv = max(1.0, dur - visible)
    rel_offset = offset - self.timeline.range_start
    self.tl_scroll.blockSignals(True)
    self.tl_scroll.setPageStep(max(1, int(visible / dur * 1000)))
    self.tl_scroll.setValue(int(max(0.0, min(1.0, rel_offset / maxv)) * 1000))
    self.tl_scroll.blockSignals(False)

def _on_tl_scroll_changed(self, v):
    dur = self.timeline.duration
    visible = self.timeline._visible()
    maxv = max(0.0, dur - visible)
    self.timeline.set_view_offset(self.timeline.range_start + v / 1000.0 * maxv)

# ── Превью: активная реплика под плейхедом ──────────────────────────────
def _active_cue_at(self, pos_s):
    for i, c in enumerate(self._cues):
        if c['start'] <= pos_s < c['end']:
            return c['text'], self._effective_style(i)
    return None

# ── Итог ─────────────────────────────────────────────────────────────────
def _on_accept(self):
    if not self.cues():
        _api.msgbox_warning(self, "Субтитры", "Добавьте хотя бы одну реплику с текстом.")
        return
    self.accept()

def last_style(self):
    """Эффективный стиль на момент закрытия — то, что последним стояло в
        тулбаре (стиль выбранной реплики, либо общий стиль по умолчанию, если
        ничего не выбрано). Вызывающая сторона (EditTab.create_subtitles)
        сохраняет это как «последние настройки сабов» для следующего открытия."""
    if 0 <= self._selected < len(self._cues):
        return self._effective_style(self._selected)
    return dict(self._default_style)

def cues(self):
    """Список словарей {start,end,text,style} с уже разрешённым (эффективным)
        стилем — только непустые реплики, start < end. Передаётся в _cues_to_ass."""
    out = []
    for i, c in enumerate(self._cues):
        text = (c.get('text') or '').strip()
        if not text or c['end'] <= c['start']:
            continue
        out.append({'start': c['start'], 'end': c['end'], 'text': text,
                   'style': self._effective_style(i)})
    out.sort(key=lambda c: c['start'])
    return out
