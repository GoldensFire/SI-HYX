# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab: _update_views_max_enabled. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _update_views_max_enabled(self, *_):
    """Поле «Проверять просмотров у …» активно только при сортировке
        «По просмотрам» — для прочих сортировок оно ни на что не влияет."""
    active = self._views_sort_active()
    sp = getattr(self, "sp_views_max", None)
    lbl = getattr(self, "lbl_views_max", None)
    if sp is not None:
        sp.setEnabled(active)
    if lbl is not None:
        lbl.setEnabled(active)

def _views_sort_limit(self) -> int:
    """Сколько верхних тайтлов проверять на просмотры (из поля настроек)."""
    try:
        return max(1, int(self.sp_views_max.value()))
    except Exception:
        return _api._VIEWS_SORT_MAX

def _display_results(self):
    """Заполняет список результатами. При сортировке по просмотрам сначала
        упорядочивает их по кешу просмотров (неизвестные — в конец)."""
    if self._views_sort_active():
        self._results.sort(key=self._sort_key, reverse=True)
    self._fill_list(self._results)

def _stop_views_task(self):
    if self._views_task is not None:
        try:
            self._views_task.stop()
        except Exception:
            pass
        # Отписываемся от сигналов: задача в пуле ещё доживёт цикл, но её
        # поздние сигналы не должны трогать UI после «Очистить»/нового поиска.
        for sig in (self._views_task.signals.item,
                    self._views_task.signals.progress,
                    self._views_task.signals.finished):
            try:
                sig.disconnect()
            except Exception:
                pass
        self._views_task = None

def _begin_views_sort(self):
    """Дозагружает просмотры для результатов, у которых их ещё нет, и затем
        пересортировывает список. Уже известные берём из кеша (не перезапрашиваем)."""
    self._stop_views_task()
    limit = self._views_sort_limit()
    ids = [a.id for a in self._results[:limit]
           if a.id not in self._views_cache]
    if not ids:
        self._resort_by_views(done=True)
        return
    self.lbl_status.setText(
        f"Сортировка {self._sort_phrase()}… 0/{len(ids)} (можно «Стоп»)")
    # «Стоп» активен и во время сортировки — её тоже можно прервать.
    self.btn_cancel.setEnabled(True)
    self.btn_search.setEnabled(False)
    self.btn_search_cache.setEnabled(False)
    task = _api._ViewsTask(ids)
    task.signals.item.connect(self._on_views_item)
    task.signals.progress.connect(self._on_views_progress)
    task.signals.finished.connect(self._on_views_finished)
    self._views_task = task
    self._pool.start(task)

def _on_views_item(self, anime_id: int, views: int, base: float, comps=None):
    self._views_cache[anime_id] = views
    self._index_base_cache[anime_id] = base
    self._index_breakdown_cache[anime_id] = list(comps or [])
    # Свежая запись — фиксируем время и планируем отложенную запись на диск.
    self._index_cache_ts[anime_id] = _api.time.time()
    self._schedule_index_cache_save()
    # Подсказка с разбивкой индекса показывается делегатом по наведению на
    # значок индекса (см. _ViewsBadgeDelegate.helpEvent) — здесь только кешируем.
    # Расставляем тайтлы ПАРАЛЛЕЛЬНО, по мере поступления просмотров: как только
    # узнали число у тайтла, сразу ставим его на своё место (не ждём конца
    # дозагрузки). Порядок строк и номера мест обновляются вживую.
    if self._views_sort_active():
        self._resort_by_views(done=False)

def _index_tooltip_for(self, aid) -> str:
    """Текст подсказки к «индексу популярности». Показываем ПОЛНУЮ цепочку,
        чтобы было видно, что свежесть/оценка реально применяются:
        база (люди × вес статуса) → множители за дату выхода и оценку → итог."""
    comps = self._index_breakdown_cache.get(aid)
    base = self._index_base_cache.get(aid, 0.0)
    if not comps or base <= 0:
        return ""
    a = self._anime_by_id.get(aid)
    when = (a.air_date or a.year) if a else None
    score = a.score if a else 0.0
    recency, score_factor = _api._index_factors(when, score)
    idx_val = _api._popularity_index(base, when, score)
    if idx_val <= 0:
        return ""
    def _fmt(n):
        return f"{int(round(n)):,}".replace(",", " ")
    lines = [f"Индекс популярности — {_fmt(idx_val)}",
             f"База (люди × вес статуса): {_fmt(base)}"]
    for label, weighted, cnt in comps:
        pct = weighted / base * 100.0
        lines.append(f"  • {label}: {_fmt(weighted)}  "
                     f"({_fmt(cnt)} чел., {pct:.0f}%)")
    lines.append("")
    lines.append("Множители за свежесть и оценку:")
    date_lbl = (a.date_label if a else "") or "дата неизвестна"
    lines.append(f"  • Свежесть выхода ({date_lbl}): "
                 f"×{recency:.2f} ({(recency - 1.0) * 100:+.0f}%)")
    score_lbl = f"{float(score):.2f}" if score else "нет оценки"
    lines.append(f"  • Оценка ({score_lbl}): "
                 f"×{score_factor:.2f} ({(score_factor - 1.0) * 100:+.0f}%)")
    lines.append(f"Итог: {_fmt(base)} × {recency:.2f} × {score_factor:.2f}"
                 f" ≈ {_fmt(idx_val)}")
    lines.append("")
    lines.append("По этому индексу сортирует режим «По индексу популярности».")
    return "\n".join(lines)

def _on_views_progress(self, done: int, total: int):
    if self._views_task is not None:
        self.lbl_status.setText(
            f"Сортировка {self._sort_phrase()}… {done}/{total} (можно «Стоп»)")

def _on_views_finished(self):
    self._views_task = None
    # Сортировка завершилась сама — возвращаем кнопки в обычное состояние.
    self.btn_cancel.setEnabled(False)
    self.btn_search.setEnabled(True)
    self.btn_search_cache.setEnabled(True)
    self._resort_by_views(done=True)
    # Дозагрузка карточек закончилась — сразу сохраняем кеш индекса на диск.
    self._save_index_cache()

# ── Постоянный кеш «индекса популярности» (просмотры/база/разбивка) ───────
def _load_index_cache(self):
    """Подтягивает сохранённые ранее просмотры/базу индекса из файла, чтобы
        не дозапрашивать карточки заново при каждом запуске. Просроченные записи
        (старше _INDEX_CACHE_TTL) пропускаем — просмотры медленно растут."""
    if not _api._INDEX_CACHE_FILE:
        return
    try:
        with open(_api._INDEX_CACHE_FILE, encoding="utf-8") as f:
            data = _api.json.load(f)
    except Exception:
        return
    now = _api.time.time()
    for k, e in (data.get("entries") or {}).items():
        try:
            aid = int(k)
            ts = float(e.get("t", 0))
            if now - ts > _api._INDEX_CACHE_TTL:
                continue
            self._views_cache[aid] = int(e.get("v", -1))
            self._index_base_cache[aid] = float(e.get("b", 0.0))
            comps = e.get("c") or []
            self._index_breakdown_cache[aid] = [
                (str(c[0]), float(c[1]), int(c[2]))
                for c in comps
                if isinstance(c, (list, tuple)) and len(c) >= 3
            ]
            self._index_cache_ts[aid] = ts
        except (TypeError, ValueError):
            continue

def _schedule_index_cache_save(self):
    try:
        self._index_cache_save_timer.start(1500)
    except Exception:
        pass

def _save_index_cache(self):
    """Атомарно (через .tmp + os.replace) пишет кеш индекса на диск. Время
        записи (t) сохраняем исходное — иначе записи никогда не протухали бы."""
    if not _api._INDEX_CACHE_FILE:
        return
    now = _api.time.time()
    entries = {}
    for aid, views in self._views_cache.items():
        comps = self._index_breakdown_cache.get(aid, [])
        entries[str(aid)] = {
            "v": int(views),
            "b": float(self._index_base_cache.get(aid, 0.0)),
            "c": [[lbl, wv, cnt] for (lbl, wv, cnt) in comps],
            "t": self._index_cache_ts.get(aid, now),
        }
        if len(entries) >= _api._INDEX_CACHE_MAX:
            break
    try:
        tmp = _api._INDEX_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _api.json.dump({"version": 1, "entries": entries}, f,
                      ensure_ascii=False)
        _api.os.replace(tmp, _api._INDEX_CACHE_FILE)
    except Exception:
        pass

def _resort_by_views(self, done: bool = False):
    """Пересобирает список в порядке убывания просмотров (по кешу). Сохраняет
        позицию прокрутки и выделение, чтобы живая пересортировка не «дёргала»
        список к началу на каждом новом тайтле."""
    if not self._views_sort_active():
        return
    sb = self.list.verticalScrollBar()
    pos = sb.value()
    cur = self.list.currentItem()
    cur_id = cur.data(_api.Qt.ItemDataRole.UserRole + 1) if cur else None
    self._results.sort(key=self._sort_key, reverse=True)
    self._fill_list(self._results)
    if cur_id is not None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(_api.Qt.ItemDataRole.UserRole + 1) == cur_id:
                self.list.setCurrentItem(it)
                break
    sb.setValue(min(pos, sb.maximum()))
    if done:
        n = len(self._results)
        self.lbl_status.setText(
            f"Найдено: {len(self._raw_results)}, после фильтра: {n} "
            f"({self._sort_phrase()})" if n else "Ничего не найдено.")

def _fill_list(self, results: list):
    self.list.clear()
    self._anime_by_id = {a.id: a for a in results}
    for a in results:
        self._append_anime(a)
    self._load_visible_thumbs()

def _row_text(self, a: '_api.Anime') -> str:
    """Текст строки тайтла: название + краткая инфа. Просмотры (значок «глаз»
        + число) рисует _ViewsBadgeDelegate справа — в текст они не входят."""
    ct = self._content_type()
    unit = "гл." if ct == _api.CONTENT_MANGA else "эп."
    parts = []
    if a.score:
        parts.append(f"★ {a.score:.2f}")
    parts.append(_api.kind_label(ct, a.kind))
    # Дата выхода: по возможности с днём/месяцем или сезоном, иначе год.
    date_lbl = a.date_label or (str(a.year) if a.year else "")
    if date_lbl:
        parts.append(date_lbl)
    if a.episodes:
        parts.append(f"{a.episodes} {unit}")
    sub = "  ·  ".join(parts)
    text = a.title
    if a.name and a.name != a.title:
        text += f"\n{a.name}"
    text += f"\n{sub}"
    return text

def _append_anime(self, a: '_api.Anime'):
    """Добавляет один тайтл в список (обложка + название + краткая инфа).
        Обложку НЕ запрашиваем здесь — она грузится лениво для видимых строк
        (см. _load_visible_thumbs), иначе сотни параллельных запросов → 429."""
    self._anime_by_id[a.id] = a
    it = _api.QListWidgetItem(self._row_text(a))
    it.setData(_api.Qt.ItemDataRole.UserRole, a.url)
    it.setData(_api.Qt.ItemDataRole.UserRole + 1, a.id)
    it.setData(_api.Qt.ItemDataRole.UserRole + 2, a.title)  # для кнопки «копировать» (рус.)
    it.setData(_api.Qt.ItemDataRole.UserRole + 3, a.name)   # для кнопки «копировать» (ориг.)
    it.setIcon(self._thumb_cache.get(a.id) or self._placeholder_icon())
    it.setSizeHint(_api.QSize(0, _api._THUMB_H + 12))
    self.list.addItem(it)

# ── Обложки (ленивая загрузка только видимых, с кешем) ──────────────────────
def _placeholder_icon(self) -> _api.QIcon:
    if self._placeholder is None:
        pm = _api.QPixmap(_api._THUMB_W, _api._THUMB_H)
        pm.fill(_api.QColor(_api.C["surface3"]))
        self._placeholder = _api.QIcon(pm)
    return self._placeholder
