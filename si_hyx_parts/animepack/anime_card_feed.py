# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Один разбор каталога аниме на оба потока кандидатов. Namespace: animepack.

Песня из AnisongDB нужна РОВНО песенным вопросам. Кадры, персонажи, сюжет,
арты, сакуга, места, студии и загадки по названию берутся прямо с карточки
Shikimori — им всё равно, есть ли у тайтла опенинг в базе AMQ.

Раньше весь поток аниме шёл через AnisongDB и `filter_song`, как только в паке
появлялась хоть какая-то доля песен. Тайтл без подходящей песни не
рассматривался вовсе — ни под кадр, ни под персонажа: в живом логе из 12 811
карточек кэша до отбора добрались 849, и пак вышел 116 вопросов из 144, хотя
в активный диапазон сложности попадали 4 520 тайтлов.

Здесь каталог перебирается ОДИН раз. Карточка разбирается и ложится в одну из
двух очередей — «есть подходящая песня» и «песни нет». Песенный поток тянет
только из первой. Непесенный — из ОБЕИХ в порядке каталога: наличие песни
решает лишь пригодность к песенной категории. Тайтл с песней уходит под кадр,
только пока песен в остатке каталога с запасом хватает песенным местам:
маленький каталог (списки пользователей) иначе остался бы без песен. Раньше он читал одну очередь
«песни нет» и систематически выбирал тайтлы без подходящей песни — фильмы и
спин-оффы («Наруто 3», театральные «Пле-пле-плеяды»), а не основные сезоны.
Та же карточка второй раз с Shikimori не спрашивается, `used_anime` и брони
франшиз у обоих потоков общие.
"""
from __future__ import annotations
from collections import deque

import animepack as _api


_EMPTY = object()
# Во сколько раз песенных тайтлов впереди должно быть больше, чем свободных
# песенных мест, чтобы тайтл с песней можно было отдать под кадр: часть
# кандидатов отсеет сложность, часть — неудачная загрузка.
SONG_SUPPLY_MARGIN = 3


def _mal_of_song(song: dict) -> int:
    try:
        return int((song.get("linked_ids") or {})["myanimelist"])
    except (KeyError, TypeError, ValueError):
        return 0


def _mal_of_card(card: dict) -> int:
    try:
        return int(card.get("malId") or 0)
    except (TypeError, ValueError):
        return 0


def _known_favorites(gen, anime):
    """Use saved popularity before average selection, without extra HTTP calls."""
    try:
        title_id = int(anime.get("id") or 0)
        value = gen.db_cache.memo("anime_favorites", title_id)
        return int(value) if value is not None else -1
    except (TypeError, ValueError):
        return -1


class AnimeCardFeed:
    """Каталог аниме, разобранный один раз на два потока кандидатов."""

    def __init__(self, gen, pairs, want_songs: bool):
        self.gen = gen
        self.ids = [int(aid) for aid, _ in pairs]
        self.users_by_id = {int(aid): list(users) for aid, users in pairs}
        from .catalog_selection import CatalogPlan
        self.plan = CatalogPlan(gen, pairs)
        self.want_songs = bool(want_songs)
        # Разобранные карточки: (карточка, MAL id, подходящие песни, названия
        # всех песен тайтла). Первая очередь кормит песенные вопросы, вторая —
        # все остальные.
        self.with_song: deque = deque()
        self.no_song: deque = deque()
        # Тайтлы, уже ставшие кандидатом. Набор ОДИН на оба потока: иначе
        # пак выдал бы опенинг и кадр одного и того же аниме.
        self.used_anime: set[int] = set()
        # Номер карточки в порядке каталога: по нему непесенный поток сливает
        # обе очереди, не отдавая предпочтения ни одной из них.
        self._arrived = 0
        # Сколько карточек разобрано и у скольких нашлась песня — по ним
        # оценивается, сколько песенных тайтлов ещё впереди.
        self._walked = 0
        self._songful = 0
        self.done = False
        self._source = self._walk()
        # Тайтлы, отсеянные только потому, что их серию держал другой
        # кандидат: (франшизные ключи, строка). Держатель мог ещё качаться и
        # сорваться — тогда серия свободна, и тайтл возвращается в очередь.
        # Раньше такой выбрасывался навсегда: окно в 20 кандидатов наперёд
        # успевало отсеять всю серию, пока её первый тайтл качался.
        self.held: list = []
        self._held_releases = 0

    @property
    def drained(self) -> bool:
        """Каталог разобран, и очереди пусты: новых карточек аниме не будет.

        Отложенные по франшизе (`held`) сюда не считаются — они ждут исхода
        чужой загрузки, и поток из-за них может висеть, пока идёт отбор книг."""
        return self.done and not self.with_song and not self.no_song

    # ── производитель ────────────────────────────────────────────────────
    def _songs_needed(self):
        return self.want_songs and getattr(self.gen, "_song_lookup_needed", True)

    def _eligible_song_ids(self, batch):
        """Только чистые фильтры известных MAL-карточек; брони здесь нет."""
        gen = self.gen
        cards = getattr(gen, "_card_cache", {})
        return [aid for aid in batch if aid not in cards or (
            _api.filter_anime(cards[aid], gen.s)
            and not gen._root_excluded(cards[aid]))]

    def _ask_songs(self, batch):
        """Песни пачки. Возвращает (подходящие по id, все названия по id,
        MAL id пачки) либо None, если пачку пришлось пропустить."""
        gen = self.gen
        if not self._songs_needed() and not gen._ids_are_ann:
            return {}, {}, list(batch)
        asked = batch if gen._ids_are_ann else self._eligible_song_ids(batch)
        if not asked:
            return {}, {}, list(batch)
        try:
            if gen._ids_are_ann:
                gen.log(f"AnisongDB: спрашиваю песни для {len(asked)} аниме…")
                songs = gen.anisong.songs_by_ann_ids(asked)
            else:
                songs = gen.anisong.songs_by_mal_ids(asked)
                # Пачки, целиком взятые из кэша, в журнал не пишутся: в живом
                # логе 639 строк «спрашиваю» были чтением кэша без единого
                # запроса к серверу.
                fetched = getattr(gen.anisong, "last_fetched", None)
                fetched = fetched() if callable(fetched) else len(asked)
                if fetched:
                    gen.log(f"AnisongDB: спросил песни для {fetched} аниме "
                            f"(из кэша {len(asked) - fetched}).")
        except _api.AnimePackApiError as e:
            if gen._ids_are_ann:
                # Мастер-лист AMQ хранит ANN id: без ответа AnisongDB карточку
                # тайтла не спросить вовсе.
                gen.log(f"AnisongDB: {e} — пропускаю пачку")
                return None
            # А с MAL id непесенным вопросам AnisongDB не нужен: песен у этой
            # пачки просто не будет, а кадры и персонажи из неё возьмутся.
            gen.log(f"AnisongDB: {e} — беру эту пачку без песен")
            return {}, {}, list(batch)
        # Названия ВСЕХ песен тайтла — до фильтра по типам: поиску каверов
        # они нужны целиком (см. cover_meta.song_ref).
        siblings: dict[int, list[str]] = {}
        order: list[int] = []
        for song in songs:
            mal = _mal_of_song(song)
            if not mal:
                continue
            if mal not in siblings:
                siblings[mal] = []
                order.append(mal)
            name = str(song.get("songName") or "").strip()
            if name:
                siblings[mal].append(name)
        picked = [s for s in songs if _api.filter_song(s, gen.s)]
        gen.rng.shuffle(picked)
        by_mal: dict[int, list[dict]] = {}
        for song in picked:
            mal = _mal_of_song(song)
            if mal:
                by_mal.setdefault(mal, []).append(song)
        # Мастер-лист AMQ хранит ANN id: MAL-номер известен только из ответа
        # AnisongDB, и карточку тайтла, которого там нет, взять неоткуда.
        return by_mal, siblings, (order if gen._ids_are_ann else list(batch))

    def _walk(self):
        """Перебирает каталог, раскладывая карточки по очередям.

        Отдаёт управление после каждой разобранной пачки: кому из потоков
        карточки нужнее, тот производителя и крутит."""
        gen = self.gen
        for batch in self.plan.batches(_api.ANISONG_BATCH):
            if gen.stopped():
                return
            got = self._ask_songs(batch)
            if got is None:
                continue
            by_mal, siblings, mal_batch = got
            mal_batch = [i for i in mal_batch if i not in self.used_anime]
            for sub in _api._chunks(mal_batch, _api.SHIKIMORI_BATCH):
                if gen.stopped():
                    return
                try:
                    animes = gen._animes_by_ids(sub)
                except _api.AnimePackApiError as e:
                    gen.log(f"Shikimori: {e} — пропускаю пачку")
                    continue
                gen._load_franchise_indexes(animes)
                for anime in animes:
                    mal = _mal_of_card(anime)
                    if not mal:
                        continue
                    songs = by_mal.get(mal) or []
                    row = (anime, mal, songs, list(siblings.get(mal, ())))
                    queue = self.with_song if songs else self.no_song
                    self._arrived += 1
                    self._walked += 1
                    self._songful += bool(songs)
                    queue.append((self._arrived, row))
                yield True

    def _next_queue(self, song_stream, needed):
        """Очередь, из которой поток берёт следующую карточку (или None).

        Песни нужны — песенный поток ждёт карточку с песней. Во всех остальных
        случаях карточка берётся из общего порядка каталога."""
        if song_stream and needed:
            return self.with_song or None
        first, second = self.with_song, self.no_song
        if needed and not song_stream and not self._song_supply_ok():
            first = None
        if first and second:
            return first if first[0][0] < second[0][0] else second
        return first or second or None

    def _song_supply_ok(self) -> bool:
        """Хватит ли песенных тайтлов, если один из них отдать под кадр."""
        left = int(getattr(self.gen, "_song_slots_left", 0) or 0)
        if left <= 0:
            return True
        ratio = self._songful / self._walked if self._walked else 0.0
        ahead = max(0, len(self.ids) - self._walked) * ratio
        return len(self.with_song) - 1 + ahead >= SONG_SUPPLY_MARGIN * left

    def _rows(self, song_stream):
        """После набора песен оба потока обслуживают оставшиеся карточки.

        Потребность проверяется между пачками: перераспределение квот может
        снова потребовать песни. ANN по-прежнему нужен для получения MAL id.
        """
        while not self.gen.stopped():
            needed = self._songs_needed()
            queue = self._next_queue(song_stream, needed)
            if queue:
                yield queue.popleft()[1], needed
                continue
            if self.done:
                if self._requeue_held():
                    continue
                if self.held and _selection_busy(self.gen):
                    # Серии отложенных держат качающиеся вопросы: ждём их
                    # исхода, не мешая остальным потокам (см. _merge_streams).
                    yield None, needed
                    continue
                return
            if next(self._source, _EMPTY) is _EMPTY:
                self.done = True

    # ── кандидаты ────────────────────────────────────────────────────────
    def _candidates(self, row, kind, used_franchise, with_song=True):
        """Карточка → кандидаты. Фильтры и бронь франшизы — здесь, а не в
        производителе: карточка, застрявшая в очереди, не должна держать за
        собой всю серию."""
        gen = self.gen
        anime, mal, songs, siblings = row
        from .song_supply import ordered_songs
        songs, music_needed = ordered_songs(gen, songs)
        if music_needed:
            with_song = True
        if not with_song:
            songs = []
        if not gen._accept_anime(anime, mal, self.used_anime, used_franchise):
            if getattr(gen, "_last_reject", "") == "franchise":
                from si_hyx_parts.animepack.generator_catalog import _franchise_marks
                self.held.append((tuple(_franchise_marks(anime)), row))
            return
        reserved = gen._last_reserved
        users = list(self.users_by_id.get(mal, ()))
        if not songs:
            cand = _api.SongCandidate(
                song={}, anime=anime, kind=kind, users=users,
                franchise_index=gen._franchise_index(anime),
                favorites=_known_favorites(gen, anime),
                compress_images=gen.s.compress_images)
            cand._reserved = reserved
            yield cand
            return
        picked = songs if gen.s.dup_anime else songs[:1]
        for song in picked:
            cand = _api.SongCandidate(
                song=song, anime=anime, users=users,
                kind=_api.song_kind(song.get("songType")) or "opening",
                trim_start=gen._trim_start(song),
                franchise_index=gen._franchise_index(anime),
                favorites=_known_favorites(gen, anime),
                compress_audio=gen.s.compress_audio,
                compress_images=gen.s.compress_images,
                siblings=list(siblings))
            # Бронь на серию одна на весь тайтл: при разрешённых дублях песен
            # её держит первая из них.
            cand._reserved, reserved = reserved, None
            if not gen.s.dup_anime:
                cand._song_alternatives = list(songs[1:])
            yield cand

    def _requeue_held(self) -> bool:
        """Вернуть в очередь отложенные тайтлы, чья серия освободилась."""
        gen = self.gen
        releases = getattr(gen, "_franchise_releases", 0)
        if not self.held or releases == self._held_releases:
            return False
        self._held_releases = releases
        with gen._studio_lock:
            used = set(gen._used_franchise)
        free = [(marks, row) for marks, row in self.held
                if not any(mark in used for mark in marks if mark)]
        if not free:
            return False
        back = {id(row) for _marks, row in free}
        self.held = [item for item in self.held if id(item[1]) not in back]
        for _marks, row in free:
            # Первая попытка уже посчитана в журнале как «франшиза уже в паке».
            gen._seen_titles -= 1
            gen._seen_by_media["anime"] -= 1
            gen._skips["франшиза уже в паке"] -= 1
            queue = self.with_song if row[2] else self.no_song
            self._arrived += 1
            queue.append((self._arrived, row))
        return True

    # ── потоки ───────────────────────────────────────────────────────────
    def songs(self, used_franchise):
        """Кандидаты с песней, прошедшей filter_song."""
        from .manga_plan_prefetch import PENDING
        for row, needed in self._rows(True):
            if row is None:
                yield PENDING
                continue
            kind = "" if needed else self.gen._silent_kind()
            if kind is not None:
                yield from self._candidates(row, kind, used_franchise)

    def pictures(self, kind, used_franchise):
        """Непесенные кандидаты из всего каталога: кадры, персонажи, сюжет…

        Песня у карточки может быть: в непесенный вопрос она не попадёт
        (кандидат строится без неё).

        Род вопроса тут лишь первый по списку: `_pick_kind` переставит его по
        недобранным квотам."""
        from .manga_plan_prefetch import PENDING
        for row, _needed in self._rows(False):
            if row is None:
                yield PENDING
                continue
            yield from self._candidates(row, kind, used_franchise, with_song=False)


def _selection_busy(gen) -> bool:
    """Идёт отбор, и у части кандидатов исход ещё неизвестен: качаются, ждут
    потока или лежат в окне источника (см. select_songs)."""
    waits = getattr(gen, "_selection_waits", None)
    return bool(waits and waits())


AnimeCardFeed.__module__ = _api.__name__
_api.AnimeCardFeed = AnimeCardFeed
