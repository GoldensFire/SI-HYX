# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab: _load_visible_thumbs. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _load_visible_thumbs(self):
    """Запускает загрузку обложек ТОЛЬКО для строк, попадающих в видимую
        область списка. Уже загруженные (кеш) и уже запрошенные (pending) —
        пропускаем. Вызывается при наполнении списка и при прокрутке."""
    n = self.list.count()
    if not n:
        return
    vp = self.list.viewport().rect()
    for i in range(n):
        it = self.list.item(i)
        if it is None:
            continue
        r = self.list.visualItemRect(it)
        if r.bottom() < vp.top() or r.top() > vp.bottom():
            continue
        aid = it.data(_api.Qt.ItemDataRole.UserRole + 1)
        if aid in self._thumb_cache or aid in self._thumb_pending:
            continue
        # Сперва — дисковый кеш (мгновенно, без сети): постеры за день не
        # меняются, повторно качать их незачем.
        pm = _api._load_cover_from_disk(aid)
        if pm is not None:
            icon = _api.QIcon(pm)
            self._thumb_cache[aid] = icon
            it.setIcon(icon)
            continue
        a = self._anime_by_id.get(aid)
        if a is None or not a.image_url:
            continue
        self._thumb_pending.add(aid)
        task = _api._ThumbTask(aid, a.image_url)
        task.signals.done.connect(self._on_thumb_loaded)
        self._pool.start(task)

def _on_thumb_loaded(self, anime_id: int, data: bytes):
    self._thumb_pending.discard(anime_id)
    pm = _api.QPixmap()
    if not pm.loadFromData(data):
        return
    pm = pm.scaled(_api._THUMB_W, _api._THUMB_H, _api.Qt.AspectRatioMode.KeepAspectRatio,
                   _api.Qt.TransformationMode.SmoothTransformation)
    icon = _api.QIcon(pm)
    self._thumb_cache[anime_id] = icon
    _api._save_cover_to_disk(anime_id, pm)
    # Находим строку с этим id и ставим иконку (список мог быть перестроен).
    for i in range(self.list.count()):
        it = self.list.item(i)
        if it.data(_api.Qt.ItemDataRole.UserRole + 1) == anime_id:
            it.setIcon(icon)
            break

def _on_selection_changed(self):
    has_sel = self.list.currentItem() is not None
    self.btn_open.setEnabled(has_sel and bool(self._results))

def _open_selected_in_browser(self, *_):
    it = self.list.currentItem()
    if it is None:
        return
    url = it.data(_api.Qt.ItemDataRole.UserRole)
    if url:
        try:
            _api.webbrowser.open(url)
        except Exception:
            pass

# ── Исключение паков SiQuesterHYX ──────────────────────────────────────────
def _siq_datasets(self):
    """Список загруженных в SiQuesterHYX датасетов или [] если вкладки нет."""
    tsq = getattr(self.main, "tab_siquester", None) if self.main else None
    inner = getattr(tsq, "inner", None) if tsq else None
    return list(getattr(inner, "datasets", []) or []) if inner else []

@staticmethod
def _pack_answers(ds) -> set:
    """Собирает нормализованные ответы из одного .siq-пака."""
    out = set()
    w = ds.get("widget")
    siq = getattr(w, "_siq", None) if w else None
    rounds = getattr(siq, "rounds", []) if siq else []
    for rd in rounds:
        for th in rd.get("themes", []):
            for q in th.get("questions", []):
                answers = list(q.get("answers", []) or [])
                for it in q.get("items", []):
                    if (it.get("param") == "answer"
                            and it.get("type") == "text"
                            and not it.get("is_ref")):
                        answers.append(it.get("text", ""))
                for ans in answers:
                    # Один ответ нередко содержит несколько вариантов тайтла
                    # через « / » или « | » («Охотник x Охотник / Hunter x
                    # Hunter (1999)») — разбиваем, чтобы в исключения попал и
                    # русский, и ромадзи-вариант по отдельности. Делим только
                    # по разделителю С ПРОБЕЛАМИ, чтобы не рвать «Fate/stay».
                    for part in _api.re.split(r"\s+[/|]\s+", ans or ""):
                        n = _api._norm_title(part)
                        if n:
                            out.add(n)
    return out

def _choose_packs(self):
    datasets = self._siq_datasets()
    if not datasets:
        _api.msgbox_information(
            self, "Паки SiQuesterHYX",
            "Нет загруженных паков.\n\nВключите вкладку «SiQuesterHYX» в "
            "Настройках и откройте в ней .siq-пак(и), затем повторите.")
        return
    dlg = _api.QDialog(self)
    dlg.setWindowTitle("Выбор паков для исключения")
    dlg.setMinimumWidth(380)
    lay = _api.QVBoxLayout(dlg)
    lay.addWidget(_api.QLabel("Тайтлы из ответов отмеченных паков будут скрыты "
                         "из выдачи поиска:"))
    checks = []
    for idx, ds in enumerate(datasets):
        name = ds.get("pkg_name") or f"Пак {idx + 1}"
        cb = _api.QCheckBox(name)
        cb.setChecked(name in self._excluded_packs)
        lay.addWidget(cb)
        checks.append((cb, ds, name))
    line = _api.QFrame(); line.setFrameShape(_api.QFrame.Shape.HLine)
    line.setStyleSheet(f"color:{_api.C['border']};")
    lay.addWidget(line)
    bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                          | _api.QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec() != _api.QDialog.DialogCode.Accepted:
        return
    excluded = set()
    chosen_names = []
    for cb, ds, name in checks:
        if cb.isChecked():
            chosen_names.append(name)
            excluded |= self._pack_answers(ds)
    self._excluded = excluded
    self._rebuild_excluded_bases()
    self._excluded_packs = chosen_names
    if chosen_names:
        self.lbl_packs.setText(
            f"Выбрано паков: {len(chosen_names)} "
            f"({len(excluded)} ответов).\n" + ", ".join(chosen_names))
    else:
        self.lbl_packs.setText("Паки не выбраны.")
    # Переприменяем к уже найденному (без нового запроса).
    if self._raw_results:
        self._apply_exclusions()

# ── Жанры (асинхронно) ───────────────────────────────────────────────────
def _load_genres_async(self, content_type: str):
    if self._genres_task is not None:
        return
    task = _api._GenresTask(content_type)
    task.signals.finished.connect(self._on_genres_loaded)
    task.signals.failed.connect(lambda *_: setattr(self, "_genres_task", None))
    self._genres_task = task
    self._pool.start(task)

def _on_genres_loaded(self, content_type: str, genres: list):
    self._genres_task = None
    items = []
    for g in genres:
        gid = g.get("id")
        if gid is None:
            continue
        label = g.get("russian") or g.get("name") or str(gid)
        items.append((int(gid), label, _api.genre_group(g)))
    items.sort(key=lambda x: x[1].lower())
    self._genres_cache[content_type] = items
    # Применяем отложенный (восстановленный из настроек) выбор — только те id,
    # что реально есть в списке этого типа контента.
    if content_type == self._content_type():
        valid = {gid for gid, _, _ in items}
        if self._pending_genres:
            self._sel_genres = [g for g in self._pending_genres if g in valid]
            self._pending_genres = []
        if self._pending_excl:
            self._excl_genres = [g for g in self._pending_excl if g in valid]
            self._pending_excl = []
        self._update_genres_btn()

def _open_genre_picker(self):
    ct = self._content_type()
    items = self._genres_cache.get(ct)
    if not items:
        # Список ещё не пришёл — подгрузим и попросим повторить чуть позже.
        self._load_genres_async(ct)
        _api.msgbox_information(
            self, "Жанры и темы",
            "Список жанров ещё загружается — повторите через секунду.")
        return
    dlg = _api._GenrePickerDialog(items, self._sel_genres, self._excl_genres, self)
    if dlg.exec():
        self._sel_genres = dlg.selected_ids()
        self._excl_genres = dlg.excluded_ids()
        self._update_genres_btn()

def _update_genres_btn(self):
    """Подпись кнопки выбора жанров/тем: «Любые», сами названия (если выбран/
        исключён 1–2) или «Выбрано: N, исключено: M»."""
    inc = len(self._sel_genres)
    exc = len(self._excl_genres)
    if inc == 0 and exc == 0:
        self.btn_genres.setText("Любые")
        return
    lookup = {gid: label
              for gid, label, _ in self._genres_cache.get(
                  self._content_type(), [])}
    if inc + exc <= 2:
        parts = [lookup.get(g, str(g)) for g in self._sel_genres]
        parts += [f"−{lookup.get(g, str(g))}" for g in self._excl_genres]
        self.btn_genres.setText(", ".join(parts))
    else:
        bits = []
        if inc:
            bits.append(f"выбрано: {inc}")
        if exc:
            bits.append(f"искл.: {exc}")
        self.btn_genres.setText(", ".join(bits))

# ── Сохранение / восстановление / сброс настроек ───────────────────────────
def get_settings(self) -> dict:
    """Текущие настройки вкладки (для сохранения в settings.json)."""
    if not _api._HAS_API:
        return dict(self._initial_settings)
    return {
        "content_type": self._content_type(),
        "query": self.ed_query.text().strip(),
        "score_min": self.sp_score_min.value(),
        "score_max": self.sp_score_max.value(),
        "order": self.cb_order.currentData() or "ranked",
        "views_max": int(self.sp_views_max.value()),
        "stop_limit": int(self.sp_stop_limit.value()),
        "kind": self.cb_kind.currentData() or "",
        "status": self.cb_status.currentData() or "",
        "genres": list(self._sel_genres),
        "excl_genres": list(self._excl_genres),
        "year_from": self.sp_year_from.value(),
        "year_to": self.sp_year_to.value(),
        "ep_min": self.sp_ep_min.value(),
        "ep_max": self.sp_ep_max.value(),
        "excluded_packs": list(self._excluded_packs),
        "collapse_franchise": bool(self._collapse_franchise),
    }
