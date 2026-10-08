# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage. Public namespace: siquester.result_page."""
import siquester.result_page as _api
from si_hyx_parts.siquester.result_page.editing import ResultPageEditingMixin


class ResultPage(ResultPageEditingMixin, _api.QWidget):

    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#181825;")
        self.ds = ds
        self._siq: _api.SiqPackage | None = None
        self._viewer: _api.QuestionViewer | None = None
        self._gen = 0
        self._pending: list[_api.QWidget] = []
        self._content_widget = None
        # Сетку плиток строим ЛЕНИВО — только когда страница пакета реально
        # показана (см. _rebuild_content/showEvent). При старте так со всеми
        # пакетами сразу: иначе построение 18 пакетов по ~5 сек подряд намертво
        # вешало GUI-поток. Видимая страница строится сразу.
        self._content_dirty = False
        self._siq_view_dirty = False   # вьюер вопросов тоже строим лениво (см. attach_siq)
        # ── Undo / Redo stacks ──────────────────────────────
        self._undo_stack: _api._collections.deque = _api._collections.deque(maxlen=self._MAX_UNDO)
        self._redo_stack: list = []
        # ── Banner caches (must exist before first _refresh_banner_widget call) ─
        self._banner_fill_cache: tuple[int, float] | None = None
        self._banner_fill_siq_id: int | None = None
        self._banner_refs: dict | None = None
        self._banner_struct_key = None
        # Cache for g_t / g_r / n_all stats — invalidated when questions are played.
        # Key: id(rounds list), Value: (n_all, g_t, g_r)
        self._banner_stats_cache: tuple | None = None
        self._banner_stats_key: int = 0   # incremented on every stats update
        # ── Drop-area registry ───────────────────────────────
        # _drop_areas: flat list for iteration (WASD, deselect-all)
        # _drop_area_index: (r_idx, t_idx) → area for O(1) targeted lookup
        self._drop_areas: list = []
        self._drop_area_index: dict = {}
        # ── Cached MainWindow ref (set in showEvent to avoid repeated .window()) ─
        self._mw = None

        root = _api.QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self._banner_frame = _api.QFrame()
        self._refresh_banner_widget()   # safe now: all attrs exist
        root.addWidget(self._banner_frame)

        # Horizontal splitter: stats left | viewer right
        self._splitter = _api.QSplitter(_api.Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(3)
        root.addWidget(self._splitter, stretch=1)

        left_w = _api.QWidget(); left_w.setStyleSheet("background:#181825;")
        left_lay = _api.QVBoxLayout(left_w); left_lay.setContentsMargins(0, 0, 0, 0)
        self._scroll = _api.SmoothScrollArea(); self._scroll.setStyleSheet("border:none;background:#181825;")
        left_lay.addWidget(self._scroll)
        self._splitter.addWidget(left_w)

        # Right viewer panel (hidden until SIQ attached)
        self._viewer_wrap = _api.QWidget(); self._viewer_wrap.setStyleSheet("background:#181825;")
        self._viewer_wrap.setVisible(False)
        self._viewer_lay = _api.QVBoxLayout(self._viewer_wrap); self._viewer_lay.setContentsMargins(0, 0, 0, 0)
        ph = _api._lbl("← Нажмите на цену вопроса в таблице",
                  "color:#585b70;font-size:13px;background:#181825;padding:20px;")
        ph.setAlignment(_api._AlignC); self._viewer_lay.addWidget(ph)
        self._splitter.addWidget(self._viewer_wrap)
        self._splitter.setSizes([10000, 0])

        self._rebuild_content(animated=False)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._mw is None:
            self._mw = _api._find_mw(self)
        # Достраиваем отложенное при первом реальном показе страницы: сначала
        # вьюер+сетку (если был привязан siq), иначе — только сетку плиток.
        if getattr(self, "_siq_view_dirty", False):
            self._ensure_siq_view()
        elif getattr(self, "_content_dirty", False):
            # Первый показ страницы пакета — сетку плиток заполняем порциями,
            # чтобы доска появилась мгновенно, а не висла на ~1.4 с.
            self._rebuild_content(animated=False, chunked=True)

    # ── Banner ────────────────────────────────────────────
    def _invalidate_fill_cache(self):
        """Call after any question is added, removed, or its items change."""
        self._banner_fill_cache = None

    def _refresh_banner_widget(self):
        rounds    = self.ds["rounds"]
        pkg_name  = self.ds["pkg_name"]
        stats     = self.ds.get("stats", "")
        total_dur = self.ds.get("total_duration_sec", 0)

        # Package size on disk changes as questions are edited (auto-saved to
        # the .siq file) — re-stat it here instead of trusting the value
        # cached at import time, otherwise the banner shows a stale size.
        siq_path = self.ds.get("siq_path", "")
        if siq_path and _api.os.path.exists(siq_path):
            try:
                self.ds["pkg_size"] = f"{_api.os.path.getsize(siq_path)/1024/1024:.1f} МБ"
            except OSError:
                pass
        pkg_size  = self.ds.get("pkg_size", "")

        # Single pass: compute n_all, g_t, g_r without building intermediate lists.
        # Cache result by _banner_stats_key — invalidated in update_stats().
        if self._banner_stats_cache is not None and \
                self._banner_stats_cache[0] == self._banner_stats_key:
            _, n_all, g_t, g_r = self._banner_stats_cache
        else:
            n_all = t_sum = r_sum = 0
            for rd in rounds:
                if rd.get("stats_excluded", False):
                    continue   # round excluded from overall stats by user
                for th in rd["themes"]:
                    for q in th["questions"]:
                        n_all += 1; t_sum += q.get("tries", 0); r_sum += q.get("right", 0)
            g_t = t_sum / n_all if n_all else 0.0
            g_r = r_sum / n_all if n_all else 0.0
            self._banner_stats_cache = (self._banner_stats_key, n_all, g_t, g_r)

        # ── Completeness (cached) ──────────────────────────────────
        total_q = 0; filled_score = 0.0
        if self._siq:
            siq_id = id(self._siq)
            if self._banner_fill_cache is not None and self._banner_fill_siq_id == siq_id:
                total_q, filled_score = self._banner_fill_cache
            else:
                for rd in self._siq.rounds:
                    for th in rd["themes"]:
                        for q in th["questions"]:
                            total_q += 1
                            items = q.get("items", [])
                            has_q = any(it.get("param") in ("question", "background") and
                                        (it.get("text", "").strip() or it.get("is_ref"))
                                        for it in items)
                            answers = q.get("answers", [])
                            has_a = bool(answers and any(a.strip() for a in answers))
                            if has_q and has_a:  filled_score += 1.0
                            elif has_q or has_a: filled_score += 0.5
                self._banner_fill_cache  = (total_q, filled_score)
                self._banner_fill_siq_id = siq_id

        # ── Structural key ─────────────────────────────────────────
        _has_siq      = self._siq is not None
        _has_siqpath  = bool(self.ds.get("siq_path") and _api.os.path.exists(self.ds["siq_path"]))
        _has_stats    = bool(stats)
        _has_progress = _has_siq and total_q > 0
        _struct_key   = (_has_siq, _has_siqpath, _has_stats, _has_progress)

        _banner_h = 100 if _has_progress else 78
        self._banner_frame.setFixedHeight(_banner_h)
        self._banner_frame.setStyleSheet(
            "background:#1e1e2e;border-bottom:1px solid #313244;")

        # ── Fast path: same topology → just update text/values ─────
        refs = getattr(self, "_banner_refs", None)
        if refs is not None and getattr(self, "_banner_struct_key", None) == _struct_key:
            refs["pkg_edit"].setText(pkg_name)
            refs["size_lbl"].setText(f"📦 {pkg_size}" if pkg_size else "")
            refs["size_lbl"].setVisible(bool(pkg_size))
            refs["dur_lbl"].setText(f"⏱ {_api.fmt_dur(total_dur)}" if total_dur > 0 else "")
            refs["dur_lbl"].setVisible(total_dur > 0)
            refs["count_lbl"].setText(
                f"Раундов:<b style='color:#cdd6f4'> {len(rounds)}</b>"
                f" · Вопросов:<b style='color:#cdd6f4'> {n_all}</b>")
            if _has_stats and "game_bar" in refs:
                refs["game_bar"].pct = _api.stats_pct(stats)
                refs["game_bar"].text = stats
                refs["game_bar"].update()
            refs["gt_lbl"].setText(f"🟡 Попытки: <b>{g_t:.1f}%</b>")
            refs["gr_lbl"].setText(f"🟢 Правильные: <b>{g_r:.1f}%</b>")
            if _has_progress and refs.get("fill_lbl") and refs.get("fill_bar"):
                pct = filled_score / total_q * 100
                refs["fill_lbl"].setText(
                    f"Заполнено вопросов: {filled_score:.0f} / {total_q}  ({pct:.0f}%)")
                refs["fill_bar"].update_pct(pct)
            return  # ← skips ~30 widget creations and all signal reconnections

        # ── Full structural rebuild (only on attach/detach/first call) ─
        if not self._banner_frame.layout():
            _outer_vl = _api.QVBoxLayout(self._banner_frame)
            _outer_vl.setContentsMargins(0, 0, 0, 0); _outer_vl.setSpacing(0)
        _outer_vl = self._banner_frame.layout()
        if _outer_vl.count():
            old = _outer_vl.takeAt(0).widget()
            if old: old.hide(); old.setParent(None); old.deleteLater()

        _inner = _api.QWidget(); _inner.setStyleSheet(_api._SS_TRANSPARENT)
        _outer_vl.addWidget(_inner)
        root_vl = _api.QVBoxLayout(_inner)
        root_vl.setContentsMargins(16, 6, 12, 6); root_vl.setSpacing(4)

        top_w = _api.QWidget(); top_w.setStyleSheet(_api._SS_TRANSPARENT)
        top_vl = _api.QVBoxLayout(top_w); top_vl.setContentsMargins(0, 0, 0, 0); top_vl.setSpacing(2)
        bl = _api.QHBoxLayout(); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
        nc = _api.QVBoxLayout(); nc.setSpacing(0)

        pkg_edit = _api.QLineEdit(pkg_name); pkg_edit.setMaximumWidth(280)
        pkg_edit.setSizePolicy(_api._Pref, _api._Fixed)
        pkg_edit.setStyleSheet(
            "QLineEdit{background:transparent;color:#cdd6f4;font-size:13px;font-weight:700;"
            "border:none;padding:0 2px;}"
            "QLineEdit:focus{background:#1e1e2e;border:1px solid #89b4fa;"
            "border-radius:4px;padding:0 4px;}")
        pkg_edit.setToolTip("Кликните для редактирования названия пака")
        def _pkg_edit_done(rp=self, le=pkg_edit):
            new_name = le.text().strip()
            if new_name and new_name != rp.ds["pkg_name"]:
                rp.ds["pkg_name"] = new_name
                if hasattr(rp, '_siq') and rp._siq: rp._siq.name = new_name
                mw = _api._find_mw(rp)
                if hasattr(mw, "_rename_pkg"):
                    idx = next((i for i, d in enumerate(mw.datasets)
                                if d["widget"] is rp), None)
                    if idx is not None: mw._rename_pkg(idx, new_name)
        pkg_edit.editingFinished.connect(_pkg_edit_done)
        nc.addWidget(pkg_edit)

        r2 = _api.QHBoxLayout(); r2.setSpacing(8)
        # ВАЖНО: НЕ звать setVisible(True) на ещё БЕСРОДНОМ QLabel — Qt на миг
        # показывает его как отдельное top-level окно (мелькающие окошки
        # «📦 …»/«⏱ …», которые видел пользователь). Свежесозданный QLabel и так
        # появится вместе с родителем; пустые просто прячем (.hide() не мелькает).
        size_lbl = _api._lbl(f"📦 {pkg_size}" if pkg_size else "", "color:#6c7086;font-size:10px;")
        r2.addWidget(size_lbl)
        if not pkg_size: size_lbl.hide()
        dur_lbl  = _api._lbl(f"⏱ {_api.fmt_dur(total_dur)}" if total_dur > 0 else "",
                        "color:#cba6f7;font-size:10px;")
        r2.addWidget(dur_lbl)
        if total_dur <= 0: dur_lbl.hide()
        r2.addStretch(); nc.addLayout(r2); bl.addLayout(nc)

        count_lbl = _api._lbl(
            f"Раундов:<b style='color:#cdd6f4'> {len(rounds)}</b>"
            f" · Вопросов:<b style='color:#cdd6f4'> {n_all}</b>",
            "color:#585b70;font-size:12px;")
        bl.addWidget(count_lbl)

        game_bar = None
        if _has_stats:
            game_bar = _api.GameProgressBar(stats, _api.stats_pct(stats)); bl.addWidget(game_bar)
        bl.addStretch()

        # Бейджи статистики и кнопки действий — на ОТДЕЛЬНОЙ строке, чтобы при
        # узкой ширине (вкладка внутри SI-HYX) они не наезжали на название/счётчики.
        bl2 = _api.QHBoxLayout(); bl2.setContentsMargins(0, 0, 0, 0); bl2.setSpacing(8)
        bl2.addStretch()

        gt_lbl = _api._lbl(f"🟡 Попытки: <b>{g_t:.1f}%</b>",
                      "color:#f9e2af;font-size:13px;"
                      "background:rgba(249,226,175,0.15);border-radius:5px;padding:3px 10px;")
        gr_lbl = _api._lbl(f"🟢 Правильные: <b>{g_r:.1f}%</b>",
                      "color:#a6e3a1;font-size:13px;"
                      "background:rgba(166,227,161,0.15);border-radius:5px;padding:3px 10px;")
        bl2.addWidget(gt_lbl); bl2.addWidget(gr_lbl)

        self._view_btns = []
        if _has_siqpath:
            save_btn = _api.AnimatedButton("💾")
            save_btn.setObjectName(_api._ON_BTN_COMPARE)
            save_btn.setFixedWidth(40)
            save_btn.setToolTip("Сохранить изменения в .siq файл (F5)")
            save_btn.clicked.connect(self._save_siq_inplace); bl2.addWidget(save_btn)

        if _has_siq:
            copy_ans_btn = _api.AnimatedButton("📝 Все ответы")
            copy_ans_btn.setObjectName(_api._ON_BTN_COMPARE)
            copy_ans_btn.setToolTip("Выбрать пакеты и скопировать ответы в буфер обмена")
            def _open_copy_dialog(_, rp=self):
                rp._copy_all_answers_dialog(getattr(_api._find_mw(rp), 'datasets', []))
            copy_ans_btn.clicked.connect(_open_copy_dialog); bl2.addWidget(copy_ans_btn)

            pkg_info_btn = _api.AnimatedButton("📦 Инфо пака")
            pkg_info_btn.setObjectName(_api._ON_BTN_SORT)
            pkg_info_btn.setToolTip(
                "Редактировать метаданные пакета: теги, авторы, сложность, описание…")
            def _open_pkg_info(_, rp=self):
                if not rp._siq: return
                dlg = _api.PackageInfoDialog(rp._siq, rp)
                def _on_saved():
                    rp._refresh_banner_widget()
                    mw = _api._find_mw(rp)
                    if hasattr(mw, '_rename_pkg'):
                        idx = next((i for i, d in enumerate(mw.datasets)
                                    if d['widget'] is rp), None)
                        if idx is not None: mw._rename_pkg(idx, rp._siq.name)
                    if hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                        mw._save_notif.setText("✅  Инфо пакета сохранено")
                        mw._show_save_notification()
                        _api._notif_reset(mw)
                dlg.saved.connect(_on_saved); dlg.exec()
            pkg_info_btn.clicked.connect(_open_pkg_info); bl2.addWidget(pkg_info_btn)

        top_vl.addLayout(bl); top_vl.addLayout(bl2); root_vl.addWidget(top_w)

        fill_lbl = fill_bar = None
        if _has_progress:
            prog_row = _api.QHBoxLayout(); prog_row.setContentsMargins(0, 0, 0, 0); prog_row.setSpacing(8)
            pct = filled_score / total_q * 100
            fill_lbl = _api._lbl(
                f"Заполнено вопросов: {filled_score:.0f} / {total_q}  ({pct:.0f}%)",
                "color:#a6adc8;font-size:10px;min-width:200px;")
            prog_row.addWidget(fill_lbl)
            fill_bar = _api._QProgressWidget(pct); prog_row.addWidget(fill_bar, stretch=1)
            root_vl.addLayout(prog_row)

        # Store refs for fast-path on next call
        self._banner_refs = {
            "pkg_edit": pkg_edit, "size_lbl": size_lbl, "dur_lbl": dur_lbl,
            "count_lbl": count_lbl, "gt_lbl": gt_lbl, "gr_lbl": gr_lbl,
            "fill_lbl": fill_lbl, "fill_bar": fill_bar,
        }
        if game_bar is not None: self._banner_refs["game_bar"] = game_bar
        self._banner_struct_key = _struct_key

    # ── SIQ attachment ────────────────────────────────────
    @property
    def _mw_ref(self):
        """Cached reference to the MainWindow."""
        return self._mw or _api._find_mw(self)

    def attach_siq(self, siq: _api.SiqPackage):
        self._siq = siq
        if siq.path and not self.ds.get("siq_path"):
            self.ds["siq_path"] = siq.path
        # Sync package name: SIQ XML is authoritative
        if siq.name and siq.name != self.ds.get("pkg_name", ""):
            self.ds["pkg_name"] = siq.name
            mw = self._mw_ref
            if hasattr(mw, "datasets"):
                for _d in mw.datasets:
                    if _d.get("widget") is self:
                        _d["pkg_name"] = siq.name; break
            if hasattr(mw, "sidebar"):
                mw.sidebar.rebuild(getattr(mw, "datasets", []))
        # ── Full sync: SIQ is the authoritative source for rounds/themes/questions ──
        # Re-parse ensures externally added/renamed themes are picked up.
        try:
            # Build a new ds["rounds"] mirroring the SIQ, preserving stats where possible
            old_rounds = self.ds.get("rounds", [])
            # Build lookup: (round_name, theme_name) -> list of {price, tries, right}
            stats_map: dict = {}
            for old_rd in old_rounds:
                rn = old_rd.get("round_name", "")
                for old_th in old_rd.get("themes", []):
                    tn = old_th.get("name", "")
                    for q in old_th.get("questions", []):
                        stats_map.setdefault((rn, tn), {})[q["price"]] = q

            new_rounds = []
            for siq_rd in siq.rounds:
                rn = siq_rd["name"]
                new_themes = []
                for siq_th in siq_rd["themes"]:
                    tn = siq_th["name"]
                    qs_stats = dict(stats_map.get((rn, tn), {}))
                    new_qs = []
                    for q in siq_th["questions"]:
                        saved = qs_stats.pop(q["price"], {})
                        new_qs.append({
                            "price": q["price"],
                            "tries": saved.get("tries", 0),
                            "right": saved.get("right", 0),
                        })
                    # Сохраняем «осиротевшие» статы: цены, вставленные из
                    # свежего HTML сайта, которых ещё нет в локальном .siq
                    # (пак на сайте обновили — добавили вопрос — а .siq
                    # ещё старый). Раньше они тут молча терялись при каждом
                    # attach_siq, и статистика «откатывалась» на меньшее
                    # число вопросов в теме. Не отбрасываем — дописываем.
                    for price, saved in sorted(qs_stats.items()):
                        new_qs.append({
                            "price": price,
                            "tries": saved.get("tries", 0),
                            "right": saved.get("right", 0),
                        })
                    new_themes.append({"name": tn, "questions": new_qs})
                new_rounds.append({
                    "round_name":    rn,
                    "round_type":    siq_rd.get("type", ""),
                    "round_comment": siq_rd.get("comment", ""),
                    "themes":        new_themes,
                })
            self.ds["rounds"] = new_rounds
        except Exception as e:
            _api._logger.warning(f"[attach_siq sync] {e}")
        # Invalidate completeness cache — SIQ object is new
        self._banner_fill_cache = None
        # Построение правой панели-вьюера + сетки плиток — дорогое (QuestionViewer
        # и плитки для пакета на 150+ вопросов). Откладываем до первого показа
        # страницы: при старте attach_siq зовётся для всех 18 пакетов, а виден
        # лишь один. Невидимый пакет достроится в showEvent при первом открытии.
        self._siq_view_dirty = True
        if self.isVisible():
            self._ensure_siq_view()

    def _ensure_siq_view(self):
        """Строит вьюер вопросов + сетку плиток для уже привязанного siq.
        Вызывается при первом показе страницы (или сразу, если она видима)."""
        if not self._siq_view_dirty or self._siq is None:
            return
        self._siq_view_dirty = False
        while self._viewer_lay.count():
            it = self._viewer_lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._viewer = _api.QuestionViewer(self._siq)
        self._viewer.edit_requested.connect(self._on_edit_question_requested)
        self._viewer_lay.addWidget(self._viewer)
        self._viewer_wrap.setVisible(True)
        self._splitter.setSizes([6000, 4000])
        self._refresh_banner_widget()
        # Первый показ доски редактирования — плитки порциями (мгновенный каркас).
        self._rebuild_content(animated=False, chunked=True)

    # ── WASD keyboard navigation ──────────────────────────────
    def _wasd_navigate(self, dx: int, dy: int):
        """Move tile selection by (dx, dy): A=-1,0  D=+1,0  W=0,-1  S=0,+1.

        A/D — previous/next tile within the current theme.
        W/S — previous/next theme (wraps to last/first tile in that theme).
        """
        if not self._siq: return

        cur_area = next((a for a in self._drop_areas if a._selected_tile is not None), None)
        if cur_area is None:
            for area in self._drop_areas:
                if area._tiles:
                    first = area._tiles[0]
                    price = first.property("q_price")
                    area.select_tile_obj(first)
                    self._on_question_clicked(area.r_idx, area.t_idx, price)
                    return
            return

        r_idx = cur_area.r_idx
        t_idx = cur_area.t_idx
        tiles = cur_area._tiles
        if not tiles: return
        try:
            cur_tile_pos = tiles.index(cur_area._selected_tile)
        except ValueError:
            cur_tile_pos = 0

        if dx != 0:
            # ── A / D: move within current theme ──────────────
            new_pos = cur_tile_pos + dx
            if 0 <= new_pos < len(tiles):
                # Stay in same theme
                target_tile = tiles[new_pos]
                price = target_tile.property("q_price")
                cur_area.select_tile_obj(target_tile)
                self._on_question_clicked(r_idx, t_idx, price)
            elif new_pos < 0:
                # Wrap to previous theme (S direction equivalent)
                self._wasd_navigate(0, -1)
            else:
                # Wrap to next theme (W direction equivalent)
                self._wasd_navigate(0, 1)
        else:
            # ── W / S: move between themes ────────────────────
            # Build a flat list of all drop areas in display order
            areas = self._drop_areas
            if not areas: return
            cur_area_pos = next((i for i, a in enumerate(areas) if a is cur_area), 0)
            new_area_pos = cur_area_pos + dy
            # Clamp to valid range
            new_area_pos = max(0, min(new_area_pos, len(areas) - 1))
            if new_area_pos == cur_area_pos: return  # already at edge
            new_area = areas[new_area_pos]
            if not new_area._tiles: return
            # Land on the tile at the same horizontal position if possible
            tile_pos = min(cur_tile_pos, len(new_area._tiles) - 1)
            target_tile = new_area._tiles[tile_pos]
            price = getattr(target_tile, '_q_price', target_tile.property("q_price"))
            cur_area.select_tile(-1)           # deselect old
            new_area.select_tile_obj(target_tile)
            self._on_question_clicked(new_area.r_idx, new_area.t_idx, price)
            # Scroll so the newly selected tile is visible
            try:
                tile_global = target_tile.mapToGlobal(target_tile.rect().topLeft())
                content_y   = self._content_widget.mapFromGlobal(tile_global).y()
                sb = self._scroll.verticalScrollBar()
                visible_h = self._scroll.viewport().height()
                if content_y < sb.value() or content_y + target_tile.height() > sb.value() + visible_h:
                    sb.setValue(max(0, content_y - visible_h // 3))
            except Exception:
                pass

    # ── Content rebuild ───────────────────────────────────
    @staticmethod
    def _mk_sep(height: int) -> '_api.QFrame':
        """Create a thin transparent spacer frame — shared factory to avoid
        repeating the setStyleSheet + setFixedHeight call sequence."""
        f = _api.QFrame(); f.setFixedHeight(height)
        f.setStyleSheet(_api._SS_DARK_BASE)
        return f

    def _rebuild_content(self, animated=True, chunked=False):
        # Если страница пакета сейчас НЕ видна — откладываем дорогое построение
        # сетки плиток до её первого показа (showEvent). Это ключ к мгновенному
        # открытию вкладки: при старте строится только видимый пакет, а не все 18.
        if not self.isVisible():
            self._content_dirty = True
            return
        self._content_dirty = False
        self._gen += 1; my_gen = self._gen
        self._drop_areas.clear()
        self._drop_area_index.clear()   # rebuilt by _build_tile_view below

        # Save scroll position before replacing widget
        _saved_scroll = self._scroll.verticalScrollBar().value()

        content = _api.QWidget(); content.setStyleSheet("background:#181825;")
        cl = _api.QVBoxLayout(content); cl.setContentsMargins(16,14,16,24); cl.setSpacing(0)

        # _build_tile_view собирает плитки в self._pending_tile_fills, а не лепит
        # их сразу: при chunked=True (первый показ страницы) сама сетка плиток
        # достраивается порциями по таймеру — каркас доски виден мгновенно, а 150+
        # плиток «доезжают» за пару кадров вместо ~1.4 с фриза. При обычной
        # перерисовке (правка) заполняем синхронно — код после rebuild сразу
        # рассчитывает на готовые плитки (выделение и т.п.).
        self._build_tile_view(cl)
        if not chunked:
            self._flush_tile_fills_sync()

        cl.addStretch()
        if my_gen != self._gen: content.deleteLater(); return

        old = self._content_widget
        self._content_widget = content
        self._scroll.setWidget(content)

        if chunked:
            self._start_tile_fill(my_gen)

        # Restore scroll position after layout settles
        _api.QTimer.singleShot(0, lambda v=_saved_scroll: self._scroll.verticalScrollBar().setValue(v))

        if animated:
            eff = _api.QGraphicsOpacityEffect(content); content.setGraphicsEffect(eff)
            eff.setOpacity(0.0)
            anim = _api.QPropertyAnimation(eff, b"opacity", content)
            anim.setDuration(120); anim.setEasingCurve(_api.QEasingCurve.Type.OutCubic)
            anim.setStartValue(0.0); anim.setEndValue(1.0)
            anim.start(_api.QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        if old is not None:
            self._pending.append(old)
            def _del(w=old):
                if w in self._pending: self._pending.remove(w)
                try: w.deleteLater()
                except RuntimeError: pass
            _api.QTimer.singleShot(80, _del)

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

    # ── Tile fill (synchronous / chunked) ─────────────────────
    def _flush_tile_fills_sync(self):
        """Создаёт все отложенные плитки немедленно (обычная перерисовка)."""
        fills = getattr(self, "_pending_tile_fills", None)
        if not fills:
            self._pending_tile_fills = []
            return
        self._pending_tile_fills = []
        self._tile_fill_queue = None   # отменяем возможную незавершённую порцию
        for area, q_fulls, has_siq in fills:
            for q in q_fulls:
                area.add_tile(q, has_siq)
            if has_siq:
                area.add_plus_tile()

    def _start_tile_fill(self, gen: int):
        """Заполняет сетку плитками порциями по таймеру: каркас доски виден сразу,
        а плитки «доезжают» за несколько кадров — без длинного фриза на первом
        показе пакета."""
        fills = getattr(self, "_pending_tile_fills", None)
        self._pending_tile_fills = []
        if not fills:
            self._tile_fill_queue = None
            return
        queue = _api._collections.deque()
        for area, q_fulls, has_siq in fills:
            for q in q_fulls:
                queue.append(("tile", area, q, has_siq))
            if has_siq:
                queue.append(("plus", area, None, has_siq))
        self._tile_fill_queue = queue
        self._tile_fill_gen = gen
        _api.QTimer.singleShot(0, self._fill_tiles_chunk)

    def _fill_tiles_chunk(self):
        # Перерисовка/смена пакета увеличивает _gen — устаревшее заполнение бросаем.
        if getattr(self, "_tile_fill_gen", -1) != self._gen:
            self._tile_fill_queue = None
            return
        q = getattr(self, "_tile_fill_queue", None)
        if not q:
            return
        # Бюджет по времени (~12 мс): сколько плиток успеем — столько и создаём за
        # тик, затем уступаем циклу событий, чтобы держать ~60 к/с независимо от
        # стоимости плитки на конкретной машине.
        start = _api._time.perf_counter()
        while q:
            kind, area, data, has_siq = q.popleft()
            try:
                if kind == "tile":
                    area.add_tile(data, has_siq)
                else:
                    area.add_plus_tile()
            except RuntimeError:
                pass   # область удалена при перестроении — пропускаем
            if (_api._time.perf_counter() - start) > 0.012:
                break
        if q:
            _api.QTimer.singleShot(0, self._fill_tiles_chunk)
        else:
            self._tile_fill_queue = None

    # ── Undo / Redo ────────────────────────────────────────
    _MAX_UNDO = 40


ResultPage.__module__ = _api.__name__
_api.ResultPage = ResultPage
