# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Отчёт-критик монтажа под музыку: check-sync <проект>.
Public namespace: montage_tool.

Резы — стыки клипов основной дорожки (у перехода — начало входящего).
Для каждого: смещение в кадрах проекта от ближайшей доли, сильной доли и
удара (бочка, малый) по маркерам проекта (music --write или autofill).
Итог: доля резов на сетке (±1 кадр), на сильных долях, на ударах; по
частям песни — резов в секунду против рекомендованного по энергии части;
гистограмма длин; повторы кусков исходника; соседние куски одного плана
(скачок внутри плана); по каталогу — тёмные кадры, вспышки на резе,
хардсаб, опенинг/эндинг. Проблемы — списком со временем проекта."""
import collections

import numpy as np

import montage_tool as _api

ON_GRID_FRAMES = 1
LENGTH_BINS = (0.0, 0.5, 1.0, 2.0, 4.0, float("inf"))


def _nearest(arr, t):
    if not len(arr):
        return None
    i = int(np.searchsorted(arr, t))
    best = min((j for j in (i - 1, i) if 0 <= j < len(arr)), key=lambda j: abs(arr[j] - t))
    return float(arr[best] - t)


def _catalog_hits(db, clip):
    """Планы каталога, которые попали в клип (по файлу и времени исходника)."""
    try:
        con = _api.connect(db)
    except Exception:                    # noqa: BLE001 — каталога нет: проверки по нему пропускаются
        return None
    try:
        f = con.execute("SELECT id FROM files WHERE path=?",
                        (_api.os.path.abspath(clip.src),)).fetchone()
        if f is None:
            return None
        return con.execute("SELECT * FROM shots WHERE file_id=? AND t1>? AND t0<? ORDER BY t0",
                           (f["id"], clip.in_s, clip.out_s)).fetchall()
    finally:
        con.close()


def check_sync(p, db=None):
    """Отчёт (только JSON-типы): числа, резы с отклонениями и проблемы."""
    fps = p.output_format()[2]
    main = p.clips_on(p.main_track)
    if len(main) < 2:
        raise _api.ToolError("nothing_to_render", "на основной дорожке меньше двух клипов")
    by = collections.defaultdict(list)
    for mk in p.markers:
        by[mk.kind].append(mk)
    beats = np.array(sorted(m.t for m in by["beat"]))
    downs = np.array(sorted(m.t for m in by["downbeat"]))
    hits = np.array(sorted(m.t for k in ("kick", "snare") for m in by[k]))
    if not len(beats):
        raise _api.ToolError("no_markers", "в проекте нет маркеров долей: music --write или autofill")
    cuts = [c.start for c in main[1:]]
    rows, problems = [], []
    for c, t in zip(main[1:], cuts):
        d_beat, d_down, d_hit = (_nearest(beats, t), _nearest(downs, t), _nearest(hits, t))
        row = {"t": round(t, 4), "clip": c.id,
               "beat_frames": None if d_beat is None else round(d_beat * fps, 2),
               "downbeat_frames": None if d_down is None else round(d_down * fps, 2),
               "hit_frames": None if d_hit is None else round(d_hit * fps, 2)}
        row["on_beat"] = d_beat is not None and abs(d_beat * fps) <= ON_GRID_FRAMES
        row["on_downbeat"] = d_down is not None and abs(d_down * fps) <= ON_GRID_FRAMES
        row["on_hit"] = d_hit is not None and abs(d_hit * fps) <= ON_GRID_FRAMES
        rows.append(row)
        if not row["on_beat"]:
            problems.append({"t": row["t"], "kind": "off_beat", "clip": c.id,
                             "message": f"рез мимо доли на {row['beat_frames']} кадр."})
    n = len(rows)
    lengths = [c.length for c in main]
    hist = {f"{lo:g}-{hi:g}": sum(lo <= x < hi for x in lengths)
            for lo, hi in zip(LENGTH_BINS, LENGTH_BINS[1:])}
    # Части: резы в секунду против рекомендованного по энергии (music._spacing_s).
    from si_hyx_parts.montage_tool.music import _spacing_s
    sections = []
    for s in sorted(by["section"], key=lambda m: m.t):
        end = s.end if s.end is not None else p.duration()
        k = sum(1 for t in cuts if s.t <= t < end)
        dur = max(0.01, end - s.t)
        want = 1.0 / (_spacing_s(s.strength) * 1.6)   # в среднем шаг ~1,6 наименьшего
        rate = k / dur
        sections.append({"label": s.label, "t": round(s.t, 3), "end": round(end, 3),
                         "energy": round(s.strength, 3), "cuts": k, "cuts_per_s": round(rate, 3),
                         "suggested_per_s": round(want, 3)})
        if dur >= 3.0 and rate > 2.0 * want:
            problems.append({"t": round(s.t, 3), "kind": "too_dense",
                             "message": f"{s.label}: {rate:.2f} реза/с при энергии {s.strength:.2f}"})
        elif dur >= 3.0 and rate < 0.4 * want:
            problems.append({"t": round(s.t, 3), "kind": "too_sparse",
                             "message": f"{s.label}: {rate:.2f} реза/с при энергии {s.strength:.2f}"})
    # Повторы и соседние куски одного плана.
    seen = []
    for c in main:
        for o in seen:
            if (o.src == c.src and min(o.out_s, c.out_s) - max(o.in_s, c.in_s) > 0.1):
                problems.append({"t": round(c.start, 3), "kind": "repeat", "clip": c.id,
                                 "message": f"кусок исходника уже был в клипе {o.id}"})
                break
        seen.append(c)
    for a, b in zip(main, main[1:]):
        if a.src == b.src and abs(b.in_s - a.out_s) < 0.5:
            problems.append({"t": round(b.start, 3), "kind": "jump_cut", "clip": b.id,
                             "message": "соседние куски одного плана: рез выглядит скачком"})
    # По каталогу: темнота, вспышка у реза, хардсаб, опенинг/эндинг.
    catalog = 0
    for c in main:
        shots = _catalog_hits(db, c)
        if not shots:
            continue
        catalog += 1
        for s in shots:
            if s["hardsub"]:
                problems.append({"t": round(c.start, 3), "kind": "hardsub", "clip": c.id,
                                 "message": f"в плане #{s['id']} хардсаб"})
            if s["oped"]:
                problems.append({"t": round(c.start, 3), "kind": "oped", "clip": c.id,
                                 "message": f"план #{s['id']} из {s['oped']}"})
            if s["brightness"] < 0.06:
                problems.append({"t": round(c.start, 3), "kind": "dark", "clip": c.id,
                                 "message": f"план #{s['id']} почти чёрный"})
            for acc in _api.json.loads(s["accents"] or "[]"):
                if acc.get("kind") == "flash" and abs(acc["t"] - c.in_s) < 0.1:
                    problems.append({"t": round(c.start, 3), "kind": "flash_at_cut", "clip": c.id,
                                     "message": "клип начинается со вспышки"})
    summary = {"cuts": n, "fps": fps,
               "on_beat": round(sum(r["on_beat"] for r in rows) / n, 3),
               "on_downbeat": round(sum(r["on_downbeat"] for r in rows) / n, 3),
               "on_hit": round(sum(r["on_hit"] for r in rows) / n, 3),
               "mean_abs_beat_frames": round(float(np.mean([abs(r["beat_frames"]) for r in rows
                                                            if r["beat_frames"] is not None])), 3),
               "clips": len(main), "mean_length": round(float(np.mean(lengths)), 3),
               "clips_in_catalog": catalog, "problems": len(problems)}
    return {"summary": summary, "length_histogram": hist, "sections": sections,
            "cuts": rows, "problems": sorted(problems, key=lambda x: x["t"])}
