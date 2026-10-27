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
дорожки), «track2#N» или «last» (последний добавленный в этом пакете).

Кроме правок клипов: words — пословный текст по меткам word (typography.py),
lyrics — то же со словами и строками из файла текста песни, voice — реплика
из серии на дорожку голоса (clean — без музыки, HTDemucs), settings — поля
настроек проекта (finish — эффекты всего кадра), card — карточка (фон
cards.py наложением и текст поверх), strobe — мерцание: кусок наложением,
видимый через каждые N кадров. text/words/lyrics/card берут роль стиля
ключом preset («стиль.роль», styles.py)."""
import re

import montage_tool as _api

OPS = ("add", "move", "trim", "split", "swap", "delete", "set", "text", "marker", "effect",
       "words", "lyrics", "voice", "settings", "card", "strobe")
# вид[:подпись]#номер[.end][±сдвиг] — ветки без пересечений (CodeQL).
_REF_RX = re.compile(r"([a-z]+)(?::([A-Za-z0-9_\-]+))?#([0-9]+)(\.end)?([+-][0-9]+(?:\.[0-9]+)?)?")
_CLIP_REF_RX = re.compile(r"(main|track([0-9]+))#([0-9]+)")
# Поля клипа, которые задаёт set (дорожка и место — move, длина — trim).
_SETTABLE = ("volume", "muted", "speed", "fit", "pos_x", "pos_y", "scale", "opacity",
             "transition", "transition_s", "fade_in", "fade_out", "reverse", "freeze_at",
             "in_s", "out_s", "audio_path", "audio_stream", "has_video",
             "keyframes", "effects", "speed_curve", "curve_audio", "interpolate", "upscale",
             "crop", "box", "mask", "stroke", "blend", "matte")
# Поля настроек, которые задаёт settings.
_SETTINGS = ("width", "height", "fps", "fit", "background", "loudness", "duck", "upscale",
             "deband", "finish")


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
    if want == "video" and p.tracks[track].kind == "audio" and fields.get("audio_stream", -1) >= 0:
        fields["has_video"], want = False, "audio"    # звук видеофайла — на звуковую дорожку
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
    # Слои: значение, которое чистка выбросила, — ошибка (иначе поле молча
    # не сработало бы).
    for k in ("crop", "box", "mask", "stroke", "blend", "matte"):
        if k in fields and fields[k] not in ([], {}, "", "normal", None) and not getattr(c, k):
            raise _OpError(f"{k}: неверное значение (schema: notes, enums)")
    if c.track == p.main_track and (c.mask or c.stroke or c.blend or c.matte):
        raise _OpError("mask, stroke, blend и matte — только у наложения (верхняя дорожка)")
    p._settle(c)


def _free_video_track(p, a, b, top=False):
    """Видеодорожка наложений, свободная на [a, b) (top — сначала верхние);
    нет такой — новая (она выше всех)."""
    tracks = [ti for ti in p.tracks_of("video") if ti != p.main_track]
    for ti in reversed(tracks) if top else tracks:
        if all(c.end <= a + 1e-6 or c.start >= b - 1e-6 for c in p.clips_on(ti)):
            return ti
    return p.add_track("video")


def _span(p, op, fps, default=None):
    """(начало, длина) операции: at и length или until."""
    at = resolve_time(p, op.get("at", 0.0), fps)
    if "until" in op:
        length = resolve_time(p, op["until"], fps) - at
    else:
        try:
            length = float(op.get("length", default))
        except (TypeError, ValueError):
            raise _OpError("нужна length (с) или until") from None
    if length < _api.montage_project.MIN_CLIP_S:
        raise _OpError("длина короче минимума клипа")
    return at, length


def _op_card(p, op, fps, db, state):
    """Карточка: фон (cards.card_background, PNG рядом с проектом) наложением
    на свободной верхней видеодорожке [at, at + length) и текст поверх всего;
    preset — вид карточки стиля: фон, роль текста, длина, сбой, вспышка."""
    spec = {}
    if "preset" in op:
        try:
            spec = _api.style_role(op["preset"], "cards")
        except (ValueError, _api.ToolError) as e:
            raise _OpError(f"card: {getattr(e, 'message', e)}") from e
    folder = state.get("cards")
    if not folder:
        raise _OpError("card: фон пишется рядом с проектом — edit по файлу проекта")
    at, length = _span(p, op, fps, spec.get("length", 1.0))
    w, h, _fps = p.output_format()
    if not isinstance(op.get("background") or {}, dict):
        raise _OpError("card: background — объект")
    try:
        png = _api.card_background(dict(spec.get("background") or {}, **(op.get("background") or {})),
                                   w, h, folder)
    except (ValueError, TypeError, OSError) as e:
        raise _OpError(f"card: {e}") from e
    track = int(op["track"]) if "track" in op else _free_video_track(p, at, at + length, top=True)
    c = _op_add(p, {"op": "add", "src": png, "in": 0.0, "length": length, "track": track,
                    "at": at}, fps, db)
    try:
        glitch = float(op.get("glitch", spec.get("glitch", 0.0)) or 0.0)
        flash = float(op.get("flash", spec.get("flash", 0.0)) or 0.0)
    except (TypeError, ValueError):
        raise _OpError("card: glitch и flash — числа") from None
    if glitch > 0:
        add_clip_effect(p, c, {"type": "glitch", "amount": glitch, "decay": 0.08})
        add_clip_effect(p, c, {"type": "glitch", "on": [round(c.end - 3.0 / fps, 6)],
                               "amount": glitch, "decay": 0.06})
    if flash > 0:
        add_clip_effect(p, c, {"type": "flash", "amount": flash, "decay": 0.12})
    out = {"clip": c.id, "background": png}
    if op.get("text"):
        t_op = {"op": "text", "start": c.start, "end": c.end, "text": op["text"],
                "style": op.get("style") or {}}
        for k in ("pos_x", "pos_y", "layer", "id"):
            if k in op:
                t_op[k] = op[k]
        ref = op.get("text_preset") or (f"{spec['_style']}.{spec['text']}" if spec.get("text")
                                        else None)
        if ref:
            t_op["preset"] = ref
        out["text"] = _apply(p, t_op, fps, db, state)["text"]
    return out


def _op_strobe(p, op, fps, db):
    """Мерцание: кусок (shot или src, как у add) наложением на [at, at + length),
    видим через каждые frames кадров — ключевые кадры opacity с hold."""
    at, length = _span(p, op, fps)
    k = op.get("frames", 2)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 24:
        raise _OpError("strobe: frames — целое от 1 до 24 кадров")
    track = int(op["track"]) if "track" in op else _free_video_track(p, at, at + length)
    add = {"op": "add", "track": track, "at": at, "length": length}
    for key in ("shot", "src", "in", "in_offset", "db"):
        if key in op:
            add[key] = op[key]
    c = _op_add(p, add, fps, db)
    on, pts = not op.get("start_hidden"), []
    for f in range(0, max(1, int(round(c.length * fps))), k):
        # Точка — за полкадра до кадра f: время кадра у самой границы
        # округлением ушло бы в прошлый отрезок.
        pts.append({"t": round(max(0.0, (f - 0.5) / fps), 6), "v": 1.0 if on else 0.0,
                    "ease": "hold"})
        on = not on
    _set_fields(p, c, dict({"keyframes": {"opacity": pts}}, **(op.get("fields") or {})))
    return c


def _preset_sample(p, op, fps):
    """Текст операции — по нему роль выбирает шрифт из списка: у text — сама
    строка, у lyrics — строки файла (lines), у words — метки word отрезка."""
    kind = op.get("op")
    if kind == "text":
        return str(op.get("text") or "")
    try:
        if kind == "lyrics":
            lines = _api.read_lyrics(_api.os.path.abspath(str(op.get("file") or "")))
            want = {int(n) for n in op.get("lines") or []}
            return " ".join(show for n, line in enumerate(lines, 1) if not want or n in want
                            for show, _k in line)
        t0 = resolve_time(p, op.get("from", 0.0), fps, snap=False)
        t1 = resolve_time(p, op["to"], fps, snap=False) if "to" in op else float("inf")
        return " ".join(w[2] for w in _api.project_words(p, t0, t1 + 1e-6))
    except (OSError, ValueError, TypeError, _OpError):
        return ""


def _apply(p, op, fps, db, state):
    kind = op.get("op")
    if kind not in OPS:
        raise _OpError(f"неизвестная операция {kind!r} (есть {', '.join(OPS)})")
    if kind in ("text", "words", "lyrics") and "preset" in op:
        try:
            op = _api.apply_preset(op, _preset_sample(p, op, fps))
        except (ValueError, _api.ToolError) as e:
            raise _OpError(f"{kind}: {getattr(e, 'message', e)}") from e
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
            for k in ("pos_x", "pos_y", "id", "layer"):
                if k in op:
                    raw[k] = op[k]
            if "width" in op and isinstance(raw["text"], str):
                # Блок width (доля кадра; у роли стиля) — кегль под него и
                # под край кадра от точки текста.
                import subtitle_ass
                res_x, res_y = _api.text_canvas(p)
                full = dict(subtitle_ass.DEFAULT_SUBTITLE_STYLE, **raw["style"])
                px = 0.5 if raw.get("pos_x") is None else float(raw["pos_x"])
                py = 0.5 if raw.get("pos_y") is None else float(raw["pos_y"])
                size = _api.fit_size(raw["text"], full, float(op["width"]), px, py, res_x, res_y)
                if size < float(full["size"]):
                    raw["style"] = dict(raw["style"], size=size)
            items = mp.parse_texts([raw])
            if not items:
                raise _OpError("text: нужен text и конец позже начала")
            lost = sorted(k for k in raw["style"] if k not in items[0].style)
            if lost:
                raise _OpError(f"text: неверные ключи или значения стиля {lost} "
                               f"(schema: text_style, text_style_kinetic)")
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
    elif kind == "words":
        try:
            out["texts"] = _api.add_words(p, op, lambda v: resolve_time(p, v, fps, snap=False))
        except ValueError as e:
            raise _OpError(f"words: {e}") from e
    elif kind == "lyrics":
        try:
            out.update(_api.add_lyrics(p, op, lambda v: resolve_time(p, v, fps, snap=False)))
        except (OSError, ValueError) as e:
            raise _OpError(f"lyrics: {e}") from e
    elif kind == "voice":
        c = _op_voice(p, op, fps, db)
        state["last"] = c.id
        out["clip"] = c.id
    elif kind == "settings":
        _op_settings(p, op.get("fields") or {})
    elif kind == "card":
        out.update(_op_card(p, op, fps, db, state))
        state["last"] = out["clip"]
    elif kind == "strobe":
        c = _op_strobe(p, op, fps, db)
        state["last"] = c.id
        out["clip"] = c.id
    return out


def _op_settings(p, fields):
    mp = _api.montage_project
    if not isinstance(fields, dict):
        raise _OpError("settings: fields — объект")
    bad = [k for k in fields if k not in _SETTINGS]
    if bad:
        raise _OpError(f"settings: нельзя задать {', '.join(bad)} (можно: {', '.join(_SETTINGS)})")
    raw = dict(_api.dataclasses.asdict(p.settings), **fields)
    problems = [x for x in mp.validate({"version": mp.PROJECT_VERSION, "settings": raw},
                                       strict=True, check_files=False)
                if x["path"].startswith("settings")]
    if problems:
        raise _OpError("settings: " + "; ".join(f"{x['path']}: {x['message']}" for x in problems))
    p.settings = mp.parse_settings(raw)


def _voice_track(p):
    """Звуковая дорожка с ролью voice (нет — новая); приглушение музыки — 0.6,
    если не задано."""
    for i, t in enumerate(p.tracks):
        if t.kind == "audio" and t.role == "voice":
            ti = i
            break
    else:
        ti = p.add_track("audio")
        p.tracks[ti].role = "voice"
    if p.settings.duck <= 0:
        p.settings.duck = 0.6
    return ti


def _op_voice(p, op, fps, db):
    """Реплика: кусок [in, out] файла на дорожку голоса у времени at; clean —
    вокал HTDemucs без музыки (кэш по файлу и куску)."""
    src = _api.os.path.abspath(str(op.get("src") or ""))
    if not _api.os.path.isfile(src):
        raise _OpError(f"voice: нет файла {src}")
    try:
        a, b = float(op["in"]), float(op["out"])
    except (KeyError, TypeError, ValueError):
        raise _OpError("voice: нужны in и out (секунды файла)") from None
    if b - a < _api.montage_project.MIN_CLIP_S:
        raise _OpError("voice: out не позже in")
    if op.get("clean"):
        try:
            src = _api.clean_voice(src, a, b, op.get("ml_python", ""))
        except _api.ToolError as e:
            raise _OpError(f"voice: {e.message}") from e
        a, b = 0.0, b - a
    add = {"op": "add", "src": src, "in": a, "out": b, "track": _voice_track(p),
           "at": op.get("at", 0.0)}
    c = _op_add(p, add, fps, db)
    if "volume" in op:
        _set_fields(p, c, {"volume": op["volume"]})
    return c


def _snapshot(p):
    return {c.id: (c.track, round(c.start, 6), round(c.end, 6), round(c.in_s, 6),
                   round(c.out_s, 6)) for c in p.clips}


def apply_ops(p, ops, db=None, cards=None):
    """Применяет операции к копии проекта: (новый проект, отчёт по
    операциям). Ошибка — ToolError('bad_op') с номером операции. cards —
    папка фонов карточек (op card)."""
    if not isinstance(ops, list):
        raise _api.ToolError("bad_op", "ops — JSON-список операций")
    q = p.copy()
    fps = q.output_format()[2]
    state = {"last": None, "cards": cards}
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
    q, done = apply_ops(p, ops, db, _api.cards_dir(path))
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
