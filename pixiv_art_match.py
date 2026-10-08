"""Deterministic Pixiv tag checks before optional visual inspection."""
from __future__ import annotations

from pixiv_titles import norm_title


# A short title can also be a character or generic tag. These source tags
# identify works from other media even when that work has an exact title tag.
# Keep this list conservative: only unambiguous franchise markers belong here.
OTHER_SERIES = {
    "MonsterHunter", "モンハン", "モンスターハンター",
    "CHUNITHM", "チュウニズム",
    "BlueArchive", "ブルーアーカイブ", "ブルアカ",
}
OTHER_SERIES = {norm_title(name) for name in OTHER_SERIES}

# Gilgamesh (2003) shares its title with a Fate character. Pixiv also uses
# franchise prefixes in bookmark tags and character tags such as (Fate).
FATE_MARKERS = {norm_title(name) for name in (
    "Fate", "FGO", "Fate/GrandOrder", "FateGrandOrder",
    "Fate/staynight", "Fate/Zero", "フェイト", "フェイトグランドオーダー",
)}


def _fate_tag(tag: str) -> bool:
    return (tag in FATE_MARKERS or tag.startswith(("fate/", "fate／"))
            or "(fate)" in tag or "（fate）" in tag)


def conflicting_series(tags: set[str], own_titles: set[str]) -> bool:
    """Reject a known source franchise unless it is part of the expected title."""
    normalized = {norm_title(tag) for tag in tags}
    own = {norm_title(title) for title in own_titles}
    if any(_fate_tag(tag) for tag in normalized) and not any(
            _fate_tag(title) or title.startswith("fate") for title in own):
        return True
    for brand in normalized & OTHER_SERIES:
        if not any(brand in title for title in own):
            return True
    return False
