# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionEditorDialog. Public namespace: siquester.widgets_editors."""
import siquester.widgets_editors as _api


class QuestionEditorDialog(_api.QDialog):
    """Full-featured question editor: supports both regular and select (choice) questions."""

    saved = _api.pyqtSignal()

    _GRP_STYLE_BLUE  = ("QGroupBox{color:#89b4fa;font-size:11px;font-weight:700;"
                        "border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _GRP_STYLE_GREEN = ("QGroupBox{color:#a6e3a1;font-size:11px;font-weight:700;"
                        "border:1px solid #313244;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _GRP_STYLE_GOLD  = ("QGroupBox{color:#f9e2af;font-size:11px;font-weight:700;"
                        "border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _LE_STYLE        = ("background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
                        "border-radius:4px;padding:4px 8px;font-size:13px;")
    _TE_STYLE        = ("background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
                        "border-radius:4px;padding:4px;font-size:13px;")

    def __init__(self, siq: '_api.SiqPackage', rnd_idx: int, theme_idx: int, q_idx: int,
                 parent=None):
        super().__init__(parent)
        self.siq = siq
        self.rnd_idx = rnd_idx; self.theme_idx = theme_idx; self.q_idx = q_idx
        self.q_obj = siq.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]

        theme_name = siq.rounds[rnd_idx]["themes"][theme_idx]["name"]
        price = self.q_obj["price"]
        is_select = self.q_obj.get("q_type") == "select"
        is_point  = self.q_obj.get("q_type") == "point"
        mode = "Выбор из вариантов" if is_select else ("Точка на изображении" if is_point else "Обычный")
        self.setWindowTitle(f"Редактор — {theme_name} [{price}]  ({mode})")
        self.resize(700, 600)
        self.setStyleSheet(
            "QDialog{background:#181825;color:#cdd6f4;}"
            "QLabel{background:transparent;}"
            "QGroupBox{color:#a6adc8;font-size:11px;font-weight:700;"
            "  border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )

        # State
        self._text_edits: list     = []   # QTextEdit list for question text items
        self._ans_edits:  list     = []   # QLineEdit list for regular answers
        self._ans_container        = None
        self._option_rows: list    = []   # [(key_lbl, text_edit, correct_cb), ...]
        self._opt_container        = None
        self._qgrp_vl              = None  # direct ref to question group inner layout
        self._media_labels: list   = []    # labels showing added media files

        self._build()

    # ── Build ──────────────────────────────────────────────────
    def _build(self):

        is_select = self.q_obj.get("q_type") == "select"

        root_vl = _api.QVBoxLayout(self)
        root_vl.setContentsMargins(16, 12, 16, 12); root_vl.setSpacing(10)

        # ── Scrollable area so content fits ──────────────────────
        scroll = _api.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:#181825;")
        scroll.viewport().setStyleSheet("background:#181825;")
        inner = _api.QWidget(); inner.setStyleSheet("background:#181825;")
        vl = _api.QVBoxLayout(inner); vl.setContentsMargins(0,0,2,8); vl.setSpacing(10)
        scroll.setWidget(inner)
        root_vl.addWidget(scroll, stretch=1)

        # ── Price + mode row ────────────────────────────────────
        top_row = _api.QHBoxLayout()
        top_row.addWidget(_api._lbl("Цена:", "color:#a6adc8;font-size:12px;"))
        self._price_edit = _api.QLineEdit(str(self.q_obj["price"]))
        self._price_edit.setFixedWidth(90)
        self._price_edit.setStyleSheet(
            "background:#1e1e2e;color:#f9e2af;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px;font-size:13px;font-weight:700;")
        top_row.addWidget(self._price_edit)
        top_row.addSpacing(20)
        top_row.addWidget(_api._lbl("Тип:", "color:#a6adc8;font-size:12px;"))
        self._type_cb = _api.QComboBox()
        self._type_cb.addItem("Обычный", "normal")
        self._type_cb.addItem("Выбор из вариантов", "select")
        self._type_cb.addItem("Точка на изображении", "point")
        cur_type = self.q_obj.get("q_type", "normal") or "normal"
        idx = {"normal": 0, "select": 1, "point": 2}.get(cur_type, 0)
        self._type_cb.setCurrentIndex(idx)
        _api._style_cb(self._type_cb)
        self._type_cb.setFixedWidth(180)
        top_row.addWidget(self._type_cb)
        top_row.addStretch()
        vl.addLayout(top_row)

        # ── Question text group ─────────────────────────────────
        qgrp = _api.QGroupBox("Текст вопроса"); qgrp.setStyleSheet(self._GRP_STYLE_BLUE)
        qvl = _api.QVBoxLayout(qgrp); qvl.setSpacing(4)
        self._qgrp_vl = qvl  # store direct reference

        txt_items = [it for it in self.q_obj["items"]
                     if it["param"] == "question" and it["type"] == "text" and not it["is_ref"]]
        media_items = [it for it in self.q_obj["items"]
                       if it["param"] == "question" and it["is_ref"]]
        if txt_items:
            for it in txt_items:
                te = _api.QTextEdit(it["text"]); te.setFixedHeight(68)
                te.setStyleSheet(self._TE_STYLE)
                qvl.addWidget(te); self._text_edits.append(te)
        if media_items:
            for it in media_items:
                icon = {"image": "🖼", "audio": "🎵", "video": "🎥", "html": "🌐"}.get(it["type"], "📎")
                lbl = _api._lbl(f"{icon} {it['text']}", "color:#a6adc8;font-size:10px;padding:2px 4px;"
                           "background:#1e1e2e;border-radius:3px;")
                qvl.addWidget(lbl); self._media_labels.append(lbl)

        add_txt_btn = _api.QPushButton("＋ Добавить текст")
        add_txt_btn.setObjectName(_api._ON_BTN_COMPARE); add_txt_btn.setFixedHeight(24)
        add_txt_btn.clicked.connect(lambda: self._add_question_text(""))
        qvl.addWidget(add_txt_btn)

        # ── Media add buttons ─────────────────────────────────
        media_row = _api.QHBoxLayout(); media_row.setSpacing(6)
        for icon, label, filt, itype in [
            ("🖼", "Изображение", "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.avif)", "image"),
            ("🎵", "Аудио",       "Audio (*.mp3 *.ogg *.wav *.aac *.flac *.m4a)",   "audio"),
            ("🎥", "Видео",       "Video (*.mp4 *.avi *.mkv *.mov *.wmv *.webm)",   "video"),
            ("🌐", "HTML-игра",   "HTML (*.html *.htm)",                             "html"),
        ]:
            mb = _api.QPushButton(f"{icon} {label}")
            mb.setObjectName(_api._ON_BTN_COMPARE); mb.setFixedHeight(24)
            mb.clicked.connect(lambda _, f=filt, t=itype: self._pick_media_file(f, t, 'question'))
            media_row.addWidget(mb)
        media_row.addStretch()
        qvl.addLayout(media_row)
        vl.addWidget(qgrp)

        # ── Answer section — swaps between modes ────────────────
        self._ans_stack = _api.QStackedWidget()
        vl.addWidget(self._ans_stack)

        # ─ Regular answer panel ────────────────────────────────
        reg_w = _api.QWidget(); reg_w.setStyleSheet(_api._SS_TRANSPARENT)
        reg_vl = _api.QVBoxLayout(reg_w); reg_vl.setContentsMargins(0, 0, 0, 0); reg_vl.setSpacing(6)
        agrp = _api.QGroupBox("Правильный ответ"); agrp.setStyleSheet(self._GRP_STYLE_GREEN)
        avl = _api.QVBoxLayout(agrp); avl.setSpacing(4)
        self._ans_container = _api.QVBoxLayout(); self._ans_container.setSpacing(4)
        ans_src = self.q_obj["answers"] if not is_select else []
        for ans in ans_src:
            self._add_answer_row(ans)
        add_ans_btn = _api.QPushButton("＋ Добавить вариант")
        add_ans_btn.setObjectName(_api._ON_BTN_ANALYZE); add_ans_btn.setFixedHeight(24)
        add_ans_btn.clicked.connect(lambda: self._add_answer_row(""))
        avl.addLayout(self._ans_container); avl.addWidget(add_ans_btn)
        reg_vl.addWidget(agrp)
        self._ans_stack.addWidget(reg_w)   # index 0

        # ─ Select (choice) answer panel ────────────────────────
        sel_w = _api.QWidget(); sel_w.setStyleSheet(_api._SS_TRANSPARENT)
        sel_vl = _api.QVBoxLayout(sel_w); sel_vl.setContentsMargins(0, 0, 0, 0); sel_vl.setSpacing(6)

        sel_grp = _api.QGroupBox("Варианты ответов  (✓ = правильный)")
        sel_grp.setStyleSheet(self._GRP_STYLE_GOLD)
        sel_inner = _api.QVBoxLayout(sel_grp); sel_inner.setSpacing(4)
        self._opt_container = _api.QVBoxLayout(); self._opt_container.setSpacing(4)

        # Populate existing options or defaults
        existing_opts = self.q_obj.get("answer_options", {})
        correct_keys  = set(self.q_obj.get("answers", []))
        if existing_opts:
            for key in sorted(existing_opts.keys()):
                oi_list = existing_opts[key]
                text = oi_list[0]["text"] if oi_list else ""
                self._add_option_row(key, text, key in correct_keys)
        else:
            # Default: two options A/B
            for key, correct in [("A", True), ("B", False)]:
                self._add_option_row(key, "", correct)

        add_opt_btn = _api.QPushButton("＋ Добавить вариант")
        add_opt_btn.setObjectName(_api._ON_BTN_COMPARE); add_opt_btn.setFixedHeight(24)
        add_opt_btn.clicked.connect(self._add_next_option)
        sel_inner.addLayout(self._opt_container)
        sel_inner.addWidget(add_opt_btn)
        sel_vl.addWidget(sel_grp)
        self._ans_stack.addWidget(sel_w)   # index 1

        # ─ Point-on-image panel ─────────────────────────────────
        pt_w = _api.QWidget(); pt_w.setStyleSheet(_api._SS_TRANSPARENT)
        pt_vl = _api.QVBoxLayout(pt_w); pt_vl.setContentsMargins(0, 0, 0, 0); pt_vl.setSpacing(6)
        pt_grp = _api.QGroupBox("Точка ответа  (кликните по изображению ответа)")
        pt_grp.setStyleSheet(self._GRP_STYLE_GREEN)
        pt_inner_vl = _api.QVBoxLayout(pt_grp); pt_inner_vl.setSpacing(4)
        # Point coords input
        coords_row = _api.QHBoxLayout(); coords_row.setSpacing(6)
        coords_row.addWidget(_api._lbl("X (0–1):", "color:#a6adc8;font-size:11px;"))
        self._pt_x = _api.QLineEdit(); self._pt_x.setStyleSheet(self._LE_STYLE); self._pt_x.setFixedWidth(70)
        coords_row.addWidget(self._pt_x)
        coords_row.addWidget(_api._lbl("Y (0–1):", "color:#a6adc8;font-size:11px;"))
        self._pt_y = _api.QLineEdit(); self._pt_y.setStyleSheet(self._LE_STYLE); self._pt_y.setFixedWidth(70)
        coords_row.addWidget(self._pt_y)
        coords_row.addWidget(_api._lbl("Допуск:", "color:#a6adc8;font-size:11px;"))
        self._pt_dev = _api.QLineEdit(); self._pt_dev.setStyleSheet(self._LE_STYLE); self._pt_dev.setFixedWidth(70)
        coords_row.addWidget(self._pt_dev); coords_row.addStretch()
        pt_inner_vl.addLayout(coords_row)
        # Pre-fill from existing data
        existing_ans = self.q_obj.get("answers", [])
        if existing_ans:
            try:
                ex_cx, ex_cy = map(float, existing_ans[0].split(","))
                self._pt_x.setText(f"{ex_cx:.4f}"); self._pt_y.setText(f"{ex_cy:.4f}")
            except Exception:
                self._pt_x.setText("0.5"); self._pt_y.setText("0.5")
        else:
            self._pt_x.setText("0.5"); self._pt_y.setText("0.5")
        self._pt_dev.setText(f"{self.q_obj.get('answer_deviation', 0.1):.4f}")
        pt_vl.addWidget(pt_grp)
        self._ans_stack.addWidget(pt_w)   # index 2

        cur_idx = {"normal": 0, "select": 1, "point": 2}.get(self.q_obj.get("q_type", ""), 0)
        self._ans_stack.setCurrentIndex(cur_idx)
        self._type_cb.currentIndexChanged.connect(
            lambda i: self._ans_stack.setCurrentIndex(i))

        # ── Bottom buttons ──────────────────────────────────────
        bot = _api.QHBoxLayout(); bot.setSpacing(8); bot.addStretch()
        cancel_btn = _api.AnimatedButton("Отмена"); cancel_btn.clicked.connect(self.reject)
        save_btn = _api.AnimatedButton("💾  Сохранить"); save_btn.setObjectName(_api._ON_BTN_ANALYZE)
        save_btn.clicked.connect(self._save)
        bot.addWidget(cancel_btn); bot.addWidget(save_btn)
        root_vl.addLayout(bot)

    # ── Helpers: question text ─────────────────────────────────
    def _add_question_text(self, text: str = ""):
        te = _api.QTextEdit(text); te.setFixedHeight(68)
        te.setStyleSheet(self._TE_STYLE)
        if self._qgrp_vl:
            # Insert before the "add text" button (second-to-last item) + before media row
            # Count: last 2 items are add_txt_btn + media_row → insert before them
            insert_pos = max(0, self._qgrp_vl.count() - 2)
            self._qgrp_vl.insertWidget(insert_pos, te)
            self._text_edits.append(te)

    def _pick_media_file(self, file_filter: str, itype: str, param_name: str):
        """Open file dialog, copy picked file into the SIQ zip, refresh the label list."""
        if not self.siq.path:
            _api.msgbox_warning(self, "Нет файла", "SIQ файл не прикреплён."); return
        path, _ = _api.QFileDialog.getOpenFileName(self, "Выбрать файл", "", file_filter + ";;All (*)")
        if not path: return
        ok = self.siq.add_media_to_question(
            self.rnd_idx, self.theme_idx, self.q_idx, path, param_name)
        if ok:
            icon = {"image": "🖼", "audio": "🎵", "video": "🎥", "html": "🌐"}.get(itype, "📎")
            fname = _api.os.path.basename(path)
            lbl = _api._lbl(f"{icon} {fname}", "color:#a6adc8;font-size:10px;padding:2px 4px;"
                       "background:#1e1e2e;border-radius:3px;")
            if self._qgrp_vl:
                insert_pos = max(0, self._qgrp_vl.count() - 2)
                self._qgrp_vl.insertWidget(insert_pos, lbl)
            self._media_labels.append(lbl)
            _api.msgbox_information(self, "Добавлено", f"Файл добавлен: {fname}")
        else:
            _api.msgbox_warning(self, "Ошибка", "Не удалось добавить файл в .siq пакет.")

    # ── Helpers: regular answers ───────────────────────────────
    def _add_answer_row(self, text: str = ""):
        row = _api.QHBoxLayout(); row.setSpacing(4)
        le = _api.QLineEdit(text); le.setStyleSheet(
            "background:#1e1e2e;color:#a6e3a1;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px;font-size:13px;")
        self._ans_edits.append(le); row.addWidget(le, stretch=1)
        del_btn = _api.QPushButton("✕"); del_btn.setObjectName(_api._ON_BTN_DEL)
        del_btn.setFixedSize(22, 22)
        def _rm(le=le, del_btn=del_btn):
            if le in self._ans_edits: self._ans_edits.remove(le)
            le.deleteLater(); del_btn.deleteLater()
        del_btn.clicked.connect(lambda *_: _rm()); row.addWidget(del_btn)
        row_w = _api.QWidget(); row_w.setStyleSheet(_api._SS_TRANSPARENT)
        row_w.setLayout(row)
        self._ans_container.addWidget(row_w)

    # ── Helpers: select options ────────────────────────────────
    _OPTION_KEYS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def _next_free_key(self) -> str:
        used = {r[0] for r in self._option_rows}
        for k in self._OPTION_KEYS:
            if k not in used: return k
        return str(len(self._option_rows) + 1)

    def _add_option_row(self, key: str, text: str = "", correct: bool = False):
        row = _api.QHBoxLayout(); row.setSpacing(6)

        # Correct-answer checkbox
        cb = _api.QCheckBox(); cb.setChecked(correct)
        cb.setStyleSheet("QCheckBox::indicator{width:16px;height:16px;border-radius:8px;"
                         "border:2px solid #45475a;background:#1e1e2e;}"
                         "QCheckBox::indicator:checked{background:#a6e3a1;border-color:#a6e3a1;}")
        cb.setToolTip("Отметьте правильный вариант")
        # Single-select: uncheck others when this one is checked
        cb.toggled.connect(lambda checked, c=cb: self._on_opt_checked(c, checked))
        row.addWidget(cb)

        # Key label
        key_lbl = _api.QLabel(key)
        key_lbl.setFixedSize(24, 24)
        key_lbl.setAlignment(_api._AlignC)
        key_lbl.setStyleSheet(
            "background:#313244;color:#a6adc8;border-radius:12px;"
            "font-size:12px;font-weight:700;")
        row.addWidget(key_lbl)

        # Text input
        le = _api.QLineEdit(text); le.setStyleSheet(self._LE_STYLE)
        le.setPlaceholderText(f"Вариант {key}…")
        row.addWidget(le, stretch=1)

        # Delete button
        del_btn = _api.QPushButton("✕"); del_btn.setObjectName(_api._ON_BTN_DEL)
        del_btn.setFixedSize(22, 22)
        rec = [key, le, cb]   # mutable container so _rm can find it
        def _rm(rec=rec, del_btn=del_btn):
            if rec in self._option_rows: self._option_rows.remove(rec)
            rec[1].deleteLater(); del_btn.deleteLater()
        del_btn.clicked.connect(lambda *_: _rm()); row.addWidget(del_btn)

        row_w = _api.QWidget(); row_w.setStyleSheet(_api._SS_TRANSPARENT)
        row_w.setLayout(row)
        self._opt_container.addWidget(row_w)
        self._option_rows.append(rec)   # [key, le, cb]

    def _on_opt_checked(self, sender_cb, checked: bool):
        """Keep only one checkbox checked at a time (single-correct mode)."""
        if not checked: return
        for rec in self._option_rows:
            cb = rec[2]
            if cb is not sender_cb and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

    def _add_next_option(self):
        if len(self._option_rows) >= len(self._OPTION_KEYS): return
        self._add_option_row(self._next_free_key(), "", False)

    # ── Save ───────────────────────────────────────────────────
    def _save(self):
        try:
            new_price = int(self._price_edit.text().strip())
        except ValueError:
            _api.msgbox_warning(self, "Ошибка", "Цена должна быть целым числом."); return

        new_q_texts = [te.toPlainText().strip() for te in self._text_edits]
        cur_type = self._type_cb.currentData()
        is_select = (cur_type == "select")
        is_point  = (cur_type == "point")

        if is_point:
            # ── Point-on-image ───────────────────────────────────
            try:
                cx  = float(self._pt_x.text().strip())
                cy  = float(self._pt_y.text().strip())
                dev = float(self._pt_dev.text().strip())
            except ValueError:
                _api.msgbox_warning(self, "Ошибка", "X, Y и допуск должны быть числами от 0 до 1."); return
            ok = self.siq.save_point_question(
                self.rnd_idx, self.theme_idx, self.q_idx,
                new_price, new_q_texts, cx, cy, dev)
        elif is_select:
            # ── Select options (allow empty text, correct_key optional) ──
            options: dict[str, str] = {}
            correct_key = None
            for rec in self._option_rows:
                key = rec[0]; le = rec[1]; cb = rec[2]
                options[key] = le.text().strip()  # allow empty
                if cb.isChecked(): correct_key = key
            if not options:
                _api.msgbox_warning(self, "Ошибка", "Добавьте хотя бы один вариант."); return
            if correct_key is None and options:
                correct_key = next(iter(options))  # default to first

            ok = self.siq.save_select_question(
                self.rnd_idx, self.theme_idx, self.q_idx,
                new_price, new_q_texts, options, correct_key)
        else:
            # ── Regular question ─────────────────────────────────
            new_answers = [le.text().strip() for le in self._ans_edits if le.text().strip()]
            ok_txt   = self.siq.save_question(
                self.rnd_idx, self.theme_idx, self.q_idx, new_q_texts, new_answers)
            ok_price = True
            if new_price != self.q_obj["price"]:
                ok_price = self.siq.save_question_price(
                    self.rnd_idx, self.theme_idx, self.q_idx, new_price)
            ok = ok_txt and ok_price

        if ok:
            self.saved.emit(); self.accept()
        else:
            _api.msgbox_warning(self, "Ошибка",
                "Не удалось сохранить.\nУбедитесь, что файл не открыт другой программой.")

QuestionEditorDialog.__module__ = _api.__name__
_api.QuestionEditorDialog = QuestionEditorDialog
