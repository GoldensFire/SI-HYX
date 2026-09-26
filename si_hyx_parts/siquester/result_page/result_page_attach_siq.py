# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: attach_siq. Public namespace: siquester.result_page."""
import siquester.result_page as _api


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
