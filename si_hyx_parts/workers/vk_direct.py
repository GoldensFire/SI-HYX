# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Прямое скачивание видео VK (vk.com / vk.ru / vkvideo.ru).

Зачем это нужно
---------------
Веб-версия VK переехала на новый SPA-плеер: старый `al_video.php` отвечает
`payload[0] == 3` («нужен вход») даже с валидными куками залогиненного
аккаунта, поэтому экстрактор yt-dlp для VK сейчас не работает в принципе.
Браузер же получает данные видео из `api.vk.ru/method/video.getByIds`, где
сессия подтверждается куками домена `.vk.ru`.

Мы повторяем этот путь: headless Chrome/Edge (Playwright) с куками из
cookies.txt открывает страницу видео, перехватывает ответ `video.getByIds`
и отдаёт прямые ссылки на файлы. Дальше файл качается ffmpeg'ом.
"""

import asyncio
import json
import os
import re
from urllib.parse import urlsplit

# Тот же UA, что у обычного Chrome: VK отдаёт файлы в зависимости от клиента.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)

VK_HOSTS = ("vk.com", "vk.ru", "vkvideo.ru")

# /video211617687_166105422, /video-123_456, /video_ext.php?oid=&id=
_RE_VIDEO_PATH = re.compile(r"^/video(-?\d+)_(\d+)/?$")
_RE_MP4_KEY = re.compile(r"^mp4_(\d+)$")


class VkResolveError(Exception):
    """VK не отдал прямую ссылку; текст исключения показывается пользователю."""


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def is_vk_video_url(url: str) -> bool:
    """True для ссылки на КОНКРЕТНОЕ видео VK (не клип, не плейлист)."""
    host = _host(url)
    if not host or not any(host == h or host.endswith("." + h) for h in VK_HOSTS):
        return False
    try:
        parts = urlsplit(url)
    except Exception:
        return False
    path = parts.path or ""
    if path.rstrip("/").endswith("/video_ext.php"):
        return True
    return bool(_RE_VIDEO_PATH.match(path))


def has_vk_login(cookies_path: str) -> bool:
    """Есть ли в cookies.txt сессионная кука VK (гостевой файл не подходит)."""
    try:
        with open(cookies_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) == 7 and fields[5] in ("remixsid", "remixstid"):
                    if fields[6].strip():
                        return True
    except Exception:
        return False
    return False


def _load_cookies(cookies_path: str) -> list:
    """Netscape cookies.txt → список cookie-объектов Playwright."""
    out = []
    with open(cookies_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 7:
                continue
            domain, _flag, cpath, secure, expires, name, value = fields
            out.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": cpath or "/",
                "secure": secure.upper() == "TRUE",
                "expires": float(expires) if expires.isdigit() else -1,
            })
    return out


def best_mp4(files: dict):
    """Лучший mp4 из ответа API: ('360p', url). Fallback — HLS-манифест."""
    best = None
    for key, url in (files or {}).items():
        m = _RE_MP4_KEY.match(key or "")
        if not m or not url:
            continue
        height = int(m.group(1))
        if best is None or height > best[0]:
            best = (height, url)
    if best:
        return f"{best[0]}p", best[1]
    for key in ("hls", "hls_fmp4"):
        if files.get(key):
            return "hls", files[key]
    return None


def safe_filename(title: str, fallback: str = "vk_video") -> str:
    """Имя файла без символов, запрещённых в Windows."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "").strip(" .")
    name = re.sub(r"\s{2,}", " ", name)
    return (name[:150].rstrip(" .") or fallback)


async def _resolve_async(url: str, cookies: list, timeout: float):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = None
        last_err = None
        for channel in ("chrome", "msedge"):
            try:
                browser = await pw.chromium.launch(channel=channel, headless=True)
                break
            except Exception as e:
                last_err = e
        if browser is None:
            raise VkResolveError(
                "не удалось запустить Chrome/Edge для получения ссылки "
                f"({last_err})")
        try:
            ctx = await browser.new_context(
                user_agent=USER_AGENT, locale="ru-RU",
                viewport={"width": 1280, "height": 720})
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            loop = asyncio.get_event_loop()
            fut = loop.create_future()

            async def _on_response(resp):
                if fut.done() or "video.getByIds" not in resp.url:
                    return
                try:
                    fut.set_result(await resp.text())
                except Exception as e:
                    fut.set_exception(e)

            page.on("response", lambda r: asyncio.ensure_future(_on_response(r)))
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                body = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                raise VkResolveError(
                    "страница не запросила данные видео (куки не подошли или "
                    "VK изменил API)")
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
            return body
        finally:
            try:
                await browser.close()
            except Exception:
                pass


def resolve_vk_media(url: str, cookies_path: str, log_fn=None, timeout: float = 30.0) -> dict:
    """Открывает страницу VK в headless-браузере и возвращает данные видео:
    {'title', 'duration', 'files', 'width', 'height'}.

    Бросает VkResolveError с понятным текстом, если ссылку получить нельзя."""
    if not cookies_path or not os.path.isfile(cookies_path):
        raise VkResolveError(
            "не найден файл cookies.txt — VK отдаёт видео только с куками "
            "залогиненного аккаунта")
    if not has_vk_login(cookies_path):
        raise VkResolveError(
            "в cookies.txt нет remixsid (это гостевые куки). Войдите в VK в "
            "браузере и экспортируйте куки залогиненного аккаунта")

    cookies = _load_cookies(cookies_path)
    if log_fn:
        log_fn("VK: получаю прямую ссылку через headless Chrome (куки из файла)…")
    try:
        body = asyncio.run(_resolve_async(url, cookies, timeout))
    except VkResolveError:
        raise
    except ImportError:
        raise VkResolveError(
            "модуль playwright не установлен — прямое скачивание VK недоступно")
    except Exception as e:
        raise VkResolveError(f"ошибка браузера: {e}")

    try:
        data = json.loads(body)
    except Exception:
        raise VkResolveError("VK вернул не JSON вместо данных видео")

    err = data.get("error")
    if err:
        raise VkResolveError(
            f"API VK: {err.get('error_msg') or err.get('error_code')}")
    items = (data.get("response") or {}).get("items") or []
    if not items:
        raise VkResolveError("VK не вернул данные видео (удалено или закрыто)")
    item = items[0]
    files = item.get("files") or {}
    if not best_mp4(files):
        raise VkResolveError("VK не отдал ни одной ссылки на файл видео")
    return {
        "title": item.get("title") or "",
        "duration": item.get("duration") or 0,
        "width": item.get("width") or 0,
        "height": item.get("height") or 0,
        "files": files,
    }
