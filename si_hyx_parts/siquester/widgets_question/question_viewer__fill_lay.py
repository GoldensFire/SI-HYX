# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: _fill_lay. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


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
