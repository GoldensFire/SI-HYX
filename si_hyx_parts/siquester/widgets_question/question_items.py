# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Просмотр вопроса: построение элементов вопроса и редактора ответа."""
import siquester.widgets_question as _api


class QuestionViewerItemsMixin:
    """Просмотр вопроса: построение элементов вопроса и редактора ответа."""

    def _rebuild_answer_editor(self, answers: list, wrong_answers: list | None = None):
        """Build draggable/editable correct-answer rows (and wrong-answer rows) at the bottom of _a_lay."""
        # Remove any existing editor widget
        for i in range(self._a_lay.count() - 1, -1, -1):
            it = self._a_lay.itemAt(i)
            if it and it.widget() and getattr(it.widget(), '_is_answer_editor', False):
                w = self._a_lay.takeAt(i).widget()
                w.deleteLater()

        rnd, th, price = self._current_rnd, self._current_th, self._current_price
        siq = self.siq

        editor_w = _api.QWidget(); editor_w.setStyleSheet(_api._SS_TRANSPARENT)
        editor_w._is_answer_editor = True
        evl = _api.QVBoxLayout(editor_w); evl.setContentsMargins(0, 6, 0, 4); evl.setSpacing(2)

        def _build_ans_section(evl_parent, section_label, icon, ans_list_ref, save_fn,
                               label_color, add_label, is_wrong_section=False):
            """Helper: builds a drag/edit answer section and returns the list ref."""
            sep = _api.QFrame(); sep.setFrameShape(_api.QFrame.Shape.HLine)
            sep.setStyleSheet("background:#313244; max-height:1px;")
            evl_parent.addWidget(sep)

            lbl_hdr = _api.QLabel(f"{icon}  {section_label}")
            lbl_hdr.setStyleSheet(f"color:{label_color};font-size:9px;font-weight:700;"
                                  "letter-spacing:1px;padding:4px 0 2px 0;")
            evl_parent.addWidget(lbl_hdr)

            rows_w = _api.QWidget(); rows_w.setStyleSheet(_api._SS_TRANSPARENT)
            rows_vl = _api.QVBoxLayout(rows_w); rows_vl.setContentsMargins(0, 0, 0, 0); rows_vl.setSpacing(3)
            evl_parent.addWidget(rows_w)

            _row_widgets: list = []

            def _add_row(text: str, idx: int):
                row_w = _api.QWidget(); row_w.setStyleSheet(_api._SS_TRANSPARENT)
                row_w._ans_idx = idx
                row_w.setAcceptDrops(True)
                rl = _api.QHBoxLayout(row_w); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(4)

                dh = _api.QPushButton("⠿"); dh.setFixedSize(14, 24)
                dh.setCursor(_api.Qt.CursorShape.SizeAllCursor)
                dh.setStyleSheet(_api._DH_SS_HIDDEN)
                def _dh_press(ev, h=dh): h._drag_origin = ev.position().toPoint() if ev.button() == _api.Qt.MouseButton.LeftButton else None
                def _dh_move(ev, h=dh, rw=row_w):
                    if not getattr(h,'_drag_origin',None): return
                    if (ev.position().toPoint()-h._drag_origin).manhattanLength() < 5: return
                    h._drag_origin = None; _do_row_drag(rw)
                dh.mousePressEvent = _dh_press; dh.mouseMoveEvent = _dh_move

                le = _api._AnsEdit(text)
                _this_idx = idx

                # Media file dropped on this answer row → add as media item to question
                def _on_media_drop(path, viewer=self):
                    if not viewer._current_price: return
                    try:
                        qs = viewer.siq.rounds[viewer._current_rnd]["themes"][viewer._current_th]["questions"]
                        q_idx_m = _api._q_idx(qs, viewer._current_price)
                        viewer._do_add_media(viewer._current_rnd, viewer._current_th, q_idx_m,
                                             path, param_name="answer")
                    except Exception as ex:
                        _api._logger.warning(f"[ans media drop] {ex}")
                le.media_dropped.connect(_on_media_drop)

                def _on_enter(le=le, i=_this_idx):
                    ans_list_ref[i] = le.text(); save_fn()
                    ans_list_ref.insert(i + 1, ""); _refresh_rows()
                    if i + 1 < len(_row_widgets): _row_widgets[i+1][1].setFocus()
                le.enter_pressed.connect(_on_enter)
                le.document().contentsChanged.connect(lambda le=le, i=_this_idx: ans_list_ref.__setitem__(i, le.text()) if i < len(ans_list_ref) else None)
                def _focus_out(e, le=le, i=_this_idx):
                    type(le).focusOutEvent(le, e)
                    if i < len(ans_list_ref): ans_list_ref[i] = le.text(); save_fn()
                le.focusOutEvent = _focus_out
                def _on_backspace(le=le, i=_this_idx):
                    if len(ans_list_ref) > 1:
                        ans_list_ref.pop(i); save_fn(); _refresh_rows()
                        focus_idx = max(0, i - 1)
                        if focus_idx < len(_row_widgets): _row_widgets[focus_idx][1].setFocus()
                le.backspace_empty.connect(_on_backspace)
                def _le_block_drag(rw=row_w): _do_row_drag(rw)
                le.block_drag.connect(_le_block_drag)

                del_b = _api.QPushButton("✕"); del_b.setObjectName(_api._ON_BTN_DEL); del_b.setFixedSize(22, 22)
                def _del_row(_, le=le, i=_this_idx):
                    if len(ans_list_ref) > 1:
                        ans_list_ref.pop(i); save_fn(); _refresh_rows()
                    else:
                        ans_list_ref[0] = ""; le.setText(""); save_fn()
                del_b.clicked.connect(_del_row)

                copy_b = _api.QPushButton("⎘"); copy_b.setFixedSize(22, 22)
                copy_b.setToolTip("Копировать текст ответа")
                copy_b.setStyleSheet("QPushButton{background:transparent;color:#585b70;border:none;"
                                     "font-size:13px;border-radius:3px;padding:0;}"
                                     "QPushButton:hover{color:#cdd6f4;background:rgba(255,255,255,0.06);}")
                def _copy_row(_, le=le, qv=self):
                    txt = le.text()
                    if txt:
                        _api.QApplication.clipboard().setText(txt)
                        orig_ss = le.styleSheet()
                        hl_ss = (orig_ss +
                            "background:rgba(137,180,250,0.20);color:#b4befe;"
                            "border:1px solid #89b4fa;border-radius:3px;")
                        le.setStyleSheet(hl_ss)
                        def _clear_hl(le=le, ss=orig_ss):
                            try: le.setStyleSheet(ss)
                            except RuntimeError: pass
                        qv._copy_hl_clear = _clear_hl
                        mw = _api._find_mw(qv)
                        if mw and hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                            mw._save_notif.setText("📋  Ответ скопирован")
                            mw._show_save_notification()
                            _api._notif_reset(mw)
                copy_b.clicked.connect(_copy_row)

                rl.addWidget(dh); rl.addWidget(le, stretch=1); rl.addWidget(copy_b)

                # Propagate-to-other-questions button (wrong answers section only)
                if is_wrong_section:
                    prop_b = _api.QPushButton("→"); prop_b.setFixedSize(22, 22)
                    prop_b.setToolTip("Скопировать этот неправильный ответ в другие вопросы")
                    prop_b.setStyleSheet("QPushButton{background:transparent;color:#585b70;border:none;"
                                         "font-size:11px;font-weight:700;border-radius:3px;padding:0;}"
                                         "QPushButton:hover{color:#f9e2af;background:rgba(249,226,175,0.10);}")
                    def _propagate_wrong(_, le=le, i=_this_idx, qv=self):
                        txt = le.text().strip()
                        if not txt: return
                        if i < len(ans_list_ref):
                            ans_list_ref[i] = le.text()
                        save_fn()
                        mw = _api._find_mw(qv)
                        datasets = getattr(mw, 'datasets', ())
                        qv._open_propagate_wrong_dialog(txt, datasets)
                    prop_b.clicked.connect(_propagate_wrong)
                    rl.addWidget(prop_b)

                rl.addWidget(del_b)

                def _row_enter(e, h=dh): h.setStyleSheet(_api._DH_SS_SHOWN)
                def _row_leave(e, h=dh): h.setStyleSheet(_api._DH_SS_HIDDEN)
                row_w.enterEvent = _row_enter; row_w.leaveEvent = _row_leave

                def _row_drag_enter(e, rw=row_w):
                    if e.mimeData().hasFormat(_api._MIME_ANS): e.acceptProposedAction()
                def _row_drop(e, rw=row_w):
                    if not e.mimeData().hasFormat(_api._MIME_ANS): return
                    src_i = int(bytes(e.mimeData().data(_api._MIME_ANS)).decode())
                    dst_i = rw._ans_idx
                    if src_i != dst_i:
                        item = ans_list_ref.pop(src_i)
                        ans_list_ref.insert(dst_i, item)
                        save_fn(); _refresh_rows()
                    e.acceptProposedAction()
                row_w.dragEnterEvent = _row_drag_enter; row_w.dropEvent = _row_drop

                rows_vl.addWidget(row_w)
                _row_widgets.append((row_w, le))

            def _do_row_drag(rw: _api.QWidget):
                mime = _api.QMimeData()
                mime.setData(_api._MIME_ANS, _api.QByteArray(str(rw._ans_idx).encode()))
                d = _api.QDrag(rw); d.setMimeData(mime)
                raw = rw.grab(); ghost = _api.QPixmap(raw.size()); ghost.fill(_api.Qt.GlobalColor.transparent)
                p = _api.QPainter(ghost); p.setOpacity(0.55); p.drawPixmap(0, 0, raw); p.end()
                d.setPixmap(ghost); d.setHotSpot(raw.rect().center())
                rw.setVisible(False)
                d.exec(_api.Qt.DropAction.MoveAction)
                try: rw.setVisible(True)
                except RuntimeError: pass

            def _refresh_rows():
                _row_widgets.clear()
                while rows_vl.count():
                    it = rows_vl.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                for i, a in enumerate(ans_list_ref):
                    _add_row(a, i)
                add_b = _api.QPushButton(add_label)
                add_b.setObjectName(_api._ON_BTN_ANALYZE); add_b.setFixedHeight(24)
                def _add_click():
                    ans_list_ref.append(""); save_fn(); _refresh_rows()
                    if _row_widgets: _row_widgets[-1][1].setFocus()
                add_b.clicked.connect(_add_click)
                rows_vl.addWidget(add_b)

            _refresh_rows()

        # ── Right answers section ──────────────────────────────────
        _ans_list = list(answers) if answers else [""]
        if not _ans_list: _ans_list = [""]

        def _save_right():
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx = _api._q_idx(qs, price)
                new_ans = [a for a in _ans_list if a.strip()]
                siq.save_question(rnd, th, q_idx, [], new_ans)
                siq.rounds[rnd]["themes"][th]["questions"][q_idx]["answers"] = new_ans
            except Exception as e:
                _api._logger.warning(f"[save_right] {e}")

        _build_ans_section(evl, "Правильные ответы (редактирование)", "✅",
                           _ans_list, _save_right, "#585b70", "＋ Добавить правильный ответ")

        # ── Transfer answers button ────────────────────────────────
        transfer_btn = _api.QPushButton("→ Перенести ответы в другой вопрос")
        transfer_btn.setObjectName(_api._ON_BTN_SORT)
        transfer_btn.setFixedHeight(24)
        transfer_btn.setToolTip("Скопировать все правильные ответы из этого вопроса в другой")

        def _transfer_answers(_, siq_r=siq, rnd_r=rnd, th_r=th, price_r=price,
                              ans_ref=_ans_list, viewer_r=self):
            # Collect all questions except current one
            choices = []   # (display_str, ri, ti, qi)
            for ri, rd in enumerate(siq_r.rounds):
                for ti, th_ in enumerate(rd["themes"]):
                    for qi, q in enumerate(th_["questions"]):
                        if ri == rnd_r and ti == th_r and q["price"] == price_r:
                            continue
                        label = f"[{rd['name']}] {th_['name']} — {q['price']}"
                        choices.append((label, ri, ti, qi, q["price"]))
            if not choices:
                _api.msgbox_information(viewer_r, "Перенос ответов", "Нет других вопросов в паке.")
                return
            labels = [c[0] for c in choices]
            item, ok = _api.QInputDialog.getItem(
                viewer_r, "Перенести ответы",
                "Выберите вопрос-получатель правильных ответов:",
                labels, 0, False)
            if not ok or not item: return
            idx_chosen = labels.index(item)
            _, dst_ri, dst_ti, dst_qi, dst_price = choices[idx_chosen]
            new_ans = [a for a in ans_ref if a.strip()]
            if not new_ans:
                _api.msgbox_information(viewer_r, "Перенос ответов", "Нет ответов для переноса.")
                return
            try:
                siq_r.save_question(dst_ri, dst_ti, dst_qi, [], new_ans)
                siq_r.rounds[dst_ri]["themes"][dst_ti]["questions"][dst_qi]["answers"] = new_ans
                mw = _api._find_mw(viewer_r)
                if hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                    mw._save_notif.setText(f"✅  Ответы перенесены → {item}")
                    mw._show_save_notification()
                    _api._notif_reset(mw)
            except Exception as e:
                _api.msgbox_warning(viewer_r, "Ошибка переноса", str(e))

        transfer_btn.clicked.connect(_transfer_answers)
        evl.addWidget(transfer_btn)

        # ── Wrong answers section ──────────────────────────────────
        _wrong_list = list(wrong_answers) if wrong_answers else []

        def _save_wrong():
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx = _api._q_idx(qs, price)
                new_wrong = [a for a in _wrong_list if a.strip()]
                root_xml, ns_url, tag, q_el = _api._xml_nav_q(siq, rnd, th, q_idx)
                wrong_el = q_el.find(tag("wrong"))
                if wrong_el is None and new_wrong:
                    wrong_el = _api.ET.SubElement(q_el, tag("wrong"))
                if wrong_el is not None:
                    for a in wrong_el.findall(tag("answer")):
                        wrong_el.remove(a)
                    for w in new_wrong:
                        a = _api.ET.SubElement(wrong_el, tag("answer"))
                        a.text = w
                siq._save_xml(root_xml, ns_url)
                siq.rounds[rnd]["themes"][th]["questions"][q_idx]["wrong_answers"] = new_wrong
            except Exception as e:
                _api._logger.warning(f"[save_wrong] {e}")

        _build_ans_section(evl, "Неправильные ответы (редактирование)", "❌",
                           _wrong_list, _save_wrong, "#45475a", "＋ Добавить неправильный ответ",
                           is_wrong_section=True)

        # ── Question comment section ──────────────────────────────
        comm_sep = _api.QFrame(); comm_sep.setFrameShape(_api.QFrame.Shape.HLine)
        comm_sep.setStyleSheet("background:#313244; max-height:1px;")
        evl.addWidget(comm_sep)

        q_comment = ""
        try:
            qs = siq.rounds[rnd]["themes"][th]["questions"]
            q_idx_c = _api._q_idx(qs, price)
            q_comment = qs[q_idx_c].get("comment","")
        except Exception: pass

        comm_hdr = _api.QLabel("💬  Комментарий (заметка к вопросу)")
        comm_hdr.setStyleSheet("color:#585b70;font-size:9px;font-weight:700;"
                               "letter-spacing:1px;padding:4px 0 2px 0;")
        evl.addWidget(comm_hdr)

        comm_te = _api.QTextEdit(q_comment)
        comm_te.setFixedHeight(52)
        comm_te.setPlaceholderText("Заметка ведущего (не видна игрокам). Сохраняется в XML…")
        comm_te.setStyleSheet(
            "QTextEdit{background:#1e1e2e;color:#a6adc8;border:1px solid #313244;"
            "border-radius:4px;padding:3px 6px;font-size:11px;font-style:italic;}"
            "QTextEdit:focus{border-color:#89b4fa;color:#cdd6f4;}")
        evl.addWidget(comm_te)

        def _save_comment(rnd_s=rnd, th_s=th, price_s=price, te=comm_te, viewer_s=self):
            try:
                qs_s = siq.rounds[rnd_s]["themes"][th_s]["questions"]
                q_idx_s = _api._q_idx(qs_s, price_s)
                siq.save_question_comment(rnd_s, th_s, q_idx_s, te.toPlainText().strip())
            except Exception as e:
                _api._logger.warning(f"[save_q_comment] {e}")

        comm_te.focusOutEvent = lambda e, te=comm_te: (type(te).focusOutEvent(te,e), _save_comment())

        self._a_lay.addWidget(editor_w)

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

        # ══ Regular answers — shown in editable editor below; skip static display ══
        # Wrong answers (legacy) also hidden — not needed in viewer

    def _build_item(self, it: dict) -> _api.QWidget | None:
        itype = it["type"]; text = it["text"]; is_ref = it["is_ref"]

        # Timer duration from XML attr
        dur_attr = it.get("xml_duration","")
        dur_sec_xml: float | None = _api._parse_hms(dur_attr) if dur_attr else None

        # Simultaneous badge (join to next) - no text suffix, only visual frame
        simul_tag = ""

        # Устный текст (placement=replic): 💬 icon + italic text, no blue frame
        if it.get("placement") == "replic":
            row = _api.QWidget(); row.setStyleSheet(_api._SS_TRANSPARENT)
            rl = _api.QHBoxLayout(row); rl.setContentsMargins(0,2,0,2); rl.setSpacing(6)
            icon = _api.QLabel("💬"); icon.setStyleSheet("font-size:13px;background:transparent;")
            rl.addWidget(icon, 0, _api._AlignVC)
            lbl = _api.QLabel(text); lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#b4befe;font-style:italic;font-size:12px;background:transparent;")
            rl.addWidget(lbl, 1)
            if dur_sec_xml is not None:
                dl = _api.QLabel(f"⏱ {_api.fmt_dur(dur_sec_xml)}")
                dl.setStyleSheet(_api._SS_BADGE_MUTED)
                rl.addWidget(dl, 0, _api._AlignVC)
            return row

        # Текст
        if itype == "text":
            display = text + simul_tag
            if dur_sec_xml is not None:
                row = _api.QWidget(); row.setStyleSheet(_api._SS_TRANSPARENT)
                rl = _api.QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
                lbl = _api.QLabel(display); lbl.setWordWrap(True)
                lbl.setStyleSheet("color:#cdd6f4; font-size:13px;")
                rl.addWidget(lbl, 1)
                dl = _api.QLabel(f"⏱ {_api.fmt_dur(dur_sec_xml)}")
                dl.setStyleSheet(_api._SS_BADGE_MUTED)
                rl.addWidget(dl, 0, _api._AlignVC)
                return row
            lbl = _api.QLabel(display); lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#cdd6f4; font-size:13px;"); return lbl

        # Картинка
        if itype == "image" and is_ref:
            fname_img = text.split("/")[-1]
            path = self.siq.extract_media(text)
            wrapper = _api.QWidget(); wrapper.setStyleSheet(_api._SS_TRANSPARENT)
            wrapper.setSizePolicy(_api._Pref, _api.QSizePolicy.Policy.Maximum)
            wl = _api.QVBoxLayout(wrapper); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(2)

            _img_preview_w = max(280, int(380 * _api._screen_scale()))

            if path and _api.os.path.exists(path):
                # File size (fast — just stat, no read)
                try:
                    sz_b = _api.os.path.getsize(path)
                    img_size_str = (f"  {sz_b/1_048_576:.1f} МБ" if sz_b >= 1_048_576
                                    else f"  {sz_b//1024} КБ" if sz_b > 0 else "")
                except Exception:
                    img_size_str = ""

                # ── Placeholder for the image ─────────────────────────
                img_lbl = _api.QLabel()
                img_lbl.setFixedHeight(80)
                img_lbl.setAlignment(_api._AlignC)
                img_lbl.setStyleSheet("color:#585b70;font-size:11px;background:transparent;")
                img_lbl.setText("⏳  Загрузка…")
                img_lbl.setSizePolicy(_api._Pref, _api.QSizePolicy.Policy.Maximum)
                wl.addWidget(img_lbl)

                # ── Filename / info label (dim+size filled in from bg thread) ──
                _fname_lbl = _api.QLabel(f"🖼  {fname_img}{img_size_str}{simul_tag}")
                _fname_lbl.setWordWrap(True)
                _fname_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
                _fname_lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
                _fname_lbl.setCursor(_api.Qt.CursorShape.IBeamCursor)
                _fname_lbl.setToolTip(f"ПКМ — скопировать имя файла: {fname_img}")
                _fname_lbl.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
                def _img_fname_ctx(pos, name=fname_img, lbl=_fname_lbl):
                    menu = _api.QMenu(lbl)
                    menu.addAction("📋  Копировать имя файла").triggered.connect(
                        lambda: _api.QApplication.clipboard().setText(name))
                    sel = lbl.selectedText()
                    if sel:
                        menu.addAction("Копировать выделенное").triggered.connect(
                            lambda: _api.QApplication.clipboard().setText(sel))
                    menu.exec(lbl.mapToGlobal(pos))
                _fname_lbl.customContextMenuRequested.connect(_img_fname_ctx)
                wl.addWidget(_fname_lbl)

                # ── Background thread: decode size + pixmap ───────────
                # Use the module-level singleton bridge — it is never GC'd,
                # unlike a local bridge variable which dies when _build_item returns.
                def _load_async(p=path, w=_img_preview_w,
                                dim_lbl=_fname_lbl, img_label=img_lbl,
                                fname_=fname_img, sz_str=img_size_str, simul=simul_tag):
                    iw, ih = _api._img_size_from_path(p)
                    if iw and ih:
                        _api._get_ui_bridge().deliver_text(
                            dim_lbl, f"🖼  {fname_}  {iw}×{ih}{sz_str}{simul}")
                    qimg = _api._load_qimage(p, w)
                    _api._get_ui_bridge().deliver(qimg, img_label)

                _api._threading.Thread(target=_load_async, daemon=True).start()
            else:
                wl.addWidget(_api._lbl(f"🖼  Файл не найден: {text}", "color:#f38ba8;font-size:11px;"))
                _fname_lbl = _api.QLabel(f"🖼  {fname_img}{simul_tag}")
                _fname_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
                wl.addWidget(_fname_lbl)

            return wrapper

        # Видео / аудио
        if itype in ("video", "audio") and is_ref:
            path = self.siq.extract_media(text)
            if path and _api.os.path.exists(path):
                fname_media = text.split("/")[-1] + simul_tag
                if itype == "video":
                    w = _api.MpvVideoPlayerWidget(path, fname_media, it["dur"])
                else:
                    w = _api.AudioPlayerWidget(path, fname_media, it["dur"])
                self._media_widgets.append(w)
                return w
            else:
                w = _api.QWidget(); w.setStyleSheet("background:#1e1e2e; border-radius:6px;")
                _api.QVBoxLayout(w).addWidget(_api._lbl(f"⚠  Файл не найден: {text}", "color:#f38ba8; font-size:11px;"))
                return w

        # HTML-мини-игра
        if itype == "html" and is_ref:
            fname_html = text.split("/")[-1] + simul_tag
            path = self.siq.extract_media(text)
            w = _api.QWidget(); w.setStyleSheet("background:#1e1e2e; border-radius:6px;")
            wl = _api.QHBoxLayout(w); wl.setContentsMargins(10, 8, 10, 8); wl.setSpacing(8)
            icon = _api.QLabel("🌐"); icon.setStyleSheet("font-size:18px;background:transparent;")
            wl.addWidget(icon, 0, _api._AlignVC)

            info_col = _api.QVBoxLayout(); info_col.setSpacing(1)
            name_lbl = _api.QLabel(fname_html); name_lbl.setWordWrap(True)
            name_lbl.setStyleSheet("color:#cdd6f4;font-size:12px;")
            info_col.addWidget(name_lbl)
            sub = "HTML-мини-игра"
            if dur_sec_xml is not None:
                sub += f"  ⏱ {_api.fmt_dur(dur_sec_xml)}"
            sub_lbl = _api.QLabel(sub); sub_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
            info_col.addWidget(sub_lbl)
            wl.addLayout(info_col, 1)

            if path and _api.os.path.exists(path):
                open_btn = _api.QPushButton("▶ Открыть")
                open_btn.setObjectName(_api._ON_BTN_COMPARE); open_btn.setFixedHeight(26)
                open_btn.clicked.connect(
                    lambda _, p=path: _api.QDesktopServices.openUrl(_api.QUrl.fromLocalFile(p)))
                wl.addWidget(open_btn, 0, _api._AlignVC)
            else:
                warn = _api.QLabel("⚠ файл не найден")
                warn.setStyleSheet("color:#f38ba8;font-size:11px;")
                wl.addWidget(warn, 0, _api._AlignVC)
            return w

    def _open_propagate_wrong_dialog(self, wrong_text: str, datasets: list):
        """Show round selector and copy wrong_text into wrong_answers of all questions in chosen rounds."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem
        dlg = QDialog(self)
        dlg.setWindowTitle("Скопировать неправильный ответ в другие вопросы")
        dlg.setMinimumWidth(460); dlg.setMinimumHeight(400)
        dlg.setStyleSheet("QDialog{background:#181825;color:#cdd6f4;}"
                          "QTreeWidget{background:#1e1e2e;border:1px solid #45475a;border-radius:4px;"
                          "color:#cdd6f4;font-size:12px;outline:none;}"
                          "QTreeWidget::item{padding:3px 4px;}"
                          "QTreeWidget::item:selected{background:#45475a;color:#b4befe;}"
                          "QTreeWidget::branch{background:#1e1e2e;}")
        vl = QVBoxLayout(dlg); vl.setContentsMargins(14,12,14,12); vl.setSpacing(8)
        vl.addWidget(_api._lbl("Выберите раунды для добавления неправильного ответа:",
                          "color:#cdd6f4;font-size:12px;font-weight:700;"))
        _wrong_txt_lbl = _api._lbl(f"Текст: \u00ab{wrong_text}\u00bb", "color:#f9e2af;font-size:11px;")
        _wrong_txt_lbl.setWordWrap(True)
        vl.addWidget(_wrong_txt_lbl)
        tree = QTreeWidget(); tree.setHeaderHidden(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        vl.addWidget(tree, stretch=1)
        _pkg_items = []
        for ds in datasets:
            pkg_name = ds.get("pkg_name", "?")
            w = ds.get("widget"); siq = getattr(w, "_siq", None) if w else None
            if not siq: continue
            pkg_item = QTreeWidgetItem(tree, [pkg_name])
            pkg_item.setCheckState(0, _api.Qt.CheckState.Unchecked)
            pkg_item.setFlags(pkg_item.flags() | _api.Qt.ItemFlag.ItemIsUserCheckable | _api.Qt.ItemFlag.ItemIsAutoTristate)
            pkg_item.setExpanded(True)
            for ri, rd in enumerate(siq.rounds):
                rd_item = QTreeWidgetItem(pkg_item, [rd["name"]])
                rd_item.setCheckState(0, _api.Qt.CheckState.Unchecked)
                rd_item.setFlags(rd_item.flags() | _api.Qt.ItemFlag.ItemIsUserCheckable)
                rd_item.setData(0, _api.Qt.ItemDataRole.UserRole, (siq, ri))
            _pkg_items.append(pkg_item)
        bot = QHBoxLayout(); bot.addStretch()
        def _set_all(state):
            for pi in _pkg_items:
                for ci in range(pi.childCount()):
                    pi.child(ci).setCheckState(0, _api.Qt.CheckState.Checked if state else _api.Qt.CheckState.Unchecked)
        sel_all = _api.AnimatedButton("\u2713 \u0412\u0441\u0435"); sel_all.setObjectName(_api._ON_BTN_SORT); sel_all.setFixedHeight(24)
        sel_none = _api.AnimatedButton("\u2717 \u0421\u043d\u044f\u0442\u044c"); sel_none.setObjectName(_api._ON_BTN_SORT); sel_none.setFixedHeight(24)
        sel_all.clicked.connect(lambda: _set_all(True)); sel_none.clicked.connect(lambda: _set_all(False))
        cancel_btn = _api.AnimatedButton("\u041e\u0442\u043c\u0435\u043d\u0430"); cancel_btn.clicked.connect(dlg.reject)
        # NB: intentionally NOT objectName(_ON_BTN_ANALYZE) \u2014 main_window.py's
        # permanent "\ud83d\udd0d \u0410\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u0442\u044c" button already uses that exact objectName
        # and lives in the same widget tree (this dialog's QObject parent chain
        # runs up through it). Two live widgets sharing an objectName confuses
        # QStyleSheetStyle's rule cache and can leave one of them unpainted \u2014
        # that's what was making this button vanish. Style it inline instead.
        ok_btn = _api.AnimatedButton("\u2192 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c")
        ok_btn.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#181825;border:none;font-weight:700;"
            "border-radius:4px;padding:4px 12px;}"
            "QPushButton:hover{background:#94e2d5;}"
            "QPushButton:pressed{background:#94e2d5;}")
        ok_btn.setMinimumWidth(120); ok_btn.setFixedHeight(28)
        ok_btn.clicked.connect(dlg.accept)
        # Force each button to keep its full sizeHint width \u2014 a Preferred
        # QPushButton is otherwise free to shrink under horizontal pressure,
        # which can squeeze the last (rightmost) button in a tight row down
        # to near-invisible on some DPI/font-metric setups.
        for _b in (sel_all, sel_none, cancel_btn, ok_btn):
            _b.setSizePolicy(_api.QSizePolicy.Policy.Minimum, _api.QSizePolicy.Policy.Fixed)
        bot.addWidget(sel_all); bot.addWidget(sel_none); bot.addWidget(cancel_btn); bot.addWidget(ok_btn)
        vl.addLayout(bot)
        dlg.adjustSize()   # recompute geometry from live font metrics, not the static minimum
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        added_count = 0
        for pi in _pkg_items:
            for ci in range(pi.childCount()):
                child = pi.child(ci)
                if child.checkState(0) != _api.Qt.CheckState.Checked: continue
                data = child.data(0, _api.Qt.ItemDataRole.UserRole)
                if not data: continue
                siq_t, ri = data
                try:
                    for th_data in siq_t.rounds[ri]["themes"]:
                        for q in th_data["questions"]:
                            if wrong_text not in q.get("wrong_answers", []):
                                q.setdefault("wrong_answers", []).append(wrong_text)
                                added_count += 1
                    root_xml, ns_url, tag = siq_t._load_xml_root()
                    rnd_el, tag = siq_t._nav_to_round(root_xml, tag, ri)
                    for th_idx, th_data in enumerate(siq_t.rounds[ri]["themes"]):
                        ths = rnd_el.findall(f'{tag("themes")}/{tag("theme")}')
                        if th_idx >= len(ths): continue
                        q_els = ths[th_idx].findall(f'{tag("questions")}/{tag("question")}')
                        for qi, q_el in enumerate(q_els):
                            wrong_el = q_el.find(tag("wrong"))
                            if wrong_el is None:
                                wrong_el = _api.ET.SubElement(q_el, tag("wrong"))
                            existing = [a.text or "" for a in wrong_el.findall(tag("answer"))]
                            if wrong_text not in existing:
                                ae = _api.ET.SubElement(wrong_el, tag("answer")); ae.text = wrong_text
                    siq_t._save_xml(root_xml, ns_url)
                except Exception as ex:
                    _api._logger.warning(f"[propagate_wrong] {ex}")
        mw = _api._find_mw(self)
        if hasattr(mw, "_show_save_notification"):
            mw._save_notif.setText(f"\u2192 \u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e \u0432 {added_count} \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432")
            mw._show_save_notification()
            _api.QTimer.singleShot(3100, lambda: mw._save_notif.setText("\u2705  \u0424\u0430\u0439\u043b \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d"))
