"""Russian captions with an English fallback from the selected video."""
from __future__ import annotations

from pathlib import Path
import re
import time

import animepack as api
from .episode_caption_text import cropped, parse, russian
from .episode_media import number, video_track
from .episode_sources import choose_start, hard_subbed
from .episode_subtitles import srt, TRANSLATION_SCHEMA


def language(row):
    value = " ".join(str(row.get(k) or "") for k in ("srclang", "language", "label", "name"))
    if re.search(r"\b(ru|rus|russian)\b|русск", value, re.I):
        return "ru"
    if re.search(r"\b(en|eng|english)\b", value, re.I):
        return "en"
    return "other"


def wanted(generator, stream):
    return bool(generator.s.episode_ru_subtitles or stream.get("ru_subtitles"))


def allowed(generator, stream):
    return (not wanted(generator, stream) or not hard_subbed(stream)
            or hard_language(stream) in ("ru", "en"))


def hard_language(stream):
    if stream.get("ru_subtitles"):
        return "ru"
    explicit = stream.get("subtitle_language") or stream.get("subtitleLanguage")
    if explicit:
        return language({"language": explicit})
    # Kuhi's unlabelled sub releases come from English subtitle providers.
    return "en" if stream.get("audio") == "sub" else "other"


def load(generator, stream, scope):
    client = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
    tracks = sorted(stream.get("subtitles") or [],
                    key=lambda row: (language(row) != "ru", language(row) != "en"))
    for track in tracks:
        if generator.stopped() or time.monotonic() >= scope.deadline:
            break
        try:
            selected = {**stream, "subtitles": [track]}
            files = client.captions(selected, scope)
            for data, name in files:
                lang = language(track)
                if lang == "other" and stream.get("ru_subtitles"):
                    lang = "ru"
                rows = parse(data, name, ru=lang == "ru")
                if rows:
                    return rows, lang
        except Exception as error:
            from .episode_generation import error_text
            generator._log_rare("Субтитры отрывка", f"Дорожка источника: {error_text(error)}")
    return [], ""


def translate(generator, rows):
    original = [text for _, _, text in rows]
    if all(russian(text) for text in original):
        return rows
    if generator.gemini is None:
        return []
    prompt = ("Переведи реплики субтитров аниме на естественный русский, точно сохраняя "
              "смысл, имена, порядок и число реплик. Не сокращай, не добавляй пояснений. "
              "Каждой исходной реплике соответствует ровно одна строка lines.\n"
              + api.json.dumps(original, ensure_ascii=False))
    result = generator.gemini.generate_json(prompt, TRANSLATION_SCHEMA)
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
    rows, lang = load(generator, stream, scope)
    if not rows:
        generator._log_rare("Субтитры отрывка", "Нет синхронной дорожки субтитров у выбранного видео")
        return None
    for _ in range(24):
        start = choose_start(duration, stream, generator.rng)
        if start is None or generator.stopped() or time.monotonic() >= scope.deadline:
            return None
        clip = cropped(rows, start)
        if clip and sum(right - left for left, right, _ in clip) >= 1:
            try:
                shown = translate(generator, clip)
            except Exception as error:  # noqa: BLE001 — оставляем EN резерв
                from .episode_generation import error_text
                generator._log_rare("Перевод субтитров отрывка", error_text(error))
                shown = []
            output_language = "ru"
            if not shown and lang == "en" and not generator.stopped():
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
    path = Path(final).with_suffix(".srt")
    path.write_text(srt(rows), encoding="utf-8")
    return path
