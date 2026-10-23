# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Таймлайн проекта словами JSON: что видно, что слышно, откуда.
Public namespace: montage_tool."""
import montage_tool as _api


def _r(v):
    """Секунды до микросекунды — JSON без хвостов 0.30000000000000004."""
    return round(float(v), 6)


def _clip_brief(p, c):
    return {"id": c.id, "track": c.track, "track_name": p.track_name(c.track),
            "start": _r(c.start), "end": _r(c.end), "length": _r(c.length),
            "src": c.src, "in_s": _r(c.in_s), "out_s": _r(c.out_s),
            "speed": _r(c.play_speed), "has_video": c.has_video, "is_image": c.is_image,
            "width": c.width, "height": c.height, "fps": _r(c.fps),
            "src_duration": _r(c.src_duration),
            "audio": ({"path": c.audio_path, "stream": c.audio_stream,
                       "volume": _r(c.volume), "muted": c.muted,
                       "detached": c.audio_detached} if c.audio_path else None)}


def _span(c, t0, t1):
    """Кусок клипа c на [t0, t1) проекта: время исходника его краёв."""
    return {"clip": c.id, "t0": _r(t0), "t1": _r(t1),
            "src": c.src if c.has_video else c.audio_path,
            "src_in": _r(c.source_time(t0)), "src_out": _r(c.source_time(t1)),
            "speed": _r(c.play_speed)}


def describe_project(p, at=None):
    """Словарь (только JSON-типы): формат итога, дорожки, клипы, что видно
    (video — куски кадра, как их склеит сборка; clip None — чёрный кадр) и
    что слышно (audio — все клипы, чей звук смешивается). at — время
    проекта: ещё и что видно и слышно в этот момент, со временем исходника."""
    w, h, fps = p.output_format()
    video = []
    for t0, t1, c in p.video_segments():
        if c is None:
            video.append({"clip": None, "t0": _r(t0), "t1": _r(t1)})
        else:
            video.append(_span(c, t0, t1))
    audio = [dict(_span(c, c.start, c.end), src=c.audio_path, stream=c.audio_stream,
                  volume=_r(c.volume))
             for c in sorted(p.audio_parts(), key=lambda c: (c.start, c.track))]
    out = {
        "duration": _r(p.duration()),
        "format": {"width": w, "height": h, "fps": _r(fps),
                   "fps_expr": _api.montage_project.fps_expr(fps)},
        "main_track": p.main_track,
        "tracks": [{"index": i, "kind": t.kind, "name": p.track_name(i),
                    "main": i == p.main_track, "enabled": t.enabled, "muted": t.muted,
                    "clips": [c.id for c in p.clips_on(i)]}
                   for i, t in enumerate(p.tracks)],
        "clips": [_clip_brief(p, c) for c in sorted(p.clips, key=lambda c: (c.track, c.start))],
        "video": video,
        "audio": audio,
        "markers": [{"t": _r(m.t), "kind": m.kind, "label": m.label,
                     "strength": _r(m.strength),
                     "end": None if m.end is None else _r(m.end)} for m in p.markers],
    }
    if at is not None:
        t = float(at)
        seen = next((s for s in video if s["t0"] <= t < s["t1"]), None)
        heard = []
        for c in p.audio_parts():
            if c.start <= t < c.end:
                heard.append({"clip": c.id, "src": c.audio_path,
                              "src_time": _r(c.source_time(t)), "volume": _r(c.volume)})
        vis = None
        if seen is not None and seen["clip"] is not None:
            c = p.clip(seen["clip"])
            vis = {"clip": c.id, "src": c.src, "src_time": _r(c.source_time(t)),
                   "track": c.track}
        out["at"] = {"t": _r(t), "video": vis, "audio": heard}
    return out
