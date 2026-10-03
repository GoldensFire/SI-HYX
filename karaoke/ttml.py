"""AMLL/Apple TTML word timing, pronunciation and language-aware translations."""
from __future__ import annotations

from xml.etree import ElementTree as ET
from .model import Line, Unit, validate
from .ass import seconds
from .romanization import romanize_units

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def local(name):
    return name.rsplit("}", 1)[-1]


def role(node):
    return next((v for k, v in node.attrib.items() if local(k) == "role"), "")


def clock(value):
    value = value.strip()
    if value.endswith("ms"):
        return float(value[:-2]) / 1000
    if value.endswith("s"):
        return float(value[:-1])
    return seconds(value)


def read_ttml(payload):
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("TTML с объявлениями сущностей не поддерживается.")
    root = ET.fromstring(payload)
    result = []
    for paragraph in root.iter():
        if local(paragraph.tag) != "p" or not paragraph.get("begin"):
            continue
        start = clock(paragraph.get("begin"))
        end = clock(paragraph.get("end", str(start) + "s"))
        units, translations, roman = [], {}, []
        for child in paragraph:
            kind = role(child)
            if "translation" in kind:
                language = child.get(XML_LANG, root.get(XML_LANG, "")).lower().split("-")[0]
                if language in ("ru", "en"):
                    translations[language] = "".join(child.itertext()).strip()
                continue
            if "roman" in kind:
                roman.append(child)
                continue
            if "background" in kind or kind == "x-bg":
                continue
            if not child.get("begin") or not child.get("end"):
                continue
            romaji = next(("".join(n.itertext()) for n in child
                           if "roman" in role(n)), "")
            text = child.text or ""
            text += "".join("".join(n.itertext()) + (n.tail or "")
                            for n in child if not role(n))
            text = romaji or text
            # AMLL stores separators as span tails.
            text += child.tail if child.tail and child.tail.isspace() and "\n" not in child.tail else ""
            units.append(Unit(clock(child.get("begin")), clock(child.get("end")), text))
        if units:
            for reading in roman:
                timed = [n for n in reading if n.get("begin") and n.get("end")]
                if timed:
                    units = [Unit(clock(n.get("begin")), clock(n.get("end")),
                                  "".join(n.itertext()) + (n.tail or "")) for n in timed]
                    break
                words = "".join(reading.itertext()).split()
                if len(words) == len(units):
                    units = [Unit(u.start, u.end, word + (" " if i + 1 < len(words) else ""))
                             for i, (u, word) in enumerate(zip(units, words))]
                    break
            result.append(Line(start, end, romanize_units(units), translations))
    result.sort(key=lambda line: line.start)
    return validate(result)
