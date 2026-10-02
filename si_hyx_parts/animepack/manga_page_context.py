# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Join neighboring webtoon chunks so a source seam cannot cut a face."""
import io

from PIL import Image


def is_webtoon(cand):
    return str((cand.anime or {}).get("kind") or "").lower() in ("manhwa", "manhua")


def download(generator, cand, url, *, cache=None):
    cand._manga_context_urls = [url]
    client = getattr(cand, "_manga_page_client", None)
    info = getattr(cand, "_manga_page_info", {})
    def fetch(address, metadata):
        if cache is not None and address in cache:
            return cache[address]
        if client is None:
            result = (generator._get_bytes(address), generator._url_ext(address, ".png"))
        else:
            result = client.download_page(address, metadata)
        if cache is not None:
            cache[address] = result
        return result

    data, ext = fetch(url, info)
    if not is_webtoon(cand):
        return data, ext
    with Image.open(io.BytesIO(data)) as opened:
        middle = opened.convert("RGB")
    neighbors = info.get("neighbors") or []
    pictures = {0: middle}
    for row in neighbors:
        if generator.stopped():
            return data, ext
        offset, address = row.get("offset"), row.get("url")
        if offset not in (-1, 1) or not address:
            continue
        with generator._frames_lock:
            # History excludes primary question pages, not the context needed
            # to finish a bubble at a file seam. Skipping a used neighbor can
            # leave a newly selected page with half a sentence at its edge.
            generator._frames_used.add(address.split("?")[0])
        try:
            payload, _ = fetch(address, row)
            with Image.open(io.BytesIO(payload)) as opened:
                neighbor = opened.convert("RGB")
            # Different-sized book spreads are separate pages, not webtoon seams.
            if abs(neighbor.width / middle.width - 1) > .15:
                continue
            if neighbor.width != middle.width:
                neighbor = neighbor.resize((middle.width,
                    round(neighbor.height * middle.width / neighbor.width)),
                    Image.Resampling.LANCZOS)
            if neighbor.height > middle.width * 5:
                edge = middle.width * 3
                neighbor = neighbor.crop((0, neighbor.height - edge if offset < 0 else 0,
                                          neighbor.width,
                                          neighbor.height if offset < 0 else edge))
            pictures[offset] = neighbor
            cand._manga_context_urls.append(address)
        except Exception as exc:
            generator._log_rare("Соседняя страница манги",
                                f"«{cand.title_ru}»: соседний фрагмент недоступен: {exc}")
    if len(pictures) == 1:
        return data, ext
    strip = Image.new("RGB", (middle.width, sum(p.height for p in pictures.values())))
    top = 0
    for _, picture in sorted(pictures.items()):
        strip.paste(picture, (0, top))
        top += picture.height
    output = io.BytesIO()
    strip.save(output, "PNG")
    return output.getvalue(), ".png"
