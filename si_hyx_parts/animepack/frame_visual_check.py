# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Проверка исходного кадра и выбор замены без надписи с ответом."""
from __future__ import annotations

import base64
import hashlib

import animepack as api
from gemini_api import GeminiAuthError, GeminiDownError, GeminiError, GeminiQuotaError
from .manga_visual_check import _prepare, titles
from .visual_batch import request

FRAME_TRIES = 6
SCHEMA = {
    "type": "object", "properties": {
        "accept": {"type": "boolean"},
        "has_title_text": {"type": "boolean"},
        "has_characters": {"type": "boolean"},
        "reason": {"type": "string"},
    }, "required": ["accept", "has_title_text", "has_characters", "reason"],
}


def enabled(settings, kind):
    field = "pixel_gemini_check" if kind == api.PIXEL_KIND else "frame_gemini_check"
    return bool(getattr(settings, field, False))


def _valid(verdict):
    return (isinstance(verdict, dict)
            and all(type(verdict.get(key)) is bool
                    for key in ("accept", "has_title_text", "has_characters"))
            and isinstance(verdict.get("reason"), str))


def check(generator, candidate, data, ext):
    client = getattr(generator, "gemini_frames", None)
    if client is None:
        raise GeminiAuthError("Клиент Gemini для кадров недоступен")
    prompt = (
        "Проверь исходный кадр аниме для вопроса «угадай тайтл». Названия тайтла: "
        + " / ".join(titles(candidate.anime or {}))
        + ". Верни has_title_text=true и accept=false, если прямо на изображении "
          "видно название или логотип этого тайтла на любом языке. Обычные реплики "
          "субтитров, имена персонажей и подписи, не раскрывающие название, допустимы. "
          "Независимо от надписей определи has_characters: true, если в кадре виден "
          "хотя бы один персонаж (включая животных, существ, силуэты и фоновых героев); "
          "false, если показаны только пейзаж, здания, предметы или текст. "
          "Отсутствие персонажей само по себе не причина отказа: accept=true, "
          "если названия нет. Причину напиши кратко по-русски.")
    digest = hashlib.sha256(data).hexdigest()
    key = (f"{getattr(client, 'model', 'default')}:{digest}:"
           f"{hashlib.sha256(prompt.encode()).hexdigest()}")
    cached = generator.db_cache.memo("frame_visual_v1", key)
    if _valid(cached):
        return cached
    mime, payload = _prepare(data, ext)
    verdict = request(generator, client, [
        {"type": "text", "text": prompt},
        {"type": "image", "mime_type": mime,
         "data": base64.b64encode(payload).decode("ascii")},
    ], SCHEMA)
    if not _valid(verdict):
        raise GeminiError("Gemini вернула неверный вердикт кадра")
    saved = {key: verdict[key] for key in SCHEMA["required"]}
    saved["accept"] = saved["accept"] and not saved["has_title_text"]
    generator.db_cache.remember_memo("frame_visual_v1", key, saved)
    return saved


def select(generator, candidate):
    """Возвращает байты и расширение проверенного кадра, либо None."""
    candidate.frame_has_characters = None
    checking = enabled(generator.s, candidate.kind)
    attempted = set()
    for _ in range(FRAME_TRIES if checking else 1):
        if generator.stopped():
            return None
        url = generator._pick_frame_url(candidate)
        if not url:
            break
        identity = api.frame_url_key(url)
        if identity in attempted:
            continue
        attempted.add(identity)
        try:
            data = generator._cached_bytes(url, "anime-frame")
            ext = generator._url_ext(url)
        except Exception as error:  # noqa: BLE001 — пробуем другой кадр
            generator.log(f"Кадр «{candidate.title_ru}» не скачался: {error}")
            continue
        if checking:
            try:
                verdict = check(generator, candidate, data, ext)
            except (GeminiAuthError, GeminiQuotaError, GeminiDownError) as error:
                generator.gemini_frames = None
                generator.log(f"Проверка кадров Gemini недоступна ({error}); "
                              "кадры с включённой проверкой пропускаются.")
                for kind in api.FRAME_KINDS:
                    if enabled(generator.s, kind):
                        generator._drop_kind(kind)
                return None
            except Exception as error:  # noqa: BLE001 — без дорогих повторов
                generator._log_rare("Проверка кадра Gemini", str(error))
                return None
            if not verdict["accept"]:
                generator._log_rare("Кадр с названием", f"«{candidate.title_ru}»: "
                                    f"{verdict['reason']} — беру другой кадр")
                continue
            candidate.frame_has_characters = verdict["has_characters"]
        candidate.frame_url = url
        return data, ext
    generator._log_rare("Нет подходящих кадров", f"«{candidate.title_ru}»: "
                        "свободных кадров без названия нет — беру следующий тайтл")
    return None
