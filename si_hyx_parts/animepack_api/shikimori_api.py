# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


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
    # У дат берётся не только год: по точной дате показа серии вопрос по сюжету
    # находит, какой части франшизы она своя (см. plot_air_date). Ни номер
    # сезона из инфобокса, ни названия частей этого не дают — «Алисизация» и её
    # «Война в Подмирье» у вики один сезон, а у Shikimori три разных тайтла.
    ANIME_FIELDS = """
        id malId url name russian english japanese synonyms licenseNameRu
        franchise score kind episodes
        studios { id name }
        related { relationKind anime { id kind } }
        genres { id name russian kind }
        poster { originalUrl mainUrl }
        screenshots { originalUrl x332Url }
        airedOn { year month day }
        releasedOn { year month day }
        status
        statusesStats { status count }
    """
    ANIMES_QUERY = ("query($ids: String!, $limit: Int!) {\n"
                    "  animes(ids: $ids, limit: $limit) {" + ANIME_FIELDS + "}\n}")

    # Части франшизы — по ним считается узнаваемость всей серии (у «Доктор
    # Стоун: Научное будущее. Часть 3» своих зрителей мало, но тайтл знают по
    # оригинальному «Доктору Стоуну»). Берём не одну самую популярную часть, а
    # первые FRANCHISE_PARTS: по ним видно и сколько у сериала заметных сезонов,
    # и когда вышло последнее продолжение (см. shikimori_api.franchise_parts_index).
    # Запросы склеиваются алиасами. Одна выборка с нынешними полями стоит
    # Shikimori 14 единиц сложности, а предел документа — 190: 13 выборок
    # дают 182, тогда как прежние 18 (252) сервер уже отклоняет целиком.
    FRANCHISE_BATCH = 13
    FRANCHISE_PARTS = 12
    # kind нужен отбору первого сезона: самой ранней частью франшизы сплошь и
    # рядом оказывается ПРОМО-РОЛИК («Подземелье вкусностей PV»), и ответом
    # вопроса он стать не должен (просьба пользователя).
    FRANCHISE_FIELDS = ("id malId russian kind score airedOn { year } "
                        "releasedOn { year } status "
                        "statusesStats { status count }")
    # Квадратные скобки — часть настоящих ключей Shikimori (например
    # ``[oshi_no_ko]``), а не оформление. Удалив их, получаем другую,
    # несуществующую франшизу. Остальные символы отсекаем: ключ встраивается
    # в строковый аргумент GraphQL.
    _RE_FRANCHISE = _api.re.compile(r"[^a-z0-9_\-\[\]]")

    # Shikimori держит ДВА предела разом: 5 запросов в секунду и 90 в минуту.
    # Раньше стояла только секундная пауза (2 запроса/с), а это ровно 120 в
    # минуту — то есть 429 приходил гарантированно, стоило генерации пойти
    # дольше минуты. Дальше каждый отказ стоил ещё и четырёх ретраев с
    # нарастающей паузой (~20 с на запрос), из-за чего вопросы-персонажи (у
    # каждого свой запрос про избранное и про другие тайтлы) занимали десятки
    # минут. Берём 80/мин — с запасом на редиректы .one → .io, каждый из
    # которых для сервера тоже запрос.
    PER_MINUTE = 80

    from si_hyx_parts.animepack_api.shikimori_api___init import __init__, client, base_url

    # На сколько секунд притормозить ВСЕ потоки, когда сервер всё-таки сказал
    # 429. Своих ретраев у адаптера сессии четыре, и без общей паузы соседние
    # потоки продолжают долбить сервер ровно в том же темпе.
    RETRY_PENALTY = 20.0

    from si_hyx_parts.animepack_api.shikimori_api__get import (
        _get,
        user_id,
        user_anime_ids,
        animes_by_ids,
    )
    from si_hyx_parts.animepack_api.shikimori_api_description import anime_description

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
        id malId url name russian english japanese synonyms licenseNameRu
        kind airedOn { year }
        releasedOn { year }
        status
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

    from si_hyx_parts.animepack_api.shikimori_api_search_characters_by_name import (
        search_characters_by_name,
        search_animes_by_name,
        search_mangas_by_name,
    )

    # ── Манга, манхва, манхуа и ранобэ ───────────────────────────────────
    # У типа Manga в GraphQL Shikimori те же поля, что у Anime, кроме
    # screenshots (кадров у книги нет — вопросом служит портрет персонажа либо
    # обложка). Поэтому и запросы те же, только с другим корнем.
    # related нужен, чтобы понять, есть ли у книги АНИМЕ-ЭКРАНИЗАЦИЯ: такую
    # мангу узнают по её аниме, у неё своя доля в паке и своя цена (см.
    # manga_adaptation.py). Поле лёгкое — одни идентификаторы.
    MANGA_FIELDS = """
        id malId url name russian english japanese synonyms licenseNameRu
        franchise score kind
        related { relationKind anime { id kind } }
        genres { id name russian kind }
        poster { originalUrl mainUrl }
        airedOn { year }
        releasedOn { year }
        status
        statusesStats { status count }
    """
    MANGAS_QUERY = ("query($ids: String!, $limit: Int!) {\n"
                    "  mangas(ids: $ids, limit: $limit) {" + MANGA_FIELDS + "}\n}")

    from si_hyx_parts.animepack_api.shikimori_api_mangas_by_ids import (
        mangas_by_ids,
        random_mangas,
        character_titles,
    )

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

    from si_hyx_parts.animepack_api.shikimori_api_characters_by_anime_ids import (
        characters_by_anime_ids,
    )

    # Случайные тайтлы прямо из каталога Shikimori (альтернатива базе AMQ).
    # Фильтры уходят на сервер, поэтому мусора приезжает куда меньше, чем при
    # переборе 16-мегабайтного мастер-листа AMQ.
    RANDOM_LIMIT = 50

    def random_animes(self, page: int = 1, *, limit: int = RANDOM_LIMIT,
                      season: str = "", kinds: _api.Iterable[str] = (),
                      score: int = 0, genres: _api.Iterable[int] = (),
                      genres_exclude: _api.Iterable[int] = (),
                      studios: _api.Iterable[int] = (),
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
        studio_ids = []
        for studio in studios:
            try:
                ident = int(studio)
            except (TypeError, ValueError):
                continue
            if ident:
                studio_ids.append(str(ident))
        if studio_ids:
            args.append(f'studio: "{",".join(studio_ids)}"')
        query = ("query {\n  animes(" + ", ".join(args) + ") {"
                 + self.ANIME_FIELDS + "}\n}")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {})
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    _RE_ARG = _api.re.compile(r'[^0-9a-zA-Z_,\-]')

    from si_hyx_parts.animepack_api.shikimori_api_franchise_parts import franchise_parts

    # ── «В избранном» у персонажа И у тайтла ─────────────────────────────
    # В API этого числа нет вовсе — ни у персонажа, ни у аниме, ни у манги
    # (проверено интроспекцией GraphQL и по списку эндпоинтов /api/doc):
    # GraphQL-типы Anime/Manga/Character полей про избранное не имеют, REST
    # отдаёт только `favoured` — булев флаг «добавил ли ТЕКУЩИЙ пользователь»,
    # а /api/favorites умеет лишь добавить и убрать свою запись. Сортировки по
    # избранному тоже нет (order принимает ranked/popularity/ranked_shiki и
    # прочее, но не favorites). Само число висит на СТРАНИЦЕ блоком b-favoured,
    # оттуда и берём — по запросу на тайтл, поэтому спрашиваем его только у тех
    # кандидатов, что дошли до загрузки медиа.
    _RE_FAVOURED = _api.re.compile(
        r'b-favoured.{0,800}?<div class="count">\s*(\d+)\s*</div>', _api.re.S)
    # Адрес страницы тайтла: ВСЕГДА с приставкой «z» перед id Shikimori.
    # Голый номер отвечает 404 у доброй половины тайтлов («Гинтама», «Детектив
    # Конан», «Стальной алхимик: Братство»), а «z» работает у всех — проверено.
    _TITLE_PATHS = {"anime": "animes", "manga": "mangas"}
    _TITLE_BODY = {"anime": "p-animes-show", "manga": "p-mangas-show"}

    from si_hyx_parts.animepack_api.shikimori_api_character_favorites import (
        character_favorites,
        title_favorites,
        genres,
    )

ShikimoriApi.__module__ = _api.__name__
_api.ShikimoriApi = ShikimoriApi
