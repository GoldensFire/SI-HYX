# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ошибки и ограничитель запросов; клиенты AMQ, AnisongDB и MyAnimeList. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


class AnimePackApiError(Exception):
    """Сетевая ошибка источника данных (текст уже человеко-читаемый)."""

AnimePackApiError.__module__ = _api.__name__
_api.AnimePackApiError = AnimePackApiError

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
        self._lock = _api.threading.Lock()
        self._next = 0.0
        self._recent: _api.deque = _api.deque()

    def acquire(self, deadline=None) -> None:
        with self._lock:
            while True:
                now = _api.time.monotonic()
                if deadline is not None and now >= deadline:
                    raise TimeoutError("Истекло время ожидания источника")
                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()
                wait = self._next - now
                if self.per_minute and len(self._recent) >= self.per_minute:
                    # Минутная квота выбрана — ждём, пока состарится самый
                    # ранний запрос окна.
                    wait = max(wait, self._recent[0] + 60.0 - now)
                if wait <= 0:
                    break
                _api.time.sleep(min(wait, max(0, deadline - now))
                                if deadline is not None else wait)
            now = _api.time.monotonic()
            self._next = max(now, self._next) + self.interval
            if self.per_minute:
                self._recent.append(now)

    def penalize(self, seconds: float) -> None:
        """Общая пауза для ВСЕХ потоков после отказа сервера (429).

        Одного ретрая мало: если сервер уже сердится, соседние потоки продолжат
        долбить его в том же темпе и разговор не наладится."""
        with self._lock:
            self._next = max(self._next, _api.time.monotonic()) + max(0.0, float(seconds))

RateLimiter.__module__ = _api.__name__
_api.RateLimiter = RateLimiter

def make_session(user_agent: str = _api.USER_AGENT) -> _api.requests.Session:
    """Сессия с ретраями на обрывы и 5xx,
    но POST тоже ретраится (AnisongDB и GraphQL ходят методом POST)."""
    s = _api.requests.Session()
    s.headers.update({"User-Agent": user_agent,
                      "Accept": "application/json",
                      "Accept-Language": "ru,en;q=0.8"})
    retry = _api.Retry(
        total=4, connect=4, read=4, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = _api.HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

make_session.__module__ = _api.__name__
_api.make_session = make_session

def _friendly(e: Exception, what: str) -> _api.AnimePackApiError:
    if isinstance(e, _api.requests.Timeout):
        return _api.AnimePackApiError(f"{what}: сервер не ответил вовремя.")
    if isinstance(e, _api.requests.ConnectionError):
        return _api.AnimePackApiError(f"{what}: нет связи с сервером.")
    return _api.AnimePackApiError(f"{what}: {e}")

_friendly.__module__ = _api.__name__
_api._friendly = _friendly

# ─────────────────────────────────────────────────────────────────────────────
# AMQ — общая база аниме
# ─────────────────────────────────────────────────────────────────────────────
class AmqApi:
    """Мастер-лист AMQ: annId → год выхода. Ответ большой (~16 МБ), поэтому из
    него сразу выжимается только нужное (id и год) и кладётся в кэш на сутки."""

    def __init__(self, session: _api.Optional[_api.requests.Session] = None,
                 cache_path: str = _api.AMQ_CACHE_PATH, ttl: int = _api.AMQ_CACHE_TTL):
        self.session = session or _api.make_session()
        self.cache_path = cache_path
        self.ttl = int(ttl)
        self.limiter = _api.RateLimiter(5)

    # ── кэш ────────────────────────────────────────────────────────────────
    def _read_cache(self) -> _api.Optional[dict]:
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = _api.json.load(f)
        except Exception:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("animes"), dict):
            return None
        if _api.time.time() - float(data.get("fetched") or 0) > self.ttl:
            return None
        return data

    def _write_cache(self, master_id: str, animes: dict) -> None:
        try:
            _api.os.makedirs(_api.os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _api.json.dump({"masterListId": master_id, "fetched": _api.time.time(),
                           "animes": animes}, f)
            _api.os.replace(tmp, self.cache_path)
        except Exception:
            pass  # кэш — оптимизация, его отсутствие не ошибка

    def library(self, force: bool = False,
                progress_cb: _api.Optional[_api.Callable[[str], None]] = None,
                should_stop: _api.Optional[_api.Callable[[], bool]] = None) -> dict[int, _api.Optional[int]]:
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
            with self.session.get(f"{_api.AMQ_BASE}/libraryMasterList",
                                  timeout=(10, 180), stream=True) as resp:
                resp.raise_for_status()
                chunks = []
                for chunk in resp.iter_content(chunk_size=1 << 18):
                    if should_stop and should_stop():
                        raise _api.AnimePackApiError("Остановлено")
                    if chunk:
                        chunks.append(chunk)
                data = _api.json.loads(b"".join(chunks).decode("utf-8", "replace"))
        except _api.AnimePackApiError:
            raise
        except Exception as e:
            raise _api._friendly(e, "AMQ") from e
        amap = (data or {}).get("animeMap")
        if not isinstance(amap, dict):
            raise _api.AnimePackApiError("AMQ вернул неожиданный ответ (нет animeMap).")
        animes: dict[str, _api.Optional[int]] = {}
        for key, value in amap.items():
            if not isinstance(value, dict):
                continue
            year = value.get("year")
            animes[str(key)] = int(year) if isinstance(year, (int, float)) else None
        self._write_cache(str((data or {}).get("masterListId") or ""), animes)
        if progress_cb:
            progress_cb(f"Список аниме AMQ получен: {len(animes)} шт.")
        return {int(k): v for k, v in animes.items()}

AmqApi.__module__ = _api.__name__
_api.AmqApi = AmqApi

# ─────────────────────────────────────────────────────────────────────────────
# AnisongDB — песни
# ─────────────────────────────────────────────────────────────────────────────
class AnisongApi:
    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(2)

    def _post(self, path: str, payload: dict) -> list:
        self.limiter.acquire()
        try:
            resp = self.session.post(f"{_api.ANISONG_BASE}/{path}", json=payload,
                                     timeout=(10, 60))
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _api._friendly(e, "AnisongDB") from e
        if not isinstance(data, list):
            raise _api.AnimePackApiError("AnisongDB вернул неожиданный ответ.")
        return data

    def songs_by_mal_ids(self, ids: _api.Iterable[int]) -> list[dict]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        # Именно mal_ids: старое имя malIds сервер принимает, но отдаёт пустоту.
        return self._post("mal_ids_request", {"mal_ids": ids})

    def songs_by_ann_ids(self, ids: _api.Iterable[int]) -> list[dict]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        return self._post("ann_ids_request", {"ann_ids": ids})

    def songs_by_name_artist(self, name: str, artist: str) -> list[dict]:
        """Все размещения одной и той же песни с тем же исполнителем."""
        text = lambda value: {"search": str(value), "partial_match": False,
                              "match_case": False}
        artist_filter = text(artist)
        artist_filter.update(group_granularity=0, max_other_artist=99)
        return self._post("search_request", {
            "song_name_search_filter": text(name),
            "artist_search_filter": artist_filter,
            "and_logic": True,
            "ignore_duplicate": False,
        })

AnisongApi.__module__ = _api.__name__
_api.AnisongApi = AnisongApi

# ─────────────────────────────────────────────────────────────────────────────
# MyAnimeList — публичный список пользователя
# ─────────────────────────────────────────────────────────────────────────────
class MalApi:
    PAGE = 300

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(2)

    def user_anime_ids(self, username: str, statuses: _api.Iterable[str],
                       progress_cb: _api.Optional[_api.Callable[[str], None]] = None,
                       should_stop: _api.Optional[_api.Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        """MAL id аниме (или манги) пользователя с нужными статусами.

        Список ПАГИНИРУЕТСЯ: load.json отдаёт по 300 записей, пока не вернёт
        пустой массив. Раздел манги живёт по тому же адресу, только
        /mangalist/ вместо /animelist/ и id в поле manga_id."""
        wanted = {s for s in statuses if s in _api.LIST_STATUSES}
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
                    f"{_api.MAL_BASE}/{path}/{username.strip()}/load.json",
                    params={"offset": offset, "status": 7}, timeout=(10, 45))
                if resp.status_code == 400:
                    raise _api.AnimePackApiError(
                        f"MyAnimeList: пользователь «{username}» не найден "
                        "или его список закрыт.")
                resp.raise_for_status()
                chunk = resp.json()
            except _api.AnimePackApiError:
                raise
            except Exception as e:
                raise _api._friendly(e, "MyAnimeList") from e
            if not isinstance(chunk, list) or not chunk:
                break
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                if _api._MAL_STATUS.get(row.get("status")) in wanted:
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

MalApi.__module__ = _api.__name__
_api.MalApi = MalApi
