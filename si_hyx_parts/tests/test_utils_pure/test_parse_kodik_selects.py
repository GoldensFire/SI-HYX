# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestParseKodikSelects. Public namespace: test_utils_pure."""
import test_utils_pure as _api


class TestParseKodikSelects:
    def test_translations_and_episodes(self):
        tr, eps = _api.utils._parse_kodik_selects(_api.KODIK_SERIAL_HTML)
        assert tr == [("911", "h1", "AniLibria", "serial"),
                      ("912", "h2", "AniDub", "serial")]
        assert eps == [("1", "e1", "eh1", "1 серия"), ("2", "e2", "eh2", "2 серия")]

    def test_media_type_default_serial(self):
        html = ('<select><option data-media-id="1" data-media-hash="h" '
                'data-title="X"></option></select>')
        tr, _ = _api.utils._parse_kodik_selects(html)
        assert tr[0][3] == "serial"

    def test_empty_html(self):
        assert _api.utils._parse_kodik_selects("") == ([], [])

    def test_season_block_skipped(self):
        html = '<select><option data-serial-id="1" data-id="x" data-hash="y"></option></select>'
        tr, eps = _api.utils._parse_kodik_selects(html)
        assert tr == [] and eps == []

    def test_selected_option(self):
        sel_tr = _api.utils._selected_option(_api.KODIK_SERIAL_HTML, "translation")
        assert 'data-media-id="911"' in sel_tr
        sel_ep = _api.utils._selected_option(_api.KODIK_SERIAL_HTML, "episode")
        assert 'value="2"' in sel_ep

    def test_selected_option_none(self):
        assert _api.utils._selected_option("<select><option a=1></option></select>",
                                      "translation") == ""

TestParseKodikSelects.__module__ = _api.__name__
_api.TestParseKodikSelects = TestParseKodikSelects

# ── animego helpers ──────────────────────────────────────────────────────────
class TestAnimego:
    def test_is_animego(self):
        assert _api.utils._is_animego("https://animego.me/anime/naruto-102")
        assert _api.utils._is_animego("https://ANIMEGO.online/x")
        assert _api.utils.is_animego_site("https://animego.one/y")
        assert not _api.utils._is_animego("https://example.com/animeg")
        assert not _api.utils._is_animego("")
        assert not _api.utils._is_animego(None)

    def test_animego_base(self):
        assert _api.utils._animego_base("https://animego.me/anime/x-1?q=2") == \
            "https://animego.me"

    def test_animego_parse(self):
        content = '''
        <div data-episode-number="1" foo><span data-episode="111"></span></div>
        <div data-episode-number="2"><span data-episode="222"></span></div>
        <button data-player="//kodik.info/seria/1/h/720p&amp;x=1"
                data-provider-title="Kodik" data-translation-title="AniLibria"></button>
        <button data-player="//aniboom.one/embed/2"
                data-provider-title="AniBoom" data-translation-title="Дубляж"></button>
        '''
        eps, players = _api.utils._animego_parse(content)
        assert eps == {1: "111", 2: "222"}
        assert len(players) == 2
        assert players[0] == ("Kodik", "AniLibria", "//kodik.info/seria/1/h/720p&x=1")

    def test_animego_parse_empty(self):
        eps, players = _api.utils._animego_parse("")
        assert eps == {} and players == []

    def test_kodik_players_filter(self):
        players = [("Kodik", "A", "//kodik.info/x"),
                   ("AniBoom", "B", "//aniboom.one/y"),
                   ("Other", "C", "//cloud.kodikplayer.net/z")]
        kod = _api.utils._animego_kodik_players(players)
        assert [p[0] for p in kod] == ["Kodik", "Other"]

    def test_animego_anime_id_from_slug(self, fake_session):
        # страница не отдала data-ajax-url → id берётся из слага "-102"
        class Resp:
            text = "<html></html>"
        s2 = fake_session(routes=[("animego", Resp())])
        assert _api.utils._animego_anime_id("https://animego.me/anime/naruto-102", s2) == "102"

    def test_animego_anime_id_from_page(self, fake_session):
        class Resp:
            text = '<a data-ajax-url="/player/555">плеер</a>'
        s = fake_session(routes=[("animego", Resp())])
        assert _api.utils._animego_anime_id("https://animego.me/anime/naruto-102", s) == "555"

    def test_animego_anime_id_nothing(self, fake_session):
        class Resp:
            text = "<html></html>"
        s = fake_session(routes=[("animego", Resp())])
        assert _api.utils._animego_anime_id("https://animego.me/anime/slug", s) == ""

TestAnimego.__module__ = _api.__name__
_api.TestAnimego = TestAnimego

# ── mask_html_js ─────────────────────────────────────────────────────────────
def _decode_data_si(masked: str):
    """Достаёт и раскодирует payload data-si из замаскированного HTML."""
    m = _api.re.search(r'data-si="([^"]*)"', masked)
    assert m, "data-si не найден"
    payload = _api.html_mod.unescape(m.group(1))
    items = payload.split("|")
    out = []
    for it in items:
        kind, val = it[0], it[2:]
        if kind in ("m", "b"):
            val = _api.re.sub(r"[^A-Za-z0-9+/=]", "", val)
            out.append((kind, _api.base64.b64decode(val).decode("utf-8")))
        else:
            out.append((kind, val))
    return out

_decode_data_si.__module__ = _api.__name__
_api._decode_data_si = _decode_data_si

class TestMaskHtmlJs:
    HTML = """<html><head><title>t</title></head>
<body class="game">
<div id="app" onclick="go()">содержимое</div>
<script src="https://cdn.example.com/lib.js"></script>
<script>var x = 1; function go() { alert('привет'); }</script>
</body></html>"""

    def test_counts(self):
        masked, n_inline, n_external = _api.utils.mask_html_js(self.HTML)
        assert n_inline == 1
        assert n_external == 1

    def test_no_script_tags_remain(self):
        masked, *_ = _api.utils.mask_html_js(self.HTML)
        assert "<script" not in masked.lower()
        assert "function" not in masked.replace("'Fun'+'ction'", "")

    def test_payload_roundtrip(self):
        masked, *_ = _api.utils.mask_html_js(self.HTML)
        items = _api._decode_data_si(masked)
        kinds = [k for k, _ in items]
        assert kinds == ["m", "s", "b"]
        # тело сохранилось (включая кириллицу и инлайн-обработчик)
        assert "содержимое" in items[0][1]
        assert 'onclick="go()"' in items[0][1]
        assert items[1][1] == "https://cdn.example.com/lib.js"
        assert "alert('привет')" in items[2][1]

    def test_no_active_content(self):
        masked, n_i, n_e = _api.utils.mask_html_js("<html><body><p>text</p></body></html>")
        assert n_i == 0 and n_e == 0
        # тело всё равно уезжает в data-si (m:)
        items = _api._decode_data_si(masked)
        assert items[0][0] == "m"

    def test_fully_empty_returns_original(self):
        html = "<html><head></head></html>"  # нет body и скриптов
        masked, n_i, n_e = _api.utils.mask_html_js(html)
        assert (masked, n_i, n_e) == (html, 0, 0)

    def test_closing_tag_with_junk(self):
        # </script > с мусором должен матчиться (CodeQL py/bad-tag-filter)
        html = '<body><script>evil()</script foo="bar"><p>x</p></body>'
        masked, n_i, _ = _api.utils.mask_html_js(html)
        assert n_i == 1
        assert "evil()" not in masked

    def test_base64_chunks_short(self):
        # непрерывные прогоны base64 не длиннее _B64_CHUNK (VK режет длинные)
        big = "<body><script>%s</script></body>" % ("var s='х'*1;" * 500)
        masked, *_ = _api.utils.mask_html_js(big)
        m = _api.re.search(r'data-si="([^"]*)"', masked)
        payload = m.group(1)
        for run in _api.re.findall(r"[A-Za-z0-9+/=]+", payload):
            assert len(run) <= _api.utils._B64_CHUNK

    def test_onload_has_launcher(self):
        masked, *_ = _api.utils.mask_html_js(self.HTML)
        assert "'Fun'+'ction'" in masked
        assert "window[launch]" in masked

    def test_no_body_but_script(self):
        html = "<div><script>a()</script></div>"
        masked, n_i, _ = _api.utils.mask_html_js(html)
        assert n_i == 1
        assert "data-si=" in masked

TestMaskHtmlJs.__module__ = _api.__name__
_api.TestMaskHtmlJs = TestMaskHtmlJs

# ── mask_html_js_lite (доп-режим) ────────────────────────────────────────────
# lite = envelope старого метода (в открытом HTML НЕТ <script>/eval/function —
# всё в data-si, запуск через onload+'Fun'+'ction'), но крупные ассеты кодируются
# один раз (отдельными 'r'-элементами). Хелперы разбирают payload из data-si.
def _lite_items(masked: str):
    """Список элементов payload из data-si (после HTML-деэкранирования)."""
    m = _api.re.search(r'data-si="([^"]*)"', masked)
    assert m, "data-si не найден"
    payload = (m.group(1).replace("&amp;", "&").replace("&quot;", '"')
               .replace("&lt;", "<").replace("&gt;", ">"))
    return payload.split("|")

_lite_items.__module__ = _api.__name__
_api._lite_items = _lite_items

def _lite_scripts(masked: str) -> str:
    """Склеенный декодированный код всех 'b'-элементов (спрятанные скрипты)."""
    parts = []
    for it in _api._lite_items(masked):
        if it.startswith("b:"):
            b64 = _api.re.sub(r'[^A-Za-z0-9+/=]', '', it[2:])
            parts.append(_api.base64.b64decode(b64).decode("utf-8"))
    return "\n".join(parts)

_lite_scripts.__module__ = _api.__name__
_api._lite_scripts = _lite_scripts

def _lite_raw_assets(masked: str) -> dict:
    """{idx: исходное значение} для всех 'r'-элементов (сырые ассеты, БЕЗ base64)."""
    out = {}
    for it in _api._lite_items(masked):
        if it.startswith("r:"):
            body = it[2:]
            p = body.index(":")
            out[int(body[:p])] = _api.re.sub(r'\s', '', body[p + 1:])
    return out

_lite_raw_assets.__module__ = _api.__name__
_api._lite_raw_assets = _lite_raw_assets

def _no_executable_literals(masked: str) -> bool:
    """В открытом HTML нет ни <script>, ни eval, ни function/Function/=> —
    ровно тот профиль, что проходит VK (как у старого метода). data-si (base64)
    и onload ('Fun'+'ction') не в счёт: их содержимое VK не читает."""
    # убираем значение data-si и onload — там всё в base64/склейке, VK не видит
    stripped = _api.re.sub(r'data-si="[^"]*"', '', masked)
    stripped = _api.re.sub(r'onload="[^"]*"', '', stripped)
    return not _api.re.search(r'<script|\beval\b|\bfunction\b|Function|=>', stripped)

_no_executable_literals.__module__ = _api.__name__
_api._no_executable_literals = _no_executable_literals
