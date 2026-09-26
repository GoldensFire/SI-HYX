# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_kodik_encode. Public namespace: test_utils_pure."""
import test_utils_pure as _api


# ── kodik: декодер и парсеры HTML ────────────────────────────────────────────
def _kodik_encode(plain: str) -> str:
    """Обратное преобразование к _kodik_decode: base64 + сдвиг букв на 8
    (декодер сдвигает на +18, 18+8=26 → тождество)."""
    b = _api.base64.b64encode(plain.encode("utf-8")).decode("ascii")
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

_kodik_encode.__module__ = _api.__name__
_api._kodik_encode = _kodik_encode

class TestKodikDecode:
    def test_roundtrip(self):
        plain = "//cloud.kodik-storage.com/video/123/abc/720.mp4:hls:manifest.m3u8"
        assert _api.utils._kodik_decode(_api._kodik_encode(plain)) == plain

    def test_roundtrip_stripped_padding(self):
        plain = "//example.com/a"
        enc = _api._kodik_encode(plain).rstrip("=")
        assert _api.utils._kodik_decode(enc) == plain

    def test_non_letters_preserved(self):
        plain = "1234//::"
        assert _api.utils._kodik_decode(_api._kodik_encode(plain)) == plain

TestKodikDecode.__module__ = _api.__name__
_api.TestKodikDecode = TestKodikDecode

class TestIsEmbedCandidate:
    def test_unknown_site(self):
        assert _api.utils.is_embed_candidate("https://animego.online/anime/1")

    def test_known_direct(self):
        assert not _api.utils.is_embed_candidate("https://www.youtube.com/watch?v=1")

    def test_not_http(self):
        assert not _api.utils.is_embed_candidate("ftp://x.com/1")
        assert not _api.utils.is_embed_candidate("")
        assert not _api.utils.is_embed_candidate(None)

TestIsEmbedCandidate.__module__ = _api.__name__
_api.TestIsEmbedCandidate = TestIsEmbedCandidate

class TestAttr:
    def test_found(self):
        assert _api.utils._attr('a data-id="42" b', "data-id") == "42"

    def test_missing(self):
        assert _api.utils._attr("no attrs here", "data-id") == ""

    def test_empty_value(self):
        assert _api.utils._attr('data-id=""', "data-id") == ""

TestAttr.__module__ = _api.__name__
_api.TestAttr = TestAttr
