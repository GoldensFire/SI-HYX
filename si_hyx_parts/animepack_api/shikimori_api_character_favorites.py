# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: character_favorites. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


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

def title_favorites(self, shiki_id, target: str = "anime",
                    page_url: str = "") -> int:
    """Сколько человек добавили ТАЙТЛ в избранное (−1 — не узнали).

        Число берётся со страницы Shikimori, а не из API: в API его нет вовсе
        (см. комментарий у _RE_FAVOURED). Это ровно та мера, которую просил
        пользователь — русскоязычная аудитория Shikimori, а не чужая.

        shiki_id — номер Shikimori (поле `id` карточки), НЕ malId: страницы
        открываются по нему. Ноль и «не узнали» различаются так же, как у
        персонажей: у безвестного тайтла блока с числом на странице нет."""
    try:
        tid = int(shiki_id)
    except (TypeError, ValueError):
        return -1
    if tid <= 0:
        return -1
    path = self._TITLE_PATHS.get(str(target), "animes")
    url = _title_url(self, tid, path, page_url)
    if not url:
        return -1
    try:
        resp = self._get(url,
                         headers={"Accept": "text/html"},
                         timeout=(10, 30))
        if resp.status_code == 404:
            return -1
        resp.raise_for_status()
        html = resp.text
    except Exception:  # noqa: BLE001 — доп. мера узнаваемости, не критична
        return -1
    m = self._RE_FAVOURED.search(html)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return -1
    # Страница пришла, а блока нет — значит в избранном тайтл ни у кого.
    # Посторонний ответ (заглушка Cloudflare, редирект) отличаем по классу
    # тела страницы тайтла.
    return 0 if self._TITLE_BODY.get(str(target), "") in html else -1


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

def genres(self) -> list[dict]:
    """Полный современный список жанров/тем (id/name/russian/kind)."""
    try:
        return self.client.genres("anime")
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
