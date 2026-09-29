# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Small PixivPy adapter for safe anime illustration search and download."""
from __future__ import annotations

import io
import random
import threading

from PIL import Image


from pixiv_tag_rules import TagRules
# Планка качества: меньше этого числа «в закладках» — работа, которую не
# заметил никто, а короткая сторона меньше этого числа пикселей означает
# превью, а не сам рисунок.
#
# Закладка Pixiv — это и есть «лайк»: другого счётчика одобрения открытый
# API не отдаёт вовсе. Планка теперь настраивается прямо на вкладке
# («Арты Pixiv» → «Лайков не меньше»), а это число — её значение по
# умолчанию (просьба пользователя).
MIN_BOOKMARKS = 15
MIN_SIDE = 700
# Из скольких отобранных работ тянется случайная. Больше десятки нарочно: у
# заметного тайтла верхушка по закладкам не меняется годами, и пак за паком
# приходил один и тот же рисунок (просьба пользователя).
CHOICE_POOL = 40
# Сколько работ, прошедших планку, считается достаточным пулом для случайного
# выбора: пока их меньше, поиск продолжается. Ровно из-за отсутствия этого
# числа пул раньше состоял из ОДНОЙ работы — поиск останавливался на первой
# же годной, и «случайный» выбор возвращал её всегда.
MIN_CHOICES = 8

# Верхушка тега: адрес «популярного превью» Pixiv. Открыт и бесплатному ключу,
# отдаёт до тридцати самых закладочных работ тега одним запросом — в отличие
# от обычного поиска, которому sort=popular_desc без премиума молча заменяют
# на date_desc (проверено на живом API). Своего метода в PixivPy у него нет.
POPULAR_PATH = "/v1/search/popular-preview/illust"

# Сколько страниц обычного поиска пролистывать, пока не набрался пул, и по
# сколько работ на странице отдаёт Pixiv. Этот путь — запасной: он нужен
# малоизвестным тайтлам и узким режимам («только R-18», «только ИИ»).
SEARCH_PAGES = 6
SEARCH_PAGE_SIZE = 30
# Тег взрослых работ на самом Pixiv. В режиме «только R-18» он уходит прямо в
# запрос: поиск по полному совпадению тегов складывает слова через И.
R18_TAG = "R-18"
# Метка работ нейросети. В отличие от R-18 это обычный авторский тег, а не
# поле работы: у поиска Pixiv фильтра «только ИИ» нет вовсе, зато тег «AI生成»
# авторы ставят почти всегда — по нему приходят 30 работ нейросети из 30, и
# заметных, а не вчерашних (проверено на живом API).
AI_TAG = "AI生成"


# Что делать с R-18 и с работами, нарисованными нейросетью. «Только» — это
# просьба пользователя собрать пак ровно из таких артов.
MODES = ("exclude", "allow", "only")
MODE_LABELS = {"exclude": "Исключать", "allow": "Разрешать", "only": "Только их"}


def mode_of(value, exclude_default: bool = True) -> str:
    """Режим из настроек. Пустое — из старой галочки «исключать»."""
    mode = str(value or "").strip().lower()
    if mode in MODES:
        return mode
    return "exclude" if exclude_default else "allow"


class PixivArtError(Exception):
    """One title has no suitable illustration."""


class PixivArtUnavailable(PixivArtError):
    """Authentication or the service failed; stop Pixiv work for this run."""


def validate_settings(refresh_token) -> list[str]:
    if str(refresh_token or "").strip():
        return []
    return ["Арты Pixiv: добавьте refresh token Pixiv в Настройках → Ключи API."]


def _value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


from pixiv_titles import MIN_TITLE_TAG, card_titles, norm_title
from pixiv_art_match import conflicting_series

def _art_link(illust) -> str:
    """Страница работы на Pixiv («» — id неизвестен)."""
    try:
        number = int(_value(illust, "id", 0) or 0)
    except (TypeError, ValueError):
        return ""
    return f"https://www.pixiv.net/artworks/{number}" if number > 0 else ""


def _image_extension(data: bytes) -> str:
    if not data or len(data) > 32 * 1024 * 1024:
        raise PixivArtError("Pixiv вернул пустую или слишком большую картинку.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(
                image.format)
            if not ext or min(image.size) < 256:
                raise ValueError("unexpected image")
            image.verify()
            return ext
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise PixivArtError("Pixiv вернул повреждённую картинку.") from exc


class PixivArtClient:
    """Authenticate lazily, filter Pixiv results, and return original bytes."""

    def __init__(self, refresh_token: str, *, api=None, stopped=None, rng=None,
                 exclude_r18=True, exclude_ai=True, r18_mode="", ai_mode="",
                 allow_same_sex=False, allow_manga=False, min_likes=None,
                 known_titles=None, settings=None):
        self.refresh_token = str(refresh_token or "").strip()
        self.api = api
        self.stopped = stopped or (lambda: False)
        self.rng = rng or random.Random()
        # Режимы главнее старых галочек: они и хранятся в настройках, а
        # exclude_* оставлены для прежних вызовов и тестов.
        self.r18_mode = mode_of(r18_mode, exclude_r18)
        self.ai_mode = mode_of(ai_mode, exclude_ai)
        # Работы про однополые пары — отдельной галочкой, по умолчанию их нет.
        self.allow_same_sex = bool(allow_same_sex)
        # Списки меток-исключений: встроенные группы плюс правки пользователя
        # с вкладки. Отсюда и хвост минусов для запроса, и отбор у себя.
        self.rules = TagRules.from_settings(settings, self.allow_same_sex)
        # Записи типа «манга» — комиксы из кадров с репликами. По умолчанию
        # мимо, но галочкой их можно пустить: в верхушке тега таких работ
        # треть, и без них выбор заметно уже (замерено: 66 работ из 210).
        self.allow_manga = bool(
            allow_manga or getattr(settings, "pixiv_allow_manga", False))
        # Планка лайков (закладок) — своя у каждого прогона: её задаёт
        # пользователь на вкладке. Ноль снимает планку совсем.
        if min_likes is None:
            min_likes = getattr(settings, "pixiv_min_likes", None)
        try:
            self.min_likes = max(0, int(MIN_BOOKMARKS if min_likes is None
                                        else min_likes))
        except (TypeError, ValueError):
            self.min_likes = MIN_BOOKMARKS
        self._authenticated = api is not None
        self._lock = threading.Lock()
        # Карточка, запрос и адрес работы, по которым нашёлся последний арт
        # (см. fetch).
        self.last_card: dict = {}
        self.last_query: str = ""
        self.last_link: str = ""
        self.last_illust = None
        # Что Pixiv вообще прислал за прогон: {"rows", "r18", "ai"}. По этим
        # числам вкладка и объясняет пустой прогон (см. pixiv_summary).
        self.stats: dict = {}
        # Названия ВСЕХ известных тайтлов — по ним узнаётся арт сразу по
        # нескольким сериалам (см. _foreign_title). Отдаётся набором или
        # функцией: собирать его заранее незачем, если артов в паке нет.
        self._known_titles = known_titles
        self._known_cache = None

    def _ensure_api(self):
        if self.stopped():
            raise PixivArtError("Загрузка арта Pixiv остановлена.")
        errors = validate_settings(self.refresh_token)
        if errors and self.api is None:
            raise PixivArtUnavailable(" ".join(errors))
        if self.api is None:
            try:
                from pixivpy3 import AppPixivAPI
            except ImportError:
                raise PixivArtUnavailable(
                    "Для Pixiv не установлен PixivPy3; переустановите зависимости SI-HYX.") from None
            self.api = AppPixivAPI()
        if not self._authenticated:
            try:
                self.api.auth(refresh_token=self.refresh_token)
            except Exception:
                raise PixivArtUnavailable(
                    "Pixiv не принял refresh token или сейчас недоступен.") from None
            self._authenticated = True

    @staticmethod
    def _tag_names(illust) -> set[str]:
        out = set()
        for tag in (_value(illust, "tags", []) or []):
            for key in ("name", "translated_name"):
                value = str(_value(tag, key, "") or "").strip().casefold()
                if value:
                    out.add(value)
        return out

    def _blocked_tag(self, illust) -> bool:
        """Есть ли у работы метка из списка исключений.

        Списки правит сам пользователь (окно «Исключаемые теги» на вкладке),
        поэтому проверка идёт через правила прогона, а не по жёстким
        константам. Шок-контент в правилах всегда: его выключить нельзя."""
        return self.rules.hits(self._tag_names(illust))

    def known_titles(self) -> set:
        """Названия всех тайтлов каталога — набором, собранным один раз."""
        if self._known_cache is None:
            source = self._known_titles
            try:
                names = source() if callable(source) else source
            except Exception:      # noqa: BLE001 — каталога может не быть
                names = None
            self._known_cache = {name for name in (names or ())
                                 if len(name) >= MIN_TITLE_TAG}
        return self._known_cache

    def _foreign_title(self, illust, own: set) -> bool:
        """Есть ли у работы метка с названием ДРУГОГО тайтла.

        Именно так в пак попал «2022春アニメ» — сезонная сборка, подписанная
        сразу пятью сериалами (SPY×FAMILY, «Летнее время», «Пари-пи Комэй»,
        «Дэнс Дэнс Дансэр», «Цубаки»): ни кроссовером, ни подборкой автор её
        не назвал, метки шок-списков не задел, страница всего одна — и все
        прежние проверки она прошла. Вопросом такая работа быть не может:
        правильных ответов у неё столько же, сколько сериалов на картинке.

        Узнаём по каталогу Shikimori: метка, совпавшая с названием тайтла,
        который мы НЕ искали, и есть «другой тайтл». Коротких названий не
        трогаем (см. MIN_TITLE_TAG): «Air» или «One» встречаются и обычным
        словом."""
        known = self.known_titles()
        if not known:
            return False
        for name in self._tag_names(illust):
            word = norm_title(name)
            if len(word) < MIN_TITLE_TAG or word in own:
                continue
            if word in known:
                return True
        return False

    def _good_enough(self, illust) -> bool:
        """Планка качества: замеченная одностраничная работа в хорошем размере.

        «Лайки» — те же закладки Pixiv, и порог у них свой на каждый прогон
        (настройка «Лайков не меньше»). У многостраничной публикации теги общие
        на все страницы: первая может быть по Fate, а тег, по которому работа
        нашлась, — от Hinako Note со второй страницы. Мы скачиваем только
        первую, поэтому безопасно брать лишь одностраничные работы."""
        try:
            side = min(int(_value(illust, "width", 0) or 0),
                       int(_value(illust, "height", 0) or 0))
            marks = int(_value(illust, "total_bookmarks", 0) or 0)
            pages = int(_value(illust, "page_count", 1) or 1)
        except (TypeError, ValueError):
            return False
        return side >= MIN_SIDE and marks >= self.min_likes and pages == 1

    @property
    def exclude_r18(self) -> bool:
        """Старое имя настройки — его ещё спрашивают снаружи."""
        return self.r18_mode == "exclude"

    @property
    def exclude_ai(self) -> bool:
        return self.ai_mode == "exclude"

    def _mode_ok(self, mode: str, matches: bool) -> bool:
        """Проходит ли работа режим «исключать / разрешать / только их»."""
        if mode == "exclude":
            return not matches
        if mode == "only":
            return matches
        return True

    def _safe(self, illust) -> bool:
        restrict = int(_value(illust, "x_restrict", 0) or 0)
        # R-18G и явные шок-метки не пускаются никогда. Обычный R-18 и работы
        # нейросети идут по своим режимам с вкладки.
        kinds = ("illust", "manga") if self.allow_manga else ("illust",)
        return (str(_value(illust, "type", "illust")) in kinds
                and restrict < 2
                and self._mode_ok(self.r18_mode, restrict == 1)
                and self._mode_ok(
                    self.ai_mode,
                    int(_value(illust, "illust_ai_type", 0) or 0) == 2)
                # Шок-контент, смесь франшиз, трёхмерка, наброски, фетиши,
                # работы без персонажа и прочее из списков исключений: по
                # такой работе тайтл не угадывается. Что именно отсекать —
                # решают настройки пака (см. pixiv_tag_rules).
                and not self._blocked_tag(illust)
                and bool(_value(illust, "visible", True)))

    @staticmethod
    def _url(illust) -> str:
        pages = _value(illust, "meta_pages", []) or []
        urls = _value(pages[0], "image_urls", {}) if pages else _value(
            illust, "image_urls", {})
        return str(_value(urls, "original") or _value(urls, "large") or "")

    @staticmethod
    def _titles(anime: dict, *also: dict):
        """Пары «карточка — название» в порядке поиска, без повторов.

        `also` — запасные карточки: генератор кладёт сюда сам тайтл, когда
        основным поиском идёт первый сезон его франшизы (на Pixiv тег висит на
        оригинале, см. _first_season_card). Порядок важен: сперва все названия
        первого сезона, и только потом названия сиквела."""
        seen = set()
        for card in (anime,) + also:
            for key in ("japanese", "name", "english", "russian"):
                word = " ".join(str((card or {}).get(key) or "").split())
                # Shikimori и Pixiv иногда пишут одну франшизу разными
                # звёздами. Самый заметный случай — Madoka: в карточке стоит
                # ``★``, а основной Pixiv-тег часто набран через ``☆``.
                # Для точного поиска это два совершенно разных тега.
                variants = (word, word.translate(str.maketrans("★☆", "☆★")))
                for variant in variants:
                    mark = variant.casefold()
                    if not variant or mark in seen:
                        continue
                    seen.add(mark)
                    yield card, variant

    def _queries(self, word: str) -> list[str]:
        """Запросы по одному названию — от самого узкого к простому.

        Режим R-18 задаётся прямо в поиске отдельным ТЕГОМ: у Pixiv поиск «по
        полному совпадению тега» складывает слова запроса через И, и «鬼滅の刃
        R-18» отдаёт сразу нужные работы, а не одну на сотню (просьба
        пользователя). Простой запрос остаётся запасным: если по связке тегов
        не нашлось НИЧЕГО, ищем по одному названию.

        Режим «только ИИ» сужается так же, но другим тегом (AI_TAG):
        собственного «только ИИ» у поиска Pixiv нет — его search_ai_type умеет
        лишь «скрыть работы нейросети», — а по тегу «AI生成» приходят ровно
        они, и заметные, а не вчерашние.

        МИНУСОВ ЗДЕСЬ НЕТ НАРОЧНО. Поиск «по полному совпадению тегов» их не
        понимает вовсе: проверено на живом API — «鬼滅の刃 -落書き» отдаёт РОВНО
        НОЛЬ работ, минус-слово идёт ещё одним обязательным тегом. Понимает их
        поиск «по части тега», и туда они и уходят — отдельным запросом (см.
        _minus_rows), потому что «часть тега» сама по себе неточна."""
        tags = []
        if self.r18_mode == "only":
            tags.append(R18_TAG)
        if self.ai_mode == "only":
            tags.append(AI_TAG)
        if not tags:
            return [word]
        out = [" ".join([word] + tags)]
        if len(tags) > 1:          # обе метки сразу — пробуем и по одной R-18
            out.append(f"{word} {R18_TAG}")
        out.append(word)
        return out

    # ── откуда берутся работы: три источника подряд ──────────────────
    from pixiv_art_search import (_popular_rows, _minus_rows, _exact_tags,
                                  _popular_illusts, _search_pages, _count)

    def _search_word(self, word: str, keep) -> list:
        """Подошедшие работы по одному названию тайтла.

        Три источника подряд, каждый следующий — только если пул ещё не
        набрался:

        1. верхушка тега по ТОЧНОЙ метке названия — один запрос, и почти
           всегда на этом всё и кончается;
        2. та же верхушка, но по части метки и с МИНУСАМИ: Pixiv сам
           выбрасывает лишнее, и тридцать мест выдачи не тратятся впустую;
        3. обычный постраничный поиск — для совсем малоизвестных тайтлов и
           для узких режимов («только R-18», «только ИИ»).

        Порядок не случаен: точный поиск даёт самый чистый пул, поэтому
        ухудшить его добор не может — он только добавляет."""
        for query in self._queries(word):
            rows = self._popular_rows(query, keep, self.stats)
            got = len(rows)
            if self._short(rows):
                rows = self._merge(rows,
                                   self._minus_rows(query, keep, self.stats))
            if self._short(rows):
                more, seen = self._search_pages(query, keep, self.stats)
                got += seen
                rows = self._merge(rows, more)
            if rows:
                self.last_query = query
                return rows
            if got:
                # Запрос ответил, но ничего не подошло — простой перебор тех
                # же страниц без тега R-18 лучше не сделает.
                break
        return []

    def _short(self, rows) -> bool:
        """Пула для случайного выбора ещё не хватает?"""
        return sum(1 for row in rows if self._good_enough(row)) < MIN_CHOICES

    @staticmethod
    def _merge(rows: list, more: list) -> list:
        """Добавляет работы, которых в списке ещё нет (сверяем по адресу)."""
        known = {PixivArtClient._url(row) for row in rows}
        known.discard("")
        return rows + [row for row in more
                       if PixivArtClient._url(row) not in known]

    def fetch(self, anime: dict, excluded=(), *,
              also=(), skip_links=()) -> tuple[bytes, str, str]:
        with self._lock:
            self._ensure_api()
            blocked = {str(url).split("?")[0] for url in excluded}
            # Страницы работ из прошлых паков («не повторять сами вопросы»).
            skip = {str(link).casefold() for link in skip_links}

            # Названия тайтлов, по которым идёт этот поиск: их метки на
            # работе — норма, чужие — повод её выбросить (_foreign_title).
            own = set()
            for card in (anime,) + tuple(also):
                own |= card_titles(card)

            def keep(row) -> bool:
                url = self._url(row)
                return (bool(url) and url.split("?")[0] not in blocked
                        and (not skip or _art_link(row) not in skip)
                        and self._safe(row)
                        and not conflicting_series(self._tag_names(row), own)
                        and not self._foreign_title(row, own))

            rows, matched_cards = [], {}
            for source, word in self._titles(anime, *also):
                found = self._search_word(word, keep)
                for row in found:
                    matched_cards.setdefault(self._url(row), source)
                rows = self._merge(rows, found)
                # Любой безопасный арт ещё не означает, что тег пригоден.
                # Продолжаем варианты названия, пока хотя бы одна работа не
                # прошла строгую планку закладок и размера. Раньше одна слабая
                # работа по первому тегу обрывала поиск всех остальных имён.
                if any(self._good_enough(row) for row in found):
                    break
            rows.sort(key=lambda row: int(_value(row, "total_bookmarks", 0) or 0),
                      reverse=True)
            # Планка лайков — ЗАПРЕТ, а не предпочтение (просьба пользователя).
            # Раньше при пустом отборе брались «самые замеченные из
            # остальных», и по малоизвестному тайтлу в пак уходила работа с
            # шестью закладками при планке в пятнадцать — причём одна и та же
            # из пака в пак: когда планку не проходит никто, запасной пул
            # состоит из тех же двух-трёх работ, и случайность выбирать не из
            # чего. Лучше не дать вопроса вовсе: его место займёт другой род.
            # Запреты на солянку, трёхмерку и наброски в силе всегда (_safe).
            pool = [row for row in rows if self._good_enough(row)][:CHOICE_POOL]
            # Выбор — СЛУЧАЙНЫЙ по всему пулу, а не «самая закладочная работа»
            # (просьба пользователя: «не одну и ту же картинку»). Порядок по
            # закладкам решает только, что в пул попадёт.
            choices = [(row, self._url(row)) for row in pool]
            if not choices:
                raise PixivArtError(
                    "подходящих артов по тегу не найдено"
                    + (f" (работ {len(rows)}, но ни одной от {self.min_likes} "
                       "закладок)" if rows and self.min_likes else ""))
            # Чей тег сработал — тот тайтл и становится ответом: арт по
            # «Магической битве 2» подписан названием первого сезона, и
            # спрашивать по нему надо тоже первый сезон (просьба
            # пользователя). Читается сразу после fetch, под тем же замком.
            row, url = self.rng.choice(choices)
            self.last_card = matched_cards.get(url, anime)
            # Адрес самой работы уходит в ответ вопроса (просьба пользователя):
            # ведущему видно, откуда взят арт и чей он.
            self.last_link = _art_link(row)
            self.last_illust = row
            buf = io.BytesIO()
            try:
                ok = self.api.download(url, fname=buf,
                                       referer="https://app-api.pixiv.net/")
            except Exception:
                raise PixivArtError("картинка не скачалась") from None
            if ok is False and not buf.getvalue():
                raise PixivArtError("картинка не скачалась")
            data = buf.getvalue()
            return data, _image_extension(data), url

    def summary(self) -> str:
        """Чем кончился прогон по артам — для журнала. Пусто, если объяснять
        нечего.

        Самая частая беда узких режимов: Pixiv не отдал НИ ОДНОЙ взрослой
        работы. Артов при этом сколько угодно — просто у аккаунта скрыт показ
        R-18, и его поиск таких работ не возвращает вовсе."""
        rows = int(self.stats.get("rows", 0) or 0)
        if not rows:
            return ""
        r18 = int(self.stats.get("r18", 0) or 0)
        ai = int(self.stats.get("ai", 0) or 0)
        head = (f"Pixiv прислал {rows} работ: взрослых (R-18) среди них "
                f"{r18}, нарисованных нейросетью — {ai}.")
        if self.r18_mode == "only" and not r18:
            return (head + " Ни одной взрослой работы не пришло вовсе — почти "
                    "наверняка в настройках самого аккаунта Pixiv выключен "
                    "показ R-18 (Настройки → Просмотр). Включите его либо "
                    "поставьте R-18 в «Разрешать».")
        if self.ai_mode == "only" and not ai:
            return (head + " Работ нейросети не пришло вовсе: у этих тайтлов "
                    "нет артов с меткой «AI生成». Поставьте ИИ-арты в "
                    "«Разрешать».")
        return head
