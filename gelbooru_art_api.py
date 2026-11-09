# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Арты с Gelbooru — тот же вопрос «Арт», что и с Pixiv, другой источник.

Отбор нарочно общий с Pixiv (клиент наследует PixivArtClient): режимы R-18 и
ИИ, планка «лайков», однополые пары, исключаемые метки, чужие франшизы и
сборки по нескольким тайтлам. Меняется только то, откуда приходят работы:

* тайтл ищется по метке-«копирайту» Gelbooru (`kimetsu_no_yaiba`), которую
  сначала находим по ромадзи-названию карточки через API меток;
* «лайк» — это score поста, планка уходит прямо в запрос (`score:>=N`),
  выдача сортируется по нему же; планка не выше GELBOORU_MIN_SCORE;
* R-18 — рейтинг поста: questionable и explicit; ИИ — метка ai-generated.

API Gelbooru без ключа отвечает 401, поэтому нужна строка
«&api_key=…&user_id=…» со страницы настроек аккаунта (Настройки → Ключи API).
"""
from __future__ import annotations

import html
import io
import re
import threading
import time
from urllib.parse import urlsplit

from pixiv_art_api import (CHOICE_POOL, MIN_CHOICES, MIN_SIDE, PixivArtClient,
                           PixivArtError, PixivArtUnavailable, _image_extension)
from pixiv_art_match import conflicting_series
from pixiv_auth import PixivNetworkError
from pixiv_titles import MIN_TITLE_TAG, norm_title

API_URL = "https://gelbooru.com/index.php"
POST_LINK = "https://gelbooru.com/index.php?page=post&s=view&id={}"
SOURCE_NAME = "Gelbooru"
# Постов на страницу (больше Gelbooru не отдаёт) и сколько страниц листать,
# пока не наберётся пул для случайного выбора.
PAGE_SIZE = 100
SEARCH_PAGES = 3
TIMEOUT = 20
MAX_IMAGE_BYTES = 32 * 1024 * 1024
# Сколько секунд ждать оригинал, если есть уменьшенная копия. Оригиналы
# Gelbooru бывают PNG по 15–30 МБ и качаются по 40 с, а копия — за секунду.
ORIGINAL_BUDGET = 15
# Тип метки «копирайт» (название произведения) в API меток Gelbooru.
COPYRIGHT_TYPE = 3
# Уточнения в метках-копирайтах, совпавших с другой меткой.
DISAMBIGUATION = ("anime", "manga", "series", "copyright")
# Планка score у Gelbooru. Настройка «лайков» общая с Pixiv, а score
# Gelbooru на порядок скромнее закладок Pixiv: при 15 у тайтлов середины
# каталога не оставалось ни одного арта (у «Мёда и клевера» лучший — 5).
# Меньшая планка из настройки (вплоть до нуля) остаётся в силе.
GELBOORU_MIN_SCORE = 5
# Сколько меток спрашивать о типе одним запросом к API меток.
TYPE_BATCH = 50
ADULT_RATINGS = {"questionable", "explicit"}
AI_TAGS = {"ai-generated", "ai-assisted"}
# То, что у Pixiv отсекает тип работы и одностраничность: комиксы, анимация,
# фото и косплей живых людей. Вопросом такая картинка не бывает.
BLOCKED_TAGS = ("comic", "4koma", "animated", "video", "photo_(medium)",
                "cosplay", "real_life", "text-only_page")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# Сколько сетевых срывов подряд означают «Gelbooru лежит» (как у Pixiv).
DOWN_AFTER = 5
# API Gelbooru отвечает 429 уже на ~9 запросов в секунду: замерено, две
# одновременные очереди проходят чисто, четыре — нет. 429 — не «сервер лежит»,
# а «медленнее»: ждём и повторяем, в счёт срывов он не идёт.
API_PARALLEL = 2
RATE_LIMIT_WAITS = (1, 2, 4)


class GelbooruNetworkError(PixivNetworkError):
    """Gelbooru не ответил: тайтл не виноват, его можно повторить позже."""


def parse_credentials(text) -> tuple[str, str]:
    """(api_key, user_id) из строки со страницы настроек Gelbooru.

    Принимает и строку целиком («&api_key=…&user_id=…»), и два значения через
    пробел, двоеточие или точку с запятой в любом порядке."""
    raw = str(text or "").strip()
    key = re.search(r"api_key=([0-9A-Za-z]+)", raw)
    user = re.search(r"user_id=(\d+)", raw)
    if key and user:
        return key.group(1), user.group(1)
    parts = [p for p in re.split(r"[\s:;,&|]+", raw) if p]
    digits = [p for p in parts if p.isdigit()]
    others = [p for p in parts if not p.isdigit() and p.isalnum()]
    if len(digits) == 1 and len(others) == 1:
        return others[0], digits[0]
    return "", ""


def validate_settings(credentials) -> list[str]:
    if all(parse_credentials(credentials)):
        return []
    return ["Арты Gelbooru: добавьте ключ API Gelbooru в Настройках → Ключи API "
            "(строка «&api_key=…&user_id=…» со страницы gelbooru.com → "
            "My Account → Options)."]


def _is_gelbooru_host(url: str) -> bool:
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parts.hostname or "").casefold().rstrip(".")
    return (parts.scheme == "https"
            and (host == "gelbooru.com" or host.endswith(".gelbooru.com")))


def tag_variants(word: str) -> list[str]:
    """Возможные метки-копирайты для названия: «Sousou no Frieren» →
    sousou_no_frieren. Метки Gelbooru — латиница; японское и русское
    название меткой не бывают."""
    base = " ".join(str(word or "").split()).casefold()
    if not base or not base.isascii():
        return []
    out = []
    # Подзаголовок после двоеточия у Gelbooru обычно не метка: продолжения
    # и спин-оффы висят на метке основного названия (Jinki:Extend → jinki).
    # Так же «… the Animation» / «… the Movie»: ARIA the Animation → aria_(manga).
    heads = tuple(h for h in {base.split(":", 1)[0].strip(),
                              re.sub(r"\s+the\s+(?:animation|movie)$", "", base)}
                  if h != base and len(h) >= MIN_TITLE_TAG)
    for text in (base, re.sub(r"[,.:\"]+", " ", base)) + tuple(sorted(heads)):
        tag = "_".join(text.split())
        if tag and tag not in out:
            out.append(tag)
    # Совпадающее с обычным словом название Gelbooru пишет с уточнением:
    # zipang_(anime), а просто zipang — не метка. Уточнения идут тем же
    # запросом меток, лишнего обращения к сети нет.
    return out + [f"{tag}_({kind})" for tag in out for kind in DISAMBIGUATION]


def _post_link(post_id) -> str:
    try:
        number = int(post_id or 0)
    except (TypeError, ValueError):
        return ""
    return POST_LINK.format(number) if number > 0 else ""


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


class GelbooruArtClient(PixivArtClient):
    """Поиск артов на Gelbooru с отбором PixivArtClient."""

    source_name = SOURCE_NAME

    def __init__(self, credentials: str, *, session=None, stopped=None,
                 rng=None, r18_mode="", ai_mode="", allow_same_sex=False,
                 min_likes=None, known_titles=None, franchise_titles=None,
                 settings=None):
        super().__init__("", api=None, stopped=stopped, rng=rng,
                         r18_mode=r18_mode, ai_mode=ai_mode,
                         allow_same_sex=allow_same_sex, min_likes=min_likes,
                         known_titles=known_titles,
                         franchise_titles=franchise_titles, settings=settings)
        self.credentials = str(credentials or "")
        self.min_likes = min(self.min_likes, GELBOORU_MIN_SCORE)
        self.session = session
        self._tags_memo: dict[str, str] = {}
        # Тип метки Gelbooru по имени (см. _resolve_types): общий на прогон.
        self._tag_types: dict[str, int] = {}
        self._network_failures = 0
        self._api_slots = threading.BoundedSemaphore(API_PARALLEL)

    # ── сеть ─────────────────────────────────────────────────────────────
    def _ensure_api(self):
        if self.stopped():
            raise PixivArtError("Загрузка арта Gelbooru остановлена.")
        errors = validate_settings(self.credentials)
        if errors:
            raise PixivArtUnavailable(" ".join(errors))
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers["User-Agent"] = "SI-HYX"

    def _network_failure(self, message: str):
        self._network_failures += 1
        if self._network_failures >= DOWN_AFTER:
            raise PixivArtUnavailable(
                f"{message}. Gelbooru не отвечает {DOWN_AFTER} раз подряд — "
                "арты Gelbooru в этом прогоне пропускаю.")
        raise GelbooruNetworkError(message + " — тайтл повторю позже.")

    def _call(self, params: dict) -> dict:
        """Запрос к API Gelbooru (JSON). Ключ уходит только сюда."""
        key, user = parse_credentials(self.credentials)
        query = {"page": "dapi", "q": "index", "json": "1",
                 "api_key": key, "user_id": user}
        query.update(params)
        for wait in RATE_LIMIT_WAITS + (None,):
            try:
                with self._api_slots:
                    answer = self.session.get(API_URL, params=query,
                                              timeout=TIMEOUT)
            except Exception as error:  # noqa: BLE001 — сеть, а не ключ
                text = " ".join(str(error).split())[:160].replace(key, "…")
                self._network_failure(f"Gelbooru не ответил: {text}")
            status = int(getattr(answer, "status_code", 0) or 0)
            if status != 429:
                break
            if wait is None or self.stopped():
                raise GelbooruNetworkError(
                    "Gelbooru просит запрашивать реже (HTTP 429) — тайтл "
                    "повторю позже.")
            time.sleep(wait)
        if status in (401, 403):
            raise PixivArtUnavailable(
                "Gelbooru не принял ключ API — проверьте строку "
                "«&api_key=…&user_id=…» в Настройках → Ключи API.")
        if status != 200:
            self._network_failure(f"Gelbooru ответил HTTP {status}")
        self._network_failures = 0
        try:
            data = answer.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ── метка тайтла ─────────────────────────────────────────────────────
    def _copyright_tag(self, word: str) -> str:
        """Метка-копирайт Gelbooru для названия («» — такой нет)."""
        variants = tag_variants(word)
        if not variants:
            return ""
        memo = variants[0]
        if memo in self._tags_memo:
            return self._tags_memo[memo]
        data = self._call({"s": "tag", "names": " ".join(variants)})
        best, best_count = "", 0
        for row in _as_list(data.get("tag")):
            try:
                kind = int(row.get("type", -1))
                count = int(row.get("count", 0) or 0)
            except (TypeError, ValueError):
                continue
            name = html.unescape(str(row.get("name") or ""))
            if kind == COPYRIGHT_TYPE and count > best_count and name:
                best, best_count = name, count
        self._tags_memo[memo] = best
        return best

    # ── чужой тайтл на арте ──────────────────────────────────────────────
    def _title_like(self, illust, own: set) -> set[str]:
        """Метки работы, совпавшие с названием другого тайтла каталога."""
        known = self.known_titles()
        if not known:
            return set()
        out = set()
        for name in self._tag_names(illust):
            word = norm_title(name)
            if len(word) >= MIN_TITLE_TAG and word not in own and word in known:
                out.add(name)
        return out

    def _resolve_types(self, names) -> None:
        """Узнаёт тип меток пачками и запоминает до конца прогона.

        Метки поста Gelbooru приходят строкой, без типа, а обычные метки
        («ponytail», «beach», «flower», «monster») совпадают с названиями
        тайтлов Shikimori. Считать их чужой франшизой нельзя: так отсеивался
        почти каждый пост, и пак из 18 артов собирался два часа с одним
        вопросом в итоге. Сбой сети оставляет тип неизвестным — такая метка
        считается чужим тайтлом, как раньше."""
        todo = sorted(n for n in set(names) if n not in self._tag_types)
        for start in range(0, len(todo), TYPE_BATCH):
            batch = todo[start:start + TYPE_BATCH]
            try:
                data = self._call({"s": "tag", "names": " ".join(batch),
                                   "limit": str(len(batch))})
            except GelbooruNetworkError:
                return
            for row in _as_list(data.get("tag")):
                name = html.unescape(str(row.get("name") or "")).casefold()
                try:
                    self._tag_types[name] = int(row.get("type", -1))
                except (TypeError, ValueError):
                    continue
            # Метки, которых API не вернул, не копирайт: иначе одна странная
            # метка спрашивалась бы заново на каждой странице.
            for name in batch:
                self._tag_types.setdefault(name, -1)

    def _foreign_title(self, illust, own: set) -> bool:
        """Чужой тайтл на Gelbooru — только метка-копирайт другого тайтла."""
        names = self._title_like(illust, own)
        if not names:
            return False
        self._resolve_types(names)
        return any(self._tag_types.get(name, COPYRIGHT_TYPE) == COPYRIGHT_TYPE
                   for name in names)

    # ── отбор (переопределяет Pixiv) ─────────────────────────────────────
    @staticmethod
    def _url(illust) -> str:
        return str((illust or {}).get("file_url") or "")

    def _good_enough(self, illust) -> bool:
        try:
            side = min(int(illust.get("width") or 0), int(illust.get("height") or 0))
            score = int(illust.get("score") or 0)
        except (TypeError, ValueError, AttributeError):
            return False
        return side >= MIN_SIDE and score >= self.min_likes

    def _safe(self, illust) -> bool:
        names = {str(t.get("name") or "") for t in illust.get("tags") or []}
        rating = str(illust.get("rating") or "").casefold()
        url = self._url(illust).split("?")[0].casefold()
        return (url.endswith(IMAGE_EXTS)
                and not names & set(BLOCKED_TAGS)
                and self._mode_ok(self.r18_mode, rating in ADULT_RATINGS)
                and self._mode_ok(self.ai_mode, bool(names & AI_TAGS))
                and not self._blocked_tag(illust))

    @staticmethod
    def _illust(post: dict) -> dict:
        """Пост Gelbooru в виде работы, понятном отбору и проверке Gemini."""
        tags = html.unescape(str(post.get("tags") or "")).split()
        return {"id": post.get("id"), "tags": [{"name": t} for t in tags],
                "width": post.get("width"), "height": post.get("height"),
                "score": post.get("score"), "total_bookmarks": post.get("score"),
                "rating": post.get("rating"),
                "file_url": str(post.get("file_url") or ""),
                "sample_url": str(post.get("sample_url") or "")}

    def _filters(self) -> list[str]:
        out = ["sort:score:desc"]
        if self.min_likes:
            out.append(f"score:>={self.min_likes}")
        if self.r18_mode == "exclude":
            out += ["-rating:questionable", "-rating:explicit"]
        elif self.r18_mode == "only":
            out += ["-rating:general", "-rating:sensitive"]
        if self.ai_mode == "exclude":
            out.append("-ai-generated")
        elif self.ai_mode == "only":
            out.append("ai-generated")
        out += ["-" + tag for tag in BLOCKED_TAGS]
        return out

    def _search_tag(self, tag: str, keep, own: set = frozenset()) -> list:
        query = " ".join([tag] + self._filters())
        out, seen = [], set()
        for page in range(SEARCH_PAGES):
            if self.stopped():
                break
            data = self._call({"s": "post", "tags": query,
                               "limit": str(PAGE_SIZE), "pid": str(page)})
            fresh = []
            for post in _as_list(data.get("post")):
                row = self._illust(post)
                mark = self._url(row) or str(row.get("id") or "")
                if mark and mark not in seen:
                    seen.add(mark)
                    fresh.append(row)
            self._count(fresh, self.stats)
            # Типы подозрительных меток всей страницы — одним-двумя
            # запросами, а не по запросу на пост.
            self._resolve_types(set().union(
                *(self._title_like(row, own) for row in fresh)))
            out += [row for row in fresh if keep(row)]
            if (len(fresh) < PAGE_SIZE
                    or sum(1 for r in out if self._good_enough(r)) >= MIN_CHOICES):
                break
        if out:
            self.last_query = query
        return out

    def _count(self, rows, stats: dict) -> None:
        for row in rows:
            stats["rows"] = stats.get("rows", 0) + 1
            if str(row.get("rating") or "").casefold() in ADULT_RATINGS:
                stats["r18"] = stats.get("r18", 0) + 1
            if {t.get("name") for t in row.get("tags") or []} & AI_TAGS:
                stats["ai"] = stats.get("ai", 0) + 1

    def fetch(self, anime: dict, excluded=(), *,
              also=(), skip_links=()) -> tuple[bytes, str, str]:
        _url, load = self.choose(anime, excluded, also=also,
                                 skip_links=skip_links)
        return load()

    def prepare(self, anime: dict, also=()) -> None:
        """Находит метки тайтла заранее, без общего замка генератора.

        У большинства тайтлов из середины каталога метки на Gelbooru нет, и
        отказ по ним — это только запрос к API меток. Раньше и он шёл под
        замком артов, по одному на все потоки."""
        self._ensure_api()
        for _source, word in self._titles(anime, *also):
            if self._copyright_tag(word):
                return
        raise PixivArtError("метки этого тайтла на Gelbooru нет")

    def choose(self, anime: dict, excluded=(), *, also=(), skip_links=()):
        """Выбор работы без загрузки: (адрес, load), load() → fetch().

        Генератор выбирает и бронирует арт под общим замком, а качает уже без
        него: загрузка оригинала — секунды, а то и десятки секунд, и раньше
        все потоки артов стояли в очереди за одной картинкой."""
        with self._lock:
            self._ensure_api()
            blocked = {str(url).split("?")[0] for url in excluded}
            skip = {str(link).casefold() for link in skip_links}
            own = self.own_titles((anime,) + tuple(also))

            def keep(row) -> bool:
                url = self._url(row)
                return (bool(url) and url.split("?")[0] not in blocked
                        and (not skip or _post_link(row.get("id")) not in skip)
                        and self._safe(row)
                        and not conflicting_series(self._tag_names(row), own)
                        and not self._foreign_title(row, own))

            rows, matched_cards, tried = [], {}, set()
            for source, word in self._titles(anime, *also):
                tag = self._copyright_tag(word)
                if not tag or tag in tried:
                    continue
                tried.add(tag)
                # Метка, по которой ищем, — название этого же тайтла, даже
                # если в карточке оно записано иначе (знаки, порядок слов).
                own.add(norm_title(tag))
                found = self._search_tag(tag, keep, own)
                for row in found:
                    matched_cards.setdefault(self._url(row), source)
                rows = self._merge(rows, found)
                if any(self._good_enough(row) for row in found):
                    break
            if not tried:
                raise PixivArtError("метки этого тайтла на Gelbooru нет")
            rows.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
            pool = [row for row in rows if self._good_enough(row)][:CHOICE_POOL]
            if not pool:
                raise PixivArtError(
                    "подходящих артов по метке не найдено"
                    + (f" (работ {len(rows)}, но ни одной со score от "
                       f"{self.min_likes})" if rows and self.min_likes else ""))
            row = self.rng.choice(pool)
            url = self._url(row)
            self.last_card = matched_cards.get(url, anime)
            self.last_link = _post_link(row.get("id"))
            self.last_illust = row
        return url, lambda: self._load(row)

    def _load(self, row) -> tuple[bytes, str, str]:
        url = self._url(row)
        sample = str(row.get("sample_url") or "")
        data = (self._download(url, ORIGINAL_BUDGET if sample else None)
                or self._download(sample))
        if not data:
            raise PixivArtError("картинка не скачалась")
        return data, _image_extension(data, SOURCE_NAME), url

    def _download(self, url, budget=None) -> bytes:
        """Картинка с сервера Gelbooru; b"" — не вышло, слишком большая
        или не уложилась в budget секунд."""
        if not _is_gelbooru_host(url):
            return b""
        deadline = None if budget is None else time.monotonic() + budget
        try:
            with self.session.get(url, stream=True, timeout=TIMEOUT,
                                  headers={"Referer": "https://gelbooru.com/"}) as answer:
                if int(getattr(answer, "status_code", 0) or 0) != 200:
                    return b""
                buf = io.BytesIO()
                for chunk in answer.iter_content(256 * 1024):
                    if self.stopped() or (deadline is not None
                                          and time.monotonic() > deadline):
                        return b""
                    buf.write(chunk)
                    if buf.tell() > MAX_IMAGE_BYTES:
                        return b""
                return buf.getvalue()
        except Exception:  # noqa: BLE001 — сеть: попробуем уменьшенную копию
            return b""

    def summary(self) -> str:
        rows = int(self.stats.get("rows", 0) or 0)
        if not rows:
            return ""
        r18 = int(self.stats.get("r18", 0) or 0)
        ai = int(self.stats.get("ai", 0) or 0)
        head = (f"Gelbooru прислал {rows} работ: взрослых (questionable/"
                f"explicit) среди них {r18}, нарисованных нейросетью — {ai}.")
        if self.ai_mode == "only" and not ai:
            return (head + " Работ нейросети не пришло вовсе: у этих тайтлов "
                    "нет артов с меткой ai-generated. Поставьте ИИ-арты в "
                    "«Разрешать».")
        return head
