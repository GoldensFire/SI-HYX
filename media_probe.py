# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# media_probe.py — свойства медиафайла через ffprobe без Qt.
"""Свойства медиафайла через ffprobe, без Qt.

probe_video_props, probe_mastering_nits и qt_pq_max_luminance жили в
edit_tab_frames (тот импортирует QtMultimedia) — он их реэкспортирует.
probe_media — сводка файла для монтажа (montage_tool probe): размер как на
экране, fps, длина, звуковые и субтитровые потоки, HDR."""
import json
import os
import subprocess

from ffmpeg_env import CREATE_NO_WINDOW, FFPROBE

# Картинки вкладка «Монтаж» открывает режимом «картинка → видео» (playback.py).
STILL_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")


class ProbeError(Exception):
    """ffprobe не смог прочитать файл."""


def probe_video_props(path):
    """Свойства первого видеопотока через ffprobe: размер В ПОТОКЕ (до
    поворота), поворот из метаданных (градусы) и цветовые теги. {} — не вышло.

    JSON, а не csv: в csv ffprobe ставит разделитель и в конце строки
    («960x540x», сборки 2026 года) — прежний разбор давал int("540x") →
    (0, 0), и предекодер молча не декодировал ни одного кадра."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries",
             "stream=width,height,sample_aspect_ratio,pix_fmt,color_transfer,"
             "color_space,color_range"
             ":stream_tags=rotate:stream_side_data=rotation",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=15)
        streams = json.loads(out.stdout or "{}").get("streams") or []
    except Exception:
        return {}
    if not streams:
        return {}
    st = streams[0]
    rot = 0
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    if not rot:
        try:
            rot = int(float((st.get("tags") or {}).get("rotate") or 0))
        except (TypeError, ValueError):
            rot = 0
    try:
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    except (TypeError, ValueError):
        w = h = 0
    sar = (1, 1)
    num, _, den = str(st.get("sample_aspect_ratio") or "").partition(":")
    try:
        if int(num) > 0 and int(den) > 0:
            sar = (int(num), int(den))
    except ValueError:
        pass
    return {"width": w, "height": h, "rotation": rot, "sar": sar,
            "pix_fmt": st.get("pix_fmt") or "",
            "transfer": st.get("color_transfer") or "",
            "space": st.get("color_space") or "",
            "range": st.get("color_range") or ""}


def probe_mastering_nits(path):
    """Яркость мастеринга (кд/м²) из первого кадра или None — как её берёт
    ffmpeg-бэкенд Qt (side data «Mastering display metadata»)."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-read_intervals", "%+#1", "-show_frames",
             "-show_entries", "frame=side_data_list", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=20)
        frames = json.loads(out.stdout or "{}").get("frames") or []
    except Exception:
        return None
    for fr in frames[:1]:
        for sd in fr.get("side_data_list") or []:
            val = sd.get("max_luminance")
            if not val:
                continue
            try:
                num, _sep, den = str(val).partition("/")
                return float(num) / float(den or 1)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
    return None


def qt_pq_max_luminance(nits):
    """maxLuminance кадра у ffmpeg-бэкенда Qt: яркость мастеринга × 10000
    (QFFmpegVideoBuffer::maxNits), без метаданных — 10000 (предел PQ)."""
    return float(nits) * 10000.0 if nits and nits > 0 else 10000.0


def parse_fps(stream):
    """fps видеопотока ffprobe ('avg_frame_rate', затем 'r_frame_rate' вида
    'num/den'), как у вкладки (EditTab._parse_fps). 0.0 — неизвестно."""
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = str((stream or {}).get(key) or "")
        num, sep, den = val.partition("/")
        try:
            f = float(num) / float(den) if sep else float(num or 0)
        except (ValueError, ZeroDivisionError):
            continue
        if f > 0:
            return f
    return 0.0


def _is_attached_pic(stream):
    """Обложка (attached_pic) — не видеоряд (см. edit_tab._is_attached_pic)."""
    try:
        return bool(int((stream.get("disposition") or {}).get("attached_pic", 0) or 0))
    except (TypeError, ValueError, AttributeError):
        return False


def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _stream_brief(s):
    tags = s.get("tags") if isinstance(s.get("tags"), dict) else {}
    disp = s.get("disposition") if isinstance(s.get("disposition"), dict) else {}
    return {"index": _num(s.get("index"), int), "codec": s.get("codec_name") or "",
            "language": tags.get("language") or "", "title": tags.get("title") or "",
            "default": bool(disp.get("default")), "forced": bool(disp.get("forced"))}


def probe_media(path, timeout=30):
    """Сводка файла для монтажа (dict, только JSON-типы). ProbeError — файла
    нет или ffprobe его не прочитал.

    video — первый видеопоток (не обложка): width/height — как на экране
    (montage_project.stream_display_size: поворот, неквадратный пиксель),
    stream_width/stream_height — как в потоке; hdr — None, {"kind": "pq",
    "range", "max_luminance"} (сводится в SDR при сборке, hdr_tonemap) или
    {"kind": "hlg"}. clip — поля montage_project.Clip для куска этого файла
    (кроме места и in/out), как их заполняет вкладка."""
    import hdr_tonemap
    import montage_project

    path = str(path)
    if not os.path.isfile(path):
        raise ProbeError(f"файл не найден: {path}")
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=timeout)
        data = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise ProbeError(f"ffprobe: {e}") from e
    if r.returncode != 0 or not isinstance(data, dict) or not data.get("streams"):
        raise ProbeError((r.stderr or "").strip()[-400:] or "ffprobe не нашёл потоков")
    fmt = data.get("format") or {}
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    still = os.path.splitext(path)[1].lower() in STILL_EXTS
    duration = _num(fmt.get("duration")) or 0.0
    vs = next((s for s in streams if s.get("codec_type") == "video"
               and not _is_attached_pic(s)), None)
    video = None
    if vs is not None:
        w, h = montage_project.stream_display_size(vs)
        props = probe_video_props(path) if not still else {}
        hdr = None
        transfer = vs.get("color_transfer") or ""
        if transfer == "smpte2084":
            pq = hdr_tonemap.pq_source(path)
            hdr = {"kind": "pq", "range": pq[0] if pq else "tv",
                   "max_luminance": pq[1] if pq else None}
        elif transfer == "arib-std-b67":
            hdr = {"kind": "hlg"}
        fps = 0.0 if still else parse_fps(vs)
        video = dict(_stream_brief(vs), width=w, height=h,
                     stream_width=_num(vs.get("width"), int) or 0,
                     stream_height=_num(vs.get("height"), int) or 0,
                     rotation=props.get("rotation", 0),
                     sar=vs.get("sample_aspect_ratio") or "1:1",
                     fps=round(fps, 6),
                     fps_expr=montage_project.fps_expr(fps) if fps > 0 else "",
                     pix_fmt=vs.get("pix_fmt") or "", hdr=hdr,
                     duration=_num(vs.get("duration")) or duration)
    audio = [dict(_stream_brief(s), channels=_num(s.get("channels"), int) or 0,
                  sample_rate=_num(s.get("sample_rate"), int) or 0,
                  duration=_num(s.get("duration")) or duration)
             for s in streams if s.get("codec_type") == "audio"]
    subs = [dict(_stream_brief(s),
                 text=(s.get("codec_name") or "") not in ("hdmv_pgs_subtitle",
                                                           "dvd_subtitle", "dvb_subtitle"))
            for s in streams if s.get("codec_type") == "subtitle"]
    clip = {"src": os.path.abspath(path), "has_video": video is not None,
            "is_image": bool(still and video is not None),
            "audio_path": os.path.abspath(path) if audio and not still else "",
            "audio_stream": audio[0]["index"] if audio and not still else -1,
            "width": video["width"] if video else 0,
            "height": video["height"] if video else 0,
            "fps": video["fps"] if video else 0.0,
            "src_duration": 0.0 if still else duration}
    return {"path": os.path.abspath(path), "format": fmt.get("format_name") or "",
            "duration": duration, "size": _num(fmt.get("size"), int) or 0,
            "bit_rate": _num(fmt.get("bit_rate"), int) or 0, "is_image": clip["is_image"],
            "video": video, "audio": audio, "subtitles": subs, "clip": clip}
