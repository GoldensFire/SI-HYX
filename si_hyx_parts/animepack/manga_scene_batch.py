# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Choose several scene alternatives across several pages in one request."""
import base64
import hashlib
import io

from PIL import Image

from .manga_character_crop import SCHEMA, SEND_SIDE, _frame, _prompt, _windows
from .manga_crop import _encode
from .manga_scene_review import check_many
from .manga_visual_check import titles
from .visual_batch import request

MEMO_GROUP = "manga_scene_batch_v1"
MAX_TILES = 24
MAX_CHOICES = 3
CHOICE = dict(SCHEMA, properties={**SCHEMA["properties"],
                                 "page_index": {"type": "integer"}},
              required=[*SCHEMA["required"], "page_index"])
BATCH_SCHEMA = {"type": "object", "properties": {
    "accept": {"type": "boolean"}, "has_title_text": {"type": "boolean"},
    "reason": {"type": "string"}, "candidates": {
        "type": "array", "items": CHOICE, "maxItems": MAX_CHOICES}},
    "required": ["accept", "has_title_text", "reason", "candidates"]}


def crop_pages(generator, cand, pages):
    """Return (selected page index, encoded crop), with at most two AI calls."""
    if not pages or generator.stopped():
        return None
    client = generator.gemini_manga
    if client is None:
        raise RuntimeError("Gemini для выбора сцены с персонажами недоступна")
    names = sorted({name for page in pages for name in page["titles"]})
    prompt = _prompt(cand, names) + (
        " Теперь перед тобой НЕСКОЛЬКО страниц одного произведения. "
        "Каждый фрагмент помечен page_index И tile_index; не смешивай их. "
        "Просмотри ВСЕ страницы за этот запрос и предложи до ТРЁХ разных "
        "пригодных сцен в candidates, лучшие первыми. Каждая сцена — одна "
        "цельная панель по правилам выше. Можно предложить варианты с одной "
        "страницы. У каждого варианта укажи page_index, tile_index, box и "
        "все поля оценки. Если подходящих сцен нет, candidates=[], "
        "accept=false. Это замена формата одиночного ответа выше.")
    parts, windows = [{"type": "text", "text": prompt}], []
    limit = max(1, MAX_TILES // len(pages))
    for index, page in enumerate(pages):
        with Image.open(io.BytesIO(page["data"])) as opened:
            picture = opened.convert("RGB")
        regions = _windows(*picture.size, max_tiles=limit)
        windows.append(regions)
        for tile_index, region in enumerate(regions):
            tile = picture.crop(region)
            tile.thumbnail((SEND_SIDE, SEND_SIDE), Image.Resampling.LANCZOS)
            payload = io.BytesIO()
            tile.save(payload, "JPEG", quality=88)
            parts.extend([{"type": "text", "text": (
                f"page_index={index}, tile_index={tile_index}")},
                {"type": "image", "mime_type": "image/jpeg",
                 "data": base64.b64encode(payload.getvalue()).decode("ascii")}])
        # Keep compressed source bytes, not four decoded long strips at once.
        del picture
    payload = "".join(str(p.get("text") or p.get("data")) for p in parts)
    key = f"{client.model}:{hashlib.sha256(payload.encode()).hexdigest()}"
    response = generator.db_cache.memo(MEMO_GROUP, key)
    if response is None:
        response = request(generator, client, parts, BATCH_SCHEMA)
        if isinstance(response, dict):
            generator.db_cache.remember_memo(MEMO_GROUP, key, response)
    proposals = response.get("candidates") if isinstance(response, dict) else None
    if not isinstance(proposals, list):
        proposals = []
    prepared, seen, failures = [], set(), []
    for proposal in proposals[:MAX_CHOICES]:
        index = proposal.get("page_index") if isinstance(proposal, dict) else None
        if type(index) is not int or not 0 <= index < len(pages):
            continue
        identity = repr((index, proposal.get("tile_index"), proposal.get("box")))
        if identity in seen:
            continue
        seen.add(identity)
        with Image.open(io.BytesIO(pages[index]["data"])) as opened:
            picture = opened.convert("RGB")
        context = []
        frame = _frame(picture, windows[index], proposal, failures, context)
        if frame is not None:
            prepared.append((index, frame, context[0]))
        del picture
    if not prepared:
        reason = failures[0] if failures else str(
            (response or {}).get("reason") if isinstance(response, dict) else "")
        generator._log_rare("Сцена манги", f"«{cand.title_ru}»: пачка из "
                            f"{len(pages)} страниц отклонена: {reason or 'нет цельной сцены'}")
        return None
    expected = " / ".join(titles(cand.anime or {}) + names)
    verdicts = check_many(generator, [(f, c) for _, f, c in prepared], expected)
    for (index, frame, _), (good, _) in zip(prepared, verdicts):
        if good:
            generator.log(f"«{cand.title_ru}»: из {len(pages)} страниц одним "
                          f"запросом выбрано {len(prepared)} вариантов; "
                          "проверены общей пачкой")
            return index, _encode(frame, pages[index]["ext"])
    generator._log_rare("Сцена манги", f"«{cand.title_ru}»: все варианты пачки "
                        f"отклонены проверкой: {verdicts[0][1]}")
    return None
