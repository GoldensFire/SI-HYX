# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: оригинальный стиль субтитров — mov_text в ASS и правка текста без
потери стилей.

mov_text (MP4/M4V) хранит размер шрифта в пикселях кадра, а ffmpeg при
переводе в ASS ставит холст 384×288: шрифт 51 из кадра высотой 1036 выходит
51/288 ≈ 18 % высоты на строку — субтитры «в полэкрана». Здесь холст ASS
подставляется по размеру видео.

Правка текста идёт через SRT (редактор), и без этого модуля сохранённый файл
терял все стили оригинала. rebuild_ass возвращает правленый текст в события
исходного ASS: стиль, позиция и теги реплики остаются её собственными."""
import re

import edit_tab as _api


_PLAYRES_RE = re.compile(r"^(PlayRes[XY])\s*:.*$", re.MULTILINE | re.IGNORECASE)
_OVERRIDE_RE = re.compile(r"\{[^}]*\}")
_LEAD_OVERRIDE_RE = re.compile(r"^(?:\{[^}]*\})+")


def _run_ffmpeg(cmd, timeout=60):
    kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
    return _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                               stderr=_api.subprocess.DEVNULL, timeout=timeout, **kw)


def video_size(src):
    """(ширина, высота) первого видеопотока или None."""
    try:
        r = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW, timeout=15)
        w, h = (r.stdout or "").strip().split("x")[:2]
        w, h = int(w), int(h)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def set_play_res(ass_text, size):
    """Ставит PlayResX/PlayResY холста ASS (size — (w, h))."""
    w, h = size
    values = {"playresx": w, "playresy": h}
    out = _PLAYRES_RE.sub(lambda m: f"{m.group(1)}: {values[m.group(1).lower()]}", ass_text)
    if out == ass_text and "PlayResX" not in ass_text:
        out = out.replace("[Script Info]\n",
                          f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}\n", 1)
    return out


def play_res_y(ass_text):
    """Высота холста ASS так, как её берёт libass: PlayResY, а без него — из
    PlayResX (1280 → 1024, иначе ¾ ширины), а без обоих — 288."""
    values = {}
    for m in _PLAYRES_RE.finditer(ass_text or ""):
        try:
            values[m.group(1).lower()] = int(m.group(0).split(":", 1)[1].strip())
        except ValueError:
            pass
    y, x = values.get("playresy", 0), values.get("playresx", 0)
    if y > 0:
        return y
    if x > 0:
        return 1024 if x == 1280 else max(1, x * 3 // 4)
    return 288


def extract_ass(src, rel_idx, codec=""):
    """Дорожка субтитров rel_idx (0:s:N) источника как текст ASS, или None.
    mov_text сразу получает холст по размеру кадра (см. модуль)."""
    tmp = None
    try:
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
        tmp = tf.name; tf.close()
        _run_ffmpeg([_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{int(rel_idx)}",
                     "-c:s", "ass", tmp])
        if not _api.os.path.exists(tmp) or _api.os.path.getsize(tmp) <= 0:
            return None
        with open(tmp, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    finally:
        if tmp:
            try: _api.os.remove(tmp)
            except Exception: pass
    if str(codec).lower() == "mov_text":
        size = video_size(src)
        if size:
            text = set_play_res(text, size)
    return text


def mov_text_burn_file(src, rel_idx):
    """Файл .ass для вшивания mov_text в его исходном размере, или None.
    Лежит во временной папке: «Обработка» читает его уже после возврата."""
    text = extract_ass(src, rel_idx, "mov_text")
    if not text:
        return None
    try:
        folder = _api.os.path.join(_api.tempfile.gettempdir(), "si_hyx_subs")
        _api.os.makedirs(folder, exist_ok=True)
        path = _api.os.path.join(folder, f"burn_{_api.uuid.uuid4().hex}.ass")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path
    except Exception:
        return None


def _ass_ts(sec):
    cs = int(round(max(0.0, float(sec)) * 100))
    h, rest = divmod(cs, 360000)
    m, rest = divmod(rest, 6000)
    s, cs = divmod(rest, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _parse_ass_ts(value):
    try:
        h, m, s = value.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def _plain(text):
    return _OVERRIDE_RE.sub("", text).replace("\\N", "\n").replace("\\n", "\n").strip()


def _events(ass_text):
    """[(номер строки, поля Dialogue)] секции [Events] и список имён полей."""
    lines = ass_text.splitlines()
    fmt, out, in_events = None, [], False
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("["):
            in_events = low == "[events]"
            continue
        if not in_events:
            continue
        if low.startswith("format:"):
            fmt = [p.strip().lower() for p in line.split(":", 1)[1].split(",")]
        elif low.startswith("dialogue:") and fmt:
            parts = line.split(":", 1)[1].lstrip().split(",", len(fmt) - 1)
            if len(parts) == len(fmt):
                out.append((i, dict(zip(fmt, parts))))
    return lines, fmt, out


def ass_cues(ass_text):
    """Реплики ASS как [(начало, конец, текст без тегов)] по времени — для
    расчёта, где в фильме говорят по субтитрам (рисунки без текста — мимо)."""
    _lines, fmt, events = _events(ass_text)
    if not fmt or "start" not in fmt or "end" not in fmt:
        return []
    out = []
    for _idx, ev in events:
        st, en = _parse_ass_ts(ev.get("start", "")), _parse_ass_ts(ev.get("end", ""))
        text = _plain(ev.get("text", ""))
        if st is not None and en is not None and en > st and text:
            out.append((st, en, text))
    return sorted(out)


def shift_ass(ass_text, offset):
    """Весь ASS со сдвинутым на offset секунд временем событий [Events] —
    стили, поля и теги строк остаются как были. Событие, целиком ушедшее
    раньше нуля, удаляется, частично — обрезается по нулю. None — разобрать
    не удалось."""
    lines, fmt, events = _events(ass_text)
    if not fmt or "start" not in fmt or "end" not in fmt:
        return None
    drop, new_lines = set(), {}
    for idx, ev in events:
        st, en = _parse_ass_ts(ev.get("start", "")), _parse_ass_ts(ev.get("end", ""))
        if st is None or en is None:
            continue
        st, en = st + offset, en + offset
        if en <= 0:
            drop.add(idx)
            continue
        fields = dict(ev, start=_ass_ts(max(0.0, st)), end=_ass_ts(en))
        new_lines[idx] = "Dialogue: " + ",".join(fields[k] for k in fmt)
    out = [new_lines.get(i, line) for i, line in enumerate(lines) if i not in drop]
    return "\n".join(out) + "\n"


def rebuild_ass(ass_text, cues):
    """Исходный ASS с текстом из правленых реплик cues [(start, end, text)].

    Реплика находит своё событие по времени (точность — сотые секунды ASS):
    текст тот же — строка остаётся как была, иначе меняется только текст,
    а стиль, поля и ведущие теги ({\\an8\\pos…}) остаются. Событие, у которого
    реплики не нашлось, удалено правкой — кроме безтекстовых (рисунки \\p1:
    в SRT их нет вовсе). Реплика без события получает первый стиль файла.
    None — разобрать оригинал не удалось."""
    lines, fmt, events = _events(ass_text)
    if not fmt or "text" not in fmt or "start" not in fmt:
        return None
    timed = []
    for idx, ev in events:
        st, en = _parse_ass_ts(ev.get("start", "")), _parse_ass_ts(ev.get("end", ""))
        if st is not None and en is not None:
            timed.append((idx, ev, st, en))
    used, new_lines, keep = set(), {}, set()
    fallback = next((ev for _i, ev, _s, _e in timed), None)
    extra = []
    for start, end, body in cues:
        match = None
        for idx, ev, st, en in timed:
            if idx in used or abs(st - start) > 0.02 or abs(en - end) > 0.02:
                continue
            if _plain(ev["text"]) == body.strip():
                match = (idx, ev); break
            if match is None:
                match = (idx, ev)
        text = body.replace("{", "｛").replace("}", "｝")
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
        if match is None:
            extra.append((start, end, text))
            continue
        idx, ev = match
        used.add(idx)
        if _plain(ev["text"]) == body.strip():
            keep.add(idx)
            continue
        lead = _LEAD_OVERRIDE_RE.match(ev["text"])
        fields = dict(ev, text=(lead.group(0) if lead else "") + text)
        new_lines[idx] = "Dialogue: " + ",".join(fields[k] for k in fmt)
    by_line = {idx: ev for idx, ev, _s, _e in timed}
    out = []
    for i, line in enumerate(lines):
        if i in new_lines:
            out.append(new_lines[i])
            continue
        ev = by_line.get(i)
        if ev is not None and i not in keep and _plain(ev["text"]):
            continue   # реплику удалили в редакторе
        out.append(line)
    for start, end, text in extra:
        fields = dict(fallback or {k: "" for k in fmt})
        fields.update({"layer": fields.get("layer") or "0", "start": _ass_ts(start),
                       "end": _ass_ts(end), "name": "", "effect": "", "text": text})
        for k in ("marginl", "marginr", "marginv"):
            if k in fields:
                fields[k] = "0"
        if fallback is None:
            fields["style"] = "Default"
        out.append("Dialogue: " + ",".join(fields.get(k, "") for k in fmt))
    return "\n".join(out) + "\n"
