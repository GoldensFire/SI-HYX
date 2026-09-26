# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Содержимое прямоугольника «DVD-заставки» из папки пользователя.

В папке лежат картинки и видео; при каждом отскоке прямоугольник берёт
случайный другой файл, и его форма становится формой этого файла. Видео идёт
без звука и с того места, куда выпал жребий, зацикленным: декодирует его
отдельный ffmpeg прямо в нужный размер, по кадру на кадр ролика.

Обычный модуль с явными параметрами: процессы ffmpeg регистрирует тот, кто
его вызывает (track/untrack), — так кнопка «Стоп» генератора гасит и их.
"""
from __future__ import annotations

import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageOps

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv")
# Больше файлов из папки не перебираем: на заставку их нужны единицы.
MAX_FILES = 5000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def list_media(folder: str) -> list[str]:
    """Картинки и видео из папки (с подпапками), по алфавиту."""
    out: list[str] = []
    if not folder or not os.path.isdir(folder):
        return out
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if name.lower().endswith(IMAGE_EXTS + VIDEO_EXTS):
                out.append(os.path.join(root, name))
                if len(out) >= MAX_FILES:
                    return out
    return out


class ImageClip:
    """Картинка: пиксели грузятся, лишь когда клип дошёл до экрана.

    Путь заставки строится заранее и тянет жребий на все отскоки сразу —
    держать в памяти десятки картинок целиком незачем, нужна только форма.
    """

    def __init__(self, path: str):
        self.path = path
        with Image.open(path) as opened:
            width, height = opened.size
            orientation = opened.getexif().get(0x0112, 1)
        if orientation in (5, 6, 7, 8):          # EXIF-поворот на 90°
            width, height = height, width
        self.aspect = width / max(1, height)
        self.image = None
        self._cache = None

    def frame(self, width: int, height: int):
        if self._cache is None or self._cache.shape[:2] != (height, width):
            try:
                if self.image is None:
                    with Image.open(self.path) as opened:
                        self.image = ImageOps.exif_transpose(opened).convert("RGB")
                resized = self.image.resize((width, height), Image.Resampling.LANCZOS)
            except Exception:  # noqa: BLE001 — битая картинка: окно в кадр
                return None
            self._cache = np.asarray(resized, dtype=np.uint8)
        return self._cache

    def close(self) -> None:
        self._cache = None
        self.image = None


class VideoClip:
    """Видео без звука: кадры идут из ffmpeg по трубе, в нужном размере."""

    def __init__(self, path: str, ffmpeg: str, ffprobe: str, rng,
                 fps: int, track=None, untrack=None):
        self.path, self.ffmpeg, self.fps = path, ffmpeg, fps
        self.track, self.untrack = track, untrack
        width, height, duration = _probe(ffprobe, path)
        if not width or not height:
            raise ValueError("видео без картинки")
        self.aspect = width / height
        # Случайное место старта, но не в самом хвосте: оттуда видео тут же
        # закольцуется на начало.
        self.start = rng.uniform(0, duration * 0.8) if duration > 2 else 0.0
        self.proc = None
        self.size = None
        self.last = None

    def frame(self, width: int, height: int):
        if self.size != (width, height):
            self._open(width, height)
        need = width * height * 3
        data = b""
        try:
            data = self.proc.stdout.read(need) if self.proc else b""
        except (OSError, ValueError):
            data = b""
        if len(data) == need:
            self.last = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        return self.last

    def _open(self, width: int, height: int) -> None:
        self.close()
        self.size = (width, height)
        cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-stream_loop", "-1",
               "-ss", f"{self.start:.3f}", "-i", self.path, "-an", "-sn",
               "-vf", f"fps={self.fps},scale={width}:{height}:flags=bicubic,"
                      "setsar=1",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     creationflags=_NO_WINDOW)
        if self.track:
            self.track(self.proc)

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 — процесс мог уже выйти
            pass
        if self.untrack:
            self.untrack(proc)


class FolderMedia:
    """Жребий по файлам папки: каждый отскок — другой файл."""

    ATTEMPTS = 6

    def __init__(self, files, rng, ffmpeg="ffmpeg", ffprobe="ffprobe",
                 fps: int = 30, track=None, untrack=None):
        self.files = list(files)
        self.rng, self.ffmpeg, self.ffprobe, self.fps = rng, ffmpeg, ffprobe, fps
        self.track, self.untrack = track, untrack
        self.current = None
        self.path = ""
        self.broken: set[str] = set()

    def next_clip(self):
        """Следующий клип (None — годных файлов нет, остаётся прежний)."""
        for _ in range(self.ATTEMPTS):
            pool = [p for p in self.files if p not in self.broken]
            if len(pool) > 1:
                pool = [p for p in pool if p != self.path]
            if not pool:
                return None
            path = self.rng.choice(pool)
            try:
                clip = self._open(path)
            except Exception:  # noqa: BLE001 — битый файл просто пропускаем
                self.broken.add(path)
                continue
            self.close()
            self.current, self.path = clip, path
            return clip
        return None

    def _open(self, path: str):
        if path.lower().endswith(VIDEO_EXTS):
            return VideoClip(path, self.ffmpeg, self.ffprobe, self.rng,
                             self.fps, self.track, self.untrack)
        return ImageClip(path)

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None


def _probe(ffprobe: str, path: str) -> tuple[int, int, float]:
    """(ширина, высота, длительность) первого видеопотока с учётом поворота."""
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=width,height:stream_side_data=rotation:format=duration",
           "-of", "json", path]
    done = subprocess.run(cmd, capture_output=True, timeout=30,
                          creationflags=_NO_WINDOW)
    data = json.loads((done.stdout or b"{}").decode("utf-8", "replace") or "{}")
    stream = (data.get("streams") or [{}])[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    rotation = 0
    for side in stream.get("side_data_list") or []:
        try:
            rotation = int(float(side.get("rotation") or 0))
        except (TypeError, ValueError):
            continue
    if abs(rotation) % 180 == 90:
        width, height = height, width
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return width, height, duration
