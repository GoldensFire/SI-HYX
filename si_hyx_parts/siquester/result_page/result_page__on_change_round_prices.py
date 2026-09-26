# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _on_change_round_prices. Public namespace: siquester.result_page."""
import siquester.result_page as _api


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
