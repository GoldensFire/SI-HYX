# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Cloudflare Workers AI image generation via REST, without a Worker."""
from __future__ import annotations

import base64
import binascii
import io
import re
import time

import requests
from PIL import Image

DEFAULT_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
MODELS = {
    DEFAULT_MODEL: "FLUX.2 Klein 4B",
    "@cf/black-forest-labs/flux-2-klein-9b": "FLUX.2 Klein 9B",
}
MODEL_HINTS = {
    DEFAULT_MODEL: "≈104 нейрона за арт 1024×1024 (1% дневной квоты).",
    "@cf/black-forest-labs/flux-2-klein-9b":
        "≈1364 нейрона за арт 1024×1024 (14% дневной квоты).",
}
MAX_IMAGE_BYTES = 16 * 1024 * 1024


class CloudflareArtError(Exception):
    """One image could not be generated."""


class CloudflareArtUnavailable(CloudflareArtError):
    """Do not keep spending requests on other titles in this run."""


class CloudflareArtCancelled(CloudflareArtError):
    """The user stopped generation."""


class CloudflareArtContentRejected(CloudflareArtError):
    """The provider rejected the input or exhausted output attempts."""


def validate_settings(account_id, token, model) -> list[str]:
    problems = []
    if not re.fullmatch(r"[a-fA-F0-9]{32}", str(account_id or "").strip()):
        problems.append("ИИ-арты: введите Account ID Cloudflare (32 символа) "
                        "в Настройках → Ключи API.")
    if not str(token or "").strip():
        problems.append("ИИ-арты: введите токен Cloudflare в Настройках → Ключи API.")
    if model not in MODELS:
        problems.append("ИИ-арты: выберите доступную модель Cloudflare.")
    return problems


def image_extension(data: bytes) -> str:
    """Validate the actual image, including cached files, before packaging."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise CloudflareArtError("Cloudflare вернул пустую или слишком большую картинку.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(im.format)
            if not ext or not (64 <= im.width <= 4096 and 64 <= im.height <= 4096):
                raise ValueError("unexpected image format or size")
            im.verify()
            return ext
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise CloudflareArtError("Cloudflare вернул повреждённую картинку.") from exc


class CloudflareArtClient:
    def __init__(self, account_id: str, token: str, *, model=DEFAULT_MODEL,
                 session=None, stopped=None, on_retry=None):
        self.account_id = str(account_id or "").strip()
        self.token = str(token or "").strip()
        self.model = model
        self.session = session if session is not None else requests.Session()
        self.stopped = stopped or (lambda: False)
        self.on_retry = on_retry or (lambda message: None)

    def check_cancelled(self):
        if self.stopped():
            raise CloudflareArtCancelled("Генерация ИИ-артов остановлена.")

    def _sleep(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check_cancelled()
            time.sleep(min(0.1, max(0, end - time.monotonic())))

    def generate(self, prompt: str, *, seed: int) -> tuple[bytes, str]:
        errors = validate_settings(self.account_id, self.token, self.model)
        if errors:
            raise CloudflareArtUnavailable(" ".join(errors))
        if not prompt or len(prompt) > 2048:
            raise CloudflareArtError("ИИ-арты: промпт пуст или длиннее 2048 символов.")
        url = (f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
               f"/ai/run/{self.model}")
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"files": {key: (None, str(value)) for key, value in
                             {"prompt": prompt, "width": 1024,
                              "height": 1024, "seed": seed}.items()}}
        for attempt in range(3):
            self.check_cancelled()
            try:
                response = self.session.post(url, headers=headers, timeout=(10, 90),
                                             allow_redirects=False, **payload)
            except requests.RequestException:
                # A timed-out generation may have already consumed quota.
                # Do not blindly submit the same paid operation again.
                raise CloudflareArtUnavailable(
                    "Cloudflare: соединение прервано или истекло время ожидания. "
                    "Генерация ИИ-артов в этом запуске остановлена.") from None
            try:
                self.check_cancelled()
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                errors = body.get("errors")
                errors = errors if isinstance(errors, list) else []
                codes = {str(row.get("code")) for row in errors
                         if isinstance(row, dict)}
                status = response.status_code
                if "3036" in codes:
                    raise CloudflareArtUnavailable(
                        "Cloudflare: бесплатная суточная квота ИИ-артов исчерпана. "
                        "Она обновляется в 00:00 UTC.")
                if status in (401, 403):
                    raise CloudflareArtUnavailable(
                        "Cloudflare: доступ отклонён. Проверьте Account ID, токен, "
                        "права Workers AI и доступность выбранной модели.")
                if status == 400 and "3030" in codes:
                    messages = [str(row.get("message", "")).lower()
                                for row in errors if isinstance(row, dict)
                                and str(row.get("code")) == "3030"]
                    # Output refusals also say "choose another prompt / input
                    # image combination". Those words alone are not an input
                    # refusal; look for an actual rejection of that subject.
                    input_rejected = any(re.search(
                        r"\b(?:input|prompt)\b[^.!?\n]{0,80}"
                        r"\b(?:flagged|nsfw|unsafe|rejected)\b", msg)
                        for msg in messages)
                    output_rejected = not input_rejected and any(
                        "output" in msg and "flagged" in msg for msg in messages)
                    if output_rejected and attempt < 2:
                        # The generated sample was rejected, not the prompt.
                        # A fresh sample keeps the provider's checks enabled.
                        # Share the same three-request budget with HTTP retries.
                        if "files" in payload:
                            payload = {"files": dict(payload["files"])}
                            payload["files"]["seed"] = (
                                None, str((int(seed) + attempt + 1) % (2**31)))
                        self.on_retry(
                            "Cloudflare отклонил готовую картинку (3030); "
                            f"новая генерация на {MODELS[self.model]} "
                            f"— попытка {attempt + 2}/3.")
                        continue
                    if input_rejected:
                        raise CloudflareArtContentRejected(
                            "Cloudflare отклонил промпт при проверке содержимого "
                            "(3030). Тайтл пропущен.")
                    if output_rejected:
                        raise CloudflareArtContentRejected(
                            "Cloudflare отклонил готовую картинку (3030); "
                            "лимит 3 попыток исчерпан. Тайтл пропущен.")
                if status == 429 or status >= 500:
                    if attempt == 2:
                        raise CloudflareArtUnavailable(
                            "Cloudflare временно недоступен или ограничил частоту запросов. "
                            "ИИ-арты в этом запуске остановлены.")
                    try:
                        delay = float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
                    except (TypeError, ValueError):
                        delay = 2 ** (attempt + 1)
                    self._sleep(min(60, max(1, delay)))
                    continue
                if status != 200 or body.get("success") is False:
                    # Do not put server text or request headers in the log: they
                    # may contain credentials. HTTP/code identify the failure.
                    code = ", ".join(sorted(c for c in codes if c.isdigit()))
                    raise CloudflareArtUnavailable(
                        f"Cloudflare отклонил запрос ИИ-арта (HTTP {status}"
                        f"{', код ' + code if code else ''}).")
                result = body.get("result")
                encoded = result.get("image") if isinstance(result, dict) else None
                if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 2:
                    raise CloudflareArtError("Cloudflare не вернул изображение.")
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise CloudflareArtError("Cloudflare вернул неверные данные картинки.") from None
                return data, image_extension(data)
            finally:
                response.close()
        raise CloudflareArtUnavailable("Cloudflare недоступен.")
