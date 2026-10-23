# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Инспекция проекта для модели: кадр, контактный лист и короткое превью
по времени проекта. Public namespace: montage_tool.

Всё рендерится как сборка: build_source с окном (window) по полному
проекту — тот же путь, что у звука просмотра и сэмпла «Обработки», —
поэтому модель видит ровно то, что выйдет в итоге: HDR-сведение,
вписывание, наложения, переходы и текст, которых живой плеер вкладки не
покажет. Превью — по рецепту проверки сцен
генератора (episode_scene_check.video_input): до 15 с, 480p, 12 fps, до 8 МБ."""
import base64
import concurrent.futures

import montage_tool as _api

PREVIEW_MAX_S = 15.0
PREVIEW_MAX_BYTES = 8 * 1024 * 1024
PREVIEW_HEIGHT = 480
PREVIEW_FPS = 12
SHEET_MAX = 64
_STILL_TIMEOUT = 60
_TIMECODE_FONT = _api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)),
                                   "karaoke", "fonts", "Nunito-Black.ttf")


def _frame_start(p, t):
    """Начало кадра проекта, на котором стоит t, и длина кадра."""
    _w, _h, fps = p.output_format()
    t = max(0.0, min(float(t), max(0.0, p.duration() - 1.0 / fps)))
    return _api.montage_project.snap_to_frame(t, fps), 1.0 / fps


def _tonemap(p):
    return _api.hdr_tonemap.tonemap_filters(
        (c.src for c in p.clips if c.has_video and not c.is_image), _api.escape_filter_path)


def _run(cmd, timeout):
    """ffmpeg до конца; ToolError с хвостом stderr при сбое."""
    try:
        r = _api.subprocess.run(cmd, stdin=_api.subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=_api.CREATE_NO_WINDOW, timeout=timeout)
    except _api.subprocess.TimeoutExpired as e:
        raise _api.ToolError("ffmpeg_timeout", f"ffmpeg не уложился в {timeout} с") from e
    except OSError as e:
        raise _api.ToolError("ffmpeg_not_started", f"не удалось запустить ffmpeg: {e}") from e
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-15:])
        raise _api.ToolError("ffmpeg_failed", f"ffmpeg завершился с кодом {r.returncode}",
                             detail=tail)


def _check_media(p, t0=None, t1=None):
    missing = _api.missing_files(p, t0, t1)
    if missing:
        raise _api.ToolError("missing_files", "не найдены файлы проекта",
                             problems=[{"path": m, "message": "нет файла"} for m in missing])


def still(p, t, out_png, width=0):
    """Кадр проекта на времени t в PNG (width > 0 — уменьшить до ширины).
    Возвращает {'output', 't' (начало кадра), 'clip' (что видно)}."""
    if p.duration() <= 0 or not p.has_video():
        raise _api.ToolError("nothing_to_render", "в проекте нет картинки")
    out_png = _api.check_output(p, out_png, overwrite=True)
    t0, step = _frame_start(p, t)
    _check_media(p, t0, t0 + step)
    src = _api.montage_project.build_source(p, audio=False, tonemap=_tonemap(p),
                                            window=(t0, t0 + step))
    if src is None or not src.video:
        raise _api.ToolError("nothing_to_render", f"на {t0:.3f} с нет кадра")
    graph = src.graph
    out_label = "[vout]"
    if width and width > 0:
        graph += f";[vout]scale={int(width)}:-2[vsm]"
        out_label = "[vsm]"
    cmd = ([_api.FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostdin"] + src.input_args()
           + ["-filter_complex", graph, "-map", out_label, "-frames:v", "1",
              "-update", "1", str(out_png)])
    _run(cmd, _STILL_TIMEOUT)
    seen = next((c for a, b, c in p.video_segments() if a <= t0 < b), None)
    return {"output": _api.os.path.abspath(str(out_png)), "t": round(t0, 6),
            "clip": seen.id if seen is not None else None}


def sheet_times(p, t0, t1, n):
    """n моментов в [t0, t1): середины n равных частей, по кадрам проекта."""
    n = max(1, min(SHEET_MAX, int(n)))
    t0, t1 = max(0.0, float(t0)), min(float(t1), p.duration())
    if t1 <= t0:
        raise _api.ToolError("bad_range", "пустой отрезок времени")
    step = (t1 - t0) / n
    return [_frame_start(p, t0 + (i + 0.5) * step)[0] for i in range(n)]


def contact_sheet(p, t0, t1, n, out_png, tile_width=320, columns=0):
    """Контактный лист: n кадров отрезка [t0, t1) сеткой, под каждым — время
    проекта и id видимого клипа (по ним модель называет место правки).
    Кадры рендерятся по одному (build_source с окном в кадр) в 4 потока."""
    from PIL import Image, ImageDraw, ImageFont

    out_png = _api.check_output(p, out_png, overwrite=True)
    times = sheet_times(p, t0, t1, n)
    tile_width = max(64, min(1280, int(tile_width)))
    tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_sheet_")
    try:
        paths = [_api.os.path.join(tmpdir, f"{i:03d}.png") for i in range(len(times))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            infos = list(pool.map(lambda a: still(p, a[0], a[1], tile_width),
                                  zip(times, paths)))
        tiles = [Image.open(x).convert("RGB") for x in paths]
        th = max(t.height for t in tiles)
        cols = int(columns) if columns and columns > 0 else min(len(tiles), 4)
        rows = -(-len(tiles) // cols)
        label_h = 22
        sheet = Image.new("RGB", (cols * tile_width, rows * (th + label_h)), "#111827")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype(_TIMECODE_FONT, 14)
        except OSError:
            font = ImageFont.load_default()
        for i, (tile, info) in enumerate(zip(tiles, infos)):
            x, y = (i % cols) * tile_width, (i // cols) * (th + label_h)
            sheet.paste(tile, (x, y))
            draw.text((x + 6, y + th + 3), f"{i + 1}. {info['t']:.3f} с · {info['clip'] or '—'}",
                      font=font, fill="white")
            tile.close()
        sheet.save(str(out_png))
    finally:
        _api.shutil.rmtree(tmpdir, ignore_errors=True)
    return {"output": _api.os.path.abspath(str(out_png)), "columns": cols, "rows": rows,
            "frames": [{"index": i + 1, "t": info["t"], "clip": info["clip"]}
                       for i, info in enumerate(infos)]}


def _timecode_filter(t0):
    """drawtext с временем проекта в углу кадра превью или "" (нет шрифта)."""
    if not _api.os.path.isfile(_TIMECODE_FONT):
        return ""
    font = _api.escape_filter_path(_TIMECODE_FONT)
    return (f",drawtext=fontfile='{font}':text='%{{pts\\:hms\\:{t0:.3f}}}':"
            "x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4")


def preview(p, t0, t1, out_mp4, timecode=True):
    """Ролик отрезка [t0, t1) проекта для модели (Gemini): не длиннее 15 с,
    480p, 12 fps, H.264 + AAC, до 8 МБ — как превью проверки сцен. В углу —
    время проекта (timecode), чтобы ответ модели ложился на шкалу."""
    t0 = max(0.0, float(t0))
    t1 = min(float(t1), p.duration(), t0 + PREVIEW_MAX_S)
    if t1 - t0 <= 0.05:
        raise _api.ToolError("bad_range", "пустой отрезок времени")
    out_mp4 = _api.check_output(p, out_mp4, overwrite=True)
    _check_media(p, t0, t1)
    src = _api.montage_project.build_source(p, tonemap=_tonemap(p), window=(t0, t1))
    if src is None:
        raise _api.ToolError("nothing_to_render", "на отрезке нечего показывать")
    graph = src.graph
    maps = []
    if src.video:
        tc = _timecode_filter(t0) if timecode else ""
        graph += f";[vout]scale=-2:{PREVIEW_HEIGHT}{tc}[pv]"
        maps += ["-map", "[pv]", "-r", str(PREVIEW_FPS), "-c:v", "libx264",
                 "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if src.audio:
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "96k"]
    for crf in (24, 32):
        cmd = ([_api.FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostdin"]
               + src.input_args() + ["-filter_complex", graph] + maps
               + (["-crf:v", str(crf)] if src.video else [])
               + ["-t", f"{src.duration:.6f}", "-movflags", "+faststart", str(out_mp4)])
        _run(cmd, 300)
        size = _api.os.path.getsize(out_mp4)
        if size <= PREVIEW_MAX_BYTES:
            break
    else:
        raise _api.ToolError("preview_too_large", f"превью {size} байт больше 8 МБ")
    return {"output": _api.os.path.abspath(str(out_mp4)), "t0": round(t0, 6),
            "t1": round(t0 + src.duration, 6), "size": size, "video": src.video,
            "audio": src.audio}


# ── Модель ───────────────────────────────────────────────────────────────────
_MIME = {".mp4": ("video", "video/mp4"), ".png": ("image", "image/png"),
         ".jpg": ("image", "image/jpeg"), ".jpeg": ("image", "image/jpeg"),
         ".webp": ("image", "image/webp")}


def gemini_key():
    """Ключ Gemini: переменная окружения GEMINI_API_KEY, иначе ключ из
    настроек программы (api_keys.gemini в settings.json), иначе ""."""
    key = _api.os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    base = (_api.os.getenv("APPDATA") or _api.os.path.expanduser("~")) if _api.os.name == "nt" \
        else _api.os.path.expanduser("~")
    folder = "unified_media_tool" if _api.os.name == "nt" else ".unified_media_tool"
    try:
        with open(_api.os.path.join(base, folder, "settings.json"), "r", encoding="utf-8") as f:
            saved = _api.json.load(f)
    except (OSError, ValueError):
        return ""
    keys = saved.get("api_keys") if isinstance(saved, dict) else None
    return str((keys or {}).get("gemini") or "").strip() if isinstance(keys, dict) else ""


def ask_model(media_paths, prompt, schema, client=None, model=None):
    """Отправляет превью (mp4) или кадры/контактные листы (png, jpg) и вопрос
    в GeminiClient.generate_json со схемой ответа; возвращает разобранный
    JSON. Каждое обращение тратит дневную квоту Gemini. client — готовый
    GeminiClient (тесты, свой ключ); иначе ключ — gemini_key()."""
    parts = []
    for path in media_paths:
        kind = _MIME.get(_api.os.path.splitext(str(path))[1].lower())
        if kind is None:
            raise _api.ToolError("bad_media", f"модели отдаются mp4, png, jpg, webp: {path}")
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > PREVIEW_MAX_BYTES:
            raise _api.ToolError("bad_media", f"больше 8 МБ: {path}")
        parts.append({"type": kind[0], "data": base64.b64encode(data).decode("ascii"),
                      "mime_type": kind[1]})
    parts.append({"type": "text", "text": str(prompt)})
    if client is None:
        import gemini_api
        key = gemini_key()
        if not key:
            raise _api.ToolError("gemini_no_key", "нет ключа Gemini (GEMINI_API_KEY или настройки)")
        client = gemini_api.GeminiClient(key, model=model or gemini_api.DEFAULT_MODEL)
    try:
        return client.generate_json(parts, schema)
    except Exception as e:               # GeminiError и сетевые сбои — ответом JSON
        name = type(e).__name__
        code = "gemini_quota" if "Quota" in name else "gemini_failed"
        raise _api.ToolError(code, f"{name}: {e}") from e
