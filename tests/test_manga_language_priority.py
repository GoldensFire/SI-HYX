"""Language priority also survives rejected scenes and blocked sources."""
from animepack_api import MangaPageSources
from si_hyx_parts.animepack_api.manga_reader_base import SOURCE_LABELS
from test_animepack_manga_pages import _card, _chapter, _row, _session, MAIN
from animepack_api import MangaDexApi


class Reader:
    def __init__(self, source, available, calls):
        self.source, self.available, self.calls = source, available, calls
        self.language = ""
        self.last_chapter = "chapter"
        self.last_source_link = "https://reader.test/chapter"
        self.last_titles = ["Title"]

    def panel_url(self, card, excluded):
        self.calls.append((self.source, self.language))
        url = self.available.get(self.language, "")
        return url if url not in excluded else ""


def _sources(available, **options):
    calls = []
    clients = {key: Reader(key, available.get(key, {}), calls)
               for key in SOURCE_LABELS}
    return MangaPageSources(clients=clients, **options), calls


def test_russian_readers_win_and_retries_stay_in_russian():
    api, calls = _sources({"remanga": {"ru": "remanga-page"},
                           "mangalib": {"ru": "mangalib-page"},
                           "mangadex": {"en": "english-page"}})
    assert api.panel_url(_card()) == "remanga-page"
    assert api.panel_url(_card()) == "mangalib-page"
    assert api.panel_url(_card()) == "remanga-page"
    assert api.last_language == "ru"
    assert all(source in ("remanga", "mangalib") and lang == "ru"
               for source, lang in calls)


def test_russian_mangafire_is_tried_before_english_mangadex():
    api, calls = _sources({"mangafire": {"ru": "russian-page"},
                           "mangadex": {"en": "english-page"}})
    assert api.panel_url(_card()) == "russian-page"
    assert calls == [("remanga", "ru"), ("mangalib", "ru"),
                     ("mangadex", "ru"), ("mangafire", "ru")]
    assert api.last_language == "ru"


def test_english_then_ukrainian_are_the_only_automatic_fallbacks():
    api, calls = _sources({"mangadex": {"uk": "ukrainian-page", "ja": "jp-page"}})
    assert api.panel_url(_card()) == "ukrainian-page"
    assert ("mangadex", "en") in calls
    assert ("mangadex", "uk") == calls[-1]
    assert all(lang in ("ru", "en", "uk") for _, lang in calls)


def test_rejected_russian_page_uses_another_russian_source_first():
    api, calls = _sources({"remanga": {"ru": "rejected-page"},
                           "mangadex": {"ru": "other-russian-page",
                                        "en": "english-page"}})
    assert api.panel_url(_card()) == "rejected-page"
    assert api.panel_url(_card(), {"rejected-page"}) == "other-russian-page"
    assert all(lang == "ru" for _, lang in calls)


def test_explicit_english_skips_russian_readers_and_restores_client_language():
    api, calls = _sources({"remanga": {"ru": "russian-page"},
                           "mangadex": {"en": "english-page"}}, language="en")
    assert api.panel_url(_card()) == "english-page"
    assert calls == [("mangadex", "en")]
    assert all(client.language == "" for _, client in api.clients)


def test_mangadex_ukrainian_fallback_works_without_an_unfiltered_feed(
        fake_session, fake_response):
    rows = [_row(MAIN, "Tsuredure Children", ["ru", "en", "uk"], mal="58027")]
    feeds = {(MAIN, "uk"): {"data": [_chapter("uk-1", 16)]}}
    session = _session(fake_session, fake_response, rows, feeds)
    api = MangaDexApi(session)
    assert api.panel_url(_card())
    languages = [kw["params"]["translatedLanguage[]"][0]
                 for _, url, kw in session.calls if "/feed" in url]
    assert languages == ["ru", "en", "uk"]
