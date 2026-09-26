# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestCleanAnsi. Public namespace: test_utils_pure."""
import test_utils_pure as _api


# ── clean_ansi ────────────────────────────────────────────────────────────────
class TestCleanAnsi:
    def test_removes_color_codes(self):
        assert _api.utils.clean_ansi("\x1b[31mкрасный\x1b[0m") == "красный"

    def test_plain_text_untouched(self):
        assert _api.utils.clean_ansi("обычный текст 123") == "обычный текст 123"

    def test_empty_string(self):
        assert _api.utils.clean_ansi("") == ""

    def test_only_ansi(self):
        assert _api.utils.clean_ansi("\x1b[1m\x1b[0m") == ""

    def test_cursor_moves(self):
        assert _api.utils.clean_ansi("a\x1b[2Kb") == "ab"

TestCleanAnsi.__module__ = _api.__name__
_api.TestCleanAnsi = TestCleanAnsi

# ── human_size ────────────────────────────────────────────────────────────────
class TestHumanSize:
    @_api.pytest.mark.parametrize("n,expected", [
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
        assert _api.utils.human_size(n) == expected

    def test_string_number(self):
        assert _api.utils.human_size("2048") == "2.0KB"

    def test_invalid_string(self):
        assert _api.utils.human_size("не число") == "-"

    def test_extremely_large_fallback(self):
        # больше TB — срабатывает fallback-ветка после цикла
        out = _api.utils.human_size(1024 ** 5 * 3)
        assert out.endswith("TB")

    def test_negative_number(self):
        # отрицательное число < 1024 → отдаётся с юнитом B
        assert _api.utils.human_size(-5) == "-5.0B"

TestHumanSize.__module__ = _api.__name__
_api.TestHumanSize = TestHumanSize

# ── url_host / host_matches ───────────────────────────────────────────────────
class TestUrlHost:
    def test_basic(self):
        assert _api.utils.url_host("https://www.youtube.com/watch?v=x") == "www.youtube.com"

    def test_no_scheme(self):
        assert _api.utils.url_host("youtube.com/watch") == "youtube.com"

    def test_uppercase_lowered(self):
        assert _api.utils.url_host("https://YouTube.COM/х") == "youtube.com"

    def test_empty(self):
        assert _api.utils.url_host("") == ""

    def test_leading_slashes_stripped(self):
        assert _api.utils.url_host("//youtube.com/v") == "youtube.com"

    def test_garbage(self):
        # мусор без хоста не должен бросать исключение
        assert isinstance(_api.utils.url_host("::::"), str)

TestUrlHost.__module__ = _api.__name__
_api.TestUrlHost = TestUrlHost

class TestHostMatches:
    def test_exact(self):
        assert _api.utils.host_matches("https://youtube.com/w", "youtube.com")

    def test_subdomain(self):
        assert _api.utils.host_matches("https://m.youtube.com/w", "youtube.com")

    def test_spoof_path_rejected(self):
        # CWE-20: домен в пути не должен матчиться
        assert not _api.utils.host_matches("https://evil.com/youtube.com", "youtube.com")

    def test_spoof_suffix_rejected(self):
        assert not _api.utils.host_matches("https://youtube.com.evil.com/", "youtube.com")

    def test_multiple_domains(self):
        assert _api.utils.host_matches("https://youtu.be/x", "youtube.com", "youtu.be")

    def test_empty_url(self):
        assert not _api.utils.host_matches("", "youtube.com")

    def test_domain_with_leading_dot(self):
        assert _api.utils.host_matches("https://a.tiktok.com/", ".tiktok.com")

    def test_case_insensitive_domain(self):
        assert _api.utils.host_matches("https://YOUTUBE.com/", "YouTube.Com")

TestHostMatches.__module__ = _api.__name__
_api.TestHostMatches = TestHostMatches

# ── parse_youtube_start_seconds ───────────────────────────────────────────────
class TestParseYoutubeStart:
    def test_plain_seconds(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=9182") == 9182

    def test_seconds_with_s(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://www.youtube.com/watch?v=x&t=90s") == 90

    def test_composite_hms(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtu.be/x?t=1h30m5s") == 3600 + 30 * 60 + 5

    def test_composite_ms(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=2m10s") == 130

    def test_start_param(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&start=42") == 42

    def test_not_youtube(self):
        assert _api.utils.parse_youtube_start_seconds("https://vimeo.com/1?t=10") is None

    def test_no_param(self):
        assert _api.utils.parse_youtube_start_seconds("https://youtube.com/watch?v=x") is None

    def test_broken_value(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=abc") is None

    def test_empty_t(self):
        assert _api.utils.parse_youtube_start_seconds(
            "https://youtube.com/watch?v=x&t=") is None

TestParseYoutubeStart.__module__ = _api.__name__
_api.TestParseYoutubeStart = TestParseYoutubeStart

# ── get_cookies_path / _cookie_matches_domain ─────────────────────────────────
class TestCookies:
    def test_tiktok(self):
        assert _api.utils.get_cookies_path("https://www.tiktok.com/@a/video/1") == \
            _api.utils.COOKIE_PATHS["tiktok"]

    def test_instagram(self):
        assert _api.utils.get_cookies_path("https://instagram.com/p/1") == \
            _api.utils.COOKIE_PATHS["instagram"]

    def test_instagram_cdn(self):
        assert _api.utils.get_cookies_path("https://scontent.cdninstagram.com/v.mp4") == \
            _api.utils.COOKIE_PATHS["instagram"]

    def test_youtube(self):
        assert _api.utils.get_cookies_path("https://youtu.be/x") == \
            _api.utils.COOKIE_PATHS["youtube"]

    def test_bilibili(self):
        assert _api.utils.get_cookies_path("https://b23.tv/x") == \
            _api.utils.COOKIE_PATHS["bilibili"]

    def test_default(self):
        assert _api.utils.get_cookies_path("https://example.com/x") == \
            _api.utils.COOKIE_PATHS["default"]

    def test_cookie_mismatch_ig_with_youtube_cookies(self):
        assert not _api.utils._cookie_matches_domain(
            r"C:\cfg\cookies_youtube.txt", "https://instagram.com/p/1")

    def test_cookie_mismatch_tiktok(self):
        assert not _api.utils._cookie_matches_domain(
            "cookies_instagram.txt", "https://tiktok.com/@a")

    def test_cookie_mismatch_yt_with_ig(self):
        assert not _api.utils._cookie_matches_domain(
            "cookies_instagram.txt", "https://youtube.com/watch")

    def test_cookie_match_ok(self):
        assert _api.utils._cookie_matches_domain(
            "cookies_youtube.txt", "https://youtube.com/watch")

    def test_cookie_generic_ok_for_any(self):
        assert _api.utils._cookie_matches_domain("cookies.txt", "https://tiktok.com/@a")

TestCookies.__module__ = _api.__name__
_api.TestCookies = TestCookies

# ── is_direct_cdn_video / clean_url ──────────────────────────────────────────
class TestDirectCdn:
    def test_fbcdn_mp4(self):
        assert _api.utils.is_direct_cdn_video("https://video.fbcdn.net/v/t42/file.mp4?x=1")

    def test_cdninstagram_mov(self):
        assert _api.utils.is_direct_cdn_video("https://x.cdninstagram.com/a.mov")

    def test_wrong_host(self):
        assert not _api.utils.is_direct_cdn_video("https://example.com/a.mp4")

    def test_wrong_ext(self):
        assert not _api.utils.is_direct_cdn_video("https://v.fbcdn.net/page.html")

    def test_empty(self):
        assert not _api.utils.is_direct_cdn_video("")

TestDirectCdn.__module__ = _api.__name__
_api.TestDirectCdn = TestDirectCdn

class TestCleanUrl:
    def test_tiktok_query_stripped(self):
        assert _api.utils.clean_url("https://tiktok.com/@a/video/1?lang=en") == \
            "https://tiktok.com/@a/video/1"

    def test_tiktok_no_query(self):
        assert _api.utils.clean_url("https://tiktok.com/@a/video/1") == \
            "https://tiktok.com/@a/video/1"

    def test_direct_video_query_stripped(self):
        assert _api.utils.clean_url("https://cdn.example.com/v.mp4?token=abc") == \
            "https://cdn.example.com/v.mp4"

    def test_page_url_untouched(self):
        u = "https://example.com/watch?v=123"
        assert _api.utils.clean_url(u) == u

    def test_mkv_stripped(self):
        assert _api.utils.clean_url("https://x.com/f.MKV?sig=1") == "https://x.com/f.MKV"

TestCleanUrl.__module__ = _api.__name__
_api.TestCleanUrl = TestCleanUrl

# ── parse_version ─────────────────────────────────────────────────────────────
class TestParseVersion:
    @_api.pytest.mark.parametrize("s,expected", [
        ("v0.2-beta", (0, 2)),
        ("0.10 BETA", (0, 10)),
        ("", (0,)),
        (None, (0,)),
        ("1.2.3", (1, 2, 3)),
        ("release", (0,)),
        ("v10", (10,)),
    ])
    def test_values(self, s, expected):
        assert _api.utils.parse_version(s) == expected

    def test_comparison_semantics(self):
        assert _api.utils.parse_version("v0.10") > _api.utils.parse_version("v0.9")
        assert _api.utils.parse_version("v1.0") > _api.utils.parse_version("v0.99")

TestParseVersion.__module__ = _api.__name__
_api.TestParseVersion = TestParseVersion

# ── pretty_audio_codec / fmt_bitrate_with_codec / codec_label ────────────────
class TestCodecLabels:
    @_api.pytest.mark.parametrize("name,expected", [
        ("aac", "AAC"), ("opus", "Opus"), ("libopus", "Opus"), ("mp3", "MP3"),
        ("vorbis", "Vorbis"), ("flac", "FLAC"), ("eac3", "E-AC3"),
        ("pcm_s16le", "PCM"), ("truehd", "TrueHD"),
        ("неведомый", "НЕВЕДОМЫЙ"),
        ("", ""), (None, ""),
    ])
    def test_pretty_audio_codec(self, name, expected):
        assert _api.utils.pretty_audio_codec(name) == expected

    def test_whitespace_and_case(self):
        assert _api.utils.pretty_audio_codec("  AaC ") == "AAC"

    def test_fmt_both(self):
        assert _api.utils.fmt_bitrate_with_codec("aac", "153 кбит/с") == "AAC 153 кбит/с"

    def test_fmt_only_bitrate(self):
        assert _api.utils.fmt_bitrate_with_codec(None, "128 кбит/с") == "128 кбит/с"

    def test_fmt_only_codec(self):
        assert _api.utils.fmt_bitrate_with_codec("opus", "-") == "Opus"

    def test_fmt_nothing(self):
        assert _api.utils.fmt_bitrate_with_codec(None, "—") == "—"

    @_api.pytest.mark.parametrize("name,expected", [
        ("h264", "H.264"), ("avc1", "H.264"), ("hevc", "H.265"),
        ("av1", "AV1"), ("vp9", "VP9"), ("mpeg2video", "MPEG-2"),
        ("exotic", "EXOTIC"),
    ])
    def test_codec_label(self, name, expected):
        assert _api.utils.codec_label(name) == expected

    def test_codec_label_none(self):
        assert _api.utils.codec_label(None) is None
        assert _api.utils.codec_label("") is None

TestCodecLabels.__module__ = _api.__name__
_api.TestCodecLabels = TestCodecLabels
