# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""db_cache_parts. Public namespace: animepack.

Кнопка «Обновить базу» была одна на всё: она забывала кэш целиком — и каталог
аниме, и мангу, и узнаваемость франшиз, и запомненные по одному ответы про
персонажей. Собирается это десятками минут, а обновить обычно нужно что-то
одно (просьба пользователя: «возможность раздельно обновить только аниме,
мангу или ещё что»). Здесь — чистка ОДНОЙ части базы и счётчики для панели
«Что в базе», по которым видно, из чего база вообще состоит.
"""
from __future__ import annotations
import animepack as _api

# Части базы, которые панель показывает и обновляет по отдельности.
DB_PARTS = ("anime", "manga", "favorites", "franchises", "extras")

# Как часть базы называется в журнале вкладки.
DB_PART_NAMES = {"anime": "каталог аниме", "manga": "каталог манги",
                 "favorites": "«в избранном»",
                 "franchises": "узнаваемость франшиз",
                 "extras": "хвосты кэша"}

# «В избранном» — своя часть базы, а не хвост. Число живёт только на странице
# тайтла (в API Shikimori его нет вовсе), поэтому стоит запроса на тайтл, но
# собрать его МОЖНО — обходом каталога сверху вниз (см. favorites_sweep).
# Раньше оно лежало среди хвостов, и «Забыть» уносило часы сбора вместе с
# кадрами и персонажами.
FAVORITES_MEMO_GROUPS = ("anime_favorites", "manga_favorites")

# «Хвосты» кэша: они копятся не обходом каталога, а генерациями — состав
# персонажей, их избранное, ссылки на кадры. Своей кнопки «собрать» у них нет и
# быть не может: спрашиваются они тогда, когда тайтл дошёл до вопроса. Поэтому
# «обновить» для них значит «забыть»: спросится заново по ходу генерации.
EXTRA_MEMO_GROUPS = ("character_favorites", "characters", "character_titles",
                     "anime_themes", "frame_urls", "title_eligibility_v1")


def _bucket_keys(group) -> set:
    """Ключи карточек мешка фильтров, схлопнутые по MAL id."""
    keys: set = set()
    for bucket in (group or {}).values():
        if isinstance(bucket, dict):
            keys |= set((bucket.get("cards") or {}).keys())
    return keys


def _buckets_fetched(group) -> float:
    """Когда этот раздел каталога трогали в последний раз (0 — никогда)."""
    out = 0.0
    for bucket in (group or {}).values():
        if isinstance(bucket, dict):
            try:
                out = max(out, float(bucket.get("fetched") or 0.0))
            except (TypeError, ValueError):
                continue
    return out


def clear_part(self, part: str) -> int:
    """Забыть ОДНУ часть базы. Возвращает, сколько записей унесло.

    Остальные части при этом не трогаются: обновить каталог аниме, не потеряв
    мангу, франшизы и запомненное «в избранном», — ровно то, ради чего части
    и разведены."""
    part = str(part)
    with self._lock:
        data = self._read()
        if part in ("anime", "manga"):
            gone = len(_bucket_keys(data.get(part)))
            data[part] = {}
        elif part == "franchises":
            gone = len(data.get("franchises") or {})
            data["franchises"] = {}
        elif part in ("extras", "favorites"):
            groups = (FAVORITES_MEMO_GROUPS if part == "favorites"
                      else EXTRA_MEMO_GROUPS)
            memo = data.setdefault("memo", {})
            gone = 0
            for name in groups:
                gone += len(memo.get(name) or {})
                memo.pop(name, None)
        else:
            return 0
        self._dirty = True
    return gone


def reload(self) -> None:
    """Забыть прочитанное: тот же файл мог обновить другой держатель кэша.

    Панель «Что в базе» смотрит в базу своим экземпляром, а собирает её
    генератор — своим. Без этого панель показывала бы вчерашние числа, пока
    её не закроют."""
    with self._lock:
        if self._dirty:                  # своё несохранённое терять нельзя
            return
        # Файл не менялся с прочтения — перечитывать нечего: разбор базы
        # стоит секунды, а панель зовёт reload на каждом открытии.
        if self._data is not None and self._stamp is not None                 and self._stamp == self.file_stamp():
            return
        self._data = None


def replace_title_card(self, target: str, card: dict) -> bool:
    """Заменить одну карточку во всех мешках, где она уже присутствует.

    Ключ мешка — MAL id, а точечный запрос выполняется по Shikimori id,
    поэтому совпадение проверяем по обоим. Новую карточку копируем: рабочий
    поток API не должен получить ссылку на изменяемое содержимое кэша.
    """
    if not isinstance(card, dict):
        return False
    try:
        shiki = int(card.get("id") or 0)
        mal = int(card.get("malId") or shiki)
    except (TypeError, ValueError):
        return False
    if shiki <= 0 or mal <= 0:
        return False
    copied = _api.json.loads(_api.json.dumps(card, ensure_ascii=False))
    replaced = False
    with self._lock:
        group = self._read().get(str(target)) or {}
        for bucket in group.values():
            if not isinstance(bucket, dict):
                continue
            store = bucket.get("cards") or {}
            matches = []
            for key, old in store.items():
                if not isinstance(old, dict):
                    continue
                try:
                    old_shiki = int(old.get("id") or 0)
                    old_mal = int(old.get("malId") or old_shiki)
                except (TypeError, ValueError):
                    continue
                if old_shiki == shiki or old_mal == mal:
                    matches.append(str(key))
            if not matches:
                continue
            for key in matches:
                store.pop(key, None)
            store[str(mal)] = copied
            bucket["fetched"] = _api.time.time()
            replaced = True
        if replaced:
            self._dirty = True
    return replaced


def part_counts(self) -> dict:
    """{часть: {"count": сколько, "fetched": когда трогали}} для панели."""
    with self._lock:
        data = self._read()
        anime = len(_bucket_keys(data.get("anime")))
        manga = len(_bucket_keys(data.get("manga")))
        anime_at = _buckets_fetched(data.get("anime"))
        manga_at = _buckets_fetched(data.get("manga"))
        franchises = len(data.get("franchises") or {})
        memo = data.get("memo") or {}
        extras, extras_at = _memo_count(memo, EXTRA_MEMO_GROUPS)
        favorites, favorites_at = _memo_count(memo, FAVORITES_MEMO_GROUPS)
    return {
        "anime": {"count": anime, "fetched": anime_at},
        "manga": {"count": manga, "fetched": manga_at},
        "favorites": {"count": favorites, "fetched": favorites_at},
        # У франшиз своей отметки времени нет: они прогреваются тем же
        # обходом каталога, что и карточки.
        "franchises": {"count": franchises, "fetched": 0.0},
        "extras": {"count": extras, "fetched": extras_at},
    }


def _memo_count(memo, groups) -> tuple:
    """(сколько ответов запомнено, когда трогали в последний раз)."""
    total, when = 0, 0.0
    for name in groups:
        rows = memo.get(name) or {}
        total += len(rows)
        for row in rows.values():
            if isinstance(row, dict):
                try:
                    when = max(when, float(row.get("fetched") or 0.0))
                except (TypeError, ValueError):
                    continue
    return total, when


def db_refresh_parts(parts, settings=None) -> tuple:
    """Какие части обновлять: приводит просьбу панели к набору имён.

    None — прежнее поведение кнопки «Обновить базу»: каталог аниме, каталог
    манги (если у пака есть книжная доля) и узнаваемость франшиз. «В избранном»
    и хвосты (персонажи, кадры) в этот набор не входят нарочно: они стоят
    запроса на штуку и живут между генерациями — терять их при каждом
    обновлении каталога незачем, для них в панели свои кнопки."""
    if parts is None:
        want = ["anime", "franchises"]
        if settings is None or getattr(settings, "manga_percent", 0):
            want.insert(1, "manga")
        return tuple(want)
    if isinstance(parts, str):
        parts = [parts]
    return tuple(p for p in DB_PARTS if p in {str(x) for x in parts})

db_refresh_parts.__module__ = _api.__name__
_api.db_refresh_parts = db_refresh_parts
_api.DB_PARTS = DB_PARTS
_api.DB_PART_NAMES = DB_PART_NAMES
_api.EXTRA_MEMO_GROUPS = EXTRA_MEMO_GROUPS
_api.FAVORITES_MEMO_GROUPS = FAVORITES_MEMO_GROUPS
