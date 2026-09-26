# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab: apply_settings. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def apply_settings(self, s: dict):
    """Восстанавливает настройки из словаря (вызывается при создании вкладки)."""
    if not _api._HAS_API or not isinstance(s, dict):
        return
    ct = s.get("content_type", _api.CONTENT_ANIME)
    idx = self.cb_content.findData(ct)
    if idx >= 0:
        self.cb_content.blockSignals(True)
        self.cb_content.setCurrentIndex(idx)
        self.cb_content.blockSignals(False)
        self._rebuild_kind_status()
        self.lbl_eps.setText("Главы от" if ct == _api.CONTENT_MANGA else "Эпизоды от")
    self.ed_query.setText(str(s.get("query", "")))
    self._collapse_franchise = bool(s.get("collapse_franchise", True))
    self.chk_collapse_fr.blockSignals(True)
    self.chk_collapse_fr.setChecked(self._collapse_franchise)
    self.chk_collapse_fr.blockSignals(False)
    self.sp_score_min.setValue(float(s.get("score_min", 0.0) or 0.0))
    self.sp_score_max.setValue(float(s.get("score_max", 10.0) or 10.0))
    oi = self.cb_order.findData(s.get("order", _api.ORDER_VIEWS))
    if oi >= 0:
        self.cb_order.setCurrentIndex(oi)
    self.sp_views_max.setValue(
        int(s.get("views_max", _api._VIEWS_SORT_MAX) or _api._VIEWS_SORT_MAX))
    self._update_views_max_enabled()
    self.sp_stop_limit.setValue(
        int(s.get("stop_limit", _api._STOP_LIMIT_DEFAULT) or 0))
    ki = self.cb_kind.findData(s.get("kind", ""))
    if ki >= 0:
        self.cb_kind.setCurrentIndex(ki)
    si = self.cb_status.findData(s.get("status", ""))
    if si >= 0:
        self.cb_status.setCurrentIndex(si)
    self.sp_year_from.setValue(int(s.get("year_from", 0) or 0))
    self.sp_year_to.setValue(int(s.get("year_to", 0) or 0))
    self.sp_ep_min.setValue(int(s.get("ep_min", 0) or 0))
    self.sp_ep_max.setValue(int(s.get("ep_max", 0) or 0))
    # Жанры/темы подтянутся после загрузки списка (см. _on_genres_loaded).
    # Поддерживаем и старый формат настроек (один «genre»: int).
    gids = s.get("genres")
    if gids is None:
        one = int(s.get("genre", 0) or 0)
        gids = [one] if one else []
    self._pending_genres = [int(x) for x in gids if x]
    self._pending_excl = [int(x) for x in (s.get("excl_genres") or []) if x]
    ct = self._content_type()
    if ct in self._genres_cache:
        valid = {gid for gid, _, _ in self._genres_cache[ct]}
        self._sel_genres = [g for g in self._pending_genres if g in valid]
        self._pending_genres = []
        self._excl_genres = [g for g in self._pending_excl if g in valid]
        self._pending_excl = []
    self._update_genres_btn()
    # Выбранные паки восстанавливаем (если SiQuesterHYX уже загрузил их).
    names = list(s.get("excluded_packs", []) or [])
    if names:
        self._restore_packs(names)

def _restore_packs(self, names: list):
    """Восстанавливает исключаемые паки по именам (если они уже загружены)."""
    wanted = set(names)
    excluded = set()
    found = []
    for idx, ds in enumerate(self._siq_datasets()):
        name = ds.get("pkg_name") or f"Пак {idx + 1}"
        if name in wanted:
            found.append(name)
            excluded |= self._pack_answers(ds)
    # Имена помним даже если паки ещё не открыты — попадут при следующем выборе.
    self._excluded_packs = found or list(names)
    self._excluded = excluded
    self._rebuild_excluded_bases()
    if found:
        self.lbl_packs.setText(
            f"Выбрано паков: {len(found)} ({len(excluded)} ответов).\n"
            + ", ".join(found))
    elif names:
        self.lbl_packs.setText(
            "Сохранённые паки не загружены в SiQuesterHYX — откройте их там.")

def reset_settings(self):
    """Сбрасывает все фильтры и выбранные паки к значениям по умолчанию."""
    if not _api._HAS_API:
        return
    self.cb_content.setCurrentIndex(0)   # Аниме (вызовет _on_content_changed)
    self.ed_query.clear()
    self.sp_score_min.setValue(0.0)
    self.sp_score_max.setValue(10.0)
    self.cb_order.setCurrentIndex(0)
    self.sp_views_max.setValue(_api._VIEWS_SORT_MAX)
    self._update_views_max_enabled()
    self.sp_stop_limit.setValue(_api._STOP_LIMIT_DEFAULT)
    self.cb_kind.setCurrentIndex(0)
    self.cb_status.setCurrentIndex(0)
    self._sel_genres = []
    self._pending_genres = []
    self._excl_genres = []
    self._pending_excl = []
    self._update_genres_btn()
    self.sp_year_from.setValue(0)
    self.sp_year_to.setValue(0)
    self.sp_ep_min.setValue(0)
    self.sp_ep_max.setValue(0)
    self._excluded = set()
    self._excluded_bases = set()
    self._excluded_franchises = set()
    self._excluded_packs = []
    self._collapse_franchise = True
    self.chk_collapse_fr.blockSignals(True)
    self.chk_collapse_fr.setChecked(True)
    self.chk_collapse_fr.blockSignals(False)
    self.lbl_packs.setText("Паки не выбраны.")
    self.lbl_status.setText("Настройки сброшены.")

# ── Экспорт ──────────────────────────────────────────────────────────────
def _export(self, fmt: str):
    if not self._results:
        return
    if fmt == "json":
        path, _ = _api.QFileDialog.getSaveFileName(
            self, "Сохранить как JSON", "shikimori.json", "JSON (*.json)")
    else:
        path, _ = _api.QFileDialog.getSaveFileName(
            self, "Сохранить как CSV", "shikimori.csv", "CSV (*.csv)")
    if not path:
        return
    rows = [a.as_row() for a in self._results]
    try:
        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                _api.json.dump(rows, f, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = _api.csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    except Exception as e:
        _api.msgbox_critical(self, "Экспорт", f"Не удалось сохранить файл:\n{e}")
        return
    self.lbl_status.setText(f"Сохранено: {_api.os.path.basename(path)} ({len(rows)})")
    if self.main is not None and hasattr(self.main, "log"):
        try:
            self.main.log(f"ShikimoriHYX: экспортировано {len(rows)} → {path}")
        except Exception:
            pass

# ── Очистка (вызывается главным окном при закрытии/выключении вкладки) ────
def cleanup(self):
    if self._task is not None:
        try:
            self._task.stop()
        except Exception:
            pass
        self._task = None
    self._stop_views_task()
    if self._genres_task is not None:
        try:
            self._genres_task.signals.finished.disconnect()
        except Exception:
            pass
        self._genres_task = None
