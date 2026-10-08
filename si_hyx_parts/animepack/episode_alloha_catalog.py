"""Actual Alloha episode/translation metadata, without executing site scripts."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .episode_ru_catalog import Catalogue, get, integer, release, subtitle_release


def file_list(content):
    # Обратная косая — только начало экранирования. Если вторая ветка тоже её
    # принимает, строка «\a\a\a…» разбирается 2^n способами (ReDoS).
    match = re.search(r"\bfileList\s*=\s*JSON\.parse\(\s*(['\"])((?:\\.|(?!\1)[^\\])*)\1\s*\)",
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


def tvdb_numbers(ctx):
    """{номер серии тайтла: (сезон, серия)} по TVDB из AniZip, если он известен."""
    result = {}
    for key, row in ((ctx or {}).get("anizip", {}).get("episodes") or {}).items():
        number = integer(key)
        if number and isinstance(row, dict):
            season, episode = integer(row.get("seasonNumber")), integer(row.get("episodeNumber"))
            if season and episode:
                result[number] = (season, episode)
    return result


def season_items(rows):
    """(серия, перевод) сезона; Alloha отдаёт серии словарём или списком."""
    groups = rows.items() if isinstance(rows, dict) else enumerate(rows or [])
    for key, translations in groups:
        if not isinstance(translations, (dict, list)):
            continue
        values = translations.values() if isinstance(translations, dict) else translations
        for item in values:
            if not isinstance(item, dict):
                continue
            episode = integer(item.get("episode"))
            if episode and (not isinstance(rows, dict) or integer(key) == episode):
                yield episode, item


def numbering(data, embed, ctx):
    """Пары (номер серии тайтла, сезон Alloha, серия Alloha) либо причина отказа.

    Alloha хранит франшизу целиком: у «Звучи, эуфониум! 2» там сезоны 1–3 по
    13 серий, а active.seasons указывает последний. Без явного сезона в ссылке
    сезон берётся из нумерации TVDB (AniZip); не сопоставилось — источник
    пропускается, а не подставляет серию другого сезона."""
    seasons = {integer(key): rows for key, rows in (data.get("all") or {}).items() if integer(key)}

    def present(season):
        return {episode for episode, _ in season_items(seasons.get(season))}

    explicit = integer((parse_qs(urlsplit(embed).query).get("season") or [0])[0])
    if explicit:
        return [(number, explicit, number) for number in sorted(present(explicit))], ""
    mapping = tvdb_numbers(ctx)
    if mapping and all(season in seasons for season, _ in mapping.values()):
        pairs = [(number, season, episode) for number, (season, episode) in sorted(mapping.items())
                 if episode in present(season)]
        if pairs:
            return pairs, ""
    expected = integer(((ctx or {}).get("media") or {}).get("episodes"))
    if len(seasons) == 1:
        season = next(iter(seasons))
        numbers = sorted(present(season))
        if not expected or len(numbers) <= expected:
            return [(number, season, number) for number in numbers], ""
    if not seasons:
        return [], ""
    return [], ("Alloha: во франшизе сезоны " + ", ".join(map(str, sorted(seasons)))
                + "; сезон тайтла не сопоставлен")


def releases(data, embed, referer, source, ctx=None):
    catalog = Catalogue()
    if data.get("type") == "movie":
        translations = data.get("all") or {}
        values = translations.values() if isinstance(translations, dict) else translations
        for item in values or ():
            if isinstance(item, dict) and subtitle_release(item.get("translation"))                     and integer(item.get("id_translation")):
                catalog.setdefault(1, []).append(release(
                    source, "alloha", episode_url(embed, 1, 1, integer(item["id_translation"])), referer,
                    label=item["translation"], release_id=item.get("id"), season=1, episode=1))
        return catalog
    pairs, catalog.reason = numbering(data, embed, ctx)
    seasons = {integer(key): rows for key, rows in (data.get("all") or {}).items() if integer(key)}
    for number, season, episode in pairs:
        for found, item in season_items(seasons.get(season)):
            translation = integer(item.get("id_translation"))
            if (found != episode or integer(item.get("seasons")) != season or not translation
                    or not subtitle_release(item.get("translation"))):
                continue
            catalog.setdefault(number, []).append(release(
                source, "alloha", episode_url(embed, season, episode, translation), referer,
                label=item["translation"], release_id=item.get("id"),
                season=season, episode=episode))
    return catalog


async def catalogue(embed, referer, source, ctx=None):
    from .episode_release_cache import public_metadata
    async def load():
        content = (await get(embed, headers={"Referer": referer})).text
        return file_list(content)
    data = await public_metadata(embed, load)
    return releases(data, embed, referer, source, ctx)
