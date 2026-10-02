"""Stable character identities, including answers in older packs."""
from __future__ import annotations

import json
import re
import unicodedata


def _name(value) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"\w+", value, re.UNICODE))


def character_keys(character, names=()) -> set[tuple]:
    character = character or {}
    keys = set()
    try:
        number = int(character.get("id") or 0)
    except (TypeError, ValueError):
        number = 0
    if number > 0:
        keys.add(("character-id", str(number)))
    variants = [character.get(key) for key in ("name", "russian", "romaji")]
    variants += list(character.get("names") or []) + list(names)
    for variant in variants:
        normalized = _name(variant)
        if normalized:
            keys.add(("character-name", normalized))
    return keys


def stable_keys(keys) -> set[tuple]:
    """An available ID distinguishes unrelated characters sharing a name."""
    if any(key[0] == "character-id" for key in keys):
        return {key for key in keys if key[0] != "character-name"}
    return set(keys)


def manifest_keys(archive) -> tuple[set[tuple], set[tuple]]:
    from .pack_manifest import MANIFEST_NAME
    try:
        if archive.getinfo(MANIFEST_NAME).file_size > 2_000_000:
            return set(), set()
        data = json.loads(archive.read(MANIFEST_NAME))
    except (KeyError, ValueError, UnicodeError):
        return set(), set()
    keys, identified_names = set(), set()
    for row in (data.get("characters") or []) if isinstance(data, dict) else []:
        if isinstance(row, dict):
            identity = character_keys(row)
            stable = stable_keys(identity)
            keys.update(stable)
            identified_names.update(identity - stable)
    return keys, identified_names


def answer_keys(answers, question_texts) -> set[tuple]:
    """Recognize our old title — 『character』 answer without its title."""
    if not answers:
        return set()
    match = re.search(r"\s[—–-]\s*『([^』]+)』\s*$", answers[0])
    task = any("персонаж" in _name(text) for text in question_texts)
    if not match and not task:
        return set()
    # A song uses the same quotes but has its own OP/ED/OST tag.
    if not task and re.search(r"\b(?:OP|ED|OST)\s*\d*\b", answers[0], re.I):
        return set()
    names = [match.group(1)] if match else [answers[0]]
    names += [text for text in answers[1:]
              if not str(text).startswith(("http://", "https://"))]
    return character_keys({}, names)
