# -*- coding: utf-8 -*-
"""OCR названия арта Pixiv и семантическая проверка через Gemini."""
from __future__ import annotations

import base64
import hashlib

from .visual_batch import request


SCHEMA = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "has_title_text": {"type": "boolean"},
        "mixed_anime": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["accept", "has_title_text", "mixed_anime", "reason"],
}


def check(generator, cand, data: bytes, ext: str, illust=None):
    mode = getattr(getattr(generator, "s", None), "pixiv_title_check_mode", "gemini")
    if mode != "local":
        return _gemini_check(generator, cand, data, ext, illust)
    from .local_title_match import decide, titles
    from .local_visual_ocr import note, read
    mixed_check = bool(getattr(generator.s, "pixiv_gemini_check", True))

    try:
        rows, elapsed, cached = read(generator, data)
    except Exception as exc:
        if (generator.stopped() or not mixed_check
                or getattr(generator, "gemini_pixiv", None) is None):
            raise
        note(generator, "Pixiv", {"status": "uncertain", "ocr": "",
                                   "title": "", "similarity": 0,
                                   "confidence": 0}, 0.0, False, True)
        generator.log(f"OCR Pixiv недоступен ({exc}) — проверяю через Gemini")
        return _gemini_check(generator, cand, data, ext, illust)
    result = decide(rows, titles(cand.anime or {}))
    fallback = (mixed_check and result["status"] == "uncertain"
                and getattr(generator, "gemini_pixiv", None) is not None)
    note(generator, "Pixiv", result, elapsed, cached, fallback)
    if result["status"] == "title":
        return False, f"OCR: «{result['ocr']}» = «{result['title']}»"
    if result["status"] == "uncertain":
        if fallback:
            return _gemini_check(generator, cand, data, ext, illust)
        return False, "OCR распознал возможное название"
    if mixed_check:
        return _gemini_check(generator, cand, data, ext, illust,
                             mixed_only=True)
    return True, ""


def _gemini_check(generator, cand, data: bytes, ext: str, illust=None, *,
                  mixed_only=False):
    """Возвращает ``(можно_брать, причина)``; результат хранится в базе."""
    client = getattr(generator, "gemini_pixiv", None)
    if client is None:
        raise RuntimeError("клиент Gemini для Pixiv не создан")
    model = str(getattr(client, "model", "") or "default")
    digest = hashlib.sha256(data).hexdigest()

    anime = cand.anime or {}
    titles = []
    for name in (anime.get("russian"), anime.get("name"),
                 anime.get("english"), anime.get("japanese"),
                 *(anime.get("synonyms") or [])):
        text = " ".join(str(name or "").split())
        if text and text.casefold() not in {x.casefold() for x in titles}:
            titles.append(text)
    tags = sorted(_tags(illust))
    prompt = (
        "Проверь фан-арт для вопроса по аниме. Ожидаемое аниме: "
        + " / ".join(titles) + ".\nМетки Pixiv: " + ", ".join(tags)
        + ("\nНаличие названия ожидаемого аниме уже проверено локальным OCR. "
           "Проверяй только чужие франшизы; has_title_text=false. "
           "Здесь accept=false означает только чужую франшизу. "
           if mixed_only else
           "\nВерни accept=false и has_title_text=true, если видно название "
           "или логотип ожидаемого аниме. ")
        + "Верни accept=false и mixed_anime=true, если изображены "
          "узнаваемые персонажи, логотипы или названия любого другого аниме "
          "либо смешаны несколько тайтлов. Обычные подписи автора и текст, "
          "не раскрывающий название, допустимы. Если метки явно называют "
          "другое исходное произведение, в том числе игру, верни accept=false "
          "даже при совпадении общей метки названия. Оцени само изображение, "
          "а метки используй как дополнительное доказательство. Причину напиши "
          "кратко по-русски.")
    key = f"{model}:{digest}:{hashlib.sha256(prompt.encode()).hexdigest()}"
    cached = generator.db_cache.memo("pixiv_visual_v2", key)
    if isinstance(cached, dict) and "accept" in cached:
        return bool(cached["accept"]), str(cached.get("reason") or "")
    from .manga_visual_check import _prepare
    mime, payload = _prepare(data, ext)
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image", "mime_type": mime,
         "data": base64.b64encode(payload).decode("ascii")},
    ]
    verdict = request(generator, client, parts, SCHEMA)
    if not isinstance(verdict, dict):
        verdict = {"accept": False, "mixed_anime": True,
                   "reason": "Gemini не вернула вердикт"}
    accept = ((verdict.get("accept") is True and
               verdict.get("mixed_anime") is False) if mixed_only else
              bool(verdict.get("accept"))
              and not bool(verdict.get("has_title_text"))
              and not bool(verdict.get("mixed_anime")))
    saved = {"accept": accept,
             "has_title_text": (False if mixed_only else
                                bool(verdict.get("has_title_text"))),
             "mixed_anime": bool(verdict.get("mixed_anime")),
             "reason": str(verdict.get("reason") or "")}
    generator.db_cache.remember_memo("pixiv_visual_v2", key, saved)
    return accept, saved["reason"]


def _field(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _tags(illust) -> set[str]:
    out = set()
    for row in (_field(illust, "tags", []) or []):
        for name in ("name", "translated_name"):
            value = " ".join(str(_field(row, name, "") or "").split())
            if value:
                out.add(value)
    return out


def _mime(ext: str) -> str:
    value = str(ext or "").lower().lstrip(".")
    if value == "jpg":
        value = "jpeg"
    return "image/" + (value if value in {"jpeg", "png", "webp", "gif"}
                       else "jpeg")
