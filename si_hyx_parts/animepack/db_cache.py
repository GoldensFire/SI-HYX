# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Кэш базы Shikimori на диске и подпись фильтров каталога. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


# Части базы, которые панель показывает и обновляет по отдельности.
DB_PARTS = ("anime", "manga", "remanga", "mangalib", "favorites", "franchises", "extras")

# Как часть базы называется в журнале вкладки.
DB_PART_NAMES = {"anime": "каталог аниме", "manga": "каталог манги",
                 "remanga": "популярность ReManga", "mangalib": "популярность MangaLib",
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


def db_refresh_parts(parts=None, settings=None) -> tuple:
    """Какие части обновлять: приводит просьбу панели к набору имён.

    None — все собираемые разделы, независимо от состава пака и фильтров.
    settings оставлен для совместимости и не влияет на выбор разделов.
    Хвосты генерации не очищаются при обновлении всей базы."""
    if parts is None:
        return tuple(part for part in DB_PARTS if part != "extras")
    if isinstance(parts, str):
        parts = [parts]
    return tuple(p for p in DB_PARTS if p in {str(x) for x in parts})

db_refresh_parts.__module__ = _api.__name__
_api.db_refresh_parts = db_refresh_parts
_api.DB_PARTS = DB_PARTS
_api.DB_PART_NAMES = DB_PART_NAMES
_api.EXTRA_MEMO_GROUPS = EXTRA_MEMO_GROUPS
_api.FAVORITES_MEMO_GROUPS = FAVORITES_MEMO_GROUPS


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
        # Экземпляры с одним файлом делят замки и разобранное содержимое
        # (db_cache_shared): пак в очереди не разбирает базу заново.
        from .db_cache_shared import entry
        self._shared = entry(self.path)
        self._lock = self._shared["lock"]
        self._save_lock = self._shared["save_lock"]
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
            from .db_cache_shared import publish, reuse
            self._stamp = self.file_stamp()
            known = reuse(self._shared, self._stamp)
            if known is not None:
                self._data = known
                return known
            try:
                raw = load_file(self.path)
            except Exception:  # noqa: BLE001 — кэша может не быть вовсе
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            for key in ("anime", "manga", "franchises", "memo"):
                if not isinstance(raw.get(key), dict):
                    raw[key] = {}
            from .db_memo_migration import attach
            attach(self, raw)
            self._data = raw
            publish(self._shared, raw, self._stamp)
        return self._data

    def save(self) -> bool:
        """Сбрасывает накопленное на диск (без изменений — ничего не делает)."""
        # Разные источники сохраняют один файл: снимок и замену сериализуем.
        with self._save_lock:
            return self._save()

    def _save(self) -> bool:
        with self._lock:
            if self._data is None:
                return False
            if not self._dirty:
                from .db_memo_migration import memo_saved
                return memo_saved(self)
            # Рабочие потоки одновременно дописывают memo и карточки. Нельзя
            # отдавать json.dump живую ссылку: он обходит словари уже без
            # замка и падает с ``dictionary changed size during iteration``.
            # Кусками (db_json): json.dumps всей базы держал GIL секунды.
            from .db_json import dump_parts
            from .db_memo_migration import prepare
            payload = dump_parts(prepare(self))
            self._dirty = False
        try:
            _api.os.makedirs(_api.os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for part in payload:
                    f.write(part)
            _api.os.replace(tmp, self.path)
            from .db_cache_shared import publish
            with self._lock:
                self._stamp = self.file_stamp()
                publish(self._shared, self._data, self._stamp)
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
            store = self._shared.get("memo_store")
            if store is not None:
                store.clear()
            self._data = {"anime": {}, "manga": {}, "franchises": {},
                          "memo": {}}
            self._dirty = False
            from .db_cache_shared import publish
            publish(self._shared, None, None)
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

    def add_cards(self, target: str, signature: str, cards, *, next_page=None) -> int:
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
            filtered = [k for k in group if k != _api.SHIKIMORIHYX_BUCKET]
            if len(filtered) > _api.SHIKI_CACHE_BUCKETS:
                # При равных размерах «самым большим» считается свежий мешок:
                # он и так не старейший, и порядок выбывания не меняется.
                biggest = max(filtered, key=lambda k: (
                    len((group.get(k) or {}).get("cards") or {}),
                    float((group.get(k) or {}).get("fetched") or 0.0)))
                old = sorted((k for k in filtered if k != biggest
                              and not (group.get(k) or {}).get("complete")),
                             key=lambda k: float((group.get(k) or {})
                                                 .get("fetched") or 0.0))
                for key in old[:len(filtered) - _api.SHIKI_CACHE_BUCKETS]:
                    group.pop(key, None)
            if next_page is not None:
                bucket["next_page"] = int(next_page)
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
            bucket["fetched"] = _api.time.time()
            self._dirty = True

    def catalog_cursor(self, target: str, signature: str) -> dict:
        with self._lock:
            bucket = (self._read().get(str(target)) or {}).get(str(signature)) or {}
            return {"next_page": int(bucket.get("next_page") or 1),
                    "complete": bool(bucket.get("complete"))}

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

    def memo_group(self, category: str) -> dict:
        """Все значения одной категории memo: {ключ: значение}."""
        with self._lock:
            group = (self._read().get("memo") or {}).get(str(category)) or {}
            rows = {str(key): row.get("value")
                    for key, row in group.items() if isinstance(row, dict)}
        return _api.json.loads(_api.json.dumps(rows, ensure_ascii=False))

    def memo_entries(self, category: str) -> dict:
        """Copied values and timestamps for maintenance freshness checks."""
        with self._lock:
            group = (self._read().get("memo") or {}).get(str(category)) or {}
            rows = dict(group.items())
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
            # Не `or {}`: у группы в SQLite проверка на пустоту — отдельный
            # запрос, а план книг спрашивает memo больше ста тысяч раз.
            rows = group.get(str(category))
            row = rows.get(str(key)) if rows is not None else None
            if not isinstance(row, dict) or "value" not in row:
                return None
            if max_age:
                age = _api.time.time() - float(row.get("fetched") or 0.0)
                if age > float(max_age):
                    return None
            from .db_memo_sqlite import MemoGroup
            if isinstance(rows, MemoGroup):
                return row["value"]     # строка только что разобрана из JSON
            # API values are JSON data. Copy through JSON so callers and
            # worker threads cannot mutate the shared in-memory cache.
            return _api.json.loads(_api.json.dumps(row["value"],
                                                   ensure_ascii=False))

    def memo_many(self, category: str, keys) -> dict:
        """memo для многих ключей сразу: {ключ: значение} найденных (без срока)."""
        from .db_memo_sqlite import MemoGroup
        with self._lock:
            rows = (self._read().get("memo") or {}).get(str(category))
            if rows is None:
                return {}
            shared = not isinstance(rows, MemoGroup)
            found = ({str(k): rows.get(str(k)) for k in keys} if shared
                     else rows.many(keys))
            values = {key: row["value"] for key, row in found.items()
                      if isinstance(row, dict) and "value" in row}
            if not shared:
                return values   # строки только что разобраны из JSON
            return _api.json.loads(_api.json.dumps(values, ensure_ascii=False))

    def remember_memo_many(self, category: str, values: dict) -> None:
        """remember_memo для многих ключей: в SQLite — одной транзакцией."""
        values = {str(k): v for k, v in (values or {}).items() if v is not None}
        if not values:
            return
        copied = _api.json.loads(_api.json.dumps(values, ensure_ascii=False))
        fetched = _api.time.time()
        rows = {key: {"fetched": fetched, "value": value} for key, value in copied.items()}
        from .db_memo_sqlite import MemoGroup
        with self._lock:
            groups = self._read().setdefault("memo", {})
            from .db_memo_migration import remember_group
            group = remember_group(self, groups, str(category))
            if isinstance(group, MemoGroup):
                group.update_many(rows)
            else:
                group.update(rows)
                self._dirty = True

    def remember_memo(self, category: str, key, value) -> None:
        """Store a small reusable API result next to the catalog cache."""
        if value is None:
            return
        copied = _api.json.loads(_api.json.dumps(value, ensure_ascii=False))
        with self._lock:
            groups = self._read().setdefault("memo", {})
            from .db_memo_migration import remember_group
            group = remember_group(self, groups, str(category))
            group[str(key)] = {"fetched": _api.time.time(), "value": copied}
            from .db_memo_sqlite import MemoGroup
            if not isinstance(group, MemoGroup):
                self._dirty = True

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
                    store = self._shared.get("memo_store")
                    if store is not None:
                        store.clear_category(name)
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
