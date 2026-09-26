# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_kodik_decode. Public namespace: utils."""
import utils as _api


def _kodik_decode(src: str) -> str:
    """Декодирует src ссылки Kodik: шифр ROT18 по буквам + base64."""
    out = []
    for ch in src:
        c = ord(ch)
        if 65 <= c <= 90:          # A-Z
            c += 18; c = c if c <= 90 else c - 26
            out.append(chr(c))
        elif 97 <= c <= 122:       # a-z
            c += 18; c = c if c <= 122 else c - 26
            out.append(chr(c))
        else:
            out.append(ch)
    b = "".join(out)
    b += "=" * (-len(b) % 4)       # дополняем паддинг base64
    return _api.base64.b64decode(b).decode("utf-8", "replace")

_kodik_decode.__module__ = _api.__name__
_api._kodik_decode = _kodik_decode

def is_embed_candidate(url: str) -> bool:
    """True, если для URL имеет смысл пробовать Kodik-резолвер
    (это http(s)-страница не из списка напрямую поддерживаемых сайтов)."""
    u = (url or "").lower()
    return u.startswith("http") and not any(d in u for d in _api.KNOWN_DIRECT_SITES)

is_embed_candidate.__module__ = _api.__name__
_api.is_embed_candidate = is_embed_candidate

def _find_kodik_iframe(page_url: str, session) -> str:
    """Ищет URL Kodik-iframe на странице: прямой iframe/ссылка либо через
    DLE-контроллер (data-params=mod=kodik-player...). Возвращает URL или ''."""
    from urllib.parse import urlparse
    try:
        html = session.get(page_url, timeout=30).text
    except Exception:
        return ""

    # 1) Прямая ссылка/iframe на kodik
    m = _api._KODIK_HOST_RE.search(html.replace("&amp;", "&"))
    if m:
        u = m.group(0)
        return ("https:" + u) if u.startswith("//") else u

    # 2) DLE XFPlayer: data-params="mod=kodik-player&...&id=N" → controller.php
    m = _api.re.search(r'data-params=["\']([^"\']*mod=kodik-player[^"\']*)["\']', html, _api.re.I)
    if m:
        params = m.group(1).replace("&amp;", "&")
        pu = urlparse(page_url)
        ctl = f"{pu.scheme}://{pu.netloc}/engine/ajax/controller.php?{params}"
        try:
            d = session.get(ctl, headers={"Referer": page_url,
                                          "X-Requested-With": "XMLHttpRequest"},
                            timeout=30).json()
            data = (d.get("data") or "").replace("&amp;", "&")
            if data:
                return ("https:" + data) if data.startswith("//") else data
        except Exception:
            pass
    return ""

_find_kodik_iframe.__module__ = _api.__name__
_api._find_kodik_iframe = _find_kodik_iframe

def _attr(s: str, name: str) -> str:
    m = _api.re.search(name + r'="([^"]*)"', s)
    return m.group(1) if m else ""

_attr.__module__ = _api.__name__
_api._attr = _attr

def _parse_kodik_selects(html: str):
    """Разбирает <select>-блоки сериального плеера Kodik.
    Возвращает (translations, episodes):
      translations = [(media_id, media_hash, title), ...]  — озвучки
      episodes     = [(value, data_id, data_hash, title), ...] — серии
    """
    translations, episodes = [], []
    for block in _api.re.findall(r"<select\b[^>]*>(.*?)</select>", html, _api.re.S):
        if "data-media-id" in block:               # озвучки
            for o in _api.re.findall(r"<option\b([^>]*)>", block):
                mid, mh = _api._attr(o, "data-media-id"), _api._attr(o, "data-media-hash")
                if mid and mh:
                    # data-media-type (season/serial/video) нужен для корректной
                    # перезагрузки страницы озвучки — раньше был жёстко /serial/.
                    translations.append((mid, mh, _api._attr(o, "data-title"),
                                         _api._attr(o, "data-media-type") or "serial"))
        elif "data-serial-id" in block:            # сезоны — пропускаем
            continue
        else:                                       # серии
            for o in _api.re.findall(r"<option\b([^>]*)>", block):
                did, dh = _api._attr(o, "data-id"), _api._attr(o, "data-hash")
                if did and dh:
                    episodes.append((_api._attr(o, "value"), did, dh, _api._attr(o, "data-title")))
    return translations, episodes

_parse_kodik_selects.__module__ = _api.__name__
_api._parse_kodik_selects = _parse_kodik_selects

def _selected_option(html: str, kind: str):
    """Возвращает атрибуты выбранного (<option ... selected>) в нужном <select>.
    kind: 'translation' (data-media-id), 'episode' (серии)."""
    for block in _api.re.findall(r"<select\b[^>]*>(.*?)</select>", html, _api.re.S):
        is_tr = "data-media-id" in block
        is_season = (not is_tr) and ("data-serial-id" in block)
        if is_season:
            continue
        if (kind == "translation") != is_tr:
            continue
        m = _api.re.search(r"<option\b([^>]*\bselected\b[^>]*)>", block)
        if m:
            return m.group(1)
    return ""

_selected_option.__module__ = _api.__name__
_api._selected_option = _selected_option

# ──────────────────────────────────────────────────────────────────────────
#  animego.* — плеер грузится отдельным AJAX (/player/{id} и
#  /player/videos/{episode_id}), статический Kodik-резолвер его не видит.
#  Берём Kodik-провайдера для выбранной серии/озвучки и отдаём в resolve_kodik.
# ──────────────────────────────────────────────────────────────────────────
def _is_animego(url: str) -> bool:
    """True для animego.* (animego.me/.org/.online/.one и т.п.)."""
    return 'animego.' in (url or '').lower()

_is_animego.__module__ = _api.__name__
_api._is_animego = _is_animego

def is_animego_site(url: str) -> bool:
    """Публичная обёртка над _is_animego (для `from utils import *` в workers)."""
    return _api._is_animego(url)

is_animego_site.__module__ = _api.__name__
_api.is_animego_site = is_animego_site

def _animego_base(page_url: str) -> str:
    from urllib.parse import urlparse
    pu = urlparse(page_url)
    return f"{pu.scheme}://{pu.netloc}"

_animego_base.__module__ = _api.__name__
_api._animego_base = _animego_base

def _animego_anime_id(page_url: str, session) -> str:
    """ID аниме для AJAX: из data-ajax-url='/player/N' на странице либо из слага '-N'."""
    try:
        page = session.get(page_url, timeout=30).text
    except Exception:
        page = ""
    m = _api.re.search(r'data-ajax-url="/player/(\d+)"', page)
    if m:
        return m.group(1)
    m = _api.re.search(r'-(\d+)/?(?:[?#].*)?$', page_url)
    return m.group(1) if m else ""

_animego_anime_id.__module__ = _api.__name__
_api._animego_anime_id = _animego_anime_id

def _animego_player_content(session, base: str, anime_id: str, ref: str,
                            episode_dataid: str = "") -> str:
    """HTML плеера (озвучки×провайдеры). episode_dataid='' = текущая/первая серия."""
    url = (f"{base}/player/videos/{episode_dataid}" if episode_dataid
           else f"{base}/player/{anime_id}")
    try:
        j = session.get(url, headers={"Referer": ref,
                                      "X-Requested-With": "XMLHttpRequest"},
                        timeout=30).json()
        return (j.get("data") or {}).get("content", "") or ""
    except Exception:
        return ""

_animego_player_content.__module__ = _api.__name__
_api._animego_player_content = _animego_player_content

def _animego_parse(content: str):
    """(episodes, players): episodes={номер: data-episode-id},
    players=[(provider_title, translation_title, player_url), ...]."""
    eps = {}
    for m in _api.re.finditer(r'data-episode-number="(\d+)"[\s\S]*?data-episode="(\d+)"', content):
        eps.setdefault(int(m.group(1)), m.group(2))
    players = []
    for tag in _api.re.findall(r'<button[^>]*data-player="[^"]*"[^>]*>', content):
        u = _api._attr(tag, "data-player")
        if u:
            players.append((_api._attr(tag, "data-provider-title"),
                            _api._attr(tag, "data-translation-title"),
                            u.replace("&amp;", "&")))
    return eps, players

_animego_parse.__module__ = _api.__name__
_api._animego_parse = _animego_parse

def _animego_kodik_players(players):
    """Только Kodik-провайдеры — их умеет resolve_kodik (AniBoom и пр. не поддержаны)."""
    return [p for p in players if 'kodik' in (p[0] + p[2]).lower()]

_animego_kodik_players.__module__ = _api.__name__
_api._animego_kodik_players = _animego_kodik_players

def animego_get_info(page_url: str, proxy: str = "") -> dict:
    """Списки озвучек и число серий для animego.* — формат как у kodik_get_info."""
    s = _api._requests().Session()
    s.headers.update({"User-Agent": _api.USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    aid = _api._animego_anime_id(page_url, s)
    if not aid:
        return {}
    content = _api._animego_player_content(s, _api._animego_base(page_url), aid, page_url)
    if not content:
        return {}
    eps, players = _api._animego_parse(content)
    dubs = []
    for p in _api._animego_kodik_players(players):
        if p[1] and p[1] not in dubs:
            dubs.append(p[1])
    return {"translations": dubs,
            "episodes": (max(eps) if eps else 0),
            "cur_translation": (dubs[0] if dubs else ""),
            "cur_episode": (min(eps) if eps else 1)}

animego_get_info.__module__ = _api.__name__
_api.animego_get_info = animego_get_info

def _animego_resolve_kodik_url(page_url: str, episode=None, translation: str = "",
                               proxy: str = "", log_fn=None) -> str:
    """Kodik-embed для выбранной серии и озвучки на animego.* (или '' если нет)."""
    s = _api._requests().Session()
    s.headers.update({"User-Agent": _api.USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    aid = _api._animego_anime_id(page_url, s)
    if not aid:
        return ""
    base = _api._animego_base(page_url)
    eps, players = _api._animego_parse(_api._animego_player_content(s, base, aid, page_url))
    if episode and eps:
        try:
            epn = int(episode)
        except Exception:
            epn = None
        if epn and epn in eps:
            c2 = _api._animego_player_content(s, base, aid, page_url, episode_dataid=eps[epn])
            if c2:
                _, players = _api._animego_parse(c2)
                if log_fn: log_fn(f"animego: серия {epn}")
    kod = _api._animego_kodik_players(players)
    if not kod:
        if log_fn: log_fn("animego: для этой серии нет Kodik-плеера (доступен только AniBoom/др. — они не поддержаны).")
        return ""
    if translation:
        match = [p for p in kod if translation.lower() in (p[1] or "").lower()]
        if match:
            kod = match
        elif log_fn:
            log_fn(f"animego: озвучка «{translation}» не найдена, беру «{kod[0][1]}».")
    if log_fn: log_fn(f"animego: озвучка «{kod[0][1]}» через Kodik.")
    u = kod[0][2]
    return ("https:" + u) if u.startswith("//") else u

_animego_resolve_kodik_url.__module__ = _api.__name__
_api._animego_resolve_kodik_url = _animego_resolve_kodik_url

def kodik_get_info(page_url: str, proxy: str = "") -> dict:
    """Возвращает данные Kodik-страницы для выпадашек:
    {'translations': [названия], 'episodes': N,
     'cur_translation': название, 'cur_episode': номер}."""
    if _api._is_animego(page_url):
        info = _api.animego_get_info(page_url, proxy)
        if info:
            return info
        # AJAX-плеер не отдал данные (другой клон, напр. DLE-сайт animego.online)
        # — проваливаемся в общий Kodik-путь ниже (_find_kodik_iframe видит DLE).
    s = _api._requests().Session()
    s.headers.update({"User-Agent": _api.USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    iframe = _api._find_kodik_iframe(page_url, s)
    if not iframe:
        return {}
    try:
        html = s.get(iframe, headers={"Referer": page_url}, timeout=30).text
    except Exception:
        return {}
    translations, episodes = _api._parse_kodik_selects(html)
    cur_tr = _api._attr(_api._selected_option(html, "translation"), "data-title")
    cur_ep_str = _api._attr(_api._selected_option(html, "episode"), "value")
    try: cur_ep = int(cur_ep_str)
    except Exception: cur_ep = 0
    return {"translations": [t[2] for t in translations if t[2]],
            "episodes": len(episodes),
            "cur_translation": cur_tr,
            "cur_episode": cur_ep}

kodik_get_info.__module__ = _api.__name__
_api.kodik_get_info = kodik_get_info
