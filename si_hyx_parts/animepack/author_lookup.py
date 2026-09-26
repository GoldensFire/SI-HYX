# -*- coding: utf-8 -*-
"""Авторы выбранных произведений через роли Shikimori GraphQL."""
from __future__ import annotations


_QUERY = """query($ids: String!, $limit: Int!) {
  TARGET(ids: $ids, limit: $limit) {
    id personRoles { rolesRu rolesEn person { name russian } }
  }
}"""


def _author(row: dict) -> str:
    found: dict[int, list[str]] = {}
    for role in row.get("personRoles") or []:
        labels = {str(label).strip().casefold() for label in
                  ((role or {}).get("rolesRu") or [])
                  + ((role or {}).get("rolesEn") or [])}
        if labels & {"автор оригинала", "original creator", "автор"}:
            priority = 0
        elif labels & {"сюжет и иллюстрации", "story & art", "сюжет", "story"}:
            priority = 1
        elif labels & {"компоновка серий", "series composition",
                        "сценарий", "script"}:
            priority = 2
        else:
            continue
        person = (role or {}).get("person") or {}
        name = str(person.get("russian") or person.get("name") or "").strip()
        if name and name not in found.setdefault(priority, []):
            found[priority].append(name)
    return ", ".join(found[min(found)][:2]) if found else ""


def enrich_authors(shikimori, songs: list, log) -> None:
    """Добавляет автора готовым вопросам; ошибка справочника не ломает пак."""
    if not hasattr(shikimori, "client") or not hasattr(shikimori, "limiter"):
        return
    by_type = {"animes": {}, "mangas": {}}
    for cand in songs:
        # У КНИГИ автор нужен всегда, даже когда реплика ведущего и без него не
        # пуста (в ней стоит «аниме-адаптация есть»): у книжного вопроса автор
        # и рейтинг Shikimori говорят игрокам ровно столько же, сколько у
        # остальных вопросов (просьба пользователя).
        ident = str(cand.anime.get("id") or "").strip()
        if not ident.isdigit():
            continue
        if cand.is_manga:
            by_type["mangas"].setdefault(ident, []).append(cand)
            continue
        if cand.artist or cand.users or cand.plot_episode:
            continue
        by_type["animes"].setdefault(ident, []).append(cand)
    for target, entries in by_type.items():
        ids = list(entries)
        for start in range(0, len(ids), 15):
            chunk = ids[start:start + 15]
            try:
                shikimori.limiter.acquire()
                data = shikimori.client._graphql(
                    _QUERY.replace("TARGET", target),
                    {"ids": ",".join(chunk), "limit": len(chunk)})
            except Exception as exc:
                log(f"Shikimori: не удалось получить авторов: {exc}")
                continue
            if not isinstance(data, dict):
                continue
            for row in (data or {}).get(target) or []:
                name = _author(row or {})
                if name:
                    for cand in entries.get(str(row.get("id")), []):
                        cand.author_name = name
