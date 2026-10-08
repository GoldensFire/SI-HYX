# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Проверка видимого названия манги через Gemini или локальный OCR.

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


def check(generator, cand, data: bytes, ext: str, *, manga_titles=()):
    """Use local OCR when selected, with Gemini for ambiguous lettering."""
    mode = getattr(getattr(generator, "s", None), "manga_title_check_mode", "gemini")
    if mode != "local":
        return _gemini_check(generator, cand, data, ext, manga_titles)
    from .local_title_match import decide, titles as all_titles
    from .local_visual_ocr import note, read

    try:
        rows, elapsed, cached = read(generator, data)
    except Exception as exc:
        if generator.stopped() or getattr(generator, "gemini_manga", None) is None:
            raise
        note(generator, "MangaDex", {"status": "uncertain", "ocr": "",
                                      "title": "", "similarity": 0,
                                      "confidence": 0}, 0.0, False, True)
        generator.log(f"OCR манги недоступен ({exc}) — проверяю через Gemini")
        return _gemini_check(generator, cand, data, ext, manga_titles)
    result = decide(rows, all_titles(cand.anime or {}, manga_titles))
    fallback = (result["status"] == "uncertain"
                and getattr(generator, "gemini_manga", None) is not None)
    note(generator, "MangaDex", result, elapsed, cached, fallback)
    if result["status"] == "title":
        return False, f"OCR: «{result['ocr']}» = «{result['title']}»"
    if result["status"] == "safe":
        return True, ""
    if fallback:
        return _gemini_check(generator, cand, data, ext, manga_titles)
    return False, "OCR распознал возможное название, нужна другая страница"


def _gemini_check(generator, cand, data: bytes, ext: str, manga_titles=()):
    """Возвращает ``(можно_брать, причина)``; результат хранится в базе."""
    client = getattr(generator, "gemini_manga", None)
    if client is None:
        raise RuntimeError("клиент Gemini для манги не создан")
    model = str(getattr(client, "model", "") or "default")
    prompt = (
        "Это страница манги для вопроса викторины «угадай мангу по странице». "
        "Ожидаемая манга: " + " / ".join(titles(cand.anime or {}) +
                                        list(manga_titles)) + ".\n"
        "Верни has_title_text=true и accept=false, если на странице где угодно "
        "видно название этой манги — на любом языке и в любом написании: "
        "титул главы, колонтитул, логотип, обложка, страница с титрами "
        "переводчиков или реклама с названием. Это раскрывает ответ. "
        "Имена персонажей, реплики, звуки и номер главы без названия "
        "допустимы. Причину напиши кратко по-русски.")
    digests = (f"{hashlib.sha256(data).hexdigest()}:"
               f"{hashlib.sha256(prompt.encode()).hexdigest()}")
    # Вердикт запасной Gemma годится так же, как вердикт основной модели.
    lane = getattr(generator, "_visual_spare", None)
    models = [model] + ([str(lane.client.model)] if lane is not None else [])
    for name in models:
        cached = generator.db_cache.memo(MEMO_GROUP, f"{name}:{digests}")
        if isinstance(cached, dict) and "accept" in cached:
            return bool(cached["accept"]), str(cached.get("reason") or "")
    mime, payload = _prepare(data, ext)
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image", "mime_type": mime,
         "data": base64.b64encode(payload).decode("ascii")},
    ]
    # Проверка простая, как у кадров: при занятой или перегруженной (503)
    # основной модели её берёт Gemma со своей квотой. В прогоне Flash-Lite
    # отказала 16 раз подряд, и хвост пака стоял на манге.
    from .visual_spare import verdict as spare_verdict
    verdict = spare_verdict(generator, client, parts, SCHEMA, _valid)
    if verdict is not None:
        model = models[-1]
    else:
        verdict = request(generator, client, parts, SCHEMA)
    key = f"{model}:{digests}"
    if not isinstance(verdict, dict):
        verdict = {"accept": False, "reason": "Gemini не вернула вердикт"}
    accept = (bool(verdict.get("accept"))
              and not bool(verdict.get("has_title_text")))
    saved = {"accept": accept,
             "has_title_text": bool(verdict.get("has_title_text")),
             "reason": str(verdict.get("reason") or "")}
    generator.db_cache.remember_memo(MEMO_GROUP, key, saved)
    return accept, saved["reason"]


def _valid(verdict) -> bool:
    return (isinstance(verdict, dict)
            and all(type(verdict.get(key)) is bool
                    for key in ("accept", "has_title_text"))
            and isinstance(verdict.get("reason"), str))


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
