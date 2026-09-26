# -*- coding: utf-8 -*-
"""Модульные тесты чистых функций utils.py (без сети/subprocess/Qt)."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import base64
import html as html_mod
import re

import pytest

import utils

from si_hyx_parts.tests.test_utils_pure.test_clean_ansi import (
    TestCleanAnsi,
    TestHumanSize,
    TestUrlHost,
    TestHostMatches,
    TestParseYoutubeStart,
    TestCookies,
    TestDirectCdn,
    TestCleanUrl,
    TestParseVersion,
    TestCodecLabels,
)

from si_hyx_parts.tests.test_utils_pure.kodik_encode import (
    _kodik_encode,
    TestKodikDecode,
    TestIsEmbedCandidate,
    TestAttr,
)


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

from si_hyx_parts.tests.test_utils_pure.test_parse_kodik_selects import (
    TestParseKodikSelects,
    TestAnimego,
    _decode_data_si,
    TestMaskHtmlJs,
    _lite_items,
    _lite_scripts,
    _lite_raw_assets,
    _no_executable_literals,
)

from si_hyx_parts.tests.test_utils_pure.test_mask_html_js_lite import (
    TestMaskHtmlJsLite,
    TestDefaultDownloadDir,
)
