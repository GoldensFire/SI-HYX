# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ритм-лента для модели: beat-strip <проект> <t0> <t1> <out.png>.
Public namespace: montage_tool.

Одна картинка (по умолчанию 2000 px): сверху вниз — шкала времени проекта,
части песни (маркеры section, цвет по подписи), волна звука проекта с
кривой громкости, доли (сильные — жёлтые, с номером такта), удары бочки и
малого, места для резов (треугольники), миниатюры клипов основной дорожки
на своих местах (кадр середины клипа: миниатюра каталога или кадр ffmpeg) с
номером; резы — красные линии через всю ленту."""
import numpy as np

import montage_tool as _api

_SECTION_RGB = {"intro": (110, 116, 134), "verse": (137, 180, 250), "build": (249, 226, 175),
                "chorus": (235, 160, 172), "drop": (243, 139, 168), "bridge": (148, 226, 213),
                "outro": (110, 116, 134)}
_BG, _TXT, _CUT = (17, 24, 39), (220, 224, 235), (243, 80, 90)


def _font(size):
    """Шрифт подписей — тот же, что у листов (Nunito из karaoke/fonts)."""
    from PIL import ImageFont
    from si_hyx_parts.montage_tool.inspection import _TIMECODE_FONT
    try:
        return ImageFont.truetype(_TIMECODE_FONT, size)
    except OSError:
        return ImageFont.load_default()


def _clip_frame(c, tmpdir, idx, db):
    """Кадр середины клипа: миниатюра плана каталога, иначе кадр ffmpeg."""
    t = (c.in_s + c.out_s) / 2 if not c.frozen else c.freeze_at
    try:
        con = _api.connect(db)
        try:
            row = con.execute("SELECT s.keyframes FROM shots s JOIN files f ON f.id=s.file_id "
                              "WHERE f.path=? AND s.t0<=? AND s.t1>? LIMIT 1",
                              (_api.os.path.abspath(c.src), t, t)).fetchone()
        finally:
            con.close()
        if row:
            keys = _api.json.loads(row["keyframes"] or "[]")
            if keys and _api.os.path.isfile(keys[len(keys) // 2]):
                return keys[len(keys) // 2]
    except Exception:                    # noqa: BLE001 — без каталога: кадр ffmpeg
        pass
    out = _api.os.path.join(tmpdir, f"c{idx:03d}.jpg")
    rgb = _api.hdr_tonemap.rgb_decode_filter(c.src, _api.escape_filter_path, "rgb24")
    vf = "scale=240:-2" + ("," + rgb if rgb else "")
    r = _api.subprocess.run([_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-ss", f"{t:.3f}",
                             "-i", c.src, "-frames:v", "1", "-vf", vf, out],
                            capture_output=True, creationflags=_api.CREATE_NO_WINDOW, timeout=60)
    return out if r.returncode == 0 and _api.os.path.isfile(out) else None


def beat_strip(p, t0, t1, out_png, width=2000, db=None):
    from PIL import Image, ImageDraw
    t0, t1 = max(0.0, float(t0)), min(float(t1), p.duration())
    if t1 - t0 < 0.5:
        raise _api.ToolError("bad_range", "отрезок короче 0,5 с")
    W = max(600, min(4000, int(width)))
    pad = 8
    span = W - 2 * pad

    def x_of(t):
        return pad + (t - t0) / (t1 - t0) * span

    rows = {"ruler": 22, "section": 22, "wave": 90, "beat": 30, "hits": 22, "slot": 14,
            "clips": 96}
    H = sum(rows.values()) + 8
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)
    f_small, f_mid = _font(12), _font(14)
    y = 0
    tops = {}
    for k, h in rows.items():
        tops[k] = y
        y += h
    # Шкала: шаг — чтобы метки шли не чаще ~90 px.
    step = next(s for s in (0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120) if s / (t1 - t0) * span >= 90)
    t = np.ceil(t0 / step) * step
    while t <= t1 + 1e-9:
        x = x_of(t)
        d.line([(x, 14), (x, 22)], fill=_TXT)
        d.text((x + 2, 1), f"{int(t // 60)}:{t % 60:05.2f}", font=f_small, fill=_TXT)
        t += step
    marks = {}
    for mk in p.markers:
        marks.setdefault(mk.kind, []).append(mk)
    # Части песни.
    ys = tops["section"]
    for s in sorted(marks.get("section", []), key=lambda m: m.t):
        a, b = max(t0, s.t), min(t1, s.end if s.end is not None else t1)
        if b <= a:
            continue
        col = _SECTION_RGB.get(s.label.split(" ")[0], (88, 91, 112))
        d.rectangle([x_of(a) + 1, ys + 2, x_of(b) - 1, ys + rows["section"] - 3], fill=col)
        d.text((x_of(a) + 4, ys + 3), s.label, font=f_mid, fill=(20, 20, 30))
    # Волна и громкость.
    yw, hw = tops["wave"], rows["wave"]
    try:
        x = _api.project_audio(p, t0, t1, rate=8000)
    except _api.ToolError:
        x = np.zeros(0, np.float32)
    mid = yw + hw / 2
    if len(x):
        per = max(1, len(x) // span)
        cols = len(x) // per
        blk = np.abs(x[:cols * per]).reshape(cols, per)
        peak = blk.max(axis=1)
        rms = np.sqrt((blk.astype(np.float64) ** 2).mean(axis=1))
        top = float(peak.max()) or 1.0
        for i in range(cols):
            xx = pad + i * span / cols
            h = peak[i] / top * (hw / 2 - 4)
            d.line([(xx, mid - h), (xx, mid + h)], fill=(90, 110, 160))
        k = max(1, cols // 200)
        env = np.convolve(rms, np.ones(k) / k, mode="same")
        env = env / (float(env.max()) or 1.0)
        pts = [(pad + i * span / cols, yw + hw - 4 - env[i] * (hw - 8)) for i in range(cols)]
        d.line(pts, fill=(249, 226, 175), width=2)
    # Доли.
    yb, hb = tops["beat"], rows["beat"]
    for m in marks.get("beat", []):
        if t0 <= m.t <= t1:
            x = x_of(m.t)
            d.line([(x, yb + hb - 10), (x, yb + hb - 2)], fill=(150, 155, 175))
    last_label_x = -100
    for m in marks.get("downbeat", []):
        if t0 <= m.t <= t1:
            x = x_of(m.t)
            d.line([(x, yb + 2), (x, yb + hb - 2)], fill=(249, 226, 175), width=2)
            if x - last_label_x > 28:
                d.text((x + 3, yb + 1), m.label, font=f_small, fill=(249, 226, 175))
                last_label_x = x
    # Удары.
    yh = tops["hits"]
    for kind, col, off in (("kick", (243, 139, 168), 2), ("snare", (166, 227, 161), 11)):
        for m in marks.get(kind, []):
            if t0 <= m.t <= t1:
                x = x_of(m.t)
                d.line([(x, yh + off), (x, yh + off + 3 + 5 * m.strength)], fill=col, width=2)
    # Места для резов.
    yl = tops["slot"]
    for m in marks.get("slot", []):
        if t0 <= m.t <= t1:
            x = x_of(m.t)
            d.polygon([(x - 4, yl + 2), (x + 4, yl + 2), (x, yl + 11)], fill=(166, 227, 161))
    # Клипы и резы.
    yc, hc = tops["clips"], rows["clips"]
    main = [c for c in p.clips_on(p.main_track) if c.end > t0 and c.start < t1]
    tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_strip_")
    try:
        for i, c in enumerate(main):
            a, b = max(t0, c.start), min(t1, c.end)
            xa, xb = int(x_of(a)), int(x_of(b))
            if xb - xa >= 12:
                path = _clip_frame(c, tmpdir, i, db)
                if path:
                    with Image.open(path) as im:
                        tile = im.convert("RGB")
                    th = hc - 18
                    tw = max(1, round(tile.width * th / tile.height))
                    tile = tile.resize((tw, th))
                    cut = max(0, (tw - (xb - xa)) // 2)
                    tile = tile.crop((cut, 0, cut + min(tw, xb - xa), th))
                    img.paste(tile, (xa, yc + 2))
            num = p.clips_on(p.main_track).index(c) + 1
            d.text((xa + 3, yc + hc - 15), str(num), font=f_small, fill=_TXT)
    finally:
        _api.shutil.rmtree(tmpdir, ignore_errors=True)
    for c in main[1:] if main and main[0].start >= t0 else main:
        if t0 < c.start < t1:
            x = x_of(c.start)
            d.line([(x, tops["section"]), (x, H)], fill=_CUT, width=2)
    img.save(str(out_png))
    return {"output": _api.os.path.abspath(str(out_png)), "t0": round(t0, 3), "t1": round(t1, 3),
            "width": W, "height": H, "clips": [c.id for c in main],
            "rows": list(rows)}
