# -*- coding: utf-8 -*-
"""Conservative comparison of OCR lines with actual catalogue title variants."""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz


def titles(card: dict, manga_titles=()) -> list[str]:
    out, seen = [], set()
    values = (card.get("russian"), card.get("name"), card.get("english"),
              card.get("japanese"), *(card.get("synonyms") or []), *manga_titles)
    for value in values:
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            name = " ".join(str(item or "").split())
            if name and name.casefold() not in seen:
                out.append(name)
                seen.add(name.casefold())
    return out


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = value.replace("ё", "е")
    # OCR often inserts separators in display lettering: N-A-N-A, N | A | N | A.
    value = re.sub(r"(?<=\w)[|·•_~—–-](?=\w)", "", value)
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def _candidates(rows: list[dict]):
    for start in range(len(rows)):
        for end in range(start + 1, min(start + 4, len(rows)) + 1):
            group = rows[start:end]
            if any(row.get("model") != group[0].get("model") for row in group):
                break
            yield " ".join(str(row.get("text") or "") for row in group), min(
                float(row.get("confidence") or 0) for row in group)


def decide(rows: list[dict], variants: list[str]) -> dict:
    """Return title/safe/uncertain; short titles require an exact full crop."""
    best = {"status": "safe", "similarity": 0.0, "confidence": 0.0,
            "ocr": "", "title": ""}
    normalized = [(title, normalize(title)) for title in variants]
    for raw, confidence in _candidates(rows):
        found = normalize(raw)
        compact = found.replace(" ", "")
        if not compact:
            continue
        for title, wanted in normalized:
            target = wanted.replace(" ", "")
            if not target:
                continue
            length = len(target)
            exact = found == wanted or compact == target
            # A one-letter title or a number occurs frequently in dialogue.
            # Require a clean standalone crop; ask Gemini when available.
            if length <= 3:
                status = "uncertain" if exact else "safe"
                score = 100.0 if exact else 0.0
            elif length == 4:
                status = ("title" if exact and confidence >= .93 else
                          "uncertain" if exact else "safe")
                score = 100.0 if exact else 0.0
            else:
                score = max(fuzz.ratio(compact, target),
                            fuzz.ratio(found, wanted))
                # A title embedded in a larger OCR line is common on covers.
                if re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", found):
                    score = 100.0
                strong = 94 if length < 9 else 90
                border = 86 if length < 9 else 82
                status = ("title" if score >= strong and confidence >= .75
                          else "uncertain" if score >= border else "safe")
            rank = {"safe": 0, "uncertain": 1, "title": 2}
            if (rank[status], score * confidence) > (rank[best["status"]],
                                                       best["similarity"] * best["confidence"]):
                best = {"status": status, "similarity": round(score, 1),
                        "confidence": round(confidence, 3), "ocr": raw,
                        "title": title}
    if best["status"] == "safe" and rows:
        # Text was detected, but both recognizers struggled. A stylized logo
        # deserves the existing visual model rather than a confident pass.
        crops = {}
        for row in rows:
            crop = row.get("crop", id(row))
            old = crops.get(crop, (0.0, 0.0))
            crops[crop] = (max(old[0], float(row.get("det_score") or 0)),
                           max(old[1], float(row.get("confidence") or 0)))
        if any(det >= .5 and rec < .45 for det, rec in crops.values()):
            best["status"] = "uncertain"
    return best
