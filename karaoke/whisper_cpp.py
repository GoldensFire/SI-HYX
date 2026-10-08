"""Vulkan Whisper CLI adapter retaining real word boundaries in the ASR schema."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import re
import unicodedata


def token_words(tokens):
    """The CLI may put incomplete UTF-8 byte tokens in its JSON strings."""
    words, pending, first, last = [], b"", None, None
    for token in tokens:
        text = token.get("text", "")
        offsets = token.get("offsets", {})
        if text.startswith("[_") or "from" not in offsets or "to" not in offsets:
            continue
        start, end = offsets["from"] / 1000, offsets["to"] / 1000
        if start < 0 or end < start:
            continue
        if pending and start - last > 3:
            pending, first = b"", None
        first = start if first is None else first
        last = end
        pending += text.encode("utf-8", "surrogateescape")
        try:
            text = pending.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if last > first and any(c.isalnum() for c in text):
            latin = all(not c.isalpha() or "LATIN" in unicodedata.name(c, "") for c in text)
            previous_latin = words and all(not c.isalpha() or "LATIN" in unicodedata.name(c, "")
                                           for c in words[-1]["word"])
            if previous_latin and latin and text and not text[0].isspace() and words[-1]["word"][-1:].isalpha():
                words[-1]["word"] += text
                words[-1]["end"] = last
            else:
                words.append({"start": first, "end": last, "word": text})
        pending, first = b"", None
    return words


def rows_from_json(data):
    rows = []
    for segment in data.get("transcription", []):
        if "tokens" in segment:
            words = token_words(segment["tokens"])
            if words:
                rows.append({"start": words[0]["start"], "end": words[-1]["end"],
                             "text": "".join(w["word"] for w in words), "words": words})
            continue
        # Word-sized segments from CLI --max-len 1, for builds without tokens.
        text = segment.get("text", "")
        offsets = segment.get("offsets", {})
        start, end = float(offsets.get("from", -1)) / 1000, float(offsets.get("to", -1)) / 1000
        if start < 0 or end <= start or not any(c.isalnum() for c in text):
            continue
        rows.append({"start": start, "end": end, "text": text,
                     "words": [{"start": start, "end": end, "word": text}]})
    if not rows:
        raise ValueError("whisper.cpp: no timed words")
    return rows


def transcribe(source, language, model="medium"):
    import os
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    from .ai_assets import cpp_binary, cpp_model

    if model != "medium":
        raise ValueError("The bundled Vulkan model is medium multilingual")
    binary, weights = cpp_binary(), cpp_model()
    source = Path(source)
    audio, sr = sf.read(str(source), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != 16000:
        factor = gcd(sr, 16000)
        audio = resample_poly(audio, 16000 // factor, sr // factor)
    mono = source.with_name("whisper-16k.wav")
    sf.write(str(mono), np.asarray(audio), 16000, subtype="PCM_16")
    output = source.with_name("whisper-" + (language or "auto"))
    command = [str(binary), "-m", str(weights), "-f", str(mono), "-l", language or "auto",
               "-ojf", "-of", str(output), "-ml", "1", "-sow", "-bs", "1", "-bo", "1", "-mc", "0",
               "-t", str(max(1, int(os.environ.get('SI_HYX_ML_THREADS', '4'))))]
    # stdout/stderr stay in the cancellable worker's log; inspect GPU activation
    # before accepting the output so a CPU-only binary is retried as CPU int8.
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    log = source.with_name("whisper-cpp.txt")
    with log.open("wb") as stream:
        completed = subprocess.run(command, stdout=stream, stderr=stream, creationflags=flags, check=False)
    diagnostic = log.read_text(encoding="utf-8", errors="replace")
    print(diagnostic[-3500:], flush=True)
    if completed.returncode or "ggml_vulkan" not in diagnostic or not re.search(r"using Vulkan\d* backend", diagnostic):
        raise RuntimeError("whisper.cpp Vulkan unavailable: " + diagnostic[-500:])
    payload = output.with_suffix(".json").read_bytes().decode("utf-8", "surrogateescape")
    return rows_from_json(json.loads(payload))
