# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ytdlp_base_cmd. Public namespace: config."""
import config as _api


def ytdlp_base_cmd():
    """База для запуска yt-dlp как процесса.
    Приоритет: bin/yt-dlp.exe (bundled, обновляемый) → системный yt-dlp в PATH →
    `python -m yt_dlp` (только в dev, не во frozen-сборке).
    Возвращает список аргументов или None, если yt-dlp нигде не найден.
    """
    exe = _api._resolve_tool("yt-dlp")
    if _api.os.path.isfile(exe):
        return [exe]
    w = _api.shutil.which("yt-dlp")
    if w:
        return [w]
    if not getattr(_api.sys, "frozen", False):
        return [_api.sys.executable, "-m", "yt_dlp"]
    return None

ytdlp_base_cmd.__module__ = _api.__name__
_api.ytdlp_base_cmd = ytdlp_base_cmd

def _bin_dirs():
    """Каталоги, где лежат bundled-бинарники (ffmpeg/yt-dlp/deno)."""
    dirs = []
    base = getattr(_api.sys, "_MEIPASS", None)
    if base:
        dirs += [base, _api.os.path.join(base, "bin")]
    d1 = _api.os.path.dirname(_api.os.path.abspath(_api.sys.argv[0] or "."))
    dirs += [d1, _api.os.path.join(d1, "bin")]
    d2 = _api.os.path.dirname(_api.os.path.abspath(_api.__file__))
    dirs += [d2, _api.os.path.join(d2, "bin")]
    # Уникальные существующие каталоги, порядок сохраняется
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and _api.os.path.isdir(d):
            seen.add(d); out.append(d)
    return out

_bin_dirs.__module__ = _api.__name__
_api._bin_dirs = _bin_dirs

def subprocess_env():
    """os.environ с добавленными в PATH каталогами bin — чтобы yt-dlp находил
    deno (нужен для n-challenge YouTube, иначе отдаёт только 360p) и ffmpeg."""
    env = _api.os.environ.copy()
    extra = _api._bin_dirs()
    if extra:
        env["PATH"] = _api.os.pathsep.join(extra) + _api.os.pathsep + env.get("PATH", "")
    return env

subprocess_env.__module__ = _api.__name__
_api.subprocess_env = subprocess_env

def deno_available():
    """True, если deno найден (в bin рядом с программой или в системном PATH)."""
    exe = _api._resolve_tool("deno")
    if _api.os.path.isfile(exe):
        return True
    return _api.shutil.which("deno") is not None

deno_available.__module__ = _api.__name__
_api.deno_available = deno_available

def cpu_thread_count():
    """Надёжное число логических потоков ЦП.
    os.cpu_count() в части frozen/песочница-окружений (PyInstaller windowed,
    Windows Sandbox с ограниченным affinity) возвращает None → счётчик «потоков»
    падал до 1/1. Фолбэк: NUMBER_OF_PROCESSORS → разумный дефолт 4."""
    n = _api.os.cpu_count()
    if n and n > 0:
        return n
    try:
        n = int(_api.os.environ.get("NUMBER_OF_PROCESSORS", "") or 0)
        if n > 0:
            return n
    except Exception:
        pass
    return 4

cpu_thread_count.__module__ = _api.__name__
_api.cpu_thread_count = cpu_thread_count
