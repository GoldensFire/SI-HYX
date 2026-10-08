# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api
from si_hyx_parts.siquester.widgets_question.question_items import QuestionViewerItemsMixin


class QuestionViewer(QuestionViewerItemsMixin, _api.QWidget):
    edit_requested = _api.pyqtSignal(int, int, int)   # rnd_idx, theme_idx, price

    def __init__(self, siq: _api.SiqPackage, parent=None):
        super().__init__(parent)
        self.siq = siq
        self.setStyleSheet("background:#181825;")
        self._media_widgets: list = []
        self._current_rnd = 0
        self._current_th = 0
        self._current_price = 0
        self.setAcceptDrops(True)

        root = _api.QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────
        hdr_row = _api.QHBoxLayout(); hdr_row.setContentsMargins(0, 0, 0, 0); hdr_row.setSpacing(0)
        self._hdr = _api.QLabel("← Нажмите на цену вопроса в таблице")
        self._hdr.setStyleSheet(
            "color:#a6adc8; font-size:12px; font-weight:500;"
            "background:#1e1e2e; padding:8px 14px; border-bottom:1px solid #313244;")
        hdr_row.addWidget(self._hdr, stretch=1)

        self._edit_btn = _api.QPushButton("✏  Изменить")
        self._edit_btn.setObjectName(_api._ON_BTN_UPDATE)
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
        self._scroll = _api.QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border:none; background:#181825;")
        self._scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setStyleSheet("background:#181825;")
        _api._install_wheel_filter(self._scroll)

        self._content_w = _api.QWidget(); self._content_w.setStyleSheet("background:#181825;")
        self._content_vl = _api.QVBoxLayout(self._content_w)
        self._content_vl.setContentsMargins(0,0,0,12); self._content_vl.setSpacing(0)

        # ВОПРОС section
        q_hdr = _api.QLabel("ВОПРОС")
        q_hdr.setStyleSheet(_api._SS_TOPBAR_LABEL)
        self._content_vl.addWidget(q_hdr)
        self._q_inner = _api.QWidget(); self._q_inner.setStyleSheet("background:#181825;")
        self._q_inner.setAcceptDrops(True)
        self._q_inner.dragEnterEvent = self._section_drag_enter
        self._q_inner.dragLeaveEvent = lambda e, w=self._q_inner: self._section_drag_leave(w)
        self._q_inner.dropEvent      = self.dropEvent
        self._q_lay = _api.QVBoxLayout(self._q_inner)
        self._q_lay.setContentsMargins(10,10,10,10); self._q_lay.setSpacing(6)
        self._content_vl.addWidget(self._q_inner)

        # Separator
        sep = _api.QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#313244; margin:0;")
        self._content_vl.addWidget(sep)

        # ОТВЕТ section
        a_hdr = _api.QLabel("ОТВЕТ")
        a_hdr.setStyleSheet(_api._SS_TOPBAR_LABEL)
        self._content_vl.addWidget(a_hdr)
        self._a_inner = _api.QWidget(); self._a_inner.setStyleSheet("background:#181825;")
        self._a_inner.setAcceptDrops(True)
        self._a_inner.dragEnterEvent = self._section_drag_enter
        self._a_inner.dragLeaveEvent = lambda e, w=self._a_inner: self._section_drag_leave(w)
        # Force param_name="answer" for any file dropped directly onto the answer section
        def _a_inner_drop(ev, _self=self):
            md = ev.mimeData()
            if md.hasFormat(_api._MIME_BLOCK) and _self._current_price:
                _self.dropEvent(ev); return
            if md.hasUrls() and _self._current_price:
                rnd, th, price = _self._current_rnd, _self._current_th, _self._current_price
                try:
                    qs = _self.siq.rounds[rnd]["themes"][th]["questions"]
                    q_idx = _api._q_idx(qs, price)
                except (StopIteration, Exception):
                    return
                for url in md.urls():
                    path = url.toLocalFile()
                    if _api.Path(path).suffix.lower() in _api._MEDIA_EXTS:
                        _self._do_add_media(rnd, th, q_idx, path, param_name="answer")
                ev.acceptProposedAction()
                _self._clear_section_highlights()
        self._a_inner.dropEvent = _a_inner_drop
        self._a_lay = _api.QVBoxLayout(self._a_inner)
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
            except Exception as _e: _api._logger.debug(str(_e))
            self._copy_hl_clear = None
        super().mousePressEvent(ev)

    def _section_drag_enter(self, ev):
        """Highlight drop target section while dragging a block."""
        md = ev.mimeData()
        if md.hasFormat(_api._MIME_BLOCK) or (md.hasUrls() and self._current_price):
            # Highlight whichever section received the dragEnter
            # We re-use existing dropEvent — just highlight visually
            ev.acceptProposedAction()
            # Use the widget the event was installed on
            for section_w in (self._q_inner, self._a_inner):
                rect = section_w.rect()
                tl = section_w.mapToGlobal(rect.topLeft())
                gp = section_w.mapFromGlobal(ev.position().toPoint() if hasattr(ev, 'position') else tl)
                if rect.contains(gp):
                    section_w.setStyleSheet("background:rgba(137,180,250,0.08);border:1px solid rgba(137,180,250,0.3);border-radius:4px;")
                    break

    def _section_drag_leave(self, widget: _api.QWidget):
        widget.setStyleSheet("background:#181825;")

    def show_question(self, q_obj: dict, rnd_idx: int = 0, theme_idx: int = 0):
        price = q_obj["price"]; dur = q_obj["dur"]
        self._hdr.setText(f"Вопрос  •  Цена: {price}  •  ⏱ {_api.fmt_dur(dur)}")
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
                           ("." not in w or _api.Path(w.strip()).suffix.lower() not in _api._MEDIA_EXTS)]
            answers_snap = q_obj.get("answers", [])
            _api.QTimer.singleShot(0, lambda a=answers_snap, w=clean_wrong:
                              self._rebuild_answer_editor(a, w))
        _api.QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(0))

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

    def _fill_lay(self, lay: _api.QVBoxLayout, items: list,
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

        sep = _api.QFrame(); sep.setFrameShape(_api.QFrame.Shape.HLine)
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
                if path and _api.os.path.exists(path):
                    rnd, th, price = self._current_rnd, self._current_th, self._current_price
                    pw = _api.PointOnImageWidget(path, cx, cy, answer_deviation,
                                           siq=self.siq, rnd=rnd, th=th, price=price,
                                           viewer=self)
                    lay.insertWidget(pos, pw); pos += 1
                    return
            lbl = _api._lbl(f"📍  Точка ответа: ({cx:.3f}, {cy:.3f})  ±{answer_deviation:.2f}",
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
            sel_container = _api.QWidget(); sel_container.setStyleSheet(_api._SS_TRANSPARENT)
            scl = _api.QVBoxLayout(sel_container); scl.setContentsMargins(0, 0, 0, 0); scl.setSpacing(4)
            n_total = len(ordered_keys); n_right = len(correct_keys)
            scl.addWidget(_api._lbl(f"Вариантов: {n_total}  ·  Правильных: {n_right}",
                               "color:#585b70;font-size:10px;padding:0 2px 2px 2px;"))
            rnd_ref = self._current_rnd; th_ref = self._current_th
            price_ref = self._current_price; viewer_ref = self
            for key in ordered_keys:
                label_txt = KEY_LABEL.get(key, key)
                is_right  = key in correct_keys
                opt_items = (answer_options or {}).get(key, [])
                row_f = _api.QFrame()
                row_f.setStyleSheet(
                    f"QFrame{{background:{'rgba(166,227,161,0.08)' if is_right else 'rgba(255,255,255,0.03)'};"
                    f"border:1px solid {'#a6e3a1' if is_right else '#313244'};border-radius:6px;}}")
                row_l = _api.QHBoxLayout(row_f)
                row_l.setContentsMargins(8, 5, 8, 5); row_l.setSpacing(8)
                badge = _api.QLabel(label_txt); badge.setFixedSize(26, 26)
                badge.setAlignment(_api._AlignC)
                badge.setCursor(_api.Qt.CursorShape.PointingHandCursor)
                badge.setToolTip(f"Нажмите, чтобы {'убрать как правильный' if is_right else 'сделать правильным'}")
                badge.setStyleSheet(
                    f"background:{'#a6e3a1' if is_right else '#45475a'};"
                    f"color:{'#181825' if is_right else '#a6adc8'};"
                    "border-radius:13px;font-size:12px;font-weight:700;")
                def _toggle_correct(ev, k=key, rnd=rnd_ref, th=th_ref,
                                    price=price_ref, v=viewer_ref):
                    if ev.button() != _api.Qt.MouseButton.LeftButton: return
                    try:
                        qs = v.siq.rounds[rnd]["themes"][th]["questions"]
                        q_idx = _api._q_idx(qs, price)
                        q_obj3 = qs[q_idx]
                        cur_ans = list(q_obj3.get("answers", []))
                        if k in cur_ans:
                            cur_ans = []          # deselect
                        else:
                            cur_ans = [k]         # single correct answer only
                        q_obj3["answers"] = cur_ans
                        # Update XML via cached navigator
                        root_xml, ns_url, tag3, q_el = _api._xml_nav_q(v.siq, rnd, th, q_idx)
                        right_el = q_el.find(tag3("right"))
                        if right_el is None:
                            right_el = _api.ET.SubElement(q_el, tag3("right"))
                        for old in right_el.findall(tag3("answer")):
                            right_el.remove(old)
                        for a_key in cur_ans:
                            ae = _api.ET.SubElement(right_el, tag3("answer"))
                            ae.text = a_key
                        v.siq._save_xml(root_xml, ns_url)
                        q_ref3 = v.siq.find_question(rnd, th, price)
                        if q_ref3: v.show_question(q_ref3, rnd_idx=rnd, theme_idx=th)
                    except Exception as ex:
                        _api._logger.warning(f"[toggle_correct] {ex}")
                badge.mousePressEvent = _toggle_correct
                row_l.addWidget(badge)
                for oi in opt_items:
                    if oi["type"] == "text":
                        te_sel = _api.QTextEdit(oi["text"] or "—")
                        te_sel.setReadOnly(False)
                        te_sel.setWordWrapMode(_api.QTextOption.WrapMode.WordWrap)
                        te_sel.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                        te_sel.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                        te_sel.setStyleSheet("QTextEdit{color:#cdd6f4;font-size:13px;"
                                             "background:transparent;border:none;padding:0;}")
                        doc_h = int(te_sel.document().size().height()) + 6
                        te_sel.setFixedHeight(max(24, doc_h))
                        row_l.addWidget(te_sel, stretch=1)
                if not any(oi["type"] == "text" for oi in opt_items):
                    row_l.addStretch(1)
                if is_right:
                    chk = _api.QLabel("✓"); chk.setStyleSheet("color:#a6e3a1;font-size:14px;font-weight:700;background:transparent;")
                    row_l.addWidget(chk)
                scl.addWidget(row_f)
            # ── + Add option button ───────────────────────────────
            if self.siq:
                add_opt_btn = _api.QPushButton("＋  Добавить вариант")
                add_opt_btn.setObjectName(_api._ON_BTN_COMPARE); add_opt_btn.setFixedHeight(24)
                def _add_inline_option(rnd=rnd_ref, th=th_ref, price=price_ref, v=viewer_ref):
                    try:
                        qs = v.siq.rounds[rnd]["themes"][th]["questions"]
                        q_idx = _api._q_idx(qs, price)
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
                        root_xml, ns_url, tag2, q_el = _api._xml_nav_q(v.siq, rnd, th, q_idx)
                        params_el = q_el.find(tag2("params"))
                        if params_el is None: params_el = _api.ET.SubElement(q_el, tag2("params"))
                        ao_el = next((p for p in params_el.findall(tag2("param")) if p.get("name") == "answerOptions"), None)
                        if ao_el is None:
                            ao_el = _api.ET.SubElement(params_el, tag2("param")); ao_el.set("name","answerOptions")
                        sub = _api.ET.SubElement(ao_el, tag2("param")); sub.set("name", next_k)
                        item_el = _api.ET.SubElement(sub, tag2("item")); item_el.text = ""
                        v.siq._save_xml(root_xml, ns_url)
                        q_ref2 = v.siq.find_question(rnd, th, price)
                        if q_ref2: v.show_question(q_ref2, rnd_idx=rnd, theme_idx=th)
                    except Exception as e: _api._logger.warning(f"[add_inline_opt] {e}")
                add_opt_btn.clicked.connect(_add_inline_option)
                scl.addWidget(add_opt_btn)
            lay.insertWidget(pos, sel_container); pos += 1
            return


QuestionViewer.__module__ = _api.__name__
_api.QuestionViewer = QuestionViewer
