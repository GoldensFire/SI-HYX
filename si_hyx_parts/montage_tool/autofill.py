# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Черновик AMV: autofill <проект> --song … --library … [--plan plan.json].
Public namespace: montage_tool.

Песня (music.py) даёт рекомендованные места резов окна [t0, t1) песни —
их время прилипает к сетке кадров проекта, промежутки становятся
отрезками основной дорожки (короче min_shot — сливаются с соседом).
Кандидаты — планы каталога (library.py) без опенинга/эндинга и
растворений, длиннее отрезка, по фильтрам плана (файлы, теги, без
текста). Оценка плана для отрезка: движение плана ↔ энергия такта, теги и
персонажи из плана части, подгон акцента — in_s выбирается так, чтобы
самый сильный акцент плана (вспышка, пик движения) пришёлся на сильную
долю или удар внутри отрезка. Выбор — динамическим программированием
(Витерби) по отрезкам с ценой перехода: тот же файл рядом по времени,
та же крупность три раза подряд; повторы планов потом заменяются
следующими по оценке. Звук планов выключен, песня — на звуковой дорожке
с ролью music; маркеры песни пишутся в проект во времени проекта."""
import json
import math

import numpy as np

import montage_tool as _api

DEFAULT_MIN_SHOT = 0.35
# --fx amv: удары — зум-удар по бочке, тряска по малому в припеве, вспышка на
# начале части; эффекты разворачиваются по маркерам проекта при сборке.
FX_PRESETS = {
    "amv": [{"type": "zoom_punch", "on": "kick", "amount": 0.05, "decay": 0.15},
            {"type": "shake", "on": "snare", "section": "chorus", "amount": 0.012,
             "decay": 0.2},
            {"type": "flash", "on": "section", "amount": 0.6, "decay": 0.2}],
    "soft": [{"type": "zoom_punch", "on": "downbeat", "amount": 0.03, "decay": 0.25}]}
TOP_K = 40                         # кандидатов на отрезок в ДП


def _plan(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise _api.ToolError("bad_plan", f"план не прочитан: {e}") from e
    if not isinstance(data, dict):
        raise _api.ToolError("bad_plan", "план — JSON-объект")
    return data


def pick_window(m, duration):
    """Окно песни длиной ~duration: начинается с начала части (лучше —
    подводки или припева), конец — на начале такта."""
    bars = [b["t"] for b in m["bars"]]
    best, score = (0.0, min(duration, m["duration"])), -1e9
    for s in m["sections"]:
        t0 = s["t"]
        t1 = t0 + duration
        if t1 > m["duration"] + 0.5:
            continue
        inside = [x for x in m["sections"] if x["t"] < t1 and x["end"] > t0]
        e = np.mean([x["energy"] for x in inside]) if inside else 0.0
        bonus = 0.3 * any(x["label"] in ("chorus", "drop") for x in inside) + \
            0.15 * (s["label"] in ("build", "chorus", "drop"))
        if e + bonus > score:
            score, best = e + bonus, (t0, t1)
    t0, t1 = best
    later = [b for b in bars if b > t0 + duration / 2]
    if later:                            # конец окна — на начале такта
        t1 = min(later, key=lambda b: abs(b - t1))
    return round(t0, 3), round(min(t1, m["duration"]), 3)


def segments(m, t0, t1, fps, min_shot):
    """Отрезки [(начало, конец)] в кадрах проекта (0 — t0 песни) по
    рекомендованным местам резов; короткие сливаются с соседом."""
    cuts = sorted({round((s["t"] - t0) * fps) for s in m["slots"]
                   if s.get("recommended") and t0 < s["t"] < t1})
    end = int(round((t1 - t0) * fps))
    bounds = [0] + [c for c in cuts if 0 < c < end] + [end]
    min_f = max(1, int(math.ceil(min_shot * fps)))
    merged = [bounds[0]]
    for b in bounds[1:]:
        if b - merged[-1] < min_f and b != end:
            continue
        if b == end and b - merged[-1] < min_f and len(merged) > 1:
            merged[-1] = b
            continue
        merged.append(b)
    return list(zip(merged, merged[1:]))


def _hits_in(m, a, b):
    """Сильные места отрезка [a, b) песни: удары бочки и малого, сильные доли."""
    out = []
    for kind, w in (("kick", 1.0), ("snare", 1.0)):
        for h in m["hits"].get(kind, []):
            if a <= h[0] < b:
                out.append((h[0], w * h[1]))
    for bar in m["bars"]:
        if a <= bar["t"] < b:
            out.append((bar["t"], 0.8))
    return out


def _energy_at(m, a, b):
    vals = [bar["energy"] for bar in m["bars"] if bar["t"] < b and bar["end"] > a
            and bar.get("energy") is not None]
    return float(np.mean(vals)) if vals else 0.5


def _section_at(m, t):
    for s in m["sections"]:
        if s["t"] <= t < s["end"]:
            return s
    return {"label": "", "group": ""}


def _align(shot, seg_len, hits_rel):
    """(in_s, оценка подгона): самый сильный акцент плана — на удар внутри
    отрезка (hits_rel — время от начала отрезка и сила); не выходит — середина.
    in_s — на сетке кадров исходника: иначе подрезка (Project.trim прилипает
    к кадру исходника) сдвигала бы все стыки после клипа на доли кадра."""
    fps = float(shot.get("fps") or 0.0)
    in_s, sc = _align_raw(shot, seg_len, hits_rel)
    if fps > 0:
        snapped = round(in_s * fps) / fps
        if shot["t0"] - 1e-6 <= snapped and snapped + seg_len <= shot["t1"] + 1e-6:
            in_s = snapped
    return in_s, sc


def _align_raw(shot, seg_len, hits_rel):
    t0, t1 = shot["t0"], shot["t1"]
    best_in, best = None, 0.0
    for acc in shot["accents"]:
        for tau, hs in hits_rel:
            if tau < 0.12 or tau > seg_len - 0.05:
                continue                 # удар на самом резе — акцент не виден (и вспышка на резе)
            in_s = acc["t"] - tau
            if t0 <= in_s and in_s + seg_len <= t1:
                sc = acc["strength"] * hs
                if sc > best:
                    best, best_in = sc, in_s
    if best_in is None:
        best_in = max(t0, (t0 + t1) / 2 - seg_len / 2)
        best_in = min(best_in, t1 - seg_len)
    return best_in, best


def _match_section(shot, rule):
    """Бонус плана за правило части плана: теги, персонажи, крупность, движение."""
    if not rule:
        return 0.0
    tags = set(shot["tags"]) | set(shot["character_tags"])
    sc = 0.0
    if rule.get("tags_any") and tags & {t.replace(" ", "_").lower() for t in rule["tags_any"]}:
        sc += 0.4
    names = {str(c["id"]) for c in shot["characters"]} | {c["name"].lower() for c in shot["characters"]}
    if rule.get("characters") and names & {str(x).lower() for x in rule["characters"]}:
        sc += 0.4
    if rule.get("scale") and shot["scale"] in rule["scale"]:
        sc += 0.2
    if rule.get("tags_none") and tags & {t.replace(" ", "_").lower() for t in rule["tags_none"]}:
        sc -= 1.0
    return sc


def autofill(project_path, song, db=None, plan=None, t0=None, t1=None, duration=None,
             min_shot=DEFAULT_MIN_SHOT, width=0, height=0, ctl=None, beat_model=None,
             overwrite=False, fx=""):
    """Черновик: проект с песней и планами каталога под места резов."""
    ctl = ctl or _api.NO_CONTROL
    plan = _plan(plan) if isinstance(plan, (str, type(None))) else dict(plan)
    if _api.os.path.exists(str(project_path)) and not overwrite:
        raise _api.ToolError("output_exists", f"проект уже есть: {project_path} (--overwrite)")
    m = _api.music_file(song, model=beat_model or _api.DEFAULT_BEAT_MODEL, ctl=ctl)
    if t0 is None:
        t0, t1 = pick_window(m, float(duration or 45.0))
    t1 = m["duration"] if t1 is None else min(float(t1), m["duration"])
    t0 = float(t0)
    if t1 - t0 < 2.0:
        raise _api.ToolError("bad_range", "окно песни короче 2 с")
    min_shot = float(plan.get("min_shot", min_shot))
    found = _api.search(db, tags_none=plan.get("exclude_tags", ()), no_text=plan.get("no_text", True),
                        file=plan.get("file", ""), min_len=min_shot, limit=100000)["shots"]
    files = plan.get("files") or []
    if files:
        found = [s for s in found if any(str(f).lower() in s["file"].lower() for f in files)]
    avoid = {int(x) for x in plan.get("avoid", [])}
    # Почти чёрные планы — не в черновик (check-sync их отметил бы как dark).
    found = [s for s in found if s["id"] not in avoid and not s["hardsub"]
             and s["brightness"] >= 0.06]
    if not found:
        raise _api.ToolError("nothing_to_render", "в каталоге нет подходящих планов (index?)")
    fps = float(plan.get("fps") or found[0]["fps"] or 24.0)
    segs = segments(m, t0, t1, fps, min_shot)
    # Движение планов — в ранги 0…1 (энергия тактов тоже в 0…1).
    mot = np.array([s["motion"] for s in found])
    order = np.argsort(np.argsort(mot))
    mot_rank = order / max(1, len(found) - 1)
    rules = plan.get("sections") or {}
    prefer = {int(x) for x in plan.get("prefer", [])}
    cand, unary, aligned, spare = [], [], [], []
    for a, b in segs:
        L = (b - a) / fps
        sa, sb = t0 + a / fps, t0 + b / fps
        e = _energy_at(m, sa, sb)
        sec = _section_at(m, (sa + sb) / 2)
        rule = rules.get(sec["label"]) or rules.get("default") or {}
        hits = [(t - sa, s) for t, s in _hits_in(m, sa, sb)]
        rows = []
        for k, s in enumerate(found):
            if s["length"] < L + 2.0 / fps:
                continue
            want = rule.get("motion")
            target = {"high": 0.9, "low": 0.15}.get(want, e)
            sc = 1.0 - abs(target - mot_rank[k])
            in_s, acc = _align(s, L, hits)
            sc += 0.6 * acc + _match_section(s, rule) + (0.5 if s["id"] in prefer else 0.0)
            if any(a["kind"] == "flash" and abs(a["t"] - in_s) < 0.1 for a in s["accents"]):
                sc -= 1.0                # клип начинался бы со вспышки
            sc -= 0.3 * float(s["static"] and e > 0.5)
            rows.append((sc, k, in_s, acc))
        rows.sort(key=lambda r: -r[0])
        spare.append([(r[1], r[2], r[3]) for r in rows])   # все по оценке — для замены повторов
        rows = rows[:TOP_K]
        if not rows:
            raise _api.ToolError("nothing_to_render", f"нет плана длиннее {L:.2f} с для отрезка")
        cand.append([r[1] for r in rows])
        unary.append([r[0] for r in rows])
        aligned.append({r[1]: (r[2], r[3]) for r in rows})

    def pair_cost(i, j):
        si, sj = found[i], found[j]
        c = 0.0
        if i == j:
            c += 5.0
        if si["file_id"] == sj["file_id"] and abs(si["t0"] - sj["t0"]) < 20.0:
            c += 0.6                     # соседние планы одной сцены подряд
        if si["scale"] == sj["scale"] and si["scale"] != "none":
            c += 0.15
        return c

    n = len(segs)
    score = [np.array(unary[0])]
    back = []
    for i in range(1, n):
        prev = score[-1]
        cur = np.zeros(len(cand[i]))
        bk = np.zeros(len(cand[i]), int)
        for jj, j in enumerate(cand[i]):
            tot = [prev[ii] - pair_cost(cand[i - 1][ii], j) for ii in range(len(cand[i - 1]))]
            bi = int(np.argmax(tot))
            cur[jj], bk[jj] = tot[bi] + unary[i][jj], bi
        score.append(cur)
        back.append(bk)
    pick = [int(np.argmax(score[-1]))]
    for i in range(n - 1, 0, -1):
        pick.append(int(back[i - 1][pick[-1]]))
    pick.reverse()
    chosen = [cand[i][pick[i]] for i in range(n)]
    # Повторы: позднее вхождение — на следующий по оценке неиспользованный.
    used = set()
    for i in range(n):
        if chosen[i] in used:
            for k, in_s, acc in spare[i]:
                if k not in used and (i == 0 or k != chosen[i - 1]):
                    chosen[i] = k
                    aligned[i][k] = (in_s, acc)
                    break
        used.add(chosen[i])
    # Проект.
    mp = _api.montage_project
    p = mp.Project()
    p.tracks[2].role = "music"
    first = found[chosen[0]]
    probe0 = _api.media_probe.probe_media(first["file"]).get("clip") or {}
    p.settings.width = int(width or probe0.get("width") or 1920)
    p.settings.height = int(height or probe0.get("height") or 1080)
    p.settings.fps = fps
    ops, report = [], []
    effects = list(plan.get("effects") or [])
    if fx:
        if fx not in FX_PRESETS:
            raise _api.ToolError("usage", f"--fx: {', '.join(FX_PRESETS)}")
        effects += FX_PRESETS[fx]
    for i, ((a, b), k) in enumerate(zip(segs, chosen)):
        s = found[k]
        L = (b - a) / fps
        in_s, acc = aligned[i][k]
        ops.append({"op": "add", "shot": s["id"], "in_offset": round(in_s - s["t0"], 6),
                    "length": round(L, 6)})
        for e in effects:
            ops.append({"op": "effect", "clip": "last", "effect": dict(e)})
        sec = _section_at(m, t0 + (a + b) / 2 / fps)
        report.append({"segment": i + 1, "start": round(a / fps, 6), "end": round(b / fps, 6),
                       "shot": s["id"], "file": s["file"], "in_s": round(in_s, 3),
                       "accent_on_hit": round(acc, 3), "motion": s["motion"], "scale": s["scale"],
                       "section": f"{sec['label']} {sec.get('group', '')}".strip()})
    song_probe = _api.media_probe.probe_media(song).get("clip") or {}
    audio = mp.Clip(src=_api.os.path.abspath(song), in_s=t0, out_s=t1, track=2, start=0.0,
                    has_video=False, audio_path=_api.os.path.abspath(song),
                    audio_stream=int(song_probe.get("audio_stream", -1)),
                    src_duration=float(song_probe.get("src_duration") or 0.0))
    p.append(audio)
    q, _done = _api.apply_ops(p, ops, db)
    # Маркеры песни — во времени проекта, места резов — на кадрах проекта.
    conv = _api.clip_mapper([audio])
    marks = _api.map_markers(m, _api.MUSIC_WRITE_KINDS, conv)
    for mk in marks:
        if mk["kind"] == "slot":
            mk["t"] = round(_api.snap_frame(mk["t"], fps)[0], 6)
    _api.merge_markers(q, marks, _api.MUSIC_WRITE_KINDS, 0.0, float("inf"))
    _api.montage_project.save_project(q, project_path)
    problems = mp.validate(q.to_dict(), strict=True, check_files=True)
    return {"project": _api.os.path.abspath(str(project_path)), "song": _api.os.path.abspath(song),
            "window": [round(t0, 3), round(t1, 3)], "fps": fps, "segments": report,
            "duration": round(q.duration(), 6), "candidates": len(found),
            "tempo": m["tempo"], "problems": problems}
