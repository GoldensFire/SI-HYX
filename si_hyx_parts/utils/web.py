# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ссылки и загрузки: хост, тайм-код YouTube, файл куки, прямые CDN-ссылки. Public namespace: utils."""
import utils as _api


def url_host(url: str) -> str:
    """Возвращает hostname URL в нижнем регистре ('' если не распарсилось).
    Если схема отсутствует — подставляем https://, чтобы netloc распознался."""
    try:
        from urllib.parse import urlparse
        raw = url if '://' in url else 'https://' + url.lstrip('/')
        return (urlparse(raw).hostname or '').lower()
    except Exception:
        return ''

url_host.__module__ = _api.__name__
_api.url_host = url_host


def host_matches(url: str, *domains: str) -> bool:
    """True, если hostname URL равен одному из domains ИЛИ является его
    поддоменом. Безопасная замена проверки `'domain' in url`, которую легко
    обойти (evil.com/youtube.com, youtube.com.evil.com и т.п.) — CWE-20."""
    host = _api.url_host(url)
    if not host:
        return False
    for d in domains:
        d = d.lower().lstrip('.')
        if host == d or host.endswith('.' + d):
            return True
    return False

host_matches.__module__ = _api.__name__
_api.host_matches = host_matches


def parse_youtube_start_seconds(url: str):
    """Достаёт тайминг из параметра t=/start= ссылки на YouTube (в секундах).
    Понимает как чистые секунды (t=9182, t=9182s), так и составной формат
    (t=1h30m5s, t=2m10s). Возвращает None, если ссылка не с YouTube или
    параметра нет/он битый."""
    if not _api.host_matches(url, 'youtube.com', 'youtu.be'):
        return None
    try:
        from urllib.parse import urlparse, parse_qs
        import re
        q = parse_qs(urlparse(url).query)
        raw = (q.get('t') or q.get('start') or [None])[0]
        if not raw:
            return None
        raw = raw.strip()
        if raw.isdigit():
            return int(raw)
        m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', raw)
        if not m or not any(m.groups()):
            return None
        h, mi, s = (int(g) if g else 0 for g in m.groups())
        return h * 3600 + mi * 60 + s
    except Exception:
        return None

parse_youtube_start_seconds.__module__ = _api.__name__
_api.parse_youtube_start_seconds = parse_youtube_start_seconds


def get_cookies_path(url: str) -> str:
    if _api.host_matches(url, 'tiktok.com'):   return _api.COOKIE_PATHS['tiktok']
    if _api.host_matches(url, 'instagram.com', 'fbcdn.net', 'cdninstagram.com'):
        return _api.COOKIE_PATHS['instagram']
    if _api.host_matches(url, 'youtube.com', 'youtu.be'): return _api.COOKIE_PATHS['youtube']
    if _api.host_matches(url, 'bilibili.com', 'b23.tv'): return _api.COOKIE_PATHS['bilibili']
    return _api.COOKIE_PATHS['default']

get_cookies_path.__module__ = _api.__name__
_api.get_cookies_path = get_cookies_path


def _cookie_matches_domain(cookie_path: str, url: str) -> bool:
    """Проверяет, подходит ли файл куки к домену URL.
    Если имя файла содержит название другого сервиса — не подходит."""
    cp = _api.os.path.basename(cookie_path).lower()
    is_ig = _api.host_matches(url, 'instagram.com', 'fbcdn.net', 'cdninstagram.com')
    is_tt = _api.host_matches(url, 'tiktok.com')
    is_yt = _api.host_matches(url, 'youtube.com', 'youtu.be')
    # Instagram/fbcdn с YouTube-куками → не подходит
    if is_ig and 'youtube' in cp: return False
    if is_tt and ('youtube' in cp or 'instagram' in cp): return False
    if is_yt and 'instagram' in cp: return False
    return True

_cookie_matches_domain.__module__ = _api.__name__
_api._cookie_matches_domain = _cookie_matches_domain


def is_direct_cdn_video(url: str) -> bool:
    """True если URL — прямая CDN-ссылка на видеофайл (не страница сервиса).
    Такие ссылки нельзя передавать yt-dlp — он не может извлечь метаданные
    и падает с 403 или создаёт имя файла из URL.
    """
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        path = p.path.lower()
        is_cdn_host = _api.host_matches(url, 'fbcdn.net', 'cdninstagram.com', 'cdntiktok.com')
        is_video_ext = path.endswith(('.mp4', '.webm', '.mov', '.m4v', '.ts'))
        return is_cdn_host and is_video_ext
    except Exception:
        return False

is_direct_cdn_video.__module__ = _api.__name__
_api.is_direct_cdn_video = is_direct_cdn_video


def download_cdn_direct(url: str, out_dir: str, log_fn=None) -> str:
    """Скачивает прямую CDN-ссылку через requests с нужными заголовками.
    Возвращает путь к сохранённому файлу или бросает исключение.
    """
    from pathlib import Path
    from urllib.parse import urlparse, unquote
    from filenames import safe_filename, unique_path

    # Имя файла берём из пути URL (без query-параметров) и оставляем как есть —
    # режем только запрещённое файловой системой (см. filenames.safe_filename).
    path_part = urlparse(url).path
    raw_name  = _api.os.path.basename(path_part) or "video.mp4"
    safe_name = safe_filename(unquote(raw_name), "video.mp4")
    if not safe_name.endswith(('.mp4', '.webm', '.mov', '.m4v')):
        safe_name += '.mp4'

    out_path = str(unique_path(Path(out_dir) / safe_name))

    headers = {
        "User-Agent": _api.USER_AGENT,
        "Referer":    "https://www.instagram.com/",
        "Accept":     "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if log_fn: log_fn(f"Прямое скачивание CDN: {url[:60]}...")
    with _api.http_get(url, headers=headers, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        with open(out_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if log_fn and total:
                    pct = downloaded * 100 // total
                    log_fn(f"CDN загрузка: {pct}%")
    if log_fn: log_fn(f"CDN загрузка завершена: {out_path}")
    return out_path

download_cdn_direct.__module__ = _api.__name__
_api.download_cdn_direct = download_cdn_direct


def default_download_dir() -> str:
    """Папка загрузок пользователя по умолчанию (… \\Downloads).
    Если её нет — домашняя папка."""
    try:
        d = _api.os.path.join(_api.os.path.expanduser("~"), "Downloads")
        if _api.os.path.isdir(d):
            return d
    except Exception:
        pass
    return _api.os.path.expanduser("~")

default_download_dir.__module__ = _api.__name__
_api.default_download_dir = default_download_dir


def clean_url(url: str) -> str:
    if _api.host_matches(url, 'tiktok.com') and '?' in url:
        return url.split('?')[0]
    # Прямые CDN-ссылки на видеофайлы (Instagram, Facebook и др.):
    # yt-dlp не может извлечь title/id из CDN URL → имя файла содержит
    # недопустимые символы Windows (?&=). Стрипаем query-параметры.
    if '?' in url:
        path = url.split('?')[0]
        if path.lower().endswith(('.mp4', '.webm', '.mov', '.m4v', '.avi', '.mkv')):
            return path
    return url

clean_url.__module__ = _api.__name__
_api.clean_url = clean_url
