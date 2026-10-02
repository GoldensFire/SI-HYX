"""Provider VTT chapter timings for opening/ending exclusion."""
import re

from ._http import fetch_text


def seconds(value):
    try:
        parts = [float(piece) for piece in value.strip().split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        pass
    return 0


def parse(text):
    out = {}
    for block in re.split(r"\r?\n\s*\r?\n", text):
        match = re.search(r"([\d:.]+)\s*-->\s*([\d:.]+)[^\n]*\n([^\n]+)", block)
        if not match:
            continue
        start, end, label = match.groups()
        key = ("intro" if re.search(r"\b(?:opening|intro|op)\b", label, re.I)
               else "outro" if re.search(r"\b(?:ending|outro|ed)\b", label, re.I) else "")
        if key and seconds(end) > seconds(start):
            out[key] = {"start": seconds(start), "end": seconds(end)}
    return out


async def timings(stream, headers):
    url = stream.get("chapters")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return {}
    try:
        return parse(await fetch_text(url, headers, timeout=10))
    except Exception:
        return {}
