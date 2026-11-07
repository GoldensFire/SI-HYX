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
cards.py наложением и текст поверх; countdown — обратный отсчёт), strobe —
мерцание: кусок наложением, видимый через каждые N кадров, sequence — текст
по одному на рез или долю (досье без голоса), cutout — персонаж клипа
основной дорожки поверх текста слоя 0 (matte), panels — сплит-экран и
окна-вставки вразброс (scatter), snap_cuts — резы к началам слов песни
(прокат реза, остальное на месте), columns — слово по слогам в колонках
следующего плана. text/words/lyrics/card/sequence/columns берут роль стиля
ключом preset («стиль.роль», styles.py); style.color "auto" — цвет под
план (text_color.py)."""
import math
import random
import re

import montage_tool as _api

OPS = ("add", "move", "trim", "split", "swap", "delete", "set", "text", "marker", "effect",
       "words", "lyrics", "voice", "settings", "card", "strobe", "sequence", "cutout", "panels",
       "snap_cuts", "columns")
# вид[:подпись]#номер[.end][±сдвиг] — ветки без пересечений (CodeQL).
_REF_RX = re.compile(r"([a-z]+)(?::([A-Za-z0-9_\-]+))?#([0-9]+)(\.end)?([+-][0-9]+(?:\.[0-9]+)?)?")
_CLIP_REF_RX = re.compile(r"(main|track([0-9]+))#([0-9]+)")
# Поля клипа, которые задаёт set (дорожка и место — move, длина — trim).
_SETTABLE = ("volume", "muted", "speed", "fit", "pos_x", "pos_y", "scale", "opacity",
             "transition", "transition_s", "fade_in", "fade_out", "reverse", "freeze_at",
             "in_s", "out_s", "audio_path", "audio_stream", "has_video",
             "keyframes", "effects", "speed_curve", "curve_audio", "interpolate", "upscale",
             "crop", "box", "mask", "stroke", "shadow", "blend", "matte")
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


def _trim_until(p, clip, until, fps):
    """Подрезать клип справа до until с концом ровно на кадре проекта.

    Project.trim округляет правый край к кадрам ИСХОДНИКА: until (время
    проекта) уже на сетке проекта, а snap_to_frame в trim переводил его на
    сетку исходника, и длина клипа в кадрах проекта оставалась дробной
    (41.8 кадра вместо 42). Если подрезка не упёрлась в конец исходника или
    в соседа, ставим out_s по сетке проекта."""
    mp = _api.montage_project
    p.trim(clip.id, "right", until)
    if clip.reverse or clip.speed_curve:
        return                        # край — не линейное время out_s
    speed = clip.play_speed
    want = clip.in_s + (until - clip.start) * speed
    still = clip.is_image or clip.frozen
    limit = clip.src_duration if (clip.src_duration > 0 and not still) else float("inf")
    if want > limit + 1e-6:
        return                        # until дальше конца исходника
    if clip.track != p.main_track:
        nxt = min((o.start for o in p.clips_on(clip.track)
                   if o is not clip and o.start >= clip.start + 1e-6),
                  default=float("inf"))
        if clip.start + (want - clip.in_s) / speed > nxt + 1e-6:
            return                    # until заходит на соседа
    if want >= clip.in_s + mp.MIN_CLIP_S * speed:
        clip.out_s = want
        p._settle(clip)


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
        _trim_until(p, clip, until, fps)
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
    for k in ("crop", "box", "mask", "stroke", "shadow", "blend", "matte"):
        if k in fields and fields[k] not in ([], {}, "", "normal", None) and not getattr(c, k):
            raise _OpError(f"{k}: неверное значение (schema: notes, enums)")
    if c.track == p.main_track and (c.mask or c.stroke or c.shadow or c.blend or c.matte):
        raise _OpError("mask, stroke, shadow, blend и matte — только у наложения (верхняя "
                       "дорожка)")
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
    count = op.get("countdown", spec.get("countdown_from", 0)) or 0
    if count:
        # Обратный отсчёт «00:0N» … «00:00» поровну на длину карточки.
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 59:
            raise _OpError("card: countdown — целое от 1 до 59")
        ref = op.get("countdown_preset") or (f"{spec['_style']}.{spec['countdown']}"
                                             if spec.get("countdown") else None)
        step = (c.end - c.start) / (count + 1)
        out["countdown"] = []
        for i in range(count + 1):
            t_op = {"op": "text", "start": c.start + i * step, "end": c.start + (i + 1) * step,
                    "text": f"00:{count - i:02d}"}
            if ref:
                t_op["preset"] = ref
            out["countdown"].append(_apply(p, t_op, fps, db, state)["text"])
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


def _seq_points(p, op, fps, t0, t1):
    """Моменты смены текста sequence на [t0, t1): on — cuts (начала клипов
    основной дорожки), вид маркера или список времён; t0 — всегда первый."""
    on = op.get("on", "cuts")
    if on == "cuts":
        times = [c.start for c in p.clips_on(p.main_track)]
    elif isinstance(on, str) and on in _api.montage_project.MARKER_KINDS:
        times = [m.t for m in p.markers if m.kind == on]
    elif isinstance(on, list):
        times = [resolve_time(p, v, fps) for v in on]
    else:
        raise _OpError("sequence: on — cuts, вид маркера или список времён")
    pts = sorted({round(t0, 6)} | {round(_api.snap_frame(t, fps)[0], 6) for t in times
                                   if t0 + 1e-6 < t < t1 - 1e-6})
    return pts


def _op_sequence(p, op, fps, db, state):
    """Текст по одному на рез (досье «SUBJECT: … CLASSIFICATION: …» без
    голоса, слова под доли): items по очереди на моменты _seq_points,
    каждый держится span моментов (подпись с «:» — label_span). Роль —
    preset (подписи и всё без value_preset) или value_preset (не
    кончается на «:»); у элемента-объекта — свои text, preset, style, span,
    pos_x, pos_y, layer."""
    items = op.get("items")
    if not isinstance(items, list) or not items:
        raise _OpError("sequence: items — непустой список строк или объектов {text, …}")
    t0 = resolve_time(p, op.get("from", 0.0), fps)
    t1 = resolve_time(p, op["to"], fps) if "to" in op else p.duration()
    if t1 <= t0:
        raise _OpError("sequence: to не позже from")
    pts = _seq_points(p, op, fps, t0, t1)
    try:
        label_span = int(op.get("label_span", 1))
    except (TypeError, ValueError):
        raise _OpError("sequence: label_span — целое") from None
    rows, k = [], 0
    for i, it in enumerate(items):
        it = {"text": it} if isinstance(it, str) else it
        if not isinstance(it, dict) or not str(it.get("text") or "").strip():
            raise _OpError(f"sequence: items[{i}] — строка или объект с text")
        text = str(it["text"])
        label = text.rstrip().endswith(":")
        span = it.get("span", label_span if label else 1)
        if isinstance(span, bool) or not isinstance(span, int) or span < 1:
            raise _OpError(f"sequence: items[{i}].span — целое ≥ 1")
        if k >= len(pts):
            raise _OpError(f"sequence: элементов больше, чем моментов на отрезке ({len(pts)}): "
                           f"уменьшите span, добавьте резы или возьмите on: beat")
        end = pts[k + span] if k + span < len(pts) else t1
        rows.append((pts[k], end, text, it, label))
        k += span
    out = []
    for a, b, text, it, label in rows:
        t_op = {"op": "text", "start": a, "end": b, "text": text}
        role = it.get("preset") or (op.get("preset") if label or not op.get("value_preset")
                                    else op.get("value_preset"))
        if role:
            t_op["preset"] = role
        style = dict(op.get("style") or {}, **(it.get("style") or {}))
        if style:
            t_op["style"] = style
        for key in ("pos_x", "pos_y", "layer", "width"):
            if key in it:
                t_op[key] = it[key]
            elif key in op:
                t_op[key] = op[key]
        out.append(_apply(p, t_op, fps, db, state)["text"])
    return {"texts": out, "points": len(pts), "used": k}


def _op_snap_cuts(p, op, fps):
    """Резы основной дорожки на [from, to) — к ближайшему маркеру вида on
    (word — начало слова песни) не дальше max_shift с: прокат реза — конец
    левого клипа и начало правого сдвигаются вместе, прочие клипы на месте
    (сдвиг, который их задел бы, откатывается). Резы с переходом — как есть."""
    mp = _api.montage_project
    kind = op.get("on", "word")
    if kind not in mp.MARKER_KINDS:
        raise _OpError(f"snap_cuts: on — вид маркера ({', '.join(mp.MARKER_KINDS)})")
    t0 = resolve_time(p, op.get("from", 0.0), fps)
    t1 = resolve_time(p, op["to"], fps) if "to" in op else p.duration()
    try:
        max_shift = float(op.get("max_shift", 0.15))
    except (TypeError, ValueError):
        raise _OpError("snap_cuts: max_shift — число секунд") from None
    marks = sorted(m.t for m in p.markers if m.kind == kind)
    if not marks:
        raise _OpError(f"snap_cuts: нет маркеров {kind} (слова — analyze --kinds word --vocals "
                       f"--write)")
    moved, used = [], set()
    clips = p.clips_on(p.main_track)
    for i in range(1, len(clips)):
        a, b = p.clips_on(p.main_track)[i - 1:i + 1]
        cut = b.start
        if not t0 <= cut < t1 or b.transition or abs(a.end - cut) > 1e-6:
            continue
        if any(c.reverse or c.speed_curve or c.is_image or c.freeze_at >= 0 for c in (a, b)):
            continue
        near = min(marks, key=lambda t: abs(t - cut))
        target = _api.snap_frame(near, fps)[0]
        d = target - cut
        if abs(d) < 0.5 / fps or abs(d) > max_shift or near in used:
            continue
        if a.end - a.start + d < mp.MIN_CLIP_S or b.end - b.start - d < mp.MIN_CLIP_S:
            continue
        keep = [(c.id, c.in_s, c.out_s) for c in (a, b)]
        b_end = b.end
        p.trim(a.id, "right", target)
        p.trim(b.id, "left", b.start + d)
        if abs(a.end - target) > 0.5 / fps or abs(b.end - b_end) > 0.25 / fps:
            for cid, i_s, o_s in keep:      # не хватило исходника — как было
                c = p.clip(cid)
                c.in_s, c.out_s = i_s, o_s
            p.pack()
            continue
        used.add(near)
        moved.append({"cut": round(cut, 4), "to": round(target, 4)})
    return {"snapped": moved}


# Отношение кадра у вырезки: геометрия основной дорожки (ключевые кадры
# места и масштаба, зум-удар, тряска), которую наложение не повторит.
_GEO_KEYS = ("pos_x", "pos_y", "scale", "rotation")


def _op_cutout(p, op, fps, db):
    """Персонаж поверх текста слоя 0: кусок клипа основной дорожки (clip —
    его ссылка, at/length или until — часть клипа) наложением на свободной
    верхней дорожке с matte (anime | rmbg), тот же кадр и вписывание."""
    c = _clip(p, op.get("clip"), None) if "clip" in op else None
    if c is None:
        at = resolve_time(p, op.get("at", 0.0), fps)
        c = p.clip_at(p.main_track, at + 0.5 / fps)
        if c is None:
            raise _OpError("cutout: на основной дорожке в at нет клипа")
    if c.track != p.main_track:
        raise _OpError("cutout: clip — клип основной дорожки")
    if c.reverse or c.speed_curve or c.freeze_at >= 0 or c.is_image:
        raise _OpError("cutout: у клипа реверс, кривая скорости, стоп-кадр или картинка — "
                       "вырезка не совпадёт с кадром")
    geo = [k for k in _GEO_KEYS if k in (c.keyframes or {})]
    geo += [e["type"] for e in c.effects or [] if e.get("type") in ("zoom_punch", "push", "shake")]
    if geo:
        raise _OpError(f"cutout: у клипа геометрия {', '.join(geo)} — наложение её не повторит; "
                       f"уберите её с этого клипа")
    a = resolve_time(p, op["at"], fps) if "at" in op else c.start
    if "until" in op:
        b = resolve_time(p, op["until"], fps)
    elif "length" in op:
        b = a + float(op["length"])
    else:
        b = c.end
    a, b = max(a, c.start), min(b, c.end)
    if b - a < _api.montage_project.MIN_CLIP_S:
        raise _OpError("cutout: кусок вне клипа или короче минимума")
    matte = op.get("matte", "anime")
    if matte not in _api.montage_project.MATTE_MODELS:
        raise _OpError(f"cutout: matte — {', '.join(_api.montage_project.MATTE_MODELS)}")
    track = int(op["track"]) if "track" in op else _free_video_track(p, a, b, top=True)
    add = {"op": "add", "src": c.src, "in": c.in_s + (a - c.start) * c.speed,
           "length": b - a, "speed": c.speed, "track": track, "at": a}
    ov = _op_add(p, add, fps, db)
    fields = {"matte": matte, "fit": c.fit or p.settings.fit, "muted": True}
    if c.crop:
        fields["crop"] = list(c.crop)
    if op.get("stroke"):
        fields["stroke"] = op["stroke"]
    _set_fields(p, ov, fields)
    return ov


# Раскладки panels: (ширина, высота) панели и центры — доли кадра.
_PANELS = {"v2": ((0.5, 1.0), [(0.25, 0.5), (0.75, 0.5)]),
           "v3": ((1 / 3, 1.0), [(1 / 6, 0.5), (0.5, 0.5), (5 / 6, 0.5)]),
           "h2": ((1.0, 0.5), [(0.5, 0.25), (0.5, 0.75)]),
           "h3": ((1.0, 1 / 3), [(0.5, 1 / 6), (0.5, 0.5), (0.5, 5 / 6)]),
           "grid4": ((0.5, 0.5), [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]),
           "strips2": ((0.18, 1.0), [(0.3, 0.5), (0.7, 0.5)]),
           "strips3": ((0.18, 1.0), [(0.22, 0.5), (0.5, 0.5), (0.78, 0.5)])}
# scatter — окна-вставки вразброс (стиль rcn): ширина окна по умолчанию,
# окон не больше, поля кадра (доли), кольцо вокруг центра (доля высоты).
SCATTER_SIZE = (0.24, 0.36)
SCATTER_MAX = 12
_SCATTER_MARGIN = (0.03, 0.04)
_SCATTER_RING = 0.32
# quad — четыре окна ровной сеткой 2×2 (стиль rcn): два столбца с просветом
# по центру (там герой основной дорожки), поля по краям; центры окон
# (левое верхнее, правое верхнее, левое нижнее, правое нижнее), ширина окна
# по умолчанию и предел (доли кадра) — замер эталона.
QUAD_CENTERS = [(0.27, 0.30), (0.73, 0.30), (0.27, 0.77), (0.73, 0.77)]
QUAD_SIZE = 0.37
QUAD_SIZE_MAX = 0.44
QUAD_HEIGHT_MAX = 0.46
# Раскладки окон-вставок: без фона, белый вход окна короче.
_WINDOW_LAYOUTS = ("scatter", "quad")
PANEL_LAYOUTS = tuple(_PANELS) + _WINDOW_LAYOUTS


def _scatter_args(op):
    """(min, max) ширины окна, пропорции, seed и avoid операции panels scatter."""
    size = op.get("size", list(SCATTER_SIZE))
    try:
        if isinstance(size, (int, float)) and not isinstance(size, bool):
            lo = hi = float(size)
        else:
            lo, hi = float(size[0]), float(size[1])
        aspect = float(op.get("aspect", 16 / 9))
        seed = int(op.get("seed", 1))
        avoid = op.get("avoid")
        avoid = None if avoid is None else (float(avoid[0]), float(avoid[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        raise _OpError("panels: size — число или [min, max], aspect — число, seed — целое, "
                       "avoid — [x, y]") from None
    if not 0.08 <= lo <= hi <= 0.9 or not 0.2 <= aspect <= 5.0:
        raise _OpError("panels: size — доли ширины 0.08…0.9, aspect — 0.2…5")
    return lo, hi, aspect, seed, avoid


def _scatter(p, op, n):
    """Окна scatter: [(ширина, высота)] и [(cx, cy)] в долях кадра. Жадно:
    каждое окно — в точке сетки, где больше очков: дальше от уже
    поставленных окон (до ~ширины окна — дальше не нужно, окна кучно и
    внахлёст), на кольце вокруг центра кадра (герой в середине виден) и
    дальше от avoid [x, y]; seed — дрожание выбора и размеров."""
    lo, hi, aspect, seed, avoid = _scatter_args(op)
    w, h, _fps = p.output_format()
    ar = w / float(h)
    rng = random.Random(seed)
    mx, my = _SCATTER_MARGIN
    boxes, placed = [], []
    for _i in range(n):
        bw = lo + (hi - lo) * rng.random()
        bh = bw * ar / aspect
        if bh > 0.9:
            bw, bh = bw * 0.9 / bh, 0.9
        xs = [bw / 2 + mx + k * max(0.0, 1 - bw - 2 * mx) / 6 for k in range(7)]
        ys = [bh / 2 + my + k * max(0.0, 1 - bh - 2 * my) / 4 for k in range(5)]
        reach = 0.9 * bw * ar
        best = None
        for x in xs:
            for y in ys:
                d = min((math.hypot((x - px) * ar, y - py) for px, py in placed),
                        default=reach)
                dc = math.hypot((x - 0.5) * ar, y - 0.5)
                ring = 1.0 - min(abs(dc - _SCATTER_RING) / _SCATTER_RING, 1.0)
                away = 0.0
                if avoid is not None:
                    away = min(math.hypot((x - avoid[0]) * ar, y - avoid[1]), 0.8) / 0.8
                score = min(d, reach) / reach + 0.5 * ring + 0.6 * away + 0.15 * rng.random()
                if best is None or score > best[0]:
                    best = (score, x, y)
        placed.append((best[1], best[2]))
        boxes.append((bw, bh))
    return boxes, placed


def _quad(p, op, n):
    """Окна quad: [(ширина, высота)] и [(cx, cy)] в долях кадра — четыре
    окна сеткой 2×2 (QUAD_CENTERS); size — ширина окна, aspect — пропорции
    (16:9), высота не больше QUAD_HEIGHT_MAX — окна не сходятся по вертикали."""
    if n != len(QUAD_CENTERS):
        raise _OpError(f"panels: у quad {len(QUAD_CENTERS)} окна — столько shots/srcs")
    try:
        bw = float(op.get("size", QUAD_SIZE))
        aspect = float(op.get("aspect", 16 / 9))
    except (TypeError, ValueError):
        raise _OpError("panels: у quad size и aspect — числа") from None
    if not 0.15 <= bw <= QUAD_SIZE_MAX or not 0.2 <= aspect <= 5.0:
        raise _OpError(f"panels: у quad size — 0.15…{QUAD_SIZE_MAX}, aspect — 0.2…5")
    w, h, _fps = p.output_format()
    bh = bw * (w / float(h)) / aspect
    if bh > QUAD_HEIGHT_MAX:
        bw, bh = bw * QUAD_HEIGHT_MAX / bh, QUAD_HEIGHT_MAX
    return [(bw, bh)] * n, list(QUAD_CENTERS)


def _shadow_field(op, name):
    """Тень из операции: true — по умолчанию, объект — свои поля, нет — None."""
    v = op.get("shadow")
    if v is None or v is False:
        return None
    if v is True:
        return {k: d for k, _lo, _hi, d in _api.montage_project.SHADOW_FIELDS}
    if not isinstance(v, dict):
        raise _OpError(f"{name}: shadow — true или объект {{size, x, y, opacity, color}}")
    return v


def _op_panels(p, op, fps, db, state):
    """Сплит-экран: куски (shots — id планов или srcs — {src, in}) в панелях
    раскладки layout поверх фона background (цвет; null — без фона: в щелях
    основная дорожка) на [at, at + length); stagger — панели входят по
    очереди через столько секунд, flash — вспышка входа панели (спад
    flash_decay), shadow — тень панелей. layout scatter — окна-вставки
    вразброс (_scatter): кусков 1…12, size — ширина окна (доля кадра;
    [min, max] — разные), aspect — пропорции окна (16:9), avoid, seed; фона
    по умолчанию нет, все окна держатся до конца отрезка. layout quad — четыре
    окна ровной сеткой 2×2 с просветом по центру (_quad: size, aspect),
    входят по порядку shots/srcs: левое верхнее, правое верхнее, левое
    нижнее, правое нижнее; фона тоже нет."""
    layout = op.get("layout", "v3")
    if layout not in PANEL_LAYOUTS:
        raise _OpError(f"panels: layout — {', '.join(PANEL_LAYOUTS)}")
    pieces = [{"shot": s} for s in op.get("shots") or []] + list(op.get("srcs") or [])
    at, length = _span(p, op, fps)
    try:
        gap = float(op.get("gap", 0.012))
        stagger = float(op.get("stagger", 0.0))
        flash = float(op.get("flash", 0.0))
        flash_decay = float(op.get("flash_decay", 0.05 if layout in _WINDOW_LAYOUTS else 0.12))
    except (TypeError, ValueError):
        raise _OpError("panels: gap, stagger, flash и flash_decay — числа") from None
    if layout == "scatter":
        if not 1 <= len(pieces) <= SCATTER_MAX:
            raise _OpError(f"panels: у scatter от 1 до {SCATTER_MAX} кусков shots/srcs")
        boxes, centers = _scatter(p, op, len(pieces))
    elif layout == "quad":
        boxes, centers = _quad(p, op, len(pieces))
    else:
        (bw, bh), centers = _PANELS[layout]
        if len(pieces) != len(centers):
            raise _OpError(f"panels: у {layout} {len(centers)} панели — столько shots/srcs")
        box = [max(0.02, bw - (gap if bw < 1 else 0)), max(0.02, bh - (gap if bh < 1 else 0))]
        boxes = [box] * len(centers)
    shadow = _shadow_field(op, "panels")
    out = {"panels": []}
    bg = op.get("background", None if layout in _WINDOW_LAYOUTS else "#000000")
    if bg is not None:
        folder = state.get("cards")
        if not folder:
            raise _OpError("panels: фон пишется рядом с проектом — edit по файлу проекта")
        w, h, _fps = p.output_format()
        try:
            png = _api.card_background({"colors": [bg, bg], "vignette": 0.0, "noise": 0.0},
                                       w, h, folder)
        except (ValueError, TypeError, OSError) as e:
            raise _OpError(f"panels: {e}") from e
        back = _op_add(p, {"op": "add", "src": png, "in": 0.0, "length": length, "at": at,
                           "track": _free_video_track(p, at, at + length)}, fps, db)
        out["background"] = back.id
    for i, (piece, (cx, cy), box) in enumerate(zip(pieces, centers, boxes)):
        if not isinstance(piece, dict):
            raise _OpError("panels: srcs — объекты {src, in}")
        a = at + i * stagger
        if length - i * stagger < _api.montage_project.MIN_CLIP_S:
            raise _OpError("panels: stagger съел длину панели")
        add = {"op": "add", "at": a, "length": length - i * stagger,
               "track": _free_video_track(p, a, at + length)}
        for key in ("shot", "src", "in", "in_offset", "db"):
            if key in piece:
                add[key] = piece[key]
        c = _op_add(p, add, fps, db)
        fields = {"box": [round(box[0], 6), round(box[1], 6)], "fit": "crop",
                  "pos_x": round(cx, 6), "pos_y": round(cy, 6), "muted": True}
        if shadow is not None:
            fields["shadow"] = shadow
        _set_fields(p, c, fields)
        if flash > 0:
            add_clip_effect(p, c, {"type": "flash", "amount": min(1.0, flash),
                                   "decay": flash_decay})
        out["panels"].append(c.id)
    return out


# Колонки по слогам (стиль rcn): поля и щели по умолчанию — доли ширины.
COLUMNS_MARGIN = 0.03
COLUMNS_GAP = 0.04
COLUMNS_FILL = 0.9            # слог занимает такую долю ширины колонки
COLUMNS_TAIL = 0.3            # рез после конца слова, если until не задан и реза нет
COLUMNS_MAX = 8
COLUMNS_CUT_DECAY = 0.06      # спад вспышки на резе (эталон: белый 1–3 кадра при 60 к/с)


def _word_end(p, t, fps):
    """Конец метки word, которая начинается на t (± кадр), или None."""
    for m in p.markers:
        if m.kind == "word" and abs(m.t - t) <= 1.0 / fps + 1e-6 and m.end is not None:
            return m.end
    return None


def _syllable_times(p, op, fps, at, end, n):
    """Время слогов: times — список; vocals — атаки стема вокала, ближайшие
    к равным долям [at, end); even (по умолчанию) — равными долями.
    Первый слог — at."""
    times = op.get("times", "even")
    if isinstance(times, list):
        if len(times) != n:
            raise _OpError(f"columns: times — {n} времён, по слогу")
        out = [resolve_time(p, v, fps) for v in times]
    elif times in ("even", "vocals"):
        step = (end - at) / n
        out = [at + i * step for i in range(n)]
        if times == "vocals" and n > 1:
            try:
                attacks = [float(x) for x in _api.vocal_attacks(p)]
            except _api.ToolError as e:
                raise _OpError(f"columns: атаки вокала — {e.message}") from e
            for i in range(1, n):
                near = [(abs(a - out[i]), a) for a in attacks
                        if abs(a - out[i]) <= step / 2 and a > out[i - 1] + 2.0 / fps]
                if near:
                    out[i] = min(near)[1]
        out = [_api.snap_frame(t, fps)[0] for t in out]
    else:
        raise _OpError("columns: times — список, even или vocals")
    if any(b <= a for a, b in zip(out, out[1:])):
        raise _OpError(f"columns: время слогов не по возрастанию {[round(t, 3) for t in out]}")
    return out


def _columns_until(p, op, fps, at, end):
    """Рез колонок на план: until операции; иначе начало первого клипа
    основной дорожки не раньше конца слова; нет его — конец слова + хвост."""
    if "until" in op:
        return resolve_time(p, op["until"], fps)
    after = end if end is not None else at + 0.1
    nxt = next((c.start for c in p.clips_on(p.main_track) if c.start >= after - 0.5 / fps),
               None)
    return nxt if nxt is not None else resolve_time(p, after + COLUMNS_TAIL, fps)


def _columns_plan(p, fps, until):
    """План основной дорожки, который начинается в until (на него рез)."""
    nxt = next((c for c in p.clips_on(p.main_track) if abs(c.start - until) <= 0.5 / fps), None)
    if nxt is None or not nxt.has_video:
        raise _OpError(f"columns: в until ({until:.3f} с) на основной дорожке нет реза на план; "
                       f"поставьте рез или задайте shot")
    if nxt.reverse or nxt.speed_curve:
        raise _OpError("columns: у плана после реза реверс или кривая скорости — колонки "
                       "не совпадут с ним; задайте shot")
    return nxt


def _op_columns(p, op, fps, db, state):
    """Слово по слогам в колонках (стиль rcn): на каждый слог открывается
    вертикальная колонка следующего плана — наложение с маской rect своей
    колонки и вспышкой входа; по центру колонки — слог (op text: preset и
    style операции, кегль общий — под самый широкий слог). Колонки держатся
    до until — реза основной дорожки на этот план (кадр колонок там
    продолжается целиком); cut_flash — вспышка на самом резе.
      at — начало слова (word#N); end — конец пропетого слова (по умолчанию
      конец метки word в at); until — рез (по умолчанию начало первого
      клипа основной дорожки после end, нет — end + 0.3);
      text — слово (дефис или «·» — свои слоги) или syllables — список;
      times — список, even (поровну на [at, end)) или vocals (атаки стема);
      shot | src + in — свой кусок с начала вместо плана после реза;
      margin, gap — поля и щели (доли ширины), flash, flash_decay, shadow,
      case (upper/lower), pos_y, layer."""
    mp = _api.montage_project
    syl = op.get("syllables")
    if syl is None:
        syl = _api.syllables(str(op.get("text") or ""))
    if not isinstance(syl, list) or not syl or not all(isinstance(x, str) and x.strip()
                                                       for x in syl):
        raise _OpError("columns: text — слово или syllables — непустой список слогов")
    if len(syl) > COLUMNS_MAX:
        raise _OpError(f"columns: слогов больше {COLUMNS_MAX} — колонки станут нитками")
    at = resolve_time(p, op.get("at"), fps)
    end = resolve_time(p, op["end"], fps) if "end" in op else _word_end(p, at, fps)
    until = _columns_until(p, op, fps, at, end)
    if end is None or end > until:
        end = until
    if until - at < mp.MIN_CLIP_S * len(syl):
        raise _OpError("columns: until слишком близко к at")
    times = _syllable_times(p, op, fps, at, end, len(syl))
    if times[0] < at - 1e-6 or times[-1] > until - mp.MIN_CLIP_S:
        raise _OpError("columns: слог вне [at, until)")
    try:
        margin = float(op.get("margin", COLUMNS_MARGIN))
        gap = float(op.get("gap", COLUMNS_GAP))
        flash = float(op.get("flash", 1.0))
        flash_decay = float(op.get("flash_decay", 0.05))
        cut_flash = float(op.get("cut_flash", flash))
    except (TypeError, ValueError):
        raise _OpError("columns: margin, gap, flash, flash_decay, cut_flash — числа") from None
    n = len(syl)
    cw = (1.0 - 2 * margin - (n - 1) * gap) / n
    if cw < 0.05 or margin < 0 or gap < 0:
        raise _OpError("columns: поля и щели не оставили места колонкам")
    shadow = _shadow_field(op, "columns")
    own = "shot" in op or "src" in op
    plan = None if own else _columns_plan(p, fps, until)
    out = {"columns": [], "syllables": list(syl), "times": [round(t, 4) for t in times],
           "until": round(until, 4)}
    for i, t in enumerate(times):
        x0 = margin + i * (cw + gap)
        add = {"op": "add", "at": t, "length": until - t,
               "track": _free_video_track(p, t, until, top=True)}
        if own:
            add["in_offset"] = t - times[0]
            for key in ("shot", "src", "in", "db"):
                if key in op:
                    add[key] = op[key]
        else:
            # Кадр колонки на until — первый кадр плана после реза.
            src_in = plan.in_s if plan.frozen or plan.is_image else \
                plan.in_s - (until - t) * plan.play_speed
            add.update(src=plan.src, speed=plan.speed, **{"in": max(0.0, src_in)})
        c = _op_add(p, add, fps, db)
        fields = {"mask": {"shape": "rect", "rect": [round(x0, 6), 0.0, round(x0 + cw, 6), 1.0]},
                  "muted": True, "fit": (plan.fit if plan else "") or p.settings.fit}
        if plan is not None and plan.frozen:
            fields["freeze_at"] = plan.freeze_at
        if plan is not None and plan.crop:
            fields["crop"] = list(plan.crop)
        if shadow is not None:
            fields["shadow"] = shadow
        _set_fields(p, c, fields)
        if flash > 0:
            add_clip_effect(p, c, {"type": "flash", "amount": min(1.0, flash),
                                   "decay": flash_decay})
        out["columns"].append(c.id)
    if plan is not None and cut_flash > 0:
        add_clip_effect(p, plan, {"type": "flash", "amount": min(1.0, cut_flash),
                                  "decay": COLUMNS_CUT_DECAY})
    geo = dict(margin=margin, gap=gap, cw=cw)
    out["texts"] = _column_texts(p, op, fps, db, state, syl, times, until, geo,
                                 p.clip(out["columns"][0]))
    return out


def _column_texts(p, op, fps, db, state, syl, times, until, geo, first):
    """Слоги колонок: op text в центре колонки, общий кегль под самый
    широкий слог; цвет auto — под кадр колонок (середина первой)."""
    import subtitle_ass
    base = {"op": "text", "text": " ".join(syl)}
    for k in ("preset", "style"):
        if k in op:
            base[k] = op[k]
    try:
        spec = _api.apply_preset(base, base["text"])
    except (ValueError, _api.ToolError) as e:
        raise _OpError(f"columns: {getattr(e, 'message', e)}") from e
    style = dict(spec.get("style") or {})
    case = op.get("case", spec.get("case", ""))
    words = [s.upper() if case == "upper" else s.lower() if case == "lower" else s for s in syl]
    try:
        py = float(op.get("pos_y", spec.get("pos_y", 0.5)))
    except (TypeError, ValueError):
        raise _OpError("columns: pos_y — число") from None
    margin, gap, cw = geo["margin"], geo["gap"], geo["cw"]
    centers = [margin + i * (cw + gap) + cw / 2 for i in range(len(words))]
    res_x, res_y = _api.text_canvas(p)
    full = dict(subtitle_ass.DEFAULT_SUBTITLE_STYLE, **style)
    size = min(_api.fit_size(wd, full, cw * COLUMNS_FILL, cx, py, res_x, res_y)
               for wd, cx in zip(words, centers))
    style["size"] = min(float(full["size"]), size)
    if style.get("color") == "auto":
        mid = first.in_s + 0.5 * first.length * first.play_speed
        style["color"] = _api.text_color(_api.frame_rgb(first.src, mid))
    ids = []
    for wd, t, cx in zip(words, times, centers):
        t_op = {"op": "text", "start": t, "end": until, "text": wd, "style": style,
                "pos_x": round(cx, 6), "pos_y": py}
        if "layer" in op or "layer" in spec:
            t_op["layer"] = op.get("layer", spec.get("layer"))
        ids.append(_apply(p, t_op, fps, db, state)["text"])
    return ids


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
    if kind in ("text", "words", "lyrics") and ("preset" in op or isinstance(op.get("emphasis"), dict)):
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
            items = mp.parse_texts(_api.resolve_auto_colors(p, [raw]))
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
    elif kind == "sequence":
        out.update(_op_sequence(p, op, fps, db, state))
    elif kind == "cutout":
        c = _op_cutout(p, op, fps, db)
        state["last"] = c.id
        out["clip"] = c.id
    elif kind == "panels":
        out.update(_op_panels(p, op, fps, db, state))
        state["last"] = out["panels"][-1]
    elif kind == "snap_cuts":
        out.update(_op_snap_cuts(p, op, fps))
    elif kind == "columns":
        out.update(_op_columns(p, op, fps, db, state))
        state["last"] = out["columns"][-1]
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
