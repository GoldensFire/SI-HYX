# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Медиа в пакете: имена записей, ссылки и неиспользуемые файлы. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить неиспользуемые файлы»
# ─────────────────────────────────────────────────────────────────────────────
def entry_basename(name: str) -> str:
    """Человеческое имя файла из имени записи архива: без папок и без
    percent-кодирования («Images/%D0%BA.jpg» → «к.jpg»)."""
    return _api.unquote(str(name or "").replace("\\", "/")).rsplit("/", 1)[-1]

entry_basename.__module__ = _api.__name__
_api.entry_basename = entry_basename


def referenced_names(root: _api.ET.Element) -> set:
    """Имена файлов, на которые в content.xml есть хоть какая-то ссылка.

    Смотрим и текст элементов, и ВСЕ значения атрибутов, а не только <item> и
    <atom>: логотип пака лежит атрибутом <package logo>, и удалить его из-за
    того, что вопросы на него не ссылаются, было бы порчей пака. Ошибаться тут
    можно только в одну сторону — лишний «занятый» файл просто останется лежать,
    а лишнее удаление это дырка в паке.

    Ключи — casefold: в архиве имя записано как записал автор, а в ссылке — как
    ему было удобно, и регистр у них расходится сплошь и рядом."""
    out: set = set()
    for el in root.iter():
        raw_values = [el.text or ""]
        raw_values += [str(v) for v in (el.attrib or {}).values()]
        for raw in raw_values:
            text = str(raw).strip().lstrip("@")
            if not text or len(text) > 400:
                continue
            name = _api.entry_basename(text)
            if name:
                out.add(name.casefold())
    return out

referenced_names.__module__ = _api.__name__
_api.referenced_names = referenced_names


def is_media_entry(name: str) -> bool:
    """Медиа ли это (по расширению). Служебные части пака — content.xml,
    Texts/authors.xml, [Content_Types].xml — сюда не попадают никогда."""
    return _api.os.path.splitext(_api.entry_basename(name))[1].lower() in _api.MEDIA_EXTS

is_media_entry.__module__ = _api.__name__
_api.is_media_entry = is_media_entry


def unused_entries(names, refs: set, keep=()) -> list[str]:
    """Записи архива, на которые в паке нет ни одной ссылки.

    keep — имена записей, которые трогать нельзя, чем бы дело ни кончилось
    (пережатые картинки и дорожки: их ссылки уже переписаны на новое имя, и по
    старому их никто не зовёт — а сами они в пак всё-таки идут)."""
    keep = {str(k) for k in (keep or ())}
    out: list[str] = []
    for name in names:
        if name in keep or not _api.is_media_entry(name):
            continue
        if _api.entry_basename(name).casefold() not in refs:
            out.append(name)
    return out

unused_entries.__module__ = _api.__name__
_api.unused_entries = unused_entries
