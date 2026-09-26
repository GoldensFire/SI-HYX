# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Кодирование «DVD-заставки»: покадровая анимация прямо в ffmpeg.

В отличие от ступенчатых эффектов (encode_reveal), прямоугольник двигается
каждым кадром ролика — 30 или 60 кадров в секунду по своей настройке
«DVD, кадров/с», какой бы «Кадров/с» ни стоял у остальных эффектов (просьба
пользователя: «не раз в 2 секунды»). Кадры не ложатся на диск PNG-файлами —
идут в ffmpeg по трубе сырыми RGB. К последнему кадру движения прямоугольник
улетает за край; на время последней ступени застывает этот же кадр —
полностью кадр НЕ открывается, необлетённое остаётся чёрным.
"""
from __future__ import annotations

import random
import subprocess
import tempfile

from PIL import Image, ImageOps

import animepack as _api
from frame_reveal import stage_frame_counts
from frame_reveal_dvd import DvdAnimation, dvd_fps
from frame_reveal_dvd_media import FolderMedia, list_media


def dvd_media(self, rng, fps: int):
    """Источник картинок/видео для прямоугольника или None (папки нет)."""
    folder = str(getattr(self.s, "frame_dvd_folder", "") or "").strip()
    files = list_media(folder)
    if not files:
        if folder:
            self._log_rare("DVD-заставка", f"В папке «{folder}» нет картинок "
                           "и видео — прямоугольник будет просто окном в кадр.")
        return None

    def track(proc):
        with self._procs_lock:
            self._procs.add(proc)

    def untrack(proc):
        with self._procs_lock:
            self._procs.discard(proc)

    return FolderMedia(files, rng, _api.FFMPEG, _api.FFPROBE, fps,
                       track, untrack)


def encode_dvd(self, source: str, output: str, seed: int):
    """(код возврата, текст ошибки) — как у _run_killable."""
    fps = dvd_fps(getattr(self.s, "frame_dvd_fps", None))
    counts = stage_frame_counts(self.s.pixel_seconds, fps, self.s.pixel_steps)
    total = sum(counts)
    moving = total - counts[-1]
    with Image.open(source) as opened:
        original = ImageOps.exif_transpose(opened).convert("RGB")
    height = _api.PIXEL_HEIGHT
    width = max(2, round(original.width * height / original.height / 2) * 2)
    original = original.resize((width, height), Image.Resampling.LANCZOS)
    rng = random.Random(seed)
    media = dvd_media(self, rng, fps)
    strength = max(10, min(100, int(self.s.frame_effect_strength))) / 100.0
    try:
        anim = DvdAnimation(original, strength, rng, media, fps, moving)
    except Exception:
        if media is not None:
            media.close()
        raise
    still_at = moving / fps
    cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
            "-framerate", str(fps), "-i", "-", "-frames:v", str(total),
            "-force_key_frames", f"{still_at:.9f}"]
           + self.pixel_encode_args("setsar=1")
           + ["-movflags", "+faststart", output])
    kw = {"creationflags": _api.CREATE_NO_WINDOW} if _api.os.name == "nt" else {}
    # stderr — во временный файл, а не в PIPE: недочитанная труба ошибок
    # подвешивает ffmpeg (см. память про proxy-stderr).
    with tempfile.TemporaryFile() as errors:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=errors,
                                    **kw)
        except Exception as e:  # noqa: BLE001
            _close(anim, media)
            return 1, str(e)
        with self._procs_lock:
            self._procs.add(proc)
        try:
            code = _feed(self, proc, anim, moving, total)
        finally:
            _close(anim, media)
            with self._procs_lock:
                self._procs.discard(proc)
        errors.seek(0)
        text = errors.read().decode("utf-8", "replace")
    if code is None:
        return 1, "остановлено"
    return code, text


def _close(anim, media) -> None:
    anim.close()
    if media is not None:
        media.close()


def _feed(self, proc, anim, moving: int, total: int):
    """Пишет кадры в ffmpeg; None — остановлено кнопкой «Стоп».

    После движения до конца ролика стоит последний кадр анимации, а НЕ
    полный кадр: необлетённое остаётся чёрным (просьба пользователя)."""
    last = None
    try:
        for number in range(total):
            if self.stopped():
                self._kill(proc)
                return None
            if number < moving:
                proc.stdin.write(anim.frame().tobytes())
                anim.step()
            else:
                if last is None:
                    last = anim.frame().tobytes()
                proc.stdin.write(last)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass                      # ffmpeg упал — причина будет в его stderr
    deadline = _api.time.monotonic() + 300
    while True:
        try:
            return proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        if self.stopped() or _api.time.monotonic() > deadline:
            self._kill(proc)
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            return None if self.stopped() else 1
