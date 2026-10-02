# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""WeebCentral's HTML fragment API: search, chapters and reader images."""
import re
from .manga_reader_base import MangaReaderBase, web_url


def _text(node):
    return " ".join(node.text_content().split())


class WeebCentralApi(MangaReaderBase):
    label = "WeebCentral"
    base_url = "https://weebcentral.com"
    languages = ("en",)

    def _html(self, path, params=None):
        from lxml import html
        response = self._request(path, params)
        return html.fromstring(response.content if response is not None
                               else b"<section></section>",
                               parser=html.HTMLParser(encoding="utf-8"))

    def search(self, query):
        doc = self._html("/search/data", {
            "text": re.sub(r"[!#:(),-]", " ", query).strip(),
            "limit": 32, "offset": 0, "display_mode": "Full Display"})
        out = []
        for link in doc.xpath('//article/section/a[contains(@href,"/series/")]'):
            path = link.get("href", "")
            parts = path.split("/series/", 1)[-1].split("/")
            title = link.xpath('./div[not(@class)][last()]')
            out.append({"id": parts[0], "path": path,
                        "titles": [_text(title[0]) if title else _text(link)]})
        return out

    def details(self, row):
        doc = self._html(row["path"].removeprefix(self.base_url))
        titles = [_text(n) for n in doc.xpath('//h1')]
        titles += [_text(n) for n in doc.xpath(
            '//li[strong[contains(.,"Associated Name")]]//li')]
        mal = doc.xpath('//a[contains(@href,"myanimelist.net/manga/")]/@href')
        mal_id = re.search(r"/manga/(\d+)", mal[0]) if mal else None
        tags = [_text(n).casefold() for n in doc.xpath(
            '//li[strong[contains(.,"Tag")]]//a')]
        adult = doc.xpath('//li[strong[contains(.,"Adult")]]')
        rating = "safe"
        if any(t in ("hentai", "pornographic") for t in tags):
            rating = "pornographic"
        elif "smut" in tags or any(re.search(r"\byes\b", _text(n), re.I)
                                   for n in adult):
            rating = "erotica"
        return dict(row, titles=titles or row["titles"], rating=rating,
                    mal_id=mal_id[1] if mal_id else "")

    def chapters(self, row):
        doc = self._html("/series/" + row["id"] + "/full-chapter-list")
        out = []
        for link in doc.xpath('//div[@x-data]/a[contains(@href,"/chapters/")]'):
            url = web_url(self.base_url, link.get("href"))
            key = url.split("/chapters/", 1)[-1].split("/")[0]
            if key and url:
                out.append({"id": key, "link": url})
        # The fragment is newest-first; sample up to 100 readable chapters.
        if len(out) > 100:
            out = self.rng.sample(out, 100)
        return out

    def pages(self, chapter):
        path = chapter["link"].removeprefix(self.base_url).rstrip("/") + "/images"
        doc = self._html(path, {"is_prev": "False", "reading_style": "long_strip"})
        urls = doc.xpath('//section[contains(@x-data,"scroll")]/img/@src')
        return [{"url": web_url(self.base_url, url)} for url in urls if url]
