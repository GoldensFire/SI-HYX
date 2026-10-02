# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Общее кодирование появления для генерации паков и монтажа."""
from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps
from image_entrance import fitted_size
from image_entrance_renderer import render


def _check_result(code, err, output):
    if code or not Path(output).is_file() or not Path(output).stat().st_size:
        raise RuntimeError((err or "пустой ролик появления").strip()[:240])


@dataclass
class EntranceEncoder:
    folder: str
    ffmpeg: str
    ffprobe: str
    run: Callable
    capture: Callable
    stopped: Callable
    fps: int = 30
    seconds: float = 1.2
    strength: int = 70
    preset: int = 13
    crf: int = 25
    max_height: int | None = 720
    tune: int = 0

    def encoder_args(self):
        return ["-c:v", "libsvtav1", "-crf", str(max(0, min(63, int(self.crf)))),
                "-preset", str(self.preset), "-pix_fmt", "yuv420p10le",
                "-svtav1-params", f"tune={self.tune}:keyint=-1:scd=1"]

    def output_size(self, width, height):
        if self.max_height is None:
            return tuple(max(2, round(side / 2) * 2) for side in (width, height))
        return fitted_size(width, height, self.max_height)

    def encode_image(self, source, output, effect, seed, seconds):
        fps = self.fps
        count = max(2, round(seconds * fps))
        with Image.open(source) as opened:
            original = ImageOps.exif_transpose(opened).convert("RGB")
        original = original.resize(self.output_size(*original.size),
                                   Image.Resampling.LANCZOS)
        with tempfile.TemporaryDirectory(prefix="_entrance_", dir=self.folder) as folder:
            for i in range(count):
                if self.stopped():
                    raise RuntimeError("остановлено")
                frame = render(original, effect, i / (count - 1),
                               self.strength, seed)
                frame.save(Path(folder, f"frame_{i:05d}.png"))
            cmd = ([self.ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(Path(folder, "frame_%05d.png")), "-frames:v", str(count),
                    "-force_key_frames", f"{(count - 1) / fps:.9f}",
                    "-vf", "setsar=1", "-an"] + self.encoder_args()
                   + ["-movflags", "+faststart", str(output)])
            code, err = self.run(cmd, timeout=300)
            _check_result(code, err, output)
        return count / fps
    def encode_video(self, source, output, effect, seed):
        code, text, err = self.capture(
            [self.ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration:format=duration",
             "-of", "json", str(source)], timeout=30)
        if code:
            raise RuntimeError(err or "не удалось прочитать параметры ролика")
        info = json.loads(text)
        stream = info["streams"][0]
        width, height = self.output_size(int(stream["width"]), int(stream["height"]))
        duration = float(stream.get("duration") or info["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError("неизвестная длительность ролика")
        fps = self.fps
        count = max(2, min(round(self.seconds * fps),
                           math.floor(duration * fps)))
        with tempfile.TemporaryDirectory(prefix="_entrance_", dir=self.folder) as folder:
            root = Path(folder)
            # Обрабатывается движение исходного видео, а не замороженный первый кадр.
            cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
                   "-vf", f"scale={width}:{height},fps={fps},setsar=1",
                   "-frames:v", str(count), str(root / "source_%05d.png")]
            code, err = self.run(cmd, timeout=120)
            if code:
                raise RuntimeError(err or "не удалось прочитать начало ролика")
            frames = sorted(root.glob("source_*.png"))
            if len(frames) < 2:
                raise RuntimeError("в ролике меньше двух кадров")
            count = len(frames)
            intro_seconds = count / fps
            for i, path in enumerate(frames):
                if self.stopped():
                    raise RuntimeError("остановлено")
                with Image.open(path) as opened:
                    frame = render(opened, effect, i / (count - 1),
                                   self.strength, seed)
                frame.save(root / f"frame_{i:05d}.png")
                path.unlink()
            if intro_seconds >= duration - 0.5 / fps:
                chain = "[1:v]setsar=1,setpts=PTS-STARTPTS[out]"
            else:
                chain = (f"[0:v]scale={width}:{height},fps={fps},setsar=1,"
                         f"trim=start={intro_seconds:.9f},setpts=PTS-STARTPTS[rest];"
                         "[1:v]setsar=1,setpts=PTS-STARTPTS[start];"
                         "[start][rest]concat=n=2:v=1:a=0[out]")
            cmd = ([self.ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
                    "-framerate", str(fps), "-i", str(root / "frame_%05d.png"),
                    "-filter_complex", chain, "-map", "[out]", "-map", "0:a?",
                    "-force_key_frames", f"{(count - 1) / fps:.9f}",
                    "-c:a", "copy", "-t", f"{duration:.9f}"] + self.encoder_args()
                   + ["-movflags", "+faststart", str(output)])
            code, err = self.run(cmd, timeout=300)
            _check_result(code, err, output)
