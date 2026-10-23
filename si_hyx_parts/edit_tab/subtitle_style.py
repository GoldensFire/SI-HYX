# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: оригинальный стиль субтитров — mov_text в ASS и правка текста без
потери стилей.

mov_text (MP4/M4V) хранит размер шрифта в пикселях кадра, а ffmpeg при
переводе в ASS ставит холст 384×288: шрифт 51 из кадра высотой 1036 выходит
51/288 ≈ 18 % высоты на строку — субтитры «в полэкрана». Здесь холст ASS
подставляется по размеру видео.

Правка идёт в окне «Создать субтитры»: edit_cues даёт ему реплики ASS с
номерами их событий и похожим стилем, rebuild_ass возвращает правку в те же
события — время и текст новые, стиль, позиция и теги остаются своими, даже
если реплику сдвинули по времени."""
import re

import edit_tab as _api
from edit_tab_base import (
    DEFAULT_SUBTITLE_STYLE, _ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V,
    _ASS_PLAYRES_X, _ASS_PLAYRES_Y, _animation_override_tags, _hex_to_ass_color,
    _style_num
)


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


def play_res(ass_text):
    """(PlayResX, PlayResY) холста ASS так, как их берёт libass: недостающий
    достраивается из другого (1280 ↔ 1024, иначе 4:3), без обоих — 384×288."""
    values = {}
    for m in _PLAYRES_RE.finditer(ass_text or ""):
        try:
            values[m.group(1).lower()] = int(m.group(0).split(":", 1)[1].strip())
        except ValueError:
            pass
    x, y = values.get("playresx", 0), values.get("playresy", 0)
    if x <= 0 and y <= 0:
        return 384, 288
    if y <= 0:
        y = 1024 if x == 1280 else max(1, x * 3 // 4)
    if x <= 0:
        x = 1280 if y == 1024 else max(1, y * 4 // 3)
    return x, y


def play_res_y(ass_text):
    """Высота холста ASS так, как её берёт libass (см. play_res)."""
    return play_res(ass_text)[1]


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


def fit_canvas_file(src, path):
    """Холст .ass-копии mov_text — по размеру кадра src, на месте: превью
    «как в оригинале» рисует её так же, как вшивание (mov_text_burn_file)."""
    size = video_size(src)
    if not size:
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(set_play_res(text, size))


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


_STYLE_FORMAT = ["name", "fontname", "fontsize", "primarycolour", "secondarycolour",
                 "outlinecolour", "backcolour", "bold", "italic", "underline",
                 "strikeout", "scalex", "scaley", "spacing", "angle", "borderstyle",
                 "outline", "shadow", "alignment", "marginl", "marginr", "marginv",
                 "encoding"]
_AN_RE = re.compile(r"\\an([1-9])")


def _styles(lines):
    """Стили раздела [V4+ Styles]: (поля Format, {имя: поля}, номер строки,
    после которой дописывать свои стили, или None — раздела нет)."""
    fmt, styles, in_styles, last = None, {}, False, None
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("["):
            in_styles = low in ("[v4+ styles]", "[v4 styles]")
            if in_styles:
                last = i
            continue
        if not in_styles:
            continue
        if low.startswith("format:"):
            fmt = [p.strip().lower() for p in line.split(":", 1)[1].split(",")]
            last = i
        elif low.startswith("style:") and fmt:
            parts = line.split(":", 1)[1].lstrip().split(",", len(fmt) - 1)
            if len(parts) == len(fmt):
                st = dict(zip(fmt, (p.strip() for p in parts)))
                styles[st.get("name", "")] = st
            last = i
    return fmt, styles, last


def _event_style(styles, ev):
    """Стиль события так, как его ищет libass: имя без «*», иначе Default."""
    name = str(ev.get("style", "")).strip().lstrip("*")
    return (styles.get(name) or styles.get("Default")
            or next(iter(styles.values()), {}))


def _ass_colour(value):
    """Цвет ASS («&HAABBGGRR» или число) → ('#RRGGBB', прозрачность 0..255)."""
    v = str(value or "").strip().upper().rstrip("&")
    try:
        n = int(v[2:], 16) if v.startswith("&H") else int(v)
    except ValueError:
        return "#FFFFFF", 0
    a, b, g, r = (n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255
    return f"#{r:02X}{g:02X}{b:02X}", a


def editor_style(st, res, lead=""):
    """Стиль ASS → стиль реплики окна «Создать субтитры» (единицы его холста
    384×288, см. DEFAULT_SUBTITLE_STYLE): окно правки показывает реплику
    похожей на оригинал. lead — ведущие теги события (их \\an — выравнивание)."""
    k = _ASS_PLAYRES_Y / float(res[1])

    def num(key, default=0.0):
        try:
            return float(st.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    color, _alpha = _ass_colour(st.get("primarycolour"))
    outline_color, _alpha = _ass_colour(st.get("outlinecolour"))
    _back, back_alpha = _ass_colour(st.get("backcolour"))
    align = int(num("alignment", 2))
    an = _AN_RE.search(lead or "")
    if an:
        align = int(an.group(1))
    return {
        'font': st.get("fontname") or "Arial",
        # Кегль и интервал — без округления до целых: сменишь реплике только
        # цвет, а размер в файле остаётся прежним.
        'size': max(1.0, round(num("fontsize", 20) * k, 3)),
        'bold': num("bold") != 0, 'italic': num("italic") != 0,
        'underline': num("underline") != 0,
        'align': align if 1 <= align <= 9 else 2,
        'spacing': round(num("spacing") * k, 3),
        'color': color, 'outline_color': outline_color,
        'outline': round(num("outline") * k, 2), 'shadow': round(num("shadow") * k, 2),
        'shadow_alpha': back_alpha,
        'scale_x': num("scalex", 100), 'scale_y': num("scaley", 100),
        'animation': 'none',
    }


def edit_cues(ass_text):
    """Реплики ASS для окна правки: [{'start','end','text','src','base'}] по
    времени. src — номера строк событий в файле: по ним rebuild_ass вернёт
    правку в те же события, даже если реплику сдвинули по времени. Слои одной
    реплики (то же время и текст — подложка и сам текст опенинга) идут одной
    репликой. Рисунки без текста в список не попадают и остаются в файле."""
    lines, fmt, events = _events(ass_text)
    if not fmt or not {"start", "end", "text"} <= set(fmt):
        return []
    _sfmt, styles, _last = _styles(lines)
    res = play_res(ass_text)
    merged, out = {}, []
    for idx, ev in events:
        st, en = _parse_ass_ts(ev.get("start", "")), _parse_ass_ts(ev.get("end", ""))
        text = _plain(ev.get("text", ""))
        if st is None or en is None or en <= st or not text:
            continue
        key = (round(st, 2), round(en, 2), text)
        if key in merged:
            merged[key]['src'].append(idx)
            continue
        lead = _LEAD_OVERRIDE_RE.match(ev["text"])
        cue = {'start': st, 'end': en, 'text': text, 'src': [idx],
               'base': editor_style(_event_style(styles, ev), res,
                                    lead.group(0) if lead else "")}
        merged[key] = cue
        out.append(cue)
    out.sort(key=lambda c: (c['start'], c['end']))
    for cue in out:
        cue['src'] = tuple(cue['src'])
    return out


def _style_fields(name, style, res):
    """Поля стиля ASS из стиля окна правки — в единицах холста файла res."""
    k = res[1] / float(_ASS_PLAYRES_Y)
    kx = res[0] / float(_ASS_PLAYRES_X)

    def num(key, default, scale=1.0):
        value = _style_num(style, key, default) * scale
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return {
        "name": name,
        "fontname": style.get('font') or DEFAULT_SUBTITLE_STYLE['font'],
        "fontsize": num('size', DEFAULT_SUBTITLE_STYLE['size'], k),
        "primarycolour": _hex_to_ass_color(style.get('color') or '#FFFFFF'),
        "secondarycolour": "&H000000FF",
        "outlinecolour": _hex_to_ass_color(style.get('outline_color') or '#000000'),
        "backcolour": _hex_to_ass_color(
            '#000000', int(_style_num(style, 'shadow_alpha', 0))),
        "bold": "-1" if style.get('bold') else "0",
        "italic": "-1" if style.get('italic') else "0",
        "underline": "-1" if style.get('underline') else "0",
        "strikeout": "0",
        "scalex": num('scale_x', 100), "scaley": num('scale_y', 100),
        "spacing": num('spacing', 0, k), "angle": "0", "borderstyle": "1",
        "outline": num('outline', 1, k), "shadow": num('shadow', 0, k),
        "alignment": str(int(style.get('align') or 2)),
        "marginl": str(int(round(_ASS_MARGIN_L * kx))),
        "marginr": str(int(round(_ASS_MARGIN_R * kx))),
        "marginv": str(int(round(_ASS_MARGIN_V * k))),
        "encoding": "1", "alphalevel": "0",
    }


def _ass_text(body):
    """Текст реплики окна → поле Text события: фигурные скобки не должны стать
    тегами, переносы строк — \\N."""
    text = body.replace("{", "｛").replace("}", "｝")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\\N")


def rebuild_ass(ass_text, cues):
    """Исходный ASS с правкой из окна субтитров. cues — его реплики
    [{'start','end','text','style','src','tmpl','restyled'}] (см.
    SubtitleCreatorDialog.cues).

    Реплика с src возвращается в свои события: время и текст — новые, стиль,
    поля и ведущие теги ({\\an8\\pos…}) — свои; текст не правили — остаются и
    теги внутри строки. Раньше событие искалось по времени, и сдвинутая
    реплика теряла свой стиль — получала стиль первого события файла (у
    Kanon — опенинга, прижатого вправо). Новая реплика берёт событие-образец
    tmpl (так дублируется реплика оригинала). Реплика, которой в окне сменили
    стиль (restyled), и новая без образца получают стиль из окна в единицах
    холста файла — как их показывало окно, без старых ведущих тегов. Событие
    с текстом, которого нет ни в одной реплике, удалено правкой; рисунки без
    текста остаются. None — разобрать оригинал не удалось."""
    lines, fmt, events = _events(ass_text)
    if not fmt or not {"start", "end", "text"} <= set(fmt):
        return None
    by_line = dict(events)
    sfmt, styles, styles_last = _styles(lines)
    res = play_res(ass_text)
    margins = (int(round(_ASS_MARGIN_L * res[0] / float(_ASS_PLAYRES_X))),
               int(round(_ASS_MARGIN_R * res[0] / float(_ASS_PLAYRES_X))),
               int(round(_ASS_MARGIN_V * res[1] / float(_ASS_PLAYRES_Y))))
    taken, new_styles = set(styles), []

    def own_style(style):
        n = len(new_styles) + 1
        while f"SIHYX{n}" in taken:
            n += 1
        name = f"SIHYX{n}"
        taken.add(name)
        fields = _style_fields(name, style, res)
        new_styles.append("Style: " + ",".join(fields.get(k, "0")
                                               for k in (sfmt or _STYLE_FORMAT)))
        return name

    def anim(style, start, end):
        return _animation_override_tags(
            style.get('animation', 'none'), int(style.get('align') or 2),
            max(0.01, end - start), play_res=res, margins=margins)

    def dialogue(fields):
        return "Dialogue: " + ",".join(fields.get(k, "") for k in fmt)

    new_lines, keep, extra = {}, set(), []
    for cue in cues:
        start, end = float(cue['start']), float(cue['end'])
        body = str(cue.get('text') or '').strip()
        style = cue.get('style') or {}
        restyled = bool(cue.get('restyled'))
        src = [i for i in (cue.get('src') or ()) if i in by_line]
        if src:
            # Слои одной реплики в новом стиле — одним событием: иначе
            # одинаковый текст лёг бы сам на себя.
            name = own_style(style) if restyled else None
            for idx in (src[:1] if restyled else src):
                ev = by_line[idx]
                fields = dict(ev)
                if (abs((_parse_ass_ts(ev["start"]) or 0.0) - start) >= 0.005
                        or abs((_parse_ass_ts(ev["end"]) or 0.0) - end) >= 0.005):
                    fields["start"], fields["end"] = _ass_ts(start), _ass_ts(end)
                if name:
                    fields["style"] = name
                    fields["text"] = anim(style, start, end) + _ass_text(body)
                elif _plain(ev["text"]) != body:
                    lead = _LEAD_OVERRIDE_RE.match(ev["text"])
                    fields["text"] = (lead.group(0) if lead else "") + _ass_text(body)
                keep.add(idx)
                new_lines[idx] = dialogue(fields)
            continue
        tmpl = by_line.get(cue.get('tmpl'))
        if tmpl is not None and not restyled:
            lead = _LEAD_OVERRIDE_RE.match(tmpl["text"])
            fields = dict(tmpl, start=_ass_ts(start), end=_ass_ts(end),
                          text=(lead.group(0) if lead else "") + _ass_text(body))
        else:
            fields = {k: "" for k in fmt}
            fields.update({"layer": "0", "start": _ass_ts(start), "end": _ass_ts(end),
                           "style": own_style(style), "marginl": "0", "marginr": "0",
                           "marginv": "0", "text": anim(style, start, end) + _ass_text(body)})
        extra.append(dialogue(fields))

    # Новые события — в конец раздела [Events] (за ним бывают [Fonts] и др.).
    events_hdr = next((i for i, line in enumerate(lines)
                       if line.strip().lower() == "[events]"), 0)
    events_last = events_hdr
    for i in range(events_hdr + 1, len(lines)):
        if lines[i].strip().startswith("["):
            break
        if lines[i].strip():
            events_last = i
    out = []
    for i, line in enumerate(lines):
        if i == events_hdr and new_styles and styles_last is None:
            out += ["[V4+ Styles]",
                    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                    "Alignment, MarginL, MarginR, MarginV, Encoding"]
            out += new_styles + [""]
        if i in new_lines:
            out.append(new_lines[i])
        elif not (i in by_line and i not in keep and _plain(by_line[i]["text"])):
            out.append(line)    # иначе реплику удалили в окне правки
        if i == styles_last:
            out += new_styles
        if i == events_last:
            out += extra
    return "\n".join(out) + "\n"
