"""Inspect the encoded clip, rather than inferring speech/captions from a URL."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from .episode_caption_policy import mode
from .episode_caption_text import russian

MAX_BYTES = 8 * 1024 * 1024
# Каждый какой ролик с синхронной дорожкой субтитров всё же смотрит модель.
SYNC_SAMPLE = 3
SCHEMA = {"type": "object", "properties": {
    "segment": {"type": "string", "enum": ["scene", "opening", "ending", "credits", "title_card", "uncertain"]},
    "speech": {"type": "string", "enum": ["dialogue", "song", "none", "uncertain"]},
    "audio_language": {"type": "string", "enum": ["ja", "other", "uncertain"]},
    "spoken_lines": {"type": "integer"}, "dialogue_seconds": {"type": "number"},
    "spoken_example": {"type": "string"},
    "subtitle_language": {"type": "string", "enum": ["ru", "en", "none", "other", "uncertain"]},
    "visible_example": {"type": "string"},
    "additional_subtitle_language": {"type": "string", "enum": ["none", "ru", "en", "other", "uncertain"]},
    "additional_subtitle_example": {"type": "string"},
    "sync": {"type": "string", "enum": ["ok", "mismatch", "absent", "uncertain"]},
    "meaning_matches": {"type": "boolean"}, "wrong_title": {"type": "boolean"},
    "reason": {"type": "string"}}, "required": [
        "segment", "speech", "audio_language", "spoken_lines", "dialogue_seconds",
        "spoken_example", "subtitle_language", "visible_example", "additional_subtitle_language",
        "additional_subtitle_example", "sync",
        "meaning_matches", "wrong_title", "reason"]}

PROMPT = (
    "Проверь именно готовое 15-секундное видео. Нужна сцена серии с японским "
    "разговором, не OP/ED, титры, заставка названия, песня или одни звуковые эффекты. "
    "Посчитай слышимые реплики и примерную длительность разговора. В spoken_example "
    "приведи реально услышанную реплику ЯПОНСКИМ ПИСЬМОМ. Определи язык реально "
    "ВИДИМЫХ субтитров. В visible_example точно перепиши одну строку с видео: "
    "нельзя переводить её при переписывании. Если поверх/рядом есть второй слой "
    "сабов, укажи additional_subtitle_language и точно процитируй его; иначе none и пустую строку. "
    "Надписи, сообщения телефона и "
    "японские звуковые эффекты внутри оригинального рисунка не считаются отдельной "
    "дорожкой иностранных сабов. Проверь синхронность (до 0.5 с) и смысл перевода. "
    "Отсечённая границей ролика фраза допустима. Если явно узнаёшь другое аниме, "
    "wrong_title=true; неугадываемый по короткой сцене тайтл не означает подмену. "
    "Нельзя объявлять русские сабы, процитировав английскую строку. При сомнении "
    "используй uncertain и объясни наблюдение в reason."
)


def expected(candidate, stream):
    """Кого ждём в ролике: русское и оригинальные названия, MAL/AniList, серия.

    По одному русскому «Сверхкуб» модель путала Super Cube (MAL 60057) с
    Super Cub; оригинальные названия и ID снимают такую неоднозначность."""
    card = getattr(candidate, "anime", None) or {}
    names = [str(card.get(key)).strip() for key in ("name", "english", "japanese") if card.get(key)]
    names = [name for name in dict.fromkeys(names) if name]
    ids = [f"MAL {candidate.mal_id}"]
    anilist = card.get("anilistId") or card.get("anilist_id")
    if anilist:
        ids.append(f"AniList {anilist}")
    year = getattr(candidate, "year", 0) or ""
    episode = stream.get("episode")
    return (f"Ожидаемый тайтл: «{candidate.title_ru}»"
            + (f" ({'; '.join(names)})" if names else "")
            + f", {', '.join(ids)}" + (f", {year} г." if year else "")
            + (f", серия {episode}." if episode else "."))


def verdict(value):
    """Вердикт модели целиком, со строками ограниченной длины."""
    if not isinstance(value, dict):
        return {"invalid": str(value)[:300]}
    return {key: (re.sub(r"https?://\S+", "[URL]", item)[:300] if isinstance(item, str) else item)
            for key, item in value.items() if key in SCHEMA["properties"]}


def initialize(generator):
    generator._episode_scene_deadlines = threading.local()
    generator._episode_scene_cache = {}
    generator._episode_scene_cache_lock = threading.Lock()
    client = getattr(generator, "gemini_episode", None)
    if client is not None and hasattr(client, "stopped"):
        client.stopped = lambda: (generator.stopped() or time.monotonic() >= getattr(
            generator._episode_scene_deadlines, "deadline", float("inf")))


def accepted(value, requested):
    if not isinstance(value, dict) or not set(SCHEMA["required"]).issubset(value):
        return False
    if type(value["wrong_title"]) is not bool or type(value["meaning_matches"]) is not bool:
        return False
    if (value["segment"] != "scene" or value["speech"] != "dialogue"
            or value["audio_language"] != "ja" or value["wrong_title"]):
        return False
    if (type(value["spoken_lines"]) is not int or type(value["dialogue_seconds"]) not in (int, float)
            or not 0 <= value["dialogue_seconds"] <= 15 or value["spoken_lines"] < 0):
        return False
    if value["spoken_lines"] < 2 and value["dialogue_seconds"] < 3:
        return False
    if not isinstance(value["spoken_example"], str) or not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", value["spoken_example"]):
        return False
    lang, example = value["subtitle_language"], value["visible_example"]
    if not isinstance(example, str) or not isinstance(value["reason"], str):
        return False
    if lang == "ru" and not russian(example):
        return False
    if lang == "en" and (russian(example) or not re.search("[a-zA-Z]", example)):
        return False
    if lang not in ("ru", "en", "none"):
        return False
    extra = value["additional_subtitle_language"]
    if (extra not in ("none", "ru", "en") or not isinstance(value["additional_subtitle_example"], str)
            or (extra != "none" and extra != lang)):
        return False
    if requested == "required" and lang != "ru":
        return False
    if requested == "preferred" and lang not in ("ru", "en"):
        return False
    if requested == "none" and lang == "ru":
        return False
    return lang == "none" or (value["sync"] == "ok" and value["meaning_matches"])


def video_input(generator, video, scope):
    if video.stat().st_size <= MAX_BYTES:
        return video.read_bytes()
    import animepack as api
    preview = video.with_suffix(".scene-check.mp4")
    try:
        code, _error = generator._run_killable([
            api.FFMPEG, "-v", "error", "-y", "-i", str(video), "-t", "15", "-vf",
            "scale=-2:480", "-r", "12", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "24", "-c:a", "aac", "-b:a", "96k", str(preview)],
            timeout=min(40, max(1, scope.deadline - time.monotonic())))
        if code == 0 and preview.is_file() and 0 < preview.stat().st_size <= MAX_BYTES:
            return preview.read_bytes()
        return None
    finally:
        preview.unlink(missing_ok=True)


def sampled_out(generator, stream):
    """Ролик с субтитрами из синхронной дорожки проверяется выборочно.

    Окно уже выбрано по самой дорожке: в нём есть реплики (dialogue_window),
    OP/ED исключены (choose_start), тайминги — от релиза, а не от догадки.
    Модель тут ловит только чужой тайтл или озвучку вместо японской речи —
    поэтому у каждого провайдера проверяется первый такой ролик и затем каждый
    SYNC_SAMPLE-й (в прогоне на это уходило 28 запросов). Ослабляет защиту
    от подмены тайтла — так решил пользователь."""
    if not stream.get("_captions_burned") or not stream.get("_ru_cues"):
        return False
    # После отказа модели тот же поток дальше смотрится каждый раз.
    if stream.get("audio") != "sub" or stream.get("_scene_rejected"):
        return False
    lock = getattr(generator, "_episode_scene_cache_lock", None)
    if lock is None:
        initialize(generator)
        lock = generator._episode_scene_cache_lock
    with lock:
        seen = generator.__dict__.setdefault("_episode_sync_seen", {})
        provider = str(stream.get("provider") or "")
        count = seen.get(provider, 0)
        seen[provider] = count + 1
    return count % SYNC_SAMPLE != 0


def check(generator, candidate, stream, final, scope):
    if not getattr(generator.s, "episode_scene_check", True):
        return True
    if sampled_out(generator, stream):
        stream["_captions_confirmed"] = True
        stream["_scene_sampled_out"] = True
        return True
    client = getattr(generator, "gemini_episode", None) or generator.gemini
    if client is None or generator.stopped() or time.monotonic() >= scope.deadline:
        return False
    video = Path(final)
    if not video.is_file() or video.stat().st_size <= 0:
        return False
    data = video_input(generator, video, scope)
    if not data:
        generator.log(f"Проверка сцены {stream['provider']}: не удалось подготовить видео для проверки.")
        return False
    requested = mode(generator.s)
    key = (candidate.mal_id, requested, hashlib.sha256(data).hexdigest())
    lock = getattr(generator, "_episode_scene_cache_lock", None)
    if lock is None:
        initialize(generator)
        lock = generator._episode_scene_cache_lock
    with lock:
        value = generator._episode_scene_cache.get(key)
    try:
        if value is None:
            generator._episode_scene_deadlines.deadline = scope.deadline
            parts = [{"type": "video", "data": base64.b64encode(data).decode("ascii"), "mime_type": "video/mp4"},
                     {"type": "text", "text": PROMPT + "\n" + expected(candidate, stream) + f" Режим: {requested}."}]
            from .generation_diagnostics import measuring
            with measuring(generator, "проверка сцены моделью"):
                value = client.generate_json(parts, SCHEMA)
            if generator.stopped() or time.monotonic() >= scope.deadline:
                return False
            with lock:
                if len(generator._episode_scene_cache) >= 128:
                    generator._episode_scene_cache.clear()
                generator._episode_scene_cache[key] = value
        if not accepted(value, requested):
            reason = value.get("reason", "неверный вердикт") if isinstance(value, dict) else "неверный вердикт"
            languages = {"ru": "русские", "en": "английские", "none": "нет", "other": "другой язык", "uncertain": "не определены"}
            observed = languages.get(value.get("subtitle_language"), "не определены") if isinstance(value, dict) else "не определены"
            generator.log(f"Сцена {stream['provider']} / «{candidate.title_ru}»: отклонена; сабы: {observed}. "
                          + re.sub(r"https?://\S+", "[URL]", str(reason))[:180]
                          + " Вердикт: " + json.dumps(verdict(value), ensure_ascii=False))
            complete = isinstance(value, dict) and set(SCHEMA["required"]).issubset(value)
            # Чужой язык или другой тайтл не исправить другим участком того же
            # потока: раньше это стоило до трёх лишних кодирований AV1.
            foreign = complete and (value.get("wrong_title") is True or value.get("audio_language") == "other")
            stream["_scene_retry"] = complete and not foreign
            stream["_scene_rejected"] = True
            stream["_scene_switch"] = foreign
            return False
        lang = value["subtitle_language"]
        stream["_caption_output_language"] = lang if lang != "none" else ""
        stream["_captions_confirmed"] = lang in ("ru", "en")
        if not stream.get("_captions_burned"):
            stream["_observed_hardsub"] = lang in ("ru", "en")
        # Полный структурированный вердикт, а не одна усечённая причина.
        stream["_scene_check"] = verdict(value)
        return True
    except Exception as error:
        from .episode_generation import error_text
        generator.log(f"Проверка сцены {stream['provider']}: {type(error).__name__}: {error_text(error)}")
        stream["_scene_retry"] = False
        return False
    finally:
        generator._episode_scene_deadlines.deadline = float("inf")
