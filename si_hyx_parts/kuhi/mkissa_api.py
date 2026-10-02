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

from . import mkissa as _api


def make_aa_req(key: bytes, epoch, build_id: str, query_hash: str, lane: str = _api.CONTENT_LANE) -> str:
    ts = (int(time.time() * 1000) // _api.AA_REQ_MS) * _api.AA_REQ_MS
    payload = json.dumps({"v": 1, "ts": ts, "epoch": epoch, "buildId": build_id,
                          "qh": query_hash, "k": lane}, separators=(",", ":")).encode("utf-8")
    iv = hashlib.sha256(f"{epoch}:{build_id}:{query_hash}:{ts}:{lane}".encode("utf-8")).digest()[:12]
    ct, tag = _api.aes_gcm_encrypt(bytes(key), iv, payload)
    return base64.b64encode(b"\x01" + iv + ct + tag).decode("ascii")


def decrypt_tobeparsed(b64: str, key: bytes):
    buf = base64.b64decode(b64)
    if not buf or buf[0] != 1:
        raise RuntimeError(f"Unsupported MKissa encryption version: {buf[0] if buf else None}")
    iv = buf[1:13]
    body = buf[13:]
    ct, tag = body[:-16], body[-16:]
    plain = _api.aes_gcm_decrypt(bytes(key), bytes(iv), bytes(ct), bytes(tag))
    return json.loads(plain.decode("utf-8"))


def episode_query() -> str:
    zt = "\ntbObj {\n  u\n  sm\n  md\n  ts\n}\n"
    pu = "\n_id\nname\nenglishName\nnativeName\nslugTime\n"
    xa = (f"\n{pu}\nthumbnail\n{zt}\nlastEpisodeInfo\nlastEpisodeDate\ntype\nseason\n"
          "score\nairedStart\navailableEpisodes\nepisodeDuration\nepisodeCount\n"
          "lastUpdateEnd\ncharacterCount\n")
    ef = ("\n  _id\n  username\n  displayName\n  createdAt\n  picture\n  reputation\n"
          "  roleLevel\n\n  \n  brief\n  followerCount\n  followingCount\n  pDec\n"
          "  equippedBadgeKey\n  equippedBadge {\n    key\n    name\n    rank\n"
          "    iconPath\n    date\n  }\n  ugcContributorStats {\n"
          "    mediaEditReviewSubmitCount\n    mediaEditApprovedCount\n"
          "    mediaEditRejectedCount\n    mediaEditAppliedCount\n"
          "    mediaEditContributionPoints\n    mediaEditModContributionPoints\n  }\n"
          "\n  hideMe\n")
    fr = ("\nviews\nlikesCount\ncommentCount\ndislikesCount\nboostsCount\nreviewCount\n"
          "userScoreCount\nuserScoreTotalValue\nuserScoreAverValue\nviewers{\nfirstViewers{\n"
          f"viewCount\nlastWatchedDate\nuser{{\n{ef}\n}}\n}}\nrecViewers{{\nviewCount\n"
          f"lastWatchedDate\nuser{{\n{ef}\n}}\n}}\n}}\n")
    return ("\nquery(\n$showId: String!\n$translationType: VaildTranslationTypeEnumType!\n"
            "$episodeString: String!\n) {\nepisode(\nshowId: $showId\n"
            "translationType: $translationType\nepisodeString: $episodeString\n) {\n"
            "episodeString\nuploadDate\nsourceUrls\nthumbnail\nnotes\nshow{\n"
            f"{xa}\ndescription\nbroadcastInterval\nbanner\ncharacters\n"
            "availableEpisodesDetail\nnameOnlyString\ncharacters\nisAdult\nrelatedShows\n"
            "relatedMangas\naltNames\ndisqusIds\n}\npageStatus{\n_id\nnotes\npageId\n"
            f"showId\n{fr}\n}}\nepisodeInfo{{\nnotes\nthumbnails\n{zt}\nvidInforssub\n"
            "uploadDates\nvidInforsdub\nvidInforsraw\ndescription\n}\nversionFix\n}\n}\n")


async def api_post(query: str, variables: dict, build_id=None, extensions=None) -> dict:
    if build_id is None:
        config = await _api.discover_crypto_config()
        build_id = config["buildId"]
    body = {"query": query, "variables": variables}
    if extensions is not None:
        body["extensions"] = extensions
    res = await _api._api_request("POST", _api.API_URL,
                             _api.api_headers(build_id, {"Content-Type": "application/json"}),
                             json_body=body)
    raw = res.text
    if res.status_code != 200:
        err = RuntimeError(f"API POST {res.status_code}")
        err.raw_body = raw
        raise err
    try:
        payload = json.loads(raw)
    except Exception:
        err = RuntimeError("API POST invalid JSON")
        err.raw_body = raw
        raise err
    errors = payload.get("errors") or []
    if errors:
        messages = [(e.get("message") or (e.get("extensions") or {}).get("code")
                     or "GraphQL error") for e in errors]
        err = (_api.NeedCaptchaError(" \u00b7 ".join(messages)) if "NEED_CAPTCHA" in messages
               else RuntimeError(" \u00b7 ".join(messages)))
        err.raw_body = raw
        err.graphql = payload
        raise err
    return payload.get("data") or {}


async def api_episode(query: str, variables: dict, force: bool = False,
                      captcha_retry: int = 0, captcha=None, post_fallback: bool = False) -> dict:
    digest = _api.sha256_hex(query)
    lane = await _api.get_lane_key(_api.CONTENT_LANE, force)
    key, epoch, build_id = lane["key"], lane["epoch"], lane["buildId"]
    extensions = {"persistedQuery": {"version": 1, "sha256Hash": digest},
                  "k": _api.CONTENT_LANE,
                  "aaReq": _api.make_aa_req(key, epoch, build_id, digest, _api.CONTENT_LANE)}
    if captcha:
        extensions["captcha"] = captcha
    if captcha:
        posted = await _api.api_post(query, variables, build_id, extensions)
        return _api.decrypt_tobeparsed(posted["tobeparsed"], key) if posted.get("tobeparsed") else posted
    enc = lambda v: quote(v, safe="!~*'()-._")
    url = (f"{_api.API_URL}?variables={enc(json.dumps(variables, separators=(',', ':')))}"
           f"&extensions={enc(json.dumps(extensions, separators=(',', ':')))}")
    res = await _api._api_request("GET", url, _api.api_headers(build_id))
    raw = res.text
    if res.status_code != 200:
        err = RuntimeError(f"API {res.status_code}")
        err.raw_body = raw
        raise err
    try:
        payload = json.loads(raw)
    except Exception:
        err = RuntimeError("API invalid JSON")
        err.raw_body = raw
        raise err
    errors = payload.get("errors") or []
    messages = [(e.get("message") or (e.get("extensions") or {}).get("code") or "")
                for e in errors]
    messages = [m for m in messages if m]
    if any(m == "PersistedQueryNotFound" or re.search(r"Context creation failed", m, re.IGNORECASE)
           for m in messages):
        posted = await _api.api_post(query, variables, build_id, extensions)
        return _api.decrypt_tobeparsed(posted["tobeparsed"], key) if posted.get("tobeparsed") else posted
    if "NEED_CAPTCHA" in messages:
        if not post_fallback:
            try:
                post_hash = _api.sha256_hex(query)
                post_ext = {"persistedQuery": {"version": 1, "sha256Hash": post_hash},
                            "k": _api.CONTENT_LANE,
                            "aaReq": _api.make_aa_req(key, epoch, build_id, post_hash, _api.CONTENT_LANE)}
                posted = await _api.api_post(query, variables, build_id, post_ext)
                return (_api.decrypt_tobeparsed(posted["tobeparsed"], key)
                        if posted.get("tobeparsed") else posted)
            except _api.NeedCaptchaError:
                pass
        if captcha_retry < _api.CAPTCHA_RETRIES:
            await asyncio.sleep(1.5 + captcha_retry * 1.2)
            return await _api.api_episode(query, variables, force=True,
                                     captcha_retry=captcha_retry + 1,
                                     post_fallback=True)
        err = _api.NeedCaptchaError("MKissa requested captcha")
        err.raw_body = raw
        raise err
    if any(re.match(r"^AA_CRYPTO_", m) for m in messages):
        if not force:
            return await _api.api_episode(query, variables, force=True,
                                     captcha_retry=captcha_retry, captcha=captcha,
                                     post_fallback=post_fallback)
        err = RuntimeError(" \u00b7 ".join(messages))
        err.raw_body = raw
        raise err
    data = payload.get("data") or {}
    if data.get("tobeparsed"):
        return _api.decrypt_tobeparsed(data["tobeparsed"], key)
    if messages:
        err = RuntimeError(" \u00b7 ".join(messages))
        err.raw_body = raw
        raise err
    return data


async def search_mkissa(query: str, mode: str = "sub") -> list:
    gql = ("query($search:SearchInput $limit:Int $page:Int $translationType:"
           "VaildTranslationTypeEnumType $countryOrigin:VaildCountryOriginEnumType)"
           "{shows(search:$search limit:$limit page:$page translationType:$translationType "
           "countryOrigin:$countryOrigin){edges{_id name englishName nativeName slugTime "
           "availableEpisodes availableEpisodesDetail aniListId __typename}}}")
    data = await _api.api_post(gql, {"search": {"allowAdult": False, "allowUnknown": False,
                                           "query": query},
                                "limit": 40, "page": 1, "translationType": mode,
                                "countryOrigin": "ALL"})
    return (data.get("shows") or {}).get("edges") or []


async def get_episode_sources(show_id: str, ep_num, audio: str = "sub", captcha=None):
    query = await _api.discover_episode_query()
    data = await _api.api_episode(query, {"showId": show_id, "translationType": audio,
                                     "episodeString": str(ep_num)}, captcha=captcha)
    return data.get("episode")
