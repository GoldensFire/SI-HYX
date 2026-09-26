# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Подготовка ступеней раскрытия и кодирование одного вопроса."""
from pathlib import Path

from PIL import Image, ImageOps

import animepack as _api
from frame_reveal import RevealRenderer, stage_frame_counts


def encode_reveal(self, source: str, output: str, effect: str, seed: int):
    """PNG существуют лишь во временной папке; в пак попадает один ролик."""
    fps = max(1, min(60, int(self.s.pixel_fps)))
    counts = stage_frame_counts(self.s.pixel_seconds, fps, self.s.pixel_steps)
    with Image.open(source) as opened:
        original = ImageOps.exif_transpose(opened).convert("RGB")
    height = _api.PIXEL_HEIGHT
    width = max(2, round(original.width * height / original.height / 2) * 2)
    original = original.resize((width, height), Image.Resampling.LANCZOS)
    renderer = RevealRenderer(original, effect, self.s.frame_effect_strength, seed)
    with _api.tempfile.TemporaryDirectory(prefix="_reveal_", dir=self.folder) as folder:
        root = Path(folder)
        lines = ["ffconcat version 1.0"]
        for i, count in enumerate(counts):
            if self.stopped():
                return 1, "остановлено"
            name = f"step_{i:02d}.png"
            renderer.render(i / (len(counts) - 1)).save(root / name)
            lines.extend([f"file '{name}'", f"option framerate {fps}",
                          f"duration {count / fps:.9f}"])
        # Последний повтор задаёт конец длительности последней ступени.
        lines.extend([f"file 'step_{len(counts) - 1:02d}.png'", f"option framerate {fps}"])
        manifest = root / "stages.ffconcat"
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if self.stopped():
            return 1, "остановлено"
        # Последняя ступень обязана быть чистым кадром. После почти чёрных
        # плиток межкадровое сжатие могло протащить их след в единственный
        # финальный кадр при 1 fps; принудительный ключевой кадр разрывает
        # такую зависимость, не раздувая ключевыми кадрами весь ролик.
        clean_at = sum(counts[:-1]) / fps
        cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-f", "concat",
                "-safe", "0", "-i", str(manifest), "-r", str(fps),
                "-frames:v", str(sum(counts)), "-force_key_frames",
                f"{clean_at:.9f}"]
               + self.pixel_encode_args("setsar=1")
               + ["-movflags", "+faststart", output])
        return self._run_killable(cmd, timeout=300)
