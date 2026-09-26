# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _refresh_banner_widget. Public namespace: siquester.result_page."""
import siquester.result_page as _api


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
