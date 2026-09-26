# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _flush_tile_fills_sync. Public namespace: siquester.result_page."""
import siquester.result_page as _api


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
        _api._logger.warning(f"[move_round ds] {e}"); return
    if self._siq:
        try: self._siq.move_round(src_idx, dst_idx)
        except Exception as e: _api._logger.warning(f"[move_round siq] {e}")
    self._rebuild_content(animated=False)
    mw = self._mw_ref
    _api._schedule_save(mw)

def _add_theme(self, rnd_idx: int):
    """Add a new empty theme instantly — name can be edited inline."""
    if self._siq is None: return
    name = ""   # empty — user fills via inline double-click rename
    ok_siq = self._siq.add_theme(rnd_idx, name)
    if not ok_siq:
        _api.msgbox_warning(self, "Ошибка", "Не удалось добавить тему в .siq файл."); return
    self.ds["rounds"][rnd_idx]["themes"].append({"name": name, "questions": []})
    self._rebuild_content(animated=False)
    mw = self._mw_ref
    _api._schedule_save(mw)

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

        src_qs.remove(q_obj)
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
            dst_qs.insert(ds_clamped, q_obj)

        # ── Auto-price: reprice entire dst theme by column ───────────
        # After reorder, every tile in the destination theme gets the
        # majority price for its column position (from all OTHER themes).
        # This prevents duplicates and keeps the grid consistent.
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
                canon = _api._collections.Counter(col_prices).most_common(1)[0][0]
                old_p = tile_q["price"]
                if old_p != canon:
                    _price_remap[old_p] = canon
                    tile_q["price"] = canon
    except Exception as e:
        _api._logger.warning(f"[move_tile ds] {e}"); return

    # ── 2. Update SIQ XML ─────────────────────────────────────
    if self._siq:
        try:
            root, ns_url, tag = self._siq._load_xml_root()
            src_theme_el, tag = self._siq._nav_to_question(root, tag, src_r, src_t)
            dst_theme_el, _   = self._siq._nav_to_question(root, tag, dst_r, dst_t)
            src_qs_el = src_theme_el.find(tag('questions'))
            dst_qs_el = dst_theme_el.find(tag('questions'))
            if dst_qs_el is None:
                dst_qs_el = _api.ET.SubElement(dst_theme_el, tag('questions'))
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
            _api._logger.warning(f"[move_tile siq] {e}")

    # ── 3. Update UI ──────────────────────────────────────────
    # Always repopulate (not just reorder) since prices may have changed
    if same_theme:
        src_area = self._drop_area_index.get((src_r, src_t))
        if src_area is not None:
            src_area.repopulate(dst_qs_final, self._siq is not None)
            mw = self._mw_ref
            _api._schedule_save(mw, 200)
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
    _api._schedule_save(mw, 200)

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
    new_price, ok = _api.QInputDialog.getInt(self, "Сменить стоимость",
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
            q_idx = _api._q_idx(qs, old_price)
            # Update in-memory SIQ price
            qs[q_idx]["price"] = new_price
            root, ns_url, tag, q_el = self._siq._xml_nav_q(rnd_idx, theme_idx, q_idx)
            q_el.set("price", str(new_price))
            self._siq._save_xml(root, ns_url)
        except Exception as e:
            _api._logger.warning(f"[price_change siq] {e}")
    self._rebuild_content(animated=False)
    mw = self._mw_ref
    _api._schedule_save(mw, 200)

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
            _api._logger.warning(f"[delete_q siq] {e}")
    self._rebuild_content(animated=False)
    mw = self._mw_ref
    _api._schedule_save(mw, 200)
