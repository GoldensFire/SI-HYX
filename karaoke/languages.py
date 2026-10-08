"""Rank languages from original lyrics only; unknown text uses Whisper auto."""
from __future__ import annotations

from collections import Counter

# Whisper's multilingual medium language tokens, including aliases from langid.
SUPPORTED = set("en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue".split())
ALIASES = {"nb": "no", "jv": "jw"}


def _script(char):
    number = ord(char)
    if 0x3040 <= number <= 0x30ff or 0x31f0 <= number <= 0x31ff:
        return "ja"
    if 0x3400 <= number <= 0x9fff:
        return "han"
    if 0xac00 <= number <= 0xd7af or 0x1100 <= number <= 0x11ff:
        return "ko"
    return "other"


def rank(original, classify):
    """Weight script spans, not whole mixed lines mislabeled as one language."""
    votes = Counter()
    japanese = any(_script(c) == "ja" for line in original for c in line)
    remainder = []
    for line in original:
        other = []
        for char in line:
            script = _script(char)
            language = "ja" if script == "han" and japanese else "zh" if script == "han" else script
            if language in ("ja", "zh", "ko"):
                votes[language] += 1
                other.append("\n")
            else:
                other.append(char)
        remainder.append("".join(other))
    # The full non-CJK corpus stabilizes short monolingual English lines.
    whole = "\n".join(remainder)
    dominant, confidence = classify(whole) if any(c.isalpha() for c in whole) else (None, 0)
    if confidence < .9:
        dominant = None
    for text in remainder:
        for span in text.split("\n"):
            size = sum(c.isalpha() for c in span)
            if not size:
                continue
            language, probability = classify(span)
            if size < 12 or probability < .95:
                language = dominant
            # Small interjections and English inserts in Japanese lyrics often
            # get a confidently wrong langid label (br/sw/fr). Require enough
            # independent prose for a second non-English language.
            if japanese and language != "en" and (size < 40 or confidence < .99):
                language = None
            language = ALIASES.get(language, language)
            if language in SUPPORTED:
                votes[language] += size
    if not votes:
        return [None]
    ordered = votes.most_common(2)
    result = [ordered[0][0]]
    if len(ordered) > 1 and ordered[1][1] >= 12 and ordered[1][1] / sum(votes.values()) >= .1:
        result.append(ordered[1][0])
    return result


def detect(original):
    from langid.langid import LanguageIdentifier, model
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    return rank(original, identifier.classify)


def lyric_languages(python, original, work, *, stopped, log):
    import json
    from chiptune.runtime import run_process
    from .ai_runtime import ensure_packages
    from .recognition import WORKER
    try:
        ensure_packages(python, ["langid"], ["langid==1.1.6"], stopped=stopped, log=log)
        source, target = work / "original.json", work / "languages.json"
        source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        code, output = run_process([str(python), "-I", "-X", "utf8", str(WORKER),
                                   "languages", str(source), str(target)], 60, stopped=stopped)
        if code:
            raise ValueError(output[-300:])
        return json.loads(target.read_text(encoding="utf-8"))
    except (RuntimeError, ValueError, OSError) as error:
        if stopped():
            raise RuntimeError("Караоке: остановлено.") from error
        log("Караоке: язык текста не определён; Whisper определит язык по вокалу.")
        return [None]
