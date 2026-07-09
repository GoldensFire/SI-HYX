# -*- coding: utf-8 -*-
"""Тесты сетевых функций utils.py (Kodik/animego) на фейковых сессиях."""
import base64

import pytest

import utils
from conftest import FakeResponse, FakeSession


def _enc(plain: str) -> str:
    """Кодирование под _kodik_decode (сдвиг букв на 8 + base64)."""
    b = base64.b64encode(plain.encode()).decode()
    out = []
    for ch in b:
        c = ord(ch)
        if 65 <= c <= 90:
            c += 8
            c = c if c <= 90 else c - 26
        elif 97 <= c <= 122:
            c += 8
            c = c if c <= 122 else c - 26
        out.append(chr(c))
    return "".join(out)


# ── _find_kodik_iframe ───────────────────────────────────────────────────────
class TestFindKodikIframe:
    def test_direct_iframe(self):
        html = '<iframe src="//kodik.info/seria/1000/hash123/720p?x=1"></iframe>'
        s = FakeSession(routes=[("page", FakeResponse(text=html))])
        url = utils._find_kodik_iframe("https://site.ru/page", s)
        assert url == "https://kodik.info/seria/1000/hash123/720p?x=1"

    def test_amp_entities_unescaped(self):
        html = '<a href="https://aniqit.com/serial/5/h/720p?a=1&amp;b=2">x</a>'
        s = FakeSession(routes=[("page", FakeResponse(text=html))])
        url = utils._find_kodik_iframe("https://site.ru/page", s)
        assert "a=1&b=2" in url

    def test_dle_controller(self):
        page_html = '<div data-params="mod=kodik-player&amp;news_id=7&amp;id=7"></div>'
        ctl_resp = FakeResponse(json_data={"data": "//kodik.info/video/9/hh/720p"})
        s = FakeSession(routes=[
            ("controller.php", ctl_resp),
            ("site.ru", FakeResponse(text=page_html)),
        ])
        url = utils._find_kodik_iframe("https://site.ru/anime/7", s)
        assert url == "https://kodik.info/video/9/hh/720p"

    def test_nothing_found(self):
        s = FakeSession(routes=[("site", FakeResponse(text="<html>пусто</html>"))])
        assert utils._find_kodik_iframe("https://site.ru/x", s) == ""

    def test_network_error(self):
        class BoomSession:
            def get(self, *a, **k):
                raise OSError("сеть")
        assert utils._find_kodik_iframe("https://site.ru/x", BoomSession()) == ""


# ── kodik_get_info ───────────────────────────────────────────────────────────
IFRAME_HTML = """
<select><option data-media-id="10" data-media-hash="mh" data-title="Дубляж"
    data-media-type="serial" selected></option></select>
<select>
  <option value="1" data-id="d1" data-hash="h1" data-title="1 серия"></option>
  <option value="2" data-id="d2" data-hash="h2" data-title="2 серия" selected></option>
</select>
"""


class TestKodikGetInfo:
    def _session(self, iframe_html=IFRAME_HTML):
        page = '<iframe src="//kodik.info/serial/10/mh/720p"></iframe>'
        return FakeSession(routes=[
            ("kodik.info", FakeResponse(text=iframe_html)),
            ("site.ru", FakeResponse(text=page)),
        ])

    def test_info(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        info = utils.kodik_get_info("https://site.ru/anime/1")
        assert info == {"translations": ["Дубляж"], "episodes": 2,
                        "cur_translation": "Дубляж", "cur_episode": 2}

    def test_no_iframe(self, monkeypatch):
        s = FakeSession(routes=[("site.ru", FakeResponse(text="<html></html>"))])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.kodik_get_info("https://site.ru/anime/1") == {}

    def test_proxy_applied(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        utils.kodik_get_info("https://site.ru/anime/1", proxy="http://127.0.0.1:1")
        assert s.proxies == {"http": "http://127.0.0.1:1",
                             "https": "http://127.0.0.1:1"}


# ── resolve_kodik: полный путь до m3u8 ───────────────────────────────────────
def _iframe_full_html(direct=False):
    src360 = "//cdn.example/360.m3u8" if direct else _enc("//cdn.example/360.m3u8")
    src720 = "//cdn.example/720.m3u8" if direct else _enc("//cdn.example/720.m3u8")
    return """
<select><option data-media-id="10" data-media-hash="mh" data-title="Дубляж"
   data-media-type="serial" selected></option></select>
<select>
  <option value="1" data-id="d1" data-hash="h1" data-title="1 серия" selected></option>
  <option value="2" data-id="d2" data-hash="h2" data-title="2 серия"></option>
</select>
<script>
var urlParams = '{"d":"site.ru","d_sign":"ds","pd":"kodik.info","pd_sign":"pds",
"ref":"https%3A%2F%2Fsite.ru%2F","ref_sign":"rs"}';
videoInfo.type = 'seria'; videoInfo.hash = 'vh'; videoInfo.id = '77';
</script>
""", src360, src720


class TestResolveKodik:
    def _make_session(self, links=None):
        html, s360, s720 = _iframe_full_html()
        page = '<iframe src="//kodik.info/seria/77/vh/720p"></iframe>'
        if links is None:
            links = {"360": [{"src": s360}], "720": [{"src": s720}]}
        ftor = FakeResponse(json_data={"links": links})
        posts = []

        def ftor_handler(url, **kw):
            posts.append(kw)
            return ftor
        s = FakeSession(routes=[
            ("/ftor", ftor_handler),
            ("kodik.info", FakeResponse(text=html)),
            ("site.ru", FakeResponse(text=page)),
        ])
        s._posts = posts
        return s

    def test_resolves_best_fitting(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        res = utils.resolve_kodik("https://site.ru/anime/1", want_height=720)
        assert res["url"] == "https://cdn.example/720.m3u8"
        assert res["height"] == 720
        assert res["referer"] == "https://kodik.info/"

    def test_want_lower_height(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        res = utils.resolve_kodik("https://site.ru/anime/1", want_height=480)
        assert res["height"] == 360

    def test_want_below_min_takes_min_available(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        res = utils.resolve_kodik("https://site.ru/anime/1", want_height=144)
        # ничего не влезает под 144 → берётся max из доступных
        assert res["height"] == 720

    def test_direct_links_passthrough(self, monkeypatch):
        # если src уже содержит '//' — декодирование не применяется
        links = {"480": [{"src": "//direct.example/480.m3u8"}]}
        s = self._make_session(links=links)
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        res = utils.resolve_kodik("https://site.ru/anime/1")
        assert res["url"] == "https://direct.example/480.m3u8"

    def test_ref_unquoted_in_post(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        utils.resolve_kodik("https://site.ru/anime/1")
        post_data = s._posts[0]["data"]
        # ref обязан быть РАСкодированным, иначе подпись не сойдётся (ftor 500)
        assert post_data["ref"] == "https://site.ru/"
        assert post_data["type"] == "seria"
        assert post_data["hash"] == "vh"
        assert post_data["id"] == "77"

    def test_no_iframe_returns_empty(self, monkeypatch):
        s = FakeSession(routes=[("site.ru", FakeResponse(text="<p>нет</p>"))])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.resolve_kodik("https://site.ru/anime/1") == {}

    def test_no_links_returns_empty(self, monkeypatch):
        s = self._make_session(links={})
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.resolve_kodik("https://site.ru/anime/1") == {}

    def test_episode_selection(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        logs = []
        utils.resolve_kodik("https://site.ru/anime/1", episode=2, log_fn=logs.append)
        post_data = s._posts[0]["data"]
        assert post_data["id"] == "d2" and post_data["hash"] == "h2"
        assert any("серия 2" in l for l in logs)

    def test_episode_not_found_keeps_default(self, monkeypatch):
        s = self._make_session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        logs = []
        utils.resolve_kodik("https://site.ru/anime/1", episode=99, log_fn=logs.append)
        assert s._posts[0]["data"]["id"] == "77"
        assert any("не найдена" in l for l in logs)

    def test_ftor_failure_returns_empty(self, monkeypatch):
        html, *_ = _iframe_full_html()
        page = '<iframe src="//kodik.info/seria/77/vh/720p"></iframe>'

        def boom(url, **kw):
            raise OSError("сбой")
        s = FakeSession(routes=[
            ("/ftor", boom),
            ("kodik.info", FakeResponse(text=html)),
            ("site.ru", FakeResponse(text=page)),
        ])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.resolve_kodik("https://site.ru/anime/1") == {}

    def test_missing_video_params(self, monkeypatch):
        page = '<iframe src="//kodik.info/seria/77/vh/720p"></iframe>'
        s = FakeSession(routes=[
            ("kodik.info", FakeResponse(text="<html>без vInfo</html>")),
            ("site.ru", FakeResponse(text=page)),
        ])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        logs = []
        assert utils.resolve_kodik("https://site.ru/anime/1", log_fn=logs.append) == {}
        assert any("не найдены параметры" in l for l in logs)


# ── animego AJAX-плеер ───────────────────────────────────────────────────────
ANIMEGO_CONTENT = """
<div data-episode-number="1"><span data-episode="501"></span></div>
<div data-episode-number="2"><span data-episode="502"></span></div>
<button data-player="//kodik.info/seria/1/aa/720p" data-provider-title="Kodik"
        data-translation-title="AniLibria"></button>
<button data-player="//aniboom.one/embed/9" data-provider-title="AniBoom"
        data-translation-title="Студия"></button>
"""


class TestAnimegoInfo:
    def _session(self, content=ANIMEGO_CONTENT):
        page = '<a data-ajax-url="/player/321">x</a>'
        return FakeSession(routes=[
            ("/player/", FakeResponse(json_data={"data": {"content": content}})),
            ("animego.me", FakeResponse(text=page)),
        ])

    def test_info(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        info = utils.animego_get_info("https://animego.me/anime/naruto-321")
        assert info["translations"] == ["AniLibria"]
        assert info["episodes"] == 2
        assert info["cur_translation"] == "AniLibria"
        assert info["cur_episode"] == 1

    def test_no_id(self, monkeypatch):
        s = FakeSession(routes=[("animego.me", FakeResponse(text="<html></html>"))])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.animego_get_info("https://animego.me/anime/slug") == {}

    def test_no_content(self, monkeypatch):
        page = '<a data-ajax-url="/player/321">x</a>'
        s = FakeSession(routes=[
            ("/player/", FakeResponse(json_data={"data": {}})),
            ("animego.me", FakeResponse(text=page)),
        ])
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        assert utils.animego_get_info("https://animego.me/anime/naruto-321") == {}

    def test_resolve_kodik_url_translation_match(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        url = utils._animego_resolve_kodik_url(
            "https://animego.me/anime/naruto-321", translation="anilibria")
        assert url == "https://kodik.info/seria/1/aa/720p"

    def test_resolve_kodik_url_no_kodik(self, monkeypatch):
        content = ('<button data-player="//aniboom.one/e/1" '
                   'data-provider-title="AniBoom" data-translation-title="X"></button>')
        s = self._session(content=content)
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        logs = []
        url = utils._animego_resolve_kodik_url(
            "https://animego.me/anime/naruto-321", log_fn=logs.append)
        assert url == ""
        assert any("нет Kodik" in l for l in logs)

    def test_resolve_unknown_translation_falls_back(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(utils.requests, "Session", lambda: s)
        logs = []
        url = utils._animego_resolve_kodik_url(
            "https://animego.me/anime/naruto-321", translation="Несуществующая",
            log_fn=logs.append)
        assert url == "https://kodik.info/seria/1/aa/720p"
        assert any("не найдена" in l for l in logs)


# ── http_get / _Resp (config) ────────────────────────────────────────────────
class TestHttpGet:
    def test_ok(self, monkeypatch):
        import config
        r = FakeResponse(text="привет", headers={"Content-Length": "6"})
        monkeypatch.setattr(config.requests, "get", lambda *a, **k: r)
        resp = config.http_get("https://x.example/")
        assert resp.status == 200
        assert resp.read() == "привет".encode("utf-8")
        assert resp.headers.get("Content-Length") == "6"

    def test_read_chunks(self, monkeypatch):
        import config
        r = FakeResponse(content=b"abcdefgh")
        monkeypatch.setattr(config.requests, "get", lambda *a, **k: r)
        resp = config.http_get("https://x.example/")
        assert resp.read(4) == b"abcd"
        assert resp.read(4) == b"efgh"
        assert resp.read(4) == b""

    def test_context_manager(self, monkeypatch):
        import config
        r = FakeResponse(content=b"z")
        monkeypatch.setattr(config.requests, "get", lambda *a, **k: r)
        with config.http_get("https://x.example/") as resp:
            assert resp.read() == b"z"

    def test_ssl_fallback_insecure(self, monkeypatch):
        import config
        import requests as req
        calls = []

        def fake_get(url, **kw):
            calls.append(kw)
            if "verify" not in kw:
                raise req.exceptions.SSLError("bad cert")
            return FakeResponse(content=b"ok")
        monkeypatch.setattr(config.requests, "get", fake_get)
        resp = config.http_get("https://x.example/")
        assert resp.read() == b"ok"
        assert calls[1].get("verify") is False

    def test_ssl_no_fallback_when_secure_required(self, monkeypatch):
        import config
        import requests as req

        def fake_get(url, **kw):
            raise req.exceptions.SSLError("bad cert")
        monkeypatch.setattr(config.requests, "get", fake_get)
        with pytest.raises(req.exceptions.SSLError):
            config.http_get("https://upd.example/app.exe", allow_insecure=False)

    def test_http_error_raises(self, monkeypatch):
        import config
        monkeypatch.setattr(config.requests, "get",
                            lambda *a, **k: FakeResponse(status_code=404))
        import requests as req
        with pytest.raises(req.HTTPError):
            config.http_get("https://x.example/missing")
