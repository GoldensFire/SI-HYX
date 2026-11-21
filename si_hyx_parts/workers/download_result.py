# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded retries and validation before publishing a completed download."""
import workers as _api
from .download_network import is_network_error, terminal_ffmpeg_error
from .download_validation import (
    DownloadValidationError, expected_duration, validate_streams,
)


def _media_summary_from_probe(info: dict, path: str) -> dict:
    """Извлекает (size, br_str, a_br) из уже выполненного вывода ffprobe —
    чтобы GUI-поток не запускал ffprobe повторно."""
    size = 0
    try:
        size = _api.os.path.getsize(path)
    except OSError:
        size = 0
    fmt = info.get("format") or {}
    try:
        dur = float(fmt.get("duration", 0) or 0)
    except (ValueError, TypeError):
        dur = 0.0
    br_str = "-"
    a_br = "-"
    fmt_br = 0
    try:
        fmt_br = int(fmt.get("bit_rate", 0) or 0)
        if fmt_br > 0:
            br_str = f"{fmt_br // 1000} кбит/с"
    except (ValueError, TypeError):
        pass
    audio_streams = [s for s in (info.get("streams") or [])
                     if isinstance(s, dict) and s.get("codec_type") == "audio"]
    if audio_streams:
        s0 = audio_streams[0]
        try:
            abr = int(s0.get("bit_rate", 0) or 0)
            if abr > 0:
                a_br = f"{abr // 1000} кбит/с"
                br_str = a_br
        except (ValueError, TypeError):
            pass
        if a_br == "-":
            try:
                sr = int(s0.get("sample_rate", 0) or 0)
                ch = int(s0.get("channels", 0) or 0)
                bps = int(s0.get("bits_per_sample", 0) or 0)
                if sr > 0 and ch > 0 and bps > 0:
                    a_br = f"{(sr * ch * bps) // 1000} кбит/с"
                    br_str = a_br
            except (ValueError, TypeError):
                pass
        if a_br == "-" and fmt_br > 0:
            a_br = f"{fmt_br // 1000} кбит/с"
            br_str = a_br
    if br_str == "-" and dur > 0 and size > 0:
        est = int(size * 8 / dur)
        br_str = f"{est // 1000} кбит/с"
        if a_br == "-":
            a_br = br_str
    return {"size": size, "br_str": br_str, "a_br": a_br}


def probe_download(worker, path, audio_only):
    try:
        result = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-show_entries",
             "format=duration,bit_rate:stream=codec_type,duration,duration_ts,time_base,"
             "bit_rate,sample_rate,channels,bits_per_sample,codec_name:"
             "stream_tags=DURATION:stream_disposition=attached_pic",
             "-of", "json", path],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=_api.CREATE_NO_WINDOW)
    except (OSError, _api.subprocess.TimeoutExpired) as exc:
        raise DownloadValidationError(
            f"Не удалось проверить скачанный файл через ffprobe: {exc}") from exc
    if result.returncode:
        raise DownloadValidationError(
            "Скачанный файл повреждён или не читается: " + result.stderr.strip(),
            incomplete=True)
    try:
        info = _api.json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise DownloadValidationError("ffprobe не вернул данные для проверки файла.") from exc
    source = getattr(worker, "_source_duration", None) or worker.c.get("source_duration")
    validate_streams(
        info, audio_only=audio_only,
        expect_audio=getattr(worker, "_expected_audio", audio_only),
        duration=expected_duration(source, worker.c.get("start_s"), worker.c.get("end_s")))
    return _media_summary_from_probe(info, path)


def preserve_incomplete(worker, path):
    """Keep rejected data, but remove the completed filename from the next attempt."""
    destination = path + ".incomplete"
    index = 1
    while _api.os.path.exists(destination):
        destination = path + f".incomplete-{index}"
        index += 1
    _api.os.rename(path, destination)
    worker.log_sig.emit(f"Неполный файл сохранён: {destination}")


def verified_download(worker, cmd, iid, audio_only, result):
    for attempt in range(3):
        if not worker.is_running:
            raise RuntimeError("Загрузка остановлена пользователем")
        rc, path, clean_info, tail = result
        detail = "\n".join(tail).strip()
        failure = getattr(worker, "_download_failure", "") or next(
            (terminal_ffmpeg_error(line) for line in tail if terminal_ffmpeg_error(line)), "")
        incomplete = False
        if rc not in (0, None):
            message = detail or f"yt-dlp завершился с кодом {rc}"
            if failure and failure not in message:
                message = failure + "\n" + message
            retryable = is_network_error(message)
        else:
            if failure:
                message = "Загрузка оборвалась: " + failure
                retryable = is_network_error(detail + failure)
                incomplete = bool(path and _api.os.path.isfile(path))
            elif not path or not _api.os.path.isfile(path):
                message = "yt-dlp завершил работу, но файл не найден."
                if detail:
                    message += "\n" + detail
                retryable = True
            else:
                try:
                    media_summary = probe_download(worker, path, audio_only)
                    if not worker.is_running:
                        raise RuntimeError("Загрузка остановлена пользователем")
                    return path, clean_info, media_summary
                except DownloadValidationError as exc:
                    message, retryable = str(exc), exc.incomplete
                    incomplete = exc.incomplete
        if incomplete:
            preserve_incomplete(worker, path)
        if not retryable or attempt == 2:
            raise RuntimeError(message)
        worker.log_sig.emit(f"{message}\nПовтор загрузки {attempt + 1}/2…")
        worker.progress_sig.emit(iid, 0.0, f"Повтор {attempt + 1}/2…")
        worker._sleep_interruptible(2.0)
        if not worker.is_running:
            raise RuntimeError("Загрузка остановлена пользователем")
        result = worker._exec_ytdlp(cmd, iid, audio_only)
