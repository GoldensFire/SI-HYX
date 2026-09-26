# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_animation_override_tags. Public namespace: edit_tab_base."""
import edit_tab_base as _api


def _animation_override_tags(anim, align, duration_s):
    """Строит override-теги ASS ({\\...}) для простой анимации появления —
    fade/slide/pop. Тайминг анимации — треть длительности реплики (но не больше
    300мс и не меньше 50мс), чтобы короткие реплики не «залипали» в анимации."""
    if anim not in ('fade', 'slide', 'pop'):
        return ''
    dur_ms = max(10, int(round(duration_s * 1000)))
    t = min(300, max(50, dur_ms // 3))
    if anim == 'fade':
        return f"{{\\fad({t},{t})}}"
    if anim == 'pop':
        return f"{{\\fscx0\\fscy0\\t(0,{t},\\fscx100\\fscy100)}}"
    # slide: анкер — точка, куда libass поместил бы текст по Alignment (см.
    # обычные формулы ASS для \pos/\move), старт — со смещением за пределы
    # кадра со стороны, соответствующей горизонтали/вертикали выравнивания.
    row = (align - 1) // 3; col = (align - 1) % 3
    x = (_api._ASS_PLAYRES_X / 2 if col == 1
         else (_api._ASS_MARGIN_L if col == 0 else _api._ASS_PLAYRES_X - _api._ASS_MARGIN_R))
    y = (_api._ASS_PLAYRES_Y - _api._ASS_MARGIN_V if row == 0
         else (_api._ASS_PLAYRES_Y / 2 if row == 1 else _api._ASS_MARGIN_V))
    if col == 0:
        x0, y0 = -60, y
    elif col == 2:
        x0, y0 = _api._ASS_PLAYRES_X + 60, y
    elif row == 0:
        x0, y0 = x, _api._ASS_PLAYRES_Y + 40
    elif row == 2:
        x0, y0 = x, -40
    else:
        x0, y0 = x, y
    return f"{{\\move({x0:.0f},{y0:.0f},{x:.0f},{y:.0f},0,{t})}}"

_animation_override_tags.__module__ = _api.__name__
_api._animation_override_tags = _animation_override_tags

def _style_line(name, style):
    font = style.get('font') or _api.DEFAULT_SUBTITLE_STYLE['font']
    size = int(style.get('size') or _api.DEFAULT_SUBTITLE_STYLE['size'])
    bold = 1 if style.get('bold') else 0
    italic = 1 if style.get('italic') else 0
    underline = 1 if style.get('underline') else 0
    spacing = int(style.get('spacing') or 0)
    align = int(style.get('align') or 2)
    primary = _api._hex_to_ass_color(style.get('color') or '#FFFFFF')
    outline = _api._hex_to_ass_color(style.get('outline_color') or '#000000')
    return (f"Style: {name},{font},{size},{primary},&H000000FF,{outline},&H00000000,"
            f"{bold},{italic},{underline},0,100,100,{spacing},0,1,1,0,{align},"
            f"{_api._ASS_MARGIN_L},{_api._ASS_MARGIN_R},{_api._ASS_MARGIN_V},1")

_style_line.__module__ = _api.__name__
_api._style_line = _style_line
