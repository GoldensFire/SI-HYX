# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: _build_item. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


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
