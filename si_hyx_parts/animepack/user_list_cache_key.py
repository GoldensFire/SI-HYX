# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""user_list_cache_key. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def user_list_cache_key(source: str, username: str, statuses) -> tuple:
    """Ключ кэша: источник + ник без учёта регистра + набор статусов."""
    return (str(source or "").strip().lower(),
            str(username or "").strip().casefold(),
            tuple(sorted(str(s) for s in (statuses or []))))

user_list_cache_key.__module__ = _api.__name__
_api.user_list_cache_key = user_list_cache_key

def cached_user_list(key: tuple) -> _api.Optional[list[int]]:
    with _api._LISTS_LOCK:
        ids = _api._LISTS_CACHE.get(key)
    return list(ids) if ids is not None else None

cached_user_list.__module__ = _api.__name__
_api.cached_user_list = cached_user_list

def remember_user_list(key: tuple, ids) -> None:
    with _api._LISTS_LOCK:
        _api._LISTS_CACHE[key] = [int(i) for i in ids]

remember_user_list.__module__ = _api.__name__
_api.remember_user_list = remember_user_list

def clear_user_list_cache() -> None:
    """Забыть все запомненные списки (нужно тестам и кнопке «обновить»)."""
    with _api._LISTS_LOCK:
        _api._LISTS_CACHE.clear()

clear_user_list_cache.__module__ = _api.__name__
_api.clear_user_list_cache = clear_user_list_cache

# ─────────────────────────────────────────────────────────────────────────────
# Кэш каталога Shikimori (карточки случайной выборки + части франшиз)
# ─────────────────────────────────────────────────────────────────────────────
class ShikimoriDbCache:
    """Карточки каталога Shikimori и части франшиз, сохранённые на диск.

    Зачем: раньше каждая генерация «случайных из базы Shikimori» заново
    вычерпывала каталог постранично (order: random) и заново спрашивала
    узнаваемость франшиз — это и была та самая минута «поиска кандидатов».
    Теперь набранное лежит в файле и переживает перезапуск программы; обновляет
    его только кнопка «Обновить базу» (см. refresh_shikimori_db).

    Карточки хранятся МЕШКАМИ по набору фильтров, с которым их спрашивали
    (`signature`): выборка «ТВ, 2000–2010, оценка от 7» — совсем не то же самое,
    что «всё подряд», и подменять одну другой нельзя. Части франшиз общие: они
    от фильтров не зависят.
    """

    def __init__(self, path: _api.Optional[str] = None):
        # Путь берём в момент создания, а не значением по умолчанию: значения
        # аргументов вычисляются один раз при импорте, и тесты не смогли бы
        # увести кэш из настоящего %APPDATA% пользователя.
        self.path = path or _api.SHIKI_CACHE_FILE
        self._lock = _api.threading.Lock()
        self._data: _api.Optional[dict] = None
        self._dirty = False
        # Каким был файл, когда его прочли (время и размер): панель базы
        # перечитывает его, только если с тех пор файл и правда сменился.
        self._stamp = None

    # ── чтение/запись ─────────────────────────────────────────────────────
    def _read(self) -> dict:
        """Содержимое кэша (зовётся уже под замком)."""
        if self._data is None:
            # Порциями, а не json.load: разбор двухсот мегабайт одним вызовом
            # держал GIL секундами, и окно программы висело (см. db_json).
            from .db_json import load_file
            self._stamp = self.file_stamp()
            try:
                raw = load_file(self.path)
            except Exception:  # noqa: BLE001 — кэша может не быть вовсе
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            for key in ("anime", "manga", "franchises", "memo"):
                if not isinstance(raw.get(key), dict):
                    raw[key] = {}
            self._data = raw
        return self._data

    def save(self) -> bool:
        """Сбрасывает накопленное на диск (без изменений — ничего не делает)."""
        with self._lock:
            if not self._dirty or self._data is None:
                return False
            # Рабочие потоки одновременно дописывают memo и карточки. Нельзя
            # отдавать json.dump живую ссылку: он обходит словари уже без
            # замка и падает с ``dictionary changed size during iteration``.
            # Кусками (db_json): json.dumps всей базы держал GIL секунды.
            from .db_json import dump_parts
            payload = dump_parts(self._data)
            self._dirty = False
        try:
            _api.os.makedirs(_api.os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for part in payload:
                    f.write(part)
            _api.os.replace(tmp, self.path)
            with self._lock:
                self._stamp = self.file_stamp()
            return True
        except OSError:
            # Запись можно будет повторить; изменения, пришедшие после снимка,
            # уже сами выставили этот флаг и тоже не должны потеряться.
            with self._lock:
                self._dirty = True
            return False

    def file_stamp(self):
        """(время изменения, размер) файла базы или None, если его нет."""
        try:
            st = _api.os.stat(self.path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def clear(self) -> None:
        """Забыть всё: и карточки, и франшизы (кнопка «Обновить базу»)."""
        with self._lock:
            self._data = {"anime": {}, "manga": {}, "franchises": {},
                          "memo": {}}
            self._dirty = False
        try:
            _api.os.remove(self.path)
        except OSError:
            pass

    # ── карточки каталога ─────────────────────────────────────────────────
    def cards(self, target: str, signature: str) -> list[dict]:
        """Карточки, набранные с этим набором фильтров (пусто — не набирали)."""
        with self._lock:
            group = self._read().get(str(target)) or {}
            bucket = group.get(str(signature)) or {}
            stored = bucket.get("cards") if isinstance(bucket, dict) else None
            rows = list((stored or {}).values())
        return [c for c in rows if isinstance(c, dict)]

    def add_cards(self, target: str, signature: str, cards) -> int:
        """Кладёт карточки в мешок этого набора фильтров. Возвращает, сколько
        их стало всего."""
        with self._lock:
            group = self._read().setdefault(str(target), {})
            bucket = group.setdefault(str(signature), {})
            store = bucket.setdefault("cards", {})
            for card in cards:
                if not isinstance(card, dict):
                    continue
                try:
                    mal = int(card.get("malId") or card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if mal:
                    store[str(mal)] = card
            bucket["fetched"] = _api.time.time()
            # Самые старые наборы фильтров выбрасываем целиком — кроме
            # вычерпанных до конца и самого большого мешка: из них берутся
            # карточки и для фильтров поуже (catalog_superset), и потеря
            # полного каталога из-за пары правок фильтров стоила бы часа сбора.
            if len(group) > _api.SHIKI_CACHE_BUCKETS:
                # При равных размерах «самым большим» считается свежий мешок:
                # он и так не старейший, и порядок выбывания не меняется.
                biggest = max(group, key=lambda k: (
                    len((group.get(k) or {}).get("cards") or {}),
                    float((group.get(k) or {}).get("fetched") or 0.0)))
                old = sorted((k for k in group if k != biggest
                              and not (group.get(k) or {}).get("complete")),
                             key=lambda k: float((group.get(k) or {})
                                                 .get("fetched") or 0.0))
                for key in old[:len(group) - _api.SHIKI_CACHE_BUCKETS]:
                    group.pop(key, None)
            self._dirty = True
            return len(store)

    def buckets(self, target: str) -> dict:
        """{ключ фильтров: (карточки, вычерпан ли до конца)} раздела."""
        with self._lock:
            group = self._read().get(str(target)) or {}
            out = {}
            for sig, bucket in group.items():
                if not isinstance(bucket, dict):
                    continue
                rows = [c for c in (bucket.get("cards") or {}).values()
                        if isinstance(c, dict)]
                out[str(sig)] = (rows, bool(bucket.get("complete")))
        return out

    def is_complete(self, target: str, signature: str) -> bool:
        """Вычерпан ли мешок до конца (кнопкой «Обновить базу»)."""
        with self._lock:
            group = self._read().get(str(target)) or {}
            bucket = group.get(str(signature))
            return isinstance(bucket, dict) and bool(bucket.get("complete"))

    def mark_complete(self, target: str, signature: str) -> None:
        """Каталог под эти фильтры кончился: новых карточек сервер не даст."""
        with self._lock:
            group = self._read().setdefault(str(target), {})
            bucket = group.setdefault(str(signature), {})
            bucket["complete"] = True
            self._dirty = True

    def title_index(self) -> set:
        """Названия ВСЕХ аниме каталога в виде, сравнимом с метками Pixiv.

        Нужен ровно одному: отбору артов. Работа, подписанная названием
        тайтла, которого мы не искали, — это сборка сразу по нескольким
        сериалам, и вопросом она быть не может (см. pixiv_art_api).

        Мешки фильтров здесь не разделяем: чем больше названий известно, тем
        честнее проверка, а к отбору кандидатов этот набор отношения не имеет.
        """
        from pixiv_art_api import card_titles
        out: set = set()
        with self._lock:
            groups = self._read().get("anime") or {}
            rows = [card for bucket in groups.values()
                    if isinstance(bucket, dict)
                    for card in (bucket.get("cards") or {}).values()
                    if isinstance(card, dict)]
        for card in rows:
            out |= card_titles(card)
        out.discard("")
        return out

    def all_cards(self, target: str) -> list[dict]:
        """Все карточки каталога, какие есть, независимо от набора фильтров.

        Нужно окну «Что в базе»: там человек смотрит, какие тайтлы вообще
        набраны и с какой узнаваемостью, а не собирает по ним пак. Дубли
        схлопываются по MAL id — один тайтл мог попасть в несколько мешков."""
        with self._lock:
            groups = self._read().get(str(target)) or {}
            out = {str(key): card for bucket in groups.values()
                   if isinstance(bucket, dict)
                   for key, card in (bucket.get("cards") or {}).items()
                   if isinstance(card, dict)}
        return list(out.values())

    # Выборочная чистка частей базы и счётчики для панели «Что в базе».
    from si_hyx_parts.animepack.db_cache_parts import (clear_part, part_counts,
                                                       reload,
                                                       replace_title_card)

    def memo_group(self, category: str) -> dict:
        """Все значения одной категории memo: {ключ: значение}."""
        with self._lock:
            group = (self._read().get("memo") or {}).get(str(category)) or {}
            rows = {str(key): row.get("value")
                    for key, row in group.items() if isinstance(row, dict)}
        return _api.json.loads(_api.json.dumps(rows, ensure_ascii=False))

    # ── части франшиз ─────────────────────────────────────────────────────
    def franchise(self, key: str) -> _api.Optional[list]:
        """Карточки частей франшизы (None — не спрашивали)."""
        with self._lock:
            rows = (self._read().get("franchises") or {}).get(str(key))
        return list(rows) if isinstance(rows, list) else None

    def add_franchises(self, parts: dict) -> None:
        """Запоминает части франшиз. Пустой список тоже запоминаем: «у этой
        франшизы частей не нашлось» — такой же ответ, и спрашивать его снова
        каждую генерацию незачем."""
        if not isinstance(parts, dict) or not parts:
            return
        with self._lock:
            store = self._read().setdefault("franchises", {})
            for key, rows in parts.items():
                store[str(key)] = [r for r in (rows or []) if isinstance(r, dict)]
            self._dirty = True

    # ── редкие дополнительные данные карточки ──────────────────────────
    def memo(self, category: str, key, max_age: float = 0.0):
        """Persistent JSON value, or ``None`` when absent/expired."""
        with self._lock:
            group = self._read().get("memo") or {}
            row = (group.get(str(category)) or {}).get(str(key))
            if not isinstance(row, dict) or "value" not in row:
                return None
            if max_age:
                age = _api.time.time() - float(row.get("fetched") or 0.0)
                if age > float(max_age):
                    return None
            # API values are JSON data. Copy through JSON so callers and
            # worker threads cannot mutate the shared in-memory cache.
            return _api.json.loads(_api.json.dumps(row["value"],
                                                   ensure_ascii=False))

    def remember_memo(self, category: str, key, value) -> None:
        """Store a small reusable API result next to the catalog cache."""
        if value is None:
            return
        copied = _api.json.loads(_api.json.dumps(value, ensure_ascii=False))
        with self._lock:
            groups = self._read().setdefault("memo", {})
            group = groups.setdefault(str(category), {})
            group[str(key)] = {"fetched": _api.time.time(), "value": copied}
            self._dirty = True

ShikimoriDbCache.__module__ = _api.__name__
_api.ShikimoriDbCache = ShikimoriDbCache

def shiki_cache_signature(s: '_api.PackSettings', manga: bool = False) -> str:
    """Ключ мешка карточек: те же фильтры, что уходят в запрос к Shikimori.

    Ровно они и решают, какие карточки приедут (год, типы, оценка, исключённые
    жанры), поэтому мешок с одними фильтрами нельзя выдать за мешок с другими."""
    if manga:
        kinds = [k for k in _api.MANGA_KINDS if s.manga_kinds.get(k)]
    else:
        kinds = [k for k in _api.ANIME_KINDS if s.kinds.get(k)]
    excl = ",".join(str(int(g)) for g in sorted(s.genres_exclude or []))
    return (f"{int(s.year_from)}-{int(s.year_to)}|{','.join(kinds)}"
            f"|{int(s.score_from)}|{excl}")

shiki_cache_signature.__module__ = _api.__name__
_api.shiki_cache_signature = shiki_cache_signature

# ─────────────────────────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────────────────────────
@_api.dataclass
class UserList:
    """Один пользователь и его списки (карточка «Add List» в ASPG)."""
    username: str = ""
    source: str = "shikimori"            # shikimori | myanimelist | anilist
    statuses: list[str] = _api.field(
        default_factory=lambda: ["watching", "completed"])
    # Что берём из списка: аниме или мангу/ранобэ (у всех трёх сайтов это
    # отдельные разделы — см. LIST_TARGETS).
    target: str = "anime"
    # Доля вопросов пака, которую даёт ЭТОТ список, в процентах. 0 — «как
    # получится»: тогда порядок общий и большой список просто перевешивает
    # маленькие (у кого 1500 тайтлов, тот и заполнит пак). Ползунок на вкладке
    # раздаёт сотню между всеми списками.
    share: int = 0
    # «В основном музыка»: тайтлы из этого списка по возможности становятся
    # песенными вопросами, а не кадрами и персонажами. Нужно для списков, где
    # человек угадывает только музыку (просьба пользователя).
    prefer_music: bool = False

    def to_dict(self) -> dict:
        return {"username": self.username, "source": self.source,
                "statuses": list(self.statuses), "target": self.target,
                "share": int(self.share),
                "prefer_music": bool(self.prefer_music)}

    @classmethod
    def from_dict(cls, d: dict) -> '_api.UserList':
        d = d or {}
        st = [s for s in (d.get("statuses") or []) if s in _api.LIST_STATUSES]
        target = str(d.get("target") or "anime")
        try:
            share = max(0, min(100, int(d.get("share") or 0)))
        except (TypeError, ValueError):
            share = 0
        return cls(username=str(d.get("username") or "").strip(),
                   source=str(d.get("source") or "shikimori"),
                   statuses=st or ["watching", "completed"],
                   target=target if target in _api.LIST_TARGETS else "anime",
                   share=share,
                   prefer_music=bool(d.get("prefer_music")))

UserList.__module__ = _api.__name__
_api.UserList = UserList

def _current_year() -> int:
    return _api.date.today().year

_current_year.__module__ = _api.__name__
_api._current_year = _current_year
