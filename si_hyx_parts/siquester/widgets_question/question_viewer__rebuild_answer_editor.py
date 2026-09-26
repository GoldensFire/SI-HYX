# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: _rebuild_answer_editor. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


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
