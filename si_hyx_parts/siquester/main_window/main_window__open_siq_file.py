# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MainWindow: _open_siq_file. Public namespace: siquester.main_window."""
import siquester.main_window as _api


def _open_siq_file(self, path):
    try: siq = _api.SiqPackage(path)
    except Exception as e: _api.msgbox_warning(self,"Ошибка .siq",str(e)); return
    file_mb = _api.os.path.getsize(path)/1024/1024
    siq_rounds = [{"round_name":rd["name"],"themes":[{"name":th["name"],"questions":[{"price":q["price"],"tries":0,"right":0} for q in th["questions"]]} for th in rd["themes"]]} for rd in siq.rounds]

    match_idx = None
    for i,ds in enumerate(self.datasets):
        if ds["pkg_name"].strip().lower() == siq.name.strip().lower(): match_idx=i; break

    if match_idx is not None:
        ds = self.datasets[match_idx]
        ds["total_duration_sec"] = siq.total_duration
        ds["siq_path"] = path
        if not ds.get("pkg_size"): ds["pkg_size"] = f"{file_mb:.1f} МБ"
        # Ensure ds has at least as many rounds as the siq (handles newly added rounds)
        for ri, siq_rd in enumerate(siq.rounds):
            if ri >= len(ds.get("rounds", [])):
                if "rounds" not in ds: ds["rounds"] = []
                ds["rounds"].append({
                    "round_name": siq_rd["name"],
                    "round_type": siq_rd.get("type", ""),
                    "round_comment": siq_rd.get("comment", ""),
                    "themes": [
                        {"name": th["name"],
                         "questions": [{"price": q["price"], "tries": 0, "right": 0}
                                       for q in th["questions"]]}
                        for th in siq_rd["themes"]
                    ]
                })
        _api.save_datasets(self.datasets)
        ds["widget"].attach_siq(siq)
        self.sidebar.rebuild(self.datasets)
        self.sidebar.select_by_real(match_idx); self._show_ds(match_idx)
        real_idx = match_idx
    else:
        new_ds = {"pkg_name":siq.name,"stats":"","pkg_size":f"{file_mb:.1f} МБ",
                  "rounds":siq_rounds,"tab_id":self.sidebar.current_tab_id(),
                  "total_duration_sec":siq.total_duration,"siq_path":path}
        self._add_dataset(new_ds)
        idx = len(self.datasets)-1
        self.sidebar.select_by_real(idx); self._show_ds(idx)
        self.datasets[idx]["widget"].attach_siq(siq)
        real_idx = idx

    self._auto_fetch_stats(real_idx, siq.name, list(siq.pkg_authors), siq.rounds)

def _auto_fetch_stats(self, real_idx, name, authors, siq_rounds):
    """Тянет статистику пакета с SIStatistics в фоне — логика имя+авторы
        в siquester/stats_api.py и siquester/auto_stats.py.
        Без авторов запрос почти гарантированно 404 — не тратим время впустую."""
    if not authors:
        return
    # Карта (round_idx,theme_idx,question_idx) -> (round_name,theme_name,price):
    # у API индексы порядковые, а в ds["rounds"] (после attach_siq) вопросы
    # ищутся по имени раунда/темы + цене — строим карту, пока индексы под рукой.
    keymap = {}
    for r_idx, rd in enumerate(siq_rounds):
        for t_idx, th in enumerate(rd["themes"]):
            for q_idx, q in enumerate(th["questions"]):
                keymap[(r_idx, t_idx, q_idx)] = (rd["name"], th["name"], q["price"])

    def _do_fetch():
        try:
            result = _api.auto_stats.fetch(name, authors)
        except Exception as e:
            _api._logger.warning(f"[auto stats] {e}")
            return
        if result is None:
            return
        summary, per_question = result
        named = {keymap[k]: v for k, v in per_question.items() if k in keymap}
        _api._get_ui_bridge().deliver_call(
            lambda: self._apply_auto_stats(real_idx, summary, named))
    _api._threading.Thread(target=_do_fetch, daemon=True, name="auto-stats").start()

def _apply_auto_stats(self, real_idx, summary, named_stats):
    """Накладывает результат _auto_fetch_stats на уже открытый датасет.

        И сводная строка ("Завершённых игр"), и поштучная статистика вопросов
        (tries/right) обновляются КАЖДЫЙ раз, когда пришли свежие данные — обе
        растут со временем по мере того, как в игру играют ещё. Раньше tries/
        right заполнялись только в пустые (0/0) значения (защита от перетирания
        ручной вставки HTML с сайта) — но ручная вставка убрана, автофетч теперь
        единственный источник, поэтому «замораживать» значения на первом фетче
        больше не нужно: пак иначе никогда не подхватывал бы новую статистику."""
    if real_idx >= len(self.datasets):
        return
    ds = self.datasets[real_idx]
    changed = False
    if summary.get("rate") is not None:
        pct = round(summary["rate"] * 100)
        new_stats = f"Завершенных игр: {summary['completed']} из {summary['started']} ({pct}%)"
        if new_stats != ds.get("stats"):
            ds["stats"] = new_stats
            changed = True
    for rd in ds.get("rounds", []):
        rn = rd.get("round_name", "")
        for th in rd.get("themes", []):
            tn = th.get("name", "")
            for q in th.get("questions", []):
                key = (rn, tn, q.get("price"))
                st = named_stats.get(key)
                if st and (q.get("tries") != st["tries"] or q.get("right") != st["right"]):
                    q["tries"] = st["tries"]; q["right"] = st["right"]
                    changed = True
    if not changed:
        return

    # Пересобираем страницу пакета целиком — точечно перекрашивать уже
    # построенные плитки менее надёжно, чем просто пересоздать страницу.
    old_w = ds["widget"]
    new_w = _api.ResultPage(ds, parent=self)
    if hasattr(old_w, "_siq") and old_w._siq:
        new_w.attach_siq(old_w._siq)
    self.stack.addWidget(new_w)
    ds["widget"] = new_w
    was_current = self.stack.currentWidget() is old_w
    self.stack.removeWidget(old_w)
    old_w.deleteLater()
    if was_current:
        self.stack.setCurrentWidget(new_w)
    self.sidebar.rebuild(self.datasets)
    _api.save_datasets(self.datasets)

def _show_save_notification(self):
    """Show 'Файл сохранён' banner at top-center of the window for 3 seconds."""
    lbl = self._save_notif
    lbl.adjustSize()
    x = (self.width() - lbl.width()) // 2
    lbl.move(x, 8)
    lbl.raise_(); lbl.show()
    self._save_notif_timer.start(3000)

def resizeEvent(self, e):
    super(_api.MainWindow, self).resizeEvent(e)
    if hasattr(self, '_save_notif') and self._save_notif.isVisible():
        self._save_notif.adjustSize()
        x = (self.width() - self._save_notif.width()) // 2
        self._save_notif.move(x, 8)
    if hasattr(self, '_search_panel'):
        self._reposition_panels()
        # Keep visible panels in correct position
        for p in (self._search_panel, self._media_search_panel):
            if p.isVisible():
                p.raise_()

def dragEnterEvent(self,e):
    if e.mimeData().hasUrls(): e.acceptProposedAction()
    else: super(_api.MainWindow, self).dragEnterEvent(e)

def dragMoveEvent(self,e):
    if e.mimeData().hasUrls(): e.acceptProposedAction()

def dropEvent(self,e):
    for url in e.mimeData().urls():
        p=url.toLocalFile()
        if _api.os.path.splitext(p)[1].lower() == '.siq': self._open_siq_file(p); e.acceptProposedAction(); return
    super(_api.MainWindow, self).dropEvent(e)

def _delete_ds(self,real_idx):
    if not(0<=real_idx<len(self.datasets)): return
    ds=self.datasets[real_idx]; w=ds["widget"]
    if hasattr(w,"_siq") and w._siq:
        try: w._siq.close()
        except Exception: pass
    self.stack.removeWidget(w); w.deleteLater(); self.datasets.pop(real_idx)
    self.sidebar.rebuild(self.datasets); self._update_info()
    _api.save_datasets(self.datasets)   # saves immediately with item removed
    if self.datasets: ni=min(real_idx,len(self.datasets)-1); self.sidebar.select_by_real(ni); self._show_ds(ni)
    else: self.stack.setCurrentWidget(self.empty_page)

def _on_reorder(self,real_from,real_to):
    if not(0<=real_from<len(self.datasets) and 0<=real_to<len(self.datasets)) or real_from==real_to: return
    item=self.datasets.pop(real_from); self.datasets.insert(real_to,item)
    self.sidebar.rebuild(self.datasets); self.sidebar.select_by_real(real_to); self._show_ds(real_to); _api.save_datasets(self.datasets)

def _move_to_tab(self,real_idx,tab_id):
    if 0<=real_idx<len(self.datasets): self.datasets[real_idx]["tab_id"]=tab_id; self.sidebar.rebuild(self.datasets); _api.save_datasets(self.datasets)

def _save_after_theme_move(self):
    _api.save_datasets(self.datasets)
    # Refresh the "saved: dd.mm.yyyy HH:MM" label for the current package
    try:
        idx = self.sidebar.current_real_idx()
        if 0 <= idx < len(self.datasets):
            siq_path = self.datasets[idx].get("siq_path", "")
            if siq_path and _api.os.path.exists(siq_path):
                mtime = _api.os.path.getmtime(siq_path)
                dt = _api._dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                self._set_filename_text(f"📄 {_api.os.path.basename(siq_path)}  · сохранён {dt}")
    except Exception:
        pass

def _rename_pkg(self, real_idx: int, new_name: str):
    if not (0 <= real_idx < len(self.datasets)): return
    self.datasets[real_idx]["pkg_name"] = new_name
    # Update SIQ file name if attached
    w = self.datasets[real_idx]["widget"]
    if hasattr(w, '_siq') and w._siq:
        w._siq.name = new_name
    w._refresh_banner_widget()
    self.sidebar.rebuild(self.datasets)
    self._update_info()
    _api.save_datasets(self.datasets)

def _update_info(self):
    n=len(self.datasets)
    if not n: self.lbl_info.setText(""); return
    total=sum(sum(sum(len(t["questions"]) for t in rd["themes"]) for rd in ds["rounds"]) for ds in self.datasets)
    self.lbl_info.setText(f"Пакетов: {n}  ·  вопросов: {total}")

def closeEvent(self,e):
    for ds in self.datasets:
        w=ds["widget"]
        if hasattr(w,"_siq") and w._siq:
            try: w._siq.close()
            except Exception: pass
    e.accept()
    # Force exit so any stuck daemon threads don't keep the process alive —
    # ТОЛЬКО в standalone-режиме (окно top-level, без родителя). Встроенное в
    # SI-HYX окно имеет родителя (вкладку): убивать весь хост-процесс нельзя.
    if self.parent() is None:
        _api.QTimer.singleShot(500, lambda: _api.os._exit(0))
