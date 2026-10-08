# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Генератор: исключения, списки пользователей, каталог Shikimori и потоки кандидатов."""
from __future__ import annotations
import animepack as _api
from dataclasses import replace
from si_hyx_parts.animepack.catalog_pages import iter_catalog_pages


def _franchise_marks(anime: dict, adapted: _api.Optional[dict] = None) -> tuple:
    """Ключи, по которым тайтл считается «той же серией», что уже в паке.

        Это франшиза Shikimori и КОРЕНЬ названия — вторая линия обороны: у
        свежих тайтлов franchise иногда не проставлен, и тогда «Доктор Стоун:
        Научное будущее. Часть 3» проскакивал мимо проверки.

        У КНИГИ сюда добавляются ещё и ключи её аниме-экранизации: у манги
        поле franchise на Shikimori пустует сплошь и рядом, а у экранизации
        оно есть. Без этого «Покемон XY: Хупа и столкновение веков» (манга) и
        «Покемон: Хроники приключений» (аниме) спокойно попадали в один пак
        (просьба пользователя)."""
    out: list[str] = []
    for card, own in ((anime, True), (adapted or {}, False)):
        if not card:
            continue
        key = (_api.franchise_key(card) if own or card.get("franchise")
               else "")
        root = _api.title_root(card.get("russian") or card.get("name"))
        for mark in (key, root):
            if mark and mark not in out:
                out.append(mark)
    return tuple(out)


class GeneratorCatalogMixin:
    """Генератор: исключения, списки пользователей, каталог Shikimori и потоки кандидатов."""

    def load_exclusions(self) -> None:
        """Собирает франшизы из чужих паков (настройка «Не повторять из этих
        .siq»). Непрочитанный файл — не ошибка: о нём просто пишем в лог."""
        self._excluded_roots = set()
        self._excluded_franchises = set()
        self._excluded_studios = set()
        self._exact_keys = set()
        from .test_packs import is_test_pack
        skip_tests = bool(getattr(self.s, "ignore_test_packs", False))
        if getattr(self.s, "exclude_exact_siq", None):
            from .exact_repeat import read_exact_keys
            from .exact_key_cache import read_all
            # Неизменившиеся архивы берутся из кэша отпечатков (exact_key_cache).
            read = read_all(self.s.exclude_exact_siq, read_exact_keys,
                            skip=lambda path: skip_tests and is_test_pack(path),
                            stopped=self.stopped)
            if self.stopped():
                return
            for path, found in read.items():
                self._exact_keys.update(found)
                if not found:
                    self.log(f"Не вышло прочитать вопросы из "
                             f"{_api.os.path.basename(path)}")
            self.log(f"Не повторяю сами вопросы из выбранных паков: "
                     f"{len(self._exact_keys)} отпечатков.")
        from .pack_manifest import read as read_manifest, read_studios
        for path in (self.s.exclude_siq or []):
            if self.stopped():
                return
            if skip_tests and is_test_pack(path):
                continue
            # Пак, собранный этой же программой, носит список спрошенного при себе
            # (см. pack_manifest). Он точнее разбора ответов: у «детали сюжета»,
            # персонажа и загадки по названию в ответе стоит не тайтл, и прежним
            # способом такая франшиза не находилась вовсе.
            spent = read_manifest(path)
            self._excluded_roots |= spent["roots"]
            self._excluded_franchises |= spent["franchises"]
            self._excluded_studios |= read_studios(path)
            roots = _api.siq_answer_roots(path)
            if roots:
                self._excluded_roots |= roots
            elif not spent["roots"] and not spent["franchises"]:
                self.log(f"Не вышло прочитать ответы из {_api.os.path.basename(path)}")
        if (not self._excluded_roots and not self._excluded_franchises
                and not self._excluded_studios):
            return
        # Корень названия закрывает только части с ТЕМ ЖЕ названием («Наруто» и
        # «Наруто: Ураганные хроники»). Франшиза шире: у «Fate/Zero» и «Fate/stay
        # night» корни разные, а серия одна, и спрашивать её второй раз не надо
        # (просьба пользователя). Франшизы достаём из уже набранного каталога —
        # сети это не стоит ничего.
        from .catalog_superset import cached_catalog
        for target in ("anime", "manga"):
            sig = _api.shiki_cache_signature(self.s, target == "manga")
            for card in cached_catalog(self.db_cache, target, sig)[0]:
                key = (_api.franchise_key(card) if card.get("franchise") else "")
                if not key or key in self._excluded_franchises:
                    continue
                if self._root_excluded(card):
                    self._excluded_franchises.add(key)
        self.log(f"Не повторяю франшизы из чужих паков: "
                 f"{len(self._excluded_roots)} шт."
                 + (f" (франшиз по каталогу: {len(self._excluded_franchises)})"
                    if self._excluded_franchises else ""))
        if self._excluded_studios:
            self.log(f"Не повторяю студии из чужих паков: "
                     f"{len(self._excluded_studios)} шт.")

    def _root_excluded(self, anime: dict) -> bool:
        """Спрашивали ли этот тайтл (или его франшизу) в чужих паках."""
        if not self._excluded_roots and not self._excluded_franchises:
            return False
        key = (_api.franchise_key(anime) if (anime or {}).get("franchise")
               else "")
        legacy_key = str((anime or {}).get("franchise") or "").strip()
        if (key and key in self._excluded_franchises
                or legacy_key and legacy_key in self._excluded_franchises):
            return True
        for name in ((anime or {}).get("russian"), (anime or {}).get("name"),
                     (anime or {}).get("english")):
            root = _api.title_root(name)
            if root and root in self._excluded_roots:
                # Раз одна часть франшизы уже была в чужом паке, закрываем всю:
                # остальные её части названы иначе, и по корню не отсеклись бы.
                if key:
                    self._excluded_franchises.add(key)
                return True
        return False

    # ── шаг 1: список аниме ───────────────────────────────────────────────
    def _user_lists(self, target: str = "anime") -> list:
        """Живые карточки списков нужного раздела (аниме либо манга)."""
        return [u for u in self.s.users
                if u.username.strip() and u.statuses
                and str(u.target or "anime") == target]

    def _fetch_user_list(self, user, target: str = "anime") -> list[int]:
        """Список одного человека — с оглядкой на память между генерациями."""
        nick = user.username.strip()
        key = _api.user_list_cache_key(f"{user.source}:{target}", nick, user.statuses)
        ids = _api.cached_user_list(key)
        if ids is not None:
            self.log(f"Список {nick} ({user.source}) уже спрашивали — беру "
                     f"из памяти: {len(ids)} шт.")
            return list(ids)
        self.log(f"Беру список {nick} ({user.source}, "
                 f"{_api.TARGET_LABELS.get(target, target)})…")
        if user.source == "shikimori":
            api = self.shikimori
        elif user.source == "anilist":
            api = self.anilist
        else:
            api = self.mal
        ids = api.user_anime_ids(nick, user.statuses, progress_cb=self.log,
                                 should_stop=self._should_stop, target=target)
        # Оборванный по «Стоп» список неполон — запоминать его нельзя:
        # следующий пак собрался бы по огрызку.
        if ids and not self.stopped():
            _api.remember_user_list(key, ids)
        return list(ids)

    def _order_by_shares(self, seen: dict, by_user: dict) -> list[tuple[int, list]]:
        """Раскладывает id по долям списков (ползунок «Доли списков»).

        Без него порядок был просто случайным, и список на 1500 тайтлов
        забивал пак целиком, пока три списка по сотне почти не попадали в него
        (просьба пользователя). Здесь id выдаются по очереди, но очередь
        взвешенная: у кого доля больше, тот чаще и ходит.

        Метод — тот же, что при дележе мест по голосам (Д'Ондт): следующим
        берём список с наибольшим share/(взято+1). Тайтл, который есть у
        нескольких, отдаётся тому, чья очередь, и второй раз уже не выдаётся."""
        shares = {nick: max(0, int(pct)) for nick, pct in by_user.items()}
        if sum(shares.values()) <= 0 or len(shares) < 2:
            pairs = list(seen.items())
            self.rng.shuffle(pairs)
            return pairs
        pools: dict[str, list] = {}
        for nick in shares:
            pool = [aid for aid, owners in seen.items() if nick in owners]
            self.rng.shuffle(pool)
            pools[nick] = pool
        taken = {nick: 0 for nick in shares}
        out: list[tuple[int, list]] = []
        used: set = set()
        live = [n for n in shares if shares[n] > 0 and pools.get(n)]
        while live:
            nick = max(live, key=lambda n: shares[n] / (taken[n] + 1))
            pool = pools[nick]
            while pool and pool[-1] in used:
                pool.pop()
            if not pool:
                live.remove(nick)
                continue
            aid = pool.pop()
            used.add(aid)
            taken[nick] += 1
            out.append((aid, seen[aid]))
        # Хвост: тайтлы, до которых очередь не дошла (списки кончились
        # неодновременно). Они идут последними — если пак к тому времени не
        # набрался, пусть лучше будут они, чем недобор вопросов.
        rest = [(aid, owners) for aid, owners in seen.items() if aid not in used]
        self.rng.shuffle(rest)
        parts = ", ".join(f"{n} {shares[n]}%" for n in sorted(shares))
        self.log(f"Доли списков: {parts}")
        return out + rest

    def collect_manga_ids(self) -> list[tuple[int, list[str]]]:
        """[(id манги, у кого она в списке)] — то же, что collect_anime_ids, но
        для раздела манги/манхвы/ранобэ.

        Общей базы вроде AMQ у манги нет вовсе, поэтому случайный режим всегда
        идёт в каталог Shikimori."""
        if self.s.random_pool:
            return [(i, []) for i in self._random_shikimori_ids(manga=True)]
        seen: dict[int, list[str]] = {}
        by_user: dict[str, int] = {}
        for user in self._user_lists("manga"):
            if self.stopped():
                break
            nick = user.username.strip()
            by_user[nick] = int(user.share or 0)
            ids = self._fetch_user_list(user, "manga")
            for aid in ids:
                seen.setdefault(int(aid), [])
                if nick not in seen[int(aid)]:
                    seen[int(aid)].append(nick)
            self.log(f"{nick}: {len(ids)} манги/ранобэ")
        if not seen:
            return []
        pairs = self._order_by_shares(seen, by_user)
        self.log(f"Всего манги в работе: {len(pairs)}")
        return pairs

    def collect_anime_ids(self) -> list[tuple[int, list[str]]]:
        """[(id аниме, кто его смотрел)] в случайном порядке.

        Id — это ANN id только когда случайные аниме берутся из мастер-листа
        AMQ (так он устроен). И списки людей, и каталог Shikimori дают MAL id."""
        if self.s.random_pool:
            if not self.s.random_mode:
                # Галочка «Похожие» снята — списки не спрашиваем вовсе: пак
                # собирается случайными аниме, как и просил пользователь.
                self.log("«Похожие» снято — списки не спрашиваю, беру случайные "
                         "аниме из общей базы.")
            if self._random_source == "shikimori":
                if str(self.s.random_source or "") == "amq":
                    self.log("Песен в паке нет — базу беру с Shikimori: "
                             "мастер-лист AMQ знает только тайтлы с песнями.")
                return [(i, []) for i in self._random_shikimori_ids()]
            library = self.amq.library(progress_cb=self.log,
                                       should_stop=self._should_stop)
            ids = [ann for ann, year in library.items()
                   if year and self.s.year_from <= int(year) <= self.s.year_to]
            self.rng.shuffle(ids)
            self.log(f"Подходящих по году аниме в базе AMQ: {len(ids)}")
            return [(i, []) for i in ids]

        seen: dict[int, list[str]] = {}
        by_user: dict[str, int] = {}
        users = self._user_lists("anime")
        for user in users:
            if self.stopped():
                break
            nick = user.username.strip()
            by_user[nick] = int(user.share or 0)
            ids = self._fetch_user_list(user, "anime")
            for aid in ids:
                seen.setdefault(int(aid), [])
                if nick not in seen[int(aid)]:
                    seen[int(aid)].append(nick)
            self.log(f"{nick}: {len(ids)} аниме")

        if self.s.similar_count > 1:
            before = len(seen)
            need = int(self.s.similar_count)
            seen = {k: v for k, v in seen.items() if len(v) >= need}
            self.log(f"«Похожие»: из {before} аниме у {need}+ пользователей "
                     f"нашлось {len(seen)}")
        elif len(users) > 1:
            # «Похожие: 1 чел.» — списки просто складываются, совпадение не
            # требуется. Пишем об этом прямо, чтобы не выглядело, будто
            # совпадение всё-таки проверяется.
            self.log("«Похожие: 1 чел.» — беру всё из всех списков подряд, "
                     "совпадение не требуется.")
        pairs = self._order_by_shares(seen, by_user)
        self.log(f"Всего аниме в работе: {len(pairs)}")
        return pairs

    def _random_shikimori_ids(self, manga: bool = False) -> list[int]:
        """Случайные тайтлы прямо из каталога Shikimori (order: random).

        В отличие от мастер-листа AMQ (16 МБ, только id и год) фильтры уходят на
        сервер, а карточки приезжают сразу целиком. Набранное складывается в
        кэш на диске и переживает перезапуск программы: следующая генерация с
        теми же фильтрами не тратит на каталог ни одного запроса, пока не нажата
        кнопка «Обновить базу» (просьба пользователя). manga=True берёт каталог
        манги: своей общей базы вроде AMQ у книг нет вовсе."""
        if manga:
            # У книг запас свой: карточку манги ничем, кроме вопроса по манге, не
            # заменить, а книжные доли (экранизованные, манхва, маньхуа) отбирают
            # подходящих куда строже, чем рамка сложности.
            quota = int(self.s.question_quotas.get(_api.MANGA_KIND, 0) or 0)
            if not quota:
                return []
            want = max(50, quota * self.RANDOM_OVERSHOOT_MANGA)
        else:
            # Запас по РОДАМ ВОПРОСОВ (см. catalog_want.py): у сакуги, артов, мест
            # и загадок по названию отдача в разы ниже, чем у кадров и песен, и
            # общий множитель на весь пак им не хватал — каталог кончался раньше
            # пака. Прежние множители остаются нижней границей, чтобы паки из
            # песен и кадров набирали ровно столько же, сколько набирали.
            floor = (self.RANDOM_OVERSHOOT_SONGS if self.s.has_songs
                     else self.RANDOM_OVERSHOOT)
            want = max(50, self.s.total_questions * floor,
                       _api.anime_catalog_want(self.s))
        what = "манги" if manga else "тайтлов"
        cache = self._manga_cache if manga else self._card_cache
        target = "manga" if manga else "anime"
        sig = _api.shiki_cache_signature(self.s, manga)

        ids: list[int] = []
        seen: set[int] = set()

        def take(cards) -> int:
            """Кладёт карточки в память генератора и возвращает число новых."""
            fresh = 0
            for card in cards:
                try:
                    mal = int(card.get("malId") or card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if not mal or mal in seen:
                    continue
                seen.add(mal)
                ids.append(mal)
                cache[mal] = card
                fresh += 1
            return fresh

        # Годится и мешок с фильтрами шире нынешних (полный каталог без
        # исключённых жанров и т. п.): лишнее отсеивается на месте.
        from .catalog_superset import cached_catalog
        cached, complete = cached_catalog(self.db_cache, target, sig)
        take(cached)
        if ids:
            self.log(f"Каталог Shikimori: {len(ids)} {what} взято из кэша "
                     "(обновить — кнопкой «Обновить базу»)")
        # Сохранённые книги используем как есть: каталог обновляет отдельная
        # кнопка, а размер нового пака не должен запускать его фоновую загрузку.
        needs_fetch = not ids if manga else len(ids) < want
        if needs_fetch and not complete:
            if manga:
                self.log(f"Каталог манги пуст: беру запас до {want} карточек "
                         f"для {quota} вопросов по манге.")
            self._fetch_random_cards(manga, want, sig, take, lambda: len(ids))
            if manga:
                # При первом заполнении обеспечиваем заданные доли изданий.
                from .manga_catalog_topup import topup_editions
                topup_editions(self, sig, take)
        if not manga and not complete:
            # Много карточек — ещё не полный каталог: в пуле может не быть
            # первых сезонов при наличии четвёртого.
            self.log(f"Каталог аниме под текущие фильтры НЕПОЛНЫЙ: {len(ids)} "
                     "карточек. Полный — кнопкой «Обновить базу».")
            from .franchise_part_topup import topup as topup_parts
            topup_parts(self, sig, take)
        # Порядок случайный и внутри серии тоже (просьба пользователя): какой
        # сезон достанется паку, решает жребий, иначе одна и та же часть франшизы
        # попадалась бы из пака в пак. «Царство» приходило шестым сезоном не
        # из-за жребия, а потому что остальных сезонов в каталоге не было: до
        # кнопки «Обновить базу» он набирался обрывками (order: random) и целиком
        # не вычерпывался.
        if manga:
            self.rng.shuffle(ids)
            from .manga_source_candidates import prefer_reader_matches
            ids = prefer_reader_matches(self, ids)
        else:
            # Сначала франшиза, затем её часть: число спин-оффов не прибавляет
            # франшизе шансов, а недавно бывшие в паках части уступают другим.
            from .title_rotation import franchise_first
            ids = franchise_first(ids, cache, self.rng)
        self.log(f"Случайных {what} с Shikimori: {len(ids)}")
        return ids

    def _fetch_random_cards(self, manga: bool, want: int, sig: str,
                            take: _api.Callable[[list], int],
                            have: _api.Callable[[], int]) -> None:
        """Дочерпывает каталог Shikimori постранично, пока набранного меньше
        `want`.

        Всё, что приехало, тут же уходит в кэш на диск — даже если генерацию
        оборвали кнопкой «Стоп»: следующий запуск начнёт не с нуля."""
        if manga:
            kinds = [k for k in _api.MANGA_KINDS if self.s.manga_kinds.get(k)]
        else:
            kinds = [k for k in _api.ANIME_KINDS if self.s.kinds.get(k)]
        season = f"{int(self.s.year_from)}_{int(self.s.year_to)}"
        what = "манги" if manga else "тайтлов"
        target = "manga" if manga else "anime"
        fetch = (self.shikimori.random_mangas if manga
                 else self.shikimori.random_animes)
        try:
            for page in range(1, self.RANDOM_MAX_PAGES + 1):
                if self.stopped() or have() >= want:
                    break
                try:
                    cards = fetch(page, season=season, kinds=kinds,
                                  score=int(self.s.score_from),
                                  genres_exclude=self.s.genres_exclude)
                except _api.AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — беру, что успел набрать")
                    break
                if not cards:
                    break
                fresh = take(cards)
                self.db_cache.add_cards(target, sig, cards)
                self.log(f"Каталог Shikimori: набрано {have()} {what}…")
                if fresh == 0:
                    break             # каталог по этим фильтрам кончился
        finally:
            from .generation_checkpoint import checkpoint
            checkpoint(self)

    def fetch_full_catalog(self, manga: bool = False, *, unfiltered: bool = False,
                           resume: bool = False) -> list[int]:
        """Вычерпывает каталог Shikimori ЦЕЛИКОМ под текущие фильтры.

        В отличие от _random_shikimori_ids здесь нет потолка «сколько нужно на
        пак»: страницы идут одна за другой, пока каталог не кончится или пока не
        нажали «Остановить». Всё, что приехало, тут же уходит в кэш на диск —
        остановка на середине не теряет набранного. Возвращает id карточек."""
        settings = self.s
        if unfiltered:
            settings = replace(self.s, year_from=0, year_to=9999, score_from=0,
                               genres_exclude=[],
                               manga_kinds=dict.fromkeys(_api.MANGA_KINDS, True),
                               kinds=dict.fromkeys(_api.ANIME_KINDS, True))
        if manga:
            kinds = [k for k in _api.MANGA_KINDS if settings.manga_kinds.get(k)]
        else:
            kinds = [k for k in _api.ANIME_KINDS if settings.kinds.get(k)]
        season = "" if unfiltered else f"{int(settings.year_from)}_{int(settings.year_to)}"
        what = "манги" if manga else "тайтлов"
        target = "manga" if manga else "anime"
        errors = getattr(self, "_catalog_refresh_errors", None)
        if errors is None:
            errors = self._catalog_refresh_errors = {}
        errors.pop(target, None)
        cache = self._manga_cache if manga else self._card_cache
        sig = _api.shiki_cache_signature(settings, manga)
        ids: list[int] = []
        seen: set[int] = set()
        complete = False
        start_page = 1
        if resume:
            cursor = self.db_cache.catalog_cursor(target, sig)
            if not cursor["complete"]:
                start_page = cursor["next_page"]
                previous = self.db_cache.buckets(target).get(sig, ([], False))[0]
                for card in previous:
                    ident = int(card.get("malId") or card.get("id") or 0)
                    if ident and ident not in seen:
                        ids.append(ident)
                        seen.add(ident)
                        cache[ident] = card
        saved = _api.time.monotonic()
        try:
            for _page, cards in iter_catalog_pages(
                    self.shikimori, self.FULL_MAX_PAGES, self.stopped, manga=manga,
                    start_page=start_page,
                    limit=50, season=season, kinds=kinds, score=int(settings.score_from),
                    genres_exclude=settings.genres_exclude, order=self.FULL_ORDER):
                if not cards:
                    # Каталог по этим фильтрам кончился: генерация больше не
                    # полезет за ним на сервер (см. catalog_superset).
                    self.db_cache.mark_complete(target, sig)
                    complete = True
                    break
                fresh = 0
                for card in cards:
                    try:
                        mal = int(card.get("malId") or card.get("id") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mal or mal in seen:
                        continue
                    seen.add(mal)
                    ids.append(mal)
                    cache[mal] = card
                    fresh += 1
                self.db_cache.add_cards(target, sig, cards, next_page=_page + 1)
                if _api.time.monotonic() - saved >= 60:
                    from .generation_checkpoint import checkpoint
                    checkpoint(self)
                    saved = _api.time.monotonic()
                self.log(f"Каталог Shikimori: набрано {len(ids)} {what}…")
                if fresh == 0:
                    raise _api.AnimePackApiError("Shikimori: каталог повторил непустую страницу.")
            if not complete and not self.stopped():
                raise _api.AnimePackApiError("Shikimori: достигнут предел страниц; каталог не завершён.")
        except _api.AnimePackApiError as e:
            errors[target] = str(e)
            self.log(f"Shikimori: {e} — беру, что успел набрать")
        finally:
            from .generation_checkpoint import checkpoint
            checkpoint(self)
        if self.stopped():
            self.log(f"Каталог Shikimori: остановлено на {len(ids)} "
                     f"{what} — набранное сохранено.")
        return ids

    def _animes_by_ids(self, ids) -> list[dict]:
        """Карточки аниме с оглядкой на кэш: то, что уже приехало из каталога
        Shikimori (order: random), второй раз не запрашиваем."""
        ids = [int(i) for i in ids]
        cached = [self._card_cache[i] for i in ids if i in self._card_cache]
        rest = [i for i in ids if i not in self._card_cache]
        if not rest:
            return cached
        return cached + self.shikimori.animes_by_ids(rest)

    def _mangas_by_ids(self, ids) -> list[dict]:
        """То же для карточек манги/ранобэ (свой кэш: id манги и аниме на MAL
        считаются отдельно и запросто совпадают).

        Карточка БЕЗ поля `related` — из старого кэша, набранного до того, как
        мы стали спрашивать у книги её аниме-экранизации. Верить такой нельзя:
        «экранизаций нет» и «про экранизации не спрашивали» — разные вещи, а
        различить их можно только по наличию самого поля (у книги без
        экранизации оно приезжает пустым списком). Пока мы этого не проверяли,
        вся манга из старого кэша считалась неэкранизованной: «Этот
        замечательный мир! (2014)» мерился книжной шкалой и стоил 20 вместо
        цены своего аниме плюс два. Такие карточки перезапрашиваем и кладём в
        кэш заново — руками «Обновить базу» нажимать не нужно."""
        ids = [int(i) for i in ids]
        cached, rest = [], []
        for i in ids:
            card = self._manga_cache.get(i)
            if isinstance(card, dict) and "related" in card:
                cached.append(card)
            else:
                rest.append(i)
        if not rest:
            return cached
        fresh = self.shikimori.mangas_by_ids(rest)
        for card in fresh:
            try:
                mal = int(card.get("malId") or card.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if mal:
                self._manga_cache[mal] = card
        if fresh:
            self.db_cache.add_cards("manga",
                                    _api.shiki_cache_signature(self.s, True), fresh)
        return cached + fresh

    # ── шаг 2: кандидаты ──────────────────────────────────────────────────
    def _anime_feed(self):
        """Общий разбор каталога аниме — один на оба потока кандидатов.

        Карточки спрашиваются и разбираются ровно один раз; песенный и
        непесенный потоки тянут из его очередей (см. anime_card_feed)."""
        feed = getattr(self, "_card_feed", None)
        if feed is None:
            quotas = self.s.question_quotas
            want = any(quotas.get(k) for k in _api.SONG_KINDS + (_api.VIDEO_KIND,))
            feed = self._card_feed = _api.AnimeCardFeed(
                self, self.collect_anime_ids(), want_songs=want)
        return feed

    def _silent_kind(self) -> _api.Optional[str]:
        """Первый род вопросов без песни, у которого есть доля (манга — своя)."""
        for kind in self.s.silent_kinds:
            if kind != _api.MANGA_KIND:
                return kind
        return None

    def iter_candidates(self) -> _api.Iterator[_api.SongCandidate]:
        """Все кандидаты пака: песенные, непесенные и книжные вперемешку.

        Потоки идут не подряд, а по очереди, взвешенной по квотам: иначе
        манга набралась бы только после того, как кончатся аниме, а кадрам
        доставались бы одни объедки песенного потока."""
        quotas = self.s.question_quotas
        manga_need = int(quotas.get(_api.MANGA_KIND, 0))
        song_need = sum(int(quotas.get(k, 0) or 0)
                        for k in _api.SONG_KINDS + (_api.VIDEO_KIND,))
        silent_need = sum(int(v or 0) for k, v in quotas.items()
                          if k in _api.SILENT_KINDS and k != _api.MANGA_KIND)
        streams = []
        if song_need or silent_need:
            streams.append(("anime", self._iter_anime_candidates(),
                            max(1, song_need or silent_need)))
        if song_need and silent_need:
            # Смешанный пак: кадру, персонажу, сюжету и артам песня не нужна
            # вовсе, и ждать её от AnisongDB им незачем.
            streams.append(("silent", self._iter_silent_candidates(), silent_need))
        if manga_need > 0:
            # План книг строится фоном — поток аниме не ждёт его минутами.
            from .manga_plan_prefetch import start as start_manga_plan
            start_manga_plan(self)
            streams.append((_api.MANGA_KIND, self._iter_manga_candidates(),
                            manga_need))
        yield from self._merge_streams(streams, self._closed_streams,
                                       getattr(self, "_idle_streams", None))

    @staticmethod
    def _merge_streams(streams, closed=None, idle=None) -> _api.Iterator[_api.SongCandidate]:
        """Тянет из нескольких потоков по очереди, взвешенной по их весам
        (тот же дележ Д'Ондта, что и у долей списков).

        streams — тройки «ключ потока, кандидаты, вес». closed — множество
        ключей, которые больше не нужны: такой поток перестаёт спрашиваться
        вовсе, а когда не осталось ни одного нужного, кандидаты кончаются.
        Без этого маленький поток аниме вычерпывался первым, и весь остаток
        прогона цикл отбора тянул карточки книг, которым места в паке уже не
        было: каждую приходилось сперва скачать с Shikimori, а потом
        выбросить (в логе пользователя так ушло шесть минут из девяти на
        «поиск кандидатов», и ни одного вопроса они не дали).

        idle — ключи потоков, которые спрашиваются, только когда остальные
        кончились: в отличие от closed, такой поток не теряется насовсем."""
        from .manga_plan_prefetch import PENDING
        live = [[key, it, float(weight), 0] for key, it, weight in streams
                if weight > 0]
        off = closed if closed is not None else frozenset()
        # Потоки, ответившие PENDING (план ещё строится): их пропускаем, пока
        # остальные отдают кандидатов, и переспрашиваем после каждого кандидата.
        waiting: set[int] = set()
        while live:
            ready = [row for row in live if row[0] not in off]
            if not ready:
                return
            awake = [row for row in ready if not idle or row[0] not in idle] or ready
            asked = [row for row in awake if id(row) not in waiting]
            if not asked:
                _api.time.sleep(0.2)
                waiting.clear()
                continue
            row = max(asked, key=lambda r: r[2] / (r[3] + 1))
            cand = next(row[1], None)
            if cand is None:
                live.remove(row)
                continue
            if cand is PENDING:
                waiting.add(id(row))
                continue
            waiting.clear()
            row[3] += 1
            yield cand

    def _iter_manga_candidates(self) -> _api.Iterator[_api.SongCandidate]:
        """Кандидаты-вопросы по манге/манхве/ранобэ.

        Песен и кадров у книги нет, поэтому вопрос — либо портрет персонажа
        (его выберет _download_character уже при загрузке медиа), либо обложка;
        всё остальное — ответ, цена, узнаваемость — считается ровно как у
        аниме: карточка Shikimori у манги устроена так же."""
        from .manga_plan_prefetch import PENDING, take
        built = None
        for built in take(self):
            if built is PENDING:
                yield PENDING
        if built is None or built is PENDING:
            return
        pairs, plan = built
        if not pairs:
            self._spend_kind(_api.MANGA_KIND, "в каталоге нет книг под эти фильтры")
            return
        users_by_id = {aid: users for aid, users in pairs}
        used_manga: set[int] = set()
        # Франшизы общие с потоком аниме (просьба пользователя): раньше у каждого
        # потока был свой набор, и пак спокойно выдавал кадр из «Магической битвы»,
        # а следом страницу манги оттуда же.
        used_franchise = self._used_franchise
        for batch in plan.batches(_api.SHIKIMORI_BATCH):
            if self.stopped():
                return
            try:
                cards = self._mangas_by_ids([i for i in batch
                                             if i not in used_manga])
            except _api.AnimePackApiError as e:
                self.log(f"Shikimori (манга): {e} — пропускаю пачку")
                continue
            self._load_franchise_indexes(cards)
            adapted = _api.load_adaptations(self, cards)
            for card in cards:
                if self.stopped():
                    return
                try:
                    mal = int(card.get("malId") or 0)
                except (TypeError, ValueError):
                    continue
                if not mal:
                    continue
                anime = adapted.get(id(card)) or {}
                if not self._accept_anime(card, mal, used_manga, used_franchise,
                                          manga=True, adapted=anime):
                    continue
                cand = _api.SongCandidate(song={}, anime=card, kind=_api.MANGA_KIND,
                                    media="manga",
                                    users=list(users_by_id.get(mal, [])),
                                    franchise_index=self._franchise_index(card),
                                    compress_images=self.s.compress_images)
                try:
                    known = self.db_cache.memo('manga_favorites', int(card.get('id') or 0))
                    cand.favorites = int(known) if known is not None else -1
                except (TypeError, ValueError):
                    cand.favorites = -1
                _api.apply_adaptation(cand, anime)
                from .ru_popularity_store import apply_ru_popularity
                apply_ru_popularity(self, cand)
                cand._reserved = self._last_reserved
                self._manga_yielded = getattr(self, "_manga_yielded", 0) + 1
                yield cand
        # Каталог манги вычерпан. Мангой может стать только карточка ОТСЮДА, так
        # что доля манги дальше неисполнима — её места надо отдать остальным, иначе
        # цикл отбора будет требовать кандидатов до последнего тайтла базы аниме.
        waiting = sum(c.is_manga for c in getattr(self, "_level_bench", ()))
        self.log(f"Каталог манги просмотрен: {len(pairs)} карточек; "
                 f"отложено ради средней сложности {waiting}, "
                 f"ради долей изданий {self._manga_mix.bench_size}.")
        # Места книжной доли отдаём другим родам вопросов, только когда книг и
        # правда не осталось. Отложенные по книжным долям (скамейка MangaMix) —
        # это готовые кандидаты: раздать их места заранее значило бы недобрать пак
        # при полной скамейке (см. _close_spent_streams).
        # Последние книги ещё лежат в очереди проверок (до сотни карточек):
        # долю закрывает главный цикл, когда получит их все (_close_spent_streams).
        if not self._manga_mix.bench_size and not waiting:
            self._manga_catalog_end = f"каталог книг просмотрен целиком ({len(pairs)} карточек)"

    def _iter_anime_candidates(self) -> _api.Iterator[_api.SongCandidate]:
        """Песенный поток: тайтлы с песней, прошедшей `filter_song`.

        Пак без единого песенного вопроса до AnisongDB не доходит вовсе —
        тогда этот же поток отдаёт карточки Shikimori как есть: кадры,
        пиксели, персонажи, анаграммы, сюжеты."""
        feed = self._anime_feed()
        if not feed.ids:
            return
        if feed.want_songs:
            yield from feed.songs(self._used_franchise)
            return
        kind = self._silent_kind()
        if kind is not None:
            yield from feed.pictures(kind, self._used_franchise)

    def _iter_silent_candidates(self) -> _api.Iterator[_api.SongCandidate]:
        """Непесенный поток смешанного пака: карточки БЕЗ подходящей песни.

        Он и был потерян: при любой ненулевой доле песен весь каталог шёл
        через AnisongDB, и тайтл без песни не рассматривался даже под кадр
        (в живом логе 11 962 карточки из 12 811 не доходили до отбора)."""
        feed = self._anime_feed()
        kind = self._silent_kind()
        if not feed.ids or kind is None:
            return
        yield from feed.pictures(kind, self._used_franchise)

    @property
    def _random_source(self) -> str:
        """Откуда брать случайные тайтлы на самом деле.

        Мастер-лист AMQ — это список тайтлов, у которых есть песни в AMQ, и
        больше он ни о чём не знает. Поэтому пакам без песен (кадры, персонажи)
        он не годится: база для них всегда Shikimori, что бы ни стояло в
        галочках."""
        want = str(self.s.random_source or "shikimori")
        if want == "amq" and not self.s.has_songs:
            return "shikimori"
        return want

    @property
    def _ids_are_ann(self) -> bool:
        """Мастер-лист AMQ хранит ANN id; списки людей и каталог Shikimori —
        MAL id. От этого зависит, каким запросом спрашивать AnisongDB."""
        return bool(self.s.random_pool and self._random_source != "shikimori")

    def _iter_picture_candidates(self, kind, ids, users_by_id, used_anime,
                                 used_franchise) -> _api.Iterator[_api.SongCandidate]:
        """Кандидаты по готовому списку id: кадры, пиксели, персонажи, анаграммы,
        сюжет. Вопросом служит картинка или текст, и AnisongDB такому паку не
        нужен вовсе.

        Сам отбор ходит не сюда, а в общий разбор каталога (anime_card_feed):
        там карточка достаётся один раз и на песенный поток, и на непесенный.
        Здесь то же самое для отдельно взятого списка id.

        Списки людей и каталог Shikimori дают MAL id сразу, поэтому AnisongDB
        там не нужен вовсе. А мастер-лист AMQ хранит ANN id, и перевести их в
        MAL умеет только AnisongDB — тогда пачка всё равно идёт через него, но
        уже без фильтров по песням."""
        for batch in _api._chunks(ids, _api.ANISONG_BATCH):
            if self.stopped():
                return
            if self._ids_are_ann:
                self.log(f"AnisongDB: перевожу {len(batch)} id в MAL…")
                try:
                    songs = self.anisong.songs_by_ann_ids(batch)
                except _api.AnimePackApiError as e:
                    self.log(f"AnisongDB: {e} — пропускаю пачку")
                    continue
                mal_ids, seen = [], set()
                for song in songs:
                    try:
                        mal = int((song.get("linked_ids") or {})["myanimelist"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if mal in seen or mal in used_anime:
                        continue
                    seen.add(mal)
                    mal_ids.append(mal)
            else:
                mal_ids = [i for i in batch if i not in used_anime]
            if not mal_ids:
                continue

            for sub in _api._chunks(mal_ids, _api.SHIKIMORI_BATCH):
                if self.stopped():
                    return
                try:
                    animes = self._animes_by_ids(sub)
                except _api.AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — пропускаю пачку")
                    continue
                self._load_franchise_indexes(animes)
                for anime in animes:
                    if self.stopped():
                        return
                    try:
                        mal = int(anime.get("malId") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mal:
                        continue
                    if not self._accept_anime(anime, mal, used_anime,
                                              used_franchise):
                        continue
                    cand = _api.SongCandidate(
                        song={}, anime=anime, kind=kind,
                        users=list(users_by_id.get(mal, [])),
                        franchise_index=self._franchise_index(anime),
                        compress_images=self.s.compress_images)
                    cand._reserved = self._last_reserved
                    yield cand

    # ── общие проверки тайтла (оба потока кандидатов) ─────────────────────
    def _load_franchise_indexes(self, animes: list) -> None:
        """Догружает узнаваемость франшиз для пачки карточек.

        Части франшизы (до FRANCHISE_PARTS штук по убыванию популярности)
        спрашиваются один раз на все генерации — дальше они лежат в кэше на
        диске. Из них считается индекс серии целиком: самая популярная часть
        плюс надбавка за живые сезоны и послабление по году, если у старого
        тайтла есть заметное продолжение (franchise_parts_index)."""
        cards = [a for a in animes if isinstance(a, dict)]
        need = {str(a.get("franchise") or "").strip() for a in cards}
        need = {f for f in need if f and f not in self._fr_parts}
        fresh: dict[str, list] = {}
        ask = set()
        for key in need:
            known = self.db_cache.franchise(key)
            if known is None:
                ask.add(key)
            else:
                fresh[key] = known
        if ask:
            try:
                loaded = self.shikimori.franchise_parts(sorted(ask))
            except Exception as e:  # noqa: BLE001 — без этого пак всё равно соберётся
                self.log(f"Узнаваемость франшиз не загрузилась: {e}")
                loaded = {}
            # В кэш идут ТОЛЬКО те франшизы, про которые сервер и правда
            # ответил (пустой список — тоже ответ: «частей нет»). Про молчание
            # не запоминаем ничего: разовый обрыв связи иначе навсегда осел бы
            # в кэше нулевой узнаваемостью.
            got = {key: list(rows) for key, rows in (loaded or {}).items()
                   if key in ask}
            self.db_cache.add_franchises(got)
            from .generation_checkpoint import checkpoint
            checkpoint(self)
            fresh.update(got)
        for key in need:
            if key in fresh:
                self._fr_parts[key] = list(fresh[key])
        for anime in cards:
            key = str(anime.get("franchise") or "").strip()
            if not key:
                continue
            parts = self._fr_parts.get(key, [])
            branch = _api.franchise_branch_key(anime, parts)
            cache_key = (key, branch)
            if cache_key not in self._fr_index:
                self._fr_index[cache_key] = _api.branch_franchise_index(anime, parts)

    def _franchise_index(self, anime: dict) -> float:
        key = str(anime.get("franchise") or "").strip()
        parts = self._fr_parts.get(key, [])
        branch = _api.franchise_branch_key(anime, parts)
        return self._fr_index.get((key, branch), 0.0)

    def _accept_anime(self, anime: dict, mal: int, used_anime: set,
                      used_franchise: set, manga: bool = False,
                      adapted: _api.Optional[dict] = None) -> bool:
        """Годится ли тайтл: фильтры, дубли и сложность. Принятый сразу
        помечается использованным."""
        self._seen_titles += 1
        # Почему тайтл не взят: «franchise» — серию держит другой кандидат (он мог
        # ещё только качаться, см. AnimeCardFeed.held).
        self._last_reject = ""
        # Аниме и книги считаем порознь: «база дала 6 627 тайтлов» одной строкой
        # ни о чём не говорило — там были и 5 778 книг, и 849 аниме с песней.
        self._seen_by_media["manga" if manga else "anime"] += 1
        if not self.s.dup_anime and mal in used_anime:
            self._skips["тайтл уже брали"] += 1
            return False
        if not _api.filter_anime(anime, self.s, manga=manga):
            self._skips["фильтры (тип, год, оценка, жанры)"] += 1
            return False
        marks = _franchise_marks(anime, adapted if manga else None)
        # Франшизы, уже спрошенные в чужих паках (кнопка «Не повторять из паков»):
        # закрыт и сам тайтл, и вся его франшиза.
        if self._root_excluded(anime):
            self._skips["уже спрашивали в чужих паках"] += 1
            return False
        if not self.s.dup_franchise and any(m in used_franchise for m in marks):
            self._skips["франшиза уже в паке"] += 1
            self._last_reject = "franchise"
            return False
        # Сложность считаем через карточку-пустышку: там year/score разбираются
        # безопасно, и величина получается ровно та же, что у кандидата.
        probe = _api.SongCandidate(song={}, anime=anime,
                              media="manga" if manga else "anime",
                              franchise_index=self._franchise_index(anime))
        try:
            known = self.db_cache.memo('manga_favorites' if manga else 'anime_favorites',
                                      int(anime.get('id') or 0))
            probe.favorites = int(known) if known is not None else -1
        except (TypeError, ValueError):
            probe.favorites = -1
        if manga:
            from .ru_popularity_store import apply_ru_popularity
            apply_ru_popularity(self, probe)
            # Экранизованная книга меряется узнаваемостью своего АНИМЕ: по книжной
            # шкале её вопрос вышел бы вдесятеро труднее, чем он на самом деле.
            _api.apply_adaptation(probe, adapted or {})
            from .manga_editions import card_range
            low, high = card_range(self.s, anime)
            note = "рамки сложности манги"
        else:
            # Род вопроса ещё не выбран, поэтому рамка тут самая широкая из
            # задействованных: свою (у артов она отдельная) вопрос пройдёт уже
            # в _pick_kind.
            low, high = self.s.level_span
            note = "рамки сложности пака"
        if not (low <= probe.level <= high):
            self._skips[note] += 1
            return False
        with self._studio_lock:
            # Пока считали сложность, фоновый вопрос-студия мог занять одну из
            # франшиз своих дополнительных кадров.
            if not self.s.dup_franchise and any(m in used_franchise for m in marks):
                self._skips["франшиза уже в паке"] += 1
                self._last_reject = "franchise"
                return False
            used_anime.add(mal)
            used_franchise.update(marks)
        self._good_titles += 1
        self._good_by_media["manga" if manga else "anime"] += 1
        # Что именно забронировано под этого кандидата: цикл отбора вернёт
        # франшизу в оборот, если вопросом кандидат так и не станет (см.
        # _release_candidate). Между этой строкой и созданием карточки кандидата
        # управление никуда не уходит — оба потока кандидатов разбираются в одном
        # потоке выполнения, так что перезаписать чужую бронь тут нечем.
        self._last_reserved = marks
        return True

    def _release_candidate(self, cand) -> None:
        """Возвращает франшизу кандидата в оборот: вопросом он не стал.

        `_accept_anime` бронирует франшизу, как только тайтл прошёл фильтры, —
        иначе поток аниме и поток книг выдали бы кадр и страницу манги из одной
        серии. Но кандидат, которому не нашлось места, отвергнутый средней
        сложностью или сорвавшийся на загрузке, вопросом так и не стал, и
        держать за ним всю серию незачем: на небольшом каталоге из-за этого
        сгорали тысячи тайтлов («отсеяно „франшиза уже в паке“: 8987» при паке
        в 134 вопроса).

        Ключи берём те, что бронировались, а не считаем заново по карточке: у
        загадок по названию карточка кандидата к этому времени уже подменена
        на выбранный вариант тайтла."""
        studio = getattr(cand, "_studio_reserved", "")
        if studio:
            cand._studio_reserved = ""
            with self._studio_lock:
                self._used_studios.discard(studio)
                for mark in getattr(cand, "_studio_reserved_franchises", ()):
                    self._used_franchise.discard(mark)
                cand._studio_reserved_franchises = ()
        keys = getattr(cand, "_reserved", None)
        if not keys:
            return
        cand._reserved = None
        # Ключи не забываем: отложенный кандидат ещё может вернуться со скамейки,
        # и тогда франшизу надо занять заново (см. _rebook_candidate).
        cand._bench_keys = keys
        with self._studio_lock:
            for key in keys:
                if key:
                    self._used_franchise.discard(key)
            # По этому счёту поток карточек узнаёт, что отложенным тайтлам пора
            # проверить свою серию заново (AnimeCardFeed.held).
            self._franchise_releases = getattr(self, "_franchise_releases", 0) + 1

    def _trim_start(self, song: dict) -> int:
        """Случайная точка старта отрезка. Короткую песню берём с начала —
        в ASPG получалось отрицательное смещение."""
        try:
            length = float(song.get("songLength") or 0.0)
        except (TypeError, ValueError):
            length = 0.0
        latest = int(length) - int(self.s.audio_cut)
        if latest <= 0:
            return 0
        return self.rng.randint(0, latest)
