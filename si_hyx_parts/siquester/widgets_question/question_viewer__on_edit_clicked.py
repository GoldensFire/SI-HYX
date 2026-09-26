# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: _on_edit_clicked. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


def _on_edit_clicked(self):
    self.edit_requested.emit(self._current_rnd, self._current_th, self._current_price)

def _detect_section(self, global_pos) -> str:
    """Return 'question' or 'answer' based on where the interaction landed.
        Uses Y midpoint of the separator between sections as threshold."""
    # Try precise per-widget hit test first
    for section, widget in [("answer", self._a_inner), ("question", self._q_inner)]:
        tl = widget.mapToGlobal(widget.rect().topLeft())
        br = widget.mapToGlobal(widget.rect().bottomRight())
        if _api.QRect(tl, br).contains(global_pos):
            return section
    # Fallback: use vertical midpoint between question header bottom and answer header top
    try:
        q_bot = self._q_inner.mapToGlobal(self._q_inner.rect().bottomLeft()).y()
        a_top = self._a_inner.mapToGlobal(self._a_inner.rect().topLeft()).y()
        mid = (q_bot + a_top) // 2
        if global_pos.y() >= mid:
            return "answer"
    except Exception:
        pass
    return "question"

# ── Right-click: add item to question or answer ─────────────
def contextMenuEvent(self, ev):
    if not self._current_price:
        return
    # ev.globalPos() gives correct global coords from QContextMenuEvent
    gp = ev.globalPos()
    section = self._detect_section(gp)
    section_label = "ответ" if section == "answer" else "вопрос"
    menu = _api.QMenu(self)
    menu.addAction(f"📝  Добавить текст ({section_label})").setData(("add_text", section))
    menu.addAction(f"🗣  Добавить устный текст ({section_label})").setData(("add_oral", section))
    menu.addSeparator()
    menu.addAction(f"🖼  Добавить медиафайл ({section_label})").setData(("add_media", section))
    chosen = menu.exec(ev.globalPos())
    if not chosen or not chosen.data(): return
    action, param_name = chosen.data()
    rnd, th, price = self._current_rnd, self._current_th, self._current_price
    try:
        qs = self.siq.rounds[rnd]["themes"][th]["questions"]
        q_idx = _api._q_idx(qs, price)
    except (StopIteration, Exception):
        return
    if action == "add_text":
        text, ok = _api.QInputDialog.getMultiLineText(self, f"Добавить текст ({section_label})",
                                                 "Введите текст:")
        if ok and text.strip():
            self._add_text_item(rnd, th, q_idx, text.strip(), param_name)
    elif action == "add_oral":
        text, ok = _api.QInputDialog.getMultiLineText(self, f"Устный текст ({section_label})",
                                                 "Введите текст, который зачитывает ведущий:")
        if ok and text.strip():
            self._add_text_item(rnd, th, q_idx, text.strip(), param_name, placement="replic")
    elif action == "add_media":
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выберите медиафайл", "",
            "Медиафайлы (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.avif *.mp3 *.ogg *.wav *.aac *.flac *.m4a *.mp4 *.avi *.mkv *.mov *.wmv *.webm);;Все файлы (*)")
        if path:
            self._do_add_media(rnd, th, q_idx, path, param_name=param_name)

def _add_text_item(self, rnd, th, q_idx, text, param_name, placement=""):
    # Push undo snapshot onto the parent ResultPage before modifying
    rp = self.parent()
    while rp and not hasattr(rp, '_push_undo'):
        rp = rp.parent()
    if rp and hasattr(rp, '_push_undo'):
        rp._push_undo()
    try:
        root_xml, ns_url, tag, q_el = _api._xml_nav_q(self.siq, rnd, th, q_idx)
        params_el = q_el.find(tag("params"))
        if params_el is None:
            params_el = _api.ET.SubElement(q_el, tag("params"))
        p = None
        for pp in params_el.findall(tag("param")):
            if pp.get("name") == param_name:
                p = pp; break
        if p is None:
            p = _api.ET.SubElement(params_el, tag("param"))
            p.set("name", param_name); p.set("type", "content")
        it = _api.ET.SubElement(p, tag("item"))
        it.text = text
        if placement:
            it.set("placement", placement)
        self.siq._save_xml(root_xml, ns_url)
        # Update in-memory
        self.siq.rounds[rnd]["themes"][th]["questions"][q_idx]["items"].append(
            {"param": param_name, "type": "text", "text": text,
             "is_ref": False, "dur": len(text)/20*60/60+2,
             "placement": placement, "simultaneous": False})
        # Refresh viewer
        q_obj = self.siq.find_question(rnd, th, self._current_price)
        if q_obj: self.show_question(q_obj, rnd_idx=rnd, theme_idx=th)
    except Exception as e:
        _api._logger.warning(f"[add_text_item] {e}")
        _api.msgbox_warning(self, "Ошибка", str(e))

def _do_add_media(self, rnd, th, q_idx, path, param_name="question"):
    # Push undo snapshot onto the parent ResultPage before modifying
    rp = self.parent()
    while rp and not hasattr(rp, '_push_undo'):
        rp = rp.parent()
    if rp and hasattr(rp, '_push_undo'):
        rp._push_undo()
    ok = self.siq.add_media_to_question(rnd, th, q_idx, path, param_name=param_name)
    if ok:
        q_obj = self.siq.find_question(rnd, th, self._current_price)
        if q_obj: self.show_question(q_obj, rnd_idx=rnd, theme_idx=th)
    else:
        _api.msgbox_warning(self, "Ошибка", "Не удалось добавить медиафайл.")

# ── Drag-drop media files onto the viewer ───────────────────
def dragEnterEvent(self, ev):
    md = ev.mimeData()
    if md.hasFormat(_api._MIME_BLOCK) and self._current_price:
        ev.acceptProposedAction()
        self._highlight_section(self.mapToGlobal(ev.position().toPoint()))
        return
    if md.hasUrls() and self._current_price:
        urls = md.urls()
        if any(_api.Path(u.toLocalFile()).suffix.lower() in _api._MEDIA_EXTS for u in urls):
            ev.acceptProposedAction()

def dragMoveEvent(self, ev):
    if ev.mimeData().hasFormat(_api._MIME_BLOCK) and self._current_price:
        ev.acceptProposedAction()
        self._highlight_section(self.mapToGlobal(ev.position().toPoint()))

def dragLeaveEvent(self, ev):
    self._clear_section_highlights()

def _highlight_section(self, global_pos):
    """Highlight target drop zone (question or answer) during drag-over."""
    section = self._detect_section(global_pos)
    hl_style  = "background:rgba(137,180,250,0.10);border:1px solid #89b4fa;border-radius:4px;"
    off_style = "background:#181825;"
    if section == "answer":
        self._q_inner.setStyleSheet(off_style)
        self._a_inner.setStyleSheet(hl_style)
    else:
        self._q_inner.setStyleSheet(hl_style)
        self._a_inner.setStyleSheet(off_style)

def _clear_section_highlights(self):
    self._q_inner.setStyleSheet("background:#181825;border:none;")
    self._a_inner.setStyleSheet("background:#181825;border:none;")

def dropEvent(self, ev):
    md = ev.mimeData()
    global_drop = self.mapToGlobal(ev.position().toPoint())

    # ── Block (item) drag: move between question/answer ──────
    if md.hasFormat(_api._MIME_BLOCK) and self._current_price:
        self._clear_section_highlights()
        raw = bytes(md.data(_api._MIME_BLOCK)).decode()
        src_param, idx_str = raw.split(":", 1)
        item_idx = int(idx_str)
        dst_section = self._detect_section(global_drop)
        dst_param = "answer" if dst_section == "answer" else "question"
        if src_param != dst_param:
            self._move_item_to_section(item_idx, src_param, dst_param)
        ev.acceptProposedAction(); return

    # ── File drop ─────────────────────────────────────────────
    if not md.hasUrls() or not self._current_price: return
    rnd, th, price = self._current_rnd, self._current_th, self._current_price
    # If dropped directly on the answer inner widget, always use "answer"
    drop_pos = ev.position().toPoint()
    a_local = self._a_inner.mapFromGlobal(self.mapToGlobal(drop_pos))
    if self._a_inner.rect().contains(a_local):
        param_name = "answer"
    else:
        section = self._detect_section(self.mapToGlobal(drop_pos))
        param_name = "answer" if section == "answer" else "question"
    try:
        qs = self.siq.rounds[rnd]["themes"][th]["questions"]
        q_idx = _api._q_idx(qs, price)
    except (StopIteration, Exception):
        return
    for url in md.urls():
        path = url.toLocalFile()
        if _api.Path(path).suffix.lower() in _api._MEDIA_EXTS:
            self._do_add_media(rnd, th, q_idx, path, param_name=param_name)
    ev.acceptProposedAction()

def _move_item_to_section(self, item_idx: int, src_param: str, dst_param: str):
    """Move an item from src_param (question/answer) to dst_param."""
    rnd, th, price = self._current_rnd, self._current_th, self._current_price
    try:
        qs = self.siq.rounds[rnd]["themes"][th]["questions"]
        q_idx = _api._q_idx(qs, price)
        q_obj = qs[q_idx]
        param_items = [it for it in q_obj["items"] if it["param"] == src_param]
        if item_idx >= len(param_items): return
        # Update in-memory param
        param_items[item_idx]["param"] = dst_param
        # Update XML
        root_xml, ns_url, tag, q_el = _api._xml_nav_q(self.siq, rnd, th, q_idx)
        params_el = q_el.find(tag("params"))
        if params_el is None: return
        # Find item in src_param
        src_p = next((p for p in params_el.findall(tag("param"))
                      if p.get("name") == src_param), None)
        if src_p is None: return
        items_in_src = src_p.findall(tag("item"))
        if item_idx >= len(items_in_src): return
        item_el = items_in_src[item_idx]
        src_p.remove(item_el)
        # Find or create dst_param
        dst_p = next((p for p in params_el.findall(tag("param"))
                      if p.get("name") == dst_param), None)
        if dst_p is None:
            dst_p = _api.ET.SubElement(params_el, tag("param"))
            dst_p.set("name", dst_param); dst_p.set("type", "content")
        dst_p.append(item_el)
        self.siq._save_xml(root_xml, ns_url)
        q_ref = self.siq.find_question(rnd, th, price)
        if q_ref: self.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
    except Exception as e:
        _api._logger.warning(f"[move_item_to_section] {e}")

def _stop_player(self):
    """Stop all media players. MPV stop is async to avoid blocking the UI."""
    for mw in self._media_widgets:
        try: mw.stop()
        except Exception: pass
    self._media_widgets.clear()

def _clear_lay(self, lay: _api.QVBoxLayout):
    """Remove all widgets from layout. Hide immediately to kill artifacts, then defer deletion."""
    to_delete = []
    while lay.count() > 0:
        item = lay.takeAt(0)
        w = item.widget()
        if not w: continue
        w.hide()
        stop = getattr(w, 'stop', None)
        if stop is not None:
            try: stop()
            except Exception as _e: _api._logger.debug(str(_e))
        to_delete.append(w)
    for w in to_delete:
        w.setParent(None)
        _api.QTimer.singleShot(0, w.deleteLater)
