# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Кинетический текст проекта: теги ASS появления, ухода и вида слова.
Public namespace: montage_project.

Стиль текста (TextItem.style) сверх прежнего (font, size, color, outline,
shadow, align, animation none/fade/slide/pop):
  animation  ещё blur_in (из размытия), slide_blur (влёт сбоку со смазом),
             grow (медленно растёт всю реплику до grow %), drop (падает
             сверху), zoom_out (из крупного), typewriter (по буквам),
             flash (вспышка белым при появлении), glitch (сбой: за in_s
             текст скачет масштабом, наклоном, местом и цветом — красный,
             голубой, белый — к своему виду);
  in_s/out_s длина появления и ухода, с;  out — none, fade, blur, glitch;
  letter_s   у typewriter — каждая буква проявляется за столько секунд из
             лёгкого размытия (0 — вспыхивает, как раньше);
  blur       размытие букв;  glow, glow_color — свечение (размытая обводка
             цвета glow_color толщиной glow);
  fill_alpha непрозрачность заливки букв (0 — полые буквы, только обводка);
             вместе с glow реплика — два события: ореол (размытая обводка
             цвета свечения, заливка скрыта) и над ним буквы с чёткой
             обводкой outline — неон;
  rotation   поворот (°, по часовой);  skew — наклон (\\fax);
  rot_x/rot_y наклон в глубину (°, \\frx/\\fry): текст лежит на полу,
             уходит в стену;
  vertical   знак под знаком (вертикальная японская строка; пробелы и
             переводы строк выбрасываются);
  scale_x/scale_y — %;  alpha — непрозрачность 0…1.
Шрифт — имя системного шрифта или псевдоним FONT_ALIASES (condensed —
Impact, serif — Georgia, script — Segoe Script, japanese — Yu Gothic…).

Реплика с новыми ключами всегда получает \\pos (без него libass раздвигал бы
перекрытые реплики) и свой текст с экранированием (у typewriter — теги
каждой буквы); старые реплики собираются прежними тегами побайтно."""
import math

FONT_ALIASES = {
    "condensed": "Impact", "impact": "Impact", "serif": "Georgia", "classic": "Times New Roman",
    "script": "Segoe Script", "hand": "Ink Free", "elegant": "Gabriola", "sans": "Arial",
    "wide": "Bahnschrift", "japanese": "Yu Gothic", "rounded": "Karaoke Rounded",
}
OLD_ANIMATIONS = ("none", "fade", "slide", "pop")
NEW_ANIMATIONS = ("blur_in", "slide_blur", "grow", "drop", "zoom_out", "typewriter", "flash",
                  "glitch")
ANIMATIONS = OLD_ANIMATIONS + NEW_ANIMATIONS
OUT_ANIMATIONS = ("none", "fade", "blur", "glitch")
# Новые ключи стиля: тип и пределы (schema). scale_x/scale_y знает и
# прежний _style_line (растяжение строки стиля).
STYLE_KEYS = {"in_s": (float, 0.0, 3.0), "out_s": (float, 0.0, 3.0), "out": (str, None, None),
              "blur": (float, 0.0, 30.0), "glow": (float, 0.0, 40.0), "glow_color": (str, None, None),
              "rotation": (float, -360.0, 360.0), "skew": (float, -2.0, 2.0),
              "scale_x": (float, 5.0, 500.0), "scale_y": (float, 5.0, 500.0),
              "grow": (float, 10.0, 400.0), "alpha": (float, 0.0, 1.0),
              "letter_s": (float, 0.0, 1.0), "fill_alpha": (float, 0.0, 1.0),
              "rot_x": (float, -89.0, 89.0), "rot_y": (float, -89.0, 89.0),
              "vertical": (bool, None, None)}
# Ступени сбоя (glitch) к своему виду: доля времени появления, масштаб по x и
# y, наклон \\fax, сдвиг в долях ширины холста, цвет букв и обводки.
_GLITCH_STEPS = ((0.0, 1.9, 1.2, 0.35, 0.05, "#ff2a4a"),
                 (0.3, 0.85, 1.5, -0.25, -0.03, "#3ae0ff"),
                 (0.6, 1.1, 0.92, 0.12, 0.012, "#ffffff"))
# Центр поворота сбоя — далеко под текстом: малый \\frz вокруг него сдвигает
# строку вбок (\\move ступенек не умеет).
_GLITCH_ORG = 10.0


def resolve_font(name):
    return FONT_ALIASES.get(str(name or "").strip().lower(), name)


def is_kinetic(style):
    """Нужны ли реплике новые теги (иначе — прежняя сборка побайтно)."""
    return (style.get("animation") in NEW_ANIMATIONS
            or any(k in style for k in STYLE_KEYS if k not in ("scale_x", "scale_y"))
            or str(style.get("font") or "").strip().lower() in FONT_ALIASES)


def _ass_alpha(a):
    return f"&H{int(round((1.0 - max(0.0, min(1.0, a))) * 255)):02X}&"


def _color(hex_color):
    hc = (hex_color or "#ffffff").lstrip("#")
    return f"&H{hc[4:6]}{hc[2:4]}{hc[0:2]}&".upper()


def default_pos(align, res_x, res_y):
    """Точка привязки по выравниванию, как её поставил бы libass (холст)."""
    col, row = (align - 1) % 3, (align - 1) // 3
    x = {0: 0.04, 1: 0.5, 2: 0.96}[col]
    y = {0: 0.93, 1: 0.5, 2: 0.07}[row]
    return x * res_x, y * res_y


def style_for_ass(style):
    """Стиль для строки Style: псевдоним шрифта; свечение — обводка цвета
    свечения (её размывает тег \\blur)."""
    out = dict(style)
    out["font"] = resolve_font(out.get("font"))
    if out.get("glow"):
        out["outline"] = float(out["glow"])
        out["outline_color"] = out.get("glow_color") or out.get("color") or "#ffffff"
    return out


def _escape(text):
    text = text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")


def vertical_text(text):
    """Вертикальная строка: знак под знаком, без пробелов и переводов строк."""
    return "\n".join(ch for ch in text if not ch.isspace())


def layers_of(style):
    """Стили событий реплики снизу вверх. С fill_alpha и glow — два: ореол
    (обводка толщиной glow цвета свечения, размытая, заливка скрыта) и сами
    буквы с чёткой обводкой outline; иначе — один стиль как есть."""
    if not (style.get("glow") and "fill_alpha" in style):
        return [style]
    body = {k: v for k, v in style.items() if k not in ("glow", "glow_color")}
    return [dict(style, fill_alpha=0.0), body]


def _alpha_tags(style, always=False):
    """\\alpha реплики и \\1a заливки (fill_alpha — доля от alpha); always —
    \\alpha и без ключа (конечный вид буквы у typewriter)."""
    a = float(style.get("alpha", 1.0))
    tags = f"\\alpha{_ass_alpha(a)}" if always or "alpha" in style else ""
    if "fill_alpha" in style:
        tags += f"\\1a{_ass_alpha(a * float(style['fill_alpha']))}"
    return tags


def _glitch_state(style, step, sx, sy, res_x, res_y, jitter):
    """Теги одной ступени сбоя (step из _GLITCH_STEPS) или своего вида (None)."""
    skew = float(style.get("skew", 0.0))
    edge = style.get("glow_color") if style.get("glow") else style.get("outline_color")
    if step is None:
        kx, ky, fax, dx = 1.0, 1.0, skew, 0.0
        fill, line = _color(style.get("color")), _color(edge or "#000000")
    else:
        _at, kx, ky, fax, dx, col = step
        fax += skew
        fill = line = _color(col)
    tags = f"\\fscx{sx * kx:g}\\fscy{sy * ky:g}\\fax{fax:g}\\1c{fill}\\3c{line}"
    if jitter:
        # Сдвиг вбок на dx ширины — поворот вокруг центра _GLITCH_ORG ниже.
        ang = math.degrees(math.asin(max(-1.0, min(1.0, dx * res_x / (_GLITCH_ORG * res_y)))))
        tags += f"\\frz{-ang:.3f}"
    return tags


def _glitch_in(style, t_in, sx, sy, res_x, res_y, jitter):
    """Появление сбоем: ступени _GLITCH_STEPS за t_in мс, затем свой вид."""
    tags = [_glitch_state(style, _GLITCH_STEPS[0], sx, sy, res_x, res_y, jitter)]
    for step in _GLITCH_STEPS[1:]:
        a = int(round(step[0] * t_in))
        tags.append(f"\\t({a},{a + 1},{_glitch_state(style, step, sx, sy, res_x, res_y, jitter)})")
    tags.append(f"\\t({t_in - 1},{t_in},{_glitch_state(style, None, sx, sy, res_x, res_y, jitter)})")
    return "".join(tags)


def _glitch_out(style, dur, t_out, sx, sy, res_x, res_y, jitter):
    """Уход сбоем: ступени в обратном порядке за последние t_out мс, потом
    реплика гаснет."""
    tags = []
    for frac, step in zip((0.0, 0.4, 0.7), reversed(_GLITCH_STEPS)):
        a = dur - t_out + int(round(frac * t_out))
        tags.append(f"\\t({a},{a + 1},{_glitch_state(style, step, sx, sy, res_x, res_y, jitter)})")
    tags.append(f"\\t({dur - 1},{dur},\\alpha&HFF&)")
    return "".join(tags)


def kinetic_text(style, text, duration_s, x, y, res_x, res_y):
    """Готовый текст реплики ASS: override-теги и экранированный текст."""
    dur = max(10, int(round(duration_s * 1000)))
    anim = style.get("animation", "none")
    t_in = int(round(1000 * float(style.get("in_s", min(0.3, max(0.06, duration_s / 3))))))
    t_in = max(1, min(t_in, dur))
    t_out = min(dur, int(round(1000 * float(style.get("out_s", 0.0)))))
    out = style.get("out", "none")
    align = int(style.get("align") or 2)
    sx = float(style.get("scale_x", 100))
    sy = float(style.get("scale_y", 100))
    blur = float(style.get("blur", 0.0))
    if style.get("glow"):
        blur = max(blur, float(style["glow"]) * 0.6)
    if style.get("vertical"):
        text = vertical_text(text)
    tags = [f"\\an{align}"]
    if "rotation" in style:
        tags.append(f"\\frz{-float(style['rotation']):g}")
    if "rot_x" in style:
        tags.append(f"\\frx{float(style['rot_x']):g}")
    if "rot_y" in style:
        tags.append(f"\\fry{float(style['rot_y']):g}")
    if "skew" in style:
        tags.append(f"\\fax{float(style['skew']):g}")
    if "alpha" in style or "fill_alpha" in style:
        tags.append(_alpha_tags(style))
    glitch_out = out == "glitch" and t_out > 0
    # Сдвиг сбоя — поворотом вокруг далёкого центра; свой поворот реплики
    # он испортил бы, поэтому с rotation/rot_x/rot_y сбой без сдвига.
    jitter = (anim == "glitch" or glitch_out) and not any(
        k in style for k in ("rotation", "rot_x", "rot_y"))
    if jitter:
        tags.append(f"\\org({x:.0f},{y + _GLITCH_ORG * res_y:.0f})")
    start = {"slide": (-60 * res_x / 384, 0), "slide_blur": (-140 * res_x / 384, 0),
             "drop": (0, -70 * res_y / 288)}.get(anim)
    if start:
        tags.append(f"\\move({x + start[0]:.0f},{y + start[1]:.0f},{x:.0f},{y:.0f},0,{t_in})")
    else:
        tags.append(f"\\pos({x:.0f},{y:.0f})")
    fade_in = {"fade": t_in, "blur_in": t_in, "zoom_out": t_in, "slide_blur": min(t_in, 120),
               "drop": min(t_in, 120)}.get(anim, 0)
    fade_out = t_out if out == "fade" else 0
    if fade_in or fade_out:
        tags.append(f"\\fad({fade_in},{fade_out})")
    if anim == "pop":
        tags.append(f"\\fscx0\\fscy0\\t(0,{t_in},\\fscx{sx:g}\\fscy{sy:g})")
    elif anim in ("blur_in", "slide_blur"):
        tags.append(f"\\blur{blur + (18 if anim == 'blur_in' else 12):g}\\t(0,{t_in},\\blur{blur:g})")
    elif anim == "grow":
        k = float(style.get("grow", 130.0)) / 100.0
        tags.append(f"\\fscx{sx:g}\\fscy{sy:g}\\t(0,{dur},\\fscx{sx * k:g}\\fscy{sy * k:g})")
    elif anim == "zoom_out":
        tags.append(f"\\fscx{sx * 2.2:g}\\fscy{sy * 2.2:g}\\t(0,{t_in},0.6,\\fscx{sx:g}\\fscy{sy:g})")
    elif anim == "flash":
        edge = style.get("glow_color") if style.get("glow") else style.get("outline_color")
        tags.append(f"\\1c&HFFFFFF&\\3c&HFFFFFF&\\t(0,{t_in},\\1c{_color(style.get('color'))}"
                    f"\\3c{_color(edge or '#000000')})")
    elif anim == "glitch":
        tags.append(_glitch_in(style, t_in, sx, sy, res_x, res_y, jitter))
    if blur and anim not in ("blur_in", "slide_blur"):
        tags.append(f"\\blur{blur:g}")
    if out == "blur" and t_out:
        tags.append(f"\\t({dur - t_out},{dur},\\blur20\\alpha&HFF&)")
    elif glitch_out:
        tags.append(_glitch_out(style, dur, t_out, sx, sy, res_x, res_y, jitter))
    body = _escape(text)
    if anim == "typewriter":
        chars = list(text.replace("\r", ""))
        step = t_in / max(1, len(chars))
        # Буква проявляется за letter_s из размытия (0 — вспыхивает) к виду
        # реплики: \\alpha (и \\1a заливки) стиля, а не всегда непрозрачная.
        fade = int(round(1000 * float(style.get("letter_s", 0.0))))
        final = _alpha_tags(style, always=True)
        soft = f"\\blur{blur + 4:g}" if fade else ""
        sharp = f"\\blur{blur:g}" if fade else ""
        parts = []
        for i, ch in enumerate(chars):
            if ch == "\n":
                parts.append("\\N")
            elif ch.strip():
                a = int(i * step)
                parts.append(f"{{\\alpha&HFF&{soft}\\t({a},{a + max(1, fade)},{final}{sharp})}}"
                             f"{_escape(ch)}")
            else:
                parts.append(ch)
        body = "".join(parts)
    return "{" + "".join(tags) + "}" + body
