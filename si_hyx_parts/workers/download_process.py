# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Stop the owned downloader together with its FFmpeg/Deno child processes."""
import workers as _api


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    if _api.IS_WIN and isinstance(getattr(proc, "pid", None), int):
        try:
            _api.subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                creationflags=_api.CREATE_NO_WINDOW, timeout=5)
        except (OSError, _api.subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def stop_process_async(proc):
    """Останавливает процесс без блокировки GUI-потока.
    На Windows taskkill /T /F может выполняться до 5 с, поэтому уносим его
    в фоновый поток; при отсутствии числового PID или на других ОС
    выполняем мгновенный proc.kill() синхронно."""
    if proc is None or proc.poll() is not None:
        return
    if _api.IS_WIN and isinstance(getattr(proc, "pid", None), int):
        _api.threading.Thread(target=stop_process, args=(proc,), daemon=True).start()
    else:
        stop_process(proc)


def copy_cookies_for_job(src_path: str) -> tuple[str, bool]:
    """Создаёт временную копию файла cookies для одного запуска yt-dlp,
    чтобы параллельные процессы не конфликтовали при перезаписи --cookies.
    Возвращает (path_to_use, is_temp_copy)."""
    if not src_path or not _api.os.path.isfile(src_path):
        return src_path, False
    tmp_path = _api.os.path.join(
        _api.TEMP_DIR, f"si_hyx_cookies_{_api.uuid.uuid4().hex}.txt")
    try:
        _api.shutil.copyfile(src_path, tmp_path)
        return tmp_path, True
    except OSError:
        return src_path, False


def remove_temp_cookie(path: str, is_temp: bool) -> None:
    if is_temp and path:
        try:
            if _api.os.path.exists(path):
                _api.os.remove(path)
        except OSError:
            pass
