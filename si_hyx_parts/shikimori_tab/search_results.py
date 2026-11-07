# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriHYX: поиск, исключения, сортировка по просмотрам и индексу, заполнение списка."""
import shikimori_tab as _api

from .cache_search import query_tier, query_words


class ShikimoriSearchMixin:
    """ShikimoriHYX: поиск, исключения, сортировка по просмотрам и индексу, заполнение списка."""

    def _rebuild_kind_status(self):
        """Перезаполняет «Тип» и «Статус» под выбранный тип контента."""
        ct = self._content_type()
        self.cb_kind.blockSignals(True); self.cb_status.blockSignals(True)
        self.cb_kind.clear(); self.cb_kind.addItem("Любой", "")
        for k in _api.kinds_for(ct):
            self.cb_kind.addItem(_api.kind_label(ct, k), k)
        self.cb_status.clear(); self.cb_status.addItem("Любой", "")
        for s in _api.statuses_for(ct):
            self.cb_status.addItem(_api.status_label(ct, s), s)
        self.cb_kind.blockSignals(False); self.cb_status.blockSignals(False)

    # ── Поиск ────────────────────────────────────────────────────────────────
    def _collect_filter(self) -> '_api.AnimeFilter':
        smin = self.sp_score_min.value()
        smax = self.sp_score_max.value()
        yf = self.sp_year_from.value()
        yt = self.sp_year_to.value()
        epmin = self.sp_ep_min.value()
        epmax = self.sp_ep_max.value()
        ui_order = self.cb_order.currentData() or _api.ORDER_VIEWS
        # «По просмотрам»/«По индексу» — локальные сортировки: на СЕРВЕРЕ берём
        # популярные (чтобы вверху были известные тайтлы, а не безвестный мусор),
        # а уже их пересортировываем локально (см. _begin_views_sort).
        server_order = ("popularity"
                        if ui_order in (_api.ORDER_VIEWS, _api.ORDER_INDEX) else ui_order)
        return _api.AnimeFilter(
            query=self.ed_query.text().strip(),
            kind=self.cb_kind.currentData() or "",
            status=self.cb_status.currentData() or "",
            order=server_order,
            score_min=(smin if smin > 0 else None),
            score_max=(smax if 0 < smax < 10.0 else None),
            year_from=(yf if yf > 0 else None),
            year_to=(yt if yt > 0 else None),
            episodes_min=(epmin if epmin > 0 else None),
            episodes_max=(epmax if epmax > 0 else None),
            genres=list(self._sel_genres),
            exclude_genres=list(self._excl_genres),
            content_type=self._content_type(),
        )

    def start_search(self, cache_only=None, *, quiet: bool = False):
        if self._task is not None:
            return  # уже идёт поиск
        if cache_only is None:
            # Галочка «По кэшу»: пока она стоит, «Найти» и Enter ищут по базе.
            chk = getattr(self, "chk_cache", None)
            cache_only = bool(chk is not None and chk.isChecked())
        criteria = self._collect_filter()
        err = criteria.validate()
        if err:
            if quiet:
                # Авто-загрузка при открытии вкладки — без модальных окон.
                self.lbl_status.setText(err)
            else:
                _api.msgbox_warning(self, "Проверьте фильтры", err)
            return
        # Новый поиск — чистим список и потоково наполняем его по мере страниц.
        self._cache_only = cache_only
        self._query_words = query_words(criteria.query)
        self._query_tier_memo = {}
        self._quiet_failure = bool(quiet)
        self._stop_views_task()
        self.list.clear()
        self._anime_by_id.clear()
        self._raw_results = []
        self._results = []
        self._page = 0
        self._update_pager()
        self._seen_franchises = set()
        self._set_actions_enabled(False)
        self._set_busy(True)
        if cache_only:
            # По базе генератора — без сети, вся выдача одним сигналом.
            self.lbl_status.setText("Поиск по базе Shikimori генератора… (можно «Стоп»)")
            task = _api._CacheSearchTask(criteria)
            task.signals.finished.connect(self._on_cache_search_finished)
            task.signals.failed.connect(self._on_search_failed)
        else:
            self.lbl_status.setText("Поиск… (нажмите «Стоп», чтобы остановить)")
            task = _api._SearchTask(criteria)
            task.signals.batch.connect(self._on_search_batch)
            task.signals.finished.connect(self._on_search_finished)
            task.signals.failed.connect(self._on_search_failed)
            task.signals.progress.connect(self._on_search_progress)
        self._task = task
        self._pool.start(task)

    def _on_cache_toggled(self, on: bool):
        """Галочка «По кэшу»: включили — сразу показываем список из базы."""
        if not _api._HAS_API:
            return
        if self._task is not None:
            self._stop_search_task()
            self.lbl_status.setText("Остановлено.")
        if not on:
            if not self._results:
                self.lbl_status.setText("Готово к поиску.")
            return
        # Пока галочка стоит, обычный «Найти» тоже идёт по базе (start_search
        # читает её состояние). Здесь же сразу грузим текущие фильтры.
        self.start_search(True)

    def _stop_search_task(self):
        """Останавливает текущий поиск и отписывает его сигналы.

        Нужно перед немедленным запуском другого режима: иначе запоздавшая
        страница сетевого поиска успела бы дописаться в список уже нового,
        кешевого поиска."""
        task = self._task
        self._task = None
        self._quiet_failure = False
        if task is None:
            return
        try:
            task.stop()
        except Exception:
            pass
        for name in ("batch", "finished", "failed", "progress"):
            sig = getattr(task.signals, name, None)
            if sig is not None:
                try:
                    sig.disconnect()
                except Exception:
                    pass
        self._set_busy(False)

    def _schedule_cache_on_open(self):
        """Авто-загрузка при открытии вкладки, если галочка сохранена включённой.

        Если из настроек ждут восстановления жанры, сначала дождёмся их списка:
        иначе первый поиск по базе пойдёт без выбранных жанров."""
        if not self.chk_cache.isChecked():
            return
        if self._pending_genres or self._pending_excl:
            self._cache_wait_genres = True
            return
        _api.QTimer.singleShot(0, self._load_cache_on_open)

    def _load_cache_on_open(self):
        """Вкладка открыта с сохранённой галочкой — сразу список из базы.

        Только когда вкладку видно и главное окно достроило отложенные вкладки:
        поток разбирает базу (~230 МБ) чистым Python и держит GIL, а на старте
        главный поток в это время строил «Аниме-пак» и стоял по 5–9 с. Пока
        вкладку не открывали, поиск ждёт showEvent."""
        self._cache_on_open_pending = True
        if not self.isVisible():
            return
        if getattr(self.main, "_deferred_tabs", None):
            _api.QTimer.singleShot(500, self._load_cache_on_open)
            return
        self._cache_on_open_pending = False
        if (self.chk_cache.isChecked() and self._task is None
                and self._views_task is None):
            self.start_search(quiet=True)

    def _on_genres_ready_for_cache(self):
        """Жанры восстановлены (или не пришли) — можно грузить кеш с фильтрами."""
        if getattr(self, "_cache_wait_genres", False):
            self._cache_wait_genres = False
            _api.QTimer.singleShot(0, self._load_cache_on_open)

    def cancel_search(self):
        """«Стоп» работает на ОБОИХ этапах: и во время поиска, и во время
        дозагрузки просмотров (сортировки). Накопленное всегда оставляем."""
        # 1) Идёт дозагрузка просмотров (сортировка) — прерываем именно её и
        #    оставляем уже расставленный порядок, БЕЗ перезапуска.
        if self._views_task is not None:
            self._stop_views_task()
            self._set_busy(False)
            self._resort_by_views(done=False)
            n = len(self._results)
            self._set_actions_enabled(n > 0)
            self.lbl_status.setText(
                f"Сортировка остановлена. Найдено: {len(self._raw_results)}, "
                f"после фильтра: {n}")
            return
        # 2) Идёт поиск — останавливаем его.
        if self._task is not None:
            self._stop_search_task()
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        # Сортировка по просмотрам — досортируем то, что успели набрать (её тоже
        # можно прервать «Стопом» — см. ветку выше). При «поиске по кэшу»
        # берётся только то, что уже лежит в базе генератора.
        if n and self._views_sort_active():
            self.lbl_status.setText(f"Остановлено, сортирую {self._sort_phrase()}…")
            self._begin_views_sort()
        else:
            if n:
                self._display_results()
            self.lbl_status.setText(
                f"Остановлено. Найдено: {len(self._raw_results)}, "
                f"после фильтра: {n}" if n else "Остановлено.")

    def clear_results(self):
        """Очищает список результатов (кнопка «Очистить»). Идущий поиск/дозагрузку
        просмотров останавливает; кеш просмотров сохраняем — пригодится повторно."""
        if self._task is not None:
            self._stop_search_task()
        self._stop_views_task()
        self._set_busy(False)
        self.list.clear()
        self._anime_by_id.clear()
        self._raw_results = []
        self._results = []
        self._page = 0
        self._update_pager()
        self._set_actions_enabled(False)
        self.lbl_status.setText("Список очищен.")

    def _on_search_progress(self, page: int, matched: int):
        if self._task is not None:
            self.lbl_status.setText(
                f"Поиск… страница {page}: найдено {len(self._raw_results)}, "
                f"после фильтра {len(self._results)} (можно «Стоп»)")

    def _stop_limit_value(self) -> int:
        """0 — без лимита."""
        try:
            return int(self.sp_stop_limit.value())
        except Exception:
            return 0

    def _on_search_batch(self, items: list):
        """Потоково добавляет новые тайтлы страницы (с учётом исключения паков)."""
        if self._task is None:
            return
        self._learn_excluded_franchises(items)
        page_end = (self._page + 1) * _api._PAGE_SIZE
        for a in items:
            self._raw_results.append(a)
            if self._is_excluded(a):
                continue
            if self._collapse_franchise and self._franchise_seen(a):
                continue
            self._results.append(a)
            if len(self._results) <= page_end:
                self._append_anime(a)
            else:
                self._anime_by_id[a.id] = a
        self._update_pager()
        self._load_visible_thumbs()
        self._set_actions_enabled(bool(self._results))
        # Автостоп: набрали достаточно тайтлов ПОСЛЕ фильтрации — дальше искать
        # незачем (по просьбе пользователя, по умолчанию 500).
        limit = self._stop_limit_value()
        if limit and len(self._results) >= limit and self._task is not None:
            self._task.stop()
            self._task = None
            self._set_busy(False)
            n = len(self._results)
            self._set_actions_enabled(n > 0)
            if n and self._views_sort_active():
                self.lbl_status.setText(
                    f"Лимит {limit} достигнут, сортирую {self._sort_phrase()}…")
                self._begin_views_sort()
            else:
                self._display_results()   # совпавшие главным названием — вверх
                self.lbl_status.setText(
                    f"Лимит {limit} достигнут. Найдено: {len(self._raw_results)}, "
                    f"после фильтра: {n}")

    def _on_search_finished(self, results: list):
        self._task = None
        self._quiet_failure = False
        self._set_busy(False)
        # Полный результат — авторитетный; пересобираем список начисто (на случай
        # дублей/исключений), даём финальный статус.
        self._raw_results = results
        self._apply_exclusions()
        if self._results and self._views_sort_active():
            # Просмотры и индекс — из базы генератора; «По кэшу» не ходит в сеть
            # за недостающими карточками (см. _begin_views_sort).
            self._begin_views_sort()

    def _on_cache_search_finished(self, results: list, info: dict):
        """«По кэшу»: вся выдача из базы генератора сразу, просмотры — из её
        карточек. Индекс досчитывается следом (_begin_views_sort)."""
        self._task = None
        self._quiet_failure = False
        self._set_busy(False)
        for aid, (views, franchise) in info.items():
            self._views_cache[aid] = views
            if franchise:
                self._franchise_of[aid] = franchise
        self._raw_results = results
        self._apply_exclusions()
        if self._results and self._views_sort_active():
            self._begin_views_sort()

    def _on_search_failed(self, message: str):
        self._task = None
        self._set_busy(False)
        quiet = bool(getattr(self, "_quiet_failure", False))
        self._quiet_failure = False
        self.lbl_status.setText(message if quiet else "Ошибка запроса.")
        if quiet:
            # Авто-загрузка при открытии вкладки не должна лезть с модальным
            # окном: человек ещё ничего не нажимал. Статус всё равно скажет,
            # что база пуста или недоступна.
            return
        _api.msgbox_critical(self, "Shikimori", f"Не удалось выполнить поиск:\n{message}")

    def _set_busy(self, busy: bool):
        self.btn_search.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _set_actions_enabled(self, on: bool):
        self.btn_open.setEnabled(on)
        self.btn_export_json.setEnabled(on)
        self.btn_export_csv.setEnabled(on)

    # ── Применение исключения паков и заполнение списка ────────────────────────
    def _term_in_question_text(self, term: str) -> bool:
        """Встречается ли название в тексте вопроса отдельным словом/фразой.

        Простое `in` дало бы ложные срабатывания на коротких названиях внутри
        других слов, поэтому проверяем границы слова (`\\w`). Результат кешируем:
        в выдаче тысячи тайтлов, а названий у них заметно меньше.

        Регулярку строим только для названий, которые есть в тексте простой
        подстрокой: re.search компилирует новый шаблон на каждое название, и
        на 20 тыс. тайтлах «По кэшу» это вешало вкладку на десятки секунд."""
        cache = self._question_term_cache
        if term in cache:
            return cache[term]
        found = False
        haystack = self._excluded_question_haystack
        if term and haystack and term in haystack:
            found = bool(_api.re.search(
                r"(?<!\w)" + _api.re.escape(term) + r"(?!\w)", haystack))
        cache[term] = found
        return found

    def _question_mentions(self, nt: str, nn: str) -> bool:
        """Название тайтла (или его корень) упомянуто в тексте вопроса."""
        if not self._excluded_question_haystack:
            return False
        terms = []
        for name in (nt, nn):
            if not name:
                continue
            for term in (name, _api._base_title(name),
                         _api._franchise_key(name)):
                if term and term not in terms:
                    terms.append(term)
        return any(self._term_in_question_text(term) for term in terms)

    def _name_excluded(self, a: '_api.Anime') -> bool:
        """Совпало ли НАЗВАНИЕ тайтла с ответом/текстом вопроса из пака.

        Ответ запоминается по id до смены паков (_rebuild_excluded_bases):
        за один проход его спрашивают и _learn_excluded_franchises, и
        _is_excluded, а потоковая выдача — ещё и на каждой странице."""
        if not self._excluded and not self._excluded_question_haystack:
            return False
        memo = self._name_excluded_memo
        hit = memo.get(a.id)
        if hit is None:
            hit = memo[a.id] = self._match_excluded_name(a)
        return hit

    def _match_excluded_name(self, a: '_api.Anime') -> bool:
        nt, nn = _api._norm_title(a.title), _api._norm_title(a.name)
        if nt in self._excluded or nn in self._excluded:
            return True
        # Сезонные варианты: пак с «Ванпанчмен» прячет и «Ванпанчмен 3» (и наоборот)
        # — сравниваем «базовые» формы без хвостового номера/«сезон N».
        if self._excluded_bases:
            if _api._base_title(nt) in self._excluded_bases:
                return True
            if nn and _api._base_title(nn) in self._excluded_bases:
                return True
        # Название могло быть только в ТЕКСТЕ вопроса (ответ — имя героя,
        # предмет или разгаданное слово), поэтому проверяем и его.
        return self._question_mentions(nt, nn)

    def _is_excluded(self, a: '_api.Anime') -> bool:
        if (not self._excluded and not self._excluded_question_haystack
                and not self._excluded_franchises):
            return False
        if self._name_excluded(a):
            return True
        # Франшиза целиком: пак с «Наруто» прячет «Наруто: Ураганные хроники».
        if self._collapse_franchise and self._excluded_franchises:
            keys = self._franchise_keys(a)
            for k in keys:
                if k in self._excluded_franchises:
                    return True
            # Длинные тайтлы одной франшизы, отличающиеся лишь последним словом
            # («…мечту девочки зайки» vs «…девочки-мечтательницы»).
            for k in keys:
                if _api._matches_franchise_prefix(k, self._excluded_prefixes):
                    return True
        return False

    def _learn_excluded_franchises(self, raw):
        """Закрывает франшизы исключённых паками тайтлов, даже если у пака нет
        манифеста.

        «Атака титанов» из пака и «Атака! Титаны средней школы» из выдачи —
        один franchise у Shikimori, хотя названия разные. В «По кэшу» карточки
        уже приносят franchise (cache_search); в сетевом поиске — после
        дозагрузки просмотров."""
        if ((not self._excluded and not self._excluded_question_haystack)
                or not self._franchise_of):
            return
        for a in raw:
            franchise = self._franchise_of.get(a.id)
            if not franchise or "#" + franchise in self._excluded_franchises:
                continue
            if self._name_excluded(a):
                self._excluded_shiki_franchises.add(franchise)
                self._excluded_franchises.add("#" + franchise)

    def _franchise_keys(self, a) -> set:
        """Ключи франшизы тайтла: по русскому названию, по ромадзи и, если тайтл
        есть в базе генератора, — ключ франшизы самого Shikimori. Последний
        ловит части, у которых название другое («Атака! Титаны средней школы»
        у «Атаки титанов»)."""
        keys = self._fkeys.get(a.id)
        if keys is None:
            keys = frozenset(k for k in (_api._franchise_key(a.title),
                                         _api._franchise_key(a.name)) if k)
            self._fkeys[a.id] = keys
        franchise = self._franchise_of.get(a.id)
        return keys | {"#" + franchise} if franchise else set(keys)

    def _franchise_seen(self, a) -> bool:
        """True (и запоминает), если франшиза этого тайтла уже показана в выдаче —
        для схлопывания сезонов/частей по ходу потоковой выдачи."""
        keys = self._franchise_keys(a)
        if not keys:
            return False
        if keys & self._seen_franchises:
            return True
        self._seen_franchises |= keys
        return False

    def _filtered(self):
        """(оставшиеся тайтлы в порядке выдачи, сколько скрыто): исключение
        паков и схлопывание франшиз. От франшизы остаётся самый просматриваемый
        тайтл, а не первый попавшийся в выдаче — иначе вместо «Атаки титанов»
        мог остаться её спин-офф. Тайтлы без известных просмотров уступают
        тем, у кого они есть, а между собой идут в порядке выдачи."""
        raw = self._raw_results
        self._learn_excluded_franchises(raw)
        kept = [a for a in raw if not self._is_excluded(a)]
        hidden = len(raw) - len(kept)
        seen = set()
        if self._collapse_franchise:
            views = self._views_cache
            order = sorted(kept, key=lambda a: (views.get(a.id, -1) < 0,
                                                -views.get(a.id, -1)))
            keep_ids = set()
            for a in order:
                keys = self._franchise_keys(a)
                if keys & seen:
                    continue
                seen |= keys
                keep_ids.add(a.id)
            hidden += len(kept) - len(keep_ids)
            kept = [a for a in kept if a.id in keep_ids]
        self._seen_franchises = seen
        return kept, hidden

    def _on_collapse_toggled(self, on: bool):
        self._collapse_franchise = bool(on)
        # Переприменяем к уже найденному (без нового запроса к Shikimori).
        if self._raw_results:
            self._apply_exclusions()

    def _rebuild_excluded_bases(self):
        """Пересобирает «базовые» формы и «ключи франшиз» исключённых названий."""
        self._excluded_bases = {b for b in (_api._base_title(x) for x in self._excluded) if b}
        name_keys = {f for f in (_api._franchise_key(x) for x in self._excluded) if f}
        # Ключ самого Shikimori живёт в отдельном пространстве имён («#konosuba»,
        # «#shingeki_no_kyojin») и с названием «атака титанов» не совпадает.
        # Он приходит из манифеста пака и ловит части с другим названием.
        self._excluded_franchises = name_keys | {
            "#" + f for f in self._excluded_shiki_franchises if f}
        self._excluded_prefixes = _api._franchise_prefix_index(name_keys)
        self._excluded_question_haystack = "\n".join(
            self._excluded_question_texts)
        self._question_term_cache = {}
        self._name_excluded_memo = {}

    def _apply_exclusions(self):
        """Фильтрует «сырые» результаты по выбранным пакам и схлопывает франшизы."""
        raw = self._raw_results
        self._results, excluded_n = self._filtered()
        self._display_results()
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        if n:
            # Показываем и сколько НАШЛИ всего, и сколько осталось после фильтрации.
            msg = f"Найдено: {len(raw)}, после фильтра: {n}"
            if excluded_n:
                msg += f" (скрыто: {excluded_n})"
            self.lbl_status.setText(msg)
        elif raw and excluded_n:
            self.lbl_status.setText("Всё найденное уже есть в выбранных паках.")
        else:
            self.lbl_status.setText("Ничего не найдено под заданные фильтры.")

    # ── Сортировка по просмотрам (локально, с дозагрузкой карточек) ────────────
    def _views_sort_active(self) -> bool:
        """True для локальных сортировок, которым нужны числа просмотров: и «по
        просмотрам», и «по индексу популярности» (обе тянут карточки тайтлов)."""
        return self.cb_order.currentData() in (_api.ORDER_VIEWS, _api.ORDER_INDEX)

    def _index_sort_active(self) -> bool:
        return self.cb_order.currentData() == _api.ORDER_INDEX

    def _sort_key(self, a) -> float:
        """Ключ локальной сортировки. Неизвестные просмотры (-1) — в конец.
        Для «индекса» взвешиваем просмотры на свежесть выхода тайтла."""
        views = self._views_cache.get(a.id, -1)
        if views < 0:
            return -1.0
        if self._index_sort_active():
            return float(self._index_cache.get(a.id, 0.0))
        return float(views)

    def _sort_phrase(self) -> str:
        return "по индексу" if self._index_sort_active() else "по просмотрам"

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
        self._order_by_query()
        self._fill_list(self._results)

    def _query_tier(self, a) -> int:
        """Ступень совпадения запроса с главным названием (см. query_tier)."""
        memo = self._query_tier_memo
        tier = memo.get(a.id)
        if tier is None:
            tier = memo[a.id] = query_tier(self._query_words, (a.russian, a.name))
        return tier

    def _order_by_query(self):
        """Тайтлы, у которых запрос есть в главном названии, — первыми; внутри
        ступени сохраняется выбранная сортировка (sort устойчив)."""
        if getattr(self, "_query_words", ()):
            self._results.sort(key=self._query_tier)

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
        # Что уже лежит в базе генератора, считается для всех найденных — и для
        # скрытых схлопыванием частей: по их просмотрам и ключу франшизы
        # выбирается, какая часть останется. По сети дозапрашиваются только
        # верхние limit (и не в режиме «По кэшу»).
        if self._cache_only and not self._index_sort_active():
            # «По кэшу» просмотры уже есть у всех; индекс всей базы считается
            # секундами — огонёк нужен лишь строкам открытой страницы.
            off = self._page * _api._PAGE_SIZE
            pool = self._results[off:off + _api._PAGE_SIZE]
        else:
            pool = self._raw_results
        ids = [a.id for a in pool if a.id not in self._index_cache]
        fetch_ids = ([] if self._cache_only else
                     [a.id for a in self._results[:limit] if a.id not in self._index_cache])
        if not ids:
            self._resort_by_views(done=True)
            return
        self.lbl_status.setText(
            f"Сортировка {self._sort_phrase()}: читаю базу Shikimori генератора… "
            "(можно «Стоп»)")
        # «Стоп» активен и во время сортировки — её тоже можно прервать.
        self.btn_cancel.setEnabled(True)
        self.btn_search.setEnabled(False)
        task = _api._ViewsTask(ids, self._content_type(), fetch_ids=fetch_ids,
                               network=not self._cache_only)
        task.signals.item.connect(self._on_views_item)
        task.signals.progress.connect(self._on_views_progress)
        task.signals.finished.connect(self._on_views_finished)
        self._views_task = task
        self._pool.start(task)

    def _on_views_item(self, anime_id: int, views: int, index: float, row=None):
        self._views_cache[anime_id] = views
        self._index_cache[anime_id] = index
        if row is not None:
            self._index_rows[anime_id] = row
            franchise = str((row.get("card") or {}).get("franchise") or "")
            if franchise:
                self._franchise_of[anime_id] = franchise
        # Подсказка с разбивкой индекса показывается делегатом по наведению на
        # значок индекса (см. _ViewsBadgeDelegate.helpEvent) — здесь только кешируем.
        # Расставляем тайтлы ПАРАЛЛЕЛЬНО, по мере поступления просмотров: как только
        # узнали число у тайтла, сразу ставим его на своё место (не ждём конца
        # дозагрузки). Порядок строк и номера мест обновляются вживую.
        # Из базы карточки приходят пачкой — пересобираем список не на каждую.
        # Пауза между пересборками — не меньше утроенной цены последней: на
        # 20 тыс. тайтлах «По кэшу» пересборка идёт десятые доли секунды, и
        # с фиксированными 150 мс окно было бы занято ею почти всё время.
        if self._views_sort_active() and not getattr(self, "_views_resort_pending", False):
            self._views_resort_pending = True
            cost = getattr(self, "_views_resort_cost", 0.0)
            _api.QTimer.singleShot(max(150, int(cost * 3000)), self._flush_views_resort)

    def _flush_views_resort(self):
        self._views_resort_pending = False
        if self._views_sort_active():
            started = _api.time.perf_counter()
            self._resort_by_views(done=False)
            self._views_resort_cost = _api.time.perf_counter() - started

    def _index_tooltip_for(self, aid) -> str:
        """Подсказка к «индексу популярности» — формула генератора аниме-пака."""
        from .pack_index import tooltip
        return tooltip(self._index_rows.get(aid))

    def _on_views_progress(self, done: int, total: int):
        if self._views_task is not None:
            self.lbl_status.setText(
                f"Сортировка {self._sort_phrase()}… {done}/{total} (можно «Стоп»)")

    def _on_views_finished(self):
        self._views_task = None
        # Сортировка завершилась сама — возвращаем кнопки в обычное состояние.
        self.btn_cancel.setEnabled(False)
        self.btn_search.setEnabled(True)
        self._resort_by_views(done=True)

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
        # Узнали просмотры и франшизы — от франшизы остаётся самая популярная часть.
        self._results = self._filtered()[0]
        self._results.sort(key=self._sort_key, reverse=True)
        self._order_by_query()
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
            unknown = sum(1 for a in self._results
                          if self._views_cache.get(a.id, -1) < 0)
            tail = f", нет в базе: {unknown}" if unknown else ""
            self.lbl_status.setText(
                f"Найдено: {len(self._raw_results)}, после фильтра: {n} "
                f"({self._sort_phrase()}{tail})" if n else "Ничего не найдено.")

    def _fill_list(self, results: list):
        """Показывает открытую страницу выдачи (_PAGE_SIZE строк)."""
        self.list.clear()
        self._anime_by_id = {a.id: a for a in results}
        pages = max(1, -(-len(results) // _api._PAGE_SIZE))
        self._page = max(0, min(self._page, pages - 1))
        off = self._page * _api._PAGE_SIZE
        for a in results[off:off + _api._PAGE_SIZE]:
            self._append_anime(a)
        self._update_pager()
        self._load_visible_thumbs()

    def _update_pager(self):
        """Кнопки страниц и «Стр. N из M» — только когда страниц больше одной."""
        pages = max(1, -(-len(self._results) // _api._PAGE_SIZE))
        multi = pages > 1
        for w in (self.btn_page_prev, self.lbl_page, self.btn_page_next):
            w.setVisible(multi)
        if not multi:
            return
        self.lbl_page.setText(f"Стр. {self._page + 1} из {pages}")
        self.btn_page_prev.setEnabled(self._page > 0)
        self.btn_page_next.setEnabled(self._page < pages - 1)

    def _go_page(self, delta: int):
        pages = max(1, -(-len(self._results) // _api._PAGE_SIZE))
        page = max(0, min(self._page + delta, pages - 1))
        if page == self._page:
            return
        self._page = page
        self._fill_list(self._results)
        self.list.scrollToTop()
        # «По кэшу» огонёк индекса считается постранично (см. _begin_views_sort).
        if (self._cache_only and self._views_sort_active() and self._task is None
                and self._views_task is None):
            self._begin_views_sort()

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
