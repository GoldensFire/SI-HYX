# -*- coding: utf-8 -*-
"""Визуальная проверка арта Pixiv через Gemini."""
from __future__ import annotations

import base64
import hashlib


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
    """Возвращает ``(можно_брать, причина)``; результат хранится в базе."""
    client = getattr(generator, "gemini_pixiv", None)
    if client is None:
        raise RuntimeError("клиент Gemini для Pixiv не создан")
    model = str(getattr(client, "model", "") or "default")
    digest = hashlib.sha256(data).hexdigest()
    key = f"{model}:{digest}"
    cached = generator.db_cache.memo("pixiv_visual_v1", key)
    if isinstance(cached, dict) and "accept" in cached:
        return bool(cached["accept"]), str(cached.get("reason") or "")

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
        + "\nВерни accept=false, если на изображении видны название, логотип "
          "или надпись с названием ожидаемого аниме: это раскрывает ответ. "
          "Также верни accept=false и mixed_anime=true, если изображены "
          "узнаваемые персонажи, логотипы или названия любого другого аниме "
          "либо смешаны несколько тайтлов. Обычные подписи автора и текст, "
          "не раскрывающий название, допустимы. Оцени само изображение, а "
          "метки используй как дополнительное доказательство. Причину напиши "
          "кратко по-русски.")
    mime = _mime(ext)
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image", "mime_type": mime,
         "data": base64.b64encode(data).decode("ascii")},
    ]
    verdict = client.generate_json(parts, SCHEMA, temperature=0.0)
    if not isinstance(verdict, dict):
        verdict = {"accept": False, "reason": "Gemini не вернула вердикт"}
    accept = (bool(verdict.get("accept"))
              and not bool(verdict.get("has_title_text"))
              and not bool(verdict.get("mixed_anime")))
    saved = {"accept": accept,
             "has_title_text": bool(verdict.get("has_title_text")),
             "mixed_anime": bool(verdict.get("mixed_anime")),
             "reason": str(verdict.get("reason") or "")}
    generator.db_cache.remember_memo("pixiv_visual_v1", key, saved)
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
