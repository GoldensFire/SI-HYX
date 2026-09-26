# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _random_shikimori_ids. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


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
        want = max(50, self.s.total_questions * self.RANDOM_OVERSHOOT_MANGA)
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
    if len(ids) < want and not complete:
        self._fetch_random_cards(manga, want, sig, take, lambda: len(ids))
    if manga:
        # Манхва и маньхуа в общем каталоге почти не попадаются — их доли
        # добираются отдельным запросом (см. manga_catalog_topup.py).
        from .manga_catalog_topup import topup_editions
        topup_editions(self, sig, take)
    # Порядок случайный и внутри серии тоже (просьба пользователя): какой
    # сезон достанется паку, решает жребий, иначе одна и та же часть франшизы
    # попадалась бы из пака в пак. «Царство» приходило шестым сезоном не
    # из-за жребия, а потому что остальных сезонов в каталоге не было: до
    # кнопки «Обновить базу» он набирался обрывками (order: random) и целиком
    # не вычерпывался.
    self.rng.shuffle(ids)
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
        self.db_cache.save()
