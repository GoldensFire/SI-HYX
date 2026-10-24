# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ключевые кадры, эффекты и плавная скорость клипа в графе ffmpeg.
Public namespace: montage_project.

Всё — во времени КЛИПА: клип с ключевыми кадрами, эффектами или кривой
скорости собирается всегда с первого своего кадра (кадр n цепочки — n-й
кадр клипа), а кусок окна вырезается после эффектов. Так кадр выдержки
(still, preview) побайтно равен кадру полной сборки: у эффекта нет
«начала окна», а временные фильтры (tmix) видят те же соседние кадры.

Ключевые кадры (Clip.keyframes): {свойство: [{"t": с от начала клипа, "v":
значение, "ease": linear|ease_in|ease_out|ease_in_out|hold}]} для pos_x,
pos_y, scale, rotation (градусы), opacity. На основной дорожке scale ≥ 1 —
зум внутрь кадра, pos_x/pos_y — центр видимой части (доли кадра),
rotation — поворот: всё одним perspective (eval=frame, номер кадра in).
У наложения pos — overlay x/y, scale — scale eval=frame (кадр переменного
размера overlay принимает), rotation — rotate с прозрачным полем, opacity —
geq альфы.

Эффекты (Clip.effects): список {"type": …, "on": вид маркера или список
времён проекта, "section": подпись части, "amount", "decay" (с), …}.
Без "on" — на весь клип (виньетка, цвет, свечение, смаз) или один раз в
начале клипа (зум-удар, тряска, вспышка, RGB-сдвиг). С "on" — по маркерам
проекта внутри клипа (детерминированно): огибающая Σ amount·exp(−Δ/decay).
  zoom_punch  — зум +amount в момент удара (perspective);
  shake       — тряска на amount доли кадра (псевдослучайно по номеру кадра);
  flash       — заливка color с непрозрачностью amount, гаснет за decay
                (drawbox по кадрам: enable по номеру кадра);
  rgb_shift   — сдвиг каналов на amount пикселей (rgbashift по уровням);
  glow        — свечение: gblur sigma + screen с непрозрачностью amount;
  motion_blur — смаз движения: tmix по frames кадрам;
  vignette    — виньетка, angle (рад);
  color       — lut3d (.cube), eq (contrast, brightness, saturation, gamma),
                curves (preset).

Кривая скорости (Clip.speed_curve): [{"at": доля куска исходника 0…1,
"speed": скорость}] — скорость линейна по исходнику между точками; время
клипа τ(s) = ∫ ds / v(s) — по кускам (1/b)·ln(1 + b·s/a), setpts по нему,
длина клипа — τ(конец). Звук такого клипа по умолчанию выключен
(curve_audio — rubberband с командами tempo)."""
import math
import re

import montage_project as _api

KEYFRAME_PROPS = ("pos_x", "pos_y", "scale", "rotation", "opacity")
EASES = ("linear", "ease_in", "ease_out", "ease_in_out", "hold")
EFFECT_TYPES = ("zoom_punch", "shake", "flash", "rgb_shift", "glow", "motion_blur",
                "vignette", "color")
CURVES_PRESETS = ("none", "color_negative", "cross_process", "darker", "increase_contrast",
                  "lighter", "linear_contrast", "medium_contrast", "negative",
                  "strong_contrast", "vintage")
# Пределы чисел эффектов (validate): поле → (мин, макс).
EFFECT_LIMITS = {"amount": (0.0, 64.0), "decay": (0.01, 5.0), "sigma": (0.5, 100.0),
                 "frames": (2, 16), "angle": (0.0, 1.5707963), "contrast": (0.0, 3.0),
                 "brightness": (-1.0, 1.0), "saturation": (0.0, 3.0), "gamma": (0.1, 10.0)}
_ONE_SHOT = ("zoom_punch", "shake", "flash", "rgb_shift")
_DEFAULTS = {"zoom_punch": {"amount": 0.08, "decay": 0.25},
             "shake": {"amount": 0.02, "decay": 0.3},
             "flash": {"amount": 0.8, "decay": 0.15, "color": "#ffffff"},
             "rgb_shift": {"amount": 8.0, "decay": 0.2},
             "glow": {"amount": 0.45, "sigma": 18.0, "decay": 0.3},
             "motion_blur": {"frames": 3},
             "vignette": {"angle": 0.6},
             "color": {}}


EFFECT_KEYS = ("type", "on", "section", "amount", "decay", "color", "sigma", "frames", "angle",
               "lut", "contrast", "brightness", "saturation", "gamma", "curves")
_COLOR_RX = re.compile(r"#[0-9A-Fa-f]{6}")


def _n(v):
    return _api._num(float(v))


def _fr(t, fps):
    return int(round(float(t) * fps))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and not isinstance(v, bool) else None


# ── Мягкая чистка (загрузка вкладки и Clip.__post_init__) ────────────────────
def sanitize_keyframes(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for prop in KEYFRAME_PROPS:
        pts = []
        for p in raw.get(prop) or []:
            if not isinstance(p, dict):
                continue
            t, v = _num(p.get("t")), _num(p.get("v"))
            if t is None or v is None or t < 0:
                continue
            ease = p.get("ease", "linear")
            pts.append({"t": t, "v": v, "ease": ease if ease in EASES else "linear"})
        if pts:
            out[prop] = sorted(pts, key=lambda p: p["t"])
    return out


def sanitize_effect(e):
    """Эффект с известными ключами и значениями в пределах или None."""
    if not isinstance(e, dict) or e.get("type") not in EFFECT_TYPES:
        return None
    out = {"type": e["type"]}
    for k in EFFECT_KEYS[1:]:
        if k not in e or e[k] is None:
            continue
        v = e[k]
        if k == "on":
            if isinstance(v, str) and v in _api.MARKER_KINDS:
                out[k] = v
            elif isinstance(v, (list, tuple)):
                times = [f for f in (_num(x) for x in v) if f is not None and f >= 0]
                if times:
                    out[k] = times
        elif k in ("section", "lut"):
            if isinstance(v, str) and v:
                out[k] = v[:500]
        elif k == "color":
            if isinstance(v, str) and _COLOR_RX.fullmatch(v):
                out[k] = v.lower()
        elif k == "curves":
            if v in CURVES_PRESETS:
                out[k] = v
        else:
            f = _num(v)
            if f is not None:
                lo, hi = EFFECT_LIMITS[k]
                out[k] = int(min(hi, max(lo, f))) if k == "frames" else min(hi, max(lo, f))
    return out


def sanitize_effects(raw):
    return [x for x in (sanitize_effect(e) for e in (raw if isinstance(raw, list) else []))
            if x is not None]


def sanitize_curve(raw):
    pts = {}
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        at, sp = _num(p.get("at")), _num(p.get("speed"))
        if at is None or sp is None or not 0.0 <= at <= 1.0:
            continue
        pts[round(at, 6)] = max(_api.MIN_SPEED, min(_api.MAX_SPEED, sp))
    if len(pts) < 2:
        return []
    return [{"at": a, "speed": s} for a, s in sorted(pts.items())]


# ── Ключевые кадры ───────────────────────────────────────────────────────────
def _ease(kind, u):
    if kind == "ease_in":
        return f"({u})*({u})"
    if kind == "ease_out":
        return f"(1-(1-({u}))*(1-({u})))"
    if kind == "ease_in_out":
        return f"({u})*({u})*(3-2*({u}))"
    if kind == "hold":
        return "0"
    return f"({u})"


def keyframe_expr(points, var, scale_t=1.0):
    """Выражение ffmpeg значения ключевых кадров в момент var (секунды
    клипа · scale_t: для номера кадра scale_t = fps). До первого и после
    последнего — крайние значения; ease — у сегмента, к началу которого
    относится точка."""
    pts = sorted(points, key=lambda p: p["t"])
    if not pts:
        return None
    expr = _n(pts[-1]["v"])
    for a, b in reversed(list(zip(pts, pts[1:]))):
        ta, tb = a["t"] * scale_t, b["t"] * scale_t
        if tb - ta <= 1e-9:
            continue
        u = f"(({var})-{_n(ta)})/{_n(tb - ta)}"
        seg = f"{_n(a['v'])}+({_n(b['v'] - a['v'])})*{_ease(a.get('ease', 'linear'), u)}"
        expr = f"if(lt({var},{_n(tb)}),{seg},{expr})"
    return f"if(lt({var},{_n(pts[0]['t'] * scale_t)}),{_n(pts[0]['v'])},{expr})"


def keyframe_value(points, t):
    """То же значение в Python (describe, проверка)."""
    pts = sorted(points, key=lambda p: p["t"])
    if not pts:
        return None
    if t < pts[0]["t"]:
        return pts[0]["v"]
    for a, b in zip(pts, pts[1:]):
        if t < b["t"]:
            if b["t"] - a["t"] <= 1e-9:
                continue
            u = (t - a["t"]) / (b["t"] - a["t"])
            e = {"ease_in": u * u, "ease_out": 1 - (1 - u) ** 2,
                 "ease_in_out": u * u * (3 - 2 * u), "hold": 0.0}.get(a.get("ease", "linear"), u)
            return a["v"] + (b["v"] - a["v"]) * e
    return pts[-1]["v"]


# ── Огибающие по маркерам ────────────────────────────────────────────────────
def effect_params(e):
    out = dict(_DEFAULTS.get(e.get("type"), {}))
    out.update({k: v for k, v in e.items() if v is not None})
    return out


def hit_frames(project, clip, e, fps):
    """Кадры клипа (от его начала), где срабатывает эффект: маркеры вида
    "on" (и части "section"), список времён проекта или — без "on" — начало
    клипа у разовых эффектов (пусто — эффект на весь клип)."""
    on = e.get("on")
    n = _fr(clip.end, fps) - _fr(clip.start, fps)
    if on is None:
        return [0] if e.get("type") in _ONE_SHOT else []
    if isinstance(on, (list, tuple)):
        times = [float(x) for x in on]
    else:
        times = [m.t for m in project.markers if m.kind == on]
        sec = e.get("section")
        if sec:
            spans = [(m.t, m.end if m.end is not None else m.t) for m in project.markers
                     if m.kind == "section" and str(sec).lower() in m.label.lower().split()]
            times = [t for t in times if any(a <= t < b for a, b in spans)]
    f0 = _fr(clip.start, fps)
    return sorted({_fr(t, fps) - f0 for t in times if 0 <= _fr(t, fps) - f0 < n})


def envelope_expr(frames, decay_frames, var="in"):
    """Σ exp(−(var−f)/decay) по ударам (до 5 decay после удара), не больше 1."""
    if not frames:
        return "0"
    d = max(0.5, float(decay_frames))
    span = int(math.ceil(5 * d))
    terms = [f"gte({var},{f})*lt({var},{f + span})*exp(-({var}-{f})/{_n(d)})" for f in frames]
    return f"min(1,{'+'.join(terms)})"


def envelope_values(frames, decay_frames, n):
    """Огибающая по кадрам клипа (для эффектов из ступенек: вспышка, RGB)."""
    d = max(0.5, float(decay_frames))
    out = [0.0] * n
    for f in frames:
        for k in range(f, min(n, f + int(math.ceil(5 * d)))):
            out[k] = min(1.0, out[k] + math.exp(-(k - f) / d))
    return out


# ── Цепочка эффектов клипа ───────────────────────────────────────────────────
def has_fx(clip):
    return bool(clip.keyframes or clip.effects or clip.speed_curve)


def _enable_frames(frames):
    """enable по номеру кадра цепочки: подряд идущие кадры — between."""
    if not frames:
        return "0"
    runs, start, prev = [], frames[0], frames[0]
    for f in frames[1:]:
        if f == prev + 1:
            prev = f
            continue
        runs.append((start, prev))
        start = prev = f
    runs.append((start, prev))
    return "+".join(f"between(n,{a},{b})" for a, b in runs)


def main_fx_chain(project, clip, n, fps, w, h, main, label=None):
    """Фильтры кадра клипа после вписывания (кадр w×h, кадр цепочки n —
    кадр клипа), без ведущей запятой; "" — нечего. label(prefix) — новая
    метка графа (у свечения внутри цепочки свои split/blend)."""
    counter = [0]

    def lab(prefix):
        if label is not None:
            return label(prefix)
        counter[0] += 1
        return f"{prefix}{counter[0]}"

    out = []
    kf = clip.keyframes or {}
    effects = [effect_params(e) for e in clip.effects or []]
    geo = main and (any(p in kf for p in ("pos_x", "pos_y", "scale", "rotation"))
                    or any(e["type"] in ("zoom_punch", "shake") for e in effects))
    if geo:
        fr = "in"
        z = keyframe_expr(kf.get("scale", []), fr, fps) or "1"
        for e in effects:
            if e["type"] == "zoom_punch":
                env = envelope_expr(hit_frames(project, clip, e, fps), e["decay"] * fps, fr)
                z = f"({z})*(1+{_n(e['amount'])}*{env})"
        cx = keyframe_expr(kf.get("pos_x", []), fr, fps) or "0.5"
        cy = keyframe_expr(kf.get("pos_y", []), fr, fps) or "0.5"
        rot = keyframe_expr(kf.get("rotation", []), fr, fps) or "0"
        for e in effects:
            if e["type"] == "shake":
                env = envelope_expr(hit_frames(project, clip, e, fps), e["decay"] * fps, fr)
                a = _n(e["amount"])
                cx = f"({cx})+{a}*{env}*sin({fr}*2.399+1.3)"
                cy = f"({cy})+{a}*{env}*sin({fr}*3.141+0.7)"
                rot = f"({rot})+{_n(e['amount'] * 60)}*{env}*sin({fr}*1.913)"
        # Углы видимой части исходного кадра (sense=source): центр ± полу-
        # размеры / зум, повёрнутые на rot.
        hw, hh = f"(W/2/({z}))", f"(H/2/({z}))"
        cs, sn = f"cos(({rot})*PI/180)", f"sin(({rot})*PI/180)"
        corners = []
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            dx, dy = f"({sx}*{hw})", f"({sy}*{hh})"
            corners.append((f"W*({cx})+{dx}*{cs}-{dy}*{sn}", f"H*({cy})+{dx}*{sn}+{dy}*{cs}"))
        args = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(corners))
        out.append(f"perspective={args}:interpolation=linear:eval=frame")
    for e in effects:
        t = e["type"]
        if t == "flash":
            vals = envelope_values(hit_frames(project, clip, e, fps), e["decay"] * fps, n)
            levels = {}
            for k, v in enumerate(vals):
                a = round(v * float(e["amount"]) * 10) / 10.0
                if a > 0:
                    levels.setdefault(a, []).append(k)
            color = _api.ff_color(e.get("color", "#ffffff"))
            for a, frames in sorted(levels.items()):
                out.append(f"drawbox=x=0:y=0:w=iw:h=ih:t=fill:color={color}@{_n(min(1.0, a))}:"
                           f"enable='{_enable_frames(frames)}'")
        elif t == "rgb_shift":
            vals = envelope_values(hit_frames(project, clip, e, fps), e["decay"] * fps, n)
            levels = {}
            for k, v in enumerate(vals):
                px = int(round(v * float(e["amount"])))
                if px > 0:
                    levels.setdefault(px, []).append(k)
            for px, frames in sorted(levels.items()):
                out.append(f"rgbashift=rh={px}:bh={-px}:edge=smear:enable='{_enable_frames(frames)}'")
        elif t == "glow":
            frames = hit_frames(project, clip, e, fps)
            sig = _n(e["sigma"])
            op = _n(min(1.0, float(e["amount"])))
            if e.get("on") is None:
                enable = ""
            else:
                vals = envelope_values(frames, e["decay"] * fps, n)
                on_frames = [k for k, v in enumerate(vals) if v > 0.15]
                enable = f":enable='{_enable_frames(on_frames)}'"
            a, b, c = lab("gla"), lab("glb"), lab("glc")
            out.append(f"split[{a}][{b}];[{b}]gblur=sigma={sig}[{c}];[{a}][{c}]blend=all_mode=screen:"
                       f"all_opacity={op}{enable}")
        elif t == "motion_blur":
            k = int(e.get("frames", 3))
            out.append(f"tmix=frames={k}")
        elif t == "vignette":
            out.append(f"vignette=angle={_n(e['angle'])}")
        elif t == "color":
            if e.get("lut"):
                from ffmpeg_env import escape_filter_path
                out.append(f"lut3d=file='{escape_filter_path(e['lut'])}':interp=tetrahedral")
            eq = [f"{k}={_n(e[k])}" for k in ("contrast", "brightness", "saturation", "gamma")
                  if k in e]
            if eq:
                out.append("eq=" + ":".join(eq))
            if e.get("curves") and e["curves"] != "none":
                out.append(f"curves=preset={e['curves']}")
    if not main:
        out += overlay_fx(clip, fps)
    return ",".join(out)


def overlay_fx(clip, fps):
    """Ключевые кадры наложения внутри его цепочки: размер (scale
    eval=frame — доля от начального прямоугольника), поворот, прозрачность."""
    kf = clip.keyframes or {}
    out = []
    if "scale" in kf:
        base = max(_api.MIN_SCALE, float(clip.scale))
        r = f"(({keyframe_expr(kf['scale'], 't')})/{_n(base)})"
        out.append(f"scale=w='max(2,trunc(iw*{r}/2)*2)':h='max(2,trunc(ih*{r}/2)*2)':eval=frame")
    if "rotation" in kf:
        a = keyframe_expr(kf["rotation"], "t")
        out.append(f"rotate=a='({a})*PI/180':ow='hypot(iw,ih)':oh='hypot(iw,ih)':fillcolor=none")
    if "opacity" in kf:
        op = keyframe_expr(kf["opacity"], "T")
        out.append(f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='alpha(X,Y)*min(1,max(0,{op}))'")
    return out


def overlay_xy(clip, r0, f0, fps):
    """x и y overlay наложения с ключевыми кадрами: t overlay — время базы
    окна (0 на кадре r0), время клипа = t + (r0 − f0)/fps."""
    kf = clip.keyframes or {}
    tl = f"(t+{_n((r0 - f0) / fps)})"
    px = keyframe_expr(kf["pos_x"], tl) if "pos_x" in kf else _n(clip.pos_x)
    py = keyframe_expr(kf["pos_y"], tl) if "pos_y" in kf else _n(clip.pos_y)
    return f"'main_w*({px})-overlay_w/2'", f"'main_h*({py})-overlay_h/2'"


# ── Кривая скорости ──────────────────────────────────────────────────────────
def curve_points(clip):
    """[(s, v)] — позиция в секундах куска исходника и скорость."""
    span = max(1e-6, clip.out_s - clip.in_s)
    pts = sorted(((min(1.0, max(0.0, float(p["at"]))) * span, float(p["speed"]))
                  for p in clip.speed_curve), key=lambda x: x[0])
    if pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < span:
        pts.append((span, pts[-1][1]))
    return pts


def _seg_time(s0, v0, s1, v1, s):
    """∫ ds/v(s) на [s0, s] при линейной v от v0 (s0) до v1 (s1)."""
    ds = s - s0
    if s1 - s0 <= 1e-12:
        return 0.0
    b = (v1 - v0) / (s1 - s0)
    if abs(b) < 1e-9:
        return ds / v0
    return math.log((v0 + b * ds) / v0) / b


def curve_length(clip):
    pts = curve_points(clip)
    return sum(_seg_time(a[0], a[1], b[0], b[1], b[0]) for a, b in zip(pts, pts[1:]))


def curve_source_offset(clip, tau):
    """Позиция в куске исходника (с) для времени клипа tau (обратная τ)."""
    pts = curve_points(clip)
    acc = 0.0
    for (s0, v0), (s1, v1) in zip(pts, pts[1:]):
        seg = _seg_time(s0, v0, s1, v1, s1)
        if tau <= acc + seg or (s1, v1) == pts[-1]:
            x = max(0.0, tau - acc)
            b = (v1 - v0) / (s1 - s0) if s1 - s0 > 1e-12 else 0.0
            if abs(b) < 1e-9:
                return min(s1, s0 + v0 * x)
            return min(s1, s0 + v0 * (math.exp(b * x) - 1.0) / b)
        acc += seg
    return pts[-1][0]


def curve_setpts(clip):
    """setpts: время кадра в клипе по позиции в куске исходника s
    (s = PTS·TB − начало: метки с нуля после PTS-STARTPTS)."""
    pts = curve_points(clip)
    s = "(PTS*TB)"
    terms = []
    # Сумма по кускам: τ(s) = Σ τ_seg(clip(s, s0, s1)).
    for (s0, v0), (s1, v1) in zip(pts, pts[1:]):
        if s1 - s0 <= 1e-12:
            continue
        b = (v1 - v0) / (s1 - s0)
        x = f"(min(max({s},{_n(s0)}),{_n(s1)})-{_n(s0)})"
        if abs(b) < 1e-9:
            terms.append(f"{x}/{_n(v0)}")
        else:
            terms.append(f"log(1+{_n(b)}*{x}/{_n(v0)})/{_n(b)}")
    expr = "+".join(terms) or s
    return f"setpts='({expr})/TB'"


def curve_speed_at(pts, s):
    for (s0, v0), (s1, v1) in zip(pts, pts[1:]):
        if s <= s1:
            return v0 + (v1 - v0) * ((s - s0) / (s1 - s0) if s1 - s0 > 1e-12 else 0.0)
    return pts[-1][1]


def curve_rubberband(clip, step=0.04):
    """Звук клипа с кривой скорости: rubberband, tempo — командами asendcmd
    каждые step секунд исходника (метки звука — с начала куска)."""
    pts = curve_points(clip)
    span = pts[-1][0]
    cmds, s = [], 0.0
    while s < span:
        cmds.append(f"{s:.3f} rubberband tempo {curve_speed_at(pts, s):.5f}")
        s += step
    return (f"asetpts=PTS-STARTPTS,asendcmd=c='{';'.join(cmds)}',"
            f"rubberband=tempo={curve_speed_at(pts, 0.0):.5f}")


def split_fx(left, right, t_local, cut_src):
    """Разрез клипа с v3-полями: ключевые кадры правой части — со сдвигом на
    t_local (время разреза от начала клипа), кривая скорости — свои точки у
    каждой половины (скорость в точке разреза — по прямой)."""
    if left.keyframes:
        right.keyframes = {k: [dict(p_, t=max(0.0, p_["t"] - t_local)) for p_ in pts
                               if p_["t"] >= t_local] or [dict(pts[-1], t=0.0)]
                           for k, pts in left.keyframes.items()}
        for k, pts in list(right.keyframes.items()):
            # Значение на разрезе — первой точкой правой части.
            pts.insert(0, {"t": 0.0, "v": keyframe_value(left.keyframes[k], t_local),
                           "ease": "linear"})
            right.keyframes[k] = sanitize_keyframes({k: pts})[k]
    if left.speed_curve:
        pts = curve_points(left)              # (s, v) по куску исходника левого клипа
        span = pts[-1][0]
        cut = min(span, max(0.0, cut_src - left.in_s))
        v_cut = curve_speed_at(pts, cut)
        lpart = [(s, v) for s, v in pts if s < cut] + [(cut, v_cut)]
        rpart = [(cut, v_cut)] + [(s, v) for s, v in pts if s > cut]
        left.speed_curve = sanitize_curve([{"at": s / cut if cut > 0 else 0.0, "speed": v}
                                           for s, v in lpart])
        rs = span - cut
        right.speed_curve = sanitize_curve([{"at": (s - cut) / rs if rs > 0 else 0.0, "speed": v}
                                            for s, v in rpart])
