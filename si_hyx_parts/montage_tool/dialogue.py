# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Реплики серий: расшифровка при index --speech и поиск фразы (lines).
Public namespace: montage_tool.

Звук серии целиком (16 кГц моно) → Whisper (karaoke/asr_worker.py в Python
генератора, как analyze --kinds word) → слова со временем → реплики: новая
реплика — после паузы длиннее LINE_GAP_S, после конца предложения или через
LINE_MAX_WORDS слов. Реплики и слова — в каталоге (speech_lines, SQLite).

Поиск — rapidfuzz по нормализованному тексту (регистр, знаки): каждая
реплика и пара соседних (фраза бывает разрезана паузой); у найденной —
время, слова, планы каталога под ней. Голос без музыки — edit op voice
(clean: true) по file/t0/t1 найденной реплики."""
import json
import re

import montage_tool as _api
from si_hyx_parts.montage_tool import analysis as _an

LINE_GAP_S = 0.7
LINE_MAX_WORDS = 16
DEFAULT_SPEECH_MODEL = "small"
_NORM_RX = re.compile(r"[^\w]+")
_END_RX = re.compile(r"[.!?…。！？]$")


def _norm(text):
    return _NORM_RX.sub(" ", str(text).lower()).strip()


def group_lines(words):
    """[(t0, t1, текст, [[t, end, слово], …])] из слов [(t, end, слово)]."""
    lines, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] > LINE_GAP_S or len(cur) >= LINE_MAX_WORDS
                    or _END_RX.search(cur[-1][2])):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [(ln[0][0], ln[-1][1], " ".join(x[2] for x in ln),
             [[round(a, 3), round(b, 3), t] for a, b, t in ln]) for ln in lines]


def transcribe_file(con, fid, path, ctl=None, model=DEFAULT_SPEECH_MODEL, language="auto",
                    python=""):
    """Реплики файла в каталог (прежние — заменяются). Число реплик."""
    ctl = ctl or _api.NO_CONTROL
    ctl.stage("speech", path=path, model=model)
    x = _an.file_audio(path)
    if not len(x):
        return 0
    tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_lines_")
    try:
        wav = _api.os.path.join(tmpdir, "audio.wav")
        _an._write_wav(x, wav, _an.SR)
        words = _an.transcribe_words(wav, python, language, model)
    finally:
        _api.shutil.rmtree(tmpdir, ignore_errors=True)
    lines = group_lines(words)
    with con:
        con.execute("DELETE FROM speech_lines WHERE file_id=?", (fid,))
        con.executemany("INSERT INTO speech_lines(file_id, t0, t1, text, words, model) "
                        "VALUES (?,?,?,?,?,?)",
                        [(fid, round(a, 3), round(b, 3), text, json.dumps(ws, ensure_ascii=False),
                          model) for a, b, text, ws in lines])
    return len(lines)


def find_lines(db=None, say="", file="", limit=20, min_score=0.6):
    """Реплики каталога, похожие на фразу say (лучшие — первыми)."""
    from rapidfuzz import fuzz
    query = _norm(say)
    if not query:
        raise _api.ToolError("usage", "lines: нужна фраза --say")
    con = _api.connect(db)
    try:
        sql = ("SELECT l.*, f.path FROM speech_lines l JOIN files f ON f.id=l.file_id"
               + (" WHERE LOWER(f.path) LIKE ?" if file else "") + " ORDER BY l.file_id, l.t0")
        rows = con.execute(sql, ["%" + str(file).lower() + "%"] if file else []).fetchall()
        found = []
        for i, r in enumerate(rows):
            spans = [(r,)]
            if i + 1 < len(rows) and rows[i + 1]["file_id"] == r["file_id"] \
                    and rows[i + 1]["t0"] - r["t1"] < 2.0:
                spans.append((r, rows[i + 1]))
            for span in spans:
                text = " ".join(x["text"] for x in span)
                norm = _norm(text)
                # Фраза внутри реплики — partial_ratio; реплика короче фразы
                # («Yes?» против длинной фразы) — обычное сходство целиком.
                if len(norm) < 0.8 * len(query):
                    score = fuzz.ratio(query, norm) / 100.0
                else:
                    score = fuzz.partial_ratio(query, norm) / 100.0
                if score >= min_score:
                    words = [w for x in span for w in json.loads(x["words"] or "[]")]
                    found.append({"file": r["path"], "file_id": r["file_id"],
                                  "t0": span[0]["t0"], "t1": span[-1]["t1"], "text": text,
                                  "score": round(score, 3), "words": words})
        found.sort(key=lambda x: (-x["score"], x["t1"] - x["t0"]))
        best = []
        for f in found:
            # Пара реплик, где уже нашлась одна из них, — та же находка.
            if any(b["file_id"] == f["file_id"] and b["t0"] < f["t1"] and f["t0"] < b["t1"]
                   for b in best):
                continue
            shots = con.execute("SELECT id FROM shots WHERE file_id=? AND t1>? AND t0<? "
                                "ORDER BY t0", (f["file_id"], f["t0"], f["t1"])).fetchall()
            f["shots"] = [s["id"] for s in shots]
            best.append(f)
            if len(best) >= limit:
                break
        total = con.execute("SELECT COUNT(*) FROM speech_lines").fetchone()[0]
        return {"db": _api.os.path.abspath(str(db or _api.default_db())), "lines_total": total,
                "found": best}
    finally:
        con.close()
