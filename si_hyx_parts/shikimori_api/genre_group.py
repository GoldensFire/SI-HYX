# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""genre_group. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def genre_group(genre: dict) -> str:
    """К какой группе отнести жанр из /api/genres: "genre"/"theme"/"demographic".

    Сначала смотрим на kind (если API уже различает темы/демографию), иначе
    классифицируем по английскому имени (стабильно для аниме и манги)."""
    kind = str((genre or {}).get("kind") or "").strip().lower()
    if kind in (_api.GROUP_THEME, _api.GROUP_DEMOGRAPHIC):
        return kind
    name = str((genre or {}).get("name") or "").strip().lower()
    if name in _api._DEMOGRAPHIC_NAMES:
        return _api.GROUP_DEMOGRAPHIC
    if name in _api._THEME_NAMES:
        return _api.GROUP_THEME
    return _api.GROUP_GENRE

genre_group.__module__ = _api.__name__
_api.genre_group = genre_group

class ShikimoriError(Exception):
    """Любая ошибка обращения к Shikimori API (сеть, таймаут, не-2xx, разбор)."""

ShikimoriError.__module__ = _api.__name__
_api.ShikimoriError = ShikimoriError

@_api.dataclass(slots=True)
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
    aired_on: _api.Optional[str]
    released_on: _api.Optional[str]
    image_url: str
    url: str

    @property
    def title(self) -> str:
        """Заголовок для показа: русский, если есть, иначе оригинал."""
        return self.russian or self.name

    @property
    def year(self) -> _api.Optional[int]:
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
    def from_json(cls, d: dict, base_url: str = _api.DEFAULT_BASE_URL) -> '_api.Anime':
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

Anime.__module__ = _api.__name__
_api.Anime = Anime

@_api.dataclass
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
    year_from: _api.Optional[int] = None
    year_to: _api.Optional[int] = None
    score_min: _api.Optional[float] = None
    score_max: _api.Optional[float] = None
    episodes_min: _api.Optional[int] = None
    episodes_max: _api.Optional[int] = None
    genres: list[int] = _api.field(default_factory=list)
    exclude_genres: list[int] = _api.field(default_factory=list)
    order: str = "ranked"
    content_type: str = "anime"   # "anime" | "manga"

    # ── Серверная часть ────────────────────────────────────────────────────
    def to_server_params(self) -> dict[str, str]:
        """Параметры, которые умеет сам Shikimori (экономят трафик/время)."""
        params: dict[str, str] = {}
        if self.query.strip():
            params["search"] = self.query.strip()
        if self.kind in _api.kinds_for(self.content_type):
            params["kind"] = self.kind
        if self.status in _api.statuses_for(self.content_type):
            params["status"] = self.status
        if self.order in _api.ORDERS:
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
    def matches_local(self, a: _api.Anime) -> bool:
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

    def validate(self) -> _api.Optional[str]:
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

AnimeFilter.__module__ = _api.__name__
_api.AnimeFilter = AnimeFilter
