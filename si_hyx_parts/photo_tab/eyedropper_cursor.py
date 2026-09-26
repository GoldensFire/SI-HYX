# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""eyedropper_cursor. Public namespace: photo_tab."""
import photo_tab as _api


def eyedropper_cursor():
    """Курсор-пипетка (как в Photoshop/Paint): значок «капельницы» с белой
    обводкой, чтобы он был виден на любой картинке. Горячая точка — на кончике
    пипетки (нижний-левый угол глифа). Кэшируется (строим один раз)."""
    pass  # Shared state is addressed through _api.
    if _api._EYEDROPPER_CURSOR is None:
        try:
            sz = 26
            halo = _api.qta.icon('fa5s.eye-dropper', color='white').pixmap(_api.QSize(sz, sz))
            glyph = _api.qta.icon('fa5s.eye-dropper', color='#1e1e2e').pixmap(_api.QSize(sz, sz))
            canvas = _api.QPixmap(sz + 2, sz + 2)
            canvas.fill(_api.Qt.GlobalColor.transparent)
            p = _api.QPainter(canvas)
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2),
                           (0, 0), (2, 2), (0, 2), (2, 0)):
                p.drawPixmap(dx, dy, halo)     # белая обводка
            p.drawPixmap(1, 1, glyph)          # тёмный глиф поверх
            p.end()
            _api._EYEDROPPER_CURSOR = _api.QCursor(canvas, 2, sz)   # кончик — внизу слева
        except Exception:
            _api._EYEDROPPER_CURSOR = _api.QCursor(_api.Qt.CursorShape.CrossCursor)
    return _api._EYEDROPPER_CURSOR

eyedropper_cursor.__module__ = _api.__name__
_api.eyedropper_cursor = eyedropper_cursor
