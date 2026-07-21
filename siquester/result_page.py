"""ResultPage — the per-package round/theme/question board."""

from .qt import (
    _collections, _dt, _logger, _time, copy, ET, json, os, Path, QApplication,
    QByteArray, QCheckBox, QDrag, QEasingCurve, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMimeData, QPropertyAnimation,
    QPushButton, QSplitter, Qt, QTimer, QVBoxLayout, QWidget
)
from .constants import (
    _AlignC, _DH_SS_HIDDEN, _DH_SS_SHOWN, _Fixed, _MEDIA_EXTS, _ON_BTN_ANALYZE,
    _ON_BTN_COMPARE, _ON_BTN_DEL, _ON_BTN_SORT, _Pref, _SS_DARK_BASE, _SS_TRANSPARENT,
    _THEME_MIME
)
from .persistence import _notif_reset, _schedule_save
from .siq_package import SiqPackage
from .stats import stats_pct
from .util import _find_mw, _lbl, _q_idx, _screen_scale, fmt_dur
from .widgets_common import (
    _OutsideClickFilter, _QProgressWidget, AnimatedButton, GameProgressBar,
    msgbox_warning, SmoothScrollArea
)
from .widgets_editors import QuestionEditorDialog
from .widgets_question import QuestionViewer
from .widgets_tiles import _TileDropArea, PackageInfoDialog

class ResultPage(QWidget):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#181825;")
        self.ds = ds
        self._siq: SiqPackage | None = None
        self._viewer: QuestionViewer | None = None
        self._gen = 0
        self._pending: list[QWidget] = []
        self._content_widget = None
        # Сетку плиток строим ЛЕНИВО — только когда страница пакета реально
        # показана (см. _rebuild_content/showEvent). При старте так со всеми
        # пакетами сразу: иначе построение 18 пакетов по ~5 сек подряд намертво
        # вешало GUI-поток. Видимая страница строится сразу.
        self._content_dirty = False
        self._siq_view_dirty = False   # вьюер вопросов тоже строим лениво (см. attach_siq)
        # ── Undo / Redo stacks ──────────────────────────────
        self._undo_stack: _collections.deque = _collections.deque(maxlen=self._MAX_UNDO)
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

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self._banner_frame = QFrame()
        self._refresh_banner_widget()   # safe now: all attrs exist
        root.addWidget(self._banner_frame)

        # Horizontal splitter: stats left | viewer right
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(3)
        root.addWidget(self._splitter, stretch=1)

        left_w = QWidget(); left_w.setStyleSheet("background:#181825;")
        left_lay = QVBoxLayout(left_w); left_lay.setContentsMargins(0, 0, 0, 0)
        self._scroll = SmoothScrollArea(); self._scroll.setStyleSheet("border:none;background:#181825;")
        left_lay.addWidget(self._scroll)
        self._splitter.addWidget(left_w)

        # Right viewer panel (hidden until SIQ attached)
        self._viewer_wrap = QWidget(); self._viewer_wrap.setStyleSheet("background:#181825;")
        self._viewer_wrap.setVisible(False)
        self._viewer_lay = QVBoxLayout(self._viewer_wrap); self._viewer_lay.setContentsMargins(0, 0, 0, 0)
        ph = _lbl("← Нажмите на цену вопроса в таблице",
                  "color:#585b70;font-size:13px;background:#181825;padding:20px;")
        ph.setAlignment(_AlignC); self._viewer_lay.addWidget(ph)
        self._splitter.addWidget(self._viewer_wrap)
        self._splitter.setSizes([10000, 0])

        self._rebuild_content(animated=False)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._mw is None:
            self._mw = _find_mw(self)
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
        if siq_path and os.path.exists(siq_path):
            try:
                self.ds["pkg_size"] = f"{os.path.getsize(siq_path)/1024/1024:.1f} МБ"
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
        _has_siqpath  = bool(self.ds.get("siq_path") and os.path.exists(self.ds["siq_path"]))
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
            refs["dur_lbl"].setText(f"⏱ {fmt_dur(total_dur)}" if total_dur > 0 else "")
            refs["dur_lbl"].setVisible(total_dur > 0)
            refs["count_lbl"].setText(
                f"Раундов:<b style='color:#cdd6f4'> {len(rounds)}</b>"
                f" · Вопросов:<b style='color:#cdd6f4'> {n_all}</b>")
            if _has_stats and "game_bar" in refs:
                refs["game_bar"].pct = stats_pct(stats)
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
            _outer_vl = QVBoxLayout(self._banner_frame)
            _outer_vl.setContentsMargins(0, 0, 0, 0); _outer_vl.setSpacing(0)
        _outer_vl = self._banner_frame.layout()
        if _outer_vl.count():
            old = _outer_vl.takeAt(0).widget()
            if old: old.hide(); old.setParent(None); old.deleteLater()

        _inner = QWidget(); _inner.setStyleSheet(_SS_TRANSPARENT)
        _outer_vl.addWidget(_inner)
        root_vl = QVBoxLayout(_inner)
        root_vl.setContentsMargins(16, 6, 12, 6); root_vl.setSpacing(4)

        top_w = QWidget(); top_w.setStyleSheet(_SS_TRANSPARENT)
        top_vl = QVBoxLayout(top_w); top_vl.setContentsMargins(0, 0, 0, 0); top_vl.setSpacing(2)
        bl = QHBoxLayout(); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
        nc = QVBoxLayout(); nc.setSpacing(0)

        pkg_edit = QLineEdit(pkg_name); pkg_edit.setMaximumWidth(280)
        pkg_edit.setSizePolicy(_Pref, _Fixed)
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
                mw = _find_mw(rp)
                if hasattr(mw, "_rename_pkg"):
                    idx = next((i for i, d in enumerate(mw.datasets)
                                if d["widget"] is rp), None)
                    if idx is not None: mw._rename_pkg(idx, new_name)
        pkg_edit.editingFinished.connect(_pkg_edit_done)
        nc.addWidget(pkg_edit)

        r2 = QHBoxLayout(); r2.setSpacing(8)
        # ВАЖНО: НЕ звать setVisible(True) на ещё БЕСРОДНОМ QLabel — Qt на миг
        # показывает его как отдельное top-level окно (мелькающие окошки
        # «📦 …»/«⏱ …», которые видел пользователь). Свежесозданный QLabel и так
        # появится вместе с родителем; пустые просто прячем (.hide() не мелькает).
        size_lbl = _lbl(f"📦 {pkg_size}" if pkg_size else "", "color:#6c7086;font-size:10px;")
        r2.addWidget(size_lbl)
        if not pkg_size: size_lbl.hide()
        dur_lbl  = _lbl(f"⏱ {fmt_dur(total_dur)}" if total_dur > 0 else "",
                        "color:#cba6f7;font-size:10px;")
        r2.addWidget(dur_lbl)
        if total_dur <= 0: dur_lbl.hide()
        r2.addStretch(); nc.addLayout(r2); bl.addLayout(nc)

        count_lbl = _lbl(
            f"Раундов:<b style='color:#cdd6f4'> {len(rounds)}</b>"
            f" · Вопросов:<b style='color:#cdd6f4'> {n_all}</b>",
            "color:#585b70;font-size:12px;")
        bl.addWidget(count_lbl)

        game_bar = None
        if _has_stats:
            game_bar = GameProgressBar(stats, stats_pct(stats)); bl.addWidget(game_bar)
        bl.addStretch()

        # Бейджи статистики и кнопки действий — на ОТДЕЛЬНОЙ строке, чтобы при
        # узкой ширине (вкладка внутри SI-HYX) они не наезжали на название/счётчики.
        bl2 = QHBoxLayout(); bl2.setContentsMargins(0, 0, 0, 0); bl2.setSpacing(8)
        bl2.addStretch()

        gt_lbl = _lbl(f"🟡 Попытки: <b>{g_t:.1f}%</b>",
                      "color:#f9e2af;font-size:13px;"
                      "background:rgba(249,226,175,0.15);border-radius:5px;padding:3px 10px;")
        gr_lbl = _lbl(f"🟢 Правильные: <b>{g_r:.1f}%</b>",
                      "color:#a6e3a1;font-size:13px;"
                      "background:rgba(166,227,161,0.15);border-radius:5px;padding:3px 10px;")
        bl2.addWidget(gt_lbl); bl2.addWidget(gr_lbl)

        self._view_btns = []
        if _has_siqpath:
            save_btn = AnimatedButton("💾")
            save_btn.setObjectName(_ON_BTN_COMPARE)
            save_btn.setFixedWidth(40)
            save_btn.setToolTip("Сохранить изменения в .siq файл (F5)")
            save_btn.clicked.connect(self._save_siq_inplace); bl2.addWidget(save_btn)

        if _has_siq:
            copy_ans_btn = AnimatedButton("📝 Все ответы")
            copy_ans_btn.setObjectName(_ON_BTN_COMPARE)
            copy_ans_btn.setToolTip("Выбрать пакеты и скопировать ответы в буфер обмена")
            def _open_copy_dialog(_, rp=self):
                rp._copy_all_answers_dialog(getattr(_find_mw(rp), 'datasets', []))
            copy_ans_btn.clicked.connect(_open_copy_dialog); bl2.addWidget(copy_ans_btn)

            pkg_info_btn = AnimatedButton("📦 Инфо пака")
            pkg_info_btn.setObjectName(_ON_BTN_SORT)
            pkg_info_btn.setToolTip(
                "Редактировать метаданные пакета: теги, авторы, сложность, описание…")
            def _open_pkg_info(_, rp=self):
                if not rp._siq: return
                dlg = PackageInfoDialog(rp._siq, rp)
                def _on_saved():
                    rp._refresh_banner_widget()
                    mw = _find_mw(rp)
                    if hasattr(mw, '_rename_pkg'):
                        idx = next((i for i, d in enumerate(mw.datasets)
                                    if d['widget'] is rp), None)
                        if idx is not None: mw._rename_pkg(idx, rp._siq.name)
                    if hasattr(mw, '_save_notif') and hasattr(mw, '_show_save_notification'):
                        mw._save_notif.setText("✅  Инфо пакета сохранено")
                        mw._show_save_notification()
                        _notif_reset(mw)
                dlg.saved.connect(_on_saved); dlg.exec()
            pkg_info_btn.clicked.connect(_open_pkg_info); bl2.addWidget(pkg_info_btn)

        top_vl.addLayout(bl); top_vl.addLayout(bl2); root_vl.addWidget(top_w)

        fill_lbl = fill_bar = None
        if _has_progress:
            prog_row = QHBoxLayout(); prog_row.setContentsMargins(0, 0, 0, 0); prog_row.setSpacing(8)
            pct = filled_score / total_q * 100
            fill_lbl = _lbl(
                f"Заполнено вопросов: {filled_score:.0f} / {total_q}  ({pct:.0f}%)",
                "color:#a6adc8;font-size:10px;min-width:200px;")
            prog_row.addWidget(fill_lbl)
            fill_bar = _QProgressWidget(pct); prog_row.addWidget(fill_bar, stretch=1)
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
        return self._mw or _find_mw(self)

    def attach_siq(self, siq: SiqPackage):
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
            _logger.warning(f"[attach_siq sync] {e}")
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
        self._viewer = QuestionViewer(self._siq)
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
    def _mk_sep(height: int) -> 'QFrame':
        """Create a thin transparent spacer frame — shared factory to avoid
        repeating the setStyleSheet + setFixedHeight call sequence."""
        f = QFrame(); f.setFixedHeight(height)
        f.setStyleSheet(_SS_DARK_BASE)
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

        content = QWidget(); content.setStyleSheet("background:#181825;")
        cl = QVBoxLayout(content); cl.setContentsMargins(16,14,16,24); cl.setSpacing(0)

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
        QTimer.singleShot(0, lambda v=_saved_scroll: self._scroll.verticalScrollBar().setValue(v))

        if animated:
            eff = QGraphicsOpacityEffect(content); content.setGraphicsEffect(eff)
            eff.setOpacity(0.0)
            anim = QPropertyAnimation(eff, b"opacity", content)
            anim.setDuration(120); anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(0.0); anim.setEndValue(1.0)
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        if old is not None:
            self._pending.append(old)
            def _del(w=old):
                if w in self._pending: self._pending.remove(w)
                try: w.deleteLater()
                except RuntimeError: pass
            QTimer.singleShot(80, _del)

    # ── Tile view ─────────────────────────────────────────
    def _build_tile_view(self, cl: QVBoxLayout):
        has_siq = self._siq is not None
        # Плитки не добавляем сразу — собираем сюда (area, q_fulls, has_siq) и
        # заполняем синхронно или порциями (см. _rebuild_content/_start_tile_fill).
        self._pending_tile_fills = []
        # Cache scale factor once — constant for the entire build pass.
        _scale         = _screen_scale()
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

            rnd_hdr=QFrame(); rnd_hdr.setFixedHeight(36)
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
                    QTimer.singleShot(0, lambda sr=src_r: self._move_round(sr, ri))
            rnd_hdr.dragEnterEvent = _rnd_drag_enter
            rnd_hdr.dropEvent      = _rnd_drop

            rh=QHBoxLayout(rnd_hdr); rh.setContentsMargins(8,0,8,0); rh.setSpacing(6)

            # Drag handle for round
            if self._siq:
                rnd_dh = QPushButton("⠿"); rnd_dh.setFixedSize(14, 22)
                rnd_dh.setCursor(Qt.CursorShape.SizeAllCursor)
                rnd_dh.setStyleSheet(_DH_SS_HIDDEN)
                def _rnd_dh_press(ev, h=rnd_dh): h._drag_origin = ev.position().toPoint() if ev.button() == Qt.MouseButton.LeftButton else None
                def _rnd_dh_move(ev, h=rnd_dh, ri=r_idx, hdr=rnd_hdr):
                    if not getattr(h,'_drag_origin',None): return
                    if (ev.position().toPoint()-h._drag_origin).manhattanLength() < 5: return
                    h._drag_origin = None
                    mime = QMimeData(); mime.setData(_RND_MIME, QByteArray(str(ri).encode()))
                    d = QDrag(h); d.setMimeData(mime)
                    pm = hdr.grab(); d.setPixmap(pm); d.setHotSpot(pm.rect().center())
                    hdr.setVisible(False)
                    d.exec(Qt.DropAction.MoveAction)
                    try: hdr.setVisible(True)
                    except RuntimeError: pass
                rnd_dh.mousePressEvent = _rnd_dh_press
                rnd_dh.mouseMoveEvent  = _rnd_dh_move
                def _rnd_hdr_enter(ev, h=rnd_dh): h.setStyleSheet(_DH_SS_SHOWN)
                def _rnd_hdr_leave(ev, h=rnd_dh): h.setStyleSheet(_DH_SS_HIDDEN)
                rnd_hdr.enterEvent = _rnd_hdr_enter
                rnd_hdr.leaveEvent = _rnd_hdr_leave
                rh.addWidget(rnd_dh)
            # Inline editable round name (centered, stats on right side)
            rnd_edit = QLineEdit(rd['round_name'])
            rnd_edit.setAlignment(_AlignC)
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
                        except Exception as e: _logger.warning(f"[rename_round] {e}")
                    mw = self._mw_ref
                    _schedule_save(mw)
            rnd_edit.editingFinished.connect(_rnd_edit_done)
            rh.addWidget(rnd_edit, stretch=1)
            rh.addSpacing(8)
            rh.addWidget(_lbl(f"🟡{r_t:.0f}%","color:#f9e2af;font-size:11px;"))
            rh.addSpacing(4)
            rh.addWidget(_lbl(f"🟢{r_r:.0f}%","color:#a6e3a1;font-size:11px;"))
            rh.addStretch()
            if self._siq:
                # ── Final round toggle button ─────────────────────────
                siq_rnd = self._siq.rounds[r_idx] if r_idx < len(self._siq.rounds) else {}
                is_final = siq_rnd.get("type","") == "final"
                final_btn = QPushButton("🏆 ФИНАЛ" if is_final else "🏆")
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
                    _schedule_save(mw)
                final_btn.toggled.connect(_toggle_final)
                rh.addWidget(final_btn)

                # ── Exclude-from-stats toggle ─────────────────────────
                _excl = rd.get("stats_excluded", False)
                excl_btn = QPushButton("📊")
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
                    _schedule_save(mw)
                excl_btn.toggled.connect(_toggle_excl)
                rh.addWidget(excl_btn)
                # ── Round comment button ──────────────────────────────
                cur_comment = siq_rnd.get("comment","")
                _comm_lbl = "▪" if cur_comment else "▪"
                rnd_comm_btn = QPushButton()
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
                    text, ok = QInputDialog.getMultiLineText(
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
                    _schedule_save(mw)
                rnd_comm_btn.clicked.connect(_edit_rnd_comment)
                rh.addWidget(rnd_comm_btn)
                # ── Change-prices button ──────────────────────────────
                price_btn = QPushButton("💰")
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
                del_rnd2 = QPushButton("🗑")
                del_rnd2.setObjectName(_ON_BTN_DEL); del_rnd2.setFixedSize(24, 24)
                del_rnd2.setToolTip("Удалить раунд")
                del_rnd2.clicked.connect(lambda _, i=r_idx: self._delete_round(i))
                rh.addWidget(del_rnd2)
            cl.addWidget(rnd_hdr)
            # ── Round comment label (shown below header if comment present) ───
            if self._siq:
                siq_rnd2 = self._siq.rounds[r_idx] if r_idx < len(self._siq.rounds) else {}
                if siq_rnd2.get("comment",""):
                    comm_bar = QLabel(f"💬  {siq_rnd2['comment']}")
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

                theme_row = QFrame()
                # Тёмная плиточная зона (как у шапки раунда), чтобы насыщенные
                # плитки вопросов выделялись, а не тонули в серой полосе.
                theme_row.setStyleSheet("background:#1e1e2e;border-radius:5px;")
                row_hl = QHBoxLayout(theme_row); row_hl.setContentsMargins(0, 0, 0, 0); row_hl.setSpacing(0)

                # Left: theme name — double-click to rename, drag handle, delete btn.
                # Светлее плиточной зоны и отделён видимой границей справа, чтобы
                # колонка названия читалась как отдельный столбец.
                th_label_w = QWidget(); th_label_w.setFixedWidth(_th_label_w_px)
                th_label_w.setStyleSheet("background:#313244;border-right:1px solid #45475a;border-radius:5px 0 0 5px;")
                th_label_w.setAcceptDrops(True)
                th_vl = QVBoxLayout(th_label_w); th_vl.setContentsMargins(4,4,4,4); th_vl.setSpacing(2)

                # Top row: drag handle + name + delete
                th_top = QHBoxLayout(); th_top.setContentsMargins(0, 0, 0, 0); th_top.setSpacing(4)
                th_drag_btn = QPushButton("⠿"); th_drag_btn.setFixedSize(14,20)
                th_drag_btn.setCursor(Qt.CursorShape.SizeAllCursor)
                th_drag_btn.setStyleSheet(_DH_SS_HIDDEN)
                th_top.addWidget(th_drag_btn)
                th_name_lbl = _lbl(theme["name"], "color:#cdd6f4;font-size:13px;font-weight:700;")
                th_name_lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
                th_name_lbl.setCursor(Qt.CursorShape.IBeamCursor)
                th_name_lbl.setWordWrap(True)
                th_name_lbl.setToolTip("Двойной клик — переименовать тему")
                th_top.addWidget(th_name_lbl, stretch=1)

                if has_siq:
                    del_th_btn = QPushButton("✕"); del_th_btn.setObjectName(_ON_BTN_DEL)
                    del_th_btn.setFixedSize(18,18)
                    del_th_btn.setToolTip("Удалить тему")
                    del_th_btn.clicked.connect(lambda _, ri=r_idx, ti=t_idx: self._delete_theme(ri, ti))
                    th_top.addWidget(del_th_btn)
                th_vl.addLayout(th_top)

                avgs_row2 = QHBoxLayout(); avgs_row2.setSpacing(4); avgs_row2.setContentsMargins(18,0,0,0)
                avgs_row2.addWidget(_lbl(f"⌀🟡{avg_t:.0f}%","color:#f9e2af;font-size:10px;"))
                avgs_row2.addWidget(_lbl(f"⌀🟢{avg_r:.0f}%","color:#a6e3a1;font-size:10px;"))
                avgs_row2.addStretch()
                th_vl.addLayout(avgs_row2)
                row_hl.addWidget(th_label_w)

                # Theme label drag-to-reorder — uses module-level _THEME_MIME constant
                def _th_dh_press(ev, h=th_drag_btn, ri=r_idx, ti=t_idx):
                    if ev.button() == Qt.MouseButton.LeftButton: h._drag_orig = ev.position().toPoint()
                def _th_dh_move(ev, h=th_drag_btn, row=th_label_w, ri=r_idx, ti=t_idx):
                    if not getattr(h,'_drag_orig',None): return
                    if (ev.position().toPoint()-h._drag_orig).manhattanLength() < 5: return
                    h._drag_orig = None
                    mime = QMimeData(); mime.setData(_THEME_MIME, QByteArray(f"{ri}:{ti}".encode()))
                    d = QDrag(h); d.setMimeData(mime)
                    pm = row.grab(); d.setPixmap(pm); d.setHotSpot(pm.rect().center())
                    row.setVisible(False)
                    d.exec(Qt.DropAction.MoveAction)
                    try: row.setVisible(True)
                    except RuntimeError: pass
                th_drag_btn.mousePressEvent = _th_dh_press
                th_drag_btn.mouseMoveEvent  = _th_dh_move

                def _th_enter(ev, w=th_drag_btn): w.setStyleSheet(_DH_SS_SHOWN)
                def _th_leave(ev, w=th_drag_btn): w.setStyleSheet(_DH_SS_HIDDEN)
                th_label_w.enterEvent = _th_enter
                th_label_w.leaveEvent = _th_leave

                # Drop on theme label to reorder themes
                def _th_drag_enter(ev, mime_type=_THEME_MIME):
                    if ev.mimeData().hasFormat(mime_type): ev.acceptProposedAction()
                def _th_drop(ev, ri=r_idx, ti=t_idx, mime_type=_THEME_MIME):
                    if not ev.mimeData().hasFormat(mime_type): return
                    raw = bytes(ev.mimeData().data(mime_type)).decode()
                    src_r, src_t = map(int, raw.split(":"))
                    ev.acceptProposedAction()
                    if not (src_r == ri and src_t == ti):
                        QTimer.singleShot(0, lambda sr=src_r, st=src_t: self._move_theme(sr, st, ri, ti))
                def _th_drag_move(ev, mime_type=_THEME_MIME):
                    if ev.mimeData().hasFormat(mime_type): ev.acceptProposedAction()
                th_label_w.dragEnterEvent = _th_drag_enter
                th_label_w.dragMoveEvent  = _th_drag_move
                th_label_w.dropEvent      = _th_drop

                if has_siq:
                    def _start_inline_rename(e, ri=r_idx, ti=t_idx,
                                              lbl=th_name_lbl, vl=th_top):
                        # Double-click to rename; single click handled by Qt for text selection
                        if e.type() != e.Type.MouseButtonDblClick: return
                        if e.button() != Qt.MouseButton.LeftButton: return
                        cur_name = self._siq.rounds[ri]["themes"][ti]["name"]
                        le = QLineEdit(cur_name, lbl.parentWidget())
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
                                _logger.warning(f"[inline_rename] {ex}")
                        le.returnPressed.connect(_commit)
                        le.editingFinished.connect(_commit)
                        # Commit when user clicks anywhere outside the line-edit
                        _ocf = _OutsideClickFilter(le, _commit)
                        QApplication.instance().installEventFilter(_ocf)
                    th_label_w.mouseDoubleClickEvent = _start_inline_rename
                    th_name_lbl.mouseDoubleClickEvent = _start_inline_rename

                # Right: animated tile container that accepts drops
                tiles_w = _TileDropArea(r_idx, t_idx, self, has_siq)
                self._drop_areas.append(tiles_w)
                self._drop_area_index[(r_idx, t_idx)] = tiles_w
                tiles_w.question_clicked.connect(self._on_question_clicked)
                tiles_w.add_clicked.connect(self._on_add_question_requested)
                tiles_w.move_requested.connect(self._move_tile_question)

                # Forward THEME_MIME drops from the tiles area so dragging a theme
                # onto the questions area (not just the narrow name label) works too.
                def _tiles_drag_enter(ev, _orig=tiles_w.dragEnterEvent):
                    if ev.mimeData().hasFormat(_THEME_MIME): ev.acceptProposedAction()
                    else: _orig(ev)
                def _tiles_drag_move(ev, _orig=tiles_w.dragMoveEvent):
                    if ev.mimeData().hasFormat(_THEME_MIME): ev.acceptProposedAction()
                    else: _orig(ev)
                def _tiles_drop(ev, _orig=tiles_w.dropEvent, ri=r_idx, ti=t_idx):
                    if ev.mimeData().hasFormat(_THEME_MIME):
                        raw = bytes(ev.mimeData().data(_THEME_MIME)).decode()
                        src_r, src_t = map(int, raw.split(":"))
                        ev.acceptProposedAction()
                        if not (src_r == ri and src_t == ti):
                            QTimer.singleShot(0, lambda sr=src_r, st=src_t: self._move_theme(sr, st, ri, ti))
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
                add_th_btn = QPushButton(f"＋  Добавить тему в «{rd['round_name']}»")
                add_th_btn.setObjectName(_ON_BTN_COMPARE); add_th_btn.setFixedHeight(26)
                add_th_btn.clicked.connect(lambda _, ri=r_idx: self._add_theme(ri))
                cl.addWidget(add_th_btn)
                sp_after = self._mk_sep(6)
                cl.addWidget(sp_after)

        if self._siq:
            add_rnd2 = QPushButton("＋  Новый раунд")
            add_rnd2.setObjectName(_ON_BTN_COMPARE); add_rnd2.setFixedHeight(30)
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
        queue = _collections.deque()
        for area, q_fulls, has_siq in fills:
            for q in q_fulls:
                queue.append(("tile", area, q, has_siq))
            if has_siq:
                queue.append(("plus", area, None, has_siq))
        self._tile_fill_queue = queue
        self._tile_fill_gen = gen
        QTimer.singleShot(0, self._fill_tiles_chunk)

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
        start = _time.perf_counter()
        while q:
            kind, area, data, has_siq = q.popleft()
            try:
                if kind == "tile":
                    area.add_tile(data, has_siq)
                else:
                    area.add_plus_tile()
            except RuntimeError:
                pass   # область удалена при перестроении — пропускаем
            if (_time.perf_counter() - start) > 0.012:
                break
        if q:
            QTimer.singleShot(0, self._fill_tiles_chunk)
        else:
            self._tile_fill_queue = None

    def _move_round(self, src_idx: int, dst_idx: int):
        """Reorder rounds (ds + siq XML)."""
        self._push_undo()
        try:
            if src_idx == dst_idx: return
            rounds = self.ds["rounds"]
            if src_idx < 0 or dst_idx < 0: return
            if src_idx >= len(rounds) or dst_idx >= len(rounds): return
            rd = rounds.pop(src_idx)
            rounds.insert(dst_idx, rd)
        except Exception as e:
            _logger.warning(f"[move_round ds] {e}"); return
        if self._siq:
            try: self._siq.move_round(src_idx, dst_idx)
            except Exception as e: _logger.warning(f"[move_round siq] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _add_theme(self, rnd_idx: int):
        """Add a new empty theme instantly — name can be edited inline."""
        if self._siq is None: return
        name = ""   # empty — user fills via inline double-click rename
        ok_siq = self._siq.add_theme(rnd_idx, name)
        if not ok_siq:
            msgbox_warning(self, "Ошибка", "Не удалось добавить тему в .siq файл."); return
        self.ds["rounds"][rnd_idx]["themes"].append({"name": name, "questions": []})
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _move_tile_question(self, src_r, src_t, price, dst_r, dst_t, insert_idx=-1):
        """Move a question tile from one theme to another (in-memory + siq XML).

        Same-theme reorder: updates widget layout and data in-place — no
        ``_rebuild_content`` call, no widget teardown, no flash.
        Cross-theme move: still triggers a targeted rebuild of the two
        affected ``_TileDropArea`` widgets only, not the full content tree.
        """
        self._push_undo()
        same_theme = (src_r == dst_r and src_t == dst_t)
        print(f"[move_tile] called: src=({src_r},{src_t}) dst=({dst_r},{dst_t}) price={price} insert_idx={insert_idx} same_theme={same_theme}", flush=True)

        # ── 1. Update ds in-memory ─────────────────────────────────
        try:
            src_qs = self.ds["rounds"][src_r]["themes"][src_t]["questions"]
            dst_qs = self.ds["rounds"][dst_r]["themes"][dst_t]["questions"]
            q_obj = next((q for q in src_qs if q["price"] == price), None)
            if q_obj is None: return

            # Find the old position BEFORE removing (needed for tile reorder calc)
            old_ds_idx = src_qs.index(q_obj)

            src_qs.remove(q_obj)
            _pre_dst_price = None   # price displaced at target column (cross-theme)
            if same_theme:
                # insert_idx from drop is the gap position in the layout, which
                # equals the desired final position in the tile list (0-based).
                # After removing q_obj the list is 1 shorter; if insert_idx was
                # after old_ds_idx we need to subtract 1 to stay correct.
                tile_new_idx = insert_idx if insert_idx >= 0 else len(src_qs)
                # Clamp to the now-shorter list
                ds_clamped = max(0, min(tile_new_idx, len(src_qs)))
                src_qs.insert(ds_clamped, q_obj)
            else:
                ds_clamped = max(0, min(insert_idx if insert_idx >= 0 else len(dst_qs), len(dst_qs)))
                # Capture the price of the tile currently at this column position
                # in the destination theme BEFORE inserting (it will be displaced).
                # This is the most reliable signal in 2-theme packages.
                _pre_dst_price = (dst_qs[ds_clamped]["price"]
                                  if ds_clamped < len(dst_qs) else None)
                dst_qs.insert(ds_clamped, q_obj)

            # ── Auto-price: reprice entire dst theme by column ───────────
            # After reorder, every tile in the destination theme gets the
            # majority price for its column position (from all OTHER themes).
            # This prevents duplicates and keeps the grid consistent.
            new_price = price   # fallback: unchanged
            _price_remap = {}   # old_price -> new_price for XML/siq update
            dst_themes = self.ds["rounds"][dst_r]["themes"]
            dst_qs_final = self.ds["rounds"][dst_r]["themes"][dst_t]["questions"]
            for pos_i, tile_q in enumerate(dst_qs_final):
                col_prices = []
                for t_i, theme in enumerate(dst_themes):
                    if t_i == dst_t:
                        continue
                    # For cross-theme same-round: src positions shifted, skip
                    if not same_theme and src_r == dst_r and t_i == src_t:
                        continue
                    qs_i = theme["questions"]
                    if pos_i < len(qs_i):
                        col_prices.append(qs_i[pos_i]["price"])
                if col_prices:
                    canon = _collections.Counter(col_prices).most_common(1)[0][0]
                    old_p = tile_q["price"]
                    if old_p != canon:
                        _price_remap[old_p] = canon
                        tile_q["price"] = canon
                        if tile_q is q_obj:
                            new_price = canon
                else:
                    if tile_q is q_obj:
                        new_price = tile_q["price"]
        except Exception as e:
            _logger.warning(f"[move_tile ds] {e}"); return

        # ── 2. Update SIQ XML ─────────────────────────────────────
        if self._siq:
            try:
                root, ns_url, tag = self._siq._load_xml_root()
                src_theme_el, tag = self._siq._nav_to_question(root, tag, src_r, src_t)
                dst_theme_el, _   = self._siq._nav_to_question(root, tag, dst_r, dst_t)
                src_qs_el = src_theme_el.find(tag('questions'))
                dst_qs_el = dst_theme_el.find(tag('questions'))
                if dst_qs_el is None:
                    dst_qs_el = ET.SubElement(dst_theme_el, tag('questions'))
                # Move the q_el in the XML (match by original price before reprice)
                q_els = src_qs_el.findall(tag('question'))
                q_el = next((q for q in q_els if int(q.get('price', 0)) == price), None)
                if q_el is not None:
                    src_qs_el.remove(q_el)
                    existing = dst_qs_el.findall(tag('question'))
                    ins = ds_clamped if ds_clamped < len(existing) else len(existing)
                    dst_qs_el.insert(ins, q_el)
                # Apply full price remap to dst XML elements by position
                dst_q_els = dst_qs_el.findall(tag('question'))
                for pos_i, tile_q in enumerate(dst_qs_final):
                    if pos_i < len(dst_q_els):
                        dst_q_els[pos_i].set('price', str(tile_q["price"]))
                # Update siq.rounds for the moved tile (positional reorder)
                siq_src = self._siq.rounds[src_r]["themes"][src_t]["questions"]
                siq_dst = self._siq.rounds[dst_r]["themes"][dst_t]["questions"]
                siq_q = next((q for q in siq_src if q["price"] == price), None)
                if siq_q:
                    siq_src.remove(siq_q)
                    siq_dst.insert(ds_clamped, siq_q)
                # Apply remap to siq.rounds for all repriced tiles in dst theme
                for pos_i, tile_q in enumerate(dst_qs_final):
                    if pos_i < len(siq_dst):
                        siq_dst[pos_i]["price"] = tile_q["price"]
                self._siq.rebuild_index_for_theme(src_r, src_t)
                if not same_theme:
                    self._siq.rebuild_index_for_theme(dst_r, dst_t)
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[move_tile siq] {e}")

        # ── 3. Update UI ──────────────────────────────────────────
        # Always repopulate (not just reorder) since prices may have changed
        if same_theme:
            src_area = self._drop_area_index.get((src_r, src_t))
            if src_area is not None:
                src_area.repopulate(dst_qs_final, self._siq is not None)
                mw = self._mw_ref
                _schedule_save(mw, 200)
                return

        src_area = self._drop_area_index.get((src_r, src_t))
        dst_area = self._drop_area_index.get((dst_r, dst_t))
        if src_area is not None and dst_area is not None:
            src_area.repopulate(
                self.ds["rounds"][src_r]["themes"][src_t]["questions"],
                self._siq is not None)
            dst_area.repopulate(
                self.ds["rounds"][dst_r]["themes"][dst_t]["questions"],
                self._siq is not None)
        else:
            self._rebuild_content(animated=False)

        mw = self._mw_ref
        _schedule_save(mw, 200)


    # _on_table_row_clicked removed (table view removed)

    def _on_question_clicked(self, round_idx: int, theme_row: int, price: int):
        """Find question in SIQ and display it."""
        if self._siq is None or self._viewer is None: return
        q_obj = self._siq.find_question(round_idx, theme_row, price)
        if q_obj:
            self._viewer.show_question(q_obj, rnd_idx=round_idx, theme_idx=theme_row)
        # Deselect tiles in OTHER drop areas using the pre-built index.
        for key, drop_area in self._drop_area_index.items():
            try:
                if key != (round_idx, theme_row):
                    drop_area.select_tile(-1)
            except RuntimeError:
                pass

    def _on_question_price_change(self, rnd_idx: int, theme_idx: int, old_price: int):
        """Double-click on a question cell: ask for a new price and rename it."""
        self._push_undo()
        new_price, ok = QInputDialog.getInt(self, "Сменить стоимость",
                                            f"Новая стоимость вопроса [{old_price}]:",
                                            value=old_price, min=1, max=999999)
        if not ok or new_price == old_price:
            return
        # Update ds (allow duplicate prices if user wants)
        for q in self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"]:
            if q["price"] == old_price:
                q["price"] = new_price; break
        # Update SIQ
        if self._siq:
            try:
                qs = self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"]
                # Find by old_price in SIQ (it hasn't been updated yet)
                q_idx = _q_idx(qs, old_price)
                # Update in-memory SIQ price
                qs[q_idx]["price"] = new_price
                root, ns_url, tag, q_el = self._siq._xml_nav_q(rnd_idx, theme_idx, q_idx)
                q_el.set("price", str(new_price))
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[price_change siq] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw, 200)

    def _on_delete_question_requested(self, rnd_idx: int, theme_idx: int, price: int):
        """Delete a question from the theme (ds + siq) — no confirmation dialog."""
        self._push_undo()
        self._invalidate_fill_cache()
        # Remove from ds
        qs = self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"]
        self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"] = [q for q in qs if q["price"] != price]
        # Remove from SIQ
        if self._siq:
            try:
                siq_qs = self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"]
                self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"] = [q for q in siq_qs if q["price"] != price]
                root, ns_url, tag = self._siq._load_xml_root()
                theme_el, tag = self._siq._nav_to_question(root, tag, rnd_idx, theme_idx)
                qs_el = theme_el.find(tag("questions"))
                if qs_el is not None:
                    for q_el in qs_el.findall(tag("question")):
                        if q_el.get("price") == str(price):
                            qs_el.remove(q_el); break
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[delete_q siq] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw, 200)

    def _on_change_round_prices(self, rnd_idx: int):
        """Open a dialog with min/max/step spinboxes and re-price the round."""
        if self._siq is None: return
        if rnd_idx < 0 or rnd_idx >= len(self._siq.rounds): return
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                     QSpinBox, QDialogButtonBox)
        # Derive sensible defaults from the first non-empty theme
        cur_min, cur_max, cur_step = 100, 500, 100
        try:
            for th in self._siq.rounds[rnd_idx]["themes"]:
                qs = th["questions"]
                if len(qs) >= 2:
                    prs = sorted({q["price"] for q in qs})
                    cur_min, cur_max = prs[0], prs[-1]
                    cur_step = prs[1] - prs[0] if prs[1] > prs[0] else cur_step
                    break
                elif len(qs) == 1:
                    cur_min = cur_max = qs[0]["price"]
        except Exception:
            pass

        dlg = QDialog(self)
        dlg.setWindowTitle("Изменить цены в раунде")
        dlg.setStyleSheet(
            "QDialog{background:#181825;color:#cdd6f4;}"
            "QLabel{color:#cdd6f4;}"
            "QSpinBox{background:#1e1e2e;color:#cdd6f4;"
            "border:1px solid #45475a;border-radius:4px;padding:4px 6px;}"
            "QSpinBox:focus{border-color:#89b4fa;}"
            "QPushButton{background:#313244;color:#cdd6f4;"
            "border:1px solid #45475a;border-radius:4px;padding:6px 14px;}"
            "QPushButton:hover{background:#45475a;border-color:#89b4fa;}")
        v = QVBoxLayout(dlg); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)
        form = QFormLayout(); form.setSpacing(8)
        sp_min  = QSpinBox(); sp_min.setRange(1, 999999);  sp_min.setValue(cur_min)
        sp_max  = QSpinBox(); sp_max.setRange(1, 9999999); sp_max.setValue(cur_max)
        sp_step = QSpinBox(); sp_step.setRange(1, 999999); sp_step.setValue(cur_step)
        for sb in (sp_min, sp_max, sp_step): sb.setMinimumWidth(120)
        form.addRow("Минимальная цена:", sp_min)
        form.addRow("Максимальная цена:", sp_max)
        form.addRow("Шаг цены:",          sp_step)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        mn, mx, st = sp_min.value(), sp_max.value(), sp_step.value()
        if mx < mn:
            msgbox_warning(self, "Ошибка",
                                "Максимальная цена должна быть не меньше минимальной.")
            return

        self._push_undo()
        ok = self._siq.save_round_prices(rnd_idx, mn, mx, st)
        if not ok:
            # Roll back the undo snapshot we pushed — nothing actually changed.
            try:
                if self._undo_stack:
                    self._undo_stack.pop()
            except Exception:
                pass
            msgbox_warning(
                self, "Не удалось сохранить",
                "Не удалось записать новые цены в .siq файл — он, скорее всего, "
                "занят другой программой.\n\n"
                "Закройте файл, если он открыт в другом приложении "
                "(другой плеер/редактор вопросов, архиватор), дождитесь "
                "завершения синхронизации OneDrive, и попробуйте снова.")
            return
        # Sync ds["rounds"] prices from siq
        try:
            siq_themes = self._siq.rounds[rnd_idx]["themes"]
            ds_themes = self.ds["rounds"][rnd_idx]["themes"]
            for t_idx in range(min(len(siq_themes), len(ds_themes))):
                siq_qs = siq_themes[t_idx]["questions"]
                ds_qs = ds_themes[t_idx]["questions"]
                for i in range(min(len(siq_qs), len(ds_qs))):
                    ds_qs[i]["price"] = siq_qs[i]["price"]
        except Exception as e:
            _logger.warning(f"[change_round_prices ds-sync] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw, 200)

    def _delete_round(self, rnd_idx: int):
        """Delete a round (ds + siq XML)."""
        if rnd_idx < 0 or rnd_idx >= len(self.ds["rounds"]): return
        self._push_undo()
        self._invalidate_fill_cache()
        self.ds["rounds"].pop(rnd_idx)
        if self._siq:
            try:
                root, ns_url, tag = self._siq._load_xml_root()
                rnd_el, tag = self._siq._nav_to_round(root, tag, rnd_idx)
                for p in root.iter():
                    if rnd_el in list(p):
                        p.remove(rnd_el); break
                self._siq.rounds.pop(rnd_idx)
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[delete_round] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _delete_theme(self, rnd_idx: int, theme_idx: int):
        """Delete a theme from a round (ds + siq XML)."""
        try: self.ds["rounds"][rnd_idx]["themes"].pop(theme_idx)
        except (IndexError, KeyError): return
        self._push_undo()
        self._invalidate_fill_cache()
        if self._siq:
            try:
                root, ns_url, tag = self._siq._load_xml_root()
                rnd_el, tag = self._siq._nav_to_round(root, tag, rnd_idx)
                th_els = rnd_el.findall(f'{tag("themes")}/{tag("theme")}')
                if theme_idx < len(th_els):
                    themes_el = rnd_el.find(tag("themes"))
                    if themes_el is not None:
                        themes_el.remove(th_els[theme_idx])
                if rnd_idx < len(self._siq.rounds):
                    try: self._siq.rounds[rnd_idx]["themes"].pop(theme_idx)
                    except Exception: pass
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[delete_theme] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _move_theme(self, src_r: int, src_t: int, dst_r: int, dst_t: int):
        """Move a theme to another position, including across rounds."""
        if src_r == dst_r and src_t == dst_t: return
        self._push_undo()
        try:
            src_themes = self.ds["rounds"][src_r]["themes"]
            dst_themes = self.ds["rounds"][dst_r]["themes"]
            if src_t < 0 or src_t >= len(src_themes): return
            theme = src_themes.pop(src_t)
            # After removing from src, adjust dst_t if same round and dst_t > src_t
            adj_dst_t = dst_t
            if src_r == dst_r and dst_t > src_t:
                adj_dst_t = dst_t - 1
            adj_dst_t = max(0, min(adj_dst_t, len(dst_themes)))
            dst_themes.insert(adj_dst_t, theme)
        except Exception as e:
            _logger.warning(f"[move_theme ds] {e}"); return
        if self._siq:
            try:
                root, ns_url, tag = self._siq._load_xml_root()
                src_rnd_el, tag = self._siq._nav_to_round(root, tag, src_r)
                dst_rnd_el, _   = self._siq._nav_to_round(root, tag, dst_r)
                src_themes_el = src_rnd_el.find(tag("themes"))
                dst_themes_el = dst_rnd_el.find(tag("themes"))
                if src_themes_el is not None and dst_themes_el is not None:
                    src_th_els = list(src_themes_el)
                    if src_t < len(src_th_els):
                        el = src_th_els[src_t]
                        src_themes_el.remove(el)
                        dst_th_els = list(dst_themes_el)
                        ins = max(0, min(adj_dst_t, len(dst_th_els)))
                        dst_themes_el.insert(ins, el)
                siq_src = self._siq.rounds[src_r]["themes"]
                siq_dst = self._siq.rounds[dst_r]["themes"]
                if src_t < len(siq_src):
                    t = siq_src.pop(src_t)
                    siq_dst.insert(adj_dst_t, t)
                self._siq._save_xml(root, ns_url)
            except Exception as e:
                _logger.warning(f"[move_theme siq] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _add_round(self):
        """Append a new empty round instantly — name can be edited inline."""
        if self._siq is None: return
        name = ""   # empty — user fills via inline edit
        ok_siq = self._siq.add_round(name)
        if not ok_siq:
            msgbox_warning(self, "Ошибка", "Не удалось добавить раунд в .siq файл."); return
        self.ds["rounds"].append({"round_name": name, "themes": []})
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw)

    def _on_edit_question_requested(self, rnd_idx: int, theme_idx: int, price: int):
        """Open the question editor dialog."""
        if self._siq is None: return
        # Find q_idx from price
        try:
            questions = self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"]
            q_idx = _q_idx(questions, price)
        except (StopIteration, IndexError, KeyError):
            return
        self._push_undo()
        dlg = QuestionEditorDialog(self._siq, rnd_idx, theme_idx, q_idx, self)
        def _on_saved():
            # Refresh the displayed question
            q_obj = self._siq.find_question(rnd_idx, theme_idx, price)
            if q_obj and self._viewer:
                self._viewer.show_question(q_obj, rnd_idx=rnd_idx, theme_idx=theme_idx)
            self._rebuild_content(animated=False)
        dlg.saved.connect(_on_saved)
        dlg.exec()

    def _on_add_question_requested(self, rnd_idx: int, theme_idx: int):
        """Add a new empty question silently, sync ds, rebuild table."""
        self._push_undo()
        # Works with or without SIQ
        # Always derive prices from the live XML to avoid stale in-memory state
        try:
            if self._siq:
                root_p, ns_p, tag_p = self._siq._load_xml_root()
                rounds_p = root_p.findall(f'.//{tag_p("round")}')
                themes_p = rounds_p[rnd_idx].findall(f'{tag_p("themes")}/{tag_p("theme")}')
                qs_el_p  = themes_p[theme_idx].findall(f'{tag_p("questions")}/{tag_p("question")}')
                existing_prices = {int(q.get("price", 0)) for q in qs_el_p}
            else:
                qs_list = self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"]
                existing_prices = {q["price"] for q in qs_list}
        except Exception:
            existing_prices = set()
        if existing_prices:
            suggested = max(existing_prices) + 50
        else:
            suggested = 50
        while suggested in existing_prices:
            suggested += 50

        new_q_ds = {"price": suggested, "tries": 0, "right": 0,
                    "items": [{"param":"question","type":"text","text":"",
                               "is_ref":False,"dur":2.0,"placement":"","simultaneous":False}],
                    "answers":[""],"wrong_answers":[],"answer_options":{},"q_type":"","dur":2.0}

        # Add to ds["rounds"] (always)
        try:
            self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"].append(new_q_ds)
        except Exception as e:
            _logger.warning(f"[add_q ds] {e}"); return

        # Add to SIQ XML if attached
        if self._siq:
            ok = self._siq.add_question(rnd_idx, theme_idx, suggested)
            if not ok:
                # Roll back ds
                try:
                    qs = self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"]
                    qs[:] = [q for q in qs if q["price"] != suggested]
                except Exception: pass
                msgbox_warning(self, "Ошибка", "Не удалось добавить вопрос в .siq файл.")
                return
            # Ensure ds and siq are in sync
            try:
                self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"][-1] = \
                    self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"][-1]
            except Exception: pass

        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _schedule_save(mw, 200)


    def _copy_all_answers_dialog(self, datasets: list):
        """Show package selection dialog, then copy answers from chosen packages."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QScrollArea

        dlg = QDialog(self)
        dlg.setWindowTitle("📝 Выбрать пакеты для копирования ответов")
        dlg.setMinimumWidth(420)
        dlg.setMinimumHeight(360)
        dlg.setStyleSheet("QDialog{background:#181825;color:#cdd6f4;}")

        vl = QVBoxLayout(dlg); vl.setContentsMargins(16,14,16,14); vl.setSpacing(8)
        vl.addWidget(_lbl("Выберите пакеты:", "color:#cdd6f4;font-size:12px;font-weight:700;"))

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:1px solid #45475a;border-radius:4px;background:#1e1e2e;")
        inner = QWidget(); inner.setStyleSheet(_SS_TRANSPARENT)
        il = QVBoxLayout(inner); il.setContentsMargins(8,8,8,8); il.setSpacing(4)
        scroll.setWidget(inner)
        vl.addWidget(scroll, stretch=1)

        _checkboxes: list = []
        for ds in datasets:
            pkg = ds.get("pkg_name","?")
            w = ds.get("widget")
            siq = getattr(w, "_siq", None) if w else None
            cb = QCheckBox(pkg)
            cb.setChecked(True)
            cb.setStyleSheet(
                "QCheckBox{color:#cdd6f4;font-size:12px;}"
                "QCheckBox::indicator{width:14px;height:14px;border:1px solid #45475a;"
                "border-radius:3px;background:#1e1e2e;}"
                "QCheckBox::indicator:checked{background:#89b4fa;border-color:#89b4fa;}")
            il.addWidget(cb)
            _checkboxes.append((cb, ds, siq))

        bot = QHBoxLayout(); bot.addStretch()
        sel_all = AnimatedButton("✓ Все"); sel_all.setObjectName(_ON_BTN_SORT); sel_all.setFixedHeight(24)
        sel_none = AnimatedButton("✗ Ни одного"); sel_none.setObjectName(_ON_BTN_SORT); sel_none.setFixedHeight(24)
        sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb,_,__ in _checkboxes])
        sel_none.clicked.connect(lambda: [cb.setChecked(False) for cb,_,__ in _checkboxes])
        cancel_btn = AnimatedButton("Отмена"); cancel_btn.clicked.connect(dlg.reject)
        ok_btn = AnimatedButton("📋 Копировать"); ok_btn.setObjectName(_ON_BTN_ANALYZE)
        ok_btn.clicked.connect(dlg.accept)
        bot.addWidget(sel_all); bot.addWidget(sel_none); bot.addWidget(cancel_btn); bot.addWidget(ok_btn)
        vl.addLayout(bot)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        chosen = [(ds, siq) for cb, ds, siq in _checkboxes if cb.isChecked()]
        if not chosen:
            return

        def _is_filename(s: str) -> bool:
            return Path(s.strip()).suffix.lower() in _MEDIA_EXTS

        def _collect_texts(items, param):
            return [it["text"].strip() for it in items
                    if it.get("param") == param
                    and it.get("type") == "text"
                    and not it.get("is_ref")
                    and it.get("text","").strip()]

        all_lines = []
        for ds, siq in chosen:
            pkg_name = ds.get("pkg_name","Пакет")
            all_lines.append(f"=== {pkg_name} ===")
            all_lines.append("")
            rounds_src = siq.rounds if siq else []
            for rd in rounds_src:
                all_lines.append(f"[{rd['name']}]")
                for th in rd["themes"]:
                    for q in th["questions"]:
                        q_type = q.get("q_type","")
                        # Skip point-on-image answers
                        if q_type == "point":
                            continue
                        items = q.get("items",[])

                        if q_type == "select":
                            # Include select-type answer options text
                            opts = q.get("answer_options",{})
                            correct_keys = set(q.get("answers",[]))
                            parts = []
                            for k in sorted(opts.keys()):
                                opt_items = opts[k]
                                for oi in opt_items:
                                    if oi.get("type")=="text" and not oi.get("is_ref") and oi.get("text","").strip():
                                        mark = "✓" if k in correct_keys else ""
                                        parts.append(f"{k}{mark}: {oi['text'].strip()}")
                            if parts:
                                all_lines.append("📋 " + " | ".join(parts))
                        else:
                            right_raw = [a.strip() for a in q.get("answers",[]) if a.strip()]
                            right = [a for a in right_raw if not _is_filename(a)]
                            ans_param_texts = _collect_texts(items, "answer")
                            for t in ans_param_texts:
                                if t not in right:
                                    right.append(t)
                            if right:
                                all_lines.append("✅ " + " | ".join(right))
                    all_lines.append("")
            all_lines.append("")

        QApplication.clipboard().setText("\n".join(all_lines))
        mw = self._mw_ref
        if hasattr(mw, "_show_save_notification"):
            mw._save_notif.setText("📋  Ответы скопированы")
            mw._show_save_notification()
            _notif_reset(mw)

    def _copy_all_answers(self):
        """Legacy single-package copy — delegates to dialog with only this dataset."""
        mw = self._mw_ref
        datasets = getattr(mw, 'datasets', ())
        self._copy_all_answers_dialog(datasets)

    def _save_siq_inplace(self):
        """SIQ is already auto-saved on every edit; show notification and refresh date."""
        src = self.ds.get("siq_path", "")
        if not src or not os.path.exists(src):
            msgbox_warning(self, "Нет файла", "SIQ-файл не найден или не прикреплён.")
            return
        mw = self._mw_ref
        if hasattr(mw, '_show_save_notification'):
            mw._show_save_notification()
        self._refresh_banner_widget()   # pick up the current on-disk package size
        # Refresh the "saved: dd.mm.yyyy HH:MM" label in the toolbar
        if hasattr(mw, '_set_filename_text'):
            try:
                mtime = os.path.getmtime(src)
                dt = _dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                mw._set_filename_text(f"📄 {os.path.basename(src)}  · сохранён {dt}")
            except Exception:
                pass

    # ── Undo / Redo ────────────────────────────────────────
    _MAX_UNDO = 40

    def _push_undo(self):
        """Snapshot current state onto the undo stack (O(1) deque append)."""
        self._undo_stack.append(self._snapshot_current())
        self._redo_stack.clear()

    def _snapshot_current(self) -> tuple:
        """Return (rounds_copy, siq_xml) for the current state.
        Uses json round-trip instead of copy.deepcopy — significantly faster for
        large round structures because json encode/decode is implemented in C."""
        try:
            rounds_copy = json.loads(json.dumps(self.ds["rounds"], ensure_ascii=False))
        except Exception:
            rounds_copy = copy.deepcopy(self.ds["rounds"])
        siq_xml = None
        if self._siq:
            try:
                # Re-use the cached XML bytes if available — avoids a zip.read()
                # on every undo push (which happens on every single edit).
                cache = self._siq._xml_cache
                if cache is not None:
                    # cache[0] is (len, hash) key; the actual bytes were consumed
                    # already — re-read only when the cache was just invalidated.
                    siq_xml = self._siq._zip.read('content.xml')
                else:
                    siq_xml = self._siq._zip.read('content.xml')
            except Exception:
                pass
        return rounds_copy, siq_xml

    def _apply_snapshot(self, rounds_copy, siq_xml):
        self.ds["rounds"] = rounds_copy
        if self._siq and siq_xml is not None:
            try:
                self._siq._rewrite_zip(siq_xml)
                self._siq._reload_rounds()
            except Exception as e:
                _logger.warning(f"[apply_snapshot siq] {e}")
        self._rebuild_content(animated=False)
        _schedule_save(self._mw_ref, 200)

    def do_undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot_current())
        self._apply_snapshot(*self._undo_stack.pop())

    def do_redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot_current())
        self._apply_snapshot(*self._redo_stack.pop())

__all__ = [
    'ResultPage',
]
