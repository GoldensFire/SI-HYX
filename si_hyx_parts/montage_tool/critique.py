# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Отчёт-критик монтажа под музыку: check-sync <проект>.
Public namespace: montage_tool.

Резы — стыки клипов основной дорожки (у перехода — его конец: входящий
план виден целиком).
Для каждого: смещение в кадрах проекта от ближайшей доли, сильной доли и
удара (бочка, малый) по маркерам проекта (music --write или autofill).
Итог: доля резов на сетке (±1 кадр), на сильных долях, на ударах; по
частям песни — резов в секунду против рекомендованного по энергии части;
гистограмма длин; повторы кусков исходника; соседние куски одного плана
(скачок внутри плана); по каталогу — тёмные кадры, вспышки на резе,
хардсаб, опенинг/эндинг. Текст песни — запаздывание (lyric_lateness):
когда текст читается, против звука его слова. Проблемы — списком со
временем проекта."""
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


# Текст читается к середине появления (in_s); без in_s у анимации — как в
# text_fx.kinetic_text. Позже звука слова больше чем на кадр — проблема.
LYRIC_MATCH = 0.6                    # сходство подписи метки word со словом текста
LYRIC_REACH_S = 1.0                  # метка слова ищется не дальше от начала текста
ATTACK_REACH_S = 0.15                # атака вокала — не дальше от метки слова
LYRIC_EARLY_S = 0.6                  # раньше — текст висит до слова слишком долго


def _readable_at(t):
    st = t.style or {}
    anim = st.get("animation", "none")
    dur = max(0.01, t.end - t.start)
    in_s = st.get("in_s")
    if in_s is None:
        in_s = 0.0 if anim in ("none", "") else min(0.3, max(0.06, dur / 3))
    return t.start + 0.5 * float(in_s)


def vocal_attacks(p, ctl=None, python=""):
    """Атаки вокала звука проекта (время проекта): начала звука стема вокала
    HTDemucs из кэша карты песни (music_project; нет — считается)."""
    from si_hyx_parts.montage_tool import analysis as _an
    m = _api.music_project(p, 0.0, None, None, python=python, drums=True, sections=False,
                           ctl=ctl)
    path = _api.os.path.join(m["cache"], "stems", "vocals.wav")
    if not _api.os.path.isfile(path):
        raise _api.ToolError("ml_unavailable", "нет стема вокала (нужен Python генератора)")
    env = _an.onset_envelope(_an.file_audio(path))
    return np.array([i * _an.HOP_S + _an.ONSET_LAG_S for i in _an.pick_onsets(env)])


def lyric_lateness(p, attacks=None):
    """Тексты проекта против звука слов: время слова — метка word с тем же
    словом (первое слово текста), с attacks — ближайшая к ней атака вокала.
    {texts, matched, late, mean_late_s, max_late_s, rows, problems}."""
    from rapidfuzz import fuzz
    from si_hyx_parts.montage_tool.typography import _key
    fps = p.output_format()[2]
    words = sorted((m for m in p.markers if m.kind == "word" and m.label.strip()),
                   key=lambda m: m.t)
    wt = np.array([m.t for m in words])
    rows, problems = [], []
    for t in sorted(p.texts, key=lambda t: t.start):
        first = next((k for k in map(_key, t.text.split()) if k), "")
        if not first or not len(wt):
            continue
        i0 = int(np.searchsorted(wt, t.start - LYRIC_REACH_S))
        i1 = int(np.searchsorted(wt, t.start + LYRIC_REACH_S))
        cand = [(abs(words[i].t - t.start), i) for i in range(i0, i1)
                if fuzz.ratio(first, _key(words[i].label)) / 100.0 >= LYRIC_MATCH]
        if not cand:
            continue
        sung = words[min(cand)[1]].t
        src = "word"
        if attacks is not None and len(attacks):
            d = _nearest(attacks, sung)
            if d is not None and abs(d) <= ATTACK_REACH_S:
                sung, src = sung + d, "attack"
        seen = _readable_at(t)
        late = seen - sung
        row = {"t": round(t.start, 3), "text": t.id, "sung": round(sung, 3), "by": src,
               "late_s": round(late, 3), "late_frames": round(late * fps, 2)}
        rows.append(row)
        if late * fps > 1.0:
            problems.append({"t": row["t"], "kind": "lyric_late", "text": t.id,
                             "message": f"текст читается на {late:.2f} с позже слова "
                                        f"(начало {t.start:.2f}, слово {sung:.2f})"})
        elif late < -LYRIC_EARLY_S:
            problems.append({"t": row["t"], "kind": "lyric_early", "text": t.id,
                             "message": f"текст на {-late:.2f} с раньше слова"})
    lates = [r["late_s"] for r in rows]
    return {"texts": len(p.texts), "matched": len(rows),
            "late": sum(1 for r in rows if r["late_frames"] > 1.0),
            "mean_late_s": round(float(np.mean(lates)), 3) if lates else None,
            "max_late_s": round(float(np.max(lates)), 3) if lates else None,
            "attacks": attacks is not None, "rows": rows, "problems": problems}


def check_sync(p, db=None, attacks=None):
    """Отчёт (только JSON-типы): числа, резы с отклонениями и проблемы.
    attacks — атаки вокала (vocal_attacks) для запаздывания текста."""
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
    # Рез растворения — его конец (новый план виден целиком): так его ставит
    # на долю autofill --style.
    cuts = [c.start + p.transition_overlap(prev, c) for prev, c in zip(main, main[1:])]
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
    lyrics = lyric_lateness(p, attacks) if p.texts else None
    if lyrics:
        problems += lyrics.pop("problems")
    summary = {"cuts": n, "fps": fps,
               "on_beat": round(sum(r["on_beat"] for r in rows) / n, 3),
               "on_downbeat": round(sum(r["on_downbeat"] for r in rows) / n, 3),
               "on_hit": round(sum(r["on_hit"] for r in rows) / n, 3),
               "mean_abs_beat_frames": round(float(np.mean([abs(r["beat_frames"]) for r in rows
                                                            if r["beat_frames"] is not None])), 3),
               "clips": len(main), "mean_length": round(float(np.mean(lengths)), 3),
               "clips_in_catalog": catalog, "problems": len(problems)}
    if lyrics:
        summary["lyrics_late"] = lyrics["late"]
        summary["lyrics_mean_late_s"] = lyrics["mean_late_s"]
    return {"summary": summary, "length_histogram": hist, "sections": sections,
            "cuts": rows, "lyrics": lyrics, "problems": sorted(problems, key=lambda x: x["t"])}
