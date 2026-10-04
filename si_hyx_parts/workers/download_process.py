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
