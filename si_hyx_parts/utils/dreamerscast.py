# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Dream Cast (dreamerscast.com): прямой HLS из встроенного плеера.

Сайт не отдаёт видео через yt-dlp: на странице стоит Playerjs, а ссылка на
master.m3u8 спрятана в base64 (в функции vlc() и в параметрах плеера). Здесь
достаём её, разбираем master-манифест и возвращаем поток нужной высоты.
Public namespace: utils."""
import utils as _api

# Служебные base64-вставки в аргументе Playerjs: начинаются с «//» и
# заканчиваются паддингом «==». В обычном base64 паддинг встречается только в
# самом конце строки, поэтому такие куски можно вырезать и получить целый JSON.
_PLAYERJS_JUNK_RE = _api.re.compile(r"//[A-Za-z0-9+/]+?==")


def is_dreamerscast_site(url: str) -> bool:
    """True для dreamerscast.com и его поддоменов."""
    return _api.host_matches(url, "dreamerscast.com")


is_dreamerscast_site.__module__ = _api.__name__
_api.is_dreamerscast_site = is_dreamerscast_site


def _safe_stream_url(url: str) -> str:
    """Проверяет, что ссылка ведёт на http(s)-поток Dream Cast."""
    from urllib.parse import urlsplit
    try:
        pu = urlsplit((url or "").strip())
    except Exception:
        return ""
    if pu.scheme not in ("http", "https"):
        return ""
    host = (pu.hostname or "").lower()
    if not (host == "dreamerscast.com" or host.endswith(".dreamerscast.com")):
        return ""
    return pu.geturl()


def _playerjs_payload(src: str) -> dict:
    """base64-JSON из аргумента `new Playerjs("#2…")` без служебных вставок.

    Вставки бывают разной длины и могут стоять в любом месте, поэтому не
    угадываем одну, а перебираем варианты вырезания: первый же вариант, из
    которого получается JSON-объект, и есть настоящий payload."""
    body = src[1:] if src.startswith("#") else src
    if body.startswith("2"):
        body = body[1:]
    queue = [body]
    seen = {body}
    for _ in range(8):
        pending = []
        for candidate in queue:
            try:
                data = _api.json.loads(
                    _api.base64.b64decode(candidate + "=" * (-len(candidate) % 4))
                    .decode("utf-8", "replace"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
            for match in _PLAYERJS_JUNK_RE.finditer(candidate):
                shorter = candidate[:match.start()] + candidate[match.end():]
                if shorter not in seen:
                    seen.add(shorter)
                    pending.append(shorter)
        queue = pending[:256]
        if not queue:
            break
    return {}


def _master_from_playerjs(html: str) -> str:
    """Ссылка на master.m3u8 из Playerjs (обычно первая в поле file)."""
    m = _api.re.search(r'new\s+Playerjs\(\s*["\']([^"\']+)["\']\s*\)', html)
    if not m:
        return ""
    data = _playerjs_payload(m.group(1))
    urls = [u.strip() for u in (data.get("file") or "").split(" or ")]
    for u in urls:
        if _safe_stream_url(u) and ".m3u8" in u.lower():
            return u
    for u in urls:
        if _safe_stream_url(u):
            return u
    return ""


def _master_from_vlc(html: str) -> str:
    """Ссылка из `function vlc()` — обычно чистый master.m3u8 без вставок."""
    m = _api.re.search(
        r"function\s+vlc\s*\(\s*\)[\s\S]{0,2000}?atob\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)",
        html)
    if not m:
        return ""
    try:
        url = _api.base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)).decode(
            "utf-8", "replace")
    except Exception:
        return ""
    return _safe_stream_url(url)


def _pick_hls_variant(session, master_url: str, referer: str, want_height: int, log_fn=None):
    """(URL варианта, высота) из master.m3u8; при неудаче — ('', 0)."""
    from urllib.parse import urljoin
    try:
        text = session.get(master_url, headers={"Referer": referer}, timeout=30).text
    except Exception as e:
        if log_fn:
            log_fn(f"Dream Cast: master.m3u8 не открылся ({e})")
        return "", 0

    lines = [line.strip() for line in text.splitlines()]
    variants = []
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        m = _api.re.search(r"RESOLUTION=\d+x(\d+)", line)
        url = next((nxt for nxt in lines[i + 1:] if nxt and not nxt.startswith("#")), "")
        if not url:
            continue
        variants.append((int(m.group(1)) if m else 0, urljoin(master_url, url)))
    if not variants:
        return "", 0

    heights = sorted(h for h, _ in variants if h)
    if not heights:
        return variants[0][1], 0
    fitting = [h for h in heights if h <= want_height]
    chosen_height = max(fitting) if fitting else max(heights)
    chosen_url = next(url for h, url in variants if h == chosen_height)
    return chosen_url, chosen_height


def _height_from_url(url: str, want_height: int) -> int:
    """Высота из имени мастер-плейлиста (…_,1080,720,low,…)."""
    heights = [int(n) for n in _api.re.findall(r"(?:^|[,/])(\d{3,4})(?=[,/])", url)]
    if not heights:
        return max(0, int(want_height or 0))
    fitting = [h for h in heights if h <= want_height]
    return max(fitting) if fitting else max(heights)


def resolve_dreamerscast(page_url: str, want_height: int = 720, proxy: str = "",
                         log_fn=None) -> dict:
    """Прямой HLS-поток Dream Cast: {'url','referer','height','name'} или {}."""
    from urllib.parse import urlsplit
    s = _api._requests().Session()
    s.headers.update({"User-Agent": _api.USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    try:
        html = s.get(page_url, timeout=30).text
    except Exception as e:
        if log_fn:
            log_fn(f"Dream Cast: не удалось открыть страницу ({e})")
        return {}

    master = _master_from_vlc(html) or _master_from_playerjs(html)
    if not master:
        if log_fn:
            log_fn("Dream Cast: ссылка на плеер не найдена на странице")
        return {}

    pu = urlsplit(page_url)
    referer = f"{pu.scheme}://{pu.netloc}/" if pu.scheme and pu.netloc else page_url
    stream, height = _pick_hls_variant(s, master, referer, want_height, log_fn)
    if stream:
        if log_fn:
            log_fn(f"Dream Cast: HLS {height}p")
        return {"url": stream, "referer": referer, "height": height,
                "name": "Dream Cast"}
    if log_fn:
        log_fn("Dream Cast: варианты не разобраны — качаю master.m3u8 целиком")
    return {"url": master, "referer": referer,
            "height": _height_from_url(master, want_height), "name": "Dream Cast"}


resolve_dreamerscast.__module__ = _api.__name__
_api.resolve_dreamerscast = resolve_dreamerscast
