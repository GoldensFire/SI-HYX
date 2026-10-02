# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Фоновый экспорт появления с отменой и сохранением исходного файла."""
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from config import CREATE_NO_WINDOW, FFMPEG, FFPROBE
from image_entrance_encoding import EntranceEncoder


class EntranceWorker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source, output, is_image, options):
        super().__init__()
        self.source = str(source)
        self.output = str(output)
        self.is_image = is_image
        self.options = dict(options)

    def stop(self):
        self.requestInterruption()

    def _capture(self, command, timeout):
        if self.isInterruptionRequested():
            raise RuntimeError("Отменено")
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        with subprocess.Popen(command, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=flags) as process:
            started = time.monotonic()
            try:
                while True:
                    if self.isInterruptionRequested():
                        raise RuntimeError("Отменено")
                    if time.monotonic() - started > timeout:
                        raise RuntimeError("Превышено время обработки видео")
                    try:
                        out, err = process.communicate(timeout=0.2)
                        return (process.returncode, out.decode("utf-8", "replace"),
                                err.decode("utf-8", "replace"))
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def _run(self, command, timeout):
        code, _, err = self._capture(command, timeout)
        return code, err

    def run(self):
        output_created = False
        try:
            with tempfile.TemporaryDirectory(
                    prefix="_entrance_", dir=Path(self.output).parent) as folder:
                target = Path(folder, "result.mp4")
                options = dict(self.options)
                effect = options.pop("effect")
                encoder = EntranceEncoder(
                    folder=folder, ffmpeg=FFMPEG, ffprobe=FFPROBE,
                    run=self._run, capture=self._capture,
                    stopped=self.isInterruptionRequested, max_height=None, **options)
                seed = secrets.randbits(64)
                if self.is_image:
                    encoder.encode_image(self.source, target, effect, seed, encoder.seconds)
                else:
                    encoder.encode_video(self.source, target, effect, seed)
                if self.isInterruptionRequested():
                    raise RuntimeError("Отменено")
                # Создаём новый файл; существующий результат не перезаписываем.
                with target.open("rb") as source, open(self.output, "xb") as output:
                    output_created = True
                    shutil.copyfileobj(source, output)
            self.done.emit(self.output)
        except Exception as exc:
            if output_created:
                Path(self.output).unlink(missing_ok=True)
            self.failed.emit("Отменено" if self.isInterruptionRequested() else str(exc))
