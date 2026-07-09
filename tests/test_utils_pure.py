# -*- coding: utf-8 -*-
"""Модульные тесты чистых функций utils.py (без сети/subprocess/Qt)."""
import base64
import html as html_mod
import re

import pytest

import utils


# ── clean_ansi ────────────────────────────────────────────────────────────────
class TestCleanAnsi:
    def test_removes_color_codes(self):
        assert utils.clean_ansi("\x1b[31mкрасный\x1b[0m") == "красный"

    def test_plain_text_untouched(self):
        assert utils.clean_ansi("обычный текст 123") == "обычный текст 123"

    def test_empty_string(self):
        assert utils.clean_ansi("") == ""

    def test_only_ansi(self):
        assert utils.clean_ansi("\x1b[1m\x1b[0m") == ""

    def test_cursor_moves(self):
        assert utils.clean_ansi("a\x1b[2Kb") == "ab"


# ── human_size ────────────────────────────────────────────────────────────────
class TestHumanSize:
    @pytest.mark.parametrize("n,expected", [
        (0, "-"),
        (None, "-"),
        ("", "-"),
        (1, "1.0B"),
        (1023, "1023.0B"),
        (1024, "1.0KB"),
        (1024 * 1024, "1.0MB"),
        (1536 * 1024, "1.5MB"),
        (1024 ** 3, "1.0GB"),
        (1024 ** 4, "1.0TB"),
    ])
    def test_values(self, n, expected):
        assert utils.human_size(n) == expected

    def test_string_number(self):
        assert utils.human_size("2048") == "2.0KB"

    def test_invalid_string(self):
        assert utils.human_size("не число") == "-"

    def test_extremely_large_fallback(self):
        # больше TB — срабатывает fallback-ветка после цикла
        out = utils.human_size(1024 ** 5 * 3)
        assert out.endswith("TB")

    def test_negative_number(self):
        # отрицательное число < 1024 → отдаётся с юнитом B
        assert utils.human_size(-5) == "-5.0B"


# ── url_host / host_matches ───────────────────────────────────────────────────
class TestUrlHost:
    def test_basic(self):
        assert utils.url_host("https://www.youtube.com/watch?v=x") == "www.youtube.com"

    def test_no_scheme(self):
        assert utils.url_host("youtube.com/watch") == "youtube.com"

    def test_uppercase_lowered(self):
        assert utils.url_host("https://YouTube.COM/х") == "youtube.com"

    def test_empty(self):
        assert utils.url_host("") == ""

    def test_leading_slashes_stripped(self):
        assert utils.url_host("//youtube.com/v") == "youtube.com"

    def test_garbage(self):
        # мусор без хоста не должен бросать исключение
        assert isinstance(utils.url_host("::::"), str)


class TestHostMatches:
    def test_exact(self):
        assert utils.host_matches("https://youtube.com/w", "youtube.com")

    def test_subdomain(self):
        assert utils.host_matches("https://m.youtube.com/w", "youtube.com")

    def test_spoof_path_rejected(self):
        # CWE-20: домен в пути не должен матчиться
        assert not utils.host_matches("https://evil.com/youtube.com", "youtube.com")

    def test_spoof_suffix_rejected(self):
        assert not utils.host_matches("https://youtube.com.evil.com/", "youtube.com")

    def test_multiple_domains(self):
        assert utils.host_matches("https://youtu.be/x", "youtube.com", "youtu.be")

    def test_empty_url(self):
        assert not utils.host_matches("", "youtube.com")

    def test_domain_with_leading_dot(self):
        assert utils.host_matches("https://a.tiktok.com/", ".tiktok.com")

    def test_case_insensitive_domain(self):
        assert utils.host_matches("https://YOUTUBE.com/", "YouTube.Com")


# ── parse_youtube_start_seconds ───────────────────────────────────────────────
class TestParseYoutubeStart:
    def test_plain_seconds(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=9182") == 9182

    def test_seconds_with_s(self):
        assert utils.parse_youtube_start_seconds(
            "https://www.youtube.com/watch?v=x&t=90s") == 90

    def test_composite_hms(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtu.be/x?t=1h30m5s") == 3600 + 30 * 60 + 5

    def test_composite_ms(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=2m10s") == 130

    def test_start_param(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&start=42") == 42

    def test_not_youtube(self):
        assert utils.parse_youtube_start_seconds("https://vimeo.com/1?t=10") is None

    def test_no_param(self):
        assert utils.parse_youtube_start_seconds("https://youtube.com/watch?v=x") is None

    def test_broken_value(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=abc") is None

    def test_empty_t(self):
        assert utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=") is None


# ── get_cookies_path / _cookie_matches_domain ─────────────────────────────────
class TestCookies:
    def test_tiktok(self):
        assert utils.get_cookies_path("https://www.tiktok.com/@a/video/1") == \
            utils.COOKIE_PATHS["tiktok"]

    def test_instagram(self):
        assert utils.get_cookies_path("https://instagram.com/p/1") == \
            utils.COOKIE_PATHS["instagram"]

    def test_instagram_cdn(self):
        assert utils.get_cookies_path("https://scontent.cdninstagram.com/v.mp4") == \
            utils.COOKIE_PATHS["instagram"]

    def test_youtube(self):
        assert utils.get_cookies_path("https://youtu.be/x") == \
            utils.COOKIE_PATHS["youtube"]

    def test_bilibili(self):
        assert utils.get_cookies_path("https://b23.tv/x") == \
            utils.COOKIE_PATHS["bilibili"]

    def test_default(self):
        assert utils.get_cookies_path("https://example.com/x") == \
            utils.COOKIE_PATHS["default"]

    def test_cookie_mismatch_ig_with_youtube_cookies(self):
        assert not utils._cookie_matches_domain(
            r"C:\cfg\cookies_youtube.txt", "https://instagram.com/p/1")

    def test_cookie_mismatch_tiktok(self):
        assert not utils._cookie_matches_domain(
            "cookies_instagram.txt", "https://tiktok.com/@a")

    def test_cookie_mismatch_yt_with_ig(self):
        assert not utils._cookie_matches_domain(
            "cookies_instagram.txt", "https://youtube.com/watch")

    def test_cookie_match_ok(self):
        assert utils._cookie_matches_domain(
            "cookies_youtube.txt", "https://youtube.com/watch")

    def test_cookie_generic_ok_for_any(self):
        assert utils._cookie_matches_domain("cookies.txt", "https://tiktok.com/@a")


# ── is_direct_cdn_video / clean_url ──────────────────────────────────────────
class TestDirectCdn:
    def test_fbcdn_mp4(self):
        assert utils.is_direct_cdn_video("https://video.fbcdn.net/v/t42/file.mp4?x=1")

    def test_cdninstagram_mov(self):
        assert utils.is_direct_cdn_video("https://x.cdninstagram.com/a.mov")

    def test_wrong_host(self):
        assert not utils.is_direct_cdn_video("https://example.com/a.mp4")

    def test_wrong_ext(self):
        assert not utils.is_direct_cdn_video("https://v.fbcdn.net/page.html")

    def test_empty(self):
        assert not utils.is_direct_cdn_video("")


class TestCleanUrl:
    def test_tiktok_query_stripped(self):
        assert utils.clean_url("https://tiktok.com/@a/video/1?lang=en") == \
            "https://tiktok.com/@a/video/1"

    def test_tiktok_no_query(self):
        assert utils.clean_url("https://tiktok.com/@a/video/1") == \
            "https://tiktok.com/@a/video/1"

    def test_direct_video_query_stripped(self):
        assert utils.clean_url("https://cdn.example.com/v.mp4?token=abc") == \
            "https://cdn.example.com/v.mp4"

    def test_page_url_untouched(self):
        u = "https://example.com/watch?v=123"
        assert utils.clean_url(u) == u

    def test_mkv_stripped(self):
        assert utils.clean_url("https://x.com/f.MKV?sig=1") == "https://x.com/f.MKV"


# ── parse_version ─────────────────────────────────────────────────────────────
class TestParseVersion:
    @pytest.mark.parametrize("s,expected", [
        ("v0.2-beta", (0, 2)),
        ("0.10 BETA", (0, 10)),
        ("", (0,)),
        (None, (0,)),
        ("1.2.3", (1, 2, 3)),
        ("release", (0,)),
        ("v10", (10,)),
    ])
    def test_values(self, s, expected):
        assert utils.parse_version(s) == expected

    def test_comparison_semantics(self):
        assert utils.parse_version("v0.10") > utils.parse_version("v0.9")
        assert utils.parse_version("v1.0") > utils.parse_version("v0.99")


# ── pretty_audio_codec / fmt_bitrate_with_codec / codec_label ────────────────
class TestCodecLabels:
    @pytest.mark.parametrize("name,expected", [
        ("aac", "AAC"), ("opus", "Opus"), ("libopus", "Opus"), ("mp3", "MP3"),
        ("vorbis", "Vorbis"), ("flac", "FLAC"), ("eac3", "E-AC3"),
        ("pcm_s16le", "PCM"), ("truehd", "TrueHD"),
        ("неведомый", "НЕВЕДОМЫЙ"),
        ("", ""), (None, ""),
    ])
    def test_pretty_audio_codec(self, name, expected):
        assert utils.pretty_audio_codec(name) == expected

    def test_whitespace_and_case(self):
        assert utils.pretty_audio_codec("  AaC ") == "AAC"

    def test_fmt_both(self):
        assert utils.fmt_bitrate_with_codec("aac", "153 кбит/с") == "AAC 153 кбит/с"

    def test_fmt_only_bitrate(self):
        assert utils.fmt_bitrate_with_codec(None, "128 кбит/с") == "128 кбит/с"

    def test_fmt_only_codec(self):
        assert utils.fmt_bitrate_with_codec("opus", "-") == "Opus"

    def test_fmt_nothing(self):
        assert utils.fmt_bitrate_with_codec(None, "—") == "—"

    @pytest.mark.parametrize("name,expected", [
        ("h264", "H.264"), ("avc1", "H.264"), ("hevc", "H.265"),
        ("av1", "AV1"), ("vp9", "VP9"), ("mpeg2video", "MPEG-2"),
        ("exotic", "EXOTIC"),
    ])
    def test_codec_label(self, name, expected):
        assert utils.codec_label(name) == expected

    def test_codec_label_none(self):
        assert utils.codec_label(None) is None
        assert utils.codec_label("") is None


# ── kodik: декодер и парсеры HTML ────────────────────────────────────────────
def _kodik_encode(plain: str) -> str:
    """Обратное преобразование к _kodik_decode: base64 + сдвиг букв на 8
    (декодер сдвигает на +18, 18+8=26 → тождество)."""
    b = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    out = []
    for ch in b:
        c = ord(ch)
        if 65 <= c <= 90:
            c += 8
            c = c if c <= 90 else c - 26
            out.append(chr(c))
        elif 97 <= c <= 122:
            c += 8
            c = c if c <= 122 else c - 26
            out.append(chr(c))
        else:
            out.append(ch)
    return "".join(out)


class TestKodikDecode:
    def test_roundtrip(self):
        plain = "//cloud.kodik-storage.com/video/123/abc/720.mp4:hls:manifest.m3u8"
        assert utils._kodik_decode(_kodik_encode(plain)) == plain

    def test_roundtrip_stripped_padding(self):
        plain = "//example.com/a"
        enc = _kodik_encode(plain).rstrip("=")
        assert utils._kodik_decode(enc) == plain

    def test_non_letters_preserved(self):
        plain = "1234//::"
        assert utils._kodik_decode(_kodik_encode(plain)) == plain


class TestIsEmbedCandidate:
    def test_unknown_site(self):
        assert utils.is_embed_candidate("https://animego.online/anime/1")

    def test_known_direct(self):
        assert not utils.is_embed_candidate("https://www.youtube.com/watch?v=1")

    def test_not_http(self):
        assert not utils.is_embed_candidate("ftp://x.com/1")
        assert not utils.is_embed_candidate("")
        assert not utils.is_embed_candidate(None)


class TestAttr:
    def test_found(self):
        assert utils._attr('a data-id="42" b', "data-id") == "42"

    def test_missing(self):
        assert utils._attr("no attrs here", "data-id") == ""

    def test_empty_value(self):
        assert utils._attr('data-id=""', "data-id") == ""


KODIK_SERIAL_HTML = """
<select name="translation">
  <option data-media-id="911" data-media-hash="h1" data-title="AniLibria"
          data-media-type="serial" selected>AniLibria</option>
  <option data-media-id="912" data-media-hash="h2" data-title="AniDub">AniDub</option>
</select>
<select name="season"><option data-serial-id="5">1 сезон</option></select>
<select name="episode">
  <option value="1" data-id="e1" data-hash="eh1" data-title="1 серия">1</option>
  <option value="2" data-id="e2" data-hash="eh2" data-title="2 серия" selected>2</option>
</select>
"""


class TestParseKodikSelects:
    def test_translations_and_episodes(self):
        tr, eps = utils._parse_kodik_selects(KODIK_SERIAL_HTML)
        assert tr == [("911", "h1", "AniLibria", "serial"),
                      ("912", "h2", "AniDub", "serial")]
        assert eps == [("1", "e1", "eh1", "1 серия"), ("2", "e2", "eh2", "2 серия")]

    def test_media_type_default_serial(self):
        html = ('<select><option data-media-id="1" data-media-hash="h" '
                'data-title="X"></option></select>')
        tr, _ = utils._parse_kodik_selects(html)
        assert tr[0][3] == "serial"

    def test_empty_html(self):
        assert utils._parse_kodik_selects("") == ([], [])

    def test_season_block_skipped(self):
        html = '<select><option data-serial-id="1" data-id="x" data-hash="y"></option></select>'
        tr, eps = utils._parse_kodik_selects(html)
        assert tr == [] and eps == []

    def test_selected_option(self):
        sel_tr = utils._selected_option(KODIK_SERIAL_HTML, "translation")
        assert 'data-media-id="911"' in sel_tr
        sel_ep = utils._selected_option(KODIK_SERIAL_HTML, "episode")
        assert 'value="2"' in sel_ep

    def test_selected_option_none(self):
        assert utils._selected_option("<select><option a=1></option></select>",
                                      "translation") == ""


# ── animego helpers ──────────────────────────────────────────────────────────
class TestAnimego:
    def test_is_animego(self):
        assert utils._is_animego("https://animego.me/anime/naruto-102")
        assert utils._is_animego("https://ANIMEGO.online/x")
        assert utils.is_animego_site("https://animego.one/y")
        assert not utils._is_animego("https://example.com/animeg")
        assert not utils._is_animego("")
        assert not utils._is_animego(None)

    def test_animego_base(self):
        assert utils._animego_base("https://animego.me/anime/x-1?q=2") == \
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
        eps, players = utils._animego_parse(content)
        assert eps == {1: "111", 2: "222"}
        assert len(players) == 2
        assert players[0] == ("Kodik", "AniLibria", "//kodik.info/seria/1/h/720p&x=1")

    def test_animego_parse_empty(self):
        eps, players = utils._animego_parse("")
        assert eps == {} and players == []

    def test_kodik_players_filter(self):
        players = [("Kodik", "A", "//kodik.info/x"),
                   ("AniBoom", "B", "//aniboom.one/y"),
                   ("Other", "C", "//cloud.kodikplayer.net/z")]
        kod = utils._animego_kodik_players(players)
        assert [p[0] for p in kod] == ["Kodik", "Other"]

    def test_animego_anime_id_from_slug(self, fake_session):
        s = fake_session(routes=[("animego", type("R", (), {"text": ""})())])
        # страница не отдала data-ajax-url → id берётся из слага "-102"
        class Resp:
            text = "<html></html>"
        s2 = fake_session(routes=[("animego", Resp())])
        assert utils._animego_anime_id("https://animego.me/anime/naruto-102", s2) == "102"

    def test_animego_anime_id_from_page(self, fake_session):
        class Resp:
            text = '<a data-ajax-url="/player/555">плеер</a>'
        s = fake_session(routes=[("animego", Resp())])
        assert utils._animego_anime_id("https://animego.me/anime/naruto-102", s) == "555"

    def test_animego_anime_id_nothing(self, fake_session):
        class Resp:
            text = "<html></html>"
        s = fake_session(routes=[("animego", Resp())])
        assert utils._animego_anime_id("https://animego.me/anime/slug", s) == ""


# ── mask_html_js ─────────────────────────────────────────────────────────────
def _decode_data_si(masked: str):
    """Достаёт и раскодирует payload data-si из замаскированного HTML."""
    m = re.search(r'data-si="([^"]*)"', masked)
    assert m, "data-si не найден"
    payload = html_mod.unescape(m.group(1))
    items = payload.split("|")
    out = []
    for it in items:
        kind, val = it[0], it[2:]
        if kind in ("m", "b"):
            val = re.sub(r"[^A-Za-z0-9+/=]", "", val)
            out.append((kind, base64.b64decode(val).decode("utf-8")))
        else:
            out.append((kind, val))
    return out


class TestMaskHtmlJs:
    HTML = """<html><head><title>t</title></head>
<body class="game">
<div id="app" onclick="go()">содержимое</div>
<script src="https://cdn.example.com/lib.js"></script>
<script>var x = 1; function go() { alert('привет'); }</script>
</body></html>"""

    def test_counts(self):
        masked, n_inline, n_external = utils.mask_html_js(self.HTML)
        assert n_inline == 1
        assert n_external == 1

    def test_no_script_tags_remain(self):
        masked, *_ = utils.mask_html_js(self.HTML)
        assert "<script" not in masked.lower()
        assert "function" not in masked.replace("'Fun'+'ction'", "")

    def test_payload_roundtrip(self):
        masked, *_ = utils.mask_html_js(self.HTML)
        items = _decode_data_si(masked)
        kinds = [k for k, _ in items]
        assert kinds == ["m", "s", "b"]
        # тело сохранилось (включая кириллицу и инлайн-обработчик)
        assert "содержимое" in items[0][1]
        assert 'onclick="go()"' in items[0][1]
        assert items[1][1] == "https://cdn.example.com/lib.js"
        assert "alert('привет')" in items[2][1]

    def test_no_active_content(self):
        masked, n_i, n_e = utils.mask_html_js("<html><body><p>text</p></body></html>")
        assert n_i == 0 and n_e == 0
        # тело всё равно уезжает в data-si (m:)
        items = _decode_data_si(masked)
        assert items[0][0] == "m"

    def test_fully_empty_returns_original(self):
        html = "<html><head></head></html>"  # нет body и скриптов
        masked, n_i, n_e = utils.mask_html_js(html)
        assert (masked, n_i, n_e) == (html, 0, 0)

    def test_closing_tag_with_junk(self):
        # </script > с мусором должен матчиться (CodeQL py/bad-tag-filter)
        html = '<body><script>evil()</script foo="bar"><p>x</p></body>'
        masked, n_i, _ = utils.mask_html_js(html)
        assert n_i == 1
        assert "evil()" not in masked

    def test_base64_chunks_short(self):
        # непрерывные прогоны base64 не длиннее _B64_CHUNK (VK режет длинные)
        big = "<body><script>%s</script></body>" % ("var s='х'*1;" * 500)
        masked, *_ = utils.mask_html_js(big)
        m = re.search(r'data-si="([^"]*)"', masked)
        payload = m.group(1)
        for run in re.findall(r"[A-Za-z0-9+/=]+", payload):
            assert len(run) <= utils._B64_CHUNK

    def test_onload_has_launcher(self):
        masked, *_ = utils.mask_html_js(self.HTML)
        assert "'Fun'+'ction'" in masked
        assert "window[launch]" in masked

    def test_no_body_but_script(self):
        html = "<div><script>a()</script></div>"
        masked, n_i, _ = utils.mask_html_js(html)
        assert n_i == 1
        assert "data-si=" in masked


# ── default_download_dir ─────────────────────────────────────────────────────
class TestDefaultDownloadDir:
    def test_returns_existing_dir(self):
        d = utils.default_download_dir()
        import os
        assert os.path.isdir(d)

    def test_fallback_home(self, monkeypatch):
        import os
        monkeypatch.setattr(utils.os.path, "isdir", lambda p: False)
        d = utils.default_download_dir()
        assert d == os.path.expanduser("~")
