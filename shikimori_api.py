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
#
# ВАЖНО: Shikimori отдаёт `name` в rates_statuses_stats ЛОКАЛИЗОВАННОЙ строкой
# (по умолчанию по-русски: «Просмотрено»/«Смотрю»/«Брошено»…), а НЕ английским
# ключом. Поэтому матчим и английские ключи, и русские подписи (аниме и манга:
# «Прочитано»/«Читаю»). Сравнение регистронезависимое (см. views_from_card).
VIEW_STATUSES = frozenset({
    "completed", "watching", "dropped",          # английские ключи (на всякий)
    "просмотрено", "смотрю", "брошено",          # русские подписи (аниме)
    "прочитано", "читаю",                        # русские подписи (манга)
})


def views_from_card(card: dict) -> int:
    """Считает «просмотры» (completed+watching+dropped) из карточки тайтла.
    Запланировано/отложено НЕ учитываются. При отсутствии данных вернёт 0."""
    if not isinstance(card, dict):
        return 0
    total = 0
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        if name in VIEW_STATUSES:
            try:
                total += int(s.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return total


# Веса статусов для «индекса популярности» (по просьбе пользователя): сколько
# «баллов» индекса даёт один пользователь из каждого списка. Реально смотревшие
# весомее планирующих. name в rates_statuses_stats приходит ЛОКАЛИЗОВАННЫМ (RU)
# или английским ключом — матчим оба, регистронезависимо (ср. VIEW_STATUSES).
_INDEX_STATUS_WEIGHTS = {
    "completed": 10.0, "просмотрено": 10.0, "прочитано": 10.0,   # просмотрено
    "watching": 8.0,   "смотрю": 8.0,       "читаю": 8.0,         # смотрю
    "dropped": 6.0,    "брошено": 6.0,                            # брошено
    "on_hold": 6.0,    "отложено": 6.0,                           # отложено
    "planned": 2.0,    "запланировано": 2.0,                      # запланировано
}


def index_base_from_card(card: dict) -> float:
    """Взвешенная «база индекса» из rates_statuses_stats: каждый пользователь
    даёт столько баллов, сколько весит его статус (просмотрено=10, смотрю=8,
    брошено/отложено=6, запланировано=2). При отсутствии данных вернёт 0."""
    if not isinstance(card, dict):
        return 0.0
    total = 0.0
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        w = _INDEX_STATUS_WEIGHTS.get(name)
        if w:
            try:
                total += w * int(s.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return total


# Каноничные RU-подписи статусов для разбивки индекса в подсказке (агрегируют и
# английские ключи, и локализованные имена аниме/манги к одной подписи).
_INDEX_STATUS_LABELS = {
    "completed": "Просмотрено", "просмотрено": "Просмотрено", "прочитано": "Прочитано",
    "watching": "Смотрю", "смотрю": "Смотрю", "читаю": "Читаю",
    "dropped": "Брошено", "брошено": "Брошено",
    "on_hold": "Отложено", "отложено": "Отложено",
    "planned": "В планах", "запланировано": "В планах",
}


def index_components_from_card(card: dict) -> list[tuple[str, float, int]]:
    """Разбивка «базы индекса» по статусам для подсказки: список кортежей
    (подпись, взвешенный_вклад, число_людей) по убыванию вклада. Подпись —
    каноничная RU (см. _INDEX_STATUS_LABELS). Возвращает только статусы с
    ненулевым числом людей; сумма взвешенных вкладов == index_base_from_card."""
    if not isinstance(card, dict):
        return []
    agg: dict[str, list] = {}  # подпись -> [взвешенный_вклад, число_людей]
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        w = _INDEX_STATUS_WEIGHTS.get(name)
        if not w:
            continue
        try:
            cnt = int(s.get("value") or 0)
        except (TypeError, ValueError):
            cnt = 0
        if cnt <= 0:
            continue
        label = _INDEX_STATUS_LABELS.get(name, name.capitalize())
        cur = agg.setdefault(label, [0.0, 0])
        cur[0] += w * cnt
        cur[1] += cnt
    out = [(label, wv, cnt) for label, (wv, cnt) in agg.items()]
    out.sort(key=lambda x: x[1], reverse=True)
    return out


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


# ── Группировка жанров: Жанры / Темы / Демография ────────────────────────────
# Shikimori /api/genres отдаёт «классический» набор, где у ВСЕХ записей
# kind == "genre" (тип аниме/манга — в entry_type). Сам сайт Shikimori делит
# этот набор на «Жанры», «Темы» и «Демография». Поскольку REST не присылает эту
# принадлежность, классифицируем по стабильному английскому имени (одинаково для
# аниме и манги). Если же будущий API вернёт kind="theme"/"demographic" — доверяем
# ему (см. genre_group).
GROUP_GENRE = "genre"
GROUP_THEME = "theme"
GROUP_DEMOGRAPHIC = "demographic"

GENRE_GROUP_LABELS = {
    GROUP_GENRE: "Жанры",
    GROUP_THEME: "Темы",
    GROUP_DEMOGRAPHIC: "Демография",
}
# Порядок показа групп в интерфейсе.
GENRE_GROUP_ORDER = (GROUP_GENRE, GROUP_THEME, GROUP_DEMOGRAPHIC)

# Возрастные категории Shikimori.
_DEMOGRAPHIC_NAMES = frozenset({
    "kids", "shoujo", "shounen", "seinen", "josei",
})
# «Темы» (по классификации Shikimori/MAL): сеттинг/мотив, а не жанр.
_THEME_NAMES = frozenset({
    "cars", "demons", "game", "historical", "magic", "martial arts", "mecha",
    "music", "parody", "police", "samurai", "school", "space", "super power",
    "vampire", "harem", "military", "work life", "gender bender",
})


def genre_group(genre: dict) -> str:
    """К какой группе отнести жанр из /api/genres: "genre"/"theme"/"demographic".

    Сначала смотрим на kind (если API уже различает темы/демографию), иначе
    классифицируем по английскому имени (стабильно для аниме и манги)."""
    kind = str((genre or {}).get("kind") or "").strip().lower()
    if kind in (GROUP_THEME, GROUP_DEMOGRAPHIC):
        return kind
    name = str((genre or {}).get("name") or "").strip().lower()
    if name in _DEMOGRAPHIC_NAMES:
        return GROUP_DEMOGRAPHIC
    if name in _THEME_NAMES:
        return GROUP_THEME
    return GROUP_GENRE


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

    @property
    def air_date(self):
        """Дата выхода как datetime.date (по aired_on/released_on, YYYY-MM-DD) для
        ТОЧНОГО расчёта «свежести» индекса по дню/месяцу, а не только году. Если
        день/месяц неизвестны — подставляем 1-е/январь; если даты нет — None."""
        import datetime as _dt
        for src in (self.aired_on, self.released_on):
            if not src or len(src) < 4 or not src[:4].isdigit():
                continue
            parts = str(src).split("-")
            try:
                y = int(parts[0])
                m = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 1
                d = int(parts[2][:2]) if len(parts) >= 3 and parts[2][:2].isdigit() else 1
                m = min(12, max(1, m)); d = min(28, max(1, d)) if m == 2 else min(31, max(1, d))
                return _dt.date(y, m, d)
            except (ValueError, IndexError):
                continue
        return None

    # Русские названия месяцев (родительный падеж) и сезонов — для date_label.
    _MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря")
    _SEASONS_RU = ("Зима", "Зима", "Весна", "Весна", "Весна", "Лето",
                   "Лето", "Лето", "Осень", "Осень", "Осень", "Зима")

    @property
    def date_label(self) -> str:
        """Дата выхода для показа, как можно точнее:
        «12 апреля 2019» (есть день+месяц) → «Весна 2019» (есть месяц) →
        «2019» (только год) → «» (даты нет)."""
        src = self.aired_on or self.released_on
        if not src or len(src) < 4 or not src[:4].isdigit():
            return ""
        y = src[:4]
        parts = src.split("-")
        mm = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
        dd = int(parts[2][:2]) if len(parts) >= 3 and parts[2][:2].isdigit() else 0
        if 1 <= mm <= 12 and dd >= 1:
            return f"{dd} {self._MONTHS_RU[mm - 1]} {y}"
        if 1 <= mm <= 12:
            return f"{self._SEASONS_RU[mm - 1]} {y}"
        return y

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
    exclude_genres: list[int] = field(default_factory=list)
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
        # Жанры/темы: включаемые — id, исключаемые — с префиксом «!» (так Shikimori
        # помечает исключение), всё в одном параметре. Используем genre_v2 —
        # современный параметр, который понимает ПОЛНЫЙ набор id жанров/тем/
        # демографий (включая «Reincarnation» и прочие новые темы из GraphQL).
        # Старый «genre» знает лишь легаси-набор и для новых id отдаёт пусто.
        if self.genres or self.exclude_genres:
            parts = [str(g) for g in self.genres]
            parts += [f"!{g}" for g in self.exclude_genres]
            params["genre_v2"] = ",".join(parts)
        # Сервер принимает только МИНИМАЛЬНУЮ оценку и целым числом.
        if self.score_min is not None:
            params["score"] = str(int(self.score_min))
        # Сезон: один год → "YYYY", диапазон → "YYYY_YYYY".
        season = self._season_param()
        if season:
            params["season"] = season
        return params

    def _season_param(self) -> str:
        # ВАЖНО: одиночный год ("2017") сервер трактует как РОВНО этот год, а НЕ
        # «до/от». Поэтому открытую границу разворачиваем в ДИАПАЗОН ("1900_2017" /
        # "2017_2027"), иначе «Год по 2017» искал только 2017 (и «Год с 2017» —
        # тоже только 2017). Точную отсечку всё равно делает matches_local.
        import datetime as _dt
        lo, hi = self.year_from, self.year_to
        if lo and hi:
            return f"{min(lo, hi)}_{max(lo, hi)}"
        if lo:
            # «От lo» — от lo до следующего года (захватываем и анонсы).
            hi_open = max(int(lo), _dt.date.today().year + 1)
            return f"{lo}_{hi_open}"
        if hi:
            # «До hi» — от ранней эпохи аниме до hi.
            return f"{min(1900, int(hi))}_{hi}"
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

    # ── GraphQL POST (для полного списка жанров/тем) ───────────────────────
    def _graphql(self, query: str, variables: Optional[dict] = None) -> Any:
        """POST к /api/graphql с ретраями. Сами обрабатываем редирект (301/302/
        307/308): requests на 301 превращает POST→GET и теряет тело, поэтому
        перепосылаем тело на адрес из Location (домен Shikimori мигрирует между
        .one/.io). Возвращает содержимое поля data или бросает ShikimoriError."""
        from urllib.parse import urljoin
        url = self.base_url + "/api/graphql"
        payload = {"query": query, "variables": variables or {}}
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.post(
                    url, json=payload, timeout=self.timeout, allow_redirects=False)
                # Следуем за редиректом ВРУЧНУЮ, сохраняя метод POST и тело.
                hops = 0
                while resp.status_code in (301, 302, 307, 308) and hops < 4:
                    loc = resp.headers.get("Location")
                    if not loc:
                        break
                    nurl = urljoin(resp.url, loc)
                    resp = self._session.post(
                        nurl, json=payload, timeout=self.timeout,
                        allow_redirects=False)
                    hops += 1
            except requests.Timeout as e:
                last_err = ShikimoriError(f"Таймаут запроса к Shikimori: {e}")
            except requests.RequestException as e:
                last_err = ShikimoriError(f"Сетевая ошибка: {e}")
            else:
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError as e:
                        raise ShikimoriError(f"Некорректный JSON от сервера: {e}")
                    if isinstance(body, dict) and body.get("errors"):
                        msg = body["errors"][0].get("message", "GraphQL error") \
                            if isinstance(body["errors"], list) and body["errors"] \
                            else "GraphQL error"
                        raise ShikimoriError(f"GraphQL: {msg}")
                    return (body or {}).get("data") if isinstance(body, dict) else None
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = ShikimoriError(f"Сервер вернул {resp.status_code}.")
                    if attempt < self.max_retries:
                        time.sleep(self._retry_delay(resp, attempt))
                        continue
                else:
                    raise ShikimoriError(
                        f"GraphQL отклонён сервером (HTTP {resp.status_code}).")
            if attempt < self.max_retries:
                time.sleep(self._backoff(attempt))
        raise last_err or ShikimoriError("Неизвестная ошибка GraphQL-запроса.")

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
        """Полный список жанров/тем/демографий (id/name/russian/kind) для фильтра.

        Берём через GraphQL (`genres(entryType: …)`): только он отдаёт СОВРЕМЕННЫЙ
        набор с правильным `kind` ("genre"/"theme"/"demographic") и id, понятными
        параметру genre_v2 поиска. Это даёт ВСЕ темы (включая «Reincarnation»,
        «Isekai» и т.п.), которых нет в легаси /api/genres.

        Если GraphQL недоступен — откатываемся на REST /api/genres (легаси-набор,
        классифицируется по имени в genre_group)."""
        ct = (content_type or "anime").lower()
        entry = "Manga" if ct == "manga" else "Anime"
        try:
            data = self._graphql(
                "query($e: GenreEntryTypeEnum!){ genres(entryType: $e){ "
                "id name russian kind } }", {"e": entry})
            glist = (data or {}).get("genres") if isinstance(data, dict) else None
            if isinstance(glist, list) and glist:
                out = []
                for g in glist:
                    if not isinstance(g, dict):
                        continue
                    # id из GraphQL приходит строкой — нормализуем к int.
                    try:
                        gid = int(g.get("id"))
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "id": gid,
                        "name": g.get("name") or "",
                        "russian": g.get("russian") or "",
                        "kind": (g.get("kind") or "genre"),
                    })
                if out:
                    return out
        except ShikimoriError:
            pass  # тихий откат на REST ниже

        # Откат: легаси REST (без новых тем; kind всегда "genre").
        data = self._get("/api/genres")
        if not isinstance(data, list):
            return []
        out = []
        for g in data:
            if not isinstance(g, dict):
                continue
            et = str(g.get("entry_type") or "").lower()
            if et:
                if et == ct:
                    out.append(g)
            elif g.get("kind") in (None, content_type):  # совместимость со старым API
                out.append(g)
        return out

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def find_anime(client: ShikimoriApiClient, criteria: AnimeFilter, *,
               max_pages: int = 200, per_page: int = 50,
               throttle: float = 0.0,
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
    • throttle — пауза (сек) между страницами, чтобы не упереться в лимит
      Shikimori на длинной выдаче. 0 — без паузы.
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
        try:
            batch = client.search_titles(ctype, page=page, limit=per_page,
                                         **server_params)
        except ShikimoriError:
            # Временная ошибка (обычно 429 на большой глубине выдачи): если уже
            # что-то набрали — отдаём накопленное, а не теряем весь поиск. На
            # самой первой странице ошибка реальна — пробрасываем дальше.
            if matched:
                break
            raise
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
        if throttle > 0:
            # Дробим паузу, чтобы «Стоп» срабатывал быстро.
            slept = 0.0
            while slept < throttle:
                if should_stop is not None and should_stop():
                    break
                time.sleep(min(0.1, throttle - slept))
                slept += 0.1
    return matched


# Удобный шорткат под пример из ТЗ: find_anime(query, max_score=6, …)
def quick_find(query: str = "", *, max_score: Optional[float] = None,
               min_score: Optional[float] = None,
               kind: str = "", status: str = "",
               year_from: Optional[int] = None, year_to: Optional[int] = None,
               episodes_min: Optional[int] = None,
               episodes_max: Optional[int] = None,
               genres: Optional[Iterable[int]] = None,
               exclude_genres: Optional[Iterable[int]] = None,
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
            exclude_genres=list(exclude_genres) if exclude_genres else [],
        )
        return find_anime(client, flt, **find_kwargs)
    finally:
        if own_client:
            client.close()
