# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Визуальная проверка страницы манги через Gemini.

Как у артов Pixiv (pixiv_visual_check): страница, на которой видно название
самой манги — титул главы, колонтитул, логотип, страница переводчиков, — сразу
раскрывает ответ. Такая страница отклоняется, и берётся другая страница той же
манги (manga_panel). Вердикт хранится в базе по модели и содержимому картинки.
"""
from __future__ import annotations

import base64
import hashlib
import io

from .visual_batch import request

SCHEMA = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "has_title_text": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["accept", "has_title_text", "reason"],
}
MEMO_GROUP = "manga_visual_v1"
# Страница уходит в Gemini уменьшенной: разворот в исходном качестве весит
# мегабайты, а читать надписи хватает и полутора тысяч пикселей.
_SEND_SIDE = 1600


def check(generator, cand, data: bytes, ext: str):
    """Возвращает ``(можно_брать, причина)``; результат хранится в базе."""
    client = getattr(generator, "gemini_manga", None)
    if client is None:
        raise RuntimeError("клиент Gemini для манги не создан")
    model = str(getattr(client, "model", "") or "default")
    key = f"{model}:{hashlib.sha256(data).hexdigest()}"
    cached = generator.db_cache.memo(MEMO_GROUP, key)
    if isinstance(cached, dict) and "accept" in cached:
        return bool(cached["accept"]), str(cached.get("reason") or "")

    prompt = (
        "Это страница манги для вопроса викторины «угадай мангу по странице». "
        "Ожидаемая манга: " + " / ".join(titles(cand.anime or {})) + ".\n"
        "Верни has_title_text=true и accept=false, если на странице где угодно "
        "видно название этой манги — на любом языке и в любом написании: "
        "титул главы, колонтитул, логотип, обложка, страница с титрами "
        "переводчиков или реклама с названием. Это раскрывает ответ. "
        "Имена персонажей, реплики, звуки и номер главы без названия "
        "допустимы. Причину напиши кратко по-русски.")
    mime, payload = _prepare(data, ext)
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image", "mime_type": mime,
         "data": base64.b64encode(payload).decode("ascii")},
    ]
    verdict = request(generator, client, parts, SCHEMA)
    if not isinstance(verdict, dict):
        verdict = {"accept": False, "reason": "Gemini не вернула вердикт"}
    accept = (bool(verdict.get("accept"))
              and not bool(verdict.get("has_title_text")))
    saved = {"accept": accept,
             "has_title_text": bool(verdict.get("has_title_text")),
             "reason": str(verdict.get("reason") or "")}
    generator.db_cache.remember_memo(MEMO_GROUP, key, saved)
    return accept, saved["reason"]


def titles(card: dict) -> list[str]:
    """Все названия тайтла без повторов: русское, ромадзи, английское…"""
    out: list[str] = []
    seen: set[str] = set()
    for name in (card.get("russian"), card.get("name"), card.get("english"),
                 card.get("japanese"), *(card.get("synonyms") or [])):
        items = name if isinstance(name, (list, tuple)) else [name]
        for item in items:
            text = " ".join(str(item or "").split())
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                out.append(text)
    return out


def _prepare(data: bytes, ext: str) -> tuple[str, bytes]:
    """(MIME, байты) для отправки: большую страницу — уменьшенным JPEG."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as opened:
            if max(opened.size) <= _SEND_SIDE and len(data) <= 2_000_000:
                return _mime(ext), data
            picture = opened.convert("RGB")
        picture.thumbnail((_SEND_SIDE, _SEND_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        picture.save(out, "JPEG", quality=90)
        return "image/jpeg", out.getvalue()
    except Exception:  # noqa: BLE001 — нечитаемое отдаём как есть
        return _mime(ext), data


def _mime(ext: str) -> str:
    value = str(ext or "").lower().lstrip(".")
    if value == "jpg":
        value = "jpeg"
    return "image/" + (value if value in {"jpeg", "png", "webp", "gif"}
                       else "jpeg")
