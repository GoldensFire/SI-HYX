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
двух очередей — «есть подходящая песня» и «песни нет»; потоки кандидатов тянут
каждый из своей, а общий производитель докручивает каталог по требованию. Та
же карточка второй раз с Shikimori не спрашивается, `used_anime` и брони
франшиз у обоих потоков общие.
"""
from __future__ import annotations
from collections import deque

import animepack as _api


_EMPTY = object()


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


class AnimeCardFeed:
    """Каталог аниме, разобранный один раз на два потока кандидатов."""

    def __init__(self, gen, pairs, want_songs: bool):
        self.gen = gen
        self.ids = [int(aid) for aid, _ in pairs]
        self.users_by_id = {int(aid): list(users) for aid, users in pairs}
        self.want_songs = bool(want_songs)
        # Разобранные карточки: (карточка, MAL id, подходящие песни, названия
        # всех песен тайтла). Первая очередь кормит песенные вопросы, вторая —
        # все остальные.
        self.with_song: deque = deque()
        self.no_song: deque = deque()
        # Тайтлы, уже ставшие кандидатом. Набор ОДИН на оба потока: иначе
        # пак выдал бы опенинг и кадр одного и того же аниме.
        self.used_anime: set[int] = set()
        self.done = False
        self._source = self._walk()

    # ── производитель ────────────────────────────────────────────────────
    def _ask_songs(self, batch):
        """Песни пачки. Возвращает (подходящие по id, все названия по id,
        MAL id пачки) либо None, если пачку пришлось пропустить."""
        gen = self.gen
        if not self.want_songs:
            return {}, {}, list(batch)
        gen.log(f"AnisongDB: спрашиваю песни для {len(batch)} аниме…")
        try:
            if gen._ids_are_ann:
                songs = gen.anisong.songs_by_ann_ids(batch)
            else:
                songs = gen.anisong.songs_by_mal_ids(batch)
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
        for batch in _api._chunks(self.ids, _api.ANISONG_BATCH):
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
                    queue.append(row)
                yield True

    def _fill(self, queue) -> bool:
        """Докручивает каталог, пока в очереди не появится карточка."""
        while not queue:
            if self.done or self.gen.stopped():
                return False
            if next(self._source, _EMPTY) is _EMPTY:
                self.done = True
        return True

    # ── кандидаты ────────────────────────────────────────────────────────
    def _candidates(self, row, kind, used_franchise):
        """Карточка → кандидаты. Фильтры и бронь франшизы — здесь, а не в
        производителе: карточка, застрявшая в очереди, не должна держать за
        собой всю серию."""
        gen = self.gen
        anime, mal, songs, siblings = row
        if not gen._accept_anime(anime, mal, self.used_anime, used_franchise):
            return
        reserved = gen._last_reserved
        users = list(self.users_by_id.get(mal, ()))
        if not songs:
            cand = _api.SongCandidate(
                song={}, anime=anime, kind=kind, users=users,
                franchise_index=gen._franchise_index(anime),
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
                compress_audio=gen.s.compress_audio,
                compress_images=gen.s.compress_images,
                siblings=list(siblings))
            # Бронь на серию одна на весь тайтл: при разрешённых дублях песен
            # её держит первая из них.
            cand._reserved, reserved = reserved, None
            yield cand

    # ── потоки ───────────────────────────────────────────────────────────
    def songs(self, used_franchise):
        """Кандидаты с песней, прошедшей filter_song."""
        while self._fill(self.with_song):
            yield from self._candidates(self.with_song.popleft(), "",
                                        used_franchise)

    def pictures(self, kind, used_franchise):
        """Кандидаты БЕЗ подходящей песни: кадры, персонажи, сюжет, арты…

        Род вопроса тут лишь первый по списку: `_pick_kind` переставит его по
        недобранным квотам."""
        while self._fill(self.no_song):
            yield from self._candidates(self.no_song.popleft(), kind,
                                        used_franchise)


AnimeCardFeed.__module__ = _api.__name__
_api.AnimeCardFeed = AnimeCardFeed
