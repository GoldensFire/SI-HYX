# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _build_tile_view. Public namespace: siquester.result_page."""
import siquester.result_page as _api


# ── Tile view ─────────────────────────────────────────
def _build_tile_view(self, cl: _api.QVBoxLayout):
    has_siq = self._siq is not None
    # Плитки не добавляем сразу — собираем сюда (area, q_fulls, has_siq) и
    # заполняем синхронно или порциями (см. _rebuild_content/_start_tile_fill).
    self._pending_tile_fills = []
    # Cache scale factor once — constant for the entire build pass.
    _scale         = _api._screen_scale()
    _th_label_w_px = max(200, int(420 * _scale))
    # Round MIME type — module-level string, assign local for fast closure capture
    _RND_MIME = "application/x-siq-round"

    for r_idx, rd in enumerate(self.ds["rounds"]):
        # Accumulate round stats inline — avoid building a flat list just for sum/len.
        n_flat = t_sum = r_sum = 0
        for th in rd["themes"]:
            for q in th["questions"]:
                n_flat += 1
                t_sum  += q.get("tries", 0)
                r_sum  += q.get("right", 0)
        r_t = t_sum / n_flat if n_flat else 0
        r_r = r_sum / n_flat if n_flat else 0

        rnd_hdr=_api.QFrame(); rnd_hdr.setFixedHeight(36)
        rnd_hdr.setStyleSheet("background:#1e1e2e;border-radius:6px;border:1px solid #313244;")
        rnd_hdr.setAcceptDrops(True)

        # Drop protocol for round reorder
        def _rnd_drag_enter(ev, mime=_RND_MIME):
            if ev.mimeData().hasFormat(mime): ev.acceptProposedAction()
        def _rnd_drop(ev, ri=r_idx, mime=_RND_MIME):
            if not ev.mimeData().hasFormat(mime): return
            src_r = int(bytes(ev.mimeData().data(mime)).decode())
            ev.acceptProposedAction()
            if src_r != ri:
                _api.QTimer.singleShot(0, lambda sr=src_r: self._move_round(sr, ri))
        rnd_hdr.dragEnterEvent = _rnd_drag_enter
        rnd_hdr.dropEvent      = _rnd_drop

        rh=_api.QHBoxLayout(rnd_hdr); rh.setContentsMargins(8,0,8,0); rh.setSpacing(6)

        # Drag handle for round
        if self._siq:
            rnd_dh = _api.QPushButton("⠿"); rnd_dh.setFixedSize(14, 22)
            rnd_dh.setCursor(_api.Qt.CursorShape.SizeAllCursor)
            rnd_dh.setStyleSheet(_api._DH_SS_HIDDEN)
            def _rnd_dh_press(ev, h=rnd_dh): h._drag_origin = ev.position().toPoint() if ev.button() == _api.Qt.MouseButton.LeftButton else None
            def _rnd_dh_move(ev, h=rnd_dh, ri=r_idx, hdr=rnd_hdr):
                if not getattr(h,'_drag_origin',None): return
                if (ev.position().toPoint()-h._drag_origin).manhattanLength() < 5: return
                h._drag_origin = None
                mime = _api.QMimeData(); mime.setData(_RND_MIME, _api.QByteArray(str(ri).encode()))
                d = _api.QDrag(h); d.setMimeData(mime)
                pm = hdr.grab(); d.setPixmap(pm); d.setHotSpot(pm.rect().center())
                hdr.setVisible(False)
                d.exec(_api.Qt.DropAction.MoveAction)
                try: hdr.setVisible(True)
                except RuntimeError: pass
            rnd_dh.mousePressEvent = _rnd_dh_press
            rnd_dh.mouseMoveEvent  = _rnd_dh_move
            def _rnd_hdr_enter(ev, h=rnd_dh): h.setStyleSheet(_api._DH_SS_SHOWN)
            def _rnd_hdr_leave(ev, h=rnd_dh): h.setStyleSheet(_api._DH_SS_HIDDEN)
            rnd_hdr.enterEvent = _rnd_hdr_enter
            rnd_hdr.leaveEvent = _rnd_hdr_leave
            rh.addWidget(rnd_dh)
        # Inline editable round name (centered, stats on right side)
        rnd_edit = _api.QLineEdit(rd['round_name'])
        rnd_edit.setAlignment(_api._AlignC)
        rnd_edit.setStyleSheet(
            "QLineEdit{background:transparent;color:#cdd6f4;font-size:13px;font-weight:700;"
            "border:none;padding:0 4px;}"
            "QLineEdit:focus{background:#181825;border:1px solid #89b4fa;border-radius:4px;}")
        rnd_edit.setToolTip("Кликните для редактирования названия раунда")
        def _rnd_edit_done(le=rnd_edit, i=r_idx):
            new = le.text().strip()
            if new:
                self.ds["rounds"][i]["round_name"] = new
                if self._siq:
                    try: self._siq.save_round_name(i, new)
                    except Exception as e: _api._logger.warning(f"[rename_round] {e}")
                mw = self._mw_ref
                _api._schedule_save(mw)
        rnd_edit.editingFinished.connect(_rnd_edit_done)
        rh.addWidget(rnd_edit, stretch=1)
        rh.addSpacing(8)
        rh.addWidget(_api._lbl(f"🟡{r_t:.0f}%","color:#f9e2af;font-size:11px;"))
        rh.addSpacing(4)
        rh.addWidget(_api._lbl(f"🟢{r_r:.0f}%","color:#a6e3a1;font-size:11px;"))
        rh.addStretch()
        if self._siq:
            # ── Final round toggle button ─────────────────────────
            siq_rnd = self._siq.rounds[r_idx] if r_idx < len(self._siq.rounds) else {}
            is_final = siq_rnd.get("type","") == "final"
            final_btn = _api.QPushButton("🏆 ФИНАЛ" if is_final else "🏆")
            final_btn.setCheckable(True); final_btn.setChecked(is_final)
            final_btn.setFixedHeight(22)
            final_btn.setToolTip("Переключить тип раунда: финал / обычный")
            final_btn.setStyleSheet(
                "QPushButton{background:rgba(249,226,175,0.25);color:#f9e2af;"
                "border:1px solid #f9e2af;border-radius:4px;font-size:10px;padding:0 6px;}"
                "QPushButton:!checked{background:transparent;color:#585b70;"
                "border:1px solid #45475a;}"
                "QPushButton:hover{background:rgba(249,226,175,0.15);color:#f9e2af;border-color:#f9e2af;}")
            def _toggle_final(checked, ri=r_idx, btn=final_btn):
                new_type = "final" if checked else ""
                btn.setText("🏆 ФИНАЛ" if checked else "🏆")
                cur_comment = self._siq.rounds[ri].get("comment","") if ri < len(self._siq.rounds) else ""
                self._siq.save_round_info(ri, new_type, cur_comment)
                if ri < len(self.ds["rounds"]):
                    self.ds["rounds"][ri]["round_type"] = new_type
                mw = self._mw_ref
                _api._schedule_save(mw)
            final_btn.toggled.connect(_toggle_final)
            rh.addWidget(final_btn)

            # ── Exclude-from-stats toggle ─────────────────────────
            _excl = rd.get("stats_excluded", False)
            excl_btn = _api.QPushButton("📊")
            excl_btn.setCheckable(True); excl_btn.setChecked(_excl)
            excl_btn.setFixedHeight(22)
            excl_btn.setToolTip(
                "Исключить раунд из общей статистики пака (попытки / правильные)" if not _excl
                else "Раунд исключён из статистики — нажмите чтобы включить обратно")
            _EXCL_ON  = ("QPushButton{background:rgba(243,139,168,0.20);color:#f38ba8;"
                         "border:1px solid #f38ba8;border-radius:4px;font-size:10px;padding:0 6px;}"
                         "QPushButton:hover{background:rgba(243,139,168,0.35);}")
            _EXCL_OFF = ("QPushButton{background:transparent;color:#585b70;"
                         "border:1px solid #45475a;border-radius:4px;font-size:10px;padding:0 6px;}"
                         "QPushButton:hover{background:rgba(137,180,250,0.10);color:#89b4fa;border-color:#89b4fa;}")
            excl_btn.setStyleSheet(_EXCL_ON if _excl else _EXCL_OFF)
            def _toggle_excl(checked, ri=r_idx, btn=excl_btn,
                             on_ss=_EXCL_ON, off_ss=_EXCL_OFF):
                self.ds["rounds"][ri]["stats_excluded"] = checked
                btn.setStyleSheet(on_ss if checked else off_ss)
                btn.setToolTip(
                    "Раунд исключён из статистики — нажмите чтобы включить обратно" if checked
                    else "Исключить раунд из общей статистики пака (попытки / правильные)")
                # Invalidate banner stats cache and refresh
                self._banner_stats_key += 1
                self._refresh_banner_widget()
                mw = self._mw_ref
                _api._schedule_save(mw)
            excl_btn.toggled.connect(_toggle_excl)
            rh.addWidget(excl_btn)
            # ── Round comment button ──────────────────────────────
            cur_comment = siq_rnd.get("comment","")
            rnd_comm_btn = _api.QPushButton()
            rnd_comm_btn.setText("Комм")
            rnd_comm_btn.setFixedSize(36, 22)
            rnd_comm_btn.setToolTip(f"Комментарий раунда: {cur_comment}" if cur_comment
                                    else "Добавить комментарий к раунду")
            rnd_comm_btn.setStyleSheet(
                f"QPushButton{{background:{'rgba(137,180,250,0.15)' if cur_comment else 'transparent'};"
                f"color:{'#89b4fa' if cur_comment else '#585b70'};"
                "border:1px solid #45475a;border-radius:4px;font-size:9px;font-weight:600;padding:0 3px;}"
                "QPushButton:hover{background:rgba(137,180,250,0.15);color:#89b4fa;border-color:#89b4fa;}")
            def _edit_rnd_comment(_, ri=r_idx, btn=rnd_comm_btn):
                siq_r = self._siq.rounds[ri] if ri < len(self._siq.rounds) else {}
                cur = siq_r.get("comment","")
                text, ok = _api.QInputDialog.getMultiLineText(
                    self, "Комментарий раунда",
                    f"Комментарий для раунда «{self.ds['rounds'][ri].get('round_name','?')}»:",
                    cur)
                if not ok: return
                cur_type = siq_r.get("type","")
                self._siq.save_round_info(ri, cur_type, text.strip())
                btn.setToolTip(f"Комментарий: {text.strip()}" if text.strip() else "Добавить комментарий к раунду")
                has_c = bool(text.strip())
                btn.setStyleSheet(
                    f"QPushButton{{background:{'rgba(137,180,250,0.15)' if has_c else 'transparent'};"
                    f"color:{'#89b4fa' if has_c else '#585b70'};"
                    "border:1px solid #45475a;border-radius:4px;font-size:9px;font-weight:600;padding:0 3px;}"
                    "QPushButton:hover{background:rgba(137,180,250,0.15);color:#89b4fa;border-color:#89b4fa;}")
                mw = self._mw_ref
                _api._schedule_save(mw)
            rnd_comm_btn.clicked.connect(_edit_rnd_comment)
            rh.addWidget(rnd_comm_btn)
            # ── Change-prices button ──────────────────────────────
            price_btn = _api.QPushButton("💰")
            price_btn.setFixedSize(24, 24)
            price_btn.setToolTip("Изменить цены вопросов в раунде "
                                 "(мин / макс / шаг)")
            price_btn.setStyleSheet(
                "QPushButton{background:transparent;color:#f9e2af;"
                "border:1px solid #45475a;border-radius:4px;font-size:11px;}"
                "QPushButton:hover{background:rgba(249,226,175,0.15);"
                "border-color:#f9e2af;}")
            price_btn.clicked.connect(
                lambda _, i=r_idx: self._on_change_round_prices(i))
            rh.addWidget(price_btn)
            del_rnd2 = _api.QPushButton("🗑")
            del_rnd2.setObjectName(_api._ON_BTN_DEL); del_rnd2.setFixedSize(24, 24)
            del_rnd2.setToolTip("Удалить раунд")
            del_rnd2.clicked.connect(lambda _, i=r_idx: self._delete_round(i))
            rh.addWidget(del_rnd2)
        cl.addWidget(rnd_hdr)
        # ── Round comment label (shown below header if comment present) ───
        if self._siq:
            siq_rnd2 = self._siq.rounds[r_idx] if r_idx < len(self._siq.rounds) else {}
            if siq_rnd2.get("comment",""):
                comm_bar = _api.QLabel(f"💬  {siq_rnd2['comment']}")
                comm_bar.setWordWrap(True)
                comm_bar.setStyleSheet(
                    "background:rgba(137,180,250,0.07);color:#b4befe;font-size:10px;"
                    "border-left:2px solid #89b4fa;padding:3px 8px;border-radius:2px;")
                cl.addWidget(comm_bar)

        sp = self._mk_sep(4)
        cl.addWidget(sp)

        for t_idx, theme in enumerate(rd["themes"]):
            qs = theme["questions"]
            n_th = len(qs)
            avg_t = sum(q.get("tries", 0) for q in qs) / n_th if n_th else 0
            avg_r = sum(q.get("right", 0) for q in qs) / n_th if n_th else 0

            theme_row = _api.QFrame()
            # Тёмная плиточная зона (как у шапки раунда), чтобы насыщенные
            # плитки вопросов выделялись, а не тонули в серой полосе.
            theme_row.setStyleSheet("background:#1e1e2e;border-radius:5px;")
            row_hl = _api.QHBoxLayout(theme_row); row_hl.setContentsMargins(0, 0, 0, 0); row_hl.setSpacing(0)

            # Left: theme name — double-click to rename, drag handle, delete btn.
            # Светлее плиточной зоны и отделён видимой границей справа, чтобы
            # колонка названия читалась как отдельный столбец.
            th_label_w = _api.QWidget(); th_label_w.setFixedWidth(_th_label_w_px)
            th_label_w.setStyleSheet("background:#313244;border-right:1px solid #45475a;border-radius:5px 0 0 5px;")
            th_label_w.setAcceptDrops(True)
            th_vl = _api.QVBoxLayout(th_label_w); th_vl.setContentsMargins(4,4,4,4); th_vl.setSpacing(2)

            # Top row: drag handle + name + delete
            th_top = _api.QHBoxLayout(); th_top.setContentsMargins(0, 0, 0, 0); th_top.setSpacing(4)
            th_drag_btn = _api.QPushButton("⠿"); th_drag_btn.setFixedSize(14,20)
            th_drag_btn.setCursor(_api.Qt.CursorShape.SizeAllCursor)
            th_drag_btn.setStyleSheet(_api._DH_SS_HIDDEN)
            th_top.addWidget(th_drag_btn)
            th_name_lbl = _api._lbl(theme["name"], "color:#cdd6f4;font-size:13px;font-weight:700;")
            th_name_lbl.setTextInteractionFlags(
                _api.Qt.TextInteractionFlag.TextSelectableByMouse)
            th_name_lbl.setCursor(_api.Qt.CursorShape.IBeamCursor)
            th_name_lbl.setWordWrap(True)
            th_name_lbl.setToolTip("Двойной клик — переименовать тему")
            th_top.addWidget(th_name_lbl, stretch=1)

            if has_siq:
                del_th_btn = _api.QPushButton("✕"); del_th_btn.setObjectName(_api._ON_BTN_DEL)
                del_th_btn.setFixedSize(18,18)
                del_th_btn.setToolTip("Удалить тему")
                del_th_btn.clicked.connect(lambda _, ri=r_idx, ti=t_idx: self._delete_theme(ri, ti))
                th_top.addWidget(del_th_btn)
            th_vl.addLayout(th_top)

            avgs_row2 = _api.QHBoxLayout(); avgs_row2.setSpacing(4); avgs_row2.setContentsMargins(18,0,0,0)
            avgs_row2.addWidget(_api._lbl(f"⌀🟡{avg_t:.0f}%","color:#f9e2af;font-size:10px;"))
            avgs_row2.addWidget(_api._lbl(f"⌀🟢{avg_r:.0f}%","color:#a6e3a1;font-size:10px;"))
            avgs_row2.addStretch()
            th_vl.addLayout(avgs_row2)
            row_hl.addWidget(th_label_w)

            # Theme label drag-to-reorder — uses module-level _THEME_MIME constant
            def _th_dh_press(ev, h=th_drag_btn, ri=r_idx, ti=t_idx):
                if ev.button() == _api.Qt.MouseButton.LeftButton: h._drag_orig = ev.position().toPoint()
            def _th_dh_move(ev, h=th_drag_btn, row=th_label_w, ri=r_idx, ti=t_idx):
                if not getattr(h,'_drag_orig',None): return
                if (ev.position().toPoint()-h._drag_orig).manhattanLength() < 5: return
                h._drag_orig = None
                mime = _api.QMimeData(); mime.setData(_api._THEME_MIME, _api.QByteArray(f"{ri}:{ti}".encode()))
                d = _api.QDrag(h); d.setMimeData(mime)
                pm = row.grab(); d.setPixmap(pm); d.setHotSpot(pm.rect().center())
                row.setVisible(False)
                d.exec(_api.Qt.DropAction.MoveAction)
                try: row.setVisible(True)
                except RuntimeError: pass
            th_drag_btn.mousePressEvent = _th_dh_press
            th_drag_btn.mouseMoveEvent  = _th_dh_move

            def _th_enter(ev, w=th_drag_btn): w.setStyleSheet(_api._DH_SS_SHOWN)
            def _th_leave(ev, w=th_drag_btn): w.setStyleSheet(_api._DH_SS_HIDDEN)
            th_label_w.enterEvent = _th_enter
            th_label_w.leaveEvent = _th_leave

            # Drop on theme label to reorder themes
            def _th_drag_enter(ev, mime_type=_api._THEME_MIME):
                if ev.mimeData().hasFormat(mime_type): ev.acceptProposedAction()
            def _th_drop(ev, ri=r_idx, ti=t_idx, mime_type=_api._THEME_MIME):
                if not ev.mimeData().hasFormat(mime_type): return
                raw = bytes(ev.mimeData().data(mime_type)).decode()
                src_r, src_t = map(int, raw.split(":"))
                ev.acceptProposedAction()
                if not (src_r == ri and src_t == ti):
                    _api.QTimer.singleShot(0, lambda sr=src_r, st=src_t: self._move_theme(sr, st, ri, ti))
            def _th_drag_move(ev, mime_type=_api._THEME_MIME):
                if ev.mimeData().hasFormat(mime_type): ev.acceptProposedAction()
            th_label_w.dragEnterEvent = _th_drag_enter
            th_label_w.dragMoveEvent  = _th_drag_move
            th_label_w.dropEvent      = _th_drop

            if has_siq:
                def _start_inline_rename(e, ri=r_idx, ti=t_idx,
                                          lbl=th_name_lbl, vl=th_top):
                    # Double-click to rename; single click handled by Qt for text selection
                    if e.type() != e.Type.MouseButtonDblClick: return
                    if e.button() != _api.Qt.MouseButton.LeftButton: return
                    cur_name = self._siq.rounds[ri]["themes"][ti]["name"]
                    le = _api.QLineEdit(cur_name, lbl.parentWidget())
                    le.setStyleSheet(
                        "QLineEdit{background:#1e1e2e;color:#cdd6f4;font-size:13px;"
                        "font-weight:700;border:1px solid #89b4fa;border-radius:4px;"
                        "padding:2px 4px;}")
                    le.setGeometry(lbl.geometry().adjusted(-2, -2, 2, 2))
                    le.show(); le.setFocus()
                    le.setCursorPosition(len(le.text()))  # cursor at end, no selection
                    lbl.setVisible(False)
                    _done = [False]
                    def _commit(ri=ri, ti=ti, lbl=lbl, le=le, _d=_done):
                        if _d[0]: return
                        _d[0] = True
                        new_name = le.text().strip() or lbl.text()
                        try: le.hide(); le.deleteLater()
                        except RuntimeError: pass
                        lbl.setVisible(True)
                        if new_name == lbl.text(): return
                        try:
                            self._siq.save_theme_name(ri, ti, new_name)
                            try: self.ds["rounds"][ri]["themes"][ti]["name"] = new_name
                            except Exception: pass
                            lbl.setText(new_name)
                        except Exception as ex:
                            _api._logger.warning(f"[inline_rename] {ex}")
                    le.returnPressed.connect(_commit)
                    le.editingFinished.connect(_commit)
                    # Commit when user clicks anywhere outside the line-edit
                    _ocf = _api._OutsideClickFilter(le, _commit)
                    _api.QApplication.instance().installEventFilter(_ocf)
                th_label_w.mouseDoubleClickEvent = _start_inline_rename
                th_name_lbl.mouseDoubleClickEvent = _start_inline_rename

            # Right: animated tile container that accepts drops
            tiles_w = _api._TileDropArea(r_idx, t_idx, self, has_siq)
            self._drop_areas.append(tiles_w)
            self._drop_area_index[(r_idx, t_idx)] = tiles_w
            tiles_w.question_clicked.connect(self._on_question_clicked)
            tiles_w.add_clicked.connect(self._on_add_question_requested)
            tiles_w.move_requested.connect(self._move_tile_question)

            # Forward THEME_MIME drops from the tiles area so dragging a theme
            # onto the questions area (not just the narrow name label) works too.
            def _tiles_drag_enter(ev, _orig=tiles_w.dragEnterEvent):
                if ev.mimeData().hasFormat(_api._THEME_MIME): ev.acceptProposedAction()
                else: _orig(ev)
            def _tiles_drag_move(ev, _orig=tiles_w.dragMoveEvent):
                if ev.mimeData().hasFormat(_api._THEME_MIME): ev.acceptProposedAction()
                else: _orig(ev)
            def _tiles_drop(ev, _orig=tiles_w.dropEvent, ri=r_idx, ti=t_idx):
                if ev.mimeData().hasFormat(_api._THEME_MIME):
                    raw = bytes(ev.mimeData().data(_api._THEME_MIME)).decode()
                    src_r, src_t = map(int, raw.split(":"))
                    ev.acceptProposedAction()
                    if not (src_r == ri and src_t == ti):
                        _api.QTimer.singleShot(0, lambda sr=src_r, st=src_t: self._move_theme(sr, st, ri, ti))
                else:
                    _orig(ev)
            tiles_w.dragEnterEvent = _tiles_drag_enter
            tiles_w.dragMoveEvent  = _tiles_drag_move
            tiles_w.dropEvent      = _tiles_drop

            q_fulls = []
            for qi, q in enumerate(theme["questions"]):
                q_full = q
                if has_siq:
                    try:
                        siq_q = self._siq.rounds[r_idx]["themes"][t_idx]["questions"][qi]
                        # Merge stats from ds into siq question using | (Python 3.9+)
                        q_full = siq_q | {"tries": q.get("tries", 0),
                                          "right": q.get("right", 0)}
                    except Exception:
                        q_full = q
                q_fulls.append(q_full)
            # Откладываем фактическое создание плиток (см. _build_tile_view).
            self._pending_tile_fills.append((tiles_w, q_fulls, has_siq))

            row_hl.addWidget(tiles_w, stretch=1)
            cl.addWidget(theme_row)

            sp2 = self._mk_sep(2)
            cl.addWidget(sp2)

        gap = self._mk_sep(10)
        cl.addWidget(gap)

        # Add theme button for this round
        if self._siq:
            add_th_btn = _api.QPushButton(f"＋  Добавить тему в «{rd['round_name']}»")
            add_th_btn.setObjectName(_api._ON_BTN_COMPARE); add_th_btn.setFixedHeight(26)
            add_th_btn.clicked.connect(lambda _, ri=r_idx: self._add_theme(ri))
            cl.addWidget(add_th_btn)
            sp_after = self._mk_sep(6)
            cl.addWidget(sp_after)

    if self._siq:
        add_rnd2 = _api.QPushButton("＋  Новый раунд")
        add_rnd2.setObjectName(_api._ON_BTN_COMPARE); add_rnd2.setFixedHeight(30)
        add_rnd2.clicked.connect(self._add_round)
        cl.addWidget(add_rnd2)
