# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import unicodedata
from urllib.parse import quote, urljoin, urlparse

from si_hyx_parts.kuhi import _transport as httpx

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_json, fetch_text
from si_hyx_parts.kuhi._match import build_titles, decode_entities, episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

NAME = "mkissa"
UA4 = UA
REFERER = "https://mkissa.to"
API = "https://api.mkissa.net"
API_URL = f"{API}/api"
CONTENT_LANE = "k7"
REFERER_HOST = "mkissa.to"
KEY_GROUP = "mkissa"
BOOT_EPOCH_MS = 604800000
BOOT_GRACE_MS = 86400000
AA_REQ_MS = 300000
WATCH_MEMORY_TTL = 45
DISCOVERY_CONCURRENCY = 16
DISCOVERY_LIMIT = 600
FETCH_TIMEOUT = 10.0
EXTRACT_TIMEOUT = 5.0
CAPTCHA_RETRIES = 5

HEX_TABLE = {
    "79": "A", "7a": "B", "7b": "C", "7c": "D", "7d": "E", "7e": "F",
    "7f": "G", "70": "H", "71": "I", "72": "J", "73": "K", "74": "L",
    "75": "M", "76": "N", "77": "O", "68": "P", "69": "Q", "6a": "R",
    "6b": "S", "6c": "T", "6d": "U", "6e": "V", "6f": "W", "60": "X",
    "61": "Y", "62": "Z", "59": "a", "5a": "b", "5b": "c", "5c": "d",
    "5d": "e", "5e": "f", "5f": "g", "50": "h", "51": "i", "52": "j",
    "53": "k", "54": "l", "55": "m", "56": "n", "57": "o", "48": "p",
    "49": "q", "4a": "r", "4b": "s", "4c": "t", "4d": "u", "4e": "v",
    "4f": "w", "40": "x", "41": "y", "42": "z", "08": "0", "09": "1",
    "0a": "2", "0b": "3", "0c": "4", "0d": "5", "0e": "6", "0f": "7",
    "00": "8", "01": "9", "15": "-", "16": ".", "67": "_", "46": "~",
    "02": ":", "17": "/", "07": "?", "1b": "#", "63": "[", "65": "]",
    "78": "@", "19": "!", "1c": "$", "1e": "&", "10": "(", "11": ")",
    "12": "*", "13": "+", "14": ",", "03": ";", "05": "=", "1d": "%",
}

_crypto_config = None
_episode_query_cache = None
_session_cookies = {}
_watch_cache = {}

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"


class NeedCaptchaError(RuntimeError):
    code = "NEED_CAPTCHA"

    def __init__(self, message="MKissa requested captcha"):
        super().__init__(message)
        self.raw_body = None


from .mkissa_http import decode_hex_url


from .mkissa_http import sha256_hex


from .mkissa_http import hmac_bytes


from .mkissa_http import store_cookies


from .mkissa_http import cookie_header


from .mkissa_http import browser_headers


from .mkissa_http import api_headers


from .mkissa_http import _session_get_text


from .mkissa_http import _api_request


from .mkissa_http import _raw_get


from .mkissa_http import _raw_post


from .mkissa_js_strings import find_balanced_block


from .mkissa_js_strings import normalize_crypto_config


from .mkissa_js_strings import find_statement_end


from .mkissa_js_strings import _split_top


from .mkissa_js_strings import split_top_level


from .mkissa_js_strings import declaration_statement_at


from .mkissa_js_strings import template_dependencies


from .mkissa_js_strings import template_declaration


from .mkissa_js_strings import valid_episode_query


from .mkissa_js_strings import _unescape_js_string


from .mkissa_js_strings import _resolve_def


from .mkissa_js_strings import _eval_str_expr


from .mkissa_query_parser import eval_episode_query_chunk


from .mkissa_query_parser import _extract_mask_array


from .mkissa_query_parser import _extract_build_id


from .mkissa_query_parser import eval_fragment_crypto_chunk


from .mkissa_query_parser import _eval_legacy_shape


from .mkissa_query_parser import eval_old_crypto_chunk


from .mkissa_query_parser import eval_modern_crypto_chunk

_JS_IDENT = r"[A-Za-z_$][\w$]*"


from .mkissa_js_parser import _js_number


from .mkissa_js_parser import _js_parse_int


from .mkissa_js_parser import _tok_js


from .mkissa_js_parser import _JsParser


from .mkissa_js_parser import _js_eval


from .mkissa_js_parser import _js_eval_str


from .mkissa_js_parser import _scan_balanced


from .mkissa_js_parser import _parse_js_array_literal


from .mkissa_js_parser import _eval_js_value


from .mkissa_js_wrappers import _parse_map_literal


from .mkissa_js_wrappers import _rotate_live_table


from .mkissa_js_wrappers import _emulate_wrappers


from .mkissa_js_config import _emulated_fragment_config


from .mkissa_js_config import eval_crypto_chunk


from .mkissa_discovery import app_entry_url


from .mkissa_discovery import _chunk_imports


from .mkissa_discovery import _fetch_chunk


from .mkissa_discovery import discover_crypto_config


from .mkissa_discovery import discover_episode_query


from .mkissa_bootstrap import build_mask_seed


from .mkissa_bootstrap import build_mask


from .mkissa_bootstrap import current_epochs


from .mkissa_bootstrap import make_boot_token


from .mkissa_bootstrap import is_unknown_build_id


from .mkissa_bootstrap import fetch_bootstrap


from .mkissa_bootstrap import derive_lane_key


from .mkissa_bootstrap import get_lane_key


from .mkissa_sboxes import _gf_mul


from .mkissa_sboxes import _gf_pow


from .mkissa_sboxes import _build_sboxes

_SBOX, _INV_SBOX = _build_sboxes()
_RCON = [0] * 11
_acc = 1
for _i in range(1, 11):
    _RCON[_i] = _acc
    _acc = _gf_mul(_acc, 2)


from .mkissa_aes import _rot_word


from .mkissa_aes import _sub_word


from .mkissa_aes import _key_expansion


from .mkissa_aes import _add_round_key


from .mkissa_aes import _aes_encrypt_block


from .mkissa_aes import _aes_decrypt_block


from .mkissa_aes import _gf128_mul


from .mkissa_aes import _ghash


from .mkissa_aes import _gctr


from .mkissa_aes import aes_gcm_encrypt


from .mkissa_aes import aes_gcm_decrypt


from .mkissa_aes import aes_cbc_decrypt


from .mkissa_api import make_aa_req


from .mkissa_api import decrypt_tobeparsed


from .mkissa_api import episode_query


from .mkissa_api import api_post


from .mkissa_api import api_episode


from .mkissa_api import search_mkissa


from .mkissa_api import get_episode_sources


from .mkissa_series import slugify_title


from .mkissa_series import warm_watch_page


from .mkissa_series import _normalize


from .mkissa_series import _extract_year


from .mkissa_series import find_best_match


from .mkissa_series import resolve_series


from .mkissa_series import _fresh_show


from .mkissa_series import _coerce_numbers


from .mkissa_series import _build_lists


from .mkissa_series import get_episodes


from .mkissa_extract import hex_to_bytes


from .mkissa_extract import aes_decrypt


from .mkissa_extract import extract_mp4


from .mkissa_extract import extract_uns


from .mkissa_extract import extract_ok


from .mkissa_extract import extract_stream_sb


from .mkissa_extract import extract_clock


from .mkissa_extract import extract_streamlare


from .mkissa_extract import embed_media_type


from .mkissa_extract import is_clock_url


from .mkissa_extract import extract_source


from .mkissa_extract import _map_source


from .mkissa_extract import watch
