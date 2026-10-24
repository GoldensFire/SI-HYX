# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""File API Gemini (REST, без google-genai): загрузка, ожидание, удаление.

Файл (видео до 2 ГБ, хранится 48 часов, на бесплатном тарифе бесплатно)
загружается в два запроса resumable-протокола: start → адрес загрузки из
заголовка x-goog-upload-url, затем «upload, finalize» с телом файла. Видео
обрабатывается сервером (state PROCESSING → ACTIVE). Ссылку file.uri
отдают в Interactions частью {"type": "video", "uri": …, "mime_type": …,
"processing": {"type": "static", "fps": …, "start_offset": с,
"end_offset": с}, "resolution": "low"} — GeminiClient.generate_json
передаёт такие части как есть. Квоту запросов модели File API не тратит."""
from __future__ import annotations

import os
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

import gemini_api

UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
_HOST = "generativelanguage.googleapis.com"
_CHUNK = 8 << 20


class GeminiFileError(gemini_api.GeminiError):
    """Файл не загрузился или не обработан сервером."""


def _check(resp, what):
    if resp.status_code in (401, 403):
        raise gemini_api.GeminiAuthError(f"File API: {what}: {resp.status_code}")
    if resp.status_code >= 400:
        raise GeminiFileError(f"File API: {what}: {resp.status_code} {resp.text[:300]}")


def upload_file(api_key: str, path: str, mime_type: str, display_name: str = "",
                session: Optional[requests.Session] = None, timeout: float = 600.0,
                stopped: Optional[Callable[[], bool]] = None) -> dict:
    """Загружает файл; ответ — словарь file (name, uri, mimeType, state)."""
    s = session or requests.Session()
    size = os.path.getsize(path)
    head = {"x-goog-api-key": api_key, "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime_type, "Content-Type": "application/json"}
    r = s.post(UPLOAD_URL, headers=head,
               json={"file": {"display_name": display_name or os.path.basename(path)[:120]}},
               timeout=(gemini_api.CONNECT_TIMEOUT, 60))
    _check(r, "начало загрузки")
    url = r.headers.get("x-goog-upload-url", "")
    # Адрес загрузки приходит от сервера — отправлять тело можно только к нему же.
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != _HOST:
        raise GeminiFileError("File API: неожиданный адрес загрузки")

    def body():
        with open(path, "rb") as f:
            while True:
                if stopped and stopped():
                    raise gemini_api.GeminiError("Отменено")
                chunk = f.read(_CHUNK)
                if not chunk:
                    return
                yield chunk

    r = s.post(url, headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                             "X-Goog-Upload-Command": "upload, finalize"},
               data=body(), timeout=(gemini_api.CONNECT_TIMEOUT, timeout))
    _check(r, "загрузка")
    info = r.json().get("file") or {}
    if not info.get("name") or not info.get("uri"):
        raise GeminiFileError("File API: в ответе нет файла")
    return info


def wait_active(api_key: str, name: str, session: Optional[requests.Session] = None,
                timeout: float = 600.0, stopped: Optional[Callable[[], bool]] = None) -> dict:
    """Ждёт state ACTIVE (видео обрабатывается сервером), FAILED — ошибка."""
    s = session or requests.Session()
    deadline = time.monotonic() + timeout
    while True:
        r = s.get(f"{gemini_api.API_ROOT}/{name}", headers={"x-goog-api-key": api_key},
                  timeout=(gemini_api.CONNECT_TIMEOUT, 60))
        _check(r, "состояние")
        info = r.json()
        state = info.get("state")
        if state == "ACTIVE":
            return info
        if state == "FAILED":
            raise GeminiFileError(f"File API: сервер не обработал {name}")
        if time.monotonic() > deadline:
            raise GeminiFileError(f"File API: {name} не готов за {timeout:.0f} с")
        if stopped and stopped():
            raise gemini_api.GeminiError("Отменено")
        time.sleep(3)


def delete_file(api_key: str, name: str, session: Optional[requests.Session] = None) -> None:
    """Удаляет загруженный файл (иначе он живёт 48 часов); сбой — не ошибка."""
    s = session or requests.Session()
    try:
        s.delete(f"{gemini_api.API_ROOT}/{name}", headers={"x-goog-api-key": api_key},
                 timeout=(gemini_api.CONNECT_TIMEOUT, 30))
    except requests.RequestException:
        pass
