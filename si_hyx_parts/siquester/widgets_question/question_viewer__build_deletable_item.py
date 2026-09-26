# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: _build_deletable_item. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


def _build_deletable_item(self, it: dict, item_idx: int, param_name: str) -> _api.QWidget | None:
    """Wrap item with drag handle. Delete/simultaneous buttons float inside the content widget."""
    siq = self.siq; viewer = self
    _rnd = self._current_rnd; _th = self._current_th; _price = self._current_price
    _pidx = item_idx; _pname = param_name

    # ── Shared save-text function for inline editors ──────────
    def _save_text_xml(new_text):
        try:
            qs = siq.rounds[_rnd]["themes"][_th]["questions"]
            q_idx_s = _api._q_idx(qs, _price)
            param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == _pname]
            if _pidx < len(param_items):
                param_items[_pidx]["text"] = new_text
            root_xml, ns_url, tag, q_el = _api._xml_nav_q(siq, _rnd, _th, q_idx_s)
            total = 0; done = False
            for p in q_el.findall(f'{tag("params")}/{tag("param")}'):
                if done: break
                if p.get("name") == _pname:
                    for iel in p.findall(tag("item")):
                        if total == _pidx:
                            iel.text = new_text; done = True; break
                        total += 1
            if done:
                siq._save_xml(root_xml, ns_url)
        except Exception as e:
            _api._logger.warning(f"[save_inline_text] {e}")

    # ── Build inner widget ────────────────────────────────────
    is_text   = (it.get("type") == "text" and not it.get("is_ref"))
    is_replic = (it.get("placement") == "replic")
    # "Join to next" is stored as waitForFinish='False' in SIQ5
    # placement='background' = background audio (different concept, always simultaneous)
    wait_for_finish = it.get("wait_for_finish", "True")
    is_join_next = (wait_for_finish.lower() == "false")
    is_simul  = bool(it.get("simultaneous"))  # kept for simul_btn state
    # Badge only for user-toggled join-to-next, not for background-placement items
    is_simul_media = (is_join_next and not is_text
                      and it.get("placement","") != "background"
                      and param_name != 'background')
    _drag_source = None

    if is_replic:
        # Oral text: 💬 icon + italic text
        row = _api.QWidget(); row.setStyleSheet(_api._SS_TRANSPARENT)
        rl = _api.QHBoxLayout(row); rl.setContentsMargins(0,2,0,2); rl.setSpacing(6)
        icon_lbl = _api.QLabel("💬"); icon_lbl.setStyleSheet("font-size:13px;background:transparent;")
        rl.addWidget(icon_lbl, 0, _api._AlignVC)
        te = _api._InlineTextEdit(
            it["text"],
            "background:transparent;color:#b4befe;font-style:italic;font-size:12px;"
            "border:none;padding:0;",
            "background:rgba(137,180,250,0.10);color:#b4befe;font-style:italic;font-size:12px;"
            "border:1px solid #89b4fa;border-radius:3px;padding:2px;")
        te.save_done.connect(_save_text_xml)
        rl.addWidget(te, 1)
        if is_join_next:
            frame = _api.QFrame()
            frame.setStyleSheet(
                "QFrame{background:rgba(137,180,250,0.07);border-left:3px solid #89b4fa;"
                "border-radius:0px 4px 4px 0px;}")
            fl = _api.QHBoxLayout(frame); fl.setContentsMargins(6,4,6,4); fl.setSpacing(0)
            fl.addWidget(row)
            inner = frame
        else:
            inner = row
        _drag_source = te
    elif is_simul_media:
        # Join-to-next media: blue left border + tinted background wrapping the player
        try:
            raw_inner = self._build_item(it)
        except Exception as e:
            _api._logger.warning(f"[build_simul_media] {e}")
            raw_inner = None
        if raw_inner is None:
            return None
        frame = _api.QFrame()
        frame.setStyleSheet(
            _api._ITEM_JOIN_SS)
        fl = _api.QVBoxLayout(frame); fl.setContentsMargins(6, 4, 6, 4); fl.setSpacing(0)
        fl.addWidget(raw_inner)
        if hasattr(raw_inner, 'block_drag'):
            _drag_source = raw_inner
        inner = frame
    elif is_join_next and is_text:
        frame = _api.QFrame()
        frame.setStyleSheet(
            _api._ITEM_JOIN_SS)
        fl = _api.QHBoxLayout(frame); fl.setContentsMargins(8,4,4,4); fl.setSpacing(6)
        te = _api._InlineTextEdit(
            it["text"],
            "background:transparent;color:#cdd6f4;font-size:13px;border:none;padding:1px;",
            "background:#1e1e2e;color:#cdd6f4;font-size:13px;"
            "border:1px solid #89b4fa;border-radius:4px;padding:3px;")
        te.save_done.connect(_save_text_xml)
        fl.addWidget(te, 1)
        inner = frame; _drag_source = te
    elif is_text:
        te = _api._InlineTextEdit(
            it["text"],
            "background:transparent;color:#cdd6f4;font-size:13px;border:none;padding:1px;",
            "background:#1e1e2e;color:#cdd6f4;font-size:13px;"
            "border:1px solid #89b4fa;border-radius:4px;padding:3px;")
        te.save_done.connect(_save_text_xml)
        inner = te
        _drag_source = te
    else:
        inner = self._build_item(it)
        if inner is None:
            return None

    # ── Outer container: drag handle left, content fills the rest ──
    outer = _api.QWidget(); outer.setStyleSheet(_api._SS_TRANSPARENT)
    outer.setAcceptDrops(False)
    ol = _api.QHBoxLayout(outer); ol.setContentsMargins(0, 0, 0, 0); ol.setSpacing(2)

    # ── Shared start-drag helper ──────────────────────────────
    def _start_drag(source_w=None):
        mime = _api.QMimeData()
        mime.setData(_api._MIME_BLOCK,
                     _api.QByteArray(f"{_pname}:{_pidx}".encode()))
        d = _api.QDrag(source_w or outer); d.setMimeData(mime)
        raw = outer.grab()
        ghost = _api.QPixmap(raw.size()); ghost.fill(_api.Qt.GlobalColor.transparent)
        p = _api.QPainter(ghost); p.setOpacity(0.55); p.drawPixmap(0, 0, raw); p.end()
        d.setPixmap(ghost)
        d.setHotSpot(raw.rect().center())
        outer.setVisible(False)
        d.exec(_api.Qt.DropAction.MoveAction)
        try: outer.setVisible(True)
        except RuntimeError: pass

    # ── Drag handle ──────────────────────────────────────────
    drag_btn = _api.QPushButton("⠿")
    drag_btn.setFixedSize(14, 22)
    drag_btn.setCursor(_api.Qt.CursorShape.SizeAllCursor)
    drag_btn.setToolTip("Перетащить в другой раздел")
    drag_btn.setStyleSheet(_api._DH_SS_HIDDEN)

    def _dh_press(ev, h=drag_btn):
        if ev.button() == _api.Qt.MouseButton.LeftButton:
            h._drag_origin = ev.position().toPoint()
    def _dh_move(ev, h=drag_btn):
        if not getattr(h, '_drag_origin', None): return
        if (ev.position().toPoint() - h._drag_origin).manhattanLength() < 4: return
        h._drag_origin = None; _start_drag(h)
    drag_btn.mousePressEvent = _dh_press
    drag_btn.mouseMoveEvent  = _dh_move

    if _drag_source is not None and hasattr(_drag_source, 'block_drag'):
        _drag_source.block_drag.connect(lambda: _start_drag(_drag_source))

    if it.get("type") == "image" and it.get("is_ref") and inner is not None:
        inner.setCursor(_api.Qt.CursorShape.OpenHandCursor)
        def _img_press(ev, w=inner):
            if ev.button() == _api.Qt.MouseButton.LeftButton:
                w._img_drag_orig = ev.position().toPoint()
        def _img_move(ev, w=inner):
            orig = getattr(w, '_img_drag_orig', None)
            if not orig: return
            if (ev.position().toPoint() - orig).manhattanLength() > 8:
                w._img_drag_orig = None; _start_drag(w)
        inner.mousePressEvent = _img_press
        inner.mouseMoveEvent  = _img_move

    if it.get("type") in ("audio", "video") and it.get("is_ref") and inner is not None:
        if hasattr(inner, 'block_drag'):
            inner.block_drag.connect(lambda: _start_drag(inner))

    ol.addWidget(drag_btn, 0, _api._AlignVC)
    ol.addWidget(inner, stretch=1)

    # ── Overlay buttons — NO layout contribution, float via resizeEvent ──
    is_simul = is_join_next   # for overlay button state
    simul_btn = _api.QPushButton("⇥")
    simul_btn.setFixedSize(20, 20); simul_btn.setCheckable(True)
    simul_btn.setChecked(is_simul)
    simul_btn.setToolTip("Присоединить к следующему (проигрывать одновременно)")
    # _SB_OFF / _SB_ON / _SB_HOV defined at module level
    simul_btn.setStyleSheet(_api._SB_ON if is_simul else _api._SB_OFF)

    def _toggle_simul(checked, btn=simul_btn, rnd=_rnd, th=_th, price=_price,
                      pidx=_pidx, pname=_pname):
        btn.setStyleSheet(_api._SB_ON if checked else _api._SB_OFF)
        try:
            qs = siq.rounds[rnd]["themes"][th]["questions"]
            q_idx_s = _api._q_idx(qs, price)
            param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == pname]
            if pidx < len(param_items):
                param_items[pidx]["simultaneous"] = checked
                param_items[pidx]["wait_for_finish"] = "False" if checked else "True"
            root_xml, ns_url, tag, q_el = siq._xml_nav_q(rnd, th, q_idx_s)
            total = 0; done = False
            for p in q_el.findall(f'{tag("params")}/{tag("param")}'):
                if done: break
                if p.get("name") == pname:
                    for iel in p.findall(tag("item")):
                        if total == pidx:
                            if checked:
                                iel.set("waitForFinish", "False")
                            else:
                                # Remove waitForFinish attr (defaults to True when absent)
                                if "waitForFinish" in iel.attrib:
                                    del iel.attrib["waitForFinish"]
                            done = True; break
                        total += 1
            if done:
                siq._save_xml(root_xml, ns_url)
                # Refresh viewer so indicator appears/disappears immediately
                q_ref = siq.find_question(rnd, th, price)
                if q_ref: viewer.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
        except Exception as e:
            _api._logger.warning(f"[toggle_simul] {e}")
    simul_btn.toggled.connect(_toggle_simul)

    del_btn = _api.QPushButton("✕")
    del_btn.setFixedSize(20, 20)
    del_btn.setToolTip("Удалить блок")
    del_btn.setStyleSheet(_api._DEL_SS_HIDDEN)

    # Oral-text button styles (defined here so hover callbacks can reference them)
    # _RB_OFF / _RB_HOV / _RB_ACTIVE defined at module level
    rnd, th, price = _rnd, _th, _price
    def _delete(_, rnd=rnd, th=th, price=price, idx=_pidx, pname=_pname, it_ref=it):
        try:
            qs = siq.rounds[rnd]["themes"][th]["questions"]
            q_idx = _api._q_idx(qs, price)
            q_obj_local = qs[q_idx]
            param_items = [i for i in q_obj_local["items"] if i["param"] == pname]
            deleted_item = param_items[idx] if idx < len(param_items) else None
            if deleted_item:
                q_obj_local["items"].remove(deleted_item)
            root_xml, ns_url, tag, q_el = _api._xml_nav_q(siq, rnd, th, q_idx)
            param_count = 0; removed = False
            for p in q_el.findall(f'{tag("params")}/{tag("param")}'):
                if p.get("name") == pname:
                    items_els = p.findall(tag("item"))
                    if param_count + len(items_els) > idx and not removed:
                        local_idx = idx - param_count
                        if 0 <= local_idx < len(items_els):
                            p.remove(items_els[local_idx]); removed = True
                    param_count += len(items_els)

            # Remove media file from zip if this was a ref item
            if deleted_item and deleted_item.get("is_ref") and deleted_item.get("text"):
                fname = deleted_item["text"]
                # Use the already-built _media_map first (O(1)).
                # Fall back to folder-prefix search only when not found there.
                zip_key = siq._media_map.get(fname) or siq._media_map.get(
                    _api._unquote(fname))
                if zip_key is None and siq._zip:
                    # _media_map miss — do a single namelist() call and scan it.
                    _nl = set(siq._zip.namelist())
                    for folder in ("Images/", "Audio/", "Video/"):
                        for candidate in (folder + fname,
                                          folder + _api._unquote(fname)):
                            if candidate in _nl:
                                zip_key = candidate
                                break
                        if zip_key:
                            break
                if zip_key:
                    # Repack zip without that file
                    tmp = siq.path + ".edit_tmp"
                    new_xml_bytes = siq._xml_to_bytes(root_xml, ns_url)
                    if siq._zip is not None:
                        siq._zip.close(); siq._zip = None
                    with _api.zipfile.ZipFile(siq.path, 'r') as zin:
                        with _api.zipfile.ZipFile(tmp, 'w') as zout:
                            for info in zin.infolist():
                                if info.filename == zip_key:
                                    continue   # skip deleted file
                                elif info.filename == 'content.xml':
                                    xi = _api.zipfile.ZipInfo('content.xml')
                                    xi.compress_type = _api.zipfile.ZIP_DEFLATED
                                    zout.writestr(xi, new_xml_bytes)
                                else:
                                    with zin.open(info) as src, zout.open(info, 'w') as dst:
                                        _api._shutil.copyfileobj(src, dst, length=1 << 20)
                    _api._safe_replace(tmp, siq.path)
                    siq._zip = _api.zipfile.ZipFile(siq.path, 'r')
                    siq._xml_cache = None   # invalidate XML cache after repack
                    siq._zip_sizes = {i.filename: i.file_size for i in siq._zip.infolist()}
                    siq._media_map.pop(zip_key, None)
                    siq._media_map.pop(fname, None)
                else:
                    siq._save_xml(root_xml, ns_url)
            else:
                siq._save_xml(root_xml, ns_url)

            q_ref = siq.find_question(rnd, th, price)
            if q_ref: viewer.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
        except Exception as e:
            _api._logger.warning(f"[delete_item] {e}")
    del_btn.clicked.connect(_delete)

    # ── "Oral text" toggle (for all text items - both normal and replic) ──
    replic_btn = None
    if is_text or is_replic:
        replic_btn = _api.QPushButton("💬")
        replic_btn.setFixedSize(20, 20)
        # _RB_ACTIVE / _RB_OFF defined at module level
        tip = "Отключить устный текст" if is_replic else "Сделать устным текстом"
        replic_btn.setToolTip(tip)
        replic_btn.setStyleSheet(_api._RB_ACTIVE if is_replic else _api._RB_OFF)

        def _toggle_replic(_, rnd=_rnd, th=_th, price=_price, pidx=_pidx, pname=_pname):
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx_s = _api._q_idx(qs, price)
                param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == pname]
                if pidx >= len(param_items): return
                cur_placement = param_items[pidx].get("placement", "")
                new_placement = "replic" if cur_placement != "replic" else ""
                param_items[pidx]["placement"] = new_placement
                root_xml, ns_url, tag, q_el = _api._xml_nav_q(siq, rnd, th, q_idx_s)
                total = 0; done = False
                for p in q_el.findall(f'{tag("params")}/{tag("param")}'):
                    if done: break
                    if p.get("name") == pname:
                        for iel in p.findall(tag("item")):
                            if total == pidx:
                                if new_placement:
                                    iel.set("placement", new_placement)
                                elif "placement" in iel.attrib:
                                    del iel.attrib["placement"]
                                done = True; break
                            total += 1
                if done:
                    siq._save_xml(root_xml, ns_url)
                    q_ref = siq.find_question(rnd, th, price)
                    if q_ref: viewer.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
            except Exception as e:
                _api._logger.warning(f"[toggle_replic] {e}")
        replic_btn.clicked.connect(_toggle_replic)

    # ── Timer button ─────────────────────────────────────────
    # _TB_OFF / _TB_HOV / _TB_ON defined at module level
    existing_dur = it.get("xml_duration","")
    _tb_secs = 0
    if existing_dur:
        try:
            _p = existing_dur.strip().split(":")
            _tb_secs = int(_p[0])*3600 + int(_p[1])*60 + int(_p[2]) if len(_p)==3 else int(_p[0])*60 + int(_p[1])
        except Exception: pass
    _tb_label = f"⏱ {_tb_secs}с" if _tb_secs > 0 else "⏱"
    timer_btn = _api.QPushButton(_tb_label)
    timer_btn.setFixedHeight(20)
    timer_btn.setFixedWidth(56)
    timer_btn.setToolTip("Кликни для ввода таймера (секунды, 0 = убрать)")
    timer_btn.setStyleSheet(_api._TB_ON if existing_dur else _api._TB_OFF)

    def _apply_timer_secs(secs, rnd=_rnd, th=_th, price=_price, pidx=_pidx, pname=_pname,
                          btn=timer_btn):
        new_dur = f"00:{secs//60:02d}:{secs%60:02d}" if secs > 0 else ""
        btn.setText(f"⏱ {secs}с" if secs > 0 else "⏱")
        btn.setStyleSheet(_api._TB_ON if secs > 0 else _api._TB_OFF)
        btn.setVisible(True)
        try:
            qs = siq.rounds[rnd]["themes"][th]["questions"]
            q_idx_s = _api._q_idx(qs, price)
            param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == pname]
            if pidx < len(param_items):
                param_items[pidx]["xml_duration"] = new_dur
            root_xml, ns_url, tag, q_el = _api._xml_nav_q(siq, rnd, th, q_idx_s)
            total = 0; done = False
            for p in q_el.findall(f'{tag("params")}/{tag("param")}'):
                if done: break
                if p.get("name") == pname:
                    for iel in p.findall(tag("item")):
                        if total == pidx:
                            if new_dur:
                                iel.set("duration", new_dur)
                            elif "duration" in iel.attrib:
                                del iel.attrib["duration"]
                            done = True; break
                        total += 1
            if done:
                siq._save_xml(root_xml, ns_url)
                q_ref = siq.find_question(rnd, th, price)
                if q_ref: viewer.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
        except Exception as e:
            _api._logger.warning(f"[set_timer] {e}")

    def _set_timer(_, btn=timer_btn, cur_secs=_tb_secs, outer_w=outer):
        # Inline editing: show QLineEdit over the button, no popup
        le = _api.QLineEdit(str(cur_secs) if cur_secs > 0 else "0", outer_w)
        le.setAlignment(_api._AlignC)
        le.setStyleSheet(
            "QLineEdit{background:#181825;color:#cba6f7;border:1px solid #cba6f7;"
            "border-radius:3px;font-size:10px;padding:0 2px;}"
        )
        le.setGeometry(btn.geometry())
        le.show(); le.setFocus(); le.selectAll()
        btn.setVisible(False)

        def _commit():
            try:
                secs = max(0, min(7200, int(le.text().strip())))
            except ValueError:
                secs = cur_secs
            le.hide(); le.deleteLater()
            _apply_timer_secs(secs)

        le.returnPressed.connect(_commit)
        le.editingFinished.connect(_commit)

    timer_btn.clicked.connect(_set_timer)

    # Parent buttons to outer — they float with no layout contribution
    simul_btn.setParent(outer); del_btn.setParent(outer)
    if replic_btn: replic_btn.setParent(outer)
    timer_btn.setParent(outer)
    # Start hidden
    simul_btn.setVisible(is_simul)   # only show if already active
    del_btn.setVisible(False)
    if replic_btn:
        replic_btn.setVisible(is_replic)   # always visible if already replic
    timer_btn.setVisible(bool(existing_dur))   # visible if timer already set

    def _outer_resize(ev, db=del_btn, sb=simul_btn, dh=drag_btn, rb=replic_btn, tb=timer_btn):
        w = ev.size().width()
        # Layout from right: ✕(22) ⇥(22) 💬(22) ⏱(56) with 2px gaps
        db.move(w - 23, 2); db.raise_()           # delete
        sb.move(w - 47, 2); sb.raise_()           # simul ⇥
        if rb: rb.move(w - 71, 2); rb.raise_()    # replic 💬
        tb.move(w - 129, 2); tb.raise_()          # timer ⏱ (56px wide)
    outer.resizeEvent = _outer_resize

    # ── Hover tracking via event filter on outer AND inner ────
    def _on_enter(db=del_btn, dh=drag_btn, sb=simul_btn, rb=replic_btn, tb=timer_btn):
        db.setVisible(True); db.setStyleSheet(_api._DEL_SS_SHOWN)
        dh.setStyleSheet(_api._DH_SS_SHOWN)
        sb.setVisible(True)
        sb.setStyleSheet(_api._SB_ON if sb.isChecked() else _api._SB_HOV)
        if rb:
            rb.setVisible(True)
            rb.setStyleSheet(_api._RB_ACTIVE if is_replic else _api._RB_HOV)
        tb.setVisible(True)
        tb.setStyleSheet(_api._TB_ON if bool(existing_dur) else _api._TB_HOV)
    def _on_leave(db=del_btn, dh=drag_btn, sb=simul_btn, rb=replic_btn, tb=timer_btn):
        db.setVisible(False); db.setStyleSheet(_api._DEL_SS_HIDDEN)
        dh.setStyleSheet(_api._DH_SS_HIDDEN)
        sb.setVisible(sb.isChecked())
        sb.setStyleSheet(_api._SB_ON if sb.isChecked() else _api._SB_OFF)
        if rb:
            rb.setVisible(is_replic)
            rb.setStyleSheet(_api._RB_ACTIVE if is_replic else _api._RB_OFF)
        tb.setVisible(bool(existing_dur))
        tb.setStyleSheet(_api._TB_ON if bool(existing_dur) else _api._TB_OFF)

    hf = _api._HoverFilter(outer, _on_enter, _on_leave)
    outer.installEventFilter(hf)
    inner.installEventFilter(hf)
    # Install on direct children of inner only (not all descendants).
    # This catches Enter events when the cursor enters a media player child,
    # without the O(n_descendants) cost of installEventFilter on every widget.
    for _child in inner.children():
        if isinstance(_child, _api.QWidget):
            _child.installEventFilter(hf)

    return outer
