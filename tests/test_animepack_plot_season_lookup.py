# -*- coding: utf-8 -*-
"""Season pages on Fandom are used before unrelated franchise episodes."""
import random

from animepack_api import FandomApi
from animepack_plot import pick_plot, source_page_ok


class SeasonWiki(FandomApi):
    def __init__(self):
        super().__init__(session=object())
        self.slugs = []
        self.pages = []

    def wiki_at(self, slug):
        self.slugs.append(slug)
        return "attackontitan.fandom.com" if slug == "attackontitan" else ""

    def page_source(self, host, page):
        self.pages.append(page)
        if page == "List of Attack on Titan episodes/Season 3":
            return "== Episodes ==\n{{Episode/2\n| Page = Smoke Signal (Episode)\n}}"
        if page == "Smoke Signal (Episode)":
            return ("{{Episode\n|season number=3\n}}\n== Summary ==\n"
                    + "Эрен и его друзья узнают новый план разведкорпуса. " * 9)
        return ""

    def episode_pages(self, host):
        raise AssertionError("Season index should avoid a franchise-wide search")

    def search(self, host, query, limit=0):
        raise AssertionError("Season index should avoid another search")


def test_season_title_finds_the_franchise_wiki_first():
    fandom = SeasonWiki()
    assert fandom.find_wiki(["Attack on Titan Season 3"]) == \
        "attackontitan.fandom.com"
    assert fandom.slugs == ["attackontitan"]


def test_season_index_yields_a_real_episode_retelling():
    fandom = SeasonWiki()
    got = pick_plot(fandom, ["Attack on Titan Season 3"], random.Random(0),
                    title="Атака титанов 3", year=2018)
    assert got["page"] == "Smoke Signal (Episode)"
    assert len(got["text"]) >= 220
    assert "Smoke Signal (Episode)" in fandom.pages


def test_infobox_season_prevents_wrong_season_and_accepts_right_one():
    raw = "{{Episode\n|season number=3\n}}\n== Summary ==\n" + "Сюжет. " * 50
    assert source_page_ok("Smoke Signal (Episode)", raw, "Атака титанов 3", 2018)
    assert not source_page_ok("Smoke Signal (Episode)", raw, "Атака титанов", 2018)


def test_plot_generator_keeps_selected_high_thinking_level():
    import animepack

    logs = []
    settings = animepack.PackSettings(
        pct_songs=0, pack_plot=True, pct_plot=100, gemini_key="test-key",
        gemini_model="gemini-3.5-flash-lite", gemini_thinking="high")
    generator = animepack.AnimePackGenerator(settings, log=logs.append)
    assert generator.gemini.thinking == "high"
    assert any("gemini-3.5-flash-lite" in line and "high" in line
               for line in logs)
