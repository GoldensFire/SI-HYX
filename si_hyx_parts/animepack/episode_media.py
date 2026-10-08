"""Seek a remote episode directly with SI-HYX's killable FFmpeg runner."""
from __future__ import annotations

import json
import math
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import animepack as api
from si_hyx_parts.kuhi._http import UA
from .episode_sources import CUT_SECONDS, choose_start
from .episode_quality_policy import floor, output_height

PROBE_TIMEOUT = 35
ENCODE_TIMEOUT = 300
# Запас копии после конца отрывка: ключевой кадр до start копия и так
# захватывает, а хвост нужен, чтобы точная резка не упёрлась в конец файла.
FETCH_TAIL = 2


def request_headers(stream):
    headers = {str(k): str(v) for k, v in (stream.get("headers") or {}).items()}
    lower = {k.casefold(): k for k in headers}
    referer = stream.get("referer") or headers.get(lower.get("referer", ""))
    if referer and "referer" not in lower:
        headers["Referer"] = str(referer)
    if referer and "origin" not in lower:
        parsed = urlsplit(str(referer))
        headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
    if "user-agent" not in lower:
        headers["User-Agent"] = UA
    safe = {k: v for k, v in headers.items()
            if k and not any(c in k + v for c in "\r\n\0")}
    return safe


def input_args(stream):
    safe = request_headers(stream)
    args = ["-rw_timeout", "15000000", "-headers",
            "".join(f"{k}: {v}\r\n" for k, v in safe.items()),
            "-protocol_whitelist", "http,https,httpproxy,tcp,tls,crypto,data",
            "-analyzeduration", "4000000", "-probesize", "2000000"]
    if stream.get("type") in ("hls", "dash"):
        # Serialized MPD namespaces and opaque URLs need an explicit demuxer.
        args += ["-f", stream["type"]]
    if stream.get("type") == "mp4":
        args += ["-seekable", "1", "-initial_request_size", "65536", "-request_size", "1048576"]
    elif stream.get("type") == "hls":
        # Kuhi CDNs also serve valid TS segments with .jpg/.html/token paths.
        # Protocol restrictions still forbid local files and non-HTTP media.
        args += ["-allowed_extensions", "ALL", "-allowed_segment_extensions", "ALL", "-extension_picky", "0"]
    return args


def probe(generator, url, stream=None, timeout=PROBE_TIMEOUT):
    args = input_args(stream) if stream else []
    cmd = [api.FFPROBE, "-v", "error"] + args + [
        "-show_entries", "format=duration:stream=index,codec_type,duration,width,height,bit_rate:stream_tags=language:stream_disposition=attached_pic",
        "-of", "json", str(url)]
    code, output, error = generator._run_capture(cmd, timeout=timeout)
    if code:
        if stream:
            stream["_probe_error"] = re.sub(r"https?://\S+", "[URL]", error or "таймаут")[-180:]
        if stream and hasattr(generator, "_log_rare"):
            status = re.search(r"(?:HTTP error|Server returned)\s+\d{3}[^\r\n]*", error or "")
            reason = status.group(0)[:100] if status else "источник не читается или истёк таймаут"
            generator._log_rare("ffprobe отрывка", f"{stream.get('provider', 'Kuhi')}: {reason}")
        return {}
    try:
        value = json.loads(output)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else 0
    except (ValueError, TypeError):
        return 0


def audio_track(info, *, source_language=None):
    audios = [s for s in info.get("streams", ()) if s.get("codec_type") == "audio"]
    japanese = [s for s in audios if str((s.get("tags") or {}).get("language") or "").lower() in ("ja", "jpn")]
    untagged = [s for s in audios if str((s.get("tags") or {}).get("language") or "").lower() in ("", "und", "unknown")]
    # Alloha's Japanese source contains a single track tagged "eng" in its TS.
    # An explicit player language binds that single track; never guess among dubs.
    confirmed = audios if source_language in ("ja", "jpn") and len(audios) == 1 else []
    return (japanese or untagged or confirmed or [None])[0]


def video_track(info):
    videos = [s for s in info.get("streams", ()) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")]
    return max(videos, key=lambda s: (number(s.get("height")), number(s.get("bit_rate"))), default=None)


@contextmanager
def prepared(stream, final):
    """HTTP input lets FFmpeg carry headers through a restricted manifest."""
    manifest = stream.get("manifest")
    source = dict(stream)
    if manifest:
        from .episode_manifest import serve_manifest
        with serve_manifest(manifest, stream["type"]) as url:
            source["url"] = url
            yield source
    else:
        yield source


def inspect_stream(generator, stream, final, deadline):
    """ffprobe-сведения годного потока либо {}; причина отказа — в stream["_reject"]:
    "low" — дорожка проверена и не подходит, "pause" — источник не ответил."""
    minimum = floor(stream)
    if stream.get("manifest_height") and stream["manifest_height"] < minimum:
        stream["_reject"] = "low"
        return {}
    with prepared(stream, final) as source:
        remaining = min(PROBE_TIMEOUT, max(1, deadline - time.monotonic()))
        info = probe(generator, source["url"], source, remaining)
    if not info:
        stream["_reject"] = "pause"
        return {}
    video = video_track(info)
    if video is None or number(video.get("height")) < minimum or audio_track(
            info, source_language=stream.get("audio_language")) is None:
        if hasattr(generator, "_log_rare"):
            height = int(number((video or {}).get("height")))
            generator._log_rare("Качество отрывка", f"{stream.get('provider', 'Kuhi')}: "
                                f"{height}p или нет японского аудио; требуется ≥{minimum}p")
        stream["_reject"] = "low"
        return {}
    stream["source_height"] = int(number(video["height"]))
    stream["bandwidth"] = int(number(video.get("bit_rate"))) or stream.get("bandwidth", 0)
    return info


def valid_clip(info):
    streams = info.get("streams", ())
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = audio_track(info)
    duration = number((info.get("format") or {}).get("duration"))
    if not video or audio is None or not CUT_SECONDS - 0.5 <= duration <= CUT_SECONDS + 0.75:
        return False
    return all(not number(s.get("duration")) or number(s["duration"]) >= CUT_SECONDS - 0.75
               for s in (video, audio))


def encode_args(generator, subtitles=None, height=720, subtitle_start=None):
    args = generator.video_encode_args()
    if height < 720:
        at = args.index("-vf") + 1
        args[at] = f"scale=-2:{height}:flags=lanczos,setsar=1"
    if subtitles:
        # -vf is already provided by the common scaler. Append the burn filter.
        path = Path(subtitles).as_posix().replace(":", "\\:").replace("'", "\\'")
        at = args.index("-vf") + 1
        clock = "setpts=PTS-STARTPTS"
        native_ass = subtitle_start is not None and Path(subtitles).suffix.lower() in (".ass", ".ssa")
        if native_ass:
            clock += f"+{float(subtitle_start):.3f}/TB"
        args[at] = clock + "," + args[at] + f",subtitles=filename='{path}':charenc=UTF-8"
        if native_ass:
            args[at] += ",setpts=PTS-STARTPTS"
    return args


def cut(generator, candidate, stream, final, *, subtitles=None, start=None, info=None, deadline=None):
    with prepared(stream, final) as source:
        return _cut(generator, candidate, source, final, subtitles=subtitles, start=start,
                    info=info or stream.get("_probe_info"), deadline=deadline)


def _cut(generator, candidate, stream, final, *, subtitles=None, start=None, info=None, deadline=None):
    remaining = min(PROBE_TIMEOUT, max(1, deadline - time.monotonic())) if deadline else PROBE_TIMEOUT
    info = info or probe(generator, stream["url"], stream, timeout=remaining)
    if not info or (deadline and time.monotonic() >= deadline):
        return None
    video = video_track(info)
    audio = audio_track(info, source_language=stream.get("audio_language"))
    if video is None or number(video.get("height")) < floor(stream) or audio is None:
        if hasattr(generator, "_log_rare"):
            generator._log_rare("Дорожки отрывка", f"{stream.get('provider', 'Kuhi')}: нет видео ≥{floor(stream)}p с японской дорожкой")
        return None
    stream["source_height"] = int(number(video["height"]))
    duration = number((info.get("format") or {}).get("duration"))
    if not duration:
        duration = number(video.get("duration"))
    if start is None:
        start = choose_start(duration, stream, generator.rng)
    if start is None or generator.stopped():
        return None
    local = Path(final).with_name(Path(final).stem + ".source.mkv")
    try:
        if _fetch(generator, stream, video, audio, start, local, deadline):
            # Копия хранит исходные метки: -seek_timestamp режет ровно с start,
            # и отрывок совпадает с прямой резкой из сети кадр в кадр.
            source = ["-seek_timestamp", "1", "-ss", f"{start:.3f}", "-i", str(local),
                      "-t", str(CUT_SECONDS), "-map", "0:0", "-map", "0:1"]
        else:
            # Input seek makes MP4 range requests and jumps to HLS/DASH segments.
            source = input_args(stream) + [
                "-ss", f"{start:.3f}", "-i", stream["url"], "-t", str(CUT_SECONDS),
                "-map", f"0:{video['index']}", "-map", f"0:{audio['index']}"]
        cmd = [api.FFMPEG, "-y", "-loglevel", "error"] + source + [
            "-sn", "-dn", "-metadata:s:a:0", "language=jpn"] + encode_args(
                generator, subtitles, output_height(stream), subtitle_start=start) + generator.opus_args(CUT_SECONDS) + [
            "-movflags", "+faststart", str(final)]
        timeout = min(ENCODE_TIMEOUT, max(1, deadline - time.monotonic())) if deadline else ENCODE_TIMEOUT
        code, _error = generator._run_killable(cmd, timeout=timeout)
    finally:
        local.unlink(missing_ok=True)
    remaining = min(PROBE_TIMEOUT, max(1, deadline - time.monotonic())) if deadline else PROBE_TIMEOUT
    if code == 0 and valid_clip(probe(generator, final, timeout=remaining)):
        return start
    Path(final).unlink(missing_ok=True)
    return None


def _fetch(generator, stream, video, audio, start, local, deadline=None) -> bool:
    """Кусок серии на диск без перекодирования, с исходными метками времени.

    Кодировщик AV1, читая прямо из сети, ждал каждый сегмент: в пакете из 100
    отрывков кодирование заняло 31 мин. Копия качается на полной скорости
    сети, а кодируется уже с диска. Не вышло — режем напрямую, как раньше."""
    if generator.stopped():
        return False
    # -t до -i: при -copyts выходной -t считал бы от нуля и отрезал всё.
    cmd = [api.FFMPEG, "-y", "-loglevel", "error"] + input_args(stream) + [
        "-ss", f"{start:.3f}", "-t", str(CUT_SECONDS + FETCH_TAIL), "-i", stream["url"],
        "-map", f"0:{video['index']}", "-map", f"0:{audio['index']}",
        "-c", "copy", "-sn", "-dn", "-copyts", "-start_at_zero", str(local)]
    timeout = min(ENCODE_TIMEOUT, max(1, deadline - time.monotonic())) if deadline else ENCODE_TIMEOUT
    code, error = generator._run_killable(cmd, timeout=timeout)
    if code == 0 and local.is_file() and local.stat().st_size:
        return True
    local.unlink(missing_ok=True)
    if hasattr(generator, "_log_rare") and not generator.stopped():
        # Последняя строка stderr без префикса «[out#0/matroska @ 0x…]»: срез
        # хвоста резал слово посередине и тащил в журнал переносы строк.
        lines = [line.strip() for line in str(error or "").splitlines() if line.strip()]
        reason = re.sub(r"^\[[^\]]*@\s*[0-9a-fA-Fx]+\]\s*", "", lines[-1]) if lines else "таймаут"
        reason = re.sub(r"https?://\S+", "[URL]", reason)[-120:]
        generator._log_rare("Копия отрывка", f"{stream.get('provider', 'Kuhi')}: {reason}; режу напрямую")
    return False
