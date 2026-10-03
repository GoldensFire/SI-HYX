"""Verified lyric sheets and conservative line-to-translation mapping."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from urllib.parse import urlencode, urljoin, urlparse

from lxml import html
from .model import normalize
from .matching import title_key


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
    return [line.strip() for line in lines if any(char.isalnum() for char in line)]


def text_lines(node, *, short):
    node = html.fromstring(html.tostring(node))
    for unwanted in node.xpath('.//script|.//style|.//button'):
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
    def __init__(self, http, log=lambda _: None):
        self.http, self.log = http, log
        self._blocked = set()

    def search(self, title, artist, *, duration):
        # AnimeLyrics first. It may be unavailable behind its challenge page.
        providers = (self.animelyrics, self.animesonglyrics)
        for provider in providers:
            if provider.__name__ in self._blocked:
                continue
            try:
                result = provider(title, artist, duration < 150)
                if result:
                    return result
            except Exception as error:
                if getattr(getattr(error, "response", None), "status_code", 0) == 403:
                    self._blocked.add(provider.__name__)
                self.log(f"Караоке: {provider.__name__}: {str(error)[:140]}")
        return None

    def animelyrics(self, title, artist, short):
        base = "https://www.animelyrics.com"
        url = base + "/search.php?" + urlencode({"q": title})
        tree = parse_html(self.http.bytes(url, maximum=2_000_000))
        for link in tree.xpath('//a[contains(@href,".htm")]'):
            if title_key(title) not in title_key(link.text_content()):
                continue
            page = urljoin(base, link.get("href"))
            if urlparse(page).hostname != "www.animelyrics.com":
                continue
            document = parse_html(self.http.bytes(page, maximum=2_000_000))
            headings = " ".join(document.xpath('//h1//text()|//h2//text()'))
            if title_key(title) not in title_key(headings):
                continue
            if normalize(artist) not in normalize(document.text_content()):
                continue
            roman = document.xpath('//*[contains(@class,"romaji") or @id="romaji"]')
            japanese = document.xpath('//*[contains(@class,"kanji") or @id="kanji"]')
            english = document.xpath('//*[contains(@class,"translation") or @id="translation"]')
            if roman:
                return Sheet(title, artist, page,
                             text_lines(japanese[0], short=short) if japanese else [],
                             text_lines(roman[0], short=short),
                             {"en": text_lines(english[0], short=short)} if english else {})
        return None

    def animesonglyrics(self, title, artist, short):
        base = "https://www.animesonglyrics.com"
        tree = parse_html(self.http.bytes(base + "/results?" + urlencode({"q": title}),
                                         maximum=3_000_000))
        pages = []
        for link in tree.xpath('//a[@href]'):
            page = urljoin(base, link.get("href"))
            if (urlparse(page).hostname != "www.animesonglyrics.com"
                    or page in pages or page.count("/") != 4):
                continue
            text = link.text_content()
            if title_key(title) in title_key(text) and normalize(artist) in normalize(text):
                pages.append(page)
        for page in pages[:3]:
            document = parse_html(self.http.bytes(page, maximum=3_000_000))
            heading = " ".join(document.xpath('//h1//text()'))
            if title_key(title) not in title_key(heading) or normalize(artist) not in normalize(heading):
                continue
            def extract(name):
                nodes = document.xpath(f'//div[contains(@class,"{name}lyrics-sbs")]')
                return text_lines(nodes[0], short=short) if nodes else []
            roman, native, english = extract("romaji"), extract("kanji"), extract("english")
            native = [re.sub(r"(?<=[\u3400-\u9fff])[（(][\u3040-\u30ffー]+[）)]", "", line).strip("\ufeff ")
                      for line in native]
            if roman:
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
