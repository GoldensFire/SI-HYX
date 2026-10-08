"""AnimeGO.online's DLE search and public player relay, with exact title binding."""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import re

from lxml import html

from .episode_ru_catalog import (Catalogue, absolute, error_detail, get, integer, matches,
                                 names, player_name, release, subtitle_release)

BASE = "https://animego.online"
MIRRORS = (BASE,)
RELAY = BASE + "/engine/ajax/controller.php"


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def parse_players(content, referer):
    episodes, players = {}, []
    for _tag, attrs in Tags(content).tags:
        number = integer(attrs.get("data-episode-number"))
        if number and attrs.get("data-episode"):
            episodes[number] = str(attrs["data-episode"])
        embed = attrs.get("data-player")
        label = attrs.get("data-translation-title", "")
        player = player_name(attrs.get("data-provider-title", ""), embed)
        if embed and player and subtitle_release(label):
            players.append(release("animego", player, embed, referer, label=label))
    return episodes, players


async def player_html(url, referer):
    data = (await get(url, headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})).json()
    return str((data.get("data") or {}).get("content") or "")


def search_rows(content, base=BASE):
    tree = html.fromstring(content)
    rows = {}
    for link in tree.xpath('//a[@href]'):
        url = absolute(link.get("href"), base)
        ident = re.search(r"/(\d+)-[^/?#]+\.html(?:$|[?#])", url)
        if not ident or not url.startswith(base + "/"):
            continue
        titles = link.xpath('.//*[contains(@class,"__title")]')
        title = titles[0].text_content().strip() if titles else link.get("title", "")
        if title:
            rows[url] = {"id": ident[1], "title": title, "url": url}
    return list(rows.values())


def page_identity(content):
    tree = html.fromstring(content)
    original = tree.xpath('//*[contains(@class,"page__original")]//text()')
    row = {"title": " ".join(tree.xpath('//h1//text()')).strip(),
           "other_titles": [text.strip() for text in original if text.strip()]}
    for link in tree.xpath('//a[@href]'):
        href = link.get("href", "")
        mal = re.search(r'(?:myanimelist\.net/anime|shikimori\.[^/]+/animes)/(\d+)', href)
        if mal:
            row["mal_id"] = int(mal[1])
            break
    return row, tree


async def page_catalogue(tree, referer, ctx=None):
    from .episode_ru_players import subtitle_playlist
    from .episode_alloha_catalog import catalogue as alloha_catalogue
    roots = tree.xpath('//*[@data-player-anime-id]')
    if not roots:
        raise ValueError("AnimeGO.online: на странице нет списка плееров")

    async def collect(root, slot):
        label = slot.get("data-player-title", "")
        player = player_name(label, "")
        if not player:
            return {}  # This player has no supported native-stream resolver.
        data = (await get(RELAY, params={"mod": "player", "id": root.get("data-player-anime-id"),
                                        "slot": slot.get("data-player-slot")},
                          headers={"Referer": referer})).json()
        if not data.get("status") or not isinstance(data.get("data"), dict):
            raise ValueError("AnimeGO.online: плеер не вернул свои данные")
        data = data["data"]
        if data.get("kind") == "cvh":
            return await subtitle_playlist(referer, referer, "animego",
                title_id=data["title_id"], publisher=data["pub_id"], aggregator=data["aggregator"])
        embed = absolute(data.get("src"), referer)
        if player == "alloha" and embed:
            return await alloha_catalogue(embed, referer, "animego", ctx)
        raise ValueError("AnimeGO.online: неподдерживаемый формат плеера " + label)

    results = await asyncio.gather(*(collect(root, slot) for root in roots
        for slot in root.xpath('.//*[@data-player-slot]')), return_exceptions=True)
    catalog, failures = {}, []
    reasons = [getattr(result, "reason", "") for result in results
               if not isinstance(result, BaseException)]
    for result in results:
        if isinstance(result, Exception):
            failures.append(error_detail(result))
        elif isinstance(result, BaseException):
            raise result
        else:
            for number, rows in result.items():
                catalog.setdefault(number, []).extend(rows)
    if failures and not catalog:
        raise RuntimeError("AnimeGO.online: " + "; ".join(failures))
    reason = next((text for text in reasons if text), "")
    return Catalogue(catalog, reason=reason) if reason and not catalog else catalog


async def catalogue(candidate, ctx):
    visited, failures = set(), []
    found = False
    for query in names(candidate, ctx)[:6]:
        response = await get(BASE + "/index.php", params={"do": "search", "subaction": "search", "story": query})
        rows = search_rows(response.text)
        # Search cards omit the original title. Confirm it on bounded title pages.
        rows.sort(key=lambda row: not matches(row, candidate, ctx))
        for row in rows[:4]:
            if row["url"] in visited:
                continue
            visited.add(row["url"])
            page = await get(row["url"])
            identity, tree = page_identity(page.text)
            if not matches(identity, candidate, ctx):
                continue
            found = True
            try:
                catalog = await page_catalogue(tree, str(getattr(page, "url", row["url"])), ctx)
            except Exception as error:
                failures.append(error_detail(error))
                continue
            if catalog:
                return Catalogue(catalog)
            return Catalogue(reason=getattr(catalog, "reason", "")
                             or "тайтл найден; в плеерах нет RU-субтитров; Kodik пропущен")
        if found:
            break
    if failures:
        raise RuntimeError("; ".join(failures))
    return Catalogue(reason="тайтл не найден на animego.online")


async def expand(row):
    content = await player_html(row["embed"], row["referer"])
    return parse_players(content, row["referer"])[1]
