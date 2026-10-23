# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# ffmpeg_env.py — ffmpeg без Qt: где лежат программы, экранирование путей в
# фильтрах и выбор кодировщика H.264.
"""ffmpeg без Qt: поиск программ, пути в фильтрах, кодировщик H.264.

config импортирует отсюда resolve_tool и держит прежние имена FFMPEG/FFPROBE;
headless-инструменты (montage_tool) и модули без интерфейса (hdr_tonemap,
media_probe) берут их здесь, не поднимая PyQt6 и не создавая папку настроек."""
import os
import subprocess
import sys
import tempfile

IS_WIN = sys.platform.startswith("win")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0
TEMP_DIR = tempfile.gettempdir()


def resolve_tool(name):
    """Ищет ffmpeg/ffprobe рядом с программой (для сборки в .exe с bundled-ffmpeg).
    Порядок: _MEIPASS (PyInstaller) → папка exe/скрипта → подпапка bin → PATH.
    Если ничего не найдено — возвращает имя для поиска в системном PATH.
    """
    exe = name + (".exe" if IS_WIN else "")
    roots = []
    base = getattr(sys, "_MEIPASS", None)        # распакованные данные PyInstaller
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))  # папка exe
    roots.append(os.path.dirname(os.path.abspath(__file__)))            # папка скрипта
    for r in roots:
        for cand in (os.path.join(r, exe), os.path.join(r, "bin", exe)):
            if os.path.isfile(cand):
                return cand
    return name  # из системного PATH


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")


def escape_filter_path(p):
    """Экранирует путь для libavfilter (movie/subtitles/lut3d/fontsdir):
    прямые слэши + экранированное двоеточие диска + экранированная кавычка.
    Без экранирования двоеточия фильтр на Windows не инициализируется."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def available_encoders(ffmpeg=None):
    """Вывод `ffmpeg -encoders` или "" (опросить сборку не вышло — тогда
    выбор кодировщика считает доступным всё)."""
    try:
        p = subprocess.run([ffmpeg or FFMPEG, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=CREATE_NO_WINDOW,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout or ""


def gpu_h264_args(encoders, hardsub=False):
    """Первый доступный аппаратный (GPU) H.264-кодировщик, иначе None.
    При hardsub (вшивание субтитров) поджимаем качество, чтобы края текста
    не мылились."""
    q = 18 if hardsub else 20
    if "h264_nvenc" in encoders:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(q)]
    if "h264_qsv" in encoders:
        return ["-c:v", "h264_qsv", "-global_quality", str(q)]
    if "h264_amf" in encoders:
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(q), "-qp_p", str(q)]
    if "h264_mf" in encoders:
        qual = 80 if hardsub else 70
        return ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", str(qual)]
    return None


def h264_encoder_args(encoders, choice=0, hardsub=False):
    """Аргументы H.264-кодировщика: choice 0 — авто (libx264), 1 — процессор,
    2 — видеокарта. Если выбранного варианта в сборке нет — мягкий откат
    (GPU↔CPU↔mpeg4), чтобы перекодировка всегда состоялась. encoders — вывод
    available_encoders ("" — доступно всё).

    hardsub=True (вшивание субтитров): чуть более качественный профиль — у
    текста резкие края, и на «fast»/высоком CRF они мылятся."""
    cpu_args = (["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
                if hardsub else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
    cpu = cpu_args if ("libx264" in encoders or encoders == "") else None
    gpu = gpu_h264_args(encoders, hardsub=hardsub)
    if choice == 2:                      # GPU — с откатом на CPU
        args = gpu or cpu
    else:                                # CPU и «Авто» — с откатом на GPU
        args = cpu or gpu
    if args is None:
        args = ["-c:v", "mpeg4", "-q:v", "3"]
    args = list(args)
    if hardsub and "-pix_fmt" not in args:
        args += ["-pix_fmt", "yuv420p"]
    return args
