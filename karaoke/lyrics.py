"""Verified lyric sheets and conservative line-to-translation mapping."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from urllib.parse import urlencode, urljoin, urlparse

from lxml import html
from .model import normalize
from .matching import title_key
from .search import queries, title_names, matches_page


@dataclass
class Sheet:
    title: str
    artist: str
    url: str
    original: list[str]
    romaji: list[str]
    translations: dict[str, list[str]] = field(default_factory=dict)


def clean_lines(lines):
    """Site expanders and musical separators are not sung lyric lines."""
    placeholders = {"na", "notavailable", "lyricsnotavailable", "kanjinotavailable"}
    return [line.strip() for line in lines if any(char.isalnum() for char in line)
            and normalize(line) not in placeholders]


def text_lines(node, *, short):
    node = html.fromstring(html.tostring(node))
    for unwanted in node.xpath('.//script|.//style|.//button|.//rt|.//rp'):
        unwanted.drop_tree()
    for br in node.xpath('.//br|.//hr'):
        br.tail = "\n" + (br.tail or "")
    lines = []
    version = None
    for line in node.text_content().splitlines():
        line = line.strip()
        if re.match(r"\[.*(?:version|tv|full).*\]", line, re.I):
            version = "short" if "tv" in line.lower() else "full"
            continue
        if version is not None and (version == "short") != short:
            continue
        if line and not line.startswith(("[", "Lyrics from", "Romaji", "English", "Japanese")):
            lines.append(line)
    return clean_lines(lines)


def parse_html(payload):
    # libxml's HTML default is Latin-1 when a page lacks an old-style charset
    # meta tag; these sources use UTF-8. Wrong decoding corrupts Japanese text
    # and can even turn UTF-8 bytes into artificial line separators.
    return html.fromstring(payload.decode("utf-8-sig"))


class LyricSites:
    def __init__(self, http, log=lambda _: None, *, audit=None):
        self.http, self.log = http, log
        self.audit = audit
        self._blocked = set()

    def _record(self, provider, status, title, artist, **details):
        if self.audit:
            name = provider.__name__
            if name == "uta_net":
                if status in ("sheet", "no_match"):
                    return  # UtaNet records these with publication identity details.
                name = "Uta-Net Global"
            self.audit.record(name, status, title, artist, **details)

    def search(self, title, artist, *, duration, context=None):
        return self.lookup(title, artist, duration=duration, context=context)[0]

    def available(self, title, artist, *, duration, context=None):
        """Original lyrics before the recording is downloaded: True/False, or
        None when a provider failed and absence is not proven."""
        sheet, uncertain = self.lookup(title, artist, duration=duration, context=context)
        if sheet is not None and sheet.original:
            return True
        return None if uncertain else False

    def lookup(self, title, artist, *, duration, context=None):
        # Prefer reachable plain-text providers. AnimeLyrics challenges and
        # failed CDN addresses must not delay every otherwise available song.
        providers = (self.animesonglyrics, self.uta_net, self.animelyrics)
        partial = None
        uncertain = False
        for provider in providers:
            if provider.__name__ in self._blocked:
                # Blocked for the rest of the run: resolve() cannot use it either.
                self._record(provider, "blocked", title, artist)
                continue
            self._record(provider, "searched", title, artist)
            try:
                visited = set()
                planned = [title] if provider.__name__ == "uta_net" else queries(title, artist, context)
                for query in planned:
                    result = provider(title, artist, duration < 150, query=query,
                                      context=context, visited=visited)
                    if result:
                        self._record(provider, "sheet" if result.original else "romaji_only",
                                     title, artist, url=result.url, lines=len(result.original))
                        if result.original:
                            return result, False
                        partial = partial or result
                self._record(provider, "no_match", title, artist)
            except Exception as error:
                import requests
                if (getattr(getattr(error, "response", None), "status_code", 0) == 403
                        or isinstance(error, (requests.ConnectionError, requests.Timeout))):
                    self._blocked.add(provider.__name__)
                self.log(f"Караоке: {provider.__name__}: {str(error)[:140]}")
                self._record(provider, "error", title, artist, reason=str(error)[:300])
                uncertain = True
        return partial, uncertain

    def uta_net(self, title, artist, short, *, query=None, context=None, visited=None):
        from .source_audit import SourceAudit
        from .uta_net import UtaNet
        return UtaNet(self.http, self.audit or SourceAudit()).search(title, artist, context)

    def animelyrics(self, title, artist, short, *, query=None, context=None, visited=None):
        base = "https://www.animelyrics.com"
        url = base + "/search.php?" + urlencode({"q": query or title})
        tree = parse_html(self.http.bytes(url, maximum=2_000_000))
        for link in tree.xpath('//a[contains(@href,".htm")]'):
            page = urljoin(base, link.get("href"))
            if urlparse(page).hostname != "www.animelyrics.com":
                continue
            if visited is not None:
                if page in visited:
                    continue
                visited.add(page)
            document = parse_html(self.http.bytes(page, maximum=2_000_000))
            headings = " ".join(document.xpath('//h1//text()|//h2//text()'))
            if not matches_page(title, artist, headings, "\n".join(document.xpath('//text()')), context):
                continue
            roman = document.xpath('//*[contains(@class,"romaji") or @id="romaji"]')
            japanese = document.xpath('//*[contains(@class,"kanji") or @id="kanji"]')
            english = document.xpath('//*[contains(@class,"translation") or @id="translation"]')
            if roman or japanese:
                return Sheet(title, artist, page,
                             text_lines(japanese[0], short=short) if japanese else [],
                             text_lines(roman[0], short=short) if roman else [],
                             {"en": text_lines(english[0], short=short)} if english else {})
        return None

    def animesonglyrics(self, title, artist, short, *, query=None, context=None, visited=None):
        base = "https://www.animesonglyrics.com"
        tree = parse_html(self.http.bytes(base + "/results?" + urlencode({"q": query or title}),
                                         maximum=3_000_000))
        pages = []
        for link in tree.xpath('//a[@href]'):
            page = urljoin(base, link.get("href"))
            if (urlparse(page).hostname != "www.animesonglyrics.com"
                    or page in pages or page.count("/") != 4):
                continue
            # Anime/performer searches may show only the anime in the link.
            # Validate song and performer on the destination page instead.
            pages.append(page)
        names = title_names(title, context)
        pages.sort(key=lambda page: not any(title_key(name) in title_key(page) for name in names))
        for page in pages[:12]:
            if visited is not None:
                if page in visited:
                    continue
                visited.add(page)
            document = parse_html(self.http.bytes(page, maximum=3_000_000))
            heading = " ".join(document.xpath('//h1//text()'))
            if not matches_page(title, artist, heading, "\n".join(document.xpath('//text()')), context):
                continue
            def extract(name):
                nodes = document.xpath(f'//div[contains(@class,"{name}lyrics-sbs")]')
                return text_lines(nodes[0], short=short) if nodes else []
            roman, native, english = extract("romaji"), extract("kanji"), extract("english")
            native = [re.sub(r"(?<=[\u3400-\u9fff])[（(][\u3040-\u30ffー]+[）)]", "", line).strip("\ufeff ")
                      for line in native]
            if not native and roman and roman == english:
                native = list(roman)
            if short and native and roman:
                from .lyric_versions import native_version
                native = native_version(native, roman)
            if roman or native:
                return Sheet(title, artist, page, native, roman,
                             {"en": english} if english else {})
        return None


def add_translations(lines, sheet):
    if not sheet or len(sheet.romaji) < 1:
        return
    # Without a demonstrable one-to-one text mapping, do not guess translations
    # by line number: TV/full edits and differently split lines are common.
    for language in ("ru", "en"):
        translated = sheet.translations.get(language) or []
        if len(translated) != len(sheet.romaji):
            continue
        cursor = 0
        for line in lines:
            scores = [(SequenceMatcher(None, normalize(line.text), normalize(text)).ratio(), i)
                      for i, text in enumerate(sheet.romaji) if i >= cursor]
            matches = [(score, i) for score, i in scores if score >= .94]
            if matches:
                _, index = max(matches, key=lambda pair: (pair[0], -pair[1]))
                line.translations.setdefault(language, translated[index])
                cursor = index + 1
