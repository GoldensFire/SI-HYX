# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# photo_tool.py — «Редактирование фото» без интерфейса: команды для внешней
# нейросети (агента).
"""«Редактирование фото» без интерфейса: CLI и API для агента.

    python -I photo_tool.py <команда> [аргументы]

Команды (ответ — один JSON в stdout, ошибка — JSON с "ok": false и код
выхода ≠ 0):
  guide                          памятка: операции edit, координаты, цвета;
  info <картинка>                размер, альфа, формат, вес файла;
  preview <картинка> <out.png> [--max 1280] [--grid 0|N]
                                 уменьшенная копия для просмотра моделью;
                                 --grid рисует сетку с подписями в пикселях
                                 ИСХОДНИКА — по ней удобно брать координаты;
  edit <вход> <выход> --ops ops.json | --ops-json '[…]'
       [--export lossless|process] [--set ключ=значение …] [--open]
                                 операции по порядку (кадрирование, кисть,
                                 размытие, фигуры, текст, наложение, удаление
                                 объекта LaMa, фона RMBG, чёрных полос,
                                 вотермарок, поворот, масштаб);
  merge <выход> <картинка>… [--vertical] [--svg-white]
                                 склейка как «Объединить фото»;
  export <картинка> <папка> [--stem имя] [--set ключ=значение …]
                                 сжать настройками «Обработки» (AVIF и др.);
  open <картинка> [--note …]     открыть во вкладке «Редактирование фото»
                                 запущенного приложения (photo_handoff).

Координаты — пиксели исходника (x вправо, y вниз), прямоугольник —
[x, y, w, h]. Модели LaMa/RMBG — те же, что у вкладки (models/)."""
import os
import sys

if __name__ == "__main__":
    # -I не кладёт папку скрипта в sys.path — без неё не найти соседние модули.
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import photo_tool
    sys.exit(photo_tool.main())

import argparse
import json
import shutil
import tempfile

import numpy as np

try:
    import cv2
except Exception:                 # pragma: no cover
    cv2 = None

from PIL import Image, ImageDraw, ImageFont, ImageOps

import photo_export
import photo_handoff

GUIDE = """Операции edit — список объектов JSON, применяются по порядку.
Координаты в пикселях текущей картинки (после предыдущих операций!),
прямоугольник — [x, y, w, h]. Цвет — "#rrggbb", "#rrggbbaa" или [r,g,b(,a)].
Области (для blur и remove_object): "rects": [[x,y,w,h],…],
"ellipses": [[x,y,w,h],…], "strokes": [{"points": [[x,y],…], "size": 30},…],
"mask": "путь к ч/б маске" (белое = область).

  {"op": "crop", "rect": [x, y, w, h]}                 кадрирование
  {"op": "black_bars"}                                 обрезать чёрные полосы
  {"op": "rotate", "angle": 90|180|270}                по часовой
  {"op": "flip", "axis": "h"|"v"}                      отражение
  {"op": "resize", "max_side": N | "width": W | "height": H | "scale": k}
  {"op": "brush", "points": [[x,y],…], "size": 30, "color": "#eb2d2d"}
  {"op": "rect"|"ellipse", "rect": [x,y,w,h], "color": …, "width": 4, "fill": false}
  {"op": "line"|"arrow", "from": [x,y], "to": [x,y], "color": …, "width": 4}
  {"op": "text", "at": [x,y], "text": "…", "size": 48, "font": "Arial"|путь,
       "color": "#ffffff", "stroke_color": "#000000", "stroke_width": 0,
       "anchor": "la"}        (anchor — как в Pillow: la, mm, rs …)
  {"op": "blur", области…, "radius": 12, "mode": "gaussian"|"pixelate"}
  {"op": "overlay", "image": путь, "at": [x,y], "width": W?, "height": H?,
       "opacity": 1.0}                                 наложить картинку
  {"op": "remove_object", области…}                    LaMa дорисует фон
  {"op": "remove_bg"}                                  RMBG: фон прозрачный
  {"op": "remove_watermarks"}                          Gemini и Meta AI

Порядок работы: info → preview --grid (взять координаты) → edit → preview
результата → export (сжатие настройками «Обработки») или open (показать
пользователю во вкладке). edit --export process --set img_fmt=avif
--set limit=300 сразу сохранит сжатым; ключи --set: img_fmt (avif, webp,
png, jpg, ico), limit (КБ, 0 — без лимита), cq, adim (макс. сторона),
awidth, aheight, aspd (0–8), fit_passes, chroma (420/422/444), gemini_wm.
Без --set берутся настройки вкладки «Обработка» из settings.json."""


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ── Картинка: BGR uint8 + альфа (H, W) или None, как у холста вкладки ─────────

def load_image(path):
    if not os.path.isfile(path):
        raise ToolError("not_found", f"нет файла: {path}")
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            has_alpha = im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or \
                (im.mode == "P" and "transparency" in im.info)
            arr = np.asarray(im.convert("RGBA" if has_alpha else "RGB"))
    except Exception as exc:
        raise ToolError("bad_image", f"не открыть {path}: {exc}") from None
    bgr = np.ascontiguousarray(arr[:, :, 2::-1])
    alpha = np.ascontiguousarray(arr[:, :, 3]) if has_alpha else None
    return bgr, alpha


def save_image(path, bgr, alpha=None):
    """Без потерь по расширению (png/tif/bmp/webp), jpg — качество 95."""
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    rgb = bgr[:, :, ::-1]
    fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "bmp": "BMP", "tif": "TIFF",
           "tiff": "TIFF", "webp": "WEBP"}.get(ext)
    if fmt is None:
        raise ToolError("bad_format", f"формат .{ext} не поддержан (png, tif, bmp, webp, jpg); "
                                      "сжатые avif и др. — через --export process")
    if alpha is not None and fmt in ("JPEG", "BMP"):
        a = alpha.astype(np.float32)[..., None] / 255.0
        rgb = (rgb * a + 255.0 * (1.0 - a)).astype(np.uint8)
        alpha = None
    im = Image.fromarray(np.dstack([rgb, alpha]) if alpha is not None
                         else np.ascontiguousarray(rgb))
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    kw = {"quality": 95} if fmt == "JPEG" else ({"lossless": True} if fmt == "WEBP" else {})
    im.save(path, format=fmt, **kw)


def image_info(path):
    bgr, alpha = load_image(path)
    with Image.open(path) as im:
        fmt = im.format
    return {"path": os.path.abspath(path), "width": int(bgr.shape[1]),
            "height": int(bgr.shape[0]), "alpha": alpha is not None,
            "format": fmt, "size_kb": round(os.path.getsize(path) / 1024, 1)}


# ── Разбор аргументов операций ────────────────────────────────────────────────

def parse_color(value, default=(235, 45, 45, 255)):
    """→ (r, g, b, a)."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        c = [int(max(0, min(255, v))) for v in value]
        return tuple(c + [255]) if len(c) == 3 else tuple(c)
    s = str(value).strip().lstrip("#")
    if len(s) in (6, 8):
        try:
            c = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
        except ValueError:
            c = None
        if c:
            return tuple(c + [255]) if len(c) == 3 else tuple(c)
    raise ToolError("bad_op", f"цвет не понят: {value!r} (нужно #rrggbb или [r,g,b])")


def _rect(value, w, h, name="rect"):
    try:
        x, y, rw, rh = (int(round(float(v))) for v in value)
    except Exception:
        raise ToolError("bad_op", f"{name}: нужно [x, y, w, h]") from None
    x0, y0 = max(0, min(w, x)), max(0, min(h, y))
    x1, y1 = max(0, min(w, x + rw)), max(0, min(h, y + rh))
    if x1 <= x0 or y1 <= y0:
        raise ToolError("bad_op", f"{name} {value} вне картинки {w}×{h}")
    return x0, y0, x1, y1


def _pt(value, name):
    try:
        x, y = value
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        raise ToolError("bad_op", f"{name}: нужно [x, y]") from None


def region_mask(op, w, h):
    """Маска (H, W) uint8 из rects/ellipses/strokes/mask операции."""
    m = np.zeros((h, w), np.uint8)
    for r in op.get("rects") or []:
        x0, y0, x1, y1 = _rect(r, w, h, "rects")
        m[y0:y1, x0:x1] = 255
    for r in op.get("ellipses") or []:
        x0, y0, x1, y1 = _rect(r, w, h, "ellipses")
        cv2.ellipse(m, ((x0 + x1) // 2, (y0 + y1) // 2),
                    (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2)),
                    0, 0, 360, 255, -1, cv2.LINE_AA)
    for st in op.get("strokes") or []:
        _stroke(m, st.get("points") or [], int(st.get("size", 30)), 255)
    if op.get("mask"):
        mk = cv2.imread(str(op["mask"]), cv2.IMREAD_GRAYSCALE)
        if mk is None:
            raise ToolError("not_found", f"маска не открылась: {op['mask']}")
        if mk.shape[:2] != (h, w):
            mk = cv2.resize(mk, (w, h), interpolation=cv2.INTER_NEAREST)
        m = np.maximum(m, mk)
    if not m.any():
        raise ToolError("bad_op", f"{op.get('op')}: пустая область "
                                  "(нужны rects / ellipses / strokes / mask)")
    return m


def _stroke(img, points, size, color):
    pts = [_pt(p, "points") for p in points]
    if not pts:
        raise ToolError("bad_op", "мазок без точек")
    size = max(1, int(size))
    for a, b in zip(pts, pts[1:]):
        cv2.line(img, a, b, color, size, cv2.LINE_AA)
    for p in pts:
        cv2.circle(img, p, max(1, size // 2), color, -1, cv2.LINE_AA)


def _blend(bgr, drawn, opacity):
    if opacity >= 1.0:
        return drawn
    return cv2.addWeighted(drawn, float(opacity), bgr, 1.0 - float(opacity), 0)


def find_font(name, size):
    size = max(4, int(size))
    cand = []
    if name and os.path.isfile(str(name)):
        cand.append(str(name))
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    key = str(name or "arial").lower().replace(" ", "")
    try:
        files = sorted(os.listdir(fonts_dir))
    except OSError:
        files = []
    exact = [f for f in files if os.path.splitext(f)[0].lower() == key]
    starts = [f for f in files if os.path.splitext(f)[0].lower().startswith(key)
              and f.lower().endswith((".ttf", ".otf", ".ttc"))]
    cand += [os.path.join(fonts_dir, f) for f in exact + starts]
    cand += [os.path.join(fonts_dir, "arial.ttf"), "DejaVuSans.ttf"]
    for path in cand:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── Операции ──────────────────────────────────────────────────────────────────

_MODELS = {}


def _lama():
    if "lama" not in _MODELS:
        import lama_inpaint
        m = lama_inpaint.LaMaInpainter()
        if not m.is_available():
            raise ToolError("no_model", "нет модели LaMa (models/) или onnxruntime")
        _MODELS["lama"] = m
    return _MODELS["lama"]


def _rmbg():
    if "rmbg" not in _MODELS:
        import rmbg_bg
        m = rmbg_bg.RMBGRemover()
        if not m.is_available():
            raise ToolError("no_model", "нет модели RMBG (models/model_uint8.onnx) или onnxruntime")
        _MODELS["rmbg"] = m
    return _MODELS["rmbg"]


def apply_op(bgr, alpha, op):
    """Одна операция → (bgr, alpha, заметка)."""
    if cv2 is None:
        raise ToolError("no_cv2", "нужен opencv (pip install opencv-python-headless)")
    if not isinstance(op, dict) or not op.get("op"):
        raise ToolError("bad_op", f"операция без поля op: {op!r}")
    kind = str(op["op"]).lower()
    h, w = bgr.shape[:2]
    note = ""
    if kind == "crop":
        x0, y0, x1, y1 = _rect(op.get("rect"), w, h)
        bgr = bgr[y0:y1, x0:x1].copy()
        alpha = alpha[y0:y1, x0:x1].copy() if alpha is not None else None
    elif kind == "black_bars":
        from workers import ProcessWorker
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        bright = gray > ProcessWorker._CROP_LUMA_LIMIT
        if alpha is not None:
            bright &= alpha > 10
        box = ProcessWorker._crop_from_counts(bright.sum(axis=1), bright.sum(axis=0), w, h)
        if box is None:
            note = "чёрных полос нет"
        else:
            bw, bh, x, y = box
            bgr = bgr[y:y + bh, x:x + bw].copy()
            alpha = alpha[y:y + bh, x:x + bw].copy() if alpha is not None else None
            note = f"обрезано до {bw}×{bh} (x={x}, y={y})"
    elif kind == "rotate":
        codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                 270: cv2.ROTATE_90_COUNTERCLOCKWISE, -90: cv2.ROTATE_90_COUNTERCLOCKWISE}
        code = codes.get(int(op.get("angle", 90)))
        if code is None:
            raise ToolError("bad_op", "rotate: angle — 90, 180 или 270")
        bgr = cv2.rotate(bgr, code)
        alpha = cv2.rotate(alpha, code) if alpha is not None else None
    elif kind == "flip":
        code = {"h": 1, "v": 0}.get(str(op.get("axis", "h")).lower())
        if code is None:
            raise ToolError("bad_op", "flip: axis — h или v")
        bgr = cv2.flip(bgr, code)
        alpha = cv2.flip(alpha, code) if alpha is not None else None
    elif kind == "resize":
        if op.get("scale"):
            nw, nh = w * float(op["scale"]), h * float(op["scale"])
        elif op.get("max_side"):
            k = float(op["max_side"]) / max(w, h)
            nw, nh = w * k, h * k
        elif op.get("width") and op.get("height"):
            nw, nh = float(op["width"]), float(op["height"])
        elif op.get("width"):
            nw = float(op["width"]); nh = h * nw / w
        elif op.get("height"):
            nh = float(op["height"]); nw = w * nh / h
        else:
            raise ToolError("bad_op", "resize: нужен scale, max_side, width или height")
        nw, nh = max(1, int(round(nw))), max(1, int(round(nh)))
        interp = cv2.INTER_AREA if nw * nh < w * h else cv2.INTER_LANCZOS4
        bgr = cv2.resize(bgr, (nw, nh), interpolation=interp)
        alpha = cv2.resize(alpha, (nw, nh), interpolation=interp) if alpha is not None else None
    elif kind in ("brush", "rect", "ellipse", "line", "arrow"):
        r, g, b, a = parse_color(op.get("color"))
        col = (b, g, r)
        drawn = bgr.copy()
        width = max(1, int(op.get("width", op.get("size", 4))))
        if kind == "brush":
            _stroke(drawn, op.get("points") or [], int(op.get("size", 30)), col)
        elif kind in ("rect", "ellipse"):
            x0, y0, x1, y1 = _rect(op.get("rect"), w, h)
            thick = -1 if op.get("fill") else width
            if kind == "rect":
                cv2.rectangle(drawn, (x0, y0), (x1 - 1, y1 - 1), col, thick, cv2.LINE_AA)
            else:
                cv2.ellipse(drawn, ((x0 + x1) // 2, (y0 + y1) // 2),
                            (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2)),
                            0, 0, 360, col, thick, cv2.LINE_AA)
        else:
            p0, p1 = _pt(op.get("from"), "from"), _pt(op.get("to"), "to")
            if kind == "line":
                cv2.line(drawn, p0, p1, col, width, cv2.LINE_AA)
            else:
                length = max(1.0, float(np.hypot(p1[0] - p0[0], p1[1] - p0[1])))
                tip = min(0.5, max(0.05, (width * 4.0 + 12.0) / length))
                cv2.arrowedLine(drawn, p0, p1, col, width, cv2.LINE_AA, tipLength=tip)
        bgr = _blend(bgr, drawn, a / 255.0)
    elif kind == "text":
        text = str(op.get("text") or "")
        if not text:
            raise ToolError("bad_op", "text: пустой текст")
        x, y = _pt(op.get("at"), "at")
        r, g, b, a = parse_color(op.get("color"), (255, 255, 255, 255))
        sr, sg, sb, _sa = parse_color(op.get("stroke_color"), (0, 0, 0, 255))
        font = find_font(op.get("font"), op.get("size", 48))
        im = Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1]))
        drawn = im.copy()
        ImageDraw.Draw(drawn).text(
            (x, y), text, font=font, fill=(r, g, b), anchor=str(op.get("anchor") or "la"),
            stroke_width=max(0, int(op.get("stroke_width", 0))), stroke_fill=(sr, sg, sb))
        out = np.asarray(drawn)[:, :, ::-1]
        bgr = _blend(bgr, np.ascontiguousarray(out), a / 255.0)
    elif kind == "blur":
        m = region_mask(op, w, h)
        radius = max(1, int(op.get("radius", 12)))
        if str(op.get("mode", "gaussian")).lower() == "pixelate":
            small = cv2.resize(bgr, (max(1, w // radius), max(1, h // radius)),
                               interpolation=cv2.INTER_AREA)
            done = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            done = cv2.GaussianBlur(bgr, (0, 0), float(radius))
        k = (m.astype(np.float32) / 255.0)[..., None]
        bgr = (bgr * (1.0 - k) + done * k).astype(np.uint8)
    elif kind == "overlay":
        path = str(op.get("image") or "")
        obgr, oalpha = load_image(path)
        oh, ow = obgr.shape[:2]
        tw, th = op.get("width"), op.get("height")
        if tw and not th:
            th = oh * float(tw) / ow
        elif th and not tw:
            tw = ow * float(th) / oh
        if tw and th:
            tw, th = max(1, int(round(float(tw)))), max(1, int(round(float(th))))
            obgr = cv2.resize(obgr, (tw, th), interpolation=cv2.INTER_AREA)
            oalpha = cv2.resize(oalpha, (tw, th)) if oalpha is not None else None
            oh, ow = th, tw
        x, y = _pt(op.get("at", [0, 0]), "at")
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + ow), min(h, y + oh)
        if x1 <= x0 or y1 <= y0:
            raise ToolError("bad_op", "overlay: картинка целиком вне холста")
        src = obgr[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
        k = np.full((y1 - y0, x1 - x0, 1), float(op.get("opacity", 1.0)), np.float32)
        if oalpha is not None:
            k *= oalpha[y0 - y:y1 - y, x0 - x:x1 - x, None].astype(np.float32) / 255.0
        bgr = bgr.copy()
        bgr[y0:y1, x0:x1] = (bgr[y0:y1, x0:x1] * (1.0 - k) + src * k).astype(np.uint8)
        if alpha is not None:
            alpha = alpha.copy()
            alpha[y0:y1, x0:x1] = np.maximum(alpha[y0:y1, x0:x1],
                                             (k[..., 0] * 255.0).astype(np.uint8))
    elif kind == "remove_object":
        m = region_mask(op, w, h)
        bgr = _lama().inpaint(bgr, m)
        note = f"LaMa: {int((m > 0).sum())} px"
    elif kind == "remove_bg":
        a = _rmbg().remove(bgr)
        alpha = a if alpha is None else np.minimum(alpha, a)
        note = "фон прозрачный — сохраняйте в png/webp/tif"
    elif kind == "remove_watermarks":
        import gemini_watermark
        import meta_watermark
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])
        if alpha is not None:
            rgb = np.dstack([rgb, alpha])
        removed = []
        found = gemini_watermark.find_watermark(rgb, hint=bool(op.get("gemini_hint")))
        if found:
            rgb = gemini_watermark.remove_watermark(rgb, found)
            removed.append("Gemini")
        found = meta_watermark.find_watermark(rgb)
        if found:
            try:
                lama = _lama()
            except ToolError:
                lama = None
            rgb = meta_watermark.remove_watermark(rgb, found, lama)
            removed.append("Meta AI")
        bgr = np.ascontiguousarray(rgb[:, :, 2::-1])
        if alpha is not None and rgb.shape[2] == 4:
            alpha = np.ascontiguousarray(rgb[:, :, 3])
        note = ("сняты: " + ", ".join(removed)) if removed else "вотермарок не найдено"
    else:
        raise ToolError("bad_op", f"неизвестная операция: {kind}")
    return np.ascontiguousarray(bgr), alpha, note


def run_ops(bgr, alpha, ops):
    report = []
    for i, op in enumerate(ops):
        try:
            bgr, alpha, note = apply_op(bgr, alpha, op)
        except ToolError as exc:
            raise ToolError(exc.code, f"операция #{i} ({op.get('op') if isinstance(op, dict) else op}): "
                                      f"{exc.message}") from None
        entry = {"op": op.get("op"), "size": [int(bgr.shape[1]), int(bgr.shape[0])]}
        if note:
            entry["note"] = note
        report.append(entry)
    return bgr, alpha, report


# ── Просмотр с сеткой ────────────────────────────────────────────────────────

def make_preview(src, out, max_side=1280, grid=0):
    bgr, alpha = load_image(src)
    h, w = bgr.shape[:2]
    if alpha is not None:          # прозрачное — на шахматке, чтобы его было видно
        yy, xx = np.mgrid[0:h, 0:w]
        board = np.where(((xx // 16 + yy // 16) % 2)[..., None] == 0, 200, 150).astype(np.float32)
        k = alpha.astype(np.float32)[..., None] / 255.0
        bgr = (bgr * k + board * (1.0 - k)).astype(np.uint8)
    k = min(1.0, float(max_side) / max(w, h))
    view = cv2.resize(bgr, (max(1, int(w * k)), max(1, int(h * k))),
                      interpolation=cv2.INTER_AREA) if k < 1.0 else bgr.copy()
    step = max(0, int(grid or 0))
    if step:
        im = Image.fromarray(np.ascontiguousarray(view[:, :, ::-1]))
        d = ImageDraw.Draw(im)
        font = find_font("arial", max(11, int(min(im.size) / 60)))
        for gx in range(0, w, step):
            vx = int(gx * k)
            d.line([(vx, 0), (vx, im.height)], fill=(0, 255, 255), width=1)
            d.text((vx + 2, 2), str(gx), font=font, fill=(255, 255, 0),
                   stroke_width=2, stroke_fill=(0, 0, 0))
        for gy in range(0, h, step):
            vy = int(gy * k)
            d.line([(0, vy), (im.width, vy)], fill=(0, 255, 255), width=1)
            d.text((2, vy + 2), str(gy), font=font, fill=(255, 255, 0),
                   stroke_width=2, stroke_fill=(0, 0, 0))
        view = np.asarray(im)[:, :, ::-1]
    save_image(out, np.ascontiguousarray(view))
    return {"preview": os.path.abspath(out), "scale": round(k, 5),
            "source_size": [w, h], "preview_size": [int(view.shape[1]), int(view.shape[0])],
            "grid_step": step}


def auto_grid_step(w, h):
    """Шаг сетки ~8–12 линий по длинной стороне, круглым числом."""
    raw = max(w, h) / 10.0
    for s in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000):
        if s >= raw:
            return s
    return 10000


# ── Склейка, экспорт ──────────────────────────────────────────────────────────

def merge_images(paths, out, vertical=False, svg_white=False):
    """Как «Объединить фото»: по высоте (или ширине) самой крупной."""
    from utils import open_image_any
    imgs = []
    try:
        for p in paths:
            im = open_image_any(p)
            if (svg_white and os.path.splitext(p)[1].lower() == ".svg"
                    and im.mode in ("RGBA", "LA", "PA", "La", "RGBa")):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[3])
                im = bg
            imgs.append(im)
        ext = os.path.splitext(out)[1].lower()
        keep_alpha = ext in (".png", ".webp", ".tif", ".tiff") and any(
            im.mode in ("RGBA", "LA", "PA", "La", "RGBa")
            or (im.mode == "P" and "transparency" in im.info) for im in imgs)
        cmode = "RGBA" if keep_alpha else "RGB"
        bg = (0, 0, 0, 0) if keep_alpha else (0, 0, 0)
        imgs = [im if im.mode == cmode else im.convert(cmode) for im in imgs]
        if vertical:
            side = max(im.width for im in imgs)
            parts = [im.resize((side, int(im.height * side / im.width)), Image.Resampling.LANCZOS)
                     for im in imgs]
            canvas = Image.new(cmode, (side, sum(p.height for p in parts)), bg)
            pos = 0
            for p in parts:
                canvas.paste(p, (0, pos)); pos += p.height
        else:
            side = max(im.height for im in imgs)
            parts = [im.resize((int(im.width * side / im.height), side), Image.Resampling.LANCZOS)
                     for im in imgs]
            canvas = Image.new(cmode, (sum(p.width for p in parts), side), bg)
            pos = 0
            for p in parts:
                canvas.paste(p, (pos, 0)); pos += p.width
        arr = np.asarray(canvas)
        save_image(out, np.ascontiguousarray(arr[:, :, 2::-1]),
                   np.ascontiguousarray(arr[:, :, 3]) if keep_alpha else None)
    finally:
        for im in imgs:
            try:
                im.close()
            except Exception:
                pass
    return image_info(out)


def _parse_sets(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ToolError("bad_args", f"--set ждёт ключ=значение: {item}")
        k, v = item.split("=", 1)
        k, v = k.strip(), v.strip()
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = v
    return out


def export_processed(src, out_dir, stem, sets=None, log=None):
    try:
        settings = photo_export.apply_overrides(
            photo_export.load_saved_process_settings(), _parse_sets(sets))
    except ValueError as exc:
        raise ToolError("bad_args", str(exc)) from None
    logs = []
    out = photo_export.export_with_process_settings(
        src, out_dir, stem, settings, log=logs.append)
    info = image_info(out)
    info["settings"] = settings["avif"]
    info["log"] = logs[-10:]
    return info


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_ops(args):
    if args.ops_json:
        ops = json.loads(args.ops_json)
    elif args.ops:
        with open(args.ops, encoding="utf-8") as f:
            ops = json.load(f)
    else:
        raise ToolError("bad_args", "нужен --ops файл.json или --ops-json '[…]'")
    if isinstance(ops, dict):
        ops = ops.get("ops", [ops])
    if not isinstance(ops, list):
        raise ToolError("bad_args", "операции — список объектов")
    return ops


def cmd_edit(args):
    ops = _load_ops(args)
    bgr, alpha = load_image(args.input)
    bgr, alpha, report = run_ops(bgr, alpha, ops)
    res = {"ops": report}
    if args.export == "process":
        tmp_dir = tempfile.mkdtemp(prefix="photo_tool_")
        try:
            tmp = os.path.join(tmp_dir, "edit.png")
            save_image(tmp, bgr, alpha)
            out_dir = os.path.dirname(os.path.abspath(args.output)) or "."
            stem = os.path.splitext(os.path.basename(args.output))[0]
            res.update(export_processed(tmp, out_dir, stem, args.set))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        save_image(args.output, bgr, alpha)
        res.update(image_info(args.output))
    if args.open:
        res["opened"] = photo_handoff.publish(res["path"], note="photo_tool edit")
    return res


def build_parser():
    p = argparse.ArgumentParser(prog="photo_tool", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("guide", help="памятка операций")
    s = sub.add_parser("info", help="свойства картинки"); s.add_argument("image")
    s = sub.add_parser("preview", help="уменьшенная копия с сеткой")
    s.add_argument("image"); s.add_argument("out")
    s.add_argument("--max", type=int, default=1280)
    s.add_argument("--grid", default="auto",
                   help="шаг сетки в пикселях исходника; 0 — без сетки, auto — сам")
    s = sub.add_parser("edit", help="операции по списку")
    s.add_argument("input"); s.add_argument("output")
    s.add_argument("--ops"); s.add_argument("--ops-json")
    s.add_argument("--export", choices=("lossless", "process"), default="lossless")
    s.add_argument("--set", action="append", default=[])
    s.add_argument("--open", action="store_true", help="показать во вкладке приложения")
    s = sub.add_parser("merge", help="склейка картинок")
    s.add_argument("output"); s.add_argument("images", nargs="+")
    s.add_argument("--vertical", action="store_true")
    s.add_argument("--svg-white", action="store_true")
    s = sub.add_parser("export", help="сжать настройками «Обработки»")
    s.add_argument("image"); s.add_argument("out_dir")
    s.add_argument("--stem", default="")
    s.add_argument("--set", action="append", default=[])
    s = sub.add_parser("open", help="открыть во вкладке «Редактирование фото»")
    s.add_argument("image"); s.add_argument("--note", default="")
    return p


def run(argv=None):
    args = build_parser().parse_args(argv)
    c = args.command
    if c == "guide":
        return {"guide": GUIDE}
    if c == "info":
        return image_info(args.image)
    if c == "preview":
        if str(args.grid).lower() == "auto":
            bgr, _a = load_image(args.image)
            step = auto_grid_step(bgr.shape[1], bgr.shape[0])
        else:
            step = int(args.grid)
        return make_preview(args.image, args.out, args.max, step)
    if c == "edit":
        return cmd_edit(args)
    if c == "merge":
        return merge_images(args.images, args.output, args.vertical, args.svg_white)
    if c == "export":
        stem = args.stem or os.path.splitext(os.path.basename(args.image))[0] + "_photo"
        return export_processed(args.image, args.out_dir, stem, args.set)
    if c == "open":
        if not os.path.isfile(args.image):
            raise ToolError("not_found", f"нет файла: {args.image}")
        return {"opened": photo_handoff.publish(args.image, note=args.note)}
    raise ToolError("bad_args", f"неизвестная команда: {c}")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else ""
    try:
        res = run(argv)
        out = {"ok": True, "command": command}
        out.update(res)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except ToolError as exc:
        err = {"code": exc.code, "message": exc.message}
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        err = {"code": "error", "message": f"{type(exc).__name__}: {exc}"}
    print(json.dumps({"ok": False, "command": command, "error": err}, ensure_ascii=False))
    return 1
