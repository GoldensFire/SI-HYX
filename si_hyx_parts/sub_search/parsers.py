# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Разбор SRT / ASS / SSA в список реплик (Cue) и проверка «английские ли это»."""
from __future__ import annotations

import codecs
import html
import re

from .matcher import Cue, tokenize

SUB_EXTS = (".srt", ".ass", ".ssa")

_SRT_TIME = re.compile(
    r"(\d{1,3}):(\d{2}):(\d{2})[,.:](\d{1,3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.:](\d{1,3})"
)
_ASS_TIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[.:](\d{1,3})")
_ASS_TAGS = re.compile(r"\{[^}]*\}")
_ASS_DRAWING = re.compile(r"\{[^}]*\\p[1-9]")
_HTML_TAGS = re.compile(r"</?[A-Za-z][^>]*>")
_ASS_DEFAULT_FORMAT = ["layer", "start", "end", "style", "name", "marginl", "marginr",
                       "marginv", "effect", "text"]


def decode_bytes(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", errors="replace")
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return data.decode("utf-32", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:  # необязательная зависимость (приходит вместе с requests)
        import charset_normalizer
        best = charset_normalizer.from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:  # noqa: BLE001 — нет пакета или он не справился
        pass
    return data.decode("cp1252", errors="replace")


def _srt_seconds(h: str, m: str, s: str, frac: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000


def _clean_lines(text: str) -> str:
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    return "\n".join(" ".join(ln.split()) for ln in text.split("\n") if ln.strip())


def parse_srt(text: str) -> list[Cue]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[list] = []          # [start, end, [lines]]
    cur: list | None = None
    for idx, raw in enumerate(lines):
        line = raw.lstrip("﻿")
        m = _SRT_TIME.search(line)
        if m:
            cur = [_srt_seconds(*m.groups()[:4]), _srt_seconds(*m.groups()[4:]), []]
            blocks.append(cur)
            continue
        stripped = line.strip()
        if cur is not None:
            if not stripped:
                cur = None
            elif (stripped.isdigit() and idx + 1 < len(lines)
                  and _SRT_TIME.search(lines[idx + 1])):
                cur = None          # номер следующего блока без пустой строки
            else:
                cur[2].append(line)
        elif blocks and stripped and not stripped.isdigit():
            blocks[-1][2].append(line)  # текст после пустой строки внутри блока
    out = []
    for start, end, body in blocks:
        t = "\n".join(body)
        t = _ASS_TAGS.sub("", t)          # {\an8} внутри SRT
        t = _HTML_TAGS.sub("", t)         # <i>, <font ...>
        t = _clean_lines(html.unescape(t))
        if t:
            out.append(Cue(start, end, t))
    return out


def _ass_seconds(s: str) -> float | None:
    m = _ASS_TIME.search(s)
    if not m:
        return None
    h, mi, sec, frac = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(sec) + float("0." + frac)


def parse_ass(text: str) -> list[Cue]:
    fmt: list[str] | None = None
    in_events = False
    cues: list[Cue] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        low = line[:9].lower()
        if low.startswith("format:"):
            fmt = [f.strip().lower() for f in line[7:].split(",")]
        elif low.startswith("dialogue:"):
            names = fmt or _ASS_DEFAULT_FORMAT
            if "text" not in names:
                continue
            parts = line[9:].lstrip().split(",", len(names) - 1)
            if len(parts) < len(names):
                continue
            row = dict(zip(names, parts))
            start, end = _ass_seconds(row.get("start", "")), _ass_seconds(row.get("end", ""))
            body = row["text"]
            if start is None or end is None or _ASS_DRAWING.search(body):
                continue            # векторная графика, не текст
            body = _clean_lines(_ASS_TAGS.sub("", body))
            if body:
                cues.append(Cue(start, end, body))
    return cues


def parse_subtitles(data: bytes, name: str):
    """(формат, реплики) по расширению и содержимому или None (не субтитры)."""
    text = decode_bytes(data)
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    head = text[:8000].lower()
    if ext in ("ass", "ssa") or "[events]" in head:
        cues = parse_ass(text)
        if cues or ext in ("ass", "ssa"):
            return "ass", cues
    if ext == "srt" or _SRT_TIME.search(text[:20000]):
        return "srt", parse_srt(text)
    return None


# ── Язык ────────────────────────────────────────────────────────────────────
_EN_TOKENS = {"en", "eng", "english", "enus", "engsub", "engsubs"}
_NON_EN_TOKENS = {"ja", "jp", "jpn", "jap", "japanese", "zh", "chi", "chs", "cht", "chinese",
                  "ko", "kor", "korean", "es", "spa", "spanish", "fr", "fre", "fra", "french",
                  "de", "ger", "deu", "german", "pt", "por", "ptbr", "ru", "rus", "russian",
                  "it", "ita", "ar", "ara", "th", "tha", "vi", "vie", "id", "ind"}
_STOP = {"the", "and", "you", "that", "is", "it", "to", "of", "in", "i", "this", "what", "not",
         "are", "was", "have", "with", "for", "do", "he", "she", "we", "they", "my", "your"}
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def filename_says_not_english(name: str) -> bool:
    """В имени файла явная пометка другого языка и нет пометки английского."""
    base = re.split(r"[\\/!]", name)[-1]
    toks = {t for t in re.split(r"[^a-z]+", base.lower()) if t}
    return bool(toks & _NON_EN_TOKENS) and not (toks & _EN_TOKENS)


def is_english(cues: list[Cue], sample: int = 600) -> tuple[bool, str]:
    if not cues:
        return False, "нет реплик"
    step = max(1, len(cues) // sample)
    text = " ".join(c.text for c in cues[::step][:sample])
    cjk = len(_CJK.findall(text))
    latin = [w for w in tokenize(text) if w.isascii()]
    if len(latin) < 20:
        return False, "мало латинского текста"
    if cjk > len(latin):
        return False, "в основном иероглифы"
    frac = sum(1 for w in latin if w in _STOP) / len(latin)
    if frac < 0.10:
        return False, f"не похоже на английский ({frac:.2f})"
    return True, ""


# ── Серия по имени файла ────────────────────────────────────────────────────
_EP_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])S(\d{1,2})[ ._-]?E(\d{1,4})(?![0-9])", re.I),
    re.compile(r"(?<![A-Za-z])(?:episode|ep|e)[ ._-]?(\d{1,4})(?:v\d)?(?![0-9A-Za-z])", re.I),
    re.compile(r"[ _.\]\)]-[ _.]?(\d{1,4})(?:v\d)?(?=[ _.\[\(-]|$)"),
    re.compile(r"[\[\(_ .](\d{2,3})(?:v\d)?[\]\)_ .]"),
]
_NOT_EPISODE = {"264", "265", "480", "720", "360", "128", "192", "256", "320"}


def guess_episode(path: str) -> str:
    """«S01E05», «12» или "" — номер серии из имени файла."""
    base = re.split(r"[\\/!]", path)[-1]
    for pat in _EP_PATTERNS:
        for m in pat.finditer(base):
            groups = m.groups()
            if len(groups) == 2:
                return f"S{int(groups[0]):02d}E{int(groups[1]):02d}"
            if groups[0] not in _NOT_EPISODE:
                return str(int(groups[0])) if groups[0].isdigit() else groups[0]
    return ""
