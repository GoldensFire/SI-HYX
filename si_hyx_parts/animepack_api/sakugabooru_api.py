# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SakugaApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


# Тип тега на Sakugabooru: 3 — «copyright», то есть название тайтла. Остальные
# (художник, персонаж, техника анимации) нам не годятся.
TAG_COPYRIGHT = 3
# Отрывки — это mp4/webm; png и gif на сайте это генга и раскадровки, вопросом
# им не быть (у нас для картинок есть свои роды вопросов).
CLIP_EXTENSIONS = ("mp4", "webm")
# Ролик тяжелее этого не берём: в пак он всё равно перекодируется, но качать
# сотню мегабайт ради шести секунд незачем.
MAX_CLIP_BYTES = 60 * 1024 * 1024
_SLUG = _api.re.compile(r"[^a-z0-9]+")
# Хвосты, которые Sakugabooru дописывает к названию СЕРИИ. Тег-«копирайт»,
# начинающийся с нужного названия, засчитывается только с таким хвостом.
#
# Без этого списка одно короткое английское название утаскивало вопрос в чужой
# тайтл: у «Rainbow: Nisha Rokubou no Shichinin» на Shikimori english — просто
# «Rainbow», точного тега `rainbow` на сайте нет, и самым населённым тегом с
# тем же началом оказывался `rainbow_sentai_robin` — сериал 1966 года, к
# вопросу отношения не имеющий. В ответ шёл один тайтл, а в кадре был другой.
TAG_TAIL_WORDS = {
    "series", "franchise", "anime", "tv", "movie", "movies", "film", "films",
    "ova", "ona", "special", "specials", "season", "seasons", "part",
    "the", "animation", "final", "ii", "iii", "iv", "v",
}


def slug(text) -> str:
    """«Sousou no Frieren» → «sousou_no_frieren» — как теги на Sakugabooru."""
    return _SLUG.sub("_", str(text or "").casefold()).strip("_")


class SakugaApi:
    """Sakugabooru — вырезки самой анимации: отрывок без звука и титров.

    Вопрос получается ровно про рисовку и движение: ни названия в кадре, ни
    голосов, ни музыки. Ключа и регистрации нет.

    Тайтл ищется тегом-«копирайтом»: имя тега складывается из ромадзи и
    английского названия карточки Shikimori, а сверяется по списку тегов сайта
    — тег `sousou_no_frieren` существует, а `frieren` пустой.
    """

    TAG_LIMIT = 10
    POST_LIMIT = 100

    def __init__(self, session: _api.Optional[_api.requests.Session] = None, *,
                 safe_only: bool = True, rng=None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(1.5)
        self.safe_only = bool(safe_only)
        self.rng = rng or _api.random.Random()
        self._tags: dict[int, str] = {}
        self._posts: dict[str, list[dict]] = {}
        self._lock = _api.threading.Lock()

    def _get(self, path: str, params: dict) -> list:
        self.limiter.acquire()
        try:
            resp = self.session.get(f"{_api.SAKUGA_BASE}/{path}",
                                    params=params, timeout=(10, 45))
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _api._friendly(e, "Sakugabooru") from e
        return data if isinstance(data, list) else []

    # ── тег тайтла ────────────────────────────────────────────────────────
    def tag_for(self, card: dict) -> str:
        """Тег тайтла на Sakugabooru («» — тайтла там нет).

        Точное совпадение имени тега побеждает; иначе берём самый населённый
        тег-«копирайт», начинающийся с того же имени, — так «Attack on Titan»
        находит `shingeki_no_kyojin_series` только если точного нет."""
        try:
            mal = int(card.get("malId") or 0)
        except (TypeError, ValueError):
            mal = 0
        with self._lock:
            known = self._tags.get(mal) if mal else None
        if known is not None:
            return known
        found = ""
        try:
            year = int((card.get("airedOn") or {}).get("year") or 0)
        except (AttributeError, TypeError, ValueError):
            year = 0
        seen: set[str] = set()
        for name in (card.get("name"), card.get("english")):
            want = slug(name)
            if not want or want in seen:
                continue
            seen.add(want)
            rows = self._get("tag.json", {"name": want, "limit": self.TAG_LIMIT,
                                          "order": "count"})
            found = self._pick_tag(rows, want, year)
            if found:
                break
        if mal:
            with self._lock:
                self._tags[mal] = found
        return found

    @staticmethod
    def _same_series(name: str, want: str, year: int = 0) -> bool:
        """`shingeki_no_kyojin_series` — тот же тайтл, `rainbow_sentai_robin`
        при запросе `rainbow` — уже другой.

        Тег длиннее запроса засчитывается, только когда ВЕСЬ его хвост состоит
        из служебных слов («series», «tv», «movie», номер сезона). Четыре цифры
        считаются годом/версией и должны совпасть с годом карточки. Любое новое
        значащее слово в хвосте означает другое произведение."""
        normalized = slug(name)
        want = slug(want)
        if not normalized.startswith(want):
            return False
        tail = normalized[len(want):].strip("_")
        if not tail:
            return True
        words = [word for word in tail.split("_") if word]
        for word in words:
            if word in TAG_TAIL_WORDS:
                continue
            if not word.isdigit():
                return False
            # Небольшое число — номер сезона/части. Четыре цифры у booru
            # обычно обозначают год или версию произведения: Yamato 2199 —
            # ремейк, а не 2199-й сезон. Такой хвост подходит только карточке
            # с тем же годом (`uchuu_senkan_yamato_(1974)`).
            if len(word) >= 4 and int(word) != int(year or 0):
                return False
        return True

    @classmethod
    def _pick_tag(cls, rows: list, want: str, year: int = 0) -> str:
        best, best_count = "", 0
        year_best, year_count = "", 0
        normalized_want = slug(want)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if int(row.get("type") or 0) != TAG_COPYRIGHT:
                continue
            name = str(row.get("name") or "")
            count = int(row.get("count") or 0)
            if not count:
                continue
            normalized = slug(name)
            if normalized == normalized_want:
                return name
            if not cls._same_series(name, want, year):
                continue
            if count > best_count:
                best, best_count = name, count
            tail = normalized[len(normalized_want):].strip("_")
            if (year and str(year) in tail.split("_")
                    and count > year_count):
                year_best, year_count = name, count
        # Явная версия нужного года точнее общего тега серии и номера сезона,
        # даже если у них больше постов.
        return year_best or best

    # ── отрывки ───────────────────────────────────────────────────────────
    def clips(self, tag: str) -> list[dict]:
        """Отрывки тайтла: [{"id", "url", "ext", "size", "source"}]."""
        key = str(tag or "")
        if not key:
            return []
        with self._lock:
            known = self._posts.get(key)
        if known is not None:
            return list(known)
        query = f"{key} animated"
        if self.safe_only:
            query += " rating:s"
        rows = self._get("post.json", {"tags": query, "limit": self.POST_LIMIT})
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ext = str(row.get("file_ext") or "").lower()
            url = str(row.get("file_url") or "")
            try:
                size = int(row.get("file_size") or 0)
            except (TypeError, ValueError):
                size = 0
            if ext not in CLIP_EXTENSIONS or not url:
                continue
            if size > MAX_CLIP_BYTES:
                continue
            # Теги поста: по ним видно genga и все тайтлы, к которым
            # вырезку отнесли (цена и ответ — см. sakuga_generation).
            tags = str(row.get("tags") or "").split()
            out.append({"id": str(row.get("id") or ""), "url": url, "ext": ext,
                        "size": size, "source": str(row.get("source") or ""),
                        "tags": tags})
        with self._lock:
            self._posts[key] = list(out)
        return out

    def absent(self, card: dict) -> bool:
        """После clip(): у тайтла на сайте нет ни тега, ни одной вырезки
        (а не просто все его вырезки уже заняты этим паком)."""
        tag = self.tag_for(card)
        return not tag or not self.clips(tag)

    @classmethod
    def card_tagged(cls, card: dict, tags) -> bool:
        """Ромадзи или английское название карточки — один из тегов вырезки."""
        try:
            year = int((card.get("airedOn") or {}).get("year") or 0)
        except (AttributeError, TypeError, ValueError):
            year = 0
        for name in (card.get("name"), card.get("english")):
            want = slug(name)
            if want and any(cls._same_series(tag, want, year) for tag in tags if tag):
                return True
        return False

    def clip(self, card: dict, excluded=()) -> dict:
        """Случайный отрывок тайтла ({} — подходящего нет)."""
        tag = self.tag_for(card)
        if not tag:
            return {}
        blocked = {str(u).split("?")[0] for u in excluded}
        free = [row for row in self.clips(tag)
                if row["url"].split("?")[0] not in blocked]
        if not free:
            return {}
        return self.rng.choice(free)

def post_link(post_id) -> str:
    """Страница вырезки на Sakugabooru («» — id неизвестен).

    Уходит последней строкой ответа: по ней видно, из какой сцены отрывок и
    кто её анимировал, а адрес самого файла не говорит ничего (просьба
    пользователя)."""
    key = str(post_id or "").strip()
    return f"{_api.SAKUGA_BASE}/post/show/{key}" if key else ""


SakugaApi.__module__ = _api.__name__
post_link.__module__ = _api.__name__
_api.SakugaApi = SakugaApi
_api.sakuga_post_link = post_link
