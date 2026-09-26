# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MainWindow: _build_media_search_panel. Public namespace: siquester.main_window."""
import siquester.main_window as _api


def _build_media_search_panel(self) -> _api.QFrame:
    """Floating panel: lists all media files in the currently shown SIQ pack."""
    panel = _api.QFrame()
    panel.setStyleSheet(_api._SS_PANEL_BRD2)
    pl = _api.QVBoxLayout(panel); pl.setContentsMargins(12, 10, 12, 10); pl.setSpacing(8)

    # ── Header ────────────────────────────────────────────
    hdr = _api.QHBoxLayout(); hdr.setSpacing(8)
    hdr.addWidget(_api._lbl("🎬  Медиафайлы пака", "color:#cdd6f4;font-size:13px;font-weight:700;"))
    hdr.addStretch()
    close_btn = _api.QPushButton("✕"); close_btn.setObjectName(_api._ON_BTN_DEL)
    close_btn.setFixedSize(22, 22)
    close_btn.clicked.connect(self._hide_media_search)
    hdr.addWidget(close_btn)
    pl.addLayout(hdr)

    # ── Search box ────────────────────────────────────────
    self._media_search_edit = _api.QLineEdit()
    self._media_search_edit.setPlaceholderText("Фильтр по имени файла…")
    self._media_search_edit.setStyleSheet(_api._SS_INPUT_LARGE)
    self._media_search_edit.textChanged.connect(
        lambda: _api.QTimer.singleShot(100, self._run_media_search))
    pl.addWidget(self._media_search_edit)

    # ── Filters row ───────────────────────────────────────
    flt_row = _api.QHBoxLayout(); flt_row.setSpacing(10)
    flt_row.addWidget(_api._lbl("Тип:", "color:#a6adc8;font-size:11px;"))
    self._mf_cb_img   = _api.QCheckBox("Картинки");  self._mf_cb_img.setChecked(True)
    self._mf_cb_audio = _api.QCheckBox("Аудио");     self._mf_cb_audio.setChecked(True)
    self._mf_cb_video = _api.QCheckBox("Видео");     self._mf_cb_video.setChecked(True)
    for cb in (self._mf_cb_img, self._mf_cb_audio, self._mf_cb_video):
        cb.setStyleSheet("color:#a6adc8;font-size:11px;")
        cb.stateChanged.connect(self._run_media_search)
        flt_row.addWidget(cb)
    flt_row.addSpacing(8)
    flt_row.addWidget(_api._lbl("Сортировка:", "color:#a6adc8;font-size:11px;"))
    self._mf_sort_cb = _api.QComboBox()
    self._mf_sort_cb.addItems(["По умолчанию", "Размер ↑", "Размер ↓",
                                "Длительность ↑", "Длительность ↓", "Имя ↑", "Имя ↓"])
    self._mf_sort_cb.setStyleSheet(
        "QComboBox{background:#313244;color:#cdd6f4;border:1px solid #45475a;"
        "border-radius:4px;padding:2px 6px;font-size:11px;}"
        "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;}")
    self._mf_sort_cb.currentIndexChanged.connect(self._run_media_search)
    flt_row.addWidget(self._mf_sort_cb)
    flt_row.addStretch()
    self._media_count_lbl = _api._lbl("", "color:#585b70;font-size:11px;")
    flt_row.addWidget(self._media_count_lbl)
    pl.addLayout(flt_row)

    # ── Results scroll area with thumbnails ───────────────
    self._media_scroll = _api.QScrollArea()
    self._media_scroll.setWidgetResizable(True)
    self._media_scroll.setStyleSheet("border:1px solid #313244;border-radius:6px;background:#181825;")
    self._media_scroll.setMaximumHeight(16777215)
    self._media_results_widget = _api.QWidget(); self._media_results_widget.setStyleSheet("background:#181825;")
    self._media_results_vl = _api.QVBoxLayout(self._media_results_widget)
    self._media_results_vl.setContentsMargins(4,4,4,4); self._media_results_vl.setSpacing(2)
    self._media_results_vl.addStretch()
    self._media_scroll.setWidget(self._media_results_widget)
    pl.addWidget(self._media_scroll, stretch=1)
    pl.addWidget(_api._lbl("Двойной клик — перейти к вопросу с этим файлом",
                      "color:#585b70;font-size:10px;"))
    # Keep a dummy QListWidget reference for backwards compat (not shown)
    self._media_results = _api.QListWidget(); self._media_results.hide()
    return panel

def _run_media_search(self):
    """Collect all media items from current pack, filter by type/name, then sort."""
    # Clear old rows (keep stretch at end)
    vl = self._media_results_vl
    while vl.count() > 1:
        it = vl.takeAt(0)
        w = it.widget()
        if w: w.deleteLater()

    idx = self.sidebar.current_real_idx()
    if not (0 <= idx < len(self.datasets)):
        self._media_count_lbl.setText("нет пака"); return
    w = self.datasets[idx].get("widget")
    siq = w._siq if w and hasattr(w, "_siq") else None
    if not siq:
        self._media_count_lbl.setText("нет .siq"); return

    query  = self._media_search_edit.text().strip().lower()
    do_img = self._mf_cb_img.isChecked()
    do_aud = self._mf_cb_audio.isChecked()
    do_vid = self._mf_cb_video.isChecked()
    sort_i = self._mf_sort_cb.currentIndex()

    results = []
    for ri, rd in enumerate(siq.rounds):
        for ti, th in enumerate(rd["themes"]):
            th_name = th.get("name", "")
            for q in th["questions"]:
                for it in q.get("items", []):
                    if not it.get("is_ref"): continue
                    itype = it.get("type","")
                    if itype == "image" and not do_img: continue
                    if itype == "audio" and not do_aud: continue
                    if itype == "video" and not do_vid: continue
                    if itype not in ("image","audio","video"): continue
                    fname = it.get("text","")
                    base = _api._unquote(fname.split("/")[-1])
                    if query and query not in base.lower(): continue
                    path = siq.extract_media(fname)
                    if not path: continue
                    try: sz = _api.os.path.getsize(path)
                    except Exception: sz = 0
                    dur_sec = it.get("dur", 0.0)
                    results.append((itype, base, path, sz, dur_sec, th_name, q["price"], ri, ti))

    # Sort
    if sort_i == 1: results.sort(key=lambda x: x[3])
    elif sort_i == 2: results.sort(key=lambda x: x[3], reverse=True)
    elif sort_i == 3: results.sort(key=lambda x: x[4])
    elif sort_i == 4: results.sort(key=lambda x: x[4], reverse=True)
    elif sort_i == 5: results.sort(key=lambda x: x[1].lower())
    elif sort_i == 6: results.sort(key=lambda x: x[1].lower(), reverse=True)

    self._media_count_lbl.setText(f"{len(results)} файлов")

    for itype, base, path, sz, dur_sec, th_name, price, ri, ti in results:
        row_w = _api.QWidget()
        row_w.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        row_w.setStyleSheet("QWidget{background:#1e1e2e;border-radius:5px;}"
                            "QWidget:hover{background:#313244;}")
        row_l = _api.QHBoxLayout(row_w); row_l.setContentsMargins(6,4,6,4); row_l.setSpacing(8)

        # ── Thumbnail (48×36 for image/video, waveform icon for audio) ──
        thumb_lbl = _api.QLabel()
        thumb_lbl.setFixedSize(64, 48)
        thumb_lbl.setAlignment(_api._AlignC)
        thumb_lbl.setStyleSheet("background:#181825;border-radius:3px;color:#585b70;font-size:18px;")
        if itype == "image":
            try:
                reader = _api.QImageReader(path); reader.setAutoTransform(True)
                img = reader.read()
                if not img.isNull():
                    pm = _api.QPixmap.fromImage(img).scaled(
                        64, 48, _api.Qt.AspectRatioMode.KeepAspectRatio,
                        _api.Qt.TransformationMode.SmoothTransformation)
                    thumb_lbl.setPixmap(pm)
                else:
                    thumb_lbl.setText("🖼")
            except Exception:
                thumb_lbl.setText("🖼")
        elif itype == "video":
            # Try to get first frame via QImageReader (works for some formats)
            thumb_lbl.setText("🎬")
            try:
                reader = _api.QImageReader(path); reader.setAutoTransform(True)
                img = reader.read()
                if not img.isNull():
                    pm = _api.QPixmap.fromImage(img).scaled(
                        64, 48, _api.Qt.AspectRatioMode.KeepAspectRatio,
                        _api.Qt.TransformationMode.SmoothTransformation)
                    thumb_lbl.setPixmap(pm)
            except Exception:
                pass
        else:
            thumb_lbl.setText("🎵")
        row_l.addWidget(thumb_lbl)

        # ── Info ──────────────────────────────────────────────
        info_col = _api.QVBoxLayout(); info_col.setSpacing(2)
        sz_str = (f"{sz/1_048_576:.1f} МБ" if sz >= 1_048_576
                  else f"{sz//1024} КБ" if sz > 0 else "")
        dur_str = _api.fmt_dur(dur_sec) if dur_sec > 0 else ""
        meta = "  ·  ".join(filter(None, [sz_str, dur_str]))

        name_lbl = _api.QLabel(base)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet("color:#cdd6f4;font-size:11px;font-weight:600;background:transparent;")
        name_lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.NoTextInteraction)
        info_col.addWidget(name_lbl)

        sub_lbl = _api.QLabel(f"{th_name}  [{price}]" + (f"   {meta}" if meta else ""))
        sub_lbl.setStyleSheet(_api._SS_LABEL_DIM)
        info_col.addWidget(sub_lbl)
        row_l.addLayout(info_col, stretch=1)

        # ── Double-click to navigate ───────────────────────────
        _nav_data = (idx, ri, ti, price)
        def _dbl(ev, nd=_nav_data, mw=self):
            if ev.type() == ev.Type.MouseButtonDblClick:
                mw._media_result_activated_data(nd)
        row_w.mouseDoubleClickEvent = _dbl

        vl.insertWidget(vl.count() - 1, row_w)   # before the stretch

def _media_result_activated_data(self, data):
    ds_idx, ri, ti, price = data
    if not (0 <= ds_idx < len(self.datasets)): return
    self.sidebar.select_by_real(ds_idx)
    self._show_ds(ds_idx)
    w = self.datasets[ds_idx]["widget"]
    _api.QTimer.singleShot(80, lambda ri=ri, ti=ti, p=price:
                      w._on_question_clicked(ri, ti, p))

def _on_search_text_changed(self):
    _api.QTimer.singleShot(120, self._run_search)

def _run_search(self):
    query = self._search_edit.text().strip().lower()
    self._search_results.clear()
    if not query:
        self._search_count_lbl.setText(""); return

    do_q   = self._search_cb_q.isChecked()
    do_ans = self._search_cb_ans.isChecked()
    do_th  = self._search_cb_th.isChecked()
    results = []

    for ds_idx, ds in enumerate(self.datasets):
        pkg_name = ds.get("pkg_name", "?")
        w = ds.get("widget")
        siq = w._siq if w and hasattr(w, "_siq") else None
        rounds = siq.rounds if siq else []

        for ri, rd in enumerate(rounds):
            rnd_name = rd.get("name", f"Раунд {ri+1}")
            for ti, th in enumerate(rd["themes"]):
                th_name = th.get("name", "")
                if do_th and query in th_name.lower():
                    th_all_t = [q.get("tries",0) for q in th["questions"]]
                    th_all_r = [q.get("right",0) for q in th["questions"]]
                    th_avg_t = sum(th_all_t)/len(th_all_t) if th_all_t else 0
                    th_avg_r = sum(th_all_r)/len(th_all_r) if th_all_r else 0
                    th_stats = f"  🟡{th_avg_t:.0f}% 🟢{th_avg_r:.0f}%" if th_all_t else ""
                    results.append((
                        f"📚  {pkg_name}  ›  {rnd_name}  ›  {th_name}{th_stats}",
                        ds_idx, ri, ti, -1))
                for q in th["questions"]:
                    items = q.get("items", [])
                    price = q["price"]
                    q_hit = False
                    if do_q:
                        q_texts = " ".join(
                            it.get("text","") for it in items
                            if it.get("param") in ("question","background")
                            and it.get("type") == "text" and not it.get("is_ref"))
                        q_hit = query in q_texts.lower()
                    ans_hit = False
                    if do_ans:
                        all_ans = " ".join(q.get("answers",[]) + q.get("wrong_answers",[]))
                        ans_par = " ".join(it.get("text","") for it in items
                                           if it.get("param") == "answer"
                                           and it.get("type") == "text"
                                           and not it.get("is_ref"))
                        ans_hit = query in (all_ans + " " + ans_par).lower()
                    if q_hit or ans_hit:
                        tag_icon = "❓" if q_hit else "✅"
                        # Build preview: show matched answer text if ans_hit, else question text
                        if ans_hit and not q_hit:
                            # Find the specific matching answer
                            all_ans_list = q.get("answers", []) + q.get("wrong_answers", [])
                            ans_param_texts = [it.get("text","").strip() for it in items
                                               if it.get("param") == "answer"
                                               and it.get("type") == "text"
                                               and not it.get("is_ref")
                                               and it.get("text","").strip()]
                            all_ans_list += ans_param_texts
                            matched_ans = next((a for a in all_ans_list if query in a.lower()), "")
                            preview = matched_ans[:80] + ("…" if len(matched_ans) > 80 else "")
                        else:
                            preview = " / ".join(
                                it.get("text","").strip() for it in items
                                if it.get("param") in ("question","background")
                                and it.get("type") == "text" and not it.get("is_ref")
                                and it.get("text","").strip())
                            if len(preview) > 80: preview = preview[:80] + "…"

                        # Build stats suffix
                        pct_t = q.get("tries", 0)
                        pct_r = q.get("right", 0)
                        stats_str = f"  🟡{pct_t}% 🟢{pct_r}%" if (pct_t or pct_r) else ""

                        # Format: pkg › theme · [price]  preview  stats
                        line = f"{tag_icon}  {pkg_name}  ›  {th_name}  ·  [{price}]{stats_str}"
                        if preview:
                            line += f"   {preview}"
                        results.append((line, ds_idx, ri, ti, price))

    MAX = 250
    total = len(results)
    self._search_count_lbl.setText(
        f"{total} совпад." if total <= MAX else f"{MAX}+ совпад.")
    for text, ds_idx, ri, ti, price in results[:MAX]:
        item = _api.QListWidgetItem(text)
        item.setData(_api.Qt.ItemDataRole.UserRole, (ds_idx, ri, ti, price))
        self._search_results.addItem(item)
