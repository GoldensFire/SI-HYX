# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Страница пакета: правка раундов, тем и вопросов, цены, undo и сохранение."""
import siquester.result_page as _api


class ResultPageEditingMixin:
    """Страница пакета: правка раундов, тем и вопросов, цены, undo и сохранение."""

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
            _api.msgbox_warning(self, "Ошибка",
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
            _api.msgbox_warning(
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
            _api._logger.warning(f"[change_round_prices ds-sync] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw, 200)

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
                _api._logger.warning(f"[delete_round] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw)

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
                _api._logger.warning(f"[delete_theme] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw)

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
            _api._logger.warning(f"[move_theme ds] {e}"); return
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
                _api._logger.warning(f"[move_theme siq] {e}")
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw)

    def _add_round(self):
        """Append a new empty round instantly — name can be edited inline."""
        if self._siq is None: return
        name = ""   # empty — user fills via inline edit
        ok_siq = self._siq.add_round(name)
        if not ok_siq:
            _api.msgbox_warning(self, "Ошибка", "Не удалось добавить раунд в .siq файл."); return
        self.ds["rounds"].append({"round_name": name, "themes": []})
        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw)

    def _on_edit_question_requested(self, rnd_idx: int, theme_idx: int, price: int):
        """Open the question editor dialog."""
        if self._siq is None: return
        # Find q_idx from price
        try:
            questions = self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"]
            q_idx = _api._q_idx(questions, price)
        except (StopIteration, IndexError, KeyError):
            return
        self._push_undo()
        dlg = _api.QuestionEditorDialog(self._siq, rnd_idx, theme_idx, q_idx, self)
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
            _api._logger.warning(f"[add_q ds] {e}"); return

        # Add to SIQ XML if attached
        if self._siq:
            ok = self._siq.add_question(rnd_idx, theme_idx, suggested)
            if not ok:
                # Roll back ds
                try:
                    qs = self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"]
                    qs[:] = [q for q in qs if q["price"] != suggested]
                except Exception: pass
                _api.msgbox_warning(self, "Ошибка", "Не удалось добавить вопрос в .siq файл.")
                return
            # Ensure ds and siq are in sync
            try:
                self.ds["rounds"][rnd_idx]["themes"][theme_idx]["questions"][-1] = \
                    self._siq.rounds[rnd_idx]["themes"][theme_idx]["questions"][-1]
            except Exception: pass

        self._rebuild_content(animated=False)
        mw = self._mw_ref
        _api._schedule_save(mw, 200)

    def _copy_all_answers_dialog(self, datasets: list):
        """Show package selection dialog, then copy answers from chosen packages."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QScrollArea

        dlg = QDialog(self)
        dlg.setWindowTitle("📝 Выбрать пакеты для копирования ответов")
        dlg.setMinimumWidth(420)
        dlg.setMinimumHeight(360)
        dlg.setStyleSheet("QDialog{background:#181825;color:#cdd6f4;}")

        vl = QVBoxLayout(dlg); vl.setContentsMargins(16,14,16,14); vl.setSpacing(8)
        vl.addWidget(_api._lbl("Выберите пакеты:", "color:#cdd6f4;font-size:12px;font-weight:700;"))

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:1px solid #45475a;border-radius:4px;background:#1e1e2e;")
        inner = _api.QWidget(); inner.setStyleSheet(_api._SS_TRANSPARENT)
        il = QVBoxLayout(inner); il.setContentsMargins(8,8,8,8); il.setSpacing(4)
        scroll.setWidget(inner)
        vl.addWidget(scroll, stretch=1)

        _checkboxes: list = []
        for ds in datasets:
            pkg = ds.get("pkg_name","?")
            w = ds.get("widget")
            siq = getattr(w, "_siq", None) if w else None
            cb = _api.QCheckBox(pkg)
            cb.setChecked(True)
            cb.setStyleSheet(
                "QCheckBox{color:#cdd6f4;font-size:12px;}"
                "QCheckBox::indicator{width:14px;height:14px;border:1px solid #45475a;"
                "border-radius:3px;background:#1e1e2e;}"
                "QCheckBox::indicator:checked{background:#89b4fa;border-color:#89b4fa;}")
            il.addWidget(cb)
            _checkboxes.append((cb, ds, siq))

        bot = QHBoxLayout(); bot.addStretch()
        sel_all = _api.AnimatedButton("✓ Все"); sel_all.setObjectName(_api._ON_BTN_SORT); sel_all.setFixedHeight(24)
        sel_none = _api.AnimatedButton("✗ Ни одного"); sel_none.setObjectName(_api._ON_BTN_SORT); sel_none.setFixedHeight(24)
        sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb,_,__ in _checkboxes])
        sel_none.clicked.connect(lambda: [cb.setChecked(False) for cb,_,__ in _checkboxes])
        cancel_btn = _api.AnimatedButton("Отмена"); cancel_btn.clicked.connect(dlg.reject)
        ok_btn = _api.AnimatedButton("📋 Копировать"); ok_btn.setObjectName(_api._ON_BTN_ANALYZE)
        ok_btn.clicked.connect(dlg.accept)
        bot.addWidget(sel_all); bot.addWidget(sel_none); bot.addWidget(cancel_btn); bot.addWidget(ok_btn)
        vl.addLayout(bot)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        chosen = [(ds, siq) for cb, ds, siq in _checkboxes if cb.isChecked()]
        if not chosen:
            return

        def _is_filename(s: str) -> bool:
            return _api.Path(s.strip()).suffix.lower() in _api._MEDIA_EXTS

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

        _api.QApplication.clipboard().setText("\n".join(all_lines))
        mw = self._mw_ref
        if hasattr(mw, "_show_save_notification"):
            mw._save_notif.setText("📋  Ответы скопированы")
            mw._show_save_notification()
            _api._notif_reset(mw)

    def _save_siq_inplace(self):
        """SIQ is already auto-saved on every edit; show notification and refresh date."""
        src = self.ds.get("siq_path", "")
        if not src or not _api.os.path.exists(src):
            _api.msgbox_warning(self, "Нет файла", "SIQ-файл не найден или не прикреплён.")
            return
        mw = self._mw_ref
        if hasattr(mw, '_show_save_notification'):
            mw._show_save_notification()
        self._refresh_banner_widget()   # pick up the current on-disk package size
        # Refresh the "saved: dd.mm.yyyy HH:MM" label in the toolbar
        if hasattr(mw, '_set_filename_text'):
            try:
                mtime = _api.os.path.getmtime(src)
                dt = _api._dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                mw._set_filename_text(f"📄 {_api.os.path.basename(src)}  · сохранён {dt}")
            except Exception:
                pass

    def _push_undo(self):
        """Snapshot current state onto the undo stack (O(1) deque append)."""
        self._undo_stack.append(self._snapshot_current())
        self._redo_stack.clear()

    def _snapshot_current(self) -> tuple:
        """Return (rounds_copy, siq_xml) for the current state.
        Uses json round-trip instead of copy.deepcopy — significantly faster for
        large round structures because json encode/decode is implemented in C."""
        try:
            rounds_copy = _api.json.loads(_api.json.dumps(self.ds["rounds"], ensure_ascii=False))
        except Exception:
            rounds_copy = _api.copy.deepcopy(self.ds["rounds"])
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
                _api._logger.warning(f"[apply_snapshot siq] {e}")
        self._rebuild_content(animated=False)
        _api._schedule_save(self._mw_ref, 200)

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
