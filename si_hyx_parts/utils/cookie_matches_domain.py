# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_cookie_matches_domain. Public namespace: utils."""
import utils as _api


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
