# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# shikimori_api.py — слой доступа к Shikimori API (REST v1) и слой фильтрации.
# Здесь НЕТ ничего из Qt: модуль чисто сетевой/логический, его можно тестировать
# и переиспользовать отдельно от GUI (вкладка ShikimoriHYX в shikimori_tab.py).
#
# Архитектура (как просили — раздельные слои):
#   • ShikimoriApiClient — тонкий HTTP-клиент поверх requests (таймауты, ретраи
#     на 429/5xx, типизированные результаты, понятные ошибки).
#   • Anime               — типизированная модель элемента ответа.
#   • AnimeFilter         — критерии поиска. Часть отдаёт серверу (search/kind/
#     status/season/score/genre), а чего сервер не умеет (верхняя граница оценки,
#     диапазоны эпизодов/лет) — досчитывается ЛОКАЛЬНО (matches_local).
#   • find_anime()        — высокоуровневый помощник: серверный поиск с
#     пагинацией + локальная доводка под полный набор критериев.
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

try:
    import requests
    from requests import Session
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover - requests есть в requirements
    requests = None  # type: ignore
    Session = Any  # type: ignore
    _HAS_REQUESTS = False


# Текущий рабочий домен Shikimori (бывший .org переехал на .one).
DEFAULT_BASE_URL = "https://shikimori.one"
# Shikimori ТРЕБУЕТ осмысленный User-Agent (иначе 403/429). Подставляется
# название приложения; вызывающая сторона может переопределить.
DEFAULT_USER_AGENT = "SI-HYX/0.4 (+https://github.com)"

# Допустимые значения серверных фильтров (для валидации в UI и тестах).
KINDS = ("tv", "movie", "ova", "ona", "special", "music",
         "tv_13", "tv_24", "tv_48")
STATUSES = ("anons", "ongoing", "released")
ORDERS = ("ranked", "popularity", "name", "aired_on", "episodes",
          "kind", "id", "random")

# Человеко-читаемые подписи (RU) для UI — здесь, чтобы маппинг жил рядом с API.
KIND_LABELS = {
    "tv": "ТВ-сериал", "movie": "Фильм", "ova": "OVA", "ona": "ONA",
    "special": "Спешл", "music": "Клип", "tv_13": "ТВ ≤13 эп.",
    "tv_24": "ТВ ≤24 эп.", "tv_48": "ТВ ≤48 эп.",
}
STATUS_LABELS = {"anons": "Анонс", "ongoing": "Онгоинг", "released": "Вышло"}

# ── Манга ────────────────────────────────────────────────────────────────────
# Shikimori отдаёт мангу через /api/mangas с теми же параметрами поиска
# (search/kind/status/season/score/genre/order), но другими допустимыми kind/
# status и «главами» (chapters) вместо эпизодов.
MANGA_KINDS = ("manga", "manhwa", "manhua", "light_novel", "novel",
               "one_shot", "doujin")
MANGA_STATUSES = ("anons", "ongoing", "released", "paused", "discontinued")
MANGA_KIND_LABELS = {
    "manga": "Манга", "manhwa": "Манхва", "manhua": "Маньхуа",
    "light_novel": "Ранобэ", "novel": "Роман", "one_shot": "Ваншот",
    "doujin": "Додзинси",
}
MANGA_STATUS_LABELS = {
    "anons": "Анонс", "ongoing": "Онгоинг", "released": "Вышло",
    "paused": "Пауза", "discontinued": "Брошено",
}

# Тип контента вкладки.
CONTENT_ANIME = "anime"
CONTENT_MANGA = "manga"

# «Просмотры» тайтла = сумма по спискам пользователей, КРОМЕ «запланировано»
# (и «отложено» — пользователь просил считать только реально смотревших):
# completed (просмотрено) + watching (смотрю) + dropped (брошено). Берётся из
# rates_statuses_stats полной карточки /api/animes/{id} (в списочном ответе её нет).
VIEW_STATUSES = ("completed", "watching", "dropped")


def views_from_card(card: dict) -> int:
    """Считает «просмотры» (completed+watching+dropped) из карточки тайтла.
    Запланировано/отложено НЕ учитываются. При отсутствии данных вернёт 0."""
    if not isinstance(card, dict):
        return 0
    total = 0
    for s in card.get("rates_statuses_stats") or []:
        if isinstance(s, dict) and s.get("name") in VIEW_STATUSES:
            try:
                total += int(s.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return total


def kinds_for(content_type: str):
    return MANGA_KINDS if content_type == CONTENT_MANGA else KINDS


def statuses_for(content_type: str):
    return MANGA_STATUSES if content_type == CONTENT_MANGA else STATUSES


def kind_label(content_type: str, kind: str) -> str:
    if content_type == CONTENT_MANGA:
        return MANGA_KIND_LABELS.get(kind, kind)
    return KIND_LABELS.get(kind, kind)


def status_label(content_type: str, status: str) -> str:
    if content_type == CONTENT_MANGA:
        return MANGA_STATUS_LABELS.get(status, status)
    return STATUS_LABELS.get(status, status)


class ShikimoriError(Exception):
    """Любая ошибка обращения к Shikimori API (сеть, таймаут, не-2xx, разбор)."""


@dataclass(slots=True)
class Anime:
    """Типизированный элемент ответа /api/animes."""
    id: int
    name: str
    russian: str
    kind: str
    score: float
    status: str
    episodes: int
    episodes_aired: int
    aired_on: Optional[str]
    released_on: Optional[str]
    image_url: str
    url: str

    @property
    def title(self) -> str:
        """Заголовок для показа: русский, если есть, иначе оригинал."""
        return self.russian or self.name

    @property
    def year(self) -> Optional[int]:
        """Год выхода из aired_on/released_on (YYYY-MM-DD…) или None."""
        for src in (self.aired_on, self.released_on):
            if src and len(src) >= 4 and src[:4].isdigit():
                return int(src[:4])
        return None

    @classmethod
    def from_json(cls, d: dict, base_url: str = DEFAULT_BASE_URL) -> "Anime":
        img = d.get("image") or {}
        img_rel = img.get("preview") or img.get("original") or ""
        if img_rel and img_rel.startswith("/"):
            img_url = base_url + img_rel
        else:
            img_url = img_rel
        url_rel = d.get("url") or ""
        url = base_url + url_rel if url_rel.startswith("/") else url_rel

        def _num(v, cast, default):
            try:
                return cast(v)
            except (TypeError, ValueError):
                return default

        # Манга использует «главы» (chapters) вместо эпизодов — мапим их в
        # episodes, чтобы единая модель/таблица показывала число выпусков.
        episodes = _num(d.get("episodes"), int, 0)
        if not episodes and d.get("chapters") is not None:
            episodes = _num(d.get("chapters"), int, 0)
        return cls(
            id=_num(d.get("id"), int, 0),
            name=str(d.get("name") or ""),
            russian=str(d.get("russian") or ""),
            kind=str(d.get("kind") or ""),
            score=_num(d.get("score"), float, 0.0),
            status=str(d.get("status") or ""),
            episodes=episodes,
            episodes_aired=_num(d.get("episodes_aired"), int, 0),
            aired_on=d.get("aired_on"),
            released_on=d.get("released_on"),
            image_url=img_url,
            url=url,
        )

    def as_row(self) -> dict:
        """Плоский словарь для экспорта в JSON/CSV."""
        return {
            "id": self.id,
            "title": self.title,
            "name": self.name,
            "russian": self.russian,
            "kind": self.kind,
            "score": self.score,
            "status": self.status,
            "episodes": self.episodes,
            "episodes_aired": self.episodes_aired,
            "year": self.year or "",
            "aired_on": self.aired_on or "",
            "url": self.url,
        }


@dataclass
class AnimeFilter:
    """Критерии поиска аниме.

    Серверные (отдаются Shikimori): query(search), kind, status, season(год),
    score(минимум, целое), genres. Остальное — локально через matches_local():
    верхняя граница оценки, точные диапазоны лет и числа эпизодов. Локальная
    проверка дублирует и серверные числовые границы — так результат корректен
    даже если сервер фильтрует грубее (минимальный score округляется до целого).
    """
    query: str = ""
    kind: str = ""
    status: str = ""
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    score_min: Optional[float] = None
    score_max: Optional[float] = None
    episodes_min: Optional[int] = None
    episodes_max: Optional[int] = None
    genres: list[int] = field(default_factory=list)
    order: str = "ranked"
    content_type: str = "anime"   # "anime" | "manga"

    # ── Серверная часть ────────────────────────────────────────────────────
    def to_server_params(self) -> dict[str, str]:
        """Параметры, которые умеет сам Shikimori (экономят трафик/время)."""
        params: dict[str, str] = {}
        if self.query.strip():
            params["search"] = self.query.strip()
        if self.kind in kinds_for(self.content_type):
            params["kind"] = self.kind
        if self.status in statuses_for(self.content_type):
            params["status"] = self.status
        if self.order in ORDERS:
            params["order"] = self.order
        if self.genres:
            params["genre"] = ",".join(str(g) for g in self.genres)
        # Сервер принимает только МИНИМАЛЬНУЮ оценку и целым числом.
        if self.score_min is not None:
            params["score"] = str(int(self.score_min))
        # Сезон: один год → "YYYY", диапазон → "YYYY_YYYY".
        season = self._season_param()
        if season:
            params["season"] = season
        return params

    def _season_param(self) -> str:
        lo, hi = self.year_from, self.year_to
        if lo and hi:
            return f"{min(lo, hi)}_{max(lo, hi)}"
        if lo:
            return str(lo)
        if hi:
            return str(hi)
        return ""

    # ── Локальная часть ────────────────────────────────────────────────────
    def matches_local(self, a: Anime) -> bool:
        """Точная проверка одного аниме под ВСЕ критерии (то, что сервер не
        гарантирует). Безопасно вызывать на любом наборе из API."""
        if self.score_min is not None and a.score < self.score_min:
            return False
        if self.score_max is not None and a.score > self.score_max:
            return False
        if self.episodes_min is not None and a.episodes < self.episodes_min:
            return False
        if self.episodes_max is not None and a.episodes and a.episodes > self.episodes_max:
            return False
        if self.year_from is not None or self.year_to is not None:
            y = a.year
            if y is None:
                return False
            if self.year_from is not None and y < self.year_from:
                return False
            if self.year_to is not None and y > self.year_to:
                return False
        return True

    def validate(self) -> Optional[str]:
        """Возвращает текст ошибки, если критерии противоречивы, иначе None."""
        if (self.score_min is not None and self.score_max is not None
                and self.score_min > self.score_max):
            return "Минимальная оценка больше максимальной."
        if (self.episodes_min is not None and self.episodes_max is not None
                and self.episodes_min > self.episodes_max):
            return "Минимум эпизодов больше максимума."
        if (self.year_from is not None and self.year_to is not None
                and self.year_from > self.year_to):
            return "Год «с» больше года «по»."
        return None


class ShikimoriApiClient:
    """Тонкий клиент Shikimori REST API v1.

    Особенности:
      • requests.Session с обязательным User-Agent (Shikimori без него отдаёт 403);
      • таймауты (connect, read) на каждый запрос;
      • ретраи на 429/5xx с уважением Retry-After и экспоненциальным backoff;
      • опциональный OAuth-токен (Bearer) — для приватных эндпоинтов; публичный
        поиск работает и без него.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 user_agent: str = DEFAULT_USER_AGENT,
                 token: Optional[str] = None,
                 timeout: tuple[float, float] = (5.0, 15.0),
                 max_retries: int = 3,
                 session: Optional["Session"] = None):
        if not _HAS_REQUESTS:
            raise ShikimoriError(
                "Не установлен пакет requests — добавьте его в окружение.")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    # ── Низкоуровневый GET с ретраями ──────────────────────────────────────
    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = self.base_url + path
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.Timeout as e:
                last_err = ShikimoriError(f"Таймаут запроса к Shikimori: {e}")
            except requests.RequestException as e:
                last_err = ShikimoriError(f"Сетевая ошибка: {e}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as e:
                        raise ShikimoriError(f"Некорректный JSON от сервера: {e}")
                # 429/5xx — временные, повторяем с задержкой.
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = ShikimoriError(
                        f"Сервер вернул {resp.status_code}.")
                    delay = self._retry_delay(resp, attempt)
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        continue
                else:
                    # 4xx, кроме 429 — повтор не поможет.
                    raise ShikimoriError(
                        f"Запрос отклонён сервером (HTTP {resp.status_code}).")
            if attempt < self.max_retries:
                time.sleep(self._backoff(attempt))
        raise last_err or ShikimoriError("Неизвестная ошибка запроса.")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(8.0, 0.5 * (2 ** attempt))

    def _retry_delay(self, resp, attempt: int) -> float:
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return min(15.0, float(ra))
            except ValueError:
                pass
        return self._backoff(attempt)

    # ── Высокоуровневые методы ─────────────────────────────────────────────
    def search_titles(self, content_type: str = "anime", *, page: int = 1,
                      limit: int = 50, **params: Any) -> list[Anime]:
        """Один «страничный» запрос /api/animes или /api/mangas.
        limit ≤ 50 (ограничение API). content_type: "anime" | "manga"."""
        endpoint = "/api/mangas" if content_type == "manga" else "/api/animes"
        q = {"page": max(1, int(page)), "limit": max(1, min(50, int(limit)))}
        for k, v in params.items():
            if v not in (None, "", []):
                q[k] = v
        data = self._get(endpoint, q)
        if not isinstance(data, list):
            raise ShikimoriError("Ожидался список тайтлов, получено иное.")
        return [Anime.from_json(d, self.base_url) for d in data if isinstance(d, dict)]

    # Обратная совместимость со старым именем.
    def search_animes(self, *, page: int = 1, limit: int = 50,
                       **params: Any) -> list[Anime]:
        return self.search_titles("anime", page=page, limit=limit, **params)

    def get_anime(self, anime_id: int) -> dict:
        """Полная карточка одного аниме (сырой словарь)."""
        data = self._get(f"/api/animes/{int(anime_id)}")
        if not isinstance(data, dict):
            raise ShikimoriError("Ожидалась карточка аниме, получено иное.")
        return data

    def genres(self, content_type: str = "anime") -> list[dict]:
        """Список жанров (id/name/russian) для выпадающего фильтра.
        Жанры аниме и манги частично различаются — фильтруем по kind."""
        data = self._get("/api/genres")
        if not isinstance(data, list):
            return []
        return [g for g in data if isinstance(g, dict)
                and (g.get("kind") in (None, content_type))]

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def find_anime(client: ShikimoriApiClient, criteria: AnimeFilter, *,
               max_pages: int = 200, per_page: int = 50,
               progress: Optional[Any] = None,
               on_batch: Optional[Any] = None,
               should_stop: Optional[Any] = None) -> list[Anime]:
    """Высокоуровневый поиск: серверная фильтрация с пагинацией + локальная
    доводка под полный набор критериев.

    Листает страницы ПОДРЯД, пока не дойдёт до последней (сервер отдал меньше
    per_page), не упрётся в max_pages или пока вызывающая сторона не попросит
    остановиться через should_stop(). Раннего «хватит» по числу результатов НЕТ:
    поиск идёт «до конца или до Стоп» (как просил пользователь).

    • max_pages — жёсткий потолок (страховка от выкачивания всей базы).
    • progress(page, matched) — необязательный колбэк прогресса.
    • on_batch(new_matches: list[Anime]) — колбэк с НОВЫМИ подходящими тайтлами
      каждой страницы (для потокового наполнения списка в UI).
    • should_stop() -> bool — необязательная остановка (кнопка «Стоп»).
    """
    server_params = criteria.to_server_params()
    ctype = criteria.content_type
    matched: list[Anime] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        if should_stop is not None and should_stop():
            break
        batch = client.search_titles(ctype, page=page, limit=per_page,
                                     **server_params)
        new_matches: list[Anime] = []
        for a in batch:
            if a.id in seen:
                continue
            seen.add(a.id)
            if criteria.matches_local(a):
                matched.append(a)
                new_matches.append(a)
        if on_batch is not None and new_matches:
            try:
                on_batch(new_matches)
            except Exception:
                pass
        if progress is not None:
            try:
                progress(page, len(matched))
            except Exception:
                pass
        if len(batch) < per_page:
            break  # последняя страница
    return matched


# Удобный шорткат под пример из ТЗ: find_anime(query, max_score=6, …)
def quick_find(query: str = "", *, max_score: Optional[float] = None,
               min_score: Optional[float] = None,
               kind: str = "", status: str = "",
               year_from: Optional[int] = None, year_to: Optional[int] = None,
               episodes_min: Optional[int] = None,
               episodes_max: Optional[int] = None,
               genres: Optional[Iterable[int]] = None,
               client: Optional[ShikimoriApiClient] = None,
               **find_kwargs: Any) -> list[Anime]:
    """Однострочный поиск без ручного создания клиента/фильтра.
    Пример: quick_find("наруто", max_score=6)."""
    own_client = client is None
    client = client or ShikimoriApiClient()
    try:
        flt = AnimeFilter(
            query=query, kind=kind, status=status,
            year_from=year_from, year_to=year_to,
            score_min=min_score, score_max=max_score,
            episodes_min=episodes_min, episodes_max=episodes_max,
            genres=list(genres) if genres else [],
        )
        return find_anime(client, flt, **find_kwargs)
    finally:
        if own_client:
            client.close()
