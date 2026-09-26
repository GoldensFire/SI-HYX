# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FandomApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


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

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        # Fandom спокойно держит и больше, но статей на пак нужны единицы.
        self.limiter = _api.RateLimiter(2)
        # Уже опрошенные адреса: {поддомен: хост или «»}. Один и тот же тайтл
        # (а с ним и его франшиза) попадается в паке не раз.
        self._wikis: dict[str, str] = {}
        self._wikis_lock = _api.threading.Lock()

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
            raise _api._friendly(e, f"Fandom ({host})") from e
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
                f"https://{slug}.{_api.FANDOM_HOST}/api.php",
                params={"action": "query", "meta": "siteinfo",
                        "format": "json", "formatversion": "2"},
                timeout=(10, 30))
            if resp.status_code == 200:
                name = (((resp.json().get("query") or {}).get("general") or {})
                        .get("sitename") or "")
                if name:
                    host = _api.re.sub(r"^https?://", "",
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
        побеждает.

        Адрес из ОДНОГО слова названия («evangelion» для «Neon Genesis
        Evangelion») проверяется отдельно, поиском по самому названию. Без
        проверки на нём и ломалось: у «Mushoku Tensei: Jobless Reincarnation»
        самое длинное слово — «reincarnation», а reincarnation.fandom.com
        оказалась вики про чужую игру, и вопрос уехал в её сюжет (просьба
        пользователя)."""
        if isinstance(names, str):
            names = [names]
        for name in names or ():
            slugs = _api.wiki_slugs(name)
            # Адрес-одиночка идёт в списке последним и только третьим: первые
            # два собраны из ПОЛНОГО названия, и проверять их незачем.
            lone = len(slugs) - 1 if len(slugs) > 2 else -1
            for number, slug in enumerate(slugs):
                host = self.wiki_at(slug)
                if not host:
                    continue
                if number == lone and not self._fits(host, name):
                    continue
                return host
        return ""

    # Сколько букв слова значимы при сверке названия со статьями вики.
    WORD_MIN = 4

    @staticmethod
    def _words(text: str) -> set:
        return {w for w in _api.re.split(r"[^0-9a-zA-Zа-яёА-ЯЁ]+",
                                         str(text or "").casefold())
                if len(w) >= FandomApi.WORD_MIN}

    def _fits(self, host: str, name: str) -> bool:
        """Есть ли на вики статья про ЭТОТ тайтл.

        Один поиск по названию: у своей вики название стоит в заголовке статьи
        (а то и в заглавной), у чужой не находится ничего похожего. Спрашиваем
        только про адреса-одиночки — полное название в адресе говорит само за
        себя."""
        wanted = self._words(name)
        if not wanted:
            return False
        try:
            pages = self.search(host, name, limit=5)
        except _api.AnimePackApiError:
            return False
        for page in pages:
            if len(wanted & self._words(page)) * 2 >= len(wanted):
                return True
        return False

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
            except _api.AnimePackApiError:
                continue
            if names:
                break
        if not names:
            for word in ("episode", "серия"):
                try:
                    names += self.search(host, word)
                except _api.AnimePackApiError:
                    continue
        out, seen = [], set()
        for name in names:
            if _api._EPISODE_LIST.search(name):
                continue
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                out.append(name)
        return out

    # ── шаг 3: текст страницы ─────────────────────────────────────────────
    def page_source(self, host: str, page: str) -> str:
        """Разметка страницы как есть («» — не получилось).

        Нужна отдельно от `page_text`: пересказ читается очищенным, а вот
        инфобокс серии (`|season number=4`) чистка сносит вместе со всеми
        шаблонами, — а из него и берётся номер сезона (см. plot_season)."""
        try:
            data = self._api(host, {"action": "parse", "page": page,
                                    "prop": "wikitext", "redirects": 1})
        except _api.AnimePackApiError:
            return ""
        raw = ((data.get("parse") or {}).get("wikitext") or "")
        if isinstance(raw, dict):          # formatversion=1 отдаёт {"*": "…"}
            raw = raw.get("*") or ""
        return str(raw)

    def page_text(self, host: str, page: str) -> str:
        """Текст страницы без разметки («» — не получилось)."""
        return _api.strip_wikitext(self.page_source(host, page))

    def plot_section(self, text: str) -> str:
        """Кусок статьи с пересказом («» — такого раздела нет).

        Разделы размечены как «== Summary ==». Берём первый подходящий по
        заголовку и всё до следующего заголовка того же уровня."""
        return _api.plot_section(text, self.PLOT_HEADINGS)[:self.MAX_TEXT]

def page_link(host: str, page: str) -> str:
    """Адрес страницы вики («» — нечего показывать).

    Уходит последней строкой ответа: вопрос по сюжету собран из пересказа, и
    ведущему надо видеть, откуда он взят (просьба пользователя). Пробелы в
    именах статей MediaWiki — это подчёркивания, остальное кодируется как
    обычно; двоеточия и скобки НЕ кодируем — так эти адреса пишет сама вики."""
    host = str(host or "").strip().strip("/")
    page = str(page or "").strip()
    if not host or not page:
        return ""
    slug = _api.quote(page.replace(" ", "_"), safe="/:()!,'")
    return f"https://{host}/wiki/{slug}"


FandomApi.__module__ = _api.__name__
page_link.__module__ = _api.__name__
_api.FandomApi = FandomApi
_api.fandom_page_link = page_link
