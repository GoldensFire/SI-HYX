# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Короткие проверяемые диалоги: разбор субтитров и общие проверки реплик."""
from __future__ import annotations

import html
import re

import animepack as _api


_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
_TAG = re.compile(r"\{[^}]*\}|<[^>]*>")
_SPACE = re.compile(r"\s+")
_BAD = re.compile(
    r"(?:https?://|www\.|subtitle|subbed\s+by|translated\s+by|not\s+for\s+sale|"
    r"do\s+not\s+distribute|перевод|тайминг|редактор|фансаб|субтитр|"
    r"официальн\w*\s+аккаунт|подпишит|только\s+для\s+уч[её]б|"
    r"коммерческ\w*\s+(?:использован\w*\s+)?запрещ|wechat|kamigami|"
    r"字幕组|仅供|严禁|opening|ending|karaoke|♪|♫|\b(?:op|ed)\s*\d*\b)",
    re.IGNORECASE)
_COLON_PREFIX = re.compile(r"^(.{1,32}?)[：:]\s*(.+)$", re.DOTALL)
_SENTENCE = re.compile(
    r"^(.+?[.!?…。！？]+(?:[\"'»”’\)\]]*)?)(?:\s+|$)", re.DOTALL)
_PREFIX_WORDS = {"почему", "зачем", "когда", "где", "что", "ответ",
                 "вопрос", "итак", "например"}


def _seconds(value: str) -> float:
    match = _TIME.search(str(value or ""))
    if not match:
        return 0.0
    h, m, s, frac = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / (10 ** len(frac))


def _clean(text: str) -> str:
    value = html.unescape(str(text or "")).replace("\\N", "\n").replace("\\n", "\n")
    value = _TAG.sub("", value)
    lines = [_SPACE.sub(" ", line).strip(" -–—") for line in value.splitlines()]
    return _strip_speaker(" ".join(line for line in lines if line))


def _strip_speaker(text: str) -> str:
    """Убрать метку говорящего, но не обычное предложение с двоеточием."""
    value = str(text or "").strip()
    match = _COLON_PREFIX.match(value)
    if not match:
        return value
    prefix, body = match.groups()
    bare = prefix.strip().strip("[]()【】").strip()
    words = re.findall(r"[^\W\d_]+", bare, re.UNICODE)
    bracketed = prefix.strip()[:1] in "[（(【"
    uppercase = len("".join(words)) >= 2 and bare.upper() == bare
    titled = (1 <= len(words) <= 3 and bare.casefold() not in _PREFIX_WORDS
              and all(word[:1].isupper() for word in words))
    return body.strip() if bracketed or uppercase or titled else value


def _decode(data: bytes) -> str:
    encodings = (["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff"))
                 else []) + ["utf-8-sig", "cp932", "cp1251"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        at = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if at < 0:
            continue
        left, right = lines[at].split("-->", 1)
        body = _clean("\n".join(lines[at + 1:]))
        if body:
            cues.append((_seconds(left), _seconds(right), body))
    return cues


def _ass(text: str) -> list[tuple[float, float, str]]:
    cues = []
    fields = ["layer", "start", "end", "style", "name", "marginl",
              "marginr", "marginv", "effect", "text"]
    in_events = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.casefold() == "[events]":
            in_events = True
            continue
        if in_events and line.startswith("["):
            in_events = False
        if in_events and line.casefold().startswith("format:"):
            fields = [part.strip().casefold() for part in line.split(":", 1)[1].split(",")]
            continue
        if not in_events or not line.casefold().startswith("dialogue:"):
            continue
        values = line.split(":", 1)[1].split(",", max(0, len(fields) - 1))
        if len(values) != len(fields):
            continue
        row = dict(zip(fields, values))
        body = _clean(row.get("text", ""))
        if body:
            cues.append((_seconds(row.get("start", "")),
                         _seconds(row.get("end", "")), body))
    return cues


def parse_subtitles(data: bytes, name: str) -> list[tuple[float, float, str]]:
    text = _decode(bytes(data or b""))
    return _ass(text) if str(name).casefold().endswith((".ass", ".ssa")) else _srt(text)


def _name_leak(lines: list[str], names) -> bool:
    joined = " ".join(lines).casefold()
    for name in names or ():
        value = str(name or "").strip().casefold()
        if len(value) >= 4 and value in joined:
            return True
    return False


_api._dialogue_name_leak = _name_leak


def _starts_sentence(text: str) -> bool:
    value = str(text or "").lstrip(" -–—\"'«„([{【")
    if not value:
        return False
    char = value[0]
    return char.isalpha() and not char.islower()


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?…。！？]+[\"'»”’\)\]]*$", str(text or "").strip()))


def _sentence_rows(cues) -> list[tuple[float, float, str]]:
    """Склеить нарезанные субтитры и оставить только целые предложения."""
    result = []
    buffer = ""
    sentence_start = 0.0
    previous_end = None
    for start, end, raw in cues:
        text = _clean(raw)
        separated = previous_end is not None and start - previous_end > 2.5
        if separated:
            buffer = ""                 # незаконченный хвост не используем
        if not text or _BAD.search(text):
            buffer = ""
            previous_end = end
            continue
        if not buffer:
            if not _starts_sentence(text):
                previous_end = end
                continue
            sentence_start = start
        buffer = _SPACE.sub(" ", f"{buffer} {text}").strip()
        while True:
            match = _SENTENCE.match(buffer)
            if not match:
                break
            sentence = match.group(1).strip()
            buffer = buffer[match.end():].strip()
            if 8 <= len(sentence) <= 180 and not _BAD.search(sentence):
                result.append((sentence_start, end, sentence))
            sentence_start = start
        if len(buffer) > 220:
            buffer = ""                 # явно потерянное начало/конец фразы
        previous_end = end
    return result


def dialogue_text(lines: list[str]) -> str:
    return "\n".join(f"— {line}" for line in lines)


for _fn in (parse_subtitles, dialogue_text):
    _fn.__module__ = _api.__name__
    setattr(_api, _fn.__name__, _fn)
