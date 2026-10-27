# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Слои кадра: обрезка исходника, прямоугольник наложения, маска формы,
обводка, режим наложения и вырезанный персонаж. Public namespace: montage_project.

Поля клипа (v3, пустые — как раньше):
  crop   [x0, y0, x1, y1] — кусок кадра исходника (доли), до вписывания: у
         основной дорожки — рефрейм/зум, у наложения — что попадёт в панель;
  box    [ширина, высота] — прямоугольник наложения в долях кадра проекта
         вместо scale × кадр проекта (полосы, панели другой формы);
  mask   {shape: rect|ellipse|strip|polygon, …} — форма видимой части
         наложения в долях его прямоугольника: rect/ellipse — rect
         [x0, y0, x1, y1] (radius — скругление), strip — полоса через центр
         под углом angle (°) шириной width (доля высоты) со сдвигом offset,
         polygon — points [[x, y], …]; feather — размытие края (доля высоты),
         invert — наоборот. Маска — PNG в TEMP по хэшу (как .ass текста),
         в графе — альфа клипа × маска;
  stroke {width (доля высоты кадра), color, style: solid|torn, opacity} —
         обводка по альфе наложения (вырезанный персонаж, панель): альфа
         размывается и режется порогом (расширение), torn — край «рваной
         бумаги» неподвижным geq-смещением; цвет — lut, сам клип — поверх;
  blend  normal|screen|add|lighten|multiply|darken|overlay|softlight —
         как наложение смешивается с нижними слоями: клип кладётся на
         нейтральный холст (чёрный, белый или серый) и смешивается blend в
         gbrp (в YUV screen портил бы цветность);
  matte  anime | rmbg — персонаж без фона: кэш куска исходника с альфой
         (anime — ISNet anime-seg, ~2 с на кадр на CPU; rmbg — RMBG-2.0
         приложения, точнее на фото, ~50 с на кадр; готовит montage_tool
         enhance) подменяет исходник, как кэш RIFE.

Всё неподвижно во времени клипа (маска, рваный край) — кадр выдержки
по-прежнему равен кадру полной сборки."""
import hashlib
import math
import os
import re

import montage_project as _api

BLEND_MODES = ("normal", "screen", "add", "lighten", "multiply", "darken", "overlay",
               "softlight")
_BLEND_FF = {"screen": "screen", "add": "addition", "lighten": "lighten",
             "multiply": "multiply", "darken": "darken", "overlay": "overlay",
             "softlight": "softlight"}
_NEUTRAL = {"screen": "black", "add": "black", "lighten": "black", "multiply": "white",
            "darken": "white", "overlay": "0x808080", "softlight": "0x808080"}
MASK_SHAPES = ("rect", "ellipse", "strip", "polygon")
STROKE_STYLES = ("solid", "torn")
MATTE_MODELS = ("anime", "rmbg")
_MATTE_VERSION = 1
_COLOR_RX = re.compile(r"#[0-9A-Fa-f]{6}")
_MASK_SIDE = 1024                 # длинная сторона PNG маски (в графе — по размеру кадра)
MIN_PART = 0.02                   # кусок обрезки и сторона прямоугольника — не меньше


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and not isinstance(v, bool) else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── Мягкая чистка (Clip.__post_init__) ───────────────────────────────────────
def sanitize_crop(raw):
    """[x0, y0, x1, y1] в долях кадра или [] (весь кадр, неверное значение)."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return []
    v = [_num(x) for x in raw]
    if any(x is None for x in v):
        return []
    x0, y0, x1, y1 = (_clamp(x, 0.0, 1.0) for x in v)
    if x1 - x0 < MIN_PART or y1 - y0 < MIN_PART:
        return []
    if (x0, y0, x1, y1) == (0.0, 0.0, 1.0, 1.0):
        return []
    return [round(x, 6) for x in (x0, y0, x1, y1)]


def sanitize_box(raw):
    """[ширина, высота] в долях кадра проекта или []."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return []
    v = [_num(x) for x in raw]
    if any(x is None for x in v):
        return []
    return [round(_clamp(x, MIN_PART, _api.MAX_SCALE), 6) for x in v]


def sanitize_mask(raw):
    if not isinstance(raw, dict) or raw.get("shape") not in MASK_SHAPES:
        return {}
    out = {"shape": raw["shape"]}
    if out["shape"] in ("rect", "ellipse"):
        r = raw.get("rect")
        if isinstance(r, (list, tuple)) and len(r) == 4 and all(_num(x) is not None for x in r):
            x0, y0, x1, y1 = (_clamp(float(x), -1.0, 2.0) for x in r)
            if x1 - x0 >= MIN_PART and y1 - y0 >= MIN_PART:
                out["rect"] = [round(x, 6) for x in (x0, y0, x1, y1)]
        rad = _num(raw.get("radius"))
        if rad is not None and out["shape"] == "rect":
            out["radius"] = round(_clamp(rad, 0.0, 0.5), 6)
    elif out["shape"] == "strip":
        for k, lo, hi, dflt in (("angle", -89.0, 89.0, 20.0), ("width", MIN_PART, 2.0, 0.35),
                                ("offset", -1.0, 1.0, 0.0)):
            v = _num(raw.get(k))
            out[k] = round(_clamp(dflt if v is None else v, lo, hi), 6)
    else:
        pts = []
        for p in raw.get("points") or []:
            if isinstance(p, (list, tuple)) and len(p) == 2 and all(_num(x) is not None for x in p):
                pts.append([round(_clamp(float(x), -1.0, 2.0), 6) for x in p])
        if not 3 <= len(pts) <= 64:
            return {}
        out["points"] = pts
    f = _num(raw.get("feather"))
    if f is not None and f > 0:
        out["feather"] = round(_clamp(f, 0.0, 0.2), 6)
    if raw.get("invert") is True:
        out["invert"] = True
    return out


def sanitize_stroke(raw):
    if not isinstance(raw, dict):
        return {}
    w = _num(raw.get("width"))
    if w is None or w <= 0:
        return {}
    out = {"width": round(_clamp(w, 0.001, 0.08), 6)}
    color = raw.get("color", "#ffffff")
    out["color"] = color.lower() if isinstance(color, str) and _COLOR_RX.fullmatch(color) else "#ffffff"
    out["style"] = raw.get("style") if raw.get("style") in STROKE_STYLES else "solid"
    op = _num(raw.get("opacity"))
    if op is not None and op < 1.0:
        out["opacity"] = round(_clamp(op, 0.0, 1.0), 6)
    return out


def sanitize_blend(raw):
    return raw if raw in BLEND_MODES and raw != "normal" else ""


def sanitize_matte(raw):
    return raw if raw in MATTE_MODELS else ""


# ── Обрезка и прямоугольник ──────────────────────────────────────────────────
def crop_filter(c):
    """crop куска исходника (после квадратного пикселя, до вписывания), с
    запятой в конце, или ""."""
    if not c.crop:
        return ""
    x0, y0, x1, y1 = c.crop
    n = _api._num
    return (f"crop=w='trunc(iw*{n(x1 - x0)}/2)*2':h='trunc(ih*{n(y1 - y0)}/2)*2':"
            f"x='trunc(iw*{n(x0)})':y='trunc(ih*{n(y0)})',")


def box_size(c, w, h):
    """(ширина, высота) прямоугольника наложения в пикселях кадра проекта."""
    if c.box:
        bw, bh = w * c.box[0], h * c.box[1]
    else:
        bw, bh = w * c.scale, h * c.scale
    return max(2, int(round(bw / 2.0)) * 2), max(2, int(round(bh / 2.0)) * 2)


# ── Маска ────────────────────────────────────────────────────────────────────
def mask_png(mask, bw, bh):
    """PNG маски (белое — видно) размером по пропорциям прямоугольника; путь
    в TEMP по хэшу описания (тот же — тот же файл)."""
    from PIL import Image, ImageDraw, ImageFilter
    from ffmpeg_env import TEMP_DIR
    k = _MASK_SIDE / float(max(bw, bh))
    W, H = max(2, int(round(bw * k))), max(2, int(round(bh * k)))
    key = hashlib.sha1(repr((sorted(mask.items()), W, H)).encode("utf-8")).hexdigest()[:16]
    path = os.path.join(TEMP_DIR, f"sihyx_mask_{key}.png")
    if os.path.isfile(path):
        return path
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    shape = mask["shape"]
    if shape in ("rect", "ellipse"):
        x0, y0, x1, y1 = mask.get("rect", [0.0, 0.0, 1.0, 1.0])
        box = [x0 * W, y0 * H, x1 * W - 1, y1 * H - 1]
        if shape == "ellipse":
            d.ellipse(box, fill=255)
        elif mask.get("radius"):
            d.rounded_rectangle(box, radius=mask["radius"] * min(W, H), fill=255)
        else:
            d.rectangle(box, fill=255)
    elif shape == "strip":
        a = math.radians(mask["angle"])
        ux, uy = math.cos(a), -math.sin(a)          # вдоль полосы (угол против часовой)
        nx, ny = -uy, ux                            # поперёк
        cx = W / 2 + nx * mask["offset"] * H
        cy = H / 2 + ny * mask["offset"] * H
        half, far = mask["width"] * H / 2, 2 * (W + H)
        pts = [(cx + ux * s * far + nx * t * half, cy + uy * s * far + ny * t * half)
               for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        d.polygon(pts, fill=255)
    else:
        d.polygon([(x * W, y * H) for x, y in mask["points"]], fill=255)
    if mask.get("feather"):
        img = img.filter(ImageFilter.GaussianBlur(mask["feather"] * H))
    if mask.get("invert"):
        img = img.point(lambda v: 255 - v)
    tmp = f"{path}.{os.getpid()}.tmp.png"
    img.save(tmp)
    os.replace(tmp, path)
    return path


def mask_chain(g, mask, bw, bh, n, rate, label):
    """Хвост цепочки наложения: альфа × маска. Начинается с метки входа
    (цепочка до него кончается [label]), выход — без метки, ровно n кадров."""
    png = mask_png(mask, bw, bh)
    idx = len(g.inputs)
    g.inputs.append(["-loop", "1", "-framerate", rate, "-t", _api._num(n / _fps(rate) + 1.0),
                     "-i", png])
    a, b, al, m0, m1, al2, al3 = (g.label(x) for x in ("ma", "mb", "mal", "mm", "mn", "mr", "mx"))
    return (f"[{label}]format=yuva420p,split[{a}][{b}];[{b}]alphaextract[{al}];"
            f"[{idx}:v]format=gray[{m0}];[{m0}][{al}]scale2ref[{m1}][{al2}];"
            f"[{al2}][{m1}]blend=all_mode=multiply[{al3}];"
            f"[{a}][{al3}]alphamerge,trim=end_frame={n},setpts=PTS-STARTPTS")


def _fps(rate):
    num, _, den = str(rate).partition("/")
    return float(num) / float(den or 1)


# ── Обводка ──────────────────────────────────────────────────────────────────
def _yuv(color):
    """#rrggbb → Y, U, V (BT.709, ограниченный диапазон)."""
    r, g, b = (int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    u = (b - y) / 1.8556
    v = (r - y) / 1.5748
    return (int(round(16 + 219 * y)), int(round(128 + 224 * u)), int(round(128 + 224 * v)))


def stroke_chain(g, stroke, h, label):
    """Обводка по альфе (см. модуль): вход — [label], выход — без метки."""
    px = max(1, int(round(stroke["width"] * h)))
    pad = 2 * px + 2
    sig = max(0.5, px / 2.0)
    y, u, v = _yuv(stroke["color"])
    s0, s1, sil = g.label("sa"), g.label("sb"), g.label("sc")
    tail = ""
    if stroke.get("style") == "torn":
        # Неровный край: три синуса несоизмеримых частот (крупная волна,
        # средняя и мелкая рвань) — без повторяющихся зубцов. Точка выборки —
        # внутри кадра: geq интерполирует соседа справа/снизу, и за краем он
        # читал бы неинициализированный запас строки (кадр плавал от сборки
        # к сборке).
        k = 1080.0 / max(1, h)
        amp = max(1.0, px * 0.8)

        def wob(v, ph):
            return (f"{amp:.2f}*sin({v}*{0.047 * k:.4f}+{ph})"
                    f"+{amp * 0.55:.2f}*sin({v}*{0.161 * k:.4f}+{ph + 1.1:.1f})"
                    f"+{amp * 0.3:.2f}*sin({v}*{0.613 * k:.4f}+{ph + 2.3:.1f})")
        tail = (f",geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
                f"a='alpha(clip(X+{wob('Y', 1.3)},0,W-2),clip(Y+{wob('X', 0.4)},0,H-2))'")
    op = stroke.get("opacity", 1.0)
    fade = f",lut=a='val*{_api._num(op)}'" if op < 1.0 else ""
    return (f"[{label}]format=yuva420p,pad=iw+{2 * pad}:ih+{2 * pad}:{pad}:{pad}:color=black@0,"
            f"split[{s0}][{s1}];"
            f"[{s1}]lut=y={y}:u={u}:v={v},gblur=sigma={_api._num(sig)}:planes=8,"
            f"lut=a='if(gt(val,20),255,0)'{tail},gblur=sigma=0.6:planes=8{fade}[{sil}];"
            # Один поток: overlay на кадр с альфой по срезам гоняется на их
            # стыке (цветность пары строк читала альфу соседнего среза) —
            # пиксели обводки плавали от сборки к сборке.
            f"[{sil}][{s0}]overlay=format=yuv420:threads=1")


# ── Режим наложения ──────────────────────────────────────────────────────────
def blend_composite(g, cur, lab, mode, ox, oy, w, h, rate, frames):
    """Наложение [lab] на [cur] в режиме mode: на нейтральном холсте, затем
    blend в gbrp. Метка итога."""
    cv, ov, a, b, out = (g.label(x) for x in ("bc", "bo", "ba", "bb", "c"))
    g.chains.append(f"color=c={_NEUTRAL[mode]}:s={w}x{h}:r={rate},trim=end_frame={frames},"
                    f"setsar=1,format=yuv420p[{cv}]")
    g.chains.append(f"[{cv}][{lab}]overlay=x={ox}:y={oy}:eof_action=pass:format=yuv420[{ov}]")
    g.chains.append(f"[{cur}]format=gbrp[{a}]")
    g.chains.append(f"[{ov}]format=gbrp[{b}]")
    g.chains.append(f"[{a}][{b}]blend=all_mode={_BLEND_FF[mode]},format=yuv420p[{out}]")
    return out


# ── Вырезанный персонаж (кэш с альфой) ───────────────────────────────────────
def matte_span(c):
    """Кусок исходника под кэш: (начало, конец) секунды исходника."""
    if c.frozen:
        step = 1.0 / c.fps if c.fps and c.fps > 0 else 0.04
        return c.freeze_at, c.freeze_at + 2 * step
    return c.in_s, c.out_s


def matte_key(c):
    try:
        st = os.stat(c.src)
        stamp = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        stamp = "missing"
    a, b = matte_span(c)
    raw = (f"{os.path.abspath(c.src)}|{stamp}|{a:.6f}|{b:.6f}|{c.matte}|"
           f"v{_MATTE_VERSION}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def matte_path(c):
    from si_hyx_parts.montage_project.vulkan_fx import cache_root
    return os.path.join(cache_root(), "matte", f"{matte_key(c)}.mkv")


def matte_wanted(c):
    return bool(c.matte) and c.has_video and not c.is_image


def matte_source(c):
    """Клип-заместитель: исходник — кэш с альфой (кусок с нуля) или None."""
    if not matte_wanted(c):
        return None
    path = matte_path(c)
    if not os.path.isfile(path):
        return None
    from dataclasses import replace
    a, b = matte_span(c)
    if c.frozen:
        return replace(c, src=path, freeze_at=0.0, src_duration=b - a, matte="")
    return replace(c, src=path, in_s=0.0, out_s=b - a, src_duration=b - a, matte="")
