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
