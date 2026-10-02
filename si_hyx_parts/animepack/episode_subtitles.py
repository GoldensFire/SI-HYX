"""Optional SubDL -> Jimaku captions, bound to the selected episode and clip."""
from __future__ import annotations

from pathlib import Path
import re

import animepack as api
from animepack_api import jimaku_file_episode
from .dialogue_questions import parse_subtitles
from .dialogue_subdl import _decode
from .episode_media import encode_args, probe, valid_clip
from .episode_sources import CUT_SECONDS

TRANSLATION_SCHEMA = {"type": "object", "properties": {
    "lines": {"type": "array", "items": {"type": "string"}}}, "required": ["lines"]}


def cropped(data, name, start):
    end = start + CUT_SECONDS
    return [(max(0, left - start), min(CUT_SECONDS, right - start), text)
            for left, right, text in parse_subtitles(_decode(data), name)
            if left < end and right > start and right > left]


def russian(text):
    return bool(re.search("[А-Яа-яЁё]", text))


def _jimaku(generator, aid, episode, start):
    if generator.jimaku is None or generator.stopped():
        return []
    entry = generator.jimaku.entry(aid)
    if not entry:
        return []
    files = generator.jimaku.files(int(entry["id"]), episode)
    files.sort(key=lambda row: not bool(re.search(r"\b(ru|rus|russian)\b", str(row.get("name") or ""), re.I)))
    for item in files[:3]:
        if generator.stopped():
            break
        # JimakuApi.files enforces this too; retain the binding for injected clients.
        if jimaku_file_episode(str(item.get("name") or "")) != episode:
            continue
        rows = cropped(generator.jimaku.download(item), item.get("name", ""), start)
        if not rows:
            continue
        if all(russian(text) for _, _, text in rows):
            return rows
        if generator.gemini is None:
            continue
        original = [text for _, _, text in rows]
        prompt = ("Переведи все реплики субтитров на русский. Сохрани порядок и число "
                  "реплик. Не добавляй пояснений и новых реплик. Верни lines.\n"
                  + api.json.dumps(original, ensure_ascii=False))
        result = generator.gemini.generate_json(prompt, TRANSLATION_SCHEMA)
        shown = result.get("lines") if isinstance(result, dict) else None
        if (isinstance(shown, list) and len(shown) == len(rows)
                and all(isinstance(text, str) and russian(text) for text in shown)):
            return [(left, right, text.strip()) for (left, right, _), text in zip(rows, shown)]
    return []


def find(generator, candidate, aid, episode, start):
    """Missing RU captions never fail the video question."""
    if not generator.s.episode_ru_subtitles or generator.stopped():
        return []
    with generator._episode_subtitle_lock:
        if generator.subdl is not None:
            try:
                ids = generator.anizip.external_ids(candidate.mal_id)
                seasons = subdl_binding(generator.anizip.info(candidate.mal_id), episode)
                for row in seasons[:1]:
                    files = generator.subdl.episode_files(ids, row["season"], row["episode"])
                    for item in files[:3]:
                        if generator.stopped():
                            return []
                        if int(item.get("episode", row["episode"])) != row["episode"]:
                            continue
                        data, name = generator.subdl.download(item)
                        rows = cropped(data, name, start)
                        if rows:
                            return rows
            except api.SubdlQuotaError:
                generator.subdl = None
            except Exception as error:  # API/auth/network failures are optional here.
                generator._log_rare("Субтитры отрывка", f"SubDL: {error}")
        try:
            return _jimaku(generator, aid, episode, start)
        except Exception as error:
            generator._log_rare("Субтитры отрывка", f"Jimaku: {error}")
            return []


def subdl_binding(info, episode):
    """Keep title-local episode numbers separate from TVDB's season numbering."""
    episodes = info.get("episodes") or {}
    for key, row in episodes.items():
        if not isinstance(row, dict):
            continue
        try:
            local = float(row.get("episodeNumber", key))
            season = float(row.get("seasonNumber"))
            tv_episode = float(row.get("tvdbEpisodeNumber", row.get("episodeNumber", key)))
        except (ValueError, TypeError):
            continue
        if local == episode and season.is_integer() and tv_episode.is_integer() and season > 0 and tv_episode > 0:
            return [{"season": int(season), "episode": int(tv_episode)}]
    return []


def _time(seconds):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def srt(rows):
    return "\n\n".join(f"{i}\n{_time(left)} --> {_time(right)}\n{text}"
                         for i, (left, right, text) in enumerate(rows, 1)) + "\n"


def burn(generator, final, rows):
    if not rows or generator.stopped():
        return False
    subtitles = Path(final).with_suffix(".srt")
    target = Path(final).with_suffix(".ru.mp4")
    try:
        subtitles.write_text(srt(rows), encoding="utf-8")
        cmd = [api.FFMPEG, "-y", "-loglevel", "error", "-i", str(final),
               "-map", "0:v:0", "-map", "0:a:0", "-t", str(CUT_SECONDS)]
        cmd += encode_args(generator, subtitles) + ["-c:a", "copy", "-movflags", "+faststart", str(target)]
        code, _err = generator._run_killable(cmd, timeout=300)
        if code == 0 and valid_clip(probe(generator, target)):
            target.replace(final)
            return True
        return False
    finally:
        subtitles.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
