# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: fetch_full_catalog. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from dataclasses import replace
from .catalog_pages import iter_catalog_pages


def fetch_full_catalog(self, manga: bool = False, *, unfiltered: bool = False) -> list[int]:
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
    try:
        for _page, cards in iter_catalog_pages(
                self.shikimori, self.FULL_MAX_PAGES, self.stopped, manga=manga,
                limit=50, season=season, kinds=kinds, score=int(settings.score_from),
                genres_exclude=settings.genres_exclude, order=self.FULL_ORDER):
            if not cards:
                # Каталог по этим фильтрам кончился: генерация больше не
                # полезет за ним на сервер (см. catalog_superset).
                self.db_cache.mark_complete(target, sig)
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
            self.db_cache.add_cards(target, sig, cards)
            self.log(f"Каталог Shikimori: набрано {len(ids)} {what}…")
            if fresh == 0:
                raise _api.AnimePackApiError("Shikimori: каталог повторил непустую страницу.")
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
        streams.append((_api.MANGA_KIND, self._iter_manga_candidates(),
                        manga_need))
    yield from self._merge_streams(streams, self._closed_streams)

@staticmethod
def _merge_streams(streams, closed=None) -> _api.Iterator[_api.SongCandidate]:
    """Тянет из нескольких потоков по очереди, взвешенной по их весам
        (тот же дележ Д'Ондта, что и у долей списков).

        streams — тройки «ключ потока, кандидаты, вес». closed — множество
        ключей, которые больше не нужны: такой поток перестаёт спрашиваться
        вовсе, а когда не осталось ни одного нужного, кандидаты кончаются.
        Без этого маленький поток аниме вычерпывался первым, и весь остаток
        прогона цикл отбора тянул карточки книг, которым места в паке уже не
        было: каждую приходилось сперва скачать с Shikimori, а потом
        выбросить (в логе пользователя так ушло шесть минут из девяти на
        «поиск кандидатов», и ни одного вопроса они не дали)."""
    live = [[key, it, float(weight), 0] for key, it, weight in streams
            if weight > 0]
    off = closed if closed is not None else frozenset()
    while live:
        ready = [row for row in live if row[0] not in off]
        if not ready:
            return
        row = max(ready, key=lambda r: r[2] / (r[3] + 1))
        cand = next(row[1], None)
        if cand is None:
            live.remove(row)
            continue
        row[3] += 1
        yield cand

def _iter_manga_candidates(self) -> _api.Iterator[_api.SongCandidate]:
    """Кандидаты-вопросы по манге/манхве/ранобэ.

        Песен и кадров у книги нет, поэтому вопрос — либо портрет персонажа
        (его выберет _download_character уже при загрузке медиа), либо обложка;
        всё остальное — ответ, цена, узнаваемость — считается ровно как у
        аниме: карточка Shikimori у манги устроена так же."""
    pairs = self.collect_manga_ids()
    if not pairs:
        self._spend_kind(_api.MANGA_KIND)
        return
    users_by_id = {aid: users for aid, users in pairs}
    used_manga: set[int] = set()
    # Франшизы общие с потоком аниме (просьба пользователя): раньше у каждого
    # потока был свой набор, и пак спокойно выдавал кадр из «Магической битвы»,
    # а следом страницу манги оттуда же.
    used_franchise = self._used_franchise
    for batch in _api._chunks([aid for aid, _ in pairs], _api.SHIKIMORI_BATCH):
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
            _api.apply_adaptation(cand, anime)
            from .ru_popularity_store import apply_ru_popularity
            apply_ru_popularity(self, cand)
            cand._reserved = self._last_reserved
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
    if not self._manga_mix.bench_size and not waiting:
        self._spend_kind(_api.MANGA_KIND)

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
