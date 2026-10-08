# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Проверка исходного кадра и выбор замены без надписи с ответом."""
from __future__ import annotations

import base64
import hashlib

import animepack as api
from gemini_api import (GeminiAuthError, GeminiCoolingError, GeminiDownError, GeminiError,
                        GeminiQuotaError)
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
    if kind == api.STUDIO_KIND:
        return True
    field = "pixel_gemini_check" if kind == api.PIXEL_KIND else "frame_gemini_check"
    return bool(getattr(settings, field, False))


def _valid(verdict):
    return (isinstance(verdict, dict)
            and all(type(verdict.get(key)) is bool
                    for key in ("accept", "has_title_text", "has_characters"))
            and isinstance(verdict.get("reason"), str))


def check(generator, candidate, data, ext, *, purpose="проверка кадров", max_images=None):
    client = getattr(generator, "gemini_frames", None)
    if client is None:
        raise GeminiAuthError("Клиент Gemini для кадров недоступен")
    studio = candidate.kind == api.STUDIO_KIND
    prompt = (
        ("Проверь кадр аниме для вопроса «назовите студию». Названия тайтла: "
         if studio else
         "Проверь исходный кадр аниме для вопроса «угадай тайтл». Названия тайтла: ")
        + " / ".join(titles(candidate.anime or {}))
        + ". Верни has_title_text=true и accept=false, если прямо на изображении "
          "видно название или логотип этого тайтла на любом языке. Обычные реплики "
          "субтитров, имена персонажей и подписи, не раскрывающие название, допустимы. "
          "Независимо от надписей определи has_characters: true, если в кадре виден "
          "хотя бы один персонаж (включая животных, существ, силуэты и фоновых героев); "
          "false, если показаны только пейзаж, здания, предметы или текст. "
        + ("Кадр студии должен показывать персонажей: accept=false, если "
           "has_characters=false; пейзажи и пустые сцены не подходят. "
           if studio else
           "Отсутствие персонажей само по себе не причина отказа: accept=true, "
           "если названия нет. ")
        + "Причину напиши кратко по-русски.")
    digest = hashlib.sha256(data).hexdigest()
    prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()
    lane = getattr(generator, "_visual_spare", None)
    models = [str(getattr(client, "model", "default"))]
    if lane is not None:
        models.append(str(lane.client.model))
    for model in models:
        cached = generator.db_cache.memo("frame_visual_v1", f"{model}:{digest}:{prompt_digest}")
        if _valid(cached):
            return cached
    mime, payload = _prepare(data, ext)
    parts = [{"type": "text", "text": prompt},
             {"type": "image", "mime_type": mime,
              "data": base64.b64encode(payload).decode("ascii")}]
    from .visual_spare import verdict as spare_verdict
    model = models[-1]
    verdict = spare_verdict(generator, client, parts, SCHEMA, _valid)
    if verdict is None:
        model = models[0]
        verdict = request(generator, client, parts, SCHEMA, purpose=purpose,
                          max_images=max_images)
    if not _valid(verdict):
        raise GeminiError("Gemini вернула неверный вердикт кадра")
    key = f"{model}:{digest}:{prompt_digest}"
    saved = {key: verdict[key] for key in SCHEMA["required"]}
    saved["accept"] = (saved["accept"] and not saved["has_title_text"]
                       and (not studio or saved["has_characters"]))
    generator.db_cache.remember_memo("frame_visual_v1", key, saved)
    return saved


def select(generator, candidate):
    """Возвращает байты и расширение проверенного кадра, либо None."""
    candidate.frame_has_characters = None
    checking = enabled(generator.s, candidate.kind)
    studio = candidate.kind == api.STUDIO_KIND
    attempted = set()
    downloaded = False
    for _ in range(FRAME_TRIES):
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
            downloaded = True
        except Exception as error:  # noqa: BLE001 — пробуем другой кадр
            generator.log(f"Кадр «{candidate.title_ru}» не скачался: {error}")
            continue
        if checking:
            try:
                verdict = check(generator, candidate, data, ext,
                                purpose="кадры студий" if studio else "проверка кадров")
            except GeminiCoolingError as error:
                from .media_transfer import trouble_mark
                trouble_mark()      # тайтл уйдёт на повтор после паузы модели
                generator._log_rare("Проверка кадра Gemini", str(error))
                return None
            except (GeminiAuthError, GeminiQuotaError, GeminiDownError) as error:
                generator.gemini_frames = None
                generator.log(f"Проверка кадров Gemini недоступна ({error}); "
                              "кадры с включённой проверкой пропускаются.")
                for kind in api.FRAME_KINDS:
                    if enabled(generator.s, kind):
                        generator._drop_kind(kind)
                if studio or generator.s.mix_shares.get(api.STUDIO_KIND):
                    generator._drop_kind(api.STUDIO_KIND)
                return None
            except Exception as error:  # noqa: BLE001 — без дорогих повторов
                generator._log_rare("Проверка кадра Gemini", str(error))
                return None
            if not verdict["accept"] or (studio and not verdict["has_characters"]):
                category = "Кадр студии не подходит" if studio else "Кадр с названием"
                generator._log_rare(category, f"«{candidate.title_ru}»: "
                                    f"{verdict['reason']} — беру другой кадр")
                continue
            candidate.frame_has_characters = verdict["has_characters"]
        candidate.frame_url = url
        return data, ext
    reason = ("кадров с персонажами без названия нет" if studio and downloaded else
              "свободных кадров без названия нет" if checking and downloaded
              else "доступных кадров нет")
    generator._log_rare("Нет подходящих кадров", f"«{candidate.title_ru}»: "
                        f"{reason} — беру следующий тайтл")
    return None
