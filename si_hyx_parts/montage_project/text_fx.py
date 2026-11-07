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
  scale_x/scale_y — %;  alpha — непрозрачность 0…1;
  grunge     0…1 — потёртые буквы: мелкие дыры (\\iclip-рисунок по месту
             текста, узор — по тексту и месту, у окна тот же);
  scratch    0…1 — горизонтальные царапины-просветы по буквам;
  plate      0…1 — тёмная размытая плашка под текстом (событие под буквами:
             толстая размытая обводка цвета plate_color без заливки);
  chroma     px при 1080 — хроматика: красная и голубая копии букв, сдвинутые
             влево и вправо, под самим текстом;
  spread     разрядка растёт за всю реплику на столько (\\fsp, холст);
  letter_colors — цвета букв по кругу (две краски, «записка с вырезками»);
  dropout    0…1 — сбой букв: отдельные буквы ненадолго пропадают (узор и
             моменты — по crc32 текста, у копий те же);
  window     0…1 — буквы-окно: поверх букв граф кладёт тот же кадр с
             другим светом (window_light — eq brightness), насыщенностью
             (window_saturation) и тоном (window_tint) — маской из этих же
             букв (window_mask_style), с силой window;
  window_invert в буквах-окне негатив кадра: белые буквы в режиме
             «разница» — на тёмном кадре светлые, на светлом — в
             дополнительном цвете (свет и насыщенность по умолчанию — как
             у кадра: 0 и 1).
animation ещё flicker (мигает за in_s и остаётся), track_in (буквы
съезжаются из широкой разрядки); out — ещё flicker и letters (буквы гаснут
по одной в случайном порядке за out_s).
Шрифт — имя системного шрифта или псевдоним FONT_ALIASES (condensed —
Impact, serif — Georgia, script — Segoe Script, japanese — Yu Gothic…).

Реплика с новыми ключами всегда получает \\pos (без него libass раздвигал бы
перекрытые реплики) и свой текст с экранированием (у typewriter — теги
каждой буквы); старые реплики собираются прежними тегами побайтно."""
import math
import random
import zlib

FONT_ALIASES = {
    "condensed": "Impact", "impact": "Impact", "serif": "Georgia", "classic": "Times New Roman",
    "script": "Segoe Script", "hand": "Ink Free", "elegant": "Gabriola", "sans": "Arial",
    "wide": "Bahnschrift", "japanese": "Yu Gothic", "rounded": "Karaoke Rounded",
}
OLD_ANIMATIONS = ("none", "fade", "slide", "pop")
NEW_ANIMATIONS = ("blur_in", "slide_blur", "grow", "drop", "zoom_out", "typewriter", "flash",
                  "glitch", "flicker", "track_in")
ANIMATIONS = OLD_ANIMATIONS + NEW_ANIMATIONS
OUT_ANIMATIONS = ("none", "fade", "blur", "glitch", "flicker", "letters")
# Новые ключи стиля: тип и пределы (schema). scale_x/scale_y знает и
# прежний _style_line (растяжение строки стиля).
STYLE_KEYS = {"in_s": (float, 0.0, 3.0), "out_s": (float, 0.0, 3.0), "out": (str, None, None),
              "blur": (float, 0.0, 30.0), "glow": (float, 0.0, 40.0), "glow_color": (str, None, None),
              "rotation": (float, -360.0, 360.0), "skew": (float, -2.0, 2.0),
              "scale_x": (float, 5.0, 500.0), "scale_y": (float, 5.0, 500.0),
              "grow": (float, 10.0, 400.0), "alpha": (float, 0.0, 1.0),
              "letter_s": (float, 0.0, 1.0), "fill_alpha": (float, 0.0, 1.0),
              "rot_x": (float, -89.0, 89.0), "rot_y": (float, -89.0, 89.0),
              "vertical": (bool, None, None),
              "grunge": (float, 0.0, 1.0), "scratch": (float, 0.0, 1.0),
              "plate": (float, 0.0, 1.0), "plate_color": (str, None, None),
              "chroma": (float, 0.0, 40.0), "spread": (float, 0.0, 400.0),
              "letter_colors": (list, None, None), "dropout": (float, 0.0, 1.0),
              "window": (float, 0.0, 1.0), "window_light": (float, -1.0, 1.0),
              "window_saturation": (float, 0.0, 3.0), "window_tint": (str, None, None),
              "window_invert": (bool, None, None)}
# Ключи стиля цветом #RRGGBB (schema, окно свойств текста).
COLOR_KEYS = ("glow_color", "plate_color", "window_tint")
# Буквы-окно без своих значений: свет и насыщенность кадра в буквах.
WINDOW_LIGHT, WINDOW_SATURATION = 0.3, 1.25
# Сбой букв (dropout): пропаданий у буквы не больше, длина пропадания, мс.
_DROPOUT_MAX, _DROPOUT_MS = 6, (40, 160)
# Цвета копий хроматики: левая, правая.
_CHROMA = ("#ff1a3c", "#1ad8ff")
# Мигание (flicker): доли in_s/out_s, где реплика видна (чётные — скрыта).
_FLICKER = (0.0, 0.18, 0.34, 0.5, 0.64, 0.8)
# Дыр гранжа и царапин в реплике не больше (длина рисунка \\iclip).
_MAX_HOLES, _MAX_SCRATCHES = 320, 48
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
    буквы с чёткой обводкой outline; иначе — один стиль как есть. Под ними —
    плашка (plate) и копии хроматики (chroma): ключ _part, сдвиг копии — _dx."""
    if not (style.get("glow") and "fill_alpha" in style):
        main = [style]
    else:
        body = {k: v for k, v in style.items() if k not in ("glow", "glow_color")}
        main = [dict(style, fill_alpha=0.0), body]
    under = []
    if style.get("plate"):
        under.append(dict(style, _part="plate"))
    d = float(style.get("chroma", 0.0) or 0.0)
    if d:
        ghost = {k: v for k, v in style.items()
                 if k not in ("glow", "glow_color", "fill_alpha", "plate", "letter_colors")}
        for dx, col in ((-d, _CHROMA[0]), (d, _CHROMA[1])):
            under.append(dict(ghost, color=col, outline=0, shadow=0,
                              alpha=0.85 * float(style.get("alpha", 1.0)), _part="chroma", _dx=dx))
    return under + main


def window_spec(style):
    """Вид кадра в буквах-окне — ключ группы маски: (сила, свет,
    насыщенность, тон, негатив) или None, если window не задан. У негатива
    (window_invert) свет и насыщенность по умолчанию — как у кадра."""
    a = min(1.0, float(style.get("window", 0.0) or 0.0))
    if a <= 0:
        return None
    invert = bool(style.get("window_invert"))
    light, sat = (0.0, 1.0) if invert else (WINDOW_LIGHT, WINDOW_SATURATION)
    return (round(a, 3), round(float(style.get("window_light", light)), 3),
            round(float(style.get("window_saturation", sat)), 3),
            str(style.get("window_tint") or "").lower(), invert)


def window_mask_style(style):
    """Стиль маски букв-окна: белые буквы с той же анимацией и местом, без
    обводки, тени, свечения, плашки и хроматики; непрозрачность — alpha ×
    fill_alpha × window (на чёрном холсте это и есть альфа окна)."""
    out = {k: v for k, v in style.items()
           if k not in ("glow", "glow_color", "plate", "plate_color", "chroma", "letter_colors",
                        "fill_alpha")}
    out.update(color="#ffffff", outline_color="#ffffff", outline=0, shadow=0,
               alpha=float(style.get("alpha", 1.0)) * float(style.get("fill_alpha", 1.0))
               * min(1.0, float(style.get("window", 0.0) or 0.0)))
    return out


def _letter_tags(style, text, dur, t_in, t_out, blur):
    """Теги каждой видимой буквы (по порядку) для ухода letters и сбоя
    dropout; пустые строки — буквам ничего не нужно. Порядок ухода и
    моменты сбоя — по crc32 текста: у копий хроматики и маски окна те же."""
    n = sum(1 for ch in text if ch.strip())
    tags = [""] * n
    if not n:
        return tags
    final = _alpha_tags(style, always=True)
    if style.get("out") == "letters" and t_out > 0:
        order = list(range(n))
        random.Random(zlib.crc32(f"out|{text}".encode("utf-8"))).shuffle(order)
        fade = max(1, int(t_out * 0.4))
        step = (t_out - fade) / max(1, n - 1)
        for rank, i in enumerate(order):
            a = dur - t_out + int(rank * step)
            tags[i] += f"\\t({a},{a + fade},\\blur{blur + 6:g}\\alpha&HFF&)"
    drop = float(style.get("dropout", 0.0) or 0.0)
    lo, hi = t_in, dur - (t_out if style.get("out", "none") != "none" else 0)
    if drop > 0 and hi - lo > _DROPOUT_MS[1] * 2:
        count = min(_DROPOUT_MAX, max(1, int(round(drop * (hi - lo) / 2000.0))))
        for i in range(n):
            rnd = random.Random(zlib.crc32(f"drop|{text}|{i}".encode("utf-8")))
            if rnd.random() > drop:
                continue
            marks = sorted(rnd.randint(lo, hi - _DROPOUT_MS[1]) for _k in range(count))
            end = lo
            for a in marks:
                if a < end:
                    continue
                b = a + rnd.randint(*_DROPOUT_MS)
                tags[i] += f"\\t({a},{a + 1},\\alpha&HFF&)\\t({b},{b + 1},{final})"
                end = b + 1
    return tags


def _text_box(style, text, x, y):
    """Прямоугольник текста на холсте с запасом (оценка по числу знаков: у
    \\iclip дыры вне букв ничего не меняют) — (x0, y0, x1, y1)."""
    size = float(style.get("size", 48))
    lines = (vertical_text(text) if style.get("vertical") else text).split("\n") or [""]
    sx = float(style.get("scale_x", 100)) / 100.0
    sy = float(style.get("scale_y", 100)) / 100.0
    sp = float(style.get("spacing", 0) or 0) + float(style.get("spread", 0) or 0)
    w = max(len(line) for line in lines) * (size * 0.78 * sx + max(0.0, sp)) + size * 0.4
    h = len(lines) * size * 1.15 * sy + size * 0.3
    align = int(style.get("align") or 2)
    col, row = (align - 1) % 3, (align - 1) // 3
    x0 = x - w * (0.0, 0.5, 1.0)[col]
    y0 = y - h * (1.0, 0.5, 0.0)[row]
    return x0, y0, x0 + w, y0 + h


def _grunge_clip(style, text, x, y):
    """\\iclip(рисунок) дыр гранжа и царапин в месте текста или ""; узор
    детерминирован (crc32 текста, кегля и места)."""
    g, s = float(style.get("grunge", 0) or 0), float(style.get("scratch", 0) or 0)
    if g <= 0 and s <= 0:
        return ""
    size = float(style.get("size", 48))
    x0, y0, x1, y1 = _text_box(style, text, x, y)
    rnd = random.Random(zlib.crc32(f"{text}|{size:g}|{x:.0f}|{y:.0f}".encode("utf-8")))
    shapes = []
    r_min, r_max = size * 0.01, size * 0.035
    n = int(min(_MAX_HOLES, g * (x1 - x0) * (y1 - y0) / max(1.0, (size * 0.09) ** 2)))
    for _k in range(n):
        cx, cy = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        r = rnd.uniform(r_min, r_max)
        pts = []
        for j in range(5):                   # неровная клякса из 5 точек
            a = j * 2 * math.pi / 5 + rnd.uniform(-0.4, 0.4)
            rr = r * rnd.uniform(0.55, 1.25)
            pts.append(f"{cx + rr * math.cos(a):.1f} {cy + rr * math.sin(a):.1f}")
        shapes.append(f"m {pts[0]} l {' '.join(pts[1:])}")
    for _k in range(int(min(_MAX_SCRATCHES, s * 40))):
        cy = rnd.uniform(y0 + (y1 - y0) * 0.15, y1 - (y1 - y0) * 0.15)
        ln = rnd.uniform(0.08, 0.5) * (x1 - x0)
        cx = rnd.uniform(x0, x1 - ln)
        th = min(rnd.uniform(0.012, 0.03) * size, rnd.uniform(0.6, 1.4))
        shapes.append(f"m {cx:.1f} {cy:.1f} l {cx + ln:.1f} {cy + th * 0.3:.1f} "
                      f"{cx + ln:.1f} {cy + th:.1f} {cx:.1f} {cy + th * 0.7:.1f}")
    return f"\\iclip({' '.join(shapes)})" if shapes else ""


_HIDE = "\\alpha&HFF&"


def _flicker_in(final, t_in):
    """Мигание при появлении: скрыта, видна, скрыта… — к виду final."""
    tags = [_HIDE]
    for i, frac in enumerate(_FLICKER[1:], 1):
        a = int(round(frac * t_in))
        tags.append(f"\\t({a},{a + 1},{final if i % 2 else _HIDE})")
    return "".join(tags)


def _flicker_out(final, dur, t_out):
    """Мигание при уходе за последние t_out мс, в конце реплика скрыта."""
    tags = []
    for i, frac in enumerate(_FLICKER[1:], 1):
        a = dur - t_out + int(round(frac * t_out))
        tags.append(f"\\t({a},{a + 1},{_HIDE if i % 2 else final})")
    tags.append(f"\\t({dur - 1},{dur},{_HIDE})")
    return "".join(tags)


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
    """Готовый текст реплики ASS: override-теги и экранированный текст.
    Часть _part (layers_of): plate — плашка (буквы скрыты, видна толстая
    размытая обводка; мигание и сбой у неё — плавным появлением), chroma —
    цветная копия, сдвинутая на _dx (px при 1080)."""
    dur = max(10, int(round(duration_s * 1000)))
    part = style.get("_part")
    anim = style.get("animation", "none")
    out = style.get("out", "none")
    if part == "plate":
        anim = "fade" if anim in ("typewriter", "flicker", "glitch", "flash", "track_in") else anim
        out = "fade" if out in ("glitch", "flicker") else out
    t_in = int(round(1000 * float(style.get("in_s", min(0.3, max(0.06, duration_s / 3))))))
    t_in = max(1, min(t_in, dur))
    t_out = min(dur, int(round(1000 * float(style.get("out_s", 0.0)))))
    align = int(style.get("align") or 2)
    sx = float(style.get("scale_x", 100))
    sy = float(style.get("scale_y", 100))
    blur = float(style.get("blur", 0.0))
    if style.get("glow"):
        blur = max(blur, float(style["glow"]) * 0.6)
    if style.get("vertical"):
        text = vertical_text(text)
    # Узор гранжа — от места самой реплики, у копий хроматики дыры там же
    # (не сдвинуты): сквозь дыру букв не просвечивает цветная копия.
    grunge = "" if part == "plate" else _grunge_clip(style, text, x, y)
    x += float(style.get("_dx", 0.0) or 0.0) * res_y / 1080.0
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
               "drop": min(t_in, 120), "track_in": min(t_in, 150)}.get(anim, 0)
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
    elif anim == "flicker":
        tags.append(_flicker_in(_alpha_tags(style, always=True), t_in))
    sp0 = float(style.get("spacing", 0) or 0)
    spread = float(style.get("spread", 0) or 0)
    if anim == "track_in":
        wide = sp0 + float(style.get("size", 48)) * 0.9
        tags.append(f"\\fsp{wide:g}\\t(0,{t_in},0.5,\\fsp{sp0:g})")
    if spread:
        a = t_in if anim == "track_in" else 0
        tags.append(f"\\t({a},{dur},\\fsp{sp0 + spread:g})")
    if blur and anim not in ("blur_in", "slide_blur"):
        tags.append(f"\\blur{blur:g}")
    if out == "blur" and t_out:
        tags.append(f"\\t({dur - t_out},{dur},\\blur20\\alpha&HFF&)")
    elif glitch_out:
        tags.append(_glitch_out(style, dur, t_out, sx, sy, res_x, res_y, jitter))
    elif out == "flicker" and t_out:
        tags.append(_flicker_out(_alpha_tags(style, always=True), dur, t_out))
    if part == "plate":
        size = float(style.get("size", 48))
        a = float(style.get("plate", 0.6)) * float(style.get("alpha", 1.0))
        tags.append(f"\\1a&HFF&\\3c{_color(style.get('plate_color') or '#000000')}"
                    f"\\3a{_ass_alpha(a)}\\bord{size * 0.36:.1f}\\shad0\\blur{size * 0.24:.1f}")
        return "{" + "".join(tags) + "}" + _escape(text)
    tags.append(grunge)
    body = _escape(text)
    colors = [] if part else [c for c in style.get("letter_colors") or [] if isinstance(c, str)]
    # Уход по буквам и сбой букв — теги у каждой буквы (пусто — как раньше).
    extra = _letter_tags(style, text.replace("\r", ""), dur, t_in, t_out, blur)
    if (colors or any(extra)) and anim != "typewriter":
        parts, i = [], 0
        for ch in text.replace("\r", ""):
            if ch == "\n":
                parts.append("\\N")
            elif ch.strip():
                col = f"\\1c{_color(colors[i % len(colors)])}" if colors else ""
                own = col + extra[i]
                parts.append(f"{{{own}}}{_escape(ch)}" if own else _escape(ch))
                i += 1
            else:
                parts.append(ch)
        body = "".join(parts)
    if anim == "typewriter":
        chars = list(text.replace("\r", ""))
        step = t_in / max(1, len(chars))
        # Буква проявляется за letter_s из размытия (0 — вспыхивает) к виду
        # реплики: \\alpha (и \\1a заливки) стиля, а не всегда непрозрачная.
        fade = int(round(1000 * float(style.get("letter_s", 0.0))))
        final = _alpha_tags(style, always=True)
        soft = f"\\blur{blur + 4:g}" if fade else ""
        sharp = f"\\blur{blur:g}" if fade else ""
        parts, k = [], 0
        for i, ch in enumerate(chars):
            if ch == "\n":
                parts.append("\\N")
            elif ch.strip():
                a = int(i * step)
                col = f"\\1c{_color(colors[k % len(colors)])}" if colors else ""
                parts.append(f"{{\\alpha&HFF&{soft}{col}\\t({a},{a + max(1, fade)},{final}{sharp})"
                             f"{extra[k]}}}{_escape(ch)}")
                k += 1
            else:
                parts.append(ch)
        body = "".join(parts)
    return "{" + "".join(tags) + "}" + body
