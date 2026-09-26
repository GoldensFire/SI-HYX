# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_paint_subtitle_styled. Public namespace: edit_tab_base."""
import edit_tab_base as _api


def _paint_subtitle_styled(painter, rect, text, style=None):
    """Стилизованный рендер субтитров для превью в SubtitleCreatorDialog: шрифт,
    размер, жирный/курсив/подчёркивание, трекинг, выравнивание (numpad 1-9) и
    цвета — как в стиле реплики (см. DEFAULT_SUBTITLE_STYLE). Размер/трекинг
    заданы в единицах ASS PlayResY (288) и масштабируются в экранные px по
    высоте rect — так же, как libass масштабирует их при вшивании через ffmpeg,
    поэтому превью примерно совпадает с итоговым видео. НЕ используется вне
    этого диалога — обычный VLC-стиль оверлея (_paint_subtitle) не трогаем."""
    if not text:
        return
    style = style or _api.DEFAULT_SUBTITLE_STYLE
    painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(_api.QPainter.RenderHint.TextAntialiasing)
    scale = rect.height() / _api._ASS_PLAYRES_Y if rect.height() > 0 else 1.0
    px = max(8, int(round(float(style.get('size') or 20) * scale)))
    f = _api.QFont(style.get('font') or 'Arial')
    f.setBold(bool(style.get('bold')))
    f.setItalic(bool(style.get('italic')))
    f.setUnderline(bool(style.get('underline')))
    f.setPixelSize(px)
    spacing = float(style.get('spacing') or 0) * scale
    if spacing:
        f.setLetterSpacing(_api.QFont.SpacingType.AbsoluteSpacing, spacing)
    painter.setFont(f)

    align = int(style.get('align') or 2)
    row = (align - 1) // 3; col = (align - 1) % 3
    h_flag = (_api.Qt.AlignmentFlag.AlignLeft if col == 0
              else _api.Qt.AlignmentFlag.AlignRight if col == 2
              else _api.Qt.AlignmentFlag.AlignHCenter)
    v_flag = (_api.Qt.AlignmentFlag.AlignBottom if row == 0
              else _api.Qt.AlignmentFlag.AlignTop if row == 2
              else _api.Qt.AlignmentFlag.AlignVCenter)
    margin_v = max(6, int(rect.height() * 0.05))
    side = max(6, int(rect.width() * 0.04))
    area = _api.QRect(rect.left() + side, rect.top() + margin_v,
                 max(10, rect.width() - 2 * side),
                 max(10, rect.height() - 2 * margin_v))
    flags = int(h_flag | v_flag | _api.Qt.TextFlag.TextWordWrap)
    o = max(1, px // 11)
    outline = _api.QColor(style.get('outline_color') or '#000000')
    fill = _api.QColor(style.get('color') or '#FFFFFF')
    painter.setPen(_api.QPen(outline))
    for dx in (-o, 0, o):
        for dy in (-o, 0, o):
            if dx == 0 and dy == 0:
                continue
            painter.drawText(area.translated(dx, dy), flags, text)
    painter.setPen(_api.QPen(fill))
    painter.drawText(area, flags, text)

_paint_subtitle_styled.__module__ = _api.__name__
_api._paint_subtitle_styled = _paint_subtitle_styled

def _ass_timestamp(t):
    """Секунды → таймкод ASS «H:MM:SS.cc» (сотые доли, без ведущего нуля у часов)."""
    t = max(0.0, float(t))
    h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

_ass_timestamp.__module__ = _api.__name__
_api._ass_timestamp = _ass_timestamp

def _hex_to_ass_color(hex_color, alpha=0x00):
    """«#RRGGBB» → цвет ASS «&HAABBGGRR» (порядок байт обратный HTML)."""
    hc = (hex_color or "#FFFFFF").lstrip('#')
    if len(hc) != 6:
        hc = "FFFFFF"
    r, g, b = hc[0:2], hc[2:4], hc[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()

_hex_to_ass_color.__module__ = _api.__name__
_api._hex_to_ass_color = _hex_to_ass_color
