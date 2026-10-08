"""Uta-Net Global JP/Romaji sheets with exact title and performer checks."""
from urllib.parse import urlencode
import re

from .identity import exact_identity, identity_key
from .lyrics import Sheet, parse_html, text_lines
from .search import title_names

BASE = "https://www.uta-net.com/global/en"


def published_artist_alias(payload, artist, requested):
    """Use the publisher's own full name reading, never a title-only guess."""
    tree = parse_html(payload)
    headings = tree.xpath('//h1')
    if len(headings) != 1:
        return False
    match = re.fullmatch(r'(.+?)[（(]([^()（）]+)[）)]', headings[0].text_content().strip())
    if not match or identity_key(match[1]) != identity_key(artist):
        return False
    def name_key(value):
        # Hepburn long vowels may be spelled shouko, shōko or shoko.
        from .model import normalize
        return normalize(value).replace('ou', 'o').replace('oo', 'o').replace('uu', 'u')
    published = name_key(match[2])
    for name in requested:
        words = str(name).split()
        # A Japanese personal name in surname/given or given/surname order.
        # Do not reinterpret groups, duets or credits with extra performers.
        if len(words) != 2 or not all(word.isalpha() for word in words):
            continue
        if published in (name_key(''.join(words)), name_key(''.join(reversed(words)))):
            return True
    return False


def parse_sheet(payload, url):
    tree = parse_html(payload)
    titles = tree.xpath('//h1/span[not(contains(@class,"artist-name"))]')
    artists = tree.xpath('//h1/span[contains(@class,"artist-name")]')
    roman = tree.xpath('//*[@id="kashi-area-roma"]')
    native = tree.xpath('//*[@id="kashi-area"]')
    if not all((titles, artists, roman, native)):
        return None
    sheet = Sheet(titles[0].text_content().strip(), artists[0].text_content().strip(), url,
                  text_lines(native[0], short=False), text_lines(roman[0], short=False))
    return sheet if sheet.original and sheet.romaji else None


class UtaNet:
    def __init__(self, http, audit):
        self.http, self.audit = http, audit

    def search(self, title, artist, context=None):
        visited = set()
        for name in title_names(title, context)[:3]:
            data = self.http.json(BASE + "/api/searchAll/?" + urlencode({"kw": name}),
                                  maximum=2_000_000)
            for row in (data.get("song") or [])[:20]:
                id = str(row.get("tid") or "")
                if not id.isdecimal() or id in visited:
                    continue
                visited.add(id)
                # The discovery API does not return a performer; inspect the page.
                display_title = row.get("title") or ""
                if row.get("titleRoma"):
                    display_title += "(" + row["titleRoma"] + ")"
                if not exact_identity(title, artist, display_title, artist, context):
                    continue
                url = BASE + "/lyric/" + id + "/"
                payload = self.http.bytes(url, maximum=3_000_000)
                sheet = parse_sheet(payload, url)
                matched = bool(sheet and exact_identity(title, artist, sheet.title, sheet.artist, context))
                if (sheet and not matched and
                        exact_identity(title, sheet.artist, sheet.title, sheet.artist, context)):
                    links = parse_html(payload).xpath('//a[contains(@href,"/global/en/artist/")]/@href')
                    for link in links[:1]:
                        if not re.fullmatch(r'/global/en/artist/\d+/', link):
                            continue
                        evidence = 'https://www.uta-net.com' + link
                        if published_artist_alias(self.http.bytes(evidence, maximum=3_000_000),
                                                  sheet.artist, [artist, *(context or {}).get('artists', [])]):
                            matched = True
                            self.audit.record('Uta-Net Global', 'artist_alias_confirmed', title, artist,
                                              publication_artist=sheet.artist, evidence_url=evidence)
                if matched:
                    self.audit.record("Uta-Net Global", "sheet", title, artist, url=url)
                    return sheet
                self.audit.record("Uta-Net Global", "identity_rejected", title, artist, url=url)
        self.audit.record("Uta-Net Global", "no_match", title, artist)
        return None
