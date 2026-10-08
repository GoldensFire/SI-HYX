"""Refused CDN pages and retry-heavy API sessions must stay bounded."""
import random
from types import SimpleNamespace

import pytest
import requests
from requests.adapters import HTTPAdapter

from network_attempt import single_attempt_session
from animepack_api import MangaFireApi
from si_hyx_parts.animepack_api import manga_image_download as images


def test_download_session_keeps_identity_without_implicit_retries():
    with requests.Session() as source:
        source.mount("https://", HTTPAdapter(max_retries=4))
        source.headers["Authorization"] = "test-token"
        source.cookies.set("sid", "old", domain="reader.test")
        with single_attempt_session(source) as client:
            assert client is not source
            assert client.headers["Authorization"] == "test-token"
            assert client.cookies.get("sid") == "old"
            assert client.get_adapter("https://reader.test").max_retries.total == 0
            client.cookies.set("sid", "renewed", domain="reader.test")
        assert source.cookies.get("sid") == "renewed"
        assert source.get_adapter("https://reader.test").max_retries.total == 4


@pytest.mark.parametrize("oversized", [False, True])
def test_image_deadline_and_actual_size_close_stream(monkeypatch, oversized):
    closed, now = [], [0]
    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 8)
    class Response:
        headers = {}
        def raise_for_status(self):
            pass
        def iter_content(self, size):
            yield b"12345"
            now[0] = 1 if oversized else 21
            yield b"67890"
            raise AssertionError("Must stop stream here")
        def close(self):
            closed.append(1)
    session = SimpleNamespace(get=lambda *a, **k: Response())
    with pytest.raises(ValueError if oversized else requests.Timeout):
        images.download(session, "https://reader.test/page", "https://reader.test/", clock=lambda: now[0])
    assert closed == [1]


def test_two_403_pages_skip_only_that_host_and_title(monkeypatch):
    reader = MangaFireApi(SimpleNamespace(), rng=random.Random(1))
    reader.label, reader.base_url = "Reader", "https://reader.test"
    title = {"id": "title", "titles": ["Title"]}
    reader.manga = lambda card: title
    reader._chapters["title", ""] = [{"id": "ch", "link": "https://reader.test/ch"}]
    reader._pages["ch"] = [{"url": f"https://cdn.test/{i}.jpg"} for i in range(15)]
    def forbidden(*args):
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError("HTTP 403", response=response)
    monkeypatch.setattr(images, "download", forbidden)
    for _ in range(2):
        url = reader.panel_url({})
        assert url
        with pytest.raises(Exception, match="403"):
            reader.download_page(url, reader.last_page_info)
    assert reader.panel_url({}) == ""
    title["id"] = "other-title"
    reader._chapters["other-title", ""] = reader._chapters["title", ""]
    assert reader.panel_url({})
