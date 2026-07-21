"""QuestionViewer — the main question display/edit surface."""

from PyQt6.QtGui import QDesktopServices

from .qt import *
from .constants import *
from .util import *
from .persistence import *
from .media import *
from .siq_package import *
from .widgets_common import *
from .widgets_players import *
from .widgets_editors import *

class QuestionViewer(QWidget):
    edit_requested = pyqtSignal(int, int, int)   # rnd_idx, theme_idx, price

    def __init__(self, siq: SiqPackage, parent=None):
        super().__init__(parent)
        self.siq = siq
        self.setStyleSheet("background:#181825;")
        self._media_widgets: list = []
        self._current_rnd = 0
        self._current_th = 0
        self._current_price = 0
        self.setAcceptDrops(True)

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────
        hdr_row = QHBoxLayout(); hdr_row.setContentsMargins(0, 0, 0, 0); hdr_row.setSpacing(0)
        self._hdr = QLabel("← Нажмите на цену вопроса в таблице")
        self._hdr.setStyleSheet(
            "color:#a6adc8; font-size:12px; font-weight:500;"
            "background:#1e1e2e; padding:8px 14px; border-bottom:1px solid #313244;")
        hdr_row.addWidget(self._hdr, stretch=1)

        self._edit_btn = QPushButton("✏  Изменить")
        self._edit_btn.setObjectName(_ON_BTN_UPDATE)
        self._edit_btn.setFixedHeight(32)
        self._edit_btn.setToolTip("Редактировать вопрос (текст, ответы, цену)")
        self._edit_btn.setEnabled(False)
        self._edit_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#a6e3a1;border:none;"
            "border-left:1px solid #313244;border-bottom:1px solid #313244;"
            "padding:0 14px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#313244;color:#a6e3a1;}"
            "QPushButton:disabled{color:#45475a;background:#1e1e2e;}"
        )
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        hdr_row.addWidget(self._edit_btn)
        root.addLayout(hdr_row)

        # ── Single shared scroll area ────────────────────────────
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border:none; background:#181825;")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setStyleSheet("background:#181825;")
        _install_wheel_filter(self._scroll)

        self._content_w = QWidget(); self._content_w.setStyleSheet("background:#181825;")
        self._content_vl = QVBoxLayout(self._content_w)
        self._content_vl.setContentsMargins(0,0,0,12); self._content_vl.setSpacing(0)

        # ВОПРОС section
        q_hdr = QLabel("ВОПРОС")
        q_hdr.setStyleSheet(_SS_TOPBAR_LABEL)
        self._content_vl.addWidget(q_hdr)
        self._q_inner = QWidget(); self._q_inner.setStyleSheet("background:#181825;")
        self._q_inner.setAcceptDrops(True)
        self._q_inner.dragEnterEvent = self._section_drag_enter
        self._q_inner.dragLeaveEvent = lambda e, w=self._q_inner: self._section_drag_leave(w)
        self._q_inner.dropEvent      = self.dropEvent
        self._q_lay = QVBoxLayout(self._q_inner)
        self._q_lay.setContentsMargins(10,10,10,10); self._q_lay.setSpacing(6)
        self._content_vl.addWidget(self._q_inner)

        # Separator
        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#313244; margin:0;")
        self._content_vl.addWidget(sep)

        # ОТВЕТ section
        a_hdr = QLabel("ОТВЕТ")
        a_hdr.setStyleSheet(_SS_TOPBAR_LABEL)
        self._content_vl.addWidget(a_hdr)
        self._a_inner = QWidget(); self._a_inner.setStyleSheet("background:#181825;")
        self._a_inner.setAcceptDrops(True)
        self._a_inner.dragEnterEvent = self._section_drag_enter
        self._a_inner.dragLeaveEvent = lambda e, w=self._a_inner: self._section_drag_leave(w)
        # Force param_name="answer" for any file dropped directly onto the answer section
        def _a_inner_drop(ev, _self=self):
            md = ev.mimeData()
            if md.hasFormat(_MIME_BLOCK) and _self._current_price:
                _self.dropEvent(ev); return
            if md.hasUrls() and _self._current_price:
                rnd, th, price = _self._current_rnd, _self._current_th, _self._current_price
                try:
                    qs = _self.siq.rounds[rnd]["themes"][th]["questions"]
                    q_idx = _q_idx(qs, price)
                except (StopIteration, Exception):
                    return
                for url in md.urls():
                    path = url.toLocalFile()
                    if Path(path).suffix.lower() in _MEDIA_EXTS:
                        _self._do_add_media(rnd, th, q_idx, path, param_name="answer")
                ev.acceptProposedAction()
                _self._clear_section_highlights()
        self._a_inner.dropEvent = _a_inner_drop
        self._a_lay = QVBoxLayout(self._a_inner)
        self._a_lay.setContentsMargins(10,10,10,10); self._a_lay.setSpacing(6)
        self._content_vl.addWidget(self._a_inner)

        self._content_vl.addStretch(1)
        self._scroll.setWidget(self._content_w)
        root.addWidget(self._scroll, stretch=1)
        self._copy_hl_clear = None   # set by copy button; cleared on mouse press

    def mousePressEvent(self, ev):
        # Clear copy-highlight on any click inside the viewer
        if self._copy_hl_clear:
            try: self._copy_hl_clear()
            except Exception as _e: _logger.debug(str(_e))
            self._copy_hl_clear = None
        super().mousePressEvent(ev)

    def _section_drag_enter(self, ev):
        """Highlight drop target section while dragging a block."""
        md = ev.mimeData()
        if md.hasFormat(_MIME_BLOCK) or (md.hasUrls() and self._current_price):
            # Highlight whichever section received the dragEnter
            w = ev.source() if hasattr(ev, 'source') else None
            # Find which inner widget got this event by checking sender
            # We re-use existing dropEvent — just highlight visually
            ev.acceptProposedAction()
            # Use the widget the event was installed on
            for section_w in (self._q_inner, self._a_inner):
                rect = section_w.rect()
                tl = section_w.mapToGlobal(rect.topLeft())
                br = section_w.mapToGlobal(rect.bottomRight())
                gp = section_w.mapFromGlobal(ev.position().toPoint() if hasattr(ev, 'position') else tl)
                if rect.contains(gp):
                    section_w.setStyleSheet("background:rgba(137,180,250,0.08);border:1px solid rgba(137,180,250,0.3);border-radius:4px;")
                    break

    def _section_drag_leave(self, widget: QWidget):
        widget.setStyleSheet("background:#181825;")

    def show_question(self, q_obj: dict, rnd_idx: int = 0, theme_idx: int = 0):
        price = q_obj["price"]; dur = q_obj["dur"]
        self._hdr.setText(f"Вопрос  •  Цена: {price}  •  ⏱ {fmt_dur(dur)}")
        self._current_rnd = rnd_idx
        self._current_th = theme_idx
        self._current_price = price
        self._edit_btn.setEnabled(True)
        self._stop_player()
        q_type = q_obj.get("q_type", "")
        self._fill_lay(self._q_lay,
                       [i for i in q_obj["items"] if i["param"] in ("question","background")])
        # For point mode pass only answer items (image), _fill_lay will build PointOnImageWidget
        a_items = [i for i in q_obj["items"] if i["param"] == "answer"]
        self._fill_lay(self._a_lay, a_items,
                       q_obj["answers"],
                       q_obj.get("wrong_answers", []),
                       q_obj.get("answer_options", {}),
                       q_type,
                       q_obj.get("answer_deviation", 0.1))
        # Point mode and select mode have their own interactive panels
        if q_type not in ("point", "select"):
            clean_wrong = [w for w in q_obj.get("wrong_answers", [])
                           if w.strip() and
                           ("." not in w or Path(w.strip()).suffix.lower() not in _MEDIA_EXTS)]
            answers_snap = q_obj.get("answers", [])
            QTimer.singleShot(0, lambda a=answers_snap, w=clean_wrong:
                              self._rebuild_answer_editor(a, w))
        QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(0))

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

        editor_w = QWidget(); editor_w.setStyleSheet(_SS_TRANSPARENT)
        editor_w._is_answer_editor = True
        evl = QVBoxLayout(editor_w); evl.setContentsMargins(0, 6, 0, 4); evl.setSpacing(2)

        def _build_ans_section(evl_parent, section_label, icon, ans_list_ref, save_fn,
                               label_color, add_label, is_wrong_section=False):
            """Helper: builds a drag/edit answer section and returns the list ref."""
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("background:#313244; max-height:1px;")
            evl_parent.addWidget(sep)

            lbl_hdr = QLabel(f"{icon}  {section_label}")
            lbl_hdr.setStyleSheet(f"color:{label_color};font-size:9px;font-weight:700;"
                                  "letter-spacing:1px;padding:4px 0 2px 0;")
            evl_parent.addWidget(lbl_hdr)

            rows_w = QWidget(); rows_w.setStyleSheet(_SS_TRANSPARENT)
            rows_vl = QVBoxLayout(rows_w); rows_vl.setContentsMargins(0, 0, 0, 0); rows_vl.setSpacing(3)
            evl_parent.addWidget(rows_w)

            _row_widgets: list = []

            def _add_row(text: str, idx: int):
                row_w = QWidget(); row_w.setStyleSheet(_SS_TRANSPARENT)
                row_w._ans_idx = idx
                row_w.setAcceptDrops(True)
                rl = QHBoxLayout(row_w); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(4)

                dh = QPushButton("⠿"); dh.setFixedSize(14, 24)
                dh.setCursor(Qt.CursorShape.SizeAllCursor)
                dh.setStyleSheet(_DH_SS_HIDDEN)
                def _dh_press(ev, h=dh): h._drag_origin = ev.position().toPoint() if ev.button() == Qt.MouseButton.LeftButton else None
                def _dh_move(ev, h=dh, rw=row_w):
                    if not getattr(h,'_drag_origin',None): return
                    if (ev.position().toPoint()-h._drag_origin).manhattanLength() < 5: return
                    h._drag_origin = None; _do_row_drag(rw)
                dh.mousePressEvent = _dh_press; dh.mouseMoveEvent = _dh_move

                le = _AnsEdit(text)
                _this_idx = idx

                # Media file dropped on this answer row → add as media item to question
                def _on_media_drop(path, viewer=self):
                    if not viewer._current_price: return
                    try:
                        qs = viewer.siq.rounds[viewer._current_rnd]["themes"][viewer._current_th]["questions"]
                        q_idx_m = _q_idx(qs, viewer._current_price)
                        viewer._do_add_media(viewer._current_rnd, viewer._current_th, q_idx_m,
                                             path, param_name="answer")
                    except Exception as ex:
                        _logger.warning(f"[ans media drop] {ex}")
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

                del_b = QPushButton("✕"); del_b.setObjectName(_ON_BTN_DEL); del_b.setFixedSize(22, 22)
                def _del_row(_, le=le, i=_this_idx):
                    if len(ans_list_ref) > 1:
                        ans_list_ref.pop(i); save_fn(); _refresh_rows()
                    else:
                        ans_list_ref[0] = ""; le.setText(""); save_fn()
                del_b.clicked.connect(_del_row)

                copy_b = QPushButton("⎘"); copy_b.setFixedSize(22, 22)
                copy_b.setToolTip("Копировать текст ответа")
                copy_b.setStyleSheet("QPushButton{background:transparent;color:#585b70;border:none;"
                                     "font-size:13px;border-radius:3px;padding:0;}"
                                     "QPushButton:hover{color:#cdd6f4;background:rgba(255,255,255,0.06);}")
                def _copy_row(_, le=le, qv=self):
                    txt = le.text()
                    if txt:
                        QApplication.clipboard().setText(txt)
                        orig_ss = le.styleSheet()
                        hl_ss = (orig_ss +
                            "background:rgba(137,180,250,0.20);color:#b4befe;"
                            "border:1px solid #89b4fa;border-radius:3px;")
                        le.setStyleSheet(hl_ss)
                        def _clear_hl(le=le, ss=orig_ss):
                            try: le.setStyleSheet(ss)
                            except RuntimeError: pass
                        qv._copy_hl_clear = _clear_hl
                        mw = _find_mw(qv)
                        if mw and hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                            mw._save_notif.setText("📋  Ответ скопирован")
                            mw._show_save_notification()
                            _notif_reset(mw)
                copy_b.clicked.connect(_copy_row)

                rl.addWidget(dh); rl.addWidget(le, stretch=1); rl.addWidget(copy_b)

                # Propagate-to-other-questions button (wrong answers section only)
                if is_wrong_section:
                    prop_b = QPushButton("→"); prop_b.setFixedSize(22, 22)
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
                        mw = _find_mw(qv)
                        datasets = getattr(mw, 'datasets', ())
                        qv._open_propagate_wrong_dialog(txt, datasets)
                    prop_b.clicked.connect(_propagate_wrong)
                    rl.addWidget(prop_b)

                rl.addWidget(del_b)

                def _row_enter(e, h=dh): h.setStyleSheet(_DH_SS_SHOWN)
                def _row_leave(e, h=dh): h.setStyleSheet(_DH_SS_HIDDEN)
                row_w.enterEvent = _row_enter; row_w.leaveEvent = _row_leave

                def _row_drag_enter(e, rw=row_w):
                    if e.mimeData().hasFormat(_MIME_ANS): e.acceptProposedAction()
                def _row_drop(e, rw=row_w):
                    if not e.mimeData().hasFormat(_MIME_ANS): return
                    src_i = int(bytes(e.mimeData().data(_MIME_ANS)).decode())
                    dst_i = rw._ans_idx
                    if src_i != dst_i:
                        item = ans_list_ref.pop(src_i)
                        ans_list_ref.insert(dst_i, item)
                        save_fn(); _refresh_rows()
                    e.acceptProposedAction()
                row_w.dragEnterEvent = _row_drag_enter; row_w.dropEvent = _row_drop

                rows_vl.addWidget(row_w)
                _row_widgets.append((row_w, le))

            def _do_row_drag(rw: QWidget):
                mime = QMimeData()
                mime.setData(_MIME_ANS, QByteArray(str(rw._ans_idx).encode()))
                d = QDrag(rw); d.setMimeData(mime)
                raw = rw.grab(); ghost = QPixmap(raw.size()); ghost.fill(Qt.GlobalColor.transparent)
                p = QPainter(ghost); p.setOpacity(0.55); p.drawPixmap(0, 0, raw); p.end()
                d.setPixmap(ghost); d.setHotSpot(raw.rect().center())
                rw.setVisible(False)
                d.exec(Qt.DropAction.MoveAction)
                try: rw.setVisible(True)
                except RuntimeError: pass

            def _refresh_rows():
                _row_widgets.clear()
                while rows_vl.count():
                    it = rows_vl.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                for i, a in enumerate(ans_list_ref):
                    _add_row(a, i)
                add_b = QPushButton(add_label)
                add_b.setObjectName(_ON_BTN_ANALYZE); add_b.setFixedHeight(24)
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
                q_idx = _q_idx(qs, price)
                new_ans = [a for a in _ans_list if a.strip()]
                siq.save_question(rnd, th, q_idx, [], new_ans)
                siq.rounds[rnd]["themes"][th]["questions"][q_idx]["answers"] = new_ans
            except Exception as e:
                _logger.warning(f"[save_right] {e}")

        _build_ans_section(evl, "Правильные ответы (редактирование)", "✅",
                           _ans_list, _save_right, "#585b70", "＋ Добавить правильный ответ")

        # ── Transfer answers button ────────────────────────────────
        transfer_btn = QPushButton("→ Перенести ответы в другой вопрос")
        transfer_btn.setObjectName(_ON_BTN_SORT)
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
                msgbox_information(viewer_r, "Перенос ответов", "Нет других вопросов в паке.")
                return
            labels = [c[0] for c in choices]
            item, ok = QInputDialog.getItem(
                viewer_r, "Перенести ответы",
                "Выберите вопрос-получатель правильных ответов:",
                labels, 0, False)
            if not ok or not item: return
            idx_chosen = labels.index(item)
            _, dst_ri, dst_ti, dst_qi, dst_price = choices[idx_chosen]
            new_ans = [a for a in ans_ref if a.strip()]
            if not new_ans:
                msgbox_information(viewer_r, "Перенос ответов", "Нет ответов для переноса.")
                return
            try:
                siq_r.save_question(dst_ri, dst_ti, dst_qi, [], new_ans)
                siq_r.rounds[dst_ri]["themes"][dst_ti]["questions"][dst_qi]["answers"] = new_ans
                mw = _find_mw(viewer_r)
                if hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                    mw._save_notif.setText(f"✅  Ответы перенесены → {item}")
                    mw._show_save_notification()
                    _notif_reset(mw)
            except Exception as e:
                msgbox_warning(viewer_r, "Ошибка переноса", str(e))

        transfer_btn.clicked.connect(_transfer_answers)
        evl.addWidget(transfer_btn)

        # ── Wrong answers section ──────────────────────────────────
        _wrong_list = list(wrong_answers) if wrong_answers else []

        def _save_wrong():
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx = _q_idx(qs, price)
                new_wrong = [a for a in _wrong_list if a.strip()]
                root_xml, ns_url, tag, q_el = _xml_nav_q(siq, rnd, th, q_idx)
                wrong_el = q_el.find(tag("wrong"))
                if wrong_el is None and new_wrong:
                    wrong_el = ET.SubElement(q_el, tag("wrong"))
                if wrong_el is not None:
                    for a in wrong_el.findall(tag("answer")):
                        wrong_el.remove(a)
                    for w in new_wrong:
                        a = ET.SubElement(wrong_el, tag("answer"))
                        a.text = w
                siq._save_xml(root_xml, ns_url)
                siq.rounds[rnd]["themes"][th]["questions"][q_idx]["wrong_answers"] = new_wrong
            except Exception as e:
                _logger.warning(f"[save_wrong] {e}")

        _build_ans_section(evl, "Неправильные ответы (редактирование)", "❌",
                           _wrong_list, _save_wrong, "#45475a", "＋ Добавить неправильный ответ",
                           is_wrong_section=True)

        # ── Question comment section ──────────────────────────────
        comm_sep = QFrame(); comm_sep.setFrameShape(QFrame.Shape.HLine)
        comm_sep.setStyleSheet("background:#313244; max-height:1px;")
        evl.addWidget(comm_sep)

        q_comment = ""
        try:
            qs = siq.rounds[rnd]["themes"][th]["questions"]
            q_idx_c = _q_idx(qs, price)
            q_comment = qs[q_idx_c].get("comment","")
        except: pass

        comm_hdr = QLabel("💬  Комментарий (заметка к вопросу)")
        comm_hdr.setStyleSheet("color:#585b70;font-size:9px;font-weight:700;"
                               "letter-spacing:1px;padding:4px 0 2px 0;")
        evl.addWidget(comm_hdr)

        comm_te = QTextEdit(q_comment)
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
                q_idx_s = _q_idx(qs_s, price_s)
                siq.save_question_comment(rnd_s, th_s, q_idx_s, te.toPlainText().strip())
            except Exception as e:
                _logger.warning(f"[save_q_comment] {e}")

        comm_te.focusOutEvent = lambda e, te=comm_te: (type(te).focusOutEvent(te,e), _save_comment())

        self._a_lay.addWidget(editor_w)

    def _on_edit_clicked(self):
        self.edit_requested.emit(self._current_rnd, self._current_th, self._current_price)

    def _detect_section(self, global_pos) -> str:
        """Return 'question' or 'answer' based on where the interaction landed.
        Uses Y midpoint of the separator between sections as threshold."""
        # Try precise per-widget hit test first
        for section, widget in [("answer", self._a_inner), ("question", self._q_inner)]:
            tl = widget.mapToGlobal(widget.rect().topLeft())
            br = widget.mapToGlobal(widget.rect().bottomRight())
            if QRect(tl, br).contains(global_pos):
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
        menu = QMenu(self)
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
            q_idx = _q_idx(qs, price)
        except (StopIteration, Exception):
            return
        if action == "add_text":
            text, ok = QInputDialog.getMultiLineText(self, f"Добавить текст ({section_label})",
                                                     "Введите текст:")
            if ok and text.strip():
                self._add_text_item(rnd, th, q_idx, text.strip(), param_name)
        elif action == "add_oral":
            text, ok = QInputDialog.getMultiLineText(self, f"Устный текст ({section_label})",
                                                     "Введите текст, который зачитывает ведущий:")
            if ok and text.strip():
                self._add_text_item(rnd, th, q_idx, text.strip(), param_name, placement="replic")
        elif action == "add_media":
            path, _ = QFileDialog.getOpenFileName(
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
            root_xml, ns_url, tag, q_el = _xml_nav_q(self.siq, rnd, th, q_idx)
            params_el = q_el.find(tag("params"))
            if params_el is None:
                params_el = ET.SubElement(q_el, tag("params"))
            p = None
            for pp in params_el.findall(tag("param")):
                if pp.get("name") == param_name:
                    p = pp; break
            if p is None:
                p = ET.SubElement(params_el, tag("param"))
                p.set("name", param_name); p.set("type", "content")
            it = ET.SubElement(p, tag("item"))
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
            _logger.warning(f"[add_text_item] {e}")
            msgbox_warning(self, "Ошибка", str(e))

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
            msgbox_warning(self, "Ошибка", "Не удалось добавить медиафайл.")

    # ── Drag-drop media files onto the viewer ───────────────────
    def dragEnterEvent(self, ev):
        md = ev.mimeData()
        if md.hasFormat(_MIME_BLOCK) and self._current_price:
            ev.acceptProposedAction()
            self._highlight_section(self.mapToGlobal(ev.position().toPoint()))
            return
        if md.hasUrls() and self._current_price:
            urls = md.urls()
            if any(Path(u.toLocalFile()).suffix.lower() in _MEDIA_EXTS for u in urls):
                ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(_MIME_BLOCK) and self._current_price:
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
        if md.hasFormat(_MIME_BLOCK) and self._current_price:
            self._clear_section_highlights()
            raw = bytes(md.data(_MIME_BLOCK)).decode()
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
            q_idx = _q_idx(qs, price)
        except (StopIteration, Exception):
            return
        for url in md.urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in _MEDIA_EXTS:
                self._do_add_media(rnd, th, q_idx, path, param_name=param_name)
        ev.acceptProposedAction()

    def _move_item_to_section(self, item_idx: int, src_param: str, dst_param: str):
        """Move an item from src_param (question/answer) to dst_param."""
        rnd, th, price = self._current_rnd, self._current_th, self._current_price
        try:
            qs = self.siq.rounds[rnd]["themes"][th]["questions"]
            q_idx = _q_idx(qs, price)
            q_obj = qs[q_idx]
            param_items = [it for it in q_obj["items"] if it["param"] == src_param]
            if item_idx >= len(param_items): return
            # Update in-memory param
            param_items[item_idx]["param"] = dst_param
            # Update XML
            root_xml, ns_url, tag, q_el = _xml_nav_q(self.siq, rnd, th, q_idx)
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
                dst_p = ET.SubElement(params_el, tag("param"))
                dst_p.set("name", dst_param); dst_p.set("type", "content")
            dst_p.append(item_el)
            self.siq._save_xml(root_xml, ns_url)
            q_ref = self.siq.find_question(rnd, th, price)
            if q_ref: self.show_question(q_ref, rnd_idx=rnd, theme_idx=th)
        except Exception as e:
            _logger.warning(f"[move_item_to_section] {e}")

    def _stop_player(self):
        """Stop all media players. MPV stop is async to avoid blocking the UI."""
        for mw in self._media_widgets:
            try: mw.stop()
            except: pass
        self._media_widgets.clear()

    def _clear_lay(self, lay: QVBoxLayout):
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
                except Exception as _e: _logger.debug(str(_e))
            to_delete.append(w)
        for w in to_delete:
            w.setParent(None)
            QTimer.singleShot(0, w.deleteLater)

    def _build_deletable_item(self, it: dict, item_idx: int, param_name: str) -> QWidget | None:
        """Wrap item with drag handle. Delete/simultaneous buttons float inside the content widget."""
        siq = self.siq; viewer = self
        _rnd = self._current_rnd; _th = self._current_th; _price = self._current_price
        _pidx = item_idx; _pname = param_name

        # ── Shared save-text function for inline editors ──────────
        def _save_text_xml(new_text):
            try:
                qs = siq.rounds[_rnd]["themes"][_th]["questions"]
                q_idx_s = _q_idx(qs, _price)
                param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == _pname]
                if _pidx < len(param_items):
                    param_items[_pidx]["text"] = new_text
                root_xml, ns_url, tag, q_el = _xml_nav_q(siq, _rnd, _th, q_idx_s)
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
                _logger.warning(f"[save_inline_text] {e}")

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
        simul_tag = ""   # no text suffix - visual is handled by the frame
        _drag_source = None

        # ── Timer duration from XML ───────────────────────────────
        # Parse duration="HH:MM:SS" or "MM:SS" into seconds
        dur_attr = it.get("xml_duration", "")   # stored separately from computed dur
        dur_sec_override: float | None = _parse_hms(dur_attr) if dur_attr else None

        if is_replic:
            # Oral text: 💬 icon + italic text
            row = QWidget(); row.setStyleSheet(_SS_TRANSPARENT)
            rl = QHBoxLayout(row); rl.setContentsMargins(0,2,0,2); rl.setSpacing(6)
            icon_lbl = QLabel("💬"); icon_lbl.setStyleSheet("font-size:13px;background:transparent;")
            rl.addWidget(icon_lbl, 0, _AlignVC)
            te = _InlineTextEdit(
                it["text"],
                "background:transparent;color:#b4befe;font-style:italic;font-size:12px;"
                "border:none;padding:0;",
                "background:rgba(137,180,250,0.10);color:#b4befe;font-style:italic;font-size:12px;"
                "border:1px solid #89b4fa;border-radius:3px;padding:2px;")
            te.save_done.connect(_save_text_xml)
            rl.addWidget(te, 1)
            if is_join_next:
                frame = QFrame()
                frame.setStyleSheet(
                    "QFrame{background:rgba(137,180,250,0.07);border-left:3px solid #89b4fa;"
                    "border-radius:0px 4px 4px 0px;}")
                fl = QHBoxLayout(frame); fl.setContentsMargins(6,4,6,4); fl.setSpacing(0)
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
                _logger.warning(f"[build_simul_media] {e}")
                raw_inner = None
            if raw_inner is None:
                return None
            frame = QFrame()
            frame.setStyleSheet(
                _ITEM_JOIN_SS)
            fl = QVBoxLayout(frame); fl.setContentsMargins(6, 4, 6, 4); fl.setSpacing(0)
            fl.addWidget(raw_inner)
            if hasattr(raw_inner, 'block_drag'):
                _drag_source = raw_inner
            inner = frame
        elif is_join_next and is_text:
            frame = QFrame()
            frame.setStyleSheet(
                _ITEM_JOIN_SS)
            fl = QHBoxLayout(frame); fl.setContentsMargins(8,4,4,4); fl.setSpacing(6)
            te = _InlineTextEdit(
                it["text"],
                "background:transparent;color:#cdd6f4;font-size:13px;border:none;padding:1px;",
                "background:#1e1e2e;color:#cdd6f4;font-size:13px;"
                "border:1px solid #89b4fa;border-radius:4px;padding:3px;")
            te.save_done.connect(_save_text_xml)
            fl.addWidget(te, 1)
            inner = frame; _drag_source = te
        elif is_text:
            te = _InlineTextEdit(
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
        outer = QWidget(); outer.setStyleSheet(_SS_TRANSPARENT)
        outer.setAcceptDrops(False)
        ol = QHBoxLayout(outer); ol.setContentsMargins(0, 0, 0, 0); ol.setSpacing(2)

        # ── Shared start-drag helper ──────────────────────────────
        def _start_drag(source_w=None):
            mime = QMimeData()
            mime.setData(_MIME_BLOCK,
                         QByteArray(f"{_pname}:{_pidx}".encode()))
            d = QDrag(source_w or outer); d.setMimeData(mime)
            raw = outer.grab()
            ghost = QPixmap(raw.size()); ghost.fill(Qt.GlobalColor.transparent)
            p = QPainter(ghost); p.setOpacity(0.55); p.drawPixmap(0, 0, raw); p.end()
            d.setPixmap(ghost)
            d.setHotSpot(raw.rect().center())
            outer.setVisible(False)
            d.exec(Qt.DropAction.MoveAction)
            try: outer.setVisible(True)
            except RuntimeError: pass

        # ── Drag handle ──────────────────────────────────────────
        drag_btn = QPushButton("⠿")
        drag_btn.setFixedSize(14, 22)
        drag_btn.setCursor(Qt.CursorShape.SizeAllCursor)
        drag_btn.setToolTip("Перетащить в другой раздел")
        drag_btn.setStyleSheet(_DH_SS_HIDDEN)

        def _dh_press(ev, h=drag_btn):
            if ev.button() == Qt.MouseButton.LeftButton:
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
            inner.setCursor(Qt.CursorShape.OpenHandCursor)
            def _img_press(ev, w=inner):
                if ev.button() == Qt.MouseButton.LeftButton:
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

        ol.addWidget(drag_btn, 0, _AlignVC)
        ol.addWidget(inner, stretch=1)

        # ── Overlay buttons — NO layout contribution, float via resizeEvent ──
        is_simul = is_join_next   # for overlay button state
        simul_btn = QPushButton("⇥")
        simul_btn.setFixedSize(20, 20); simul_btn.setCheckable(True)
        simul_btn.setChecked(is_simul)
        simul_btn.setToolTip("Присоединить к следующему (проигрывать одновременно)")
        # _SB_OFF / _SB_ON / _SB_HOV defined at module level
        simul_btn.setStyleSheet(_SB_ON if is_simul else _SB_OFF)

        def _toggle_simul(checked, btn=simul_btn, rnd=_rnd, th=_th, price=_price,
                          pidx=_pidx, pname=_pname):
            btn.setStyleSheet(_SB_ON if checked else _SB_OFF)
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx_s = _q_idx(qs, price)
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
                _logger.warning(f"[toggle_simul] {e}")
        simul_btn.toggled.connect(_toggle_simul)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("Удалить блок")
        del_btn.setStyleSheet(_DEL_SS_HIDDEN)

        # Oral-text button styles (defined here so hover callbacks can reference them)
        # _RB_OFF / _RB_HOV / _RB_ACTIVE defined at module level
        rnd, th, price = _rnd, _th, _price
        def _delete(_, rnd=rnd, th=th, price=price, idx=_pidx, pname=_pname, it_ref=it):
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx = _q_idx(qs, price)
                q_obj_local = qs[q_idx]
                param_items = [i for i in q_obj_local["items"] if i["param"] == pname]
                deleted_item = param_items[idx] if idx < len(param_items) else None
                if deleted_item:
                    q_obj_local["items"].remove(deleted_item)
                root_xml, ns_url, tag, q_el = _xml_nav_q(siq, rnd, th, q_idx)
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
                        _unquote(fname))
                    if zip_key is None and siq._zip:
                        # _media_map miss — do a single namelist() call and scan it.
                        _nl = set(siq._zip.namelist())
                        for folder in ("Images/", "Audio/", "Video/"):
                            for candidate in (folder + fname,
                                              folder + _unquote(fname)):
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
                        with zipfile.ZipFile(siq.path, 'r') as zin:
                            with zipfile.ZipFile(tmp, 'w') as zout:
                                for info in zin.infolist():
                                    if info.filename == zip_key:
                                        continue   # skip deleted file
                                    elif info.filename == 'content.xml':
                                        xi = zipfile.ZipInfo('content.xml')
                                        xi.compress_type = zipfile.ZIP_DEFLATED
                                        zout.writestr(xi, new_xml_bytes)
                                    else:
                                        with zin.open(info) as src, zout.open(info, 'w') as dst:
                                            _shutil.copyfileobj(src, dst, length=1 << 20)
                        _safe_replace(tmp, siq.path)
                        siq._zip = zipfile.ZipFile(siq.path, 'r')
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
                _logger.warning(f"[delete_item] {e}")
        del_btn.clicked.connect(_delete)

        # ── "Oral text" toggle (for all text items - both normal and replic) ──
        replic_btn = None
        if is_text or is_replic:
            replic_btn = QPushButton("💬")
            replic_btn.setFixedSize(20, 20)
            # _RB_ACTIVE / _RB_OFF defined at module level
            tip = "Отключить устный текст" if is_replic else "Сделать устным текстом"
            replic_btn.setToolTip(tip)
            replic_btn.setStyleSheet(_RB_ACTIVE if is_replic else _RB_OFF)

            def _toggle_replic(_, rnd=_rnd, th=_th, price=_price, pidx=_pidx, pname=_pname):
                try:
                    qs = siq.rounds[rnd]["themes"][th]["questions"]
                    q_idx_s = _q_idx(qs, price)
                    param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == pname]
                    if pidx >= len(param_items): return
                    cur_placement = param_items[pidx].get("placement", "")
                    new_placement = "replic" if cur_placement != "replic" else ""
                    param_items[pidx]["placement"] = new_placement
                    root_xml, ns_url, tag, q_el = _xml_nav_q(siq, rnd, th, q_idx_s)
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
                    _logger.warning(f"[toggle_replic] {e}")
            replic_btn.clicked.connect(_toggle_replic)

        # ── Timer button ─────────────────────────────────────────
        # _TB_OFF / _TB_HOV / _TB_ON defined at module level
        existing_dur = it.get("xml_duration","")
        _tb_secs = 0
        if existing_dur:
            try:
                _p = existing_dur.strip().split(":")
                _tb_secs = int(_p[0])*3600 + int(_p[1])*60 + int(_p[2]) if len(_p)==3 else int(_p[0])*60 + int(_p[1])
            except: pass
        _tb_label = f"⏱ {_tb_secs}с" if _tb_secs > 0 else "⏱"
        timer_btn = QPushButton(_tb_label)
        timer_btn.setFixedHeight(20)
        timer_btn.setFixedWidth(56)
        timer_btn.setToolTip("Кликни для ввода таймера (секунды, 0 = убрать)")
        timer_btn.setStyleSheet(_TB_ON if existing_dur else _TB_OFF)

        def _apply_timer_secs(secs, rnd=_rnd, th=_th, price=_price, pidx=_pidx, pname=_pname,
                              btn=timer_btn):
            new_dur = f"00:{secs//60:02d}:{secs%60:02d}" if secs > 0 else ""
            btn.setText(f"⏱ {secs}с" if secs > 0 else "⏱")
            btn.setStyleSheet(_TB_ON if secs > 0 else _TB_OFF)
            btn.setVisible(True)
            try:
                qs = siq.rounds[rnd]["themes"][th]["questions"]
                q_idx_s = _q_idx(qs, price)
                param_items = [x for x in qs[q_idx_s]["items"] if x["param"] == pname]
                if pidx < len(param_items):
                    param_items[pidx]["xml_duration"] = new_dur
                root_xml, ns_url, tag, q_el = _xml_nav_q(siq, rnd, th, q_idx_s)
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
                _logger.warning(f"[set_timer] {e}")

        def _set_timer(_, btn=timer_btn, cur_secs=_tb_secs, outer_w=outer):
            # Inline editing: show QLineEdit over the button, no popup
            le = QLineEdit(str(cur_secs) if cur_secs > 0 else "0", outer_w)
            le.setAlignment(_AlignC)
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
            db.setVisible(True); db.setStyleSheet(_DEL_SS_SHOWN)
            dh.setStyleSheet(_DH_SS_SHOWN)
            sb.setVisible(True)
            sb.setStyleSheet(_SB_ON if sb.isChecked() else _SB_HOV)
            if rb:
                rb.setVisible(True)
                rb.setStyleSheet(_RB_ACTIVE if is_replic else _RB_HOV)
            tb.setVisible(True)
            tb.setStyleSheet(_TB_ON if bool(existing_dur) else _TB_HOV)
        def _on_leave(db=del_btn, dh=drag_btn, sb=simul_btn, rb=replic_btn, tb=timer_btn):
            db.setVisible(False); db.setStyleSheet(_DEL_SS_HIDDEN)
            dh.setStyleSheet(_DH_SS_HIDDEN)
            sb.setVisible(sb.isChecked())
            sb.setStyleSheet(_SB_ON if sb.isChecked() else _SB_OFF)
            if rb:
                rb.setVisible(is_replic)
                rb.setStyleSheet(_RB_ACTIVE if is_replic else _RB_OFF)
            tb.setVisible(bool(existing_dur))
            tb.setStyleSheet(_TB_ON if bool(existing_dur) else _TB_OFF)

        hf = _HoverFilter(outer, _on_enter, _on_leave)
        outer.installEventFilter(hf)
        inner.installEventFilter(hf)
        # Install on direct children of inner only (not all descendants).
        # This catches Enter events when the cursor enters a media player child,
        # without the O(n_descendants) cost of installEventFilter on every widget.
        for _child in inner.children():
            if isinstance(_child, QWidget):
                _child.installEventFilter(hf)

        return outer

    def _fill_lay(self, lay: QVBoxLayout, items: list,
                  answers: list | None = None,
                  wrong_answers: list | None = None,
                  answer_options: dict | None = None,
                  q_type: str = "",
                  answer_deviation: float = 0.1):
        self._clear_lay(lay)
        pos = 0
        param_counts: dict = {}
        for it in items:
            pname = it.get("param", "question")
            # In point mode skip answer image — rendered by PointOnImageWidget
            if q_type == "point" and pname == "answer" and it.get("type") == "image":
                continue
            idx_in_param = param_counts.get(pname, 0)
            param_counts[pname] = idx_in_param + 1
            w = self._build_deletable_item(it, idx_in_param, pname)
            if w: lay.insertWidget(pos, w); pos += 1

        if answers is None and not answer_options and q_type != "point":
            return

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#313244; max-height:1px;")
        lay.insertWidget(pos, sep); pos += 1

        # ══ Point-on-image mode ══
        if q_type == "point" and answers:
            try:
                cx, cy = map(float, answers[0].split(","))
            except Exception:
                cx, cy = 0.5, 0.5
            answer_items = [it for it in items if it.get("param") == "answer"
                            and it.get("is_ref") and it.get("type") == "image"]
            if answer_items:
                img_it = answer_items[0]
                path = self.siq.extract_media(img_it["text"])
                if path and os.path.exists(path):
                    rnd, th, price = self._current_rnd, self._current_th, self._current_price
                    pw = PointOnImageWidget(path, cx, cy, answer_deviation,
                                           siq=self.siq, rnd=rnd, th=th, price=price,
                                           viewer=self)
                    lay.insertWidget(pos, pw); pos += 1
                    return
            lbl = _lbl(f"📍  Точка ответа: ({cx:.3f}, {cy:.3f})  ±{answer_deviation:.2f}",
                       "color:#a6e3a1;font-size:13px;font-weight:600;"
                       "background:rgba(166,227,161,0.07);border-radius:4px;padding:4px 8px;")
            lay.insertWidget(pos, lbl); pos += 1
            return

        # ══ SIQ5 select mode ══
        if q_type == "select":
            KEY_LABEL = {"A":"А","B":"Б","C":"В","D":"Г","E":"Д","F":"Е"}
            correct_keys = set(answers or [])
            ordered_keys = sorted((answer_options or {}).keys())
            # ── Read-only display + inline + button ───────────────
            sel_container = QWidget(); sel_container.setStyleSheet(_SS_TRANSPARENT)
            scl = QVBoxLayout(sel_container); scl.setContentsMargins(0, 0, 0, 0); scl.setSpacing(4)
            n_total = len(ordered_keys); n_right = len(correct_keys)
            scl.addWidget(_lbl(f"Вариантов: {n_total}  ·  Правильных: {n_right}",
                               "color:#585b70;font-size:10px;padding:0 2px 2px 2px;"))
            rnd_ref = self._current_rnd; th_ref = self._current_th
            price_ref = self._current_price; viewer_ref = self
            for key in ordered_keys:
                label_txt = KEY_LABEL.get(key, key)
                is_right  = key in correct_keys
                opt_items = (answer_options or {}).get(key, [])
                row_f = QFrame()
                row_f.setStyleSheet(
                    f"QFrame{{background:{'rgba(166,227,161,0.08)' if is_right else 'rgba(255,255,255,0.03)'};"
                    f"border:1px solid {'#a6e3a1' if is_right else '#313244'};border-radius:6px;}}")
                row_l = QHBoxLayout(row_f)
                row_l.setContentsMargins(8, 5, 8, 5); row_l.setSpacing(8)
                badge = QLabel(label_txt); badge.setFixedSize(26, 26)
                badge.setAlignment(_AlignC)
                badge.setCursor(Qt.CursorShape.PointingHandCursor)
                badge.setToolTip(f"Нажмите, чтобы {'убрать как правильный' if is_right else 'сделать правильным'}")
                badge.setStyleSheet(
                    f"background:{'#a6e3a1' if is_right else '#45475a'};"
                    f"color:{'#181825' if is_right else '#a6adc8'};"
                    "border-radius:13px;font-size:12px;font-weight:700;")
                def _toggle_correct(ev, k=key, rnd=rnd_ref, th=th_ref,
                                    price=price_ref, v=viewer_ref):
                    if ev.button() != Qt.MouseButton.LeftButton: return
                    try:
                        qs = v.siq.rounds[rnd]["themes"][th]["questions"]
                        q_idx = _q_idx(qs, price)
                        q_obj3 = qs[q_idx]
                        cur_ans = list(q_obj3.get("answers", []))
                        if k in cur_ans:
                            cur_ans = []          # deselect
                        else:
                            cur_ans = [k]         # single correct answer only
                        q_obj3["answers"] = cur_ans
                        # Update XML via cached navigator
                        root_xml, ns_url, tag3, q_el = _xml_nav_q(v.siq, rnd, th, q_idx)
                        right_el = q_el.find(tag3("right"))
                        if right_el is None:
                            right_el = ET.SubElement(q_el, tag3("right"))
                        for old in right_el.findall(tag3("answer")):
                            right_el.remove(old)
                        for a_key in cur_ans:
                            ae = ET.SubElement(right_el, tag3("answer"))
                            ae.text = a_key
                        v.siq._save_xml(root_xml, ns_url)
                        q_ref3 = v.siq.find_question(rnd, th, price)
                        if q_ref3: v.show_question(q_ref3, rnd_idx=rnd, theme_idx=th)
                    except Exception as ex:
                        _logger.warning(f"[toggle_correct] {ex}")
                badge.mousePressEvent = _toggle_correct
                row_l.addWidget(badge)
                for oi in opt_items:
                    if oi["type"] == "text":
                        te_sel = QTextEdit(oi["text"] or "—")
                        te_sel.setReadOnly(False)
                        te_sel.setWordWrapMode(QTextOption.WrapMode.WordWrap)
                        te_sel.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                        te_sel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                        te_sel.setStyleSheet("QTextEdit{color:#cdd6f4;font-size:13px;"
                                             "background:transparent;border:none;padding:0;}")
                        doc_h = int(te_sel.document().size().height()) + 6
                        te_sel.setFixedHeight(max(24, doc_h))
                        row_l.addWidget(te_sel, stretch=1)
                if not any(oi["type"] == "text" for oi in opt_items):
                    row_l.addStretch(1)
                if is_right:
                    chk = QLabel("✓"); chk.setStyleSheet("color:#a6e3a1;font-size:14px;font-weight:700;background:transparent;")
                    row_l.addWidget(chk)
                scl.addWidget(row_f)
            # ── + Add option button ───────────────────────────────
            if self.siq:
                add_opt_btn = QPushButton("＋  Добавить вариант")
                add_opt_btn.setObjectName(_ON_BTN_COMPARE); add_opt_btn.setFixedHeight(24)
                def _add_inline_option(rnd=rnd_ref, th=th_ref, price=price_ref, v=viewer_ref):
                    try:
                        qs = v.siq.rounds[rnd]["themes"][th]["questions"]
                        q_idx = _q_idx(qs, price)
                        q_obj2 = qs[q_idx]
                        existing = q_obj2.get("answer_options", {})
                        # Next key
                        used_keys = set(existing.keys())
                        keys = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                        next_k = next((k for k in keys if k not in used_keys), str(len(existing)+1))
                        # Add in-memory
                        if "answer_options" not in q_obj2: q_obj2["answer_options"] = {}
                        q_obj2["answer_options"][next_k] = [{"type":"text","is_ref":False,"text":""}]
                        # Add in XML via module-level _xml_nav_q helper
                        root_xml, ns_url, tag2, q_el = _xml_nav_q(v.siq, rnd, th, q_idx)
                        params_el = q_el.find(tag2("params"))
                        if params_el is None: params_el = ET.SubElement(q_el, tag2("params"))
                        ao_el = next((p for p in params_el.findall(tag2("param")) if p.get("name") == "answerOptions"), None)
                        if ao_el is None:
                            ao_el = ET.SubElement(params_el, tag2("param")); ao_el.set("name","answerOptions")
                        sub = ET.SubElement(ao_el, tag2("param")); sub.set("name", next_k)
                        item_el = ET.SubElement(sub, tag2("item")); item_el.text = ""
                        v.siq._save_xml(root_xml, ns_url)
                        q_ref2 = v.siq.find_question(rnd, th, price)
                        if q_ref2: v.show_question(q_ref2, rnd_idx=rnd, theme_idx=th)
                    except Exception as e: _logger.warning(f"[add_inline_opt] {e}")
                add_opt_btn.clicked.connect(_add_inline_option)
                scl.addWidget(add_opt_btn)
            lay.insertWidget(pos, sel_container); pos += 1
            return

        # ══ Regular answers — shown in editable editor below; skip static display ══
        # Wrong answers (legacy) also hidden — not needed in viewer


    def _build_item(self, it: dict) -> QWidget | None:
        itype = it["type"]; text = it["text"]; is_ref = it["is_ref"]

        # Timer duration from XML attr
        dur_attr = it.get("xml_duration","")
        dur_sec_xml: float | None = _parse_hms(dur_attr) if dur_attr else None

        # Simultaneous badge (join to next) - no text suffix, only visual frame
        simul_tag = ""

        # Устный текст (placement=replic): 💬 icon + italic text, no blue frame
        if it.get("placement") == "replic":
            row = QWidget(); row.setStyleSheet(_SS_TRANSPARENT)
            rl = QHBoxLayout(row); rl.setContentsMargins(0,2,0,2); rl.setSpacing(6)
            icon = QLabel("💬"); icon.setStyleSheet("font-size:13px;background:transparent;")
            rl.addWidget(icon, 0, _AlignVC)
            lbl = QLabel(text); lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#b4befe;font-style:italic;font-size:12px;background:transparent;")
            rl.addWidget(lbl, 1)
            if dur_sec_xml is not None:
                dl = QLabel(f"⏱ {fmt_dur(dur_sec_xml)}")
                dl.setStyleSheet(_SS_BADGE_MUTED)
                rl.addWidget(dl, 0, _AlignVC)
            return row

        # Текст
        if itype == "text":
            display = text + simul_tag
            if dur_sec_xml is not None:
                row = QWidget(); row.setStyleSheet(_SS_TRANSPARENT)
                rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
                lbl = QLabel(display); lbl.setWordWrap(True)
                lbl.setStyleSheet("color:#cdd6f4; font-size:13px;")
                rl.addWidget(lbl, 1)
                dl = QLabel(f"⏱ {fmt_dur(dur_sec_xml)}")
                dl.setStyleSheet(_SS_BADGE_MUTED)
                rl.addWidget(dl, 0, _AlignVC)
                return row
            lbl = QLabel(display); lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#cdd6f4; font-size:13px;"); return lbl

        # Картинка
        if itype == "image" and is_ref:
            fname_img = text.split("/")[-1]
            path = self.siq.extract_media(text)
            wrapper = QWidget(); wrapper.setStyleSheet(_SS_TRANSPARENT)
            wrapper.setSizePolicy(_Pref, QSizePolicy.Policy.Maximum)
            wl = QVBoxLayout(wrapper); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(2)

            _img_preview_w = max(280, int(380 * _screen_scale()))

            if path and os.path.exists(path):
                # File size (fast — just stat, no read)
                try:
                    sz_b = os.path.getsize(path)
                    img_size_str = (f"  {sz_b/1_048_576:.1f} МБ" if sz_b >= 1_048_576
                                    else f"  {sz_b//1024} КБ" if sz_b > 0 else "")
                except Exception:
                    img_size_str = ""

                # ── Placeholder for the image ─────────────────────────
                img_lbl = QLabel()
                img_lbl.setFixedHeight(80)
                img_lbl.setAlignment(_AlignC)
                img_lbl.setStyleSheet("color:#585b70;font-size:11px;background:transparent;")
                img_lbl.setText("⏳  Загрузка…")
                img_lbl.setSizePolicy(_Pref, QSizePolicy.Policy.Maximum)
                wl.addWidget(img_lbl)

                # ── Filename / info label (dim+size filled in from bg thread) ──
                _fname_lbl = QLabel(f"🖼  {fname_img}{img_size_str}{simul_tag}")
                _fname_lbl.setWordWrap(True)
                _fname_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
                _fname_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                _fname_lbl.setCursor(Qt.CursorShape.IBeamCursor)
                _fname_lbl.setToolTip(f"ПКМ — скопировать имя файла: {fname_img}")
                _fname_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                def _img_fname_ctx(pos, name=fname_img, lbl=_fname_lbl):
                    menu = QMenu(lbl)
                    menu.addAction("📋  Копировать имя файла").triggered.connect(
                        lambda: QApplication.clipboard().setText(name))
                    sel = lbl.selectedText()
                    if sel:
                        menu.addAction("Копировать выделенное").triggered.connect(
                            lambda: QApplication.clipboard().setText(sel))
                    menu.exec(lbl.mapToGlobal(pos))
                _fname_lbl.customContextMenuRequested.connect(_img_fname_ctx)
                wl.addWidget(_fname_lbl)

                # ── Background thread: decode size + pixmap ───────────
                # Use the module-level singleton bridge — it is never GC'd,
                # unlike a local bridge variable which dies when _build_item returns.
                def _load_async(p=path, w=_img_preview_w,
                                dim_lbl=_fname_lbl, img_label=img_lbl,
                                fname_=fname_img, sz_str=img_size_str, simul=simul_tag):
                    iw, ih = _img_size_from_path(p)
                    if iw and ih:
                        _get_ui_bridge().deliver_text(
                            dim_lbl, f"🖼  {fname_}  {iw}×{ih}{sz_str}{simul}")
                    qimg = _load_qimage(p, w)
                    _get_ui_bridge().deliver(qimg, img_label)

                _threading.Thread(target=_load_async, daemon=True).start()
            else:
                wl.addWidget(_lbl(f"🖼  Файл не найден: {text}", "color:#f38ba8;font-size:11px;"))
                _fname_lbl = QLabel(f"🖼  {fname_img}{simul_tag}")
                _fname_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
                wl.addWidget(_fname_lbl)

            return wrapper

        # Видео / аудио
        if itype in ("video", "audio") and is_ref:
            path = self.siq.extract_media(text)
            if path and os.path.exists(path):
                fname_media = text.split("/")[-1] + simul_tag
                if itype == "video":
                    w = MpvVideoPlayerWidget(path, fname_media, it["dur"])
                else:
                    w = AudioPlayerWidget(path, fname_media, it["dur"])
                self._media_widgets.append(w)
                return w
            else:
                w = QWidget(); w.setStyleSheet("background:#1e1e2e; border-radius:6px;")
                QVBoxLayout(w).addWidget(_lbl(f"⚠  Файл не найден: {text}", "color:#f38ba8; font-size:11px;"))
                return w

        # HTML-мини-игра
        if itype == "html" and is_ref:
            fname_html = text.split("/")[-1] + simul_tag
            path = self.siq.extract_media(text)
            w = QWidget(); w.setStyleSheet("background:#1e1e2e; border-radius:6px;")
            wl = QHBoxLayout(w); wl.setContentsMargins(10, 8, 10, 8); wl.setSpacing(8)
            icon = QLabel("🌐"); icon.setStyleSheet("font-size:18px;background:transparent;")
            wl.addWidget(icon, 0, _AlignVC)

            info_col = QVBoxLayout(); info_col.setSpacing(1)
            name_lbl = QLabel(fname_html); name_lbl.setWordWrap(True)
            name_lbl.setStyleSheet("color:#cdd6f4;font-size:12px;")
            info_col.addWidget(name_lbl)
            sub = "HTML-мини-игра"
            if dur_sec_xml is not None:
                sub += f"  ⏱ {fmt_dur(dur_sec_xml)}"
            sub_lbl = QLabel(sub); sub_lbl.setStyleSheet("color:#6c7086;font-size:10px;")
            info_col.addWidget(sub_lbl)
            wl.addLayout(info_col, 1)

            if path and os.path.exists(path):
                open_btn = QPushButton("▶ Открыть")
                open_btn.setObjectName(_ON_BTN_COMPARE); open_btn.setFixedHeight(26)
                open_btn.clicked.connect(
                    lambda _, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
                wl.addWidget(open_btn, 0, _AlignVC)
            else:
                warn = QLabel("⚠ файл не найден")
                warn.setStyleSheet("color:#f38ba8;font-size:11px;")
                wl.addWidget(warn, 0, _AlignVC)
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
        vl.addWidget(_lbl("Выберите раунды для добавления неправильного ответа:",
                          "color:#cdd6f4;font-size:12px;font-weight:700;"))
        _wrong_txt_lbl = _lbl(f"Текст: \u00ab{wrong_text}\u00bb", "color:#f9e2af;font-size:11px;")
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
            pkg_item.setCheckState(0, Qt.CheckState.Unchecked)
            pkg_item.setFlags(pkg_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            pkg_item.setExpanded(True)
            for ri, rd in enumerate(siq.rounds):
                rd_item = QTreeWidgetItem(pkg_item, [rd["name"]])
                rd_item.setCheckState(0, Qt.CheckState.Unchecked)
                rd_item.setFlags(rd_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                rd_item.setData(0, Qt.ItemDataRole.UserRole, (siq, ri))
            _pkg_items.append(pkg_item)
        bot = QHBoxLayout(); bot.addStretch()
        def _set_all(state):
            for pi in _pkg_items:
                for ci in range(pi.childCount()):
                    pi.child(ci).setCheckState(0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
        sel_all = AnimatedButton("\u2713 \u0412\u0441\u0435"); sel_all.setObjectName(_ON_BTN_SORT); sel_all.setFixedHeight(24)
        sel_none = AnimatedButton("\u2717 \u0421\u043d\u044f\u0442\u044c"); sel_none.setObjectName(_ON_BTN_SORT); sel_none.setFixedHeight(24)
        sel_all.clicked.connect(lambda: _set_all(True)); sel_none.clicked.connect(lambda: _set_all(False))
        cancel_btn = AnimatedButton("\u041e\u0442\u043c\u0435\u043d\u0430"); cancel_btn.clicked.connect(dlg.reject)
        # NB: intentionally NOT objectName(_ON_BTN_ANALYZE) \u2014 main_window.py's
        # permanent "\ud83d\udd0d \u0410\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u0442\u044c" button already uses that exact objectName
        # and lives in the same widget tree (this dialog's QObject parent chain
        # runs up through it). Two live widgets sharing an objectName confuses
        # QStyleSheetStyle's rule cache and can leave one of them unpainted \u2014
        # that's what was making this button vanish. Style it inline instead.
        ok_btn = AnimatedButton("\u2192 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c")
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
            _b.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        bot.addWidget(sel_all); bot.addWidget(sel_none); bot.addWidget(cancel_btn); bot.addWidget(ok_btn)
        vl.addLayout(bot)
        dlg.adjustSize()   # recompute geometry from live font metrics, not the static minimum
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        added_count = 0
        for pi in _pkg_items:
            for ci in range(pi.childCount()):
                child = pi.child(ci)
                if child.checkState(0) != Qt.CheckState.Checked: continue
                data = child.data(0, Qt.ItemDataRole.UserRole)
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
                                wrong_el = ET.SubElement(q_el, tag("wrong"))
                            existing = [a.text or "" for a in wrong_el.findall(tag("answer"))]
                            if wrong_text not in existing:
                                ae = ET.SubElement(wrong_el, tag("answer")); ae.text = wrong_text
                    siq_t._save_xml(root_xml, ns_url)
                except Exception as ex:
                    _logger.warning(f"[propagate_wrong] {ex}")
        mw = _find_mw(self)
        if hasattr(mw, "_show_save_notification"):
            mw._save_notif.setText(f"\u2192 \u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e \u0432 {added_count} \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432")
            mw._show_save_notification()
            QTimer.singleShot(3100, lambda: mw._save_notif.setText("\u2705  \u0424\u0430\u0439\u043b \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d"))

__all__ = [
    'QuestionViewer',
]
