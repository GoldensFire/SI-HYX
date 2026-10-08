# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api
from si_hyx_parts.animepack_api.shikimori_catalog import (
    POPULATION_FIELDS,
    catalog_args,
    page_batch_size,
)
import re
import time
import animepack_api as api


# Адреса Shikimori (домен кочует между .one и .io) — у них свои ретраи сессии.
SHIKIMORI_PREFIX = "https://shikimori."


def _mount_shikimori_retry(session) -> None:
    """Повторами владеет только клиент: один запрос — одна попытка транспорта."""
    if not isinstance(session, _api.requests.Session):
        return      # подменённая в тестах сессия
    retry = _api.Retry(total=0, connect=0, read=0, status=0)
    session.mount(SHIKIMORI_PREFIX,
                  _api.HTTPAdapter(max_retries=retry, pool_maxsize=16))


def _title_url(self, tid: int, path: str, page_url: str) -> str:
    """Каноническая страница тайтла.

    Shikimori больше не принимает универсальную приставку ``z``:
    например, «Форма голоса» живёт по ``/animes/y28851-...``, а ``z28851``
    отвечает 404. Свежая GraphQL-карточка уже несёт ``url``;
    для старого кэша один раз спрашиваем REST-карточку.
    """
    url = str(page_url or "").strip()
    if not url:
        try:
            resp = self._get(f"{self.base_url}/api/{path}/{tid}",
                             headers={"Accept": "application/json"},
                             timeout=(10, 30))
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            data = resp.json()
            url = str((data or {}).get("url") or "")
        except Exception:  # noqa: BLE001 — старый/подменённый клиент
            # У старых клиентов нет REST-ответа с ``url``. Прежний
            # маршрут остаётся запасным: он всё ещё годится части
            # тайтлов, а свежие карточки всегда приносят канонический.
            return f"{self.base_url}/{path}/z{tid}"
    if url.startswith("/"):
        url = self.base_url.rstrip("/") + url
    return url.replace("shikimori.one", "shikimori.io")


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
    FRANCHISE_PARTS = 50  # максимум страницы; сложность не зависит от limit
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

    def __init__(self, session: _api.Optional[_api.requests.Session] = None,
                 client: _api.Optional[_api.Any] = None):
        self.session = session or _api.make_session()
        _mount_shikimori_retry(self.session)
        self.limiter = _api.RateLimiter(2, per_minute=self.PER_MINUTE)
        self._client = client

    # ── клиент shikimori_api (ленивый импорт) ──────────────────────────────
    @property
    def client(self):
        if self._client is None:
            from shikimori_api import ShikimoriApiClient
            # Клиент учитывает и обрывы, и 429/5xx; адаптер их не дублирует.
            self._client = ShikimoriApiClient(user_agent=_api.USER_AGENT,
                                              max_retries=1,
                                              session=self.session)
        return self._client

    @property
    def base_url(self) -> str:
        try:
            return self.client.base_url
        except Exception:  # pragma: no cover
            return "https://shikimori.io"

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
        except _api.requests.exceptions.RetryError:
            self.limiter.penalize(self.RETRY_PENALTY)
            raise
        if resp.status_code == 429:
            self.limiter.penalize(self.RETRY_PENALTY)
        return resp

    def user_id(self, nickname: str) -> _api.Optional[int]:
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
            raise _api._friendly(e, "Shikimori") from e
        uid = (data or {}).get("id") if isinstance(data, dict) else None
        return int(uid) if uid else None

    def user_anime_ids(self, nickname: str, statuses: _api.Iterable[str],
                       progress_cb: _api.Optional[_api.Callable[[str], None]] = None,
                       should_stop: _api.Optional[_api.Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        wanted = {s for s in statuses if s in _api.LIST_STATUSES}
        if not wanted:
            return []
        manga = str(target or "anime") == "manga"
        target_type = "Manga" if manga else "Anime"
        what = "манги" if manga else "аниме"
        uid = self.user_id(nickname)
        if not uid:
            raise _api.AnimePackApiError(
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
                raise _api._friendly(e, "Shikimori") from e
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
                if _api._SHIKI_STATUS.get(row.get("status")) in wanted:
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

    def animes_by_ids(self, ids: _api.Iterable[int]) -> list[dict]:
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
            raise _api._friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    def anime_description(self, shikimori_id: int) -> str:
        query = ("query($ids: String!) { "
                 "animes(ids: $ids, limit: 1) { id description } }")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {"ids": str(int(shikimori_id))})
        except Exception as exc:
            raise _api._friendly(exc, "Shikimori") from exc
        rows = (data or {}).get("animes") if isinstance(data, dict) else []
        for row in rows or []:
            if isinstance(row, dict) and str(row.get("id")) == str(shikimori_id):
                return str(row.get("description") or "")
        return ""

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
            raise _api._friendly(e, "Shikimori") from e
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
            raise _api._friendly(e, "Shikimori") from e
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
            raise _api._friendly(e, "Shikimori") from e
        mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
        return [m for m in (mangas or []) if isinstance(m, dict)]

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

    def mangas_by_ids(self, ids: _api.Iterable[int]) -> list[dict]:
        """Карточки манги/ранобэ пачкой (≤50 за раз) — как animes_by_ids."""
        ids = [str(int(i)) for i in ids]
        if not ids:
            return []
        self.limiter.acquire()
        try:
            data = self.client._graphql(self.MANGAS_QUERY,
                                        {"ids": ",".join(ids), "limit": len(ids)})
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e
        mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
        return [m for m in (mangas or []) if isinstance(m, dict)]

    def random_mangas(self, page: int = 1, *, limit: int = 50,
                      season: str = "", kinds: _api.Iterable[str] = (),
                      score: int = 0, genres: _api.Iterable[int] = (),
                      genres_exclude: _api.Iterable[int] = (),
                      order: str = "random") -> list[dict]:
        """Страница случайных карточек манги (order: random) с фильтрами.

        Про order — см. random_animes: обход каталога целиком идёт с `order: id`,
        случайная выборка — с `random`."""
        from .shikimori_catalog import catalog_args
        args = catalog_args(self._RE_ARG, page, limit=limit, season=season,
                            kinds=kinds, score=score, genres=genres,
                            genres_exclude=genres_exclude, order=order)
        query = ("query {\n  mangas(" + args + ") {"
                 + self.MANGA_FIELDS + "}\n}")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {})
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e
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
            raise _api._friendly(e, "Shikimori") from e
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

    def characters_by_anime_ids(self, ids: _api.Iterable[int],
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
            raise _api._friendly(e, "Shikimori") from e
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

    # Полные карточки: 2×67 / 4×47; census: 15×12 <=190 единиц сложности.
    CATALOG_ANIME_PAGES = 2
    CATALOG_MANGA_PAGES = 4
    CATALOG_POPULATION_PAGES = 15

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
        from .shikimori_catalog import catalog_args
        args = catalog_args(self._RE_ARG, page, limit=limit, season=season,
                            kinds=kinds, score=score, genres=genres,
                            genres_exclude=genres_exclude, studios=studios, order=order)
        query = ("query {\n  animes(" + args + ") {"
                 + self.ANIME_FIELDS + "}\n}")
        self.limiter.acquire()
        try:
            data = self.client._graphql(query, {})
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e
        animes = (data or {}).get("animes") if isinstance(data, dict) else None
        return [a for a in (animes or []) if isinstance(a, dict)]

    _RE_ARG = _api.re.compile(r'[^0-9a-zA-Z_,\-]')

    def franchise_parts(self, keys: _api.Iterable[str]) -> dict:
        """{ключ франшизы: [карточки её частей по убыванию популярности]}.

        Нужно, чтобы сиквел считался таким же узнаваемым, как оригинал (у
        «Доктор Стоун: Научное будущее. Часть 3» своих зрителей мало, но
        спрашивают-то по сути «Доктора Стоуна»), а заодно чтобы сериал с
        несколькими живыми сезонами получал надбавку, а старый тайтл со свежим
        продолжением — послабление по году (shikimori_api.franchise_parts_index).
        Запрос один на FRANCHISE_BATCH франшиз (алиасы в одном GraphQL-документе).
        """
        clean, seen, aliases = [], set(), {}
        for key in keys:
            original = str(key or "").strip()
            normalized = self._RE_FRANCHISE.sub("", original.lower())
            if not normalized:
                continue
            aliases.setdefault(normalized, []).append(original)
            if normalized not in seen:
                seen.add(normalized)
                clean.append(normalized)
        out: dict = {}
        self._franchise_errors = {}
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
            except Exception as exc:  # генерация сохранит остальные ответы
                # Сорвавшуюся пачку НЕ отмечаем как «частей нет»: иначе разовый
                # обрыв сети навсегда осел бы в кэше нулевой узнаваемостью.
                for key in batch:
                    for original in aliases.get(key, (key,)):
                        self._franchise_errors[original] = str(exc)
                continue
            for n, key in enumerate(batch):
                found = (data or {}).get(f"f{n}") if isinstance(data, dict) else None
                if not isinstance(found, list) or any(not isinstance(row, dict) for row in found):
                    for original in aliases.get(key, (key,)):
                        self._franchise_errors[original] = "Нет корректного ответа по франшизе"
                    continue
                # Пустой список тоже ответ («у этой франшизы частей нет») —
                # ключ есть, значит спрашивать её снова незачем.
                rows = [r for r in (found or []) if isinstance(r, dict)]
                # В карточках Shikimori встречаются ключи с квадратными скобками
                # (например ``[oshi_no_ko]``). В GraphQL их надо убрать, но кэш
                # обязан сохранить исходный ключ: именно его потом ищет карточка.
                for original in aliases.get(key, (key,)):
                    out[original] = list(rows)
        return out

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

    def title_favorites(self, shiki_id, target="anime", page_url="") -> int:
        """Compatible numeric result: unknown measurements remain -1."""
        return int(self.title_favorites_result(shiki_id, target, page_url).get("value", -1))

    def genres(self) -> list[dict]:
        """Полный современный список жанров/тем (id/name/russian/kind)."""
        try:
            return self.client.genres("anime")
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e

    def catalog_pages(self, page=1, *, manga=False, population=False, pages=None,
                      order="id", **filters):
        """Return consecutive pages in one HTTP request, preserving page boundaries.

    Verified 2026-10-01: complete anime/manga pages cost 67/47 each; the
    population-only selection costs 12. The server allows complexity <=190.
    A lower server budget is remembered for this client after a rejection.
    """
        if population and not manga:
            raise ValueError("population census requires manga")
        page = max(1, int(page))
        root = "mangas" if manga else "animes"
        fields = (POPULATION_FIELDS if population else
                  self.MANGA_FIELDS if manga else self.ANIME_FIELDS)
        maximum = page_batch_size(self, manga, population)
        sizes = getattr(self, "_catalog_page_sizes", None)
        if sizes is None:
            sizes = self._catalog_page_sizes = {}
        key = (manga, population)
        count = max(1, min(int(pages or maximum), maximum, sizes.get(key, maximum)))
        # Iterable filters must be reusable for every alias and any budget retry.
        filters = dict(filters)
        for name in ("kinds", "genres", "genres_exclude", "studios"):
            if name in filters:
                filters[name] = tuple(filters[name])
        while True:
            selections = []
            for offset in range(count):
                args = catalog_args(self._RE_ARG, page + offset,
                                    order=order, **filters)
                selections.append(f"p{offset}: {root}({args}) {{ {fields} }}")
            self.limiter.acquire()
            try:
                data = self.client._graphql("query {\n" + "\n".join(selections) + "\n}", {})
            except Exception as exc:
                message = str(exc).lower()
                if count > 1 and "complexity" in message and "exceeds" in message:
                    count -= 1
                    sizes[key] = count
                    continue
                raise _api._friendly(exc, "Shikimori") from exc
            result = []
            for offset in range(count):
                rows = data.get(f"p{offset}") if isinstance(data, dict) else None
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise _api.AnimePackApiError("Shikimori: некорректная страница каталога.")
                result.append(rows)
            return result

    def title_favorites_result(self, shiki_id, target="anime", page_url=""):
        from si_hyx_parts.animepack_api.shikimori_api import _title_url
        result = {"status": "ERROR", "value": -1, "checked": time.time()}
        try:
            ident = int(shiki_id)
            if ident <= 0:
                return {**result, "reason": "Некорректный номер тайтла"}
            path = self._TITLE_PATHS.get(target, "animes")
            url = _title_url(self, ident, path, page_url)
            if not url:
                return {**result, "status": "NOT_FOUND", "http": 404}
            response = self._get(url, headers={"Accept": "text/html"}, timeout=(10, 30))
            result["http"] = response.status_code
            if response.status_code == 404:
                return {**result, "status": "NOT_FOUND", "reason": "Страница не найдена"}
            if response.status_code == 403:
                age = "Доступ ограничен 18+" in response.text
                return {**result, "status": "AGE_RESTRICTED" if age else "ACCESS_DENIED",
                        "reason": "Требуется вход с подтверждённым возрастом" if age else "Доступ запрещён"}
            if response.status_code == 429:
                return {**result, "status": "RATE_LIMITED", "reason": "Превышена квота запросов"}
            response.raise_for_status()
            html = response.text
            match = self._RE_FAVOURED.search(html)
            if match:
                return {**result, "status": "NORMAL", "value": int(match.group(1))}
            widget = re.search(r'class=["\'][^"\']*b-favoured', html)
            if not widget and self._TITLE_BODY.get(target, "") in html:
                return {**result, "status": "NORMAL", "value": 0}
            return {**result, "reason": "Страница не содержит корректного счётчика"}
        except Exception as exc:
            return {**result, "reason": str(exc)[:400]}

    def title_censorship_flags(self, ids, target="manga", stopped=None):
        stopped = stopped or (lambda: False)
        clean = sorted({int(ident) for ident in ids if int(ident) > 0})
        root = "mangas" if target == "manga" else "animes"
        flags, offset, aliases = {}, 0, 16
        while offset < len(clean) and not stopped():
            batch = clean[offset:offset + aliases * 50]
            groups = [batch[i:i + 50] for i in range(0, len(batch), 50)]
            selections = [f'p{i}: {root}(ids: "{",".join(map(str, group))}", limit: 50) '
                          '{ id isCensored }' for i, group in enumerate(groups)]
            self.limiter.acquire()
            try:
                data = self.client._graphql("query { " + " ".join(selections) + " }", {})
            except Exception as exc:
                if aliases > 1 and "complexity" in str(exc).lower():
                    aliases //= 2
                    continue
                raise api._friendly(exc, "Shikimori") from exc
            for i, group in enumerate(groups):
                rows = data.get(f"p{i}") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise api.AnimePackApiError("Shikimori: неполный ответ признаков доступа")
                expected = set(group)
                for row in rows:
                    if not isinstance(row, dict):
                        raise api.AnimePackApiError("Shikimori: неверные признаки доступа")
                    ident, flag = int(row.get("id") or 0), row.get("isCensored")
                    if ident not in expected or not isinstance(flag, bool):
                        raise api.AnimePackApiError("Shikimori: неверные признаки доступа")
                    flags[ident] = flag
            offset += len(batch)
        return flags

ShikimoriApi.__module__ = _api.__name__
_api.ShikimoriApi = ShikimoriApi
