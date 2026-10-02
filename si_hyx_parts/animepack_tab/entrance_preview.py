# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Локальный анимированный пример без сети и фоновых задач."""
import time

from PIL import Image, ImageDraw
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel

from image_entrance_renderer import render


class EntrancePreview(QLabel):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 135)
        self.setMaximumHeight(180)
        self.setStyleSheet("background: #11111b; border-radius: 6px;")
        self.original = _sample()
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.draw_frame)
        self.draw_frame()

    def restart(self):
        self.started = time.monotonic()
        self.draw_frame()

    def draw_frame(self):
        mode = self.tab.cb_entrance_effect.currentData()
        if mode == "random":
            selected = [k for k, c in self.tab.entrance_effect_checks.items() if c.isChecked()]
            mode = selected[0] if selected else "spin"
        seconds = self.tab.sp_entrance_seconds.value()
        elapsed = (time.monotonic() - self.started) % (seconds + 1.0)
        result = render(self.original, mode, min(1, elapsed / seconds),
                        self.tab.sp_entrance_strength.value(), seed=42)
        data = result.tobytes()
        img = QImage(data, result.width, result.height, result.width * 3,
                     QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(img).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def showEvent(self, event):
        super().showEvent(event)
        self.restart()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)


def _sample():
    image = Image.new("RGB", (320, 180), "#252b4d")
    draw = ImageDraw.Draw(image)
    draw.ellipse((225, 12, 290, 77), fill="#f9e2af")
    draw.polygon(((0, 145), (90, 45), (185, 180), (0, 180)), fill="#89b4fa")
    draw.polygon(((110, 180), (220, 78), (320, 165), (320, 180)), fill="#cba6f7")
    draw.ellipse((115, 50, 185, 120), fill="#fab387", outline="#11111b", width=3)
    draw.rectangle((132, 75, 139, 84), fill="#11111b")
    draw.rectangle((161, 75, 168, 84), fill="#11111b")
    draw.arc((132, 86, 168, 105), 0, 180, fill="#11111b", width=3)
    draw.rounded_rectangle((105, 120, 195, 179), radius=20, fill="#a6e3a1")
    return image
