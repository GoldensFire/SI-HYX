# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Скелет готового AMV: reference <ролик> [--out skeleton.json].
Public namespace: montage_tool.

Картинка эталона — кадры 160×88 одним ffmpeg: разность соседних кадров
(средняя и доля изменившихся пикселей), расстояние цветовых гистограмм,
яркость. События — пики разности (не ближе 3 кадров):
  cut   — сменился весь кадр (доля > CUT_AREA и другая гистограмма);
  layer — сменилась часть кадра (панель, вставка, вырезка, текст);
  flash — скачок яркости вверх, который тут же спадает.
Звук эталона — карта песни music (доли Beat This!): время события →
позиция в долях от первой сильной доли («beat» 7.5 — середина восьмой
доли). Так ритм монтажа не зависит от темпа: autofill --template переносит
события на доли другой песни — резы основной дорожки на те же доли,
появления слоёв и вспышки — маркерами custom (pop, flash) в проект.
Сводка — доля резов на долях и полудолях (±2 кадра) и средняя длина плана
в долях: видно, режет ли эталон «на каждую долю» или на восьмые."""
import json

import numpy as np

import montage_tool as _api

W, H = 160, 88                     # кратно 4: клетки 4×4
CUT_AREA = 0.7
LAYER_AREA = 0.12
EVENT_KINDS = ("cut", "layer", "flash")


def _frames(path, ctl):
    """(кадры uint8 [n, H, W, 3], fps)."""
    probe = _api.media_probe.probe_media(path)
    fps = float((probe.get("clip") or {}).get("fps") or 0.0) or 30.0
    ctl.stage("frames", path=path)
    raw = _api.subprocess.run(
        [_api.FFMPEG, "-v", "error", "-nostdin", "-i", path, "-map", "0:v:0", "-vf",
         f"scale={W}:{H}:flags=area,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, creationflags=_api.CREATE_NO_WINDOW, timeout=1800).stdout
    n = len(raw) // (W * H * 3)
    if n < 2:
        raise _api.ToolError("nothing_to_render", "в ролике нет кадров")
    return np.frombuffer(raw[: n * W * H * 3], np.uint8).reshape(n, H, W, 3), fps


def _hist(f):
    q = (f // 32).astype(np.int32)
    idx = q[..., 0] * 64 + q[..., 1] * 8 + q[..., 2]
    h = np.bincount(idx.ravel(), minlength=512).astype(np.float64)
    return h / h.sum()


def frame_events(frames, fps):
    """События картинки [{'frame', 't', 'kind', 'area'}] (см. модуль).

    Событие — импульс: разность кадра с прошлым заметно выше, чем у соседей
    (движение камеры, дождь, огонь меняют кадры подряд и импульса не дают).
    Вид — по клеткам 4×4: сменились почти все — рез, часть — слой."""
    n = len(frames)
    luma = frames.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    ymean = luma.mean(axis=(1, 2))
    d = np.abs(np.diff(luma, axis=0))
    diff = np.concatenate([[0.0], d.mean(axis=(1, 2))])
    cells = np.concatenate([np.zeros((1, 4, 4), np.float32),
                            d.reshape(n - 1, 4, H // 4, 4, W // 4).mean(axis=(2, 4))])
    hists = [_hist(f) for f in frames]
    hd = np.zeros(n)
    for i in range(1, n):
        hd[i] = np.sqrt(max(0.0, 1.0 - np.sum(np.sqrt(hists[i] * hists[i - 1]))))
    cand = []
    for i in range(1, n):
        around = [diff[j] for j in range(max(1, i - 4), min(n, i + 5)) if abs(j - i) > 1]
        base = float(np.median(around)) if around else 0.0
        if diff[i] > 8.0 and diff[i] > 2.2 * base + 3.0:
            cand.append(i)
    picked = []
    for i in cand:
        if picked and i - picked[-1] < 3:
            if diff[i] > diff[picked[-1]]:
                picked[-1] = i
            continue
        picked.append(i)
    out = []
    for i in picked:
        after = ymean[min(n - 1, i + 3)]
        changed = float((cells[i] > 18.0).mean())
        if ymean[i] - ymean[i - 1] > 35 and ymean[i] - after > 20:
            kind = "flash"
        elif changed >= CUT_AREA or hd[i] > 0.5:
            kind = "cut"
        elif changed >= LAYER_AREA:
            kind = "layer"
        else:
            continue
        out.append({"frame": int(i), "t": round(i / fps, 4), "kind": kind,
                    "area": round(changed, 3)})
    return out


def beat_position(t, beats):
    """Позиция времени t в долях (номер доли с дробью) по списку долей."""
    b = np.asarray(beats, float)
    if len(b) < 2:
        return float(t)
    period = float(np.median(np.diff(b)))
    if t <= b[0]:
        return (t - b[0]) / period
    if t >= b[-1]:
        return len(b) - 1 + (t - b[-1]) / period
    k = int(np.searchsorted(b, t, side="right") - 1)
    return k + (t - b[k]) / (b[k + 1] - b[k])


def beat_time(pos, beats):
    """Обратное beat_position: время позиции pos в долях."""
    b = np.asarray(beats, float)
    period = float(np.median(np.diff(b))) if len(b) > 1 else 0.5
    if pos <= 0:
        return float(b[0] + pos * period)
    if pos >= len(b) - 1:
        return float(b[-1] + (pos - (len(b) - 1)) * period)
    k = int(np.floor(pos))
    return float(b[k] + (pos - k) * (b[k + 1] - b[k]))


def reference(video, out=None, ctl=None, beat_model=None):
    """Скелет эталона (см. модуль); out — ещё и JSON-файлом."""
    ctl = ctl or _api.NO_CONTROL
    video = _api.os.path.abspath(str(video))
    frames, fps = _frames(video, ctl)
    events = frame_events(frames, fps)
    m = _api.music_file(video, model=beat_model or _api.DEFAULT_BEAT_MODEL, ctl=ctl)
    beats = [b["t"] for b in m["beats"]]
    if len(beats) < 4:
        raise _api.ToolError("no_beats", "в звуке эталона не нашлось долей")
    downs = [b["t"] for b in m["beats"] if b.get("pos") == 1]
    k0 = beats.index(downs[0]) if downs else 0
    for e in events:
        e["beat"] = round(beat_position(e["t"], beats) - k0, 3)
    duration = len(frames) / fps
    cuts = [e for e in events if e["kind"] == "cut"]
    bounds = [0.0] + [e["t"] for e in cuts] + [duration]
    shots = [{"t0": round(a, 4), "t1": round(b, 4),
              "beats": round(beat_position(b, beats) - beat_position(a, beats), 3)}
             for a, b in zip(bounds, bounds[1:]) if b - a > 0.5 / fps]
    tol = 2.0 / fps

    def near(e, grid):
        return min(abs(e["t"] - g) for g in grid) <= tol

    halves = sorted(beats + [(a + b) / 2 for a, b in zip(beats, beats[1:])])
    stats = {"events": len(events), **{k: sum(e["kind"] == k for e in events) for k in EVENT_KINDS},
             "median_shot_beats": round(float(np.median([s["beats"] for s in shots])), 3)
             if shots else None,
             "cuts_on_beat": round(np.mean([near(e, beats) for e in cuts]), 3) if cuts else None,
             "cuts_on_half_beat": round(np.mean([near(e, halves) for e in cuts]), 3)
             if cuts else None,
             "events_on_half_beat": round(np.mean([near(e, halves) for e in events]), 3)
             if events else None}
    skel = {"source": video, "duration": round(duration, 4), "fps": fps, "tempo": m["tempo"],
            "meter": m.get("meter"), "first_downbeat": round(beats[k0], 4),
            "beats_total": round(beat_position(duration, beats) - k0, 3),
            "events": events, "shots": shots, "stats": stats,
            "sections": [{k: s[k] for k in ("label", "group", "t", "end", "energy") if k in s}
                         for s in m.get("sections", [])]}
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(skel, f, ensure_ascii=False, indent=1)
        skel["output"] = _api.os.path.abspath(str(out))
    return skel


def template_times(skel, m, t0, kinds=EVENT_KINDS):
    """События скелета на долях песни m от сильной доли у t0: (время песни
    начала, конца и [(время, вид)])."""
    beats = [b["t"] for b in m["beats"]]
    if len(beats) < 4:
        raise _api.ToolError("no_beats", "в песне не нашлось долей")
    downs = [b["t"] for b in m["beats"] if b.get("pos") == 1] or beats
    start = min(downs, key=lambda x: abs(x - t0))
    k0 = beats.index(start)
    end = beat_time(k0 + float(skel["beats_total"]), beats)
    # Позиции — на сетке четвертей доли: эталон режет на кадр позже доли
    # (кадр показа), и на другом темпе этот сдвиг рос бы в кадры мимо доли.
    evs = [(beat_time(k0 + round(float(e["beat"]) * 4) / 4.0, beats), e["kind"])
           for e in skel["events"] if e["kind"] in kinds]
    return start, min(end, m["duration"]), [(t, k) for t, k in evs if start <= t < end]
