"""Caption policy and timed tracks belonging to the selected video."""
from __future__ import annotations

from pathlib import Path
import re
import time

import animepack as api
from .episode_caption_text import cropped, parse, russian
from .episode_media import number, video_track
from .episode_sources import choose_start, hard_subbed
from .episode_subtitles import srt, TRANSLATION_SCHEMA
from .episode_caption_policy import mode, dialogue_window
from .generation_diagnostics import measuring


def language(row):
    value = " ".join(str(row.get(k) or "") for k in ("srclang", "language", "label", "name"))
    if re.search(r"\b(ru|rus|russian)\b|русск", value, re.I):
        return "ru"
    if re.search(r"\b(en|eng|english)\b", value, re.I):
        return "en"
    declared = str(row.get("srclang") or row.get("language") or "").casefold().split("-")[0]
    return declared if declared in ("ar", "ja", "zh", "fr", "de", "es", "pt") else "und"


def wanted(generator, stream):
    return mode(generator.s) != "none"


def allowed(generator, stream):
    if not hard_subbed(stream):
        return True
    lang, requested = hard_language(stream), mode(generator.s)
    if requested == "none":
        return lang != "ru"
    return lang == "ru" if requested == "required" else lang in ("ru", "en", "und")


def hard_language(stream):
    if stream.get("ru_subtitles"):
        return "ru"
    explicit = stream.get("subtitle_language") or stream.get("subtitleLanguage")
    if explicit:
        return language({"language": explicit})
    return "und"


def load(generator, stream, scope):
    client = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
    tracks = sorted(stream.get("subtitles") or [],
                    key=lambda row: (language(row) != "ru", language(row) != "en"))
    for track in tracks:
        if generator.stopped() or time.monotonic() >= scope.deadline:
            break
        try:
            selected = {**stream, "subtitles": [track]}
            with measuring(generator, "загрузка субтитров"):
                files = client.captions(selected, scope)
            for data, name in files:
                lang = language(track)
                if lang == "und" and stream.get("ru_subtitles"):
                    lang = "ru"
                rows = parse(data, name, ru=lang == "ru")
                if rows:
                    text = " ".join(row[2] for row in rows)
                    if russian(text):
                        lang = "ru"
                    elif len(re.findall(r"[\u0600-\u06ff]", text)) > len(re.findall("[a-zA-Z]", text)):
                        lang = "ar"
                    return rows, lang
        except Exception as error:
            from .episode_generation import error_text
            generator._log_rare("Субтитры отрывка", f"Дорожка источника: {error_text(error)}")
    return [], ""


def translate(generator, rows):
    if getattr(rows, "ass_russian", False):
        return rows
    original = [text for _, _, text in rows]
    if all(russian(text) for text in original):
        return rows
    client = getattr(generator, "gemini_episode", None) or generator.gemini
    if client is None:
        return []
    prompt = ("Переведи реплики субтитров аниме на естественный русский, точно сохраняя "
              "смысл, имена, порядок и число реплик. Не сокращай, не добавляй пояснений. "
              "Каждой исходной реплике соответствует ровно одна строка lines.\n"
              + api.json.dumps(original, ensure_ascii=False))
    result = client.generate_json(prompt, TRANSLATION_SCHEMA)
    shown = result.get("lines") if isinstance(result, dict) else None
    if (not isinstance(shown, list) or len(shown) != len(rows)
            or not all(isinstance(text, str) and russian(text) for text in shown)):
        return []
    return [(left, right, text.strip()) for (left, right, _), text in zip(rows, shown)]


def prepare(generator, stream, info, scope):
    """Return (start, RU rows), or None. Detached release timings are never guessed."""
    duration = number((info.get("format") or {}).get("duration"))
    duration = duration or number((video_track(info) or {}).get("duration"))
    if not allowed(generator, stream):
        return None
    if not wanted(generator, stream) or hard_subbed(stream):
        start = choose_start(duration, stream, generator.rng)
        if wanted(generator, stream) and start is not None:
            stream["_caption_output_language"] = hard_language(stream)
        return (start, []) if start is not None else None
    if (mode(generator.s) == "preferred" and not stream.get("subtitles")
            and stream.get("audio") == "sub"):
        # Unknown hardsub can only be accepted after inspecting the encoded video.
        start = choose_start(duration, stream, generator.rng)
        return (start, []) if start is not None else None
    rows, lang = load(generator, stream, scope)
    if not rows:
        generator._log_rare("Субтитры отрывка", "Нет синхронной дорожки субтитров у выбранного видео")
        return None
    for _ in range(24):
        start = choose_start(duration, stream, generator.rng)
        if start is None or generator.stopped() or time.monotonic() >= scope.deadline:
            return None
        clip = cropped(rows, start)
        if dialogue_window(clip):
            try:
                with measuring(generator, "перевод субтитров моделью"):
                    shown = translate(generator, clip)
            except Exception as error:  # noqa: BLE001 — оставляем EN резерв
                from .episode_generation import error_text
                generator._log_rare("Перевод субтитров отрывка", error_text(error))
                shown = []
            output_language = "ru"
            if (not shown and lang == "en" and mode(generator.s) == "preferred"
                    and not generator.stopped()):
                shown, output_language = clip, "en"
            if not shown:
                return None
            stream["_ru_cues"] = [{"start": round(left, 3), "end": round(right, 3),
                                  "text": text, "source_text": source[2]}
                                 for (left, right, text), source in zip(shown, clip)]
            stream["_caption_language"] = lang
            stream["_caption_output_language"] = output_language
            return start, shown
    return None


def write(final, rows):
    if not rows:
        return None
    if getattr(rows, "ass_document", "") and getattr(rows, "ass_russian", False):
        path = Path(final).with_suffix(".ass")
        path.write_text(rows.ass_document, encoding="utf-8")
        return path
    path = Path(final).with_suffix(".srt")
    path.write_text(srt(rows), encoding="utf-8")
    return path
