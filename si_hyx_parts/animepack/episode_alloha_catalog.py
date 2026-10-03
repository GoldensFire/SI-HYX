"""Actual Alloha episode/translation metadata, without executing site scripts."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .episode_ru_catalog import get, integer, release, subtitle_release


def file_list(content):
    match = re.search(r"\bfileList\s*=\s*JSON\.parse\(\s*(['\"])((?:\\.|(?!\1).)*)\1\s*\)",
                      content, re.S)
    if not match:
        raise ValueError("Alloha: в ответе нет списка серий и переводов")
    # Decode only a string literal. JSON.parse's argument is data, never Python/JS code.
    def unescape(match):
        value = match.group(1)
        if value.startswith("u"):
            return chr(int(value[1:], 16))
        if value.startswith("x"):
            return chr(int(value[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(value, value)
    decoded = re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", unescape, match[2])
    data = json.loads(decoded)
    if not isinstance(data, dict):
        raise ValueError("Alloha: некорректный список серий")
    return data


def episode_url(embed, season, number, translation):
    parts = urlsplit(embed)
    params = parse_qs(parts.query)
    params.update(season=[str(season)], episode=[str(number)], translation=[str(translation)])
    return urlunsplit(parts._replace(query=urlencode(params, doseq=True)))


def releases(data, embed, referer, source):
    active = data.get("active") or {}
    requested = parse_qs(urlsplit(embed).query)
    season = integer((requested.get("season") or [active.get("seasons") or 1])[0])
    all_rows = data.get("all") or {}
    movie = data.get("type") == "movie"
    episodes = {"1": all_rows} if movie else all_rows.get(str(season)) or {}
    catalog = {}
    for number, translations in episodes.items():
        number = integer(number)
        if not number or not isinstance(translations, dict):
            continue
        for item in translations.values():
            if not isinstance(item, dict) or not subtitle_release(item.get("translation")):
                continue
            translation = integer(item.get("id_translation"))
            if not translation:
                continue
            if not movie and (integer(item.get("episode")) != number
                              or integer(item.get("seasons")) != season):
                continue
            catalog.setdefault(number, []).append(release(
                source, "alloha", episode_url(embed, season, number, translation), referer,
                label=item["translation"], release_id=item.get("id"),
                season=season, episode=number))
    return catalog


async def catalogue(embed, referer, source):
    content = (await get(embed, headers={"Referer": referer})).text
    return releases(file_list(content), embed, referer, source)
