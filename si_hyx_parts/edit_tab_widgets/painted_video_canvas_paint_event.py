# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas: paintEvent. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def paintEvent(self, ev):
    p = _api.QPainter(self)
    p.fillRect(self.rect(), self._bg)
    img = self._frame_img
    if img is not None and not img.isNull():
        vr = self.video_rect()
        # Во время протяжки/воспроизведения — без сглаживания (быстрее, кадр всё
        # равно сейчас сменится); на устоявшемся стоп-кадре — со сглаживанием
        # (качество).
        p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform,
                        not (self._scrub_active or self._playing))
        p.drawImage(vr, img)
        self._paint_overlays(p, vr)
    elif self._audio_only_msg:
        self._paint_audio_only(p)
    p.end()
