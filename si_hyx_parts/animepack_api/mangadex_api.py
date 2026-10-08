# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MangaDexApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api
from network_attempt import single_attempt_session


# Страницы в начале и в конце главы пропускаем: там титул с названием тайтла,
# страница команды перевода, оглавление, реклама и «продолжение следует».
# Название прямо в кадре решало бы вопрос с одного взгляда, а его печатают не
# только на первой странице — по пять штук с каждого края (просьба
# пользователя), иначе оно то и дело светилось в вопросе.
PANEL_SKIP_HEAD = 5
PANEL_SKIP_TAIL = 5
# Короче этого глава не годится: срезав хотя бы по странице с краёв, надо
# оставить, из чего выбирать.
MIN_PANEL_PAGES = 4


def page_skip(pages: int) -> int:
    """Сколько страниц срезать с каждого края главы этой длины.

    Жёсткие пять страниц годятся только для обычной главы. У ёнкомы («Признания»,
    Tsurezure Children) глава — пять-шесть страниц целиком, и прежнее правило
    «меньше одиннадцати страниц не берём» отбрасывало ВСЕ главы такого тайтла:
    в логе он выглядел как «страниц на MangaDex нет». Срез уменьшается вместе с
    главой, но нулевым не становится, пока есть что резать: титул с названием
    всё так же не должен попасть в вопрос.
    """
    count = int(pages or 0)
    if count >= PANEL_SKIP_HEAD + PANEL_SKIP_TAIL + 3:
        return PANEL_SKIP_HEAD
    if count >= 7:
        return 2
    if count >= MIN_PANEL_PAGES:
        return 1
    return 0
# Столько глав рассматриваем: брать весь список смысла нет, а у длинных серий
# он уходит за тысячу.
CHAPTER_LIMIT = 100
# Сколько глав одного языка пробуем, пока ищем свободную страницу, и сколько
# заходов за страницами делаем на тайтл всего: раздача страниц лимитируется
# строже остального API, и перебирать её без счёта нельзя.
CHAPTER_TRIES = 3
PAGE_TRIES = 9
# На каком языке брать главу, когда язык не задан («Любой»). Порядок не
# случайный: перевод на MangaDex бывает на трёх десятках языков, и без этого
# списка «Ван-Пис» приезжал каталанским разворотом. После русского пробуем
# английский и украинский; другие языки требуют явного выбора.
LANGUAGE_ORDER = ("ru", "en", "uk")
# Сколько лент (карточка + язык) спрашиваем на тайтл всего: без потолка редкий
# многоязычный тайтл выедал бы лимит запросов MangaDex в одиночку.
FEED_TRIES = 6

_PUNCT = _api.re.compile(
    r"[\s\-–—_:：!！?？.,，、。"
    r"'\"“”«»‘’()（）\[\]]+")
# Кириллица в поисковом запросе. Русское название на MangaDex не ищется (там
# ромадзи, английский и оригинал), а в synonyms Shikimori русских вариантов
# хватает: запрос на них — впустую потраченный заход к API. Для СВЕРКИ
# найденной карточки они остаются: у части тайтлов altTitles содержит «ru».
_CYRILLIC = _api.re.compile(r"[Ѐ-ӿ]")


def _norm(text) -> str:
    """Название без регистра, пробелов и служебных знаков — для сверки."""
    return _PUNCT.sub("", str(text or "")).casefold()


def _titles(attrs: dict) -> list[str]:
    """Все названия карточки MangaDex: основное и все альтернативные."""
    out = list((attrs.get("title") or {}).values())
    for row in (attrs.get("altTitles") or []):
        if isinstance(row, dict):
            out.extend(row.values())
    return [str(t) for t in out if t]


class MangaDexApi:
    """MangaDex: находит тайтл и отдаёт ссылку на случайную страницу главы.

    Вопросом по манге служит сама СТРАНИЦА оригинала, а не обложка: обложку
    игроки узнают по постеру из ответа, а разворот — только по рисовке и
    героям.

    Ключа нет, но правила жёсткие: не больше пяти запросов в секунду на весь
    сайт и отдельный, куда более скупой предел у раздачи страниц
    (`/at-home/server`). Поэтому у выдачи страниц свой ограничитель, а найденные
    главы держатся в памяти на всю генерацию.

    Возрастные метки MangaDex: safe, suggestive, erotica, pornographic. Порно не
    берём никогда; erotica — по галочке, потому что в неё попадает и вполне
    обычная сэйнэн-классика («Берсерк»).
    """

    SEARCH_LIMIT = 10

    def __init__(self, session: _api.Optional[_api.requests.Session] = None, *,
                 language: str = "", allow_erotica: bool = False,
                 rng=None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(2.5)
        # Раздача страниц лимитируется отдельно и строже самого API.
        self.pages_limiter = _api.RateLimiter(0.7, per_minute=35)
        self.language = str(language or "").strip()
        self.allow_erotica = bool(allow_erotica)
        self.rng = rng or _api.random.Random()
        self._manga: dict[int, str] = {}
        # Языки перевода, объявленные самой карточкой: по ним выбирается язык
        # глав ДО запроса ленты. Без этого лента отдаёт первую сотню глав со
        # всех языков сразу, и «Ван-Пис» приезжал португальским разворотом.
        self._langs: dict[str, list[str]] = {}
        self._titles_by_id: dict[str, list[str]] = {}
        self._chapters: dict[tuple[str, str], list[str]] = {}
        # Глава, из которой взят последний разворот: её адрес уходит последней
        # строкой ответа (просьба пользователя — видеть источник вопроса).
        # Читается сразу после panel_url, под тем же замком, что и выбор.
        self.last_chapter: str = ""
        self.last_titles: list[str] = []
        self._lock = _api.threading.Lock()

    # ── сеть ──────────────────────────────────────────────────────────────
    @property
    def ratings(self) -> list[str]:
        out = ["safe", "suggestive"]
        if self.allow_erotica:
            out.append("erotica")
        return out

    def _get(self, path: str, params: dict, limiter=None) -> dict:
        deadline = getattr(self, "deadline", None)
        if deadline is None:
            (limiter or self.limiter).acquire()
        else:
            (limiter or self.limiter).acquire(deadline=deadline)
        try:
            with single_attempt_session(self.session) as session:
                resp = session.get(f"{_api.MANGADEX_BASE}{path}",
                                   params=params, timeout=(5, 10))
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _api._friendly(e, "MangaDex") from e
        return data if isinstance(data, dict) else {}

    # ── поиск тайтла ──────────────────────────────────────────────────────
    def manga_id(self, card: dict) -> str:
        """id карточки MangaDex по карточке Shikimori («» — не нашлась).

        Сверяем в два круга: сперва по ссылке на MyAnimeList (у MangaDex она
        лежит прямо в карточке и врать не может), потом по точному совпадению
        любого из названий. Похожие по смыслу, но иначе названные тайтлы не
        берём вовсе: страница не той манги хуже, чем отсутствие вопроса."""
        try:
            mal = int(card.get("malId") or 0)
        except (TypeError, ValueError):
            mal = 0
        with self._lock:
            known = self._manga.get(mal) if mal else None
        if known is not None:
            return known
        # Порядок запросов: ромадзи, английское, японское — так карточка
        # MangaDex и подписана. Русского названия среди них нет намеренно.
        names = [card.get("name"), card.get("english"), card.get("japanese")]
        names += list(card.get("synonyms") or [])
        wanted = {_norm(n) for n in names if str(n or "").strip()}
        wanted.discard("")
        found = ""
        seen: set[str] = set()
        for name in names:
            query = " ".join(str(name or "").split())
            if not query or query.casefold() in seen:
                continue
            if _CYRILLIC.search(query):
                continue
            seen.add(query.casefold())
            data = self._get("/manga", {
                "title": query, "limit": self.SEARCH_LIMIT,
                "contentRating[]": self.ratings,
                "order[relevance]": "desc"})
            rows = [r for r in (data.get("data") or []) if isinstance(r, dict)]
            found = self._match(rows, mal, wanted)
            if found:
                self._remember_languages(rows, found)
                break
        if mal:
            with self._lock:
                self._manga[mal] = found
        return found

    def _remember_languages(self, rows: list, manga_id: str) -> None:
        for row in rows:
            if str(row.get("id") or "") != manga_id:
                continue
            langs = (row.get("attributes") or {}).get(
                "availableTranslatedLanguages") or []
            with self._lock:
                self._langs[manga_id] = [str(lang) for lang in langs if lang]
                self._titles_by_id[manga_id] = _titles(row.get("attributes") or {})
            return

    @staticmethod
    def _match(rows: list, mal: int, wanted: set) -> str:
        by_title = ""
        for row in rows:
            attrs = row.get("attributes") or {}
            link = str((attrs.get("links") or {}).get("mal") or "").strip()
            if mal and link and link == str(mal):
                return str(row.get("id") or "")
            if mal and link and link != str(mal):
                continue
            if not by_title and wanted:
                if any(_norm(t) in wanted for t in _titles(attrs)):
                    by_title = str(row.get("id") or "")
        return by_title

    # ── главы и страницы ──────────────────────────────────────────────────
    def chapters(self, manga_id: str, language: str = "") -> list[str]:
        """id читаемых глав тайтла на этом языке («» — на любом).

        Внешние ссылки (Manga Plus, Viz) и главы-пустышки отброшены: страниц у
        них нет, читать нечем."""
        key = str(manga_id or "")
        if not key:
            return []
        lang = str(language or "")
        with self._lock:
            known = self._chapters.get((key, lang))
        if known is not None:
            return list(known)
        params = {"limit": CHAPTER_LIMIT, "contentRating[]": self.ratings,
                  "order[chapter]": "asc", "includeEmptyPages": 0}
        if lang:
            params["translatedLanguage[]"] = [lang]
        data = self._get(f"/manga/{key}/feed", params)
        out = []
        for row in (data.get("data") or []):
            if not isinstance(row, dict):
                continue
            attrs = row.get("attributes") or {}
            if lang and attrs.get("translatedLanguage", lang) != lang:
                continue
            # Глава, которая лежит не на MangaDex (Manga Plus, Viz), приходит
            # с externalUrl и нулём страниц — читать её нам нечем.
            if attrs.get("externalUrl"):
                continue
            try:
                pages = int(attrs.get("pages") or 0)
            except (TypeError, ValueError):
                pages = 0
            if pages < MIN_PANEL_PAGES:
                continue
            if row.get("id"):
                out.append(str(row["id"]))
        with self._lock:
            self._chapters[(key, lang)] = list(out)
        return out

    def languages(self, manga_id: str) -> list[str]:
        """Языки глав по предпочтению — их и пробуем один за другим.

        Пустая русская лента уступает английской, затем украинской. Ленту без
        фильтра не берём: она может вернуть перевод на произвольном языке.
        Явно заданный язык отменяет перебор."""
        if self.language:
            return [self.language]
        return list(LANGUAGE_ORDER)

    def _plan(self, manga_id: str) -> list[tuple[str, str]]:
        """Пары «карточка, язык» в том порядке, в каком их стоит просить.

        Карточка всегда одна — найденная по MAL или по точному названию.
        Соседние записи выдачи с пометкой в скобках («… (Pre-Serialization)»)
        мы намеренно НЕ берём: пометка не гарантирует, что это та же вещь, а
        страница не той манги хуже, чем отсутствие вопроса (просьба
        пользователя). Число заходов ограничено — лента, как и всё у MangaDex,
        считается по запросам."""
        entry = str(manga_id)
        pairs = [(entry, lang) for lang in self.languages(entry)]
        rank = {lang: number for number, lang in enumerate(LANGUAGE_ORDER)}
        unfiltered = len(rank) + 1        # лента без фильтра — последним делом
        pairs.sort(key=lambda pair: rank.get(
            pair[1], len(rank) if pair[1] else unfiltered))
        plan = pairs[:FEED_TRIES]
        return plan

    def page_urls(self, chapter_id: str) -> list[str]:
        """Ссылки на страницы главы в исходном качестве."""
        data = self._get(f"/at-home/server/{chapter_id}", {},
                         limiter=self.pages_limiter)
        chapter = data.get("chapter") or {}
        base = str(data.get("baseUrl") or "").rstrip("/")
        digest = str(chapter.get("hash") or "")
        files = [str(f) for f in (chapter.get("data") or []) if f]
        if not (base and digest and files):
            return []
        return [f"{base}/data/{digest}/{name}" for name in files]

    def panel_url(self, card: dict, excluded=()) -> str:
        """Ссылка на страницу-разворот для вопроса («» — подходящей нет).

        Глава и страница выбираются случайно, а уже показанные страницы
        пропускаются: один и тот же тайтл в разных паках спрашивается разными
        разворотами. Язык при этом не случаен (см. languages).

        Пустая глава не останавливает перебор русского, английского и
        украинского переводов. Число заходов ограничено PAGE_TRIES: раздача
        страниц лимитируется строже всего остального API."""
        manga = self.manga_id(card)
        self.last_chapter = ""
        self.last_page_info = {}
        with self._lock:
            self.last_titles = list(self._titles_by_id.get(manga, []))
        if not manga:
            return ""
        blocked = {str(u).split("?")[0] for u in excluded}
        attempts = 0
        for entry, lang in self._plan(manga):
            chapters = list(self.chapters(entry, lang))
            self.rng.shuffle(chapters)
            for chapter in chapters[:CHAPTER_TRIES]:
                if attempts >= PAGE_TRIES:
                    return ""
                attempts += 1
                urls = self.page_urls(chapter)
                skip = page_skip(len(urls))
                body = urls[skip:len(urls) - skip] if skip else list(urls)
                free = [u for u in body if u.split("?")[0] not in blocked]
                if free:
                    self.last_chapter = str(chapter)
                    url = self.rng.choice(free)
                    index = urls.index(url)
                    self.last_page_info = {"neighbors": [
                        {"url": urls[index + step], "offset": step} for step in (-1, 1)
                        if 0 <= index + step < len(urls)]}
                    return url
        return ""


def chapter_link(chapter_id) -> str:
    """Страница главы на самом MangaDex («» — главы нет).

    Не адрес картинки: тот живёт на раздающем узле, через час протухает и
    ведущему ничего не говорит. Ссылка на главу открывается в браузере и
    показывает тот же разворот в контексте (просьба пользователя)."""
    key = str(chapter_id or "").strip()
    return f"https://mangadex.org/chapter/{key}" if key else ""

MangaDexApi.__module__ = _api.__name__
chapter_link.__module__ = _api.__name__
_api.MangaDexApi = MangaDexApi
_api.mangadex_chapter_link = chapter_link
