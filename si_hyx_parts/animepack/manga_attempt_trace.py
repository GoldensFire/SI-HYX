# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Одна строка журнала на каждую попытку страницы манги.

Повторяющиеся причины _log_rare замолкает после нескольких раз, и по журналу
нельзя было понять, на что ушли последние шесть минут прогона (одна манга в
хвосте). Теперь в файле видно: тайтл, издание, источник, сколько секунд,
итог и последнюю причину отказа."""
from __future__ import annotations

import threading
import time

_LOCAL = threading.local()


def note(tag: str, message: str) -> None:
    """Последняя жалоба рабочего потока — причина неудачной попытки."""
    if getattr(_LOCAL, "active", False):
        _LOCAL.last = f"{tag}: {message}"


def page(cand, url: str, link: str = "") -> None:
    """Страница, которую попытка взяла резать: глава на сайте, номер, картинка.

    По ним в журнале можно открыть ту же страницу и самому посмотреть, почему
    проверка отвергла вырезку (просьба пользователя, прогоны 9 октября)."""
    if not url:
        return
    info = getattr(cand, "_manga_page_info", None) or {}
    tried = getattr(cand, "_tried_pages", None)
    if tried is None:
        tried = cand._tried_pages = []
    link = link or getattr(cand, "source_link", "") or ""
    tried.append((str(link), info.get("number"), str(url)))


def _pages(cand) -> str:
    rows = []
    for link, number, url in getattr(cand, "_tried_pages", ())[-4:]:
        where = f"глава {link}" if link else "глава —"
        if number:
            where += f", стр. {number}"
        rows.append(f"{where}: {url}")
    return "; страницы — " + " | ".join(rows) if rows else ""


def _source(cand) -> str:
    client = getattr(cand, "_manga_page_client", None)
    label = getattr(client, "label", "")
    if label:
        return label
    return "MangaDex" if getattr(cand, "frame_url", "") or getattr(cand, "source_link", "") else "—"


def run(generator, cand) -> bool:
    _LOCAL.active, _LOCAL.last = True, ""
    cand._tried_pages = []
    started = time.monotonic()
    ok = False
    try:
        ok = bool(generator.download_manga_panel(cand))
        return ok
    finally:
        _LOCAL.active = False
        seconds = time.monotonic() - started
        edition = str((getattr(cand, "anime", None) or {}).get("kind") or "книга")
        text = (f"Попытка манги «{cand.title_ru}» ({edition}, ур. {cand.level}): "
                f"{'готово' if ok else 'не вышло'} за {seconds:.0f} с; источник {_source(cand)}")
        if not ok and _LOCAL.last:
            text = (text + f"; причина — {_LOCAL.last}")[:400]
        generator.log(text + _pages(cand))
