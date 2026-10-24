# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Точечные правки проекта для агента: edit <проект> --ops ops.json.
Public namespace: montage_tool.

Операции идут по порядку через методы Project (основная дорожка остаётся
магнитной, свободные — без наложений); любая ошибка — ToolError с номером
операции, и проект не меняется (всё или ничего). Время — секунды или
ссылка на маркер проекта «вид#N» (N — номер среди маркеров вида по
времени, с 1), «вид:подпись#N» (подпись — слово метки: section:chorus#2,
section:A#1), «.end» — конец отрезка, «+0.25»/«-0.1» — сдвиг; итог
прилипает к сетке кадров проекта. Клип — id, «main#N» (N-й клип основной
дорожки), «track2#N» или «last» (последний добавленный в этом пакете)."""
import re

import montage_tool as _api

OPS = ("add", "move", "trim", "split", "swap", "delete", "set", "text", "marker", "effect")
# вид[:подпись]#номер[.end][±сдвиг] — ветки без пересечений (CodeQL).
_REF_RX = re.compile(r"([a-z]+)(?::([A-Za-z0-9_\-]+))?#([0-9]+)(\.end)?([+-][0-9]+(?:\.[0-9]+)?)?")
_CLIP_REF_RX = re.compile(r"(main|track([0-9]+))#([0-9]+)")
# Поля клипа, которые задаёт set (дорожка и место — move, длина — trim).
_SETTABLE = ("volume", "muted", "speed", "fit", "pos_x", "pos_y", "scale", "opacity",
             "transition", "transition_s", "fade_in", "fade_out", "reverse", "freeze_at",
             "in_s", "out_s", "audio_path", "audio_stream", "has_video",
             "keyframes", "effects", "speed_curve", "curve_audio")


class _OpError(Exception):
    pass


def resolve_time(p, value, fps, snap=True):
    """Секунды проекта для числа или ссылки на маркер (см. модуль)."""
    if isinstance(value, bool):
        raise _OpError("время — число или ссылка на маркер")
    if isinstance(value, (int, float)):
        t = float(value)
    elif isinstance(value, str):
        m = _REF_RX.fullmatch(value.strip())
        if not m:
            try:
                t = float(value)
            except ValueError:
                raise _OpError(f"не время и не ссылка на маркер: {value!r}") from None
        else:
            kind, label, num, end, shift = m.groups()
            if kind not in _api.montage_project.MARKER_KINDS:
                raise _OpError(f"нет вида маркеров {kind}")
            ms = [x for x in p.markers if x.kind == kind]
            if label:
                ms = [x for x in ms if label.lower() in x.label.lower().split()]
            ms.sort(key=lambda x: x.t)
            k = int(num)
            if not 1 <= k <= len(ms):
                raise _OpError(f"{value}: маркеров {kind}{':' + label if label else ''} — {len(ms)}")
            mk = ms[k - 1]
            if end:
                if mk.end is None:
                    raise _OpError(f"{value}: у маркера нет конца")
                t = mk.end
            else:
                t = mk.t
            t += float(shift or 0.0)
    else:
        raise _OpError("время — число или ссылка на маркер")
    if t < 0:
        raise _OpError(f"отрицательное время {value!r}")
    if snap and fps > 0:
        t = _api.snap_frame(t, fps)[0]
    return t


def _clip(p, ref, last):
    if ref == "last":
        if last is None:
            raise _OpError("last: в пакете ещё не добавлено клипов")
        ref = last
    if isinstance(ref, str):
        m = _CLIP_REF_RX.fullmatch(ref)
        if m:
            ti = p.main_track if m.group(1) == "main" else int(m.group(2))
            if not 0 <= ti < len(p.tracks):
                raise _OpError(f"нет дорожки {ti}")
            clips = p.clips_on(ti)
            k = int(m.group(3))
            if not 1 <= k <= len(clips):
                raise _OpError(f"{ref}: на дорожке {len(clips)} клипов")
            return clips[k - 1]
    c = p.clip(str(ref))
    if c is None:
        raise _OpError(f"нет клипа {ref!r}")
    return c


_probe_cache = {}


def _probe_clip(path):
    path = _api.os.path.abspath(str(path))
    if path not in _probe_cache:
        try:
            info = _api.media_probe.probe_media(path)
        except _api.media_probe.ProbeError as e:
            raise _OpError(f"{path}: {e}") from e
        _probe_cache[path] = dict(info.get("clip") or {})
    return dict(_probe_cache[path])


def _shot(db, sid):
    con = _api.connect(db)
    try:
        r = con.execute("SELECT s.*, f.path FROM shots s JOIN files f ON f.id=s.file_id WHERE s.id=?",
                        (int(sid),)).fetchone()
    finally:
        con.close()
    if r is None:
        raise _OpError(f"нет плана {sid} в каталоге")
    return r


def _op_add(p, op, fps, db):
    mp = _api.montage_project
    track = int(op.get("track", p.main_track))
    if not 0 <= track < len(p.tracks):
        raise _OpError(f"нет дорожки {track}")
    if "shot" in op:
        s = _shot(op.get("db") or db, op["shot"])
        src, base_in, base_out = s["path"], float(s["t0"]), float(s["t1"])
        muted = True                     # AMV: звук — песня, у плана звук выключен
    elif "src" in op:
        src = str(op["src"])
        base_in = float(op.get("in", 0.0))
        base_out = float(op["out"]) if "out" in op else None
        muted = False
    else:
        raise _OpError("add: нужен shot (id плана каталога) или src")
    fields = _probe_clip(src)
    if not fields:
        raise _OpError(f"{src}: не медиа")
    speed = float(op.get("speed", 1.0))
    a = base_in + float(op.get("in_offset", 0.0))
    if "length" in op:
        b = a + float(op["length"]) * speed
    elif base_out is not None:
        b = base_out
    else:
        raise _OpError("add: нужен out или length")
    dur = float(fields.get("src_duration") or 0.0)
    if dur > 0:
        b = min(b, dur)
    if b - a < mp.MIN_CLIP_S * speed:
        raise _OpError("add: клип короче минимума (in_offset/length за пределами плана?)")
    want = "video" if fields.get("has_video", True) else "audio"
    if p.tracks[track].kind != want:
        raise _OpError(f"add: {want}-клип на дорожке {p.tracks[track].kind}")
    fields.update(in_s=a, out_s=b, track=track, speed=speed)
    if muted:
        fields["muted"] = True
    clip = mp.Clip(**{k: v for k, v in fields.items() if k in mp.Clip.__dataclass_fields__})
    if "at" in op and track == p.main_track:
        at = resolve_time(p, op["at"], fps)
        clip.start = 0.0
        new = p.paste([clip], at)
        clip = new[0]
    else:
        if "at" in op:
            clip.start = resolve_time(p, op["at"], fps)
        p.append(clip)
    if "until" in op:                    # конец клипа — на время проекта (маркер)
        until = resolve_time(p, op["until"], fps)
        if until <= clip.start + mp.MIN_CLIP_S:
            raise _OpError(f"until {op['until']!r} ({until:.3f} с) не позже начала клипа "
                           f"({clip.start:.3f} с)")
        p.trim(clip.id, "right", until)
    if op.get("fields"):
        _set_fields(p, clip, op["fields"])
    return clip


def add_clip_effect(p, c, effect):
    """Эффект клипу (effect — словарь эффекта v3): чистка как при загрузке;
    отброшенный ключ или значение за пределами — ошибка с подсказкой."""
    clean = _api.montage_project.sanitize_effect(effect)
    if clean is None:
        raise _OpError(f"effect.type — одно из {', '.join(_api.montage_project.EFFECT_TYPES)}")
    lost = sorted(k for k in effect if k not in clean)
    changed = sorted(k for k in clean if k in effect and clean[k] != effect[k])
    if lost or changed:
        raise _OpError(f"effect: неизвестные или неверные поля {lost + changed} "
                       f"(пределы — schema: effect.limits)")
    c.effects = list(c.effects) + [clean]


def _set_fields(p, c, fields):
    if not isinstance(fields, dict):
        raise _OpError("fields — объект")
    bad = [k for k in fields if k not in _SETTABLE]
    if bad:
        raise _OpError(f"нельзя задать: {', '.join(bad)} (можно: {', '.join(_SETTABLE)})")
    for k, v in fields.items():
        if k == "speed":
            if not p.set_speed(c.id, v):
                raise _OpError("speed: не число")
            continue
        setattr(c, k, v)
    try:
        c.__post_init__()                # типы и пределы — как при загрузке
    except (TypeError, ValueError) as e:
        raise _OpError(f"fields: {e}") from e
    p._settle(c)


def _apply(p, op, fps, db, state):
    kind = op.get("op")
    if kind not in OPS:
        raise _OpError(f"неизвестная операция {kind!r} (есть {', '.join(OPS)})")
    out = {"op": kind}
    if kind == "add":
        c = _op_add(p, op, fps, db)
        state["last"] = c.id
        out["clip"] = c.id
    elif kind == "move":
        c = _clip(p, op.get("clip"), state["last"])
        track = int(op.get("track", c.track))
        if not p.move(c.id, track, resolve_time(p, op.get("to", c.start), fps)):
            raise _OpError("move: дорожка не того вида")
        out["clip"] = c.id
    elif kind == "trim":
        c = _clip(p, op.get("clip"), state["last"])
        edge = {"in": "left", "start": "left", "left": "left",
                "out": "right", "end": "right", "right": "right"}.get(op.get("edge"))
        if edge is None:
            raise _OpError("trim: edge — left/right (start/end)")
        p.trim(c.id, edge, resolve_time(p, op.get("to"), fps))
        out["clip"] = c.id
    elif kind == "split":
        c = _clip(p, op.get("clip"), state["last"])
        parts = p.split(c.id, resolve_time(p, op.get("at"), fps))
        if parts is None:
            raise _OpError("split: точка у края клипа или вне его")
        out.update(clip=parts[0].id, right=parts[1].id)
        state["last"] = parts[1].id
    elif kind == "swap":
        a, b = _clip(p, op.get("a"), state["last"]), _clip(p, op.get("b"), state["last"])
        if a.track != b.track:
            raise _OpError("swap: клипы на разных дорожках")
        if a.track == p.main_track:
            a.start, b.start = b.start, a.start
            p.pack()
        else:
            a.start, b.start = b.start, a.start
            p._free_spot(a)
            p._free_spot(b)
        out.update(a=a.id, b=b.id)
    elif kind == "delete":
        c = _clip(p, op.get("clip"), state["last"])
        p.remove(c.id)
        out["clip"] = c.id
    elif kind == "set":
        c = _clip(p, op.get("clip"), state["last"])
        _set_fields(p, c, op.get("fields") or {})
        out["clip"] = c.id
    elif kind == "text":
        mp = _api.montage_project
        if op.get("id") and op.get("delete"):
            n = len(p.texts)
            p.texts = [t for t in p.texts if t.id != op["id"]]
            if len(p.texts) == n:
                raise _OpError(f"нет текста {op['id']}")
            out["text"] = op["id"]
        else:
            raw = {"start": resolve_time(p, op.get("start"), fps),
                   "end": resolve_time(p, op.get("end"), fps), "text": op.get("text"),
                   "style": op.get("style") or {}}
            for k in ("pos_x", "pos_y", "id"):
                if k in op:
                    raw[k] = op[k]
            items = mp.parse_texts([raw])
            if not items:
                raise _OpError("text: нужен text и конец позже начала")
            p.texts = sorted([t for t in p.texts if t.id != items[0].id] + items,
                             key=lambda t: (t.start, t.end))
            out["text"] = items[0].id
    elif kind == "marker":
        mp = _api.montage_project
        new = mp.parse_markers([{"t": resolve_time(p, op.get("t"), fps),
                                 "kind": op.get("kind", "custom"), "label": op.get("label", ""),
                                 "end": (resolve_time(p, op["end"], fps) if "end" in op else None)}])
        if not new:
            raise _OpError("marker: неверный вид или время")
        p.markers = sorted(p.markers + new, key=lambda m: (m.t, m.kind))
    elif kind == "effect":
        c = _clip(p, op.get("clip"), state["last"])
        add_clip_effect(p, c, op.get("effect") or {})
        out["clip"] = c.id
    return out


def _snapshot(p):
    return {c.id: (c.track, round(c.start, 6), round(c.end, 6), round(c.in_s, 6),
                   round(c.out_s, 6)) for c in p.clips}


def apply_ops(p, ops, db=None):
    """Применяет операции к копии проекта: (новый проект, отчёт по
    операциям). Ошибка — ToolError('bad_op') с номером операции."""
    if not isinstance(ops, list):
        raise _api.ToolError("bad_op", "ops — JSON-список операций")
    q = p.copy()
    fps = q.output_format()[2]
    state = {"last": None}
    done = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise _api.ToolError("bad_op", f"ops[{i}]: операция — объект")
        try:
            done.append(dict(_apply(q, op, fps, db, state), index=i))
        except _OpError as e:
            raise _api.ToolError("bad_op", f"ops[{i}] ({op.get('op')}): {e}") from e
    return q, done


def edit_project(path, ops, db=None, strict=True, dry_run=False):
    """edit: операции → проект (атомарно save_project) и отчёт: операции,
    добавленные/удалённые/сдвинутые клипы, проблемы строгой проверки."""
    p, _problems = _api.load_project_file(path, strict=strict)
    before = _snapshot(p)
    q, done = apply_ops(p, ops, db)
    after = _snapshot(q)
    changed = [{"clip": cid, "before": list(before[cid]), "after": list(after[cid])}
               for cid in after if cid in before and before[cid] != after[cid]]
    problems = _api.montage_project.validate(q.to_dict(), strict=True, check_files=True)
    if not dry_run:
        _api.montage_project.save_project(q, path)
    return {"project": _api.os.path.abspath(str(path)), "saved": not dry_run, "ops": done,
            "added": [cid for cid in after if cid not in before],
            "removed": [cid for cid in before if cid not in after],
            "changed": changed, "duration": round(q.duration(), 6),
            "clips": len(q.clips), "problems": problems}
