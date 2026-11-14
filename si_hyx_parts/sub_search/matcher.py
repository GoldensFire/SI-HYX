# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Поиск фразы по репликам субтитров.

Фраза ищется по потоку слов, а не по строкам: пунктуация, переносы строк и
границы соседних блоков не мешают совпадению («Six...\\Nseven», «six, seven»,
«six-seven», «Six?» в одном блоке и «Seven!» в следующем). «sixty seven» и
«six sevenths» не совпадают — сравниваются целые слова.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Слово — буквы/цифры (Unicode), внутри допускается апостроф: don't.
_TOKEN_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'"})


@dataclass
class Cue:
    start: float
    end: float
    text: str          # чистый текст; переносы строк внутри реплики — "\n"


@dataclass
class Match:
    start: float
    end: float
    text: str          # реплика(и), в которых найдено совпадение
    matched: str       # найденный фрагмент, как он написан в субтитрах
    kind: str          # same_line | line_break | cross_block


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_APOSTROPHES)
    return s.replace("­", "")  # мягкий перенос


def tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(normalize_text(s))]


def may_contain(blob_lower: str, tokens) -> bool:
    """Быстрая предпроверка по сырому тексту файла (в нижнем регистре): все ли
    слова фразы там вообще встречаются. Ложных «нет» не бывает, поэтому
    дорогой разбор реплик идёт только для файлов, где фраза возможна."""
    return all(t in blob_lower for t in tokens)


def _flat(s: str) -> str:
    return " ".join(s.split())


def prepare_cues(cues: list[Cue]) -> list[Cue]:
    """Сортировка по времени и удаление дублей (ASS часто содержит копии реплик
    на разных слоях)."""
    seen: set = set()
    out: list[Cue] = []
    for c in sorted(cues, key=lambda c: (c.start, c.end)):
        key = (round(c.start, 2), round(c.end, 2), _flat(normalize_text(c.text)).lower())
        if key in seen or not key[2]:
            continue
        seen.add(key)
        out.append(c)
    return out


def format_timecode(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _join_text(s: str) -> str:
    return " / ".join(part.strip() for part in s.split("\n") if part.strip())


def find_phrase(cues: list[Cue], phrase: str, max_gap: float = 3.0,
                limit: int = 0) -> list[Match]:
    """Все непересекающиеся вхождения `phrase` (limit > 0 — не больше стольких).

    max_gap — наибольшая пауза (с) между соседними блоками, при которой фраза
    считается разорванной между ними, а не двумя несвязанными репликами."""
    want = tokenize(phrase)
    if not want:
        raise ValueError("пустая фраза для поиска")
    n = len(want)
    cues = prepare_cues(cues)

    # (слово, индекс реплики, индекс строки в реплике, начало, конец в норм. тексте)
    stream: list[tuple[str, int, int, int, int]] = []
    norms: list[str] = []
    for ci, cue in enumerate(cues):
        norm = normalize_text(cue.text)
        norms.append(norm)
        for m in _TOKEN_RE.finditer(norm):
            stream.append((m.group().lower(), ci, norm.count("\n", 0, m.start()),
                           m.start(), m.end()))

    matches: list[Match] = []
    first = want[0]
    i = 0
    while i + n <= len(stream):
        if stream[i][0] != first:
            i += 1
            continue
        window = stream[i:i + n]
        if [w[0] for w in window] != want:
            i += 1
            continue
        if any(a[1] != b[1] and cues[b[1]].start - cues[a[1]].end > max_gap
               for a, b in zip(window, window[1:])):
            i += 1
            continue
        involved: list[int] = []
        for w in window:
            if w[1] not in involved:
                involved.append(w[1])
        if len(involved) > 1:
            kind = "cross_block"
        elif len({w[2] for w in window}) > 1:
            kind = "line_break"
        else:
            kind = "same_line"
        pieces = []
        for ci in involved:
            toks = [w for w in window if w[1] == ci]
            pieces.append(_flat(norms[ci][toks[0][3]:toks[-1][4]]))
        matches.append(Match(
            start=cues[involved[0]].start,
            end=cues[involved[-1]].end,
            text=" || ".join(_join_text(norms[ci]) for ci in involved),
            matched=" || ".join(pieces),
            kind=kind,
        ))
        if limit and len(matches) >= limit:
            break
        i += n
    return matches
