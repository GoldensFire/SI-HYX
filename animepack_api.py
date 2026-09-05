# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# Логика вкладки «Генерация аниме-пака» портирована с разрешения автора из
# проекта ASPG (Anime Songs SiGame Pack Generator), Copyright (c) Leleath,
# лицензия MIT — https://github.com/Leleath/aspg
#
# animepack_api.py — сетевой слой генератора аниме-паков. Здесь НЕТ Qt: модуль
# чисто сетевой, его можно тестировать отдельно от GUI (сама вкладка —
# animepack_tab.py, отбор и сборка пака — animepack.py).
#
# Четыре внешних источника:
#   • AMQ (animemusicquiz.com/libraryMasterList) — вся база аниме, из которой
#     AMQ гоняет свою угадайку. Ответ ~16 МБ, поэтому кэшируется на диск.
#   • AnisongDB — песни (опенинги/эндинги/OST) по спискам MAL/ANN id.
#   • MyAnimeList — публичный список аниме пользователя (load.json).
#   • Shikimori — список пользователя (user_rates) и карточки аниме (GraphQL:
#     русское название, постер, скриншоты, жанры, франшиза, оценка).
#
# ВАЖНО, чем это отличается от оригинала ASPG (проверено живыми запросами):
#   • AnisongDB принимает тела в snake_case — {"mal_ids": […]} / {"ann_ids": […]}.
#     Старые camelCase-имена сервер молча принимает и отдаёт пустой список.
#   • Поля isDub / isRebroadcast теперь булевы, а не 0/1.
#   • Shikimori 301-редиректит .one → .io; requests на 301 превращает POST в GET
#     и теряет тело — за это отвечает ShikimoriApiClient._graphql (там редирект
#     обрабатывается вручную).
#   • Списки пользователей ПАГИНИРУЮТСЯ (и на MAL, и на Shikimori) — иначе
#     большие списки молча обрезаются.
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from config import CONFIG_DIR, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover — вне приложения (тесты модуля в одиночку)
    APP_NAME, APP_VERSION = "SI-HYX", "0.0"
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".unified_media_tool")

USER_AGENT = f"{APP_NAME}/{APP_VERSION} (+https://github.com/GoldensFire/SI-HYX)"

AMQ_BASE = "https://animemusicquiz.com"
AMQ_CDN = "https://naedist.animemusicquiz.com"
ANISONG_BASE = "https://anisongdb.com/api"
MAL_BASE = "https://myanimelist.net"
# AniList — публичный GraphQL без ключа и без регистрации (90 запросов в минуту).
# Весь список пользователя приезжает ОДНИМ запросом и сразу с MAL id, так что
# сводить каталоги не нужно.
ANILIST_BASE = "https://graphql.anilist.co"
# Kitsu — JSON:API без ключа. Нужен ради превью СЕРИЙ: у Shikimori кадров мало и
# почти все с первой серии, а Kitsu хранит миниатюру каждого эпизода.
KITSU_BASE = "https://kitsu.app/api/edge"
# AnimeThemes — ролики опенингов/эндингов, тоже без ключа. Видео там без
# кредитов (nc), то есть без названия прямо в кадре, — для угадайки это и нужно.
ANIMETHEMES_BASE = "https://api.animethemes.moe"
# Fandom — вики тайтлов, откуда берётся ПЕРЕСКАЗ СЮЖЕТА для вопросов «по
# сюжету». Работаем только через обычный MediaWiki api.php конкретной вики:
# каталог community.fandom.com и весь Fandom REST (/api/v1/…) закрыты проверкой
# Cloudflare и отвечают 403 (см. FandomApi).
FANDOM_HOST = "fandom.com"

# Кэш мастер-листа AMQ: ответ ~16 МБ, а меняется он раз в сутки.
AMQ_CACHE_PATH = os.path.join(CONFIG_DIR, "animepack_amq_library.json")
AMQ_CACHE_TTL = 24 * 3600

# Сколько id влезает в один запрос (AnisongDB держит и больше, но ответ пухнет).
ANISONG_BATCH = 300
# Shikimori GraphQL: жёсткий предел выборки animes(ids:…) — 50.
SHIKIMORI_BATCH = 50

# Статусы списков — единый внутренний словарь для обоих сайтов.
LIST_STATUSES = ("watching", "completed", "onhold", "dropped", "ptw")
STATUS_LABELS = {
    "watching": "Смотрю", "completed": "Просмотрено", "onhold": "Отложено",
    "dropped": "Брошено", "ptw": "Запланировано",
}
# Числовые статусы MAL из load.json.
_MAL_STATUS = {1: "watching", 2: "completed", 3: "onhold", 4: "dropped", 6: "ptw"}
# Строковые статусы Shikimori из /api/v2/user_rates.
_SHIKI_STATUS = {"watching": "watching", "rewatching": "watching",
                 "completed": "completed", "on_hold": "onhold",
                 "dropped": "dropped", "planned": "ptw"}
# Статусы AniList (MediaListStatus). REPEATING — это пересмотр, считаем «смотрю».
_ANILIST_STATUS = {"CURRENT": "watching", "REPEATING": "watching",
                   "COMPLETED": "completed", "PAUSED": "onhold",
                   "DROPPED": "dropped", "PLANNING": "ptw"}

# Shikimori идёт первым и по умолчанию: русские названия и статистика пака всё
# равно берутся оттуда, так что список с того же сайта совпадает точнее.
LIST_SOURCES = ("shikimori", "myanimelist", "anilist")
SOURCE_LABELS = {"myanimelist": "MyAnimeList", "shikimori": "Shikimori",
                 "anilist": "AniList"}

# Что именно берём из списка человека. Манга, манхва, манхуа и ранобэ — это ОДИН
# раздел на всех трёх сайтах (Shikimori target_type=Manga, MAL /mangalist,
# AniList type: MANGA), поэтому и у нас это один тип списка, а манхва/ранобэ
# отделяются потом фильтром «Типы» по полю kind карточки.
LIST_TARGETS = ("anime", "manga")
TARGET_LABELS = {"anime": "Аниме", "manga": "Манга/ранобэ"}
# Типы изданий Shikimori (поле kind у Manga).
MANGA_KINDS = ("manga", "manhwa", "manhua", "light_novel", "novel", "one_shot",
               "doujin")
MANGA_KIND_LABELS = {"manga": "Манга", "manhwa": "Манхва", "manhua": "Манхуа",
                     "light_novel": "Ранобэ", "novel": "Роман",
                     "one_shot": "Ваншот", "doujin": "Додзинси"}


class AnimePackApiError(Exception):
    """Сетевая ошибка источника данных (текст уже человеко-читаемый)."""


class RateLimiter:
    """Простое ведро токенов: не чаще N запросов в секунду, потокобезопасно.

    Нужно, потому что качаем пачками из нескольких потоков, а Shikimori/
    AnisongDB на всплеск отвечают 429 (и дальше приходится ждать дольше, чем
    заняла бы ровная выдача).

    per_minute — ВТОРОЙ предел, на скользящую минуту. У Shikimori лимита два
    сразу (5 запросов в секунду И 90 в минуту), и одной секундной паузы мало:
    ровные 2 запроса в секунду дают 120 в минуту, то есть гарантированный 429
    на второй же минуте работы.
    """

    def __init__(self, per_second: float, per_minute: int = 0):
        self.interval = 1.0 / max(0.01, float(per_second))
        self.per_minute = max(0, int(per_minute or 0))
        self._lock = threading.Lock()
        self._next = 0.0
        self._recent: deque = deque()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()
                wait = self._next - now
                if self.per_minute and len(self._recent) >= self.per_minute:
                    # Минутная квота выбрана — ждём, пока состарится самый
                    # ранний запрос окна.
                    wait = max(wait, self._recent[0] + 60.0 - now)
                if wait <= 0:
                    break
                time.sleep(wait)
            now = time.monotonic()
            self._next = max(now, self._next) + self.interval
            if self.per_minute:
                self._recent.append(now)

    def penalize(self, seconds: float) -> None:
        """Общая пауза для ВСЕХ потоков после отказа сервера (429).

        Одного ретрая мало: если сервер уже сердится, соседние потоки продолжат
        долбить его в том же темпе и разговор не наладится."""
        with self._lock:
            self._next = max(self._next, time.monotonic()) + max(0.0, float(seconds))


def make_session(user_agent: str = USER_AGENT) -> requests.Session:
    """Сессия с ретраями на обрывы и 5xx,
    но POST тоже ретраится (AnisongDB и GraphQL ходят методом POST)."""
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent,
                      "Accept": "application/json",
                      "Accept-Language": "ru,en;q=0.8"})
    retry = Retry(
        total=4, connect=4, read=4, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _friendly(e: Exception, what: str) -> AnimePackApiError:
    if isinstance(e, requests.Timeout):
        return AnimePackApiError(f"{what}: сервер не ответил вовремя.")
    if isinstance(e, requests.ConnectionError):
        return AnimePackApiError(f"{what}: нет связи с сервером.")
    return AnimePackApiError(f"{what}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# AMQ — общая база аниме
# ─────────────────────────────────────────────────────────────────────────────
class AmqApi:
    """Мастер-лист AMQ: annId → год выхода. Ответ большой (~16 МБ), поэтому из
    него сразу выжимается только нужное (id и год) и кладётся в кэш на сутки."""

    def __init__(self, session: Optional[requests.Session] = None,
                 cache_path: str = AMQ_CACHE_PATH, ttl: int = AMQ_CACHE_TTL):
        self.session = session or make_session()
        self.cache_path = cache_path
        self.ttl = int(ttl)
        self.limiter = RateLimiter(5)

    # ── кэш ────────────────────────────────────────────────────────────────
    def _read_cache(self) -> Optional[dict]:
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("animes"), dict):
            return None
        if time.time() - float(data.get("fetched") or 0) > self.ttl:
            return None
        return data

    def _write_cache(self, master_id: str, animes: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"masterListId": master_id, "fetched": time.time(),
                           "animes": animes}, f)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass  # кэш — оптимизация, его отсутствие не ошибка

    def library(self, force: bool = False,
                progress_cb: Optional[Callable[[str], None]] = None,
                should_stop: Optional[Callable[[], bool]] = None) -> dict[int, Optional[int]]:
        """{annId: год выхода}. force=True — игнорировать кэш.

        Качается потоком, а не одним resp.content: ответ около 16 МБ, и без
        этого «Стоп» не срабатывал, пока файл не приедет целиком."""
        if not force:
            cached = self._read_cache()
            if cached:
                if progress_cb:
                    progress_cb("Список аниме AMQ взят из кэша "
                                f"({len(cached['animes'])} шт.)")
                return {int(k): v for k, v in cached["animes"].items()}
        if progress_cb:
            progress_cb("Качаю список аниме с AMQ (~16 МБ)…")
        self.limiter.acquire()
        try:
            with self.session.get(f"{AMQ_BASE}/libraryMasterList",
                                  timeout=(10, 180), stream=True) as resp:
                resp.raise_for_status()
                chunks = []
                for chunk in resp.iter_content(chunk_size=1 << 18):
                    if should_stop and should_stop():
                        raise AnimePackApiError("Остановлено")
                    if chunk:
                        chunks.append(chunk)
                data = json.loads(b"".join(chunks).decode("utf-8", "replace"))
        except AnimePackApiError:
            raise
        except Exception as e:
            raise _friendly(e, "AMQ") from e
        amap = (data or {}).get("animeMap")
        if not isinstance(amap, dict):
            raise AnimePackApiError("AMQ вернул неожиданный ответ (нет animeMap).")
        animes: dict[str, Optional[int]] = {}
        for key, value in amap.items():
            if not isinstance(value, dict):
                continue
            year = value.get("year")
            animes[str(key)] = int(year) if isinstance(year, (int, float)) else None
        self._write_cache(str((data or {}).get("masterListId") or ""), animes)
        if progress_cb:
            progress_cb(f"Список аниме AMQ получен: {len(animes)} шт.")
        return {int(k): v for k, v in animes.items()}


# ─────────────────────────────────────────────────────────────────────────────
# AnisongDB — песни
# ─────────────────────────────────────────────────────────────────────────────
class AnisongApi:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(2)

    def _post(self, path: str, payload: dict) -> list:
        self.limiter.acquire()
        try:
            resp = self.session.post(f"{ANISONG_BASE}/{path}", json=payload,
                                     timeout=(10, 60))
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _friendly(e, "AnisongDB") from e
        if not isinstance(data, list):
            raise AnimePackApiError("AnisongDB вернул неожиданный ответ.")
        return data

    def songs_by_mal_ids(self, ids: Iterable[int]) -> list[dict]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        # Именно mal_ids: старое имя malIds сервер принимает, но отдаёт пустоту.
        return self._post("mal_ids_request", {"mal_ids": ids})

    def songs_by_ann_ids(self, ids: Iterable[int]) -> list[dict]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        return self._post("ann_ids_request", {"ann_ids": ids})


# ─────────────────────────────────────────────────────────────────────────────
# MyAnimeList — публичный список пользователя
# ─────────────────────────────────────────────────────────────────────────────
class MalApi:
    PAGE = 300

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(2)

    def user_anime_ids(self, username: str, statuses: Iterable[str],
                       progress_cb: Optional[Callable[[str], None]] = None,
                       should_stop: Optional[Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        """MAL id аниме (или манги) пользователя с нужными статусами.

        Список ПАГИНИРУЕТСЯ: load.json отдаёт по 300 записей, пока не вернёт
        пустой массив. Раздел манги живёт по тому же адресу, только
        /mangalist/ вместо /animelist/ и id в поле manga_id."""
        wanted = {s for s in statuses if s in LIST_STATUSES}
        if not username.strip() or not wanted:
            return []
        manga = str(target or "anime") == "manga"
        path = "mangalist" if manga else "animelist"
        id_field = "manga_id" if manga else "anime_id"
        what = "манги" if manga else "аниме"
        out: list[int] = []
        offset = 0
        while True:
            if should_stop and should_stop():
                break
            self.limiter.acquire()
            try:
                resp = self.session.get(
                    f"{MAL_BASE}/{path}/{username.strip()}/load.json",
                    params={"offset": offset, "status": 7}, timeout=(10, 45))
                if resp.status_code == 400:
                    raise AnimePackApiError(
                        f"MyAnimeList: пользователь «{username}» не найден "
                        "или его список закрыт.")
                resp.raise_for_status()
                chunk = resp.json()
            except AnimePackApiError:
                raise
            except Exception as e:
                raise _friendly(e, "MyAnimeList") from e
            if not isinstance(chunk, list) or not chunk:
                break
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                if _MAL_STATUS.get(row.get("status")) in wanted:
                    try:
                        out.append(int(row[id_field]))
                    except (KeyError, TypeError, ValueError):
                        continue
            if progress_cb:
                progress_cb(f"MyAnimeList/{username}: получено {len(out)} {what}…")
            if len(chunk) < self.PAGE:
                break
            offset += self.PAGE
        return out


# ─────────────────────────────────────────────────────────────────────────────
# AniList — список пользователя и картинки
# ─────────────────────────────────────────────────────────────────────────────
class AniListApi:
    """Публичный GraphQL AniList: ключ не нужен, лимит 90 запросов в минуту.

    Список пользователя приходит ОДНИМ запросом и сразу с MAL id — сводить
    каталоги (как пришлось бы с Kitsu или AniDB) не требуется.

    Картинки: `streamingEpisodes.thumbnail` — превью серий с легальных
    стримингов, то есть кадры из РАЗНЫХ серий, а не только из первой, как у
    Shikimori. Плюс баннер тайтла (широкий кадр) и обложка.
    """

    # Раздел манги — тот же запрос с type: MANGA (манхва, манхуа и ранобэ у
    # AniList лежат там же, различаясь полем format).
    LIST_QUERY = """query($name: String) {
      MediaListCollection(userName: $name, type: ANIME) {
        lists { entries { status media { idMal } } }
      }
    }"""
    LIST_QUERY_MANGA = LIST_QUERY.replace("type: ANIME", "type: MANGA")

    IMAGES_QUERY = """query($idMal: Int) {
      Media(idMal: $idMal, type: ANIME) {
        bannerImage
        coverImage { extraLarge large }
        streamingEpisodes { thumbnail }
      }
    }"""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(1.2)      # 90/мин с запасом

    def _graphql(self, query: str, variables: dict) -> dict:
        self.limiter.acquire()
        try:
            resp = self.session.post(ANILIST_BASE,
                                     json={"query": query, "variables": variables},
                                     timeout=(10, 45))
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            raise _friendly(e, "AniList") from e
        if isinstance(body, dict) and body.get("errors"):
            first = (body["errors"] or [{}])[0]
            raise AnimePackApiError(f"AniList: {first.get('message') or 'ошибка'}")
        data = (body or {}).get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    def user_anime_ids(self, username: str, statuses: Iterable[str],
                       progress_cb: Optional[Callable[[str], None]] = None,
                       should_stop: Optional[Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        """MAL id аниме (или манги) пользователя с нужными статусами (пагинации
        нет — MediaListCollection отдаёт весь список сразу)."""
        wanted = {s for s in statuses if s in LIST_STATUSES}
        nick = (username or "").strip()
        if not nick or not wanted:
            return []
        manga = str(target or "anime") == "manga"
        query = self.LIST_QUERY_MANGA if manga else self.LIST_QUERY
        try:
            data = self._graphql(query, {"name": nick})
        except AnimePackApiError as e:
            if "not found" in str(e).lower():
                raise AnimePackApiError(
                    f"AniList: пользователь «{nick}» не найден.") from e
            raise
        out: list[int] = []
        seen: set[int] = set()
        collection = (data.get("MediaListCollection") or {})
        for lst in (collection.get("lists") or []):
            if should_stop and should_stop():
                break
            for entry in ((lst or {}).get("entries") or []):
                if not isinstance(entry, dict):
                    continue
                if _ANILIST_STATUS.get(entry.get("status")) not in wanted:
                    continue
                mal = ((entry.get("media") or {}).get("idMal"))
                try:
                    mal = int(mal)
                except (TypeError, ValueError):
                    continue        # у части тайтлов AniList нет пары на MAL
                if mal in seen:
                    continue
                seen.add(mal)
                out.append(mal)
        if progress_cb:
            progress_cb(f"AniList/{nick}: получено {len(out)} "
                        f"{'манги' if manga else 'аниме'}…")
        return out

    def frames(self, mal_id: int) -> list[str]:
        """Кадры тайтла: превью серий (по одному на серию) + баннер."""
        try:
            data = self._graphql(self.IMAGES_QUERY, {"idMal": int(mal_id)})
        except Exception:  # noqa: BLE001 — дополнительный источник, не критичен
            return []
        media = data.get("Media") or {}
        out = [str(ep.get("thumbnail")) for ep in (media.get("streamingEpisodes") or [])
               if isinstance(ep, dict) and ep.get("thumbnail")]
        if media.get("bannerImage"):
            out.append(str(media["bannerImage"]))
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Kitsu — превью серий
# ─────────────────────────────────────────────────────────────────────────────
class KitsuApi:
    """Kitsu (JSON:API, без ключа). Берём только миниатюры серий: у каждой серии
    свой кадр, поэтому один тайтл даёт десятки разных сцен вместо трёх-четырёх
    скриншотов Shikimori.

    Kitsu живёт на своих id, поэтому сперва ищем тайтл по MAL id через
    /mappings, а уже потом спрашиваем серии."""

    EPISODES_LIMIT = 20      # больше Kitsu не отдаёт: page[limit]=40 → 400

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(3)

    def _get(self, path: str, params: dict) -> dict:
        self.limiter.acquire()
        resp = self.session.get(f"{KITSU_BASE}/{path}", params=params,
                                headers={"Accept": "application/vnd.api+json"},
                                timeout=(10, 45))
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def anime_id(self, mal_id: int) -> Optional[int]:
        """Kitsu id тайтла по его MAL id («» — пары нет)."""
        try:
            data = self._get("mappings", {
                "filter[externalSite]": "myanimelist/anime",
                "filter[externalId]": str(int(mal_id)),
                "include": "item"})
        except Exception:  # noqa: BLE001
            return None
        for item in (data.get("included") or []):
            if isinstance(item, dict) and item.get("type") == "anime":
                try:
                    return int(item.get("id"))
                except (TypeError, ValueError):
                    return None
        return None

    def frames(self, mal_id: int) -> list[str]:
        """Миниатюры серий тайтла (по MAL id). Пусто — пары в Kitsu нет."""
        kid = self.anime_id(mal_id)
        if not kid:
            return []
        try:
            # Без sparse fieldset (`fields[episodes]`): с ним Kitsu отдаёт
            # пустую выборку — проверено живым запросом.
            data = self._get(f"anime/{kid}/episodes",
                             {"page[limit]": self.EPISODES_LIMIT})
        except Exception:  # noqa: BLE001
            return []
        out = []
        for row in (data.get("data") or []):
            thumb = ((row or {}).get("attributes") or {}).get("thumbnail") or {}
            url = thumb.get("original") or thumb.get("large")
            if url:
                out.append(str(url))
        return out


# ─────────────────────────────────────────────────────────────────────────────
# TMDB (themoviedb.org) — запасной источник обложек
# ─────────────────────────────────────────────────────────────────────────────
TMDB_BASE = "https://api.themoviedb.org/3"
# Картинки TMDB лежат на своём CDN и ключа не требуют вовсе — ключ нужен только
# на поиск. «original» — исходный размер: под лимит пака его всё равно ужимает
# наш же кодировщик (avif_fit), а мельче брать незачем.
TMDB_IMG = "https://image.tmdb.org/t/p/original"


class TmdbApi:
    """Обложки с themoviedb.org — ЗАПАСНОЙ источник постера.

    Основной — Shikimori: там русские названия и та же карточка, из которой
    считается всё остальное. Но у части тайтлов (свежие ONA, спешлы, редкая
    манга) постера в карточке нет вовсе или ссылка не открывается, и вопрос
    оставался без картинки в ответе. Тогда тайтл ищется здесь по названию.

    Ключ пользовательский (Настройки → API на themoviedb.org, бесплатный).
    Годятся оба вида: старый v3 («api_key=...») и токен v4 («Bearer ...») —
    отличаем по виду строки, у токена всегда есть точки, как у любого JWT.
    """

    # TMDB разрешает ~50 запросов в секунду, но нам столько не нужно: постер
    # спрашивается только там, где Shikimori не дал своего.
    def __init__(self, session: Optional[requests.Session] = None,
                 key: str = "", language: str = "ru-RU"):
        self.session = session or make_session()
        self.key = str(key or "").strip()
        self.language = language
        self.limiter = RateLimiter(8)

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, params: dict) -> dict:
        headers = {"Accept": "application/json"}
        params = dict(params)
        if "." in self.key:                 # v4 read access token (JWT)
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        self.limiter.acquire()
        try:
            resp = self.session.get(f"{TMDB_BASE}/{path}", params=params,
                                    headers=headers, timeout=(10, 45))
            if resp.status_code in (401, 403):
                raise AnimePackApiError(
                    "TMDB: ключ не принят — проверьте его в настройках.")
            resp.raise_for_status()
            data = resp.json()
        except AnimePackApiError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _friendly(e, "TMDB") from e
        return data if isinstance(data, dict) else {}

    def poster_url(self, names, year: int = 0, movie: bool = False) -> str:
        """Ссылка на обложку тайтла («» — не нашлось).

        Названия перебираются по очереди: сперва оригинальное/английское (по
        ним TMDB ищет надёжнее), русское — последним. Год, если известен,
        отсеивает одноимённые ремейки."""
        if not self.enabled:
            return ""
        for name in names:
            name = str(name or "").strip()
            if not name:
                continue
            for kind in (("movie", "tv") if movie else ("tv", "movie")):
                params = {"query": name, "include_adult": "false",
                          "language": self.language}
                if year:
                    params["first_air_date_year" if kind == "tv"
                           else "primary_release_year"] = str(int(year))
                data = self._get(f"search/{kind}", params)
                url = self._pick(data.get("results") or [], name)
                if url:
                    return url
            if year:
                # Год у аниме и у TMDB иногда расходятся на сезон — второй
                # заход тем же названием, но уже без года.
                for kind in (("movie", "tv") if movie else ("tv", "movie")):
                    data = self._get(f"search/{kind}",
                                     {"query": name, "include_adult": "false",
                                      "language": self.language})
                    url = self._pick(data.get("results") or [], name)
                    if url:
                        return url
        return ""

    @staticmethod
    def _pick(rows: list, name: str) -> str:
        """Постер самого подходящего из найденного.

        Точное совпадение названия важнее популярности: по запросу «Bleach»
        TMDB первой строкой отдаёт документалку про моющее средство."""
        want = str(name or "").strip().casefold()
        best, best_score = "", -1.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("poster_path") or "").strip()
            if not path:
                continue
            titles = [str(row.get(k) or "") for k in
                      ("name", "original_name", "title", "original_title")]
            exact = any(t.strip().casefold() == want for t in titles)
            try:
                popular = float(row.get("popularity") or 0.0)
            except (TypeError, ValueError):
                popular = 0.0
            score = (1000.0 if exact else 0.0) + popular
            if score > best_score:
                best, best_score = f"{TMDB_IMG}{path}", score
        return best



# ─────────────────────────────────────────────────────────────────────────────
# AnimeThemes.moe — видео опенингов и эндингов
# ─────────────────────────────────────────────────────────────────────────────
class AnimeThemesApi:
    """Ролики опенингов/эндингов с animethemes.moe (ключи не нужны).

    Чем это лучше прочих источников видео: ролики там БЕЗ КРЕДИТОВ (nc: true) —
    то есть без надписей с названием прямо в кадре, а для угадайки это главное.
    Сервер отдаёт Range (206), поэтому ffmpeg вытягивает нужные секунды, а не
    все сорок мегабайт файла.

    Соответствие с нашими кандидатами идёт по MAL id и метке вида «OP1»/«ED2»:
    в AnisongDB та же песня называется «Opening 1», см. animepack.song_tag."""

    BATCH = 10               # столько MAL id уходит в один запрос

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(3)

    def themes_by_mal_ids(self, ids: Iterable[int]) -> dict:
        """{MAL id: {«OP1»: {url, resolution, size, song}}}.

        Возвращаем словарь по метке, а не список: вопросу нужен ровно тот
        опенинг, который выбран из AnisongDB, а не первый попавшийся."""
        wanted = [str(int(i)) for i in ids if int(i or 0) > 0]
        if not wanted:
            return {}
        params = {
            "filter[has]": "resources",
            "filter[site]": "MyAnimeList",
            "filter[external_id]": ",".join(wanted),
            "include": ("animethemes.animethemeentries.videos,"
                        "animethemes.song,resources"),
            "page[size]": 100,
        }
        self.limiter.acquire()
        try:
            resp = self.session.get(f"{ANIMETHEMES_BASE}/anime", params=params,
                                    timeout=(10, 60))
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _friendly(e, "AnimeThemes") from e
        out: dict[int, dict] = {}
        for anime in (data.get("anime") or []):
            mal = 0
            for res in (anime.get("resources") or []):
                if (res or {}).get("site") == "MyAnimeList":
                    try:
                        mal = int(res.get("external_id") or 0)
                    except (TypeError, ValueError):
                        mal = 0
                    if mal:
                        break
            if not mal:
                continue
            by_tag = out.setdefault(mal, {})
            for theme in (anime.get("animethemes") or []):
                tag = f"{(theme.get('type') or '').upper()}{theme.get('sequence') or 1}"
                best = None
                for entry in (theme.get("animethemeentries") or []):
                    for video in (entry.get("videos") or []):
                        link = (video or {}).get("link")
                        if not link:
                            continue
                        res = int(video.get("resolution") or 0)
                        # Из нескольких вариантов берём самый маленький файл при
                        # достаточном разрешении: качать 45 МБ, чтобы отрезать
                        # пятнадцать секунд и ужать до 720p, смысла нет.
                        cur = (0 if res >= 720 else 1, int(video.get("size") or 0))
                        if best is None or cur < best[0]:
                            best = (cur, {"url": str(link), "resolution": res,
                                          "size": int(video.get("size") or 0),
                                          "song": ((theme.get("song") or {})
                                                   .get("title") or "")})
                if best and tag not in by_tag:
                    by_tag[tag] = best[1]
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Fandom — пересказ сюжета для вопросов «по сюжету»
# ─────────────────────────────────────────────────────────────────────────────
class FandomApi:
    """Статьи фэндом-вики (ключей и регистрации не требуется).

    Нужны ради вопросов ПО СЮЖЕТУ: у сколько-нибудь известного тайтла на
    fandom.com есть своя вики, а в ней — страницы серий с разделом
    «Summary»/«Synopsis» (пересказ именно этой серии). Такой пересказ и уходит
    в Gemini, который делает из него вопрос (см. animepack_plot.py).

    ВАЖНО, как здесь ищется вики (проверено живыми запросами). Каталог
    community.fandom.com и вообще весь Fandom REST (/api/v1/…) закрыты
    проверкой Cloudflare и на любой запрос отвечают 403 — обходить её мы не
    станем. Зато обычный MediaWiki api.php на КАЖДОЙ вики открыт и работает,
    а сама Fandom держит адрес вики ровно по названию тайтла
    («attackontitan.fandom.com») и переставляет с синонимов
    («shingekinokyojin.fandom.com» → та же вики). Поэтому адрес мы не
    спрашиваем, а собираем из названия и проверяем запросом siteinfo:
    несуществующая вики отвечает 404.

    Расширения TextExtracts у Fandom тоже нет (prop=extracts → «Unrecognized
    value»), поэтому текст берётся сырой разметкой (action=parse&prop=wikitext)
    и чистится вручную — модель читает предложения, а не вёрстку.
    """

    # Сколько страниц берём с вики и сколько категорий проверяем.
    PAGES = 30
    CATEGORY_LIMIT = 200
    # Категории, в которых у вики лежат серии. Русские вики Fandom тоже есть.
    EPISODE_CATEGORIES = ("Episodes", "Anime Episodes", "Anime episodes",
                          "Серии", "Эпизоды")
    # Заголовки разделов, в которых лежит пересказ (регистр не важен).
    PLOT_HEADINGS = ("summary", "synopsis", "plot", "story", "overview",
                     "сюжет", "описание", "содержание", "краткое содержание")
    # Больше этого куска текста в запрос к модели не уходит: вопрос делается по
    # завязке эпизода, а не по всей статье, а токены на бесплатном тарифе
    # считаные.
    MAX_TEXT = 4000

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or make_session()
        # Fandom спокойно держит и больше, но статей на пак нужны единицы.
        self.limiter = RateLimiter(2)
        # Уже опрошенные адреса: {поддомен: хост или «»}. Один и тот же тайтл
        # (а с ним и его франшиза) попадается в паке не раз.
        self._wikis: dict[str, str] = {}
        self._wikis_lock = threading.Lock()

    # ── шаг 1: какая вики у тайтла ────────────────────────────────────────
    def _api(self, host: str, params: dict) -> dict:
        self.limiter.acquire()
        params = dict(params)
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        try:
            resp = self.session.get(f"https://{host}/api.php", params=params,
                                    timeout=(10, 45))
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise _friendly(e, f"Fandom ({host})") from e
        return data if isinstance(data, dict) else {}

    def wiki_at(self, slug: str) -> str:
        """Есть ли вики с таким адресом; возвращает КОНЕЧНЫЙ хост («» — нет).

        Конечный, потому что Fandom переставляет синонимы: запрос к
        shingekinokyojin.fandom.com приезжает на attackontitan.fandom.com, и
        дальше работать надо уже с ним."""
        slug = str(slug or "").strip().strip(".-")
        if not slug:
            return ""
        with self._wikis_lock:
            known = self._wikis.get(slug)
        if known is not None:
            return known
        host = ""
        self.limiter.acquire()
        try:
            resp = self.session.get(
                f"https://{slug}.{FANDOM_HOST}/api.php",
                params={"action": "query", "meta": "siteinfo",
                        "format": "json", "formatversion": "2"},
                timeout=(10, 30))
            if resp.status_code == 200:
                name = (((resp.json().get("query") or {}).get("general") or {})
                        .get("sitename") or "")
                if name:
                    host = re.sub(r"^https?://", "",
                                  str(resp.url or "")).split("/")[0]
        except Exception:  # noqa: BLE001 — вики просто нет, это не ошибка пака
            host = ""
        with self._wikis_lock:
            self._wikis[slug] = host
        return host

    def find_wiki(self, names) -> str:
        """Хост вики тайтла по его названиям («» — не нашлось).

        Названия перебираются подряд (обычно это ромадзи, английское и
        русское), из каждого получается пара адресов-кандидатов — «слитно» и
        «через дефис», ровно как их пишет сама Fandom. Первый живой и
        побеждает."""
        if isinstance(names, str):
            names = [names]
        for name in names or ():
            for slug in wiki_slugs(name):
                host = self.wiki_at(slug)
                if host:
                    return host
        return ""

    # ── шаг 2: какие там страницы ─────────────────────────────────────────
    def search(self, host: str, query: str, limit: int = 0) -> list[str]:
        """Названия страниц вики по запросу (основное пространство имён)."""
        if not host:
            return []
        data = self._api(host, {"action": "query", "list": "search",
                                "srsearch": query, "srnamespace": 0,
                                "srlimit": int(limit or self.PAGES)})
        out = []
        for row in (((data.get("query") or {}).get("search")) or []):
            name = str((row or {}).get("title") or "").strip()
            if name:
                out.append(name)
        return out

    def category_pages(self, host: str, category: str) -> list[str]:
        """Страницы категории (основное пространство имён)."""
        if not host:
            return []
        data = self._api(host, {"action": "query", "list": "categorymembers",
                                "cmtitle": f"Category:{category}",
                                "cmnamespace": 0,
                                "cmlimit": self.CATEGORY_LIMIT})
        out = []
        for row in (((data.get("query") or {}).get("categorymembers")) or []):
            name = str((row or {}).get("title") or "").strip()
            if name:
                out.append(name)
        return out

    def episode_pages(self, host: str) -> list[str]:
        """Страницы СЕРИЙ этой вики.

        Сперва категория серий — она есть у большинства аниме-вики и даёт
        ровно то, что нужно. Нет её (названа по-своему) — ищем поиском по
        слову «episode»: страницы серий поминают его и в тексте, а
        путеводители и списки серий отсеиваются отдельно (пересказа одной
        серии там нет)."""
        names: list[str] = []
        for category in self.EPISODE_CATEGORIES:
            try:
                names += self.category_pages(host, category)
            except AnimePackApiError:
                continue
            if names:
                break
        if not names:
            for word in ("episode", "серия"):
                try:
                    names += self.search(host, word)
                except AnimePackApiError:
                    continue
        out, seen = [], set()
        for name in names:
            if _EPISODE_LIST.search(name):
                continue
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                out.append(name)
        return out

    # ── шаг 3: текст страницы ─────────────────────────────────────────────
    def page_text(self, host: str, page: str) -> str:
        """Текст страницы без разметки («» — не получилось)."""
        try:
            data = self._api(host, {"action": "parse", "page": page,
                                    "prop": "wikitext", "redirects": 1})
        except AnimePackApiError:
            return ""
        raw = ((data.get("parse") or {}).get("wikitext") or "")
        if isinstance(raw, dict):          # formatversion=1 отдаёт {"*": "…"}
            raw = raw.get("*") or ""
        return strip_wikitext(str(raw))

    def plot_section(self, text: str) -> str:
        """Кусок статьи с пересказом («» — такого раздела нет).

        Разделы размечены как «== Summary ==». Берём первый подходящий по
        заголовку и всё до следующего заголовка того же уровня."""
        return plot_section(text, self.PLOT_HEADINGS)[:self.MAX_TEXT]


# Списки и путеводители — пересказа одной серии там нет.
_EPISODE_LIST = re.compile(r"^(list of|список)|guide$|episodes$",
                           re.IGNORECASE)
# Заголовок раздела: «== Summary ==», «===Plot===».
_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.MULTILINE)


def wiki_slugs(name: str) -> list[str]:
    """Адреса-кандидаты вики по названию тайтла.

    Fandom зовёт вики самим названием без пробелов («attackontitan») либо
    через дефис («kimetsu-no-yaiba») — оба написания и пробуем. Кириллица и
    иероглифы в адрес не годятся вовсе: русских вики по аниме на Fandom
    считаные, а адреса у них всё равно латиницей."""
    text = str(name or "").strip().lower()
    if not text:
        return []
    text = text.replace("'", "").replace("’", "")
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    if not words:
        return []
    joined = "".join(words)
    if len(joined) < 3:
        return []
    out = [joined]
    dashed = "-".join(words)
    if dashed != joined:
        out.append(dashed)
    # Последняя надежда — самое длинное слово названия: «Neon Genesis
    # Evangelion» живёт на evangelion.fandom.com, «Mahou Shoujo Madoka Magica»
    # — на madoka.fandom.com. Короткие слова сюда не берём вовсе («attack»,
    # «titan», «sekai» — это чужие вики, а не сокращение названия).
    if len(words) > 1:
        longest = max(words, key=len)
        if len(longest) >= 8 and longest not in out:
            out.append(longest)
    return out


def plot_section(text: str, headings) -> str:
    """Раздел с пересказом из текста статьи («» — не нашёлся).

    Подходящих разделов бывает несколько («Short Summary» и «Long Summary» у
    вики One Piece) — берём САМЫЙ ДЛИННЫЙ: чем подробнее пересказ, тем есть о
    чём спрашивать. Слово-заголовок ищется целиком, поэтому годятся и
    «Summary», и «Long Summary», и «Plot Summary».

    Вынесено из класса, чтобы проверялось тестами без сети."""
    body = str(text or "")
    if not body:
        return ""
    wanted = [h.casefold() for h in headings]
    marks = list(_HEADING.finditer(body))
    best = ""
    for i, m in enumerate(marks):
        name = m.group(2).strip().casefold()
        if not any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", name)
                   for w in wanted):
            continue
        level = len(m.group(1))
        end = len(body)
        for nxt in marks[i + 1:]:
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        chunk = body[m.end():end].strip()
        if len(chunk) > len(best):
            best = chunk
    return best


def strip_wikitext(raw: str) -> str:
    """Грубая чистка разметки MediaWiki до читаемого текста.

    Задача не «сверстать статью», а отдать модели связные предложения: убираем
    шаблоны {{…}}, файлы, таблицы, теги и оставляем от ссылок их подпись."""
    text = str(raw or "")
    for _ in range(6):                      # шаблоны бывают вложенными
        new = re.sub(r"\{\{[^{}]*\}\}", " ", text)
        if new == text:
            break
        text = new
    text = re.sub(r"(?s)\{\|.*?\|\}", " ", text)          # таблицы
    text = re.sub(r"(?s)<ref[^>]*>.*?</ref>", " ", text)  # сноски
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\[\[(?:Файл|File|Image|Изображение):[^\]]*\]\]", " ", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)   # [[цель|подпись]]
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)                          # ''курсив''
    text = re.sub(r"^[*#:;]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    # Вырезанные сноски и шаблоны оставляют после себя пробел перед точкой
    # («врага .») — на разбор моделью это не влияет, но лишний мусор в запросе
    # ни к чему.
    text = re.sub(r"[ \t]+([,.:;!?)])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Shikimori — список пользователя + карточки аниме
# ─────────────────────────────────────────────────────────────────────────────
class ShikimoriApi:
    """Списки пользователей и метаданные аниме.

    Метаданные идут через ShikimoriApiClient из shikimori_api.py — там уже есть
    ретраи на 429/5xx, Retry-After и ручная обработка редиректа .one → .io для
    POST-запросов GraphQL.
    """

    PAGE = 1000  # предел /api/v2/user_rates

    # english/japanese/synonyms/licenseNameRu — это варианты правильного ответа
    # (их и показывает страница тайтла: «На японском», «На английском»,
    # «Лицензировано в РФ под названием», «Синонимы»).
    # statusesStats — то же, из чего вкладка ShikimoriHYX считает «индекс
    # популярности», только в GraphQL-форме: так индекс достаётся пачкой по 50
    # тайтлов, без отдельного REST-запроса на каждый.
    ANIME_FIELDS = """
        id malId name russian english japanese synonyms licenseNameRu
        franchise score kind
        genres { id name russian kind }
        poster { originalUrl mainUrl }
        screenshots { originalUrl x332Url }
        airedOn { year }
        statusesStats { status count }
    """
    ANIMES_QUERY = ("query($ids: String!, $limit: Int!) {\n"
                    "  animes(ids: $ids, limit: $limit) {" + ANIME_FIELDS + "}\n}")

    # Части франшизы — по ним считается узнаваемость всей серии (у «Доктор
    # Стоун: Научное будущее. Часть 3» своих зрителей мало, но тайтл знают по
    # оригинальному «Доктору Стоуну»). Берём не одну самую популярную часть, а
    # первые FRANCHISE_PARTS: по ним видно и сколько у сериала заметных сезонов,
    # и когда вышло последнее продолжение (см. shikimori_api.franchise_parts_index).
    # Запросы склеиваются алиасами; 18 выборок по 12 карточек живой сервер
    # принимает — проверено.
    FRANCHISE_BATCH = 18
    FRANCHISE_PARTS = 12
    FRANCHISE_FIELDS = ("id malId russian score airedOn { year } "
                        "statusesStats { status count }")
    _RE_FRANCHISE = re.compile(r"[^a-z0-9_\-]")

    # Shikimori держит ДВА предела разом: 5 запросов в секунду и 90 в минуту.
    # Раньше стояла только секундная пауза (2 запроса/с), а это ровно 120 в
    # минуту — то есть 429 приходил гарантированно, стоило генерации пойти
    # дольше минуты. Дальше каждый отказ стоил ещё и четырёх ретраев с
    # нарастающей паузой (~20 с на запрос), из-за чего вопросы-персонажи (у
    # каждого свой запрос про избранное и про другие тайтлы) занимали десятки
    # минут. Берём 80/мин — с запасом на редиректы .one → .io, каждый из
    # которых для сервера тоже запрос.
    PER_MINUTE = 80

    def __init__(self, session: Optional[requests.Session] = None,
                 client: Optional[Any] = None):
        self.session = session or make_session()
        self.limiter = RateLimiter(2, per_minute=self.PER_MINUTE)
        self._client = client

    # ── клиент shikimori_api (ленивый импорт) ──────────────────────────────
    @property
    def client(self):
        if self._client is None:
            from shikimori_api import ShikimoriApiClient
            self._client = ShikimoriApiClient(user_agent=USER_AGENT,
                                              max_retries=4,
                                              session=self.session)
        return self._client

    @property
    def base_url(self) -> str:
        try:
            return self.client.base_url
        except Exception:  # pragma: no cover
            return "https://shikimori.one"

    # На сколько секунд притормозить ВСЕ потоки, когда сервер всё-таки сказал
    # 429. Своих ретраев у адаптера сессии четыре, и без общей паузы соседние
    # потоки продолжают долбить сервер ровно в том же темпе.
    RETRY_PENALTY = 20.0

    def _get(self, url: str, **kw):
        """GET к Shikimori через общий лимитер, с общей паузой при отказе.

        Ретраи на 429 живут в адаптере сессии, поэтому сюда такой отказ
        доезжает уже исключением RetryError («too many 429 error responses»)."""
        self.limiter.acquire()
        try:
            resp = self.session.get(url, **kw)
        except requests.RetryError:
            self.limiter.penalize(self.RETRY_PENALTY)
            raise
        if resp.status_code == 429:
            self.limiter.penalize(self.RETRY_PENALTY)
        return resp

    def user_id(self, nickname: str) -> Optional[int]:
        """Точный поиск по нику: /api/users/<ник>?is_nickname=1.

        В ASPG использовался /api/users?search=…, который ищет ПОДСТРОКОЙ среди
        всех пользователей и берёт первого попавшегося — из-за этого список мог
        приехать от постороннего человека.
        """
        nick = (nickname or "").strip()
        if not nick:
            return None
        try:
            resp = self._get(f"{self.base_url}/api/users/{nick}",
                             params={"is_nickname": 1}, timeout=(10, 30))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        uid = (data or {}).get("id") if isinstance(data, dict) else None
        return int(uid) if uid else None

    def user_anime_ids(self, nickname: str, statuses: Iterable[str],
                       progress_cb: Optional[Callable[[str], None]] = None,
                       should_stop: Optional[Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        wanted = {s for s in statuses if s in LIST_STATUSES}
        if not wanted:
            return []
        manga = str(target or "anime") == "manga"
        target_type = "Manga" if manga else "Anime"
        what = "манги" if manga else "аниме"
        uid = self.user_id(nickname)
        if not uid:
            raise AnimePackApiError(
                f"Shikimori: пользователь «{nickname}» не найден "
                "(ник указывается точно, с учётом регистра).")
        out: list[int] = []
        seen: set[int] = set()
        page = 1
        while True:
            if should_stop and should_stop():
                break
            try:
                resp = self._get(
                    f"{self.base_url}/api/v2/user_rates",
                    params={"user_id": uid, "target_type": target_type,
                            "limit": self.PAGE, "page": page},
                    timeout=(10, 45))
                resp.raise_for_status()
                chunk = resp.json()
            except Exception as e:
                raise _friendly(e, "Shikimori") from e
            if not isinstance(chunk, list) or not chunk:
                break
            fresh = 0
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                try:
                    target = int(row["target_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if target in seen:
                    continue
                seen.add(target)
                fresh += 1
                if _SHIKI_STATUS.get(row.get("status")) in wanted:
                    out.append(target)
            if progress_cb:
                progress_cb(f"Shikimori/{nickname}: получено {len(out)} {what}…")
            # /api/v2/user_rates не умеет ни page, ни limit: он всегда отдаёт
            # ВЕСЬ список пользователя (проверено на живом аккаунте — limit=1000
            # вернул 1019 записей, а page=2 и page=3 те же самые). Раньше цикл
            # из-за этого крутился бесконечно, набивая список копиями одних и тех
            # же тайтлов. Признак конца — страница без единого нового id.
            if fresh == 0 or len(chunk) < self.PAGE:
                break
            page += 1
        return out

    def animes_by_ids(self, ids: Iterable[int]) -> list[dict]:
        """Карточки аниме пачкой (≤50 за раз).

        ВНИМАНИЕ: `animes(ids:)` ищет по id Shikimori. У подавляющего
        большинства тайтлов он совпадает с MAL id (так исторически заведено),
        но совпадение не гарантировано — те, у кого id разошлись, просто не
        найдутся и будут пропущены при отборе.
        """
        ids = [str(int(i)) for i in ids]
        if not ids:
            return []
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.ANIMES_QUERY,
                                        {"ids": ",".join(ids), "limit": len(ids)})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    # ── Поиск тайтла по названию ─────────────────────────────────────────
    # Нужен вкладке «Апгрейд пака»: у неё на руках только строка ответа
    # («Наруто (2002)»), а нужны ВСЕ названия этого тайтла. Полей берём ровно
    # столько, сколько идёт в варианты ответа плюс постер (его вкладка кладёт в
    # ответ вопроса): скриншоты и жанры тут не нужны, а карточек приезжает по
    # нескольку на каждый вопрос пака.
    #
    # statusesStats — единственное «лишнее» поле, и оно необходимо: на одно и то
    # же название бывает несколько ТОЧНЫХ совпадений, и выбирать из них надо по
    # известности. Живой случай — ответ «За гранью»: так зовётся и «Kyoukai no
    # Kanata» (синонимом, больше миллиона в списках), и малоизвестная OVA «Sweat
    # Punch» (собственным русским названием), и без этого поля выбиралась вторая.
    SEARCH_FIELDS = """
        id malId name russian english japanese synonyms licenseNameRu
        kind airedOn { year }
        statusesStats { status count }
        poster { originalUrl mainUrl }
    """
    SEARCH_QUERY = ("query($search: String!, $limit: Int!) {\n"
                    "  animes(search: $search, limit: $limit) {"
                    + SEARCH_FIELDS + "}\n}")
    # То же самое, но по книгам: манга, манхва, манхуа и ранобэ. Нужен «Апгрейду
    # аниме-пака» на темах, у которых в названии написано «манга» или «ранобэ»:
    # тянуть в такой вопрос обложку аниме неправильно, а у части ответов аниме
    # нет вовсе («Soul Cartel», «Noblesse» — манхва). Поля у типа Manga те же,
    # кроме screenshots (см. MANGA_FIELDS ниже).
    MANGA_SEARCH_QUERY = ("query($search: String!, $limit: Int!) {\n"
                          "  mangas(search: $search, limit: $limit) {"
                          + SEARCH_FIELDS + "}\n}")
    # Сколько карточек просить на один запрос. Поиск Shikimori ранжирует сам, и
    # нужный тайтл почти всегда первый; несколько запасных нужны на случай, когда
    # первым идёт сиквел с более длинным названием.
    SEARCH_LIMIT = 5

    # Поиск ПЕРСОНАЖА по имени. Нужен «Апгрейду пака»: в паках сплошь и
    # рядом ответом стоит имя героя («Mumei», «Teto Kasane»), а поиск аниме на
    # него отвечает случайным одноимённым клипом. Ограничение написано числом
    # прямо в запросе: переменной его не передать — у Shikimori тут PositiveInt,
    # и Int! под него не подходит («Type mismatch on variable $limit»). Имя
    # константы не CHARACTERS_QUERY: так уже зовётся запрос «персонажи тайтла по
    # id» ниже в этом же классе, и совпадение имён молча подменяло запрос.
    CHARACTER_SEARCH_QUERY = ("query($search: String!) {\n"
                              "  characters(search: $search, limit: 5) "
                              "{ id name russian japanese }\n}")

    def search_characters_by_name(self, name: str) -> list[dict]:
        """Карточки персонажей по имени (пустая строка — пустой список)."""
        query = str(name or "").strip()
        if not query:
            return []
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.CHARACTER_SEARCH_QUERY,
                                        {"search": query})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        rows = (data or {}).get("characters") if isinstance(data, dict) else None
        return [c for c in (rows or []) if isinstance(c, dict)]

    def search_animes_by_name(self, name: str, limit: int = 0) -> list[dict]:
        """Карточки аниме по названию (поиск Shikimori). Пустая строка — пустой
        список, сеть при этом не трогается вовсе."""
        query = str(name or "").strip()
        if not query:
            return []
        limit = max(1, min(50, int(limit or self.SEARCH_LIMIT)))
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.SEARCH_QUERY,
                                        {"search": query, "limit": limit})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    def search_mangas_by_name(self, name: str, limit: int = 0) -> list[dict]:
        """Карточки манги, манхвы, манхуа и ранобэ по названию — то же, что
        search_animes_by_name, только по книгам."""
        query = str(name or "").strip()
        if not query:
            return []
        limit = max(1, min(50, int(limit or self.SEARCH_LIMIT)))
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.MANGA_SEARCH_QUERY,
                                        {"search": query, "limit": limit})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
        return [m for m in (mangas or []) if isinstance(m, dict)]

    # ── Манга, манхва, манхуа и ранобэ ───────────────────────────────────
    # У типа Manga в GraphQL Shikimori те же поля, что у Anime, кроме
    # screenshots (кадров у книги нет — вопросом служит портрет персонажа либо
    # обложка). Поэтому и запросы те же, только с другим корнем.
    MANGA_FIELDS = """
        id malId name russian english japanese synonyms licenseNameRu
        franchise score kind
        genres { id name russian kind }
        poster { originalUrl mainUrl }
        airedOn { year }
        statusesStats { status count }
    """
    MANGAS_QUERY = ("query($ids: String!, $limit: Int!) {\n"
                    "  mangas(ids: $ids, limit: $limit) {" + MANGA_FIELDS + "}\n}")

    def mangas_by_ids(self, ids: Iterable[int]) -> list[dict]:
        """Карточки манги/ранобэ пачкой (≤50 за раз) — как animes_by_ids."""
        ids = [str(int(i)) for i in ids]
        if not ids:
            return []
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.MANGAS_QUERY,
                                        {"ids": ",".join(ids), "limit": len(ids)})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
        return [m for m in (mangas or []) if isinstance(m, dict)]

    def random_mangas(self, page: int = 1, *, limit: int = 50,
                      season: str = "", kinds: Iterable[str] = (),
                      score: int = 0, genres: Iterable[int] = (),
                      genres_exclude: Iterable[int] = (),
                      order: str = "random") -> list[dict]:
        """Страница случайных карточек манги (order: random) с фильтрами.

        Про order — см. random_animes: обход каталога целиком идёт с `order: id`,
        случайная выборка — с `random`."""
        args = [f"page: {max(1, int(page))}", f"limit: {max(1, min(50, int(limit)))}",
                f"order: {self._RE_ARG.sub('', str(order or 'random')) or 'random'}",
                "censored: true"]
        if season:
            args.append(f'season: "{self._RE_ARG.sub("", str(season))}"')
        kinds = [self._RE_ARG.sub("", str(k)) for k in kinds]
        kinds = [k for k in kinds if k]
        if kinds:
            args.append(f'kind: "{",".join(kinds)}"')
        if score and int(score) > 0:
            args.append(f"score: {int(score)}")
        gen = [str(int(g)) for g in genres]
        gen += [f"!{int(g)}" for g in genres_exclude]
        if gen:
            args.append(f'genre: "{",".join(gen)}"')
        query = ("query {\n  mangas(" + ", ".join(args) + ") {"
                 + self.MANGA_FIELDS + "}\n}")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
        return [m for m in (mangas or []) if isinstance(m, dict)]

    def character_titles(self, char_id: int) -> dict:
        """{"animes": [...], "mangas": [...]} — где вообще появлялся персонаж.

        Нужно, чтобы в вопросе-персонаже ответом было САМОЕ ПЕРВОЕ произведение
        с ним, а не тот сиквел, из которого его случайно вытащили. В GraphQL у
        типа Character таких полей нет вовсе (проверено: «Field 'animes' doesn't
        exist on type 'Character'»), поэтому идём в REST /api/characters/:id —
        там у каждой строки есть и id, и aired_on."""
        try:
            cid = int(char_id)
        except (TypeError, ValueError):
            return {}
        try:
            resp = self._get(f"{self.base_url}/api/characters/{cid}",
                             timeout=(10, 30))
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        if not isinstance(data, dict):
            return {}
        out = {}
        for key in ("animes", "mangas"):
            rows = [r for r in (data.get(key) or []) if isinstance(r, dict)]
            out[key] = rows
        return out

    # Персонажи тайтла для вопроса «угадай персонажа». characterRoles — тяжёлое
    # поле (Shikimori режет запросы по «сложности»), поэтому пачка маленькая.
    CHARACTERS_BATCH = 8
    # synonyms — это раздел «Прочие» на странице персонажа: другие написания
    # имени, прозвища, имя из перевода. Всё это засчитывается как верный ответ
    # в вопросе «угадай персонажа», поэтому тянем вместе с самим именем.
    CHARACTERS_QUERY = """query($ids: String!, $limit: Int!) {
      animes(ids: $ids, limit: $limit) {
        id malId
        characterRoles {
          rolesEn
          character {
            id name russian synonyms
            poster { originalUrl mainUrl }
          }
        }
      }
    }"""

    CHARACTERS_QUERY_MANGA = CHARACTERS_QUERY.replace("animes(", "mangas(")

    def characters_by_anime_ids(self, ids: Iterable[int],
                                target: str = "anime") -> dict:
        """{id аниме: [{"name", "names", "poster", "main"}]} — персонажи с
        портретами. Роль «Main»/«Supporting» приходит списком rolesEn, а
        "names" — все варианты имени (русское, ромадзи и «Прочие»).

        target="manga" спрашивает то же самое у манги/ранобэ: characterRoles
        есть и у типа Manga."""
        ids = [str(int(i)) for i in ids]
        if not ids:
            return {}
        manga = str(target or "anime") == "manga"
        query = self.CHARACTERS_QUERY_MANGA if manga else self.CHARACTERS_QUERY
        root = "mangas" if manga else "animes"
        self.limiter.acquire()
        try:
            data = self.client._graphql(query,
                                        {"ids": ",".join(ids), "limit": len(ids)})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        out: dict[int, list[dict]] = {}
        for anime in ((data or {}).get(root) or []):
            if not isinstance(anime, dict):
                continue
            try:
                key = int(anime.get("malId") or anime.get("id") or 0)
            except (TypeError, ValueError):
                continue
            rows = []
            for role in (anime.get("characterRoles") or []):
                char = (role or {}).get("character") or {}
                poster = (char.get("poster") or {})
                url = poster.get("originalUrl") or poster.get("mainUrl")
                name = (char.get("russian") or char.get("name") or "").strip()
                if not url or not name:
                    continue
                roles = [str(r).lower() for r in (role.get("rolesEn") or [])]
                # «Прочие» Shikimori хранит списком, но внутри одной строки
                # бывает сразу несколько прозвищ через запятую («Al, Armored
                # Alchemist») — разбиваем, иначе целиком такую строку никто
                # никогда не назовёт.
                alts = [name, char.get("russian"), char.get("name")]
                for syn in (char.get("synonyms") or []):
                    alts.extend(str(syn or "").split(","))
                names, seen = [], set()
                for alt in alts:
                    alt = str(alt or "").strip()
                    if len(alt) > 1 and alt.casefold() not in seen:
                        seen.add(alt.casefold())
                        names.append(alt)
                rows.append({"id": char.get("id"), "name": name, "names": names,
                             "poster": str(url), "main": "main" in roles})
            if rows:
                out[key] = rows
        return out

    # Случайные тайтлы прямо из каталога Shikimori (альтернатива базе AMQ).
    # Фильтры уходят на сервер, поэтому мусора приезжает куда меньше, чем при
    # переборе 16-мегабайтного мастер-листа AMQ.
    RANDOM_LIMIT = 50

    def random_animes(self, page: int = 1, *, limit: int = RANDOM_LIMIT,
                      season: str = "", kinds: Iterable[str] = (),
                      score: int = 0, genres: Iterable[int] = (),
                      genres_exclude: Iterable[int] = (),
                      order: str = "random") -> list[dict]:
        """Страница случайных карточек каталога (order: random) с фильтрами.

        Аргументы подставляются в текст запроса, а не переменными: имена типов
        у аргументов `animes` в схеме Shikimori разные (AnimeKindString,
        SeasonString…), и промах в одном из них ронял бы весь запрос.

        order меняет порядок выдачи. При `random` сервер тасует каталог заново
        на КАЖДЫЙ запрос, поэтому страницы накладываются друг на друга: для
        одной выборки это ровно то, что нужно, а вот вычерпать каталог целиком
        так нельзя. Обход всего каталога идёт с `order: id` — тогда страницы не
        пересекаются и конец наступает по-настоящему."""
        args = [f"page: {max(1, int(page))}", f"limit: {max(1, min(50, int(limit)))}",
                f"order: {self._RE_ARG.sub('', str(order or 'random')) or 'random'}",
                "censored: true"]
        if season:
            args.append(f'season: "{self._RE_ARG.sub("", str(season))}"')
        kinds = [self._RE_ARG.sub("", str(k)) for k in kinds]
        kinds = [k for k in kinds if k]
        if kinds:
            args.append(f'kind: "{",".join(kinds)}"')
        if score and int(score) > 0:
            args.append(f"score: {int(score)}")
        gen = [str(int(g)) for g in genres]
        gen += [f"!{int(g)}" for g in genres_exclude]
        if gen:
            args.append(f'genre: "{",".join(gen)}"')
        query = ("query {\n  animes(" + ", ".join(args) + ") {"
                 + self.ANIME_FIELDS + "}\n}")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {})
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    _RE_ARG = re.compile(r'[^0-9a-zA-Z_,\-]')

    def franchise_parts(self, keys: Iterable[str]) -> dict:
        """{ключ франшизы: [карточки её частей по убыванию популярности]}.

        Нужно, чтобы сиквел считался таким же узнаваемым, как оригинал (у
        «Доктор Стоун: Научное будущее. Часть 3» своих зрителей мало, но
        спрашивают-то по сути «Доктора Стоуна»), а заодно чтобы сериал с
        несколькими живыми сезонами получал надбавку, а старый тайтл со свежим
        продолжением — послабление по году (shikimori_api.franchise_parts_index).
        Запрос один на FRANCHISE_BATCH франшиз (алиасы в одном GraphQL-документе).
        """
        clean, seen = [], set()
        for key in keys:
            key = self._RE_FRANCHISE.sub("", str(key or "").strip().lower())
            if key and key not in seen:
                seen.add(key)
                clean.append(key)
        out: dict = {}
        for batch in (clean[i:i + self.FRANCHISE_BATCH]
                      for i in range(0, len(clean), self.FRANCHISE_BATCH)):
            parts = [f'  f{n}: animes(franchise: "{key}", '
                     f'limit: {self.FRANCHISE_PARTS}, '
                     f'order: popularity) {{ {self.FRANCHISE_FIELDS} }}'
                     for n, key in enumerate(batch)]
            self.limiter.acquire()
            try:
                data = self.client._graphql("query {\n" + "\n".join(parts) + "\n}",
                                            {})
            except Exception:  # noqa: BLE001 — без частей франшизы пак соберётся
                # Сорвавшуюся пачку НЕ отмечаем как «частей нет»: иначе разовый
                # обрыв сети навсегда осел бы в кэше нулевой узнаваемостью.
                continue
            for n, key in enumerate(batch):
                found = (data or {}).get(f"f{n}") if isinstance(data, dict) else None
                # Пустой список тоже ответ («у этой франшизы частей нет») —
                # ключ есть, значит спрашивать её снова незачем.
                out[key] = [r for r in (found or []) if isinstance(r, dict)]
        return out

    # ── «В избранном» у персонажа ────────────────────────────────────────
    # В API этого числа нет вовсе: у GraphQL-типа Character полей про избранное
    # не существует (проверено интроспекцией), а REST /api/characters/:id отдаёт
    # только `favoured` — булев флаг «добавил ли ТЕКУЩИЙ пользователь». Само
    # число висит на странице персонажа блоком b-favoured, оттуда и берём.
    _RE_FAVOURED = re.compile(
        r'b-favoured.{0,800}?<div class="count">\s*(\d+)\s*</div>', re.S)

    def character_favorites(self, char_id: int) -> int:
        """Сколько человек добавили персонажа в избранное (−1 — не узнали).

        Ноль и «не узнали» различаются нарочно: у безвестного персонажа блока с
        числом на странице нет, и путать его с обрывом сети нельзя — иначе
        сложность вопроса считалась бы по случайности."""
        try:
            cid = int(char_id)
        except (TypeError, ValueError):
            return -1
        if cid <= 0:
            return -1
        try:
            resp = self._get(f"{self.base_url}/characters/{cid}",
                             headers={"Accept": "text/html"},
                             timeout=(10, 30))
            if resp.status_code == 404:
                return -1
            resp.raise_for_status()
            html = resp.text
        except Exception:  # noqa: BLE001 — доп. мера сложности, не критична
            return -1
        m = self._RE_FAVOURED.search(html)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                return -1
        # Страница пришла, а блока нет — значит в избранном персонаж ни у кого.
        # Отличаем это от постороннего ответа (404, заглушка Cloudflare) по
        # классу тела страницы персонажа.
        return 0 if "p-characters-show" in html else -1

    def genres(self) -> list[dict]:
        """Полный современный список жанров/тем (id/name/russian/kind)."""
        try:
            return self.client.genres("anime")
        except Exception as e:
            raise _friendly(e, "Shikimori") from e
