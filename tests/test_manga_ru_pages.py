# -*- coding: utf-8 -*-
"""ReManga access restrictions and shared page-selection behavior."""
import io

import animepack as ap
from animepack_api import MangaPageSources, ReMangaApi
from PIL import Image
from si_hyx_parts.animepack_api.manga_reader_base import SOURCE_LABELS
from si_hyx_parts.animepack_api.ru_manga_clients import (
    PublicSourceError, ReMangaPopulation, MangaLibPopulation)
from test_animepack_manga_sakuga import generator  # noqa: F401
from test_animepack_manga_sources import Reader
from test_manga_ru_cache import title
from test_manga_ru_popularity import manga


class Population:
    def __init__(self, paid=False, error=False):
        self.calls, self.paid, self.error = [], paid, error
        self.row = title(branches=[{"id": 3}], fields={"is_licensed": False})
        self.detail = {"id": 10, "is_published": True, "price": None,
                       "pages": [{"number": i, "images": [{"link": f"https://cdn.test/{i}.png"}]}
                                 for i in range(12)]}

    def search(self, card):
        if self.error:
            raise PublicSourceError("HTTP 403")
        return [self.row]

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path == "/api/titles/chapters/":
            return {"content": [{"id": 10, "is_paid": self.paid}]}
        assert path == "/api/titles/chapters/10/"
        return {"content": self.detail}


def test_free_remanga_chapter_is_an_additional_page_source():
    population = Population()
    reader = ReMangaApi(population=population)
    clients = {key: Reader() for key in SOURCE_LABELS}
    clients["remanga"] = reader
    sources = MangaPageSources(clients=clients)
    url = sources.panel_url(manga())
    assert url.startswith("https://cdn.test/")
    assert sources.last_source == "ReManga"
    assert sources.last_chapter == "10"
    assert sources.last_source_link == ReMangaApi.base_url + "/manga/external-title"
    assert population.calls[0][1]["branch_id"] == 3
    assert all(not clients[key].calls for key in SOURCE_LABELS
               if key != "remanga")
    assert not clients["mangalib"].calls


def test_paid_chapter_is_never_fetched():
    population = Population(paid=True)
    assert ReMangaApi(population=population).panel_url(manga()) == ""
    assert len(population.calls) == 1
    assert population.calls[0][0] == "/api/titles/chapters/"


def test_unknown_payment_status_unpublished_or_changed_paid_detail_is_rejected():
    for changes in ({"is_published": False}, {"is_paid": True},
                    {"is_paid": "false"}, {"price": "1.00"}, {"id": 99},
                    {"delay_pub_date": "2999-01-01T00:00:00Z"}):
        population = Population()
        population.detail.update(changes)
        assert ReMangaApi(population=population).panel_url(manga()) == ""
    population = Population()
    population.paid = None
    assert ReMangaApi(population=population).panel_url(manga()) == ""
    assert len(population.calls) == 1


def test_licensed_or_forbidden_title_does_not_read_chapters():
    for field in ("is_licensed", "is_forbidden"):
        population = Population()
        population.row["fields"][field] = True
        assert ReMangaApi(population=population).panel_url(manga()) == ""
        assert not population.calls
    population = Population()
    population.row["fields"].pop("is_licensed")
    assert ReMangaApi(population=population).panel_url(manga()) == ""
    assert not population.calls


def test_language_and_repeat_filter_use_existing_page_pipeline():
    population = Population()
    reader = ReMangaApi(population=population, language="en")
    assert reader.panel_url(manga()) == ""
    assert not population.calls
    reader = ReMangaApi(population=population, language="ru")
    blocked = {f"https://cdn.test/{i}.png" for i in range(12)}
    assert reader.panel_url(manga(), blocked) == ""


def test_remanga_failure_falls_back_to_existing_sources():
    clients = {key: Reader() for key in SOURCE_LABELS}
    clients["remanga"] = ReMangaApi(population=Population(error=True))
    clients["mangadex"].result = "https://md.test/page.png"
    sources = MangaPageSources(clients=clients)
    card = manga()
    assert sources.panel_url(card) == clients["mangadex"].result
    assert any("HTTP 403" in reason for reason in sources.last_errors)
    assert sources.panel_url(card) == clients["mangadex"].result


def test_popularity_and_page_source_are_independent():
    clients = {key: Reader() for key in SOURCE_LABELS}
    clients["mangadex"].result = "https://md.test/page.png"
    sources = MangaPageSources(sources={"mangadex": True}, clients=clients)
    candidate = ap.SongCandidate({}, manga(), media="manga")
    candidate.ru_popularity = {"sources": {"remanga": {"status": "NORMAL"},
                                          "mangalib": {"status": "NORMAL"}},
                               "ru_equivalent_book_index": 15000}
    assert sources.panel_url(candidate.anime) == clients["mangadex"].result
    assert sources.last_source == "MangaDex"
    assert candidate.effective_book_index >= candidate.book_index
    assert not clients["remanga"].calls


def test_generator_processes_remanga_image_and_keeps_attribution(generator):
    class Images:
        def get(self, url, **kwargs):
            stream = io.BytesIO()
            Image.new("RGB", (300, 500), "white").save(stream, "PNG")
            class Response:
                content = stream.getvalue()

                def raise_for_status(self):
                    pass
            return Response()
    reader = ReMangaApi(session=Images(), population=Population())
    generator.mangadex = MangaPageSources(sources={"remanga": True},
                                         clients={"remanga": reader})
    generator.s.manga_gemini_check = False
    candidate = ap.SongCandidate({}, manga(), kind=ap.MANGA_KIND, media="manga")
    assert generator.download_manga_panel(candidate)
    assert candidate.source_link == ReMangaApi.base_url + "/manga/external-title"
    assert candidate.frame_name.endswith(".png")


def test_population_fields_do_not_use_average_rating_or_page_count_as_audience():
    remanga = ReMangaPopulation().normalize({"id": 1, "dir": "slug", "type": 2,
        "count_bookmarks": 120000, "is_licensed": False, "avg_rating": "10",
        "total_votes": 30, "total_views": 500000, "count_chapters": 0})
    assert remanga["raw_metric"] == 120000 and remanga["kind"] == "manhwa"
    assert remanga["status"] == "NORMAL"
    mangalib = MangaLibPopulation().normalize({"id": 2, "slug_url": "2--slug",
        "type": {"label": "Манхва"}, "views": 90000, "rate": 40,
        "rate_avg": 10, "chap_count": 0, "close_view": 0, "shiki_id": 77,
        "rating": {"votes": 614, "average": "10"}})
    assert mangalib["raw_metric"] == 614 and mangalib["kind"] == "manhwa"
    assert mangalib["status"] == "NORMAL"
    assert "is_licensed" not in mangalib["fields"]
    assert MangaLibPopulation().normalize({"id": 2, "slug_url": "s", "views": 1,
        "type_id": 999, "close_view": 1})["status"] == "RIGHTS_RESTRICTED"


def test_population_client_does_not_fetch_pages():
    assert SOURCE_LABELS["mangalib"] == "MangaLib"
    assert not hasattr(MangaLibPopulation, "pages")
