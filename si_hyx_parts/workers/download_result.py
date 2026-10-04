# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded retries and validation before publishing a completed download."""
import workers as _api
from .download_network import is_network_error, terminal_ffmpeg_error
from .download_validation import (
    DownloadValidationError, expected_duration, validate_streams,
)


def probe_download(worker, path, audio_only):
    try:
        result = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,duration,duration_ts,time_base:"
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
            if not path:
                path = worker._find_recent_output(worker.c.get("outdir", ".") or ".")
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
                    probe_download(worker, path, audio_only)
                    if not worker.is_running:
                        raise RuntimeError("Загрузка остановлена пользователем")
                    return path, clean_info
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
