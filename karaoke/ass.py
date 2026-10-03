r"""Import authored ASS timing and render clean, safe \kf subtitles."""
from __future__ import annotations

import re
from .model import Line, Unit, validate
from .layout import positions
from .style import FONT_NAME, ass_colour, choose_colour, fitted_size, font_size

TAG = re.compile(r"\{([^}]*)\}")
K = re.compile(r"\\(?:kf|ko|k|K)(\d+)")


def seconds(value):
    parts = value.strip().split(":")
    return sum(float(part) * 60 ** i for i, part in enumerate(reversed(parts)))


def read_ass(payload):
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    lines, native, translations = [], [], []
    fields = []
    section = ""
    for raw in text.splitlines():
        if raw.startswith("["):
            section = raw.strip().lower()
        if section != "[events]":
            continue
        if raw.startswith("Format:"):
            fields = [x.strip().lower() for x in raw.split(":", 1)[1].split(",")]
        if not raw.startswith("Dialogue:") or not fields or fields[-1] != "text":
            continue
        values = raw.split(":", 1)[1].lstrip().split(",", len(fields) - 1)
        if len(values) != len(fields):
            continue
        event = dict(zip(fields, values))
        start, end = seconds(event["start"]), seconds(event["end"])
        body = event["text"]
        style = event.get("style", "").lower()
        # Furigana is a duplicate pronunciation layer, not another lyric line.
        if "furigana" in style or re.search(r"\\p[1-9]", body):
            continue
        chunks = re.split(r"(\{[^}]*\})", body)
        units, cursor, pending = [], start, None
        for chunk in chunks:
            if chunk.startswith("{"):
                for tag in K.findall(chunk):
                    if pending is not None:
                        cursor += pending
                    pending = int(tag) / 100
            elif chunk:
                clean = chunk.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
                if pending is None:
                    if units:
                        last = units[-1]
                        units[-1] = Unit(last.start, last.end, last.text + clean)
                    continue
                units.append(Unit(cursor, min(end, cursor + pending), clean))
                cursor += pending
                pending = None
        if units and end > start:
            # Timing annotations may contain a trailing empty \k segment.
            units = [u for u in units if u.start <= end]
            clean = "".join(u.text for u in units)
            if re.search(r"[А-Яа-яЁё]", clean):
                translations.append((start, end, "ru", clean))
            elif re.search(r"[\u3040-\u30ff\u3400-\u9fff]", clean):
                native.append(Line(start, end, units))
            elif any(t in style for t in ["trans", "eng", "en "]):
                translations.append((start, end, "en", clean))
            elif units:
                lines.append(Line(start, end, units))
        elif end > start:
            clean = TAG.sub("", body).replace(r"\N", " ").strip()
            language = "ru" if re.search(r"[А-Яа-яЁё]", clean) else "en"
            if clean and (language == "ru" or any(t in style for t in ["trans", "eng", "en "])):
                translations.append((start, end, language, clean))
    if not lines and native:
        from .romanization import romanize_units
        lines = [Line(line.start, line.end, romanize_units(line.units)) for line in native]
    lines.sort(key=lambda x: x.start)
    for start, end, language, text in translations:
        matches = [line for line in lines if abs(line.start - start) < .2
                   and abs(line.end - end) < .3]
        if len(matches) == 1:
            matches[0].translations[language] = text
    return validate(lines)


def escape(text):
    # No source override tag, drawing command or escape reaches libass.
    return str(text).replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ").replace("\r", " ")


def stamp(value):
    cs = max(0, round(value * 100))
    hours, cs = divmod(cs, 360000)
    minutes, cs = divmod(cs, 6000)
    seconds_, cs = divmod(cs, 100)
    return f"{hours}:{minutes:02d}:{seconds_:02d}.{cs:02d}"


def write_ass(lines, width=1280, height=720, *, translations=False, highlight=None):
    validate(lines)
    size = font_size(height)
    colour = ass_colour(highlight or choose_colour())
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Romaji,{FONT_NAME},{size},{colour},&H00F8F8FF,&H00101016,&H70000000,-1,0,0,0,100,100,0,0,1,5,1.5,5,48,48,0,1
Style: Translation,{FONT_NAME},{round(size*.65)},&H00F8F8FF,&H00F8F8FF,&H00101016,&H70000000,-1,0,0,0,100,100,0,0,1,4,1.5,5,48,48,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    layout = positions(lines, height, size, translations=translations)
    for index, line in enumerate(lines):
        visible_start, y, translation_y = layout[index]
        cursor = round(visible_start * 100)
        body = [r"{\pos(" + f"{width // 2},{y}" + ")}"]
        fitted = fitted_size(line.text, width, size)
        if fitted < size:
            body.append(r"{\fs" + str(fitted) + "}")
        for unit in line.units:
            start, end = round(unit.start * 100), round(unit.end * 100)
            if start > cursor:
                body.append(r"{\kf" + str(start - cursor) + "}")
            body.append(r"{\kf" + str(max(0, end - start)) + "}" + escape(unit.text))
            cursor = end
        prefix = f"0,{stamp(visible_start)},{stamp(line.end)},"
        events.append("Dialogue: " + prefix + "Romaji,,0,0,0,," + "".join(body))
        if translations and line.translation:
            position = r"{\pos(" + f"{width // 2},{translation_y}" + ")}"
            translated_size = fitted_size(line.translation, width, round(size * .65))
            position += r"{\fs" + str(translated_size) + "}"
            events.append("Dialogue: " + prefix + "Translation,,0,0,0,," + position + escape(line.translation))
    return header + "\n".join(events) + "\n"
