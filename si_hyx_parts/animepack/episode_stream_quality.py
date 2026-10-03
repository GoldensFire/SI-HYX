"""Resolve real HLS/DASH variants; player labels are never quality evidence."""
from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from .episode_ru_catalog import get

MIN_HEIGHT = 1080


def attributes(value):
    return {key: quoted or plain for key, quoted, plain in
            re.findall(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', value)}


def hls_variants(text, base):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    audio_groups = {}
    for line in lines:
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = attributes(line.partition(":")[2])
            if attrs.get("TYPE") == "AUDIO":
                audio_groups.setdefault(attrs.get("GROUP-ID"), []).append(line)
    variants = []
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = attributes(line.partition(":")[2])
        size = re.fullmatch(r"(\d+)x(\d+)", attrs.get("RESOLUTION", ""))
        target = next((v for v in lines[index + 1:] if not v.startswith("#")), "")
        if not target:
            continue
        variants.append({"url": urljoin(base, target), "height": int(size[2]) if size else 0,
                         "bandwidth": int(attrs.get("BANDWIDTH") or 0),
                         "audio_group": audio_groups.get(attrs.get("AUDIO"), []), "tag": line})
    return sorted(variants, key=lambda v: (-v["height"], -v["bandwidth"]))


def selected_hls(variant, base):
    """Retain external audio when restricting a master to one video rendition."""
    audio = [re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + urljoin(base, m[1]) + '"', line)
             for line in variant["audio_group"]]
    return "\n".join(["#EXTM3U", *audio, variant["tag"], variant["url"], ""])


def dash_variant(text, base):
    root = ET.fromstring(text)
    ns = "{urn:mpeg:dash:schema:mpd:2011}"
    heights = []
    for adaptation in root.iter(ns + "AdaptationSet"):
        for representation in adaptation.findall(ns + "Representation"):
            height = int(representation.get("height", adaptation.get("height", "0")))
            if height:
                heights.append((height, int(representation.get("bandwidth", "0")), representation.get("id")))
    if not heights:
        return None
    height, bandwidth, ident = max(heights)
    if height < MIN_HEIGHT:
        return {"height": height, "bandwidth": bandwidth}
    chosen = deepcopy(root)
    for adaptation in list(chosen.iter(ns + "AdaptationSet")):
        for representation in list(adaptation.findall(ns + "Representation")):
            h = int(representation.get("height", adaptation.get("height", "0")))
            if h and representation.get("id") != ident:
                adaptation.remove(representation)
        if not adaptation.findall(ns + "Representation") and adaptation.get("contentType") == "video":
            for period in chosen.iter(ns + "Period"):
                if adaptation in list(period):
                    period.remove(adaptation)
    # Root BaseURL must remain remote when FFmpeg reads our restricted MPD.
    first = chosen.find(ns + "BaseURL")
    if first is not None and first.text:
        first.text = urljoin(base, first.text)
    else:
        first = ET.Element(ns + "BaseURL")
        first.text = urljoin(base, ".")
        chosen.insert(0, first)
    return {"height": height, "bandwidth": bandwidth,
            "manifest": ET.tostring(chosen, encoding="unicode")}


async def variants(stream):
    """Media playlists and MP4 need ffprobe. Unknown quality remains unknown."""
    if stream["type"] not in ("hls", "dash"):
        return [dict(stream)]
    from .episode_media import request_headers
    response = await get(stream["url"], headers=request_headers(stream))
    base = str(response.url)
    if stream["type"] == "dash":
        selected = dash_variant(response.text, base)
        if selected is None:
            return [dict(stream)]
        return [{**stream, "manifest_height": selected["height"],
                 "bandwidth": selected["bandwidth"], "manifest": selected.get("manifest")}]
    rows = hls_variants(response.text, base)
    if not rows:
        return [dict(stream)]
    return [{**stream, "url": row["url"] if not row["audio_group"] else base,
             "manifest": selected_hls(row, base) if row["audio_group"] else None,
             "manifest_height": row["height"], "bandwidth": row["bandwidth"]}
            for row in rows if not row["height"] or row["height"] >= MIN_HEIGHT]
