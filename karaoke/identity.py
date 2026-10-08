"""Exact identities and explicit recording editions for the paired lyric path."""
import re
import unicodedata

from .model import normalize

_VERSION = re.compile(
    r"(?:[（(\[~～\-]\s*)?\b(tv[ ._-]*(?:size|ver(?:sion)?)|"
    r"full[ ._-]*(?:size|ver(?:sion)?)|live|remix|acoustic|cover|karaoke|acapella|instrumental|"
    r"off[ ._-]*vocal|remaster(?:ed)?|album[ ._-]*ver(?:sion)?)\b.*$", re.I)


def identity_key(value):
    # NFKD + dropping marks would collapse が into か and change a JP identity.
    return "".join(char for char in unicodedata.normalize("NFKC", str(value)).casefold()
                   if char.isalnum())


def edition(title):
    match = _VERSION.search(str(title))
    if not match or match.start() == 0:
        return ""
    value = normalize(match[1])
    if value.startswith("tv"):
        return "tv"
    if value.startswith("full"):
        return "full"
    return value


def base_title(title):
    return identity_key(_VERSION.sub("", str(title)).strip() if edition(title) else title)


def title_variants(value):
    # Global displays native title followed by a machine romanization in ().
    variants = [str(value)]
    match = re.fullmatch(r"(.+?)[（(]([^()（）]+)[）)]", str(value).strip())
    if match and not edition(value):
        variants.extend(match.groups())
    return variants


def exact_identity(title, artist, actual_title, actual_artist, context=None):
    info = context or {}
    titles = [title, *info.get("titles", [])]
    artists = [artist, *info.get("artists", [])]
    # Only explicitly supplied performer aliases count; no fuzzy/substring match.
    singer = identity_key(actual_artist)
    return bool(singer and singer in {identity_key(a) for a in artists}
                and any(base_title(wanted) and base_title(wanted) == base_title(actual)
                        for wanted in titles for actual in title_variants(actual_title)))


def recording_matches(title, duration, candidate):
    version = edition(candidate.title)
    requested = edition(title)
    if version and ((requested and version != requested)
                    or (not requested and version not in ("tv", "full"))):
        return False
    # Unknown duration cannot establish that the timing clock belongs to this edit.
    return candidate.duration > 0 and abs(candidate.duration - duration) <= 2.5
