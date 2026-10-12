"""One bounded image attempt, independent of the API session's retry adapters."""
import time

import requests
from network_attempt import single_attempt_session

MAX_IMAGE_BYTES = 64 * 1024 * 1024


def download(session, url, referer, *, clock=time.monotonic):
    deadline = clock() + 20
    with single_attempt_session(session) as client:
        response = client.get(url, headers={"Referer": referer,
            "Accept": "image/avif,image/webp,*/*"}, timeout=(5, 10), stream=True)
        try:
            if getattr(response, "status_code", 200) >= 400:
                _mark_geoblock(response)
            response.raise_for_status()
            declared = (getattr(response, "headers", {}) or {}).get("Content-Length", "")
            if str(declared).isdecimal() and int(declared) > MAX_IMAGE_BYTES:
                raise ValueError("Страница манги превышает 64 МиБ.")
            body = bytearray()
            chunks = response.iter_content(128 * 1024) if hasattr(response, "iter_content") else [response.content]
            for chunk in chunks:
                if clock() >= deadline:
                    raise requests.Timeout("Истёк общий срок загрузки страницы манги.")
                if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                    raise ValueError("Страница манги превышает 64 МиБ.")
                body.extend(chunk)
            return bytes(body)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()


def _mark_geoblock(response):
    """Геоблок DDoS-Guard отличается от проверки «вы не бот» только страницей
    (пара КБ): IP вне СНГ закрыт у CDN ReManga насовсем, и пишем об этом прямо."""
    try:
        chunks = response.iter_content(8192) if hasattr(response, "iter_content") else [response.content]
        chunk = next(iter(chunks), b"") or b""
    except Exception:  # noqa: BLE001 — без тела останется общий ответ «стена»
        return
    response.si_hyx_geoblocked = (b"ddos-guard/geoblocked" in chunk
                                  or b"restricted access from your current IP" in chunk)
