"""Steam Web API — метаданные Workshop-паков SIGame (app 3553500).

ТОЛЬКО метаданные (название, автор, описание, число подписок, дата публикации,
теги) через официальный Steam Web API (IPublishedFileService/QueryFiles +
ISteamUser/GetPlayerSummaries для имени автора по SteamID64). Сами depot-файлы
воркшопа НЕ скачиваются — раздача файлов там устроена иначе, чем на sibrowser
(нужен SteamCMD с анонимным логином и депо-скачиванием, а не обычный GET) —
это отдельная задача, здесь сознательно не реализована.

Требует бесплатный Steam Web API-ключ пользователя (steamcommunity.com/dev/apikey).
"""
from __future__ import annotations
import datetime
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

import requests

from . import config
from .normalize import normalize_name

SIGAME_APP_ID = 3553500

_QUERY_URL = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
_PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"

# EPublishedFileQueryType (Steam Web API) — нужные нам значения из паблик-энума.
QUERY_TYPE_SUBSCRIPTIONS = 9    # RankedByTotalUniqueSubscriptions — аналог «по скачиваниям»
QUERY_TYPE_PUBLICATION_DATE = 1  # RankedByPublicationDate — аналог «по дате публикации»


@dataclass
class WorkshopItem:
    steam_id: str
    name: str
    name_norm: str
    authors: list[str]
    description: str | None
    subscriptions: int | None
    date_published: str | None   # ISO 'YYYY-MM-DD'
    tags: list[str] = field(default_factory=list)

    def as_package(self) -> dict:
        return {
            "sibrowser_id": None,
            "source": "steam",
            "steam_id": self.steam_id,
            "name": self.name,
            "name_norm": self.name_norm,
            "authors": self.authors,
            "download_count": self.subscriptions,
            "question_count": None,
            "round_count": None,
            "length_group": config.length_group(None),
            "size_mb": None,
            "date_published": self.date_published,
            "tags": self.tags,
            "categories": [],
            "pct_text": None, "pct_photo": None, "pct_audio": None, "pct_video": None,
            "description": self.description,
        }


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def _parse_item(raw: dict) -> WorkshopItem | None:
    name = (raw.get("title") or "").strip()
    pid = raw.get("publishedfileid")
    if not name or not pid:
        return None
    ts = raw.get("time_created")
    date_pub = None
    if ts:
        try:
            date_pub = datetime.datetime.fromtimestamp(
                int(ts), tz=datetime.timezone.utc).date().isoformat()
        except (ValueError, OSError):
            date_pub = None
    tags = [t.get("tag") for t in (raw.get("tags") or []) if t.get("tag")]
    desc = (raw.get("file_description") or "").strip() or None
    return WorkshopItem(
        steam_id=str(pid),
        name=name,
        name_norm=normalize_name(name),
        authors=[],
        description=desc,
        subscriptions=raw.get("subscriptions"),
        date_published=date_pub,
        tags=tags,
    )


def query_files(
    session: requests.Session,
    api_key: str,
    page: int = 1,
    numperpage: int = 50,
    app_id: int = SIGAME_APP_ID,
    query_type: int = QUERY_TYPE_SUBSCRIPTIONS,
) -> tuple[list[dict], int]:
    """Один запрос IPublishedFileService/QueryFiles. Возвращает (сырые записи, total)."""
    params = {
        "key": api_key,
        "appid": app_id,
        "numperpage": numperpage,
        "page": page,
        "query_type": query_type,
        "return_details": True,
        "return_tags": True,
        "return_short_description": False,
    }
    resp = session.get(_QUERY_URL, params=params, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = (resp.json() or {}).get("response", {}) or {}
    return data.get("publishedfiledetails", []) or [], int(data.get("total", 0) or 0)


def resolve_creator_names(
    session: requests.Session, api_key: str, steam_ids: list[str],
) -> dict[str, str]:
    """SteamID64 → отображаемое имя (ISteamUser/GetPlayerSummaries, до 100 за запрос)."""
    result: dict[str, str] = {}
    ids = [i for i in dict.fromkeys(steam_ids) if i]
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            resp = session.get(
                _PLAYER_SUMMARIES_URL,
                params={"key": api_key, "steamids": ",".join(chunk)},
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            players = (resp.json() or {}).get("response", {}).get("players", []) or []
            for p in players:
                sid, nm = p.get("steamid"), p.get("personaname")
                if sid and nm:
                    result[sid] = nm
        except Exception:
            continue
    return result


def iter_items(
    session: requests.Session,
    api_key: str,
    skip_norms: set[str],
    app_id: int = SIGAME_APP_ID,
    query_type: int = QUERY_TYPE_SUBSCRIPTIONS,
    numperpage: int = 50,
    max_pages: int = 40,
    progress_cb: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[WorkshopItem]:
    """Идёт по страницам Steam Workshop и отдаёт новые (не в skip_norms) паки.

    Останавливается на конце каталога, max_pages или should_stop(). Дедупликация —
    по тому же normalize_name(), что и sibrowser (одно название → один пак,
    независимо от источника).
    """
    for page in range(1, max_pages + 1):
        if should_stop and should_stop():
            return
        if progress_cb:
            progress_cb(f"Steam Workshop, страница {page}…")
        try:
            raw_items, total = query_files(
                session, api_key, page=page, numperpage=numperpage,
                app_id=app_id, query_type=query_type)
        except Exception as e:
            if progress_cb:
                progress_cb(f"Ошибка запроса Steam Web API: {e}")
            return
        if not raw_items:
            return
        creator_ids = [r.get("creator") for r in raw_items if r.get("creator")]
        names = resolve_creator_names(session, api_key, creator_ids)
        for raw in raw_items:
            if should_stop and should_stop():
                return
            item = _parse_item(raw)
            if item is None:
                continue
            creator_name = names.get(raw.get("creator"))
            if creator_name:
                item.authors = [creator_name]
            if item.name_norm in skip_norms:
                continue
            skip_norms.add(item.name_norm)
            yield item
        if page * numperpage >= total:
            return
        time.sleep(config.SCRAPE_DELAY)


def workshop_url(steam_id: str) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={steam_id}"
