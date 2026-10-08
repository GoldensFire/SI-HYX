# -*- coding: utf-8 -*-
"""Одинаковая песня с тем же исполнителем у нескольких аниме."""
from __future__ import annotations

import io
import threading
import time

import animepack as _api


MAX_TITLES = 3


def enrich(generator, cand) -> None:
    """Находит другие франшизы с буквально той же песней и исполнителем."""
    if cand.is_silent or not cand.song_name or not cand.artist:
        return
    ask = getattr(generator.anisong, "songs_by_name_artist", None)
    if not callable(ask):
        return
    key = _song_key(cand.song_name, cand.artist)
    rows = generator.db_cache.memo("same_song_anime_v1", key)
    if rows is None:
        rows = _ask(generator, cand, ask, key)
    primary_id = cand.mal_id
    by_id = {}
    for row in rows or []:
        mal = _mal(row)
        if mal and mal != primary_id:
            by_id.setdefault(mal, row)
    if not by_id:
        return
    try:
        from .song_optional_catalog import cards as optional_cards
        cards = optional_cards(generator, list(by_id)[:50])
    except _api.AnimePackApiError as exc:
        generator._log_rare("Одинаковые песни",
                            f"Shikimori: тайтлы одинаковой песни не загружены: {exc}")
        return
    own = _franchise(cand.anime)
    seen = {own}
    alternates = []
    for card in cards:
        mal = _card_mal(card)
        branch = _franchise(card)
        # Повторное использование внутри одной франшизы не превращаем в
        # отдельный ответ: OP сериала в рекапе или фильме остаётся OP сериала.
        if not mal or mal not in by_id or not branch or branch in seen:
            continue
        seen.add(branch)
        alternates.append({"anime": card, "song": by_id[mal]})
        if len(alternates) >= MAX_TITLES - 1:
            break
    cand.song_alternates = alternates


_ASKING = threading.Lock()


def _ask(generator, cand, ask, key) -> list:
    """Один запрос обогащения за раз; при сбое и паузе — локальный снимок.

    Восемь потоков спрашивали AnisongDB одновременно: пауза после 503
    ставилась, когда соседние запросы уже ушли и тоже получали 503."""
    if not _ASKING.acquire(timeout=5):
        return _snapshot(generator, cand)
    try:
        rows = generator.db_cache.memo("same_song_anime_v1", key)
        if rows is not None:
            return rows
        if time.monotonic() < getattr(generator, "_same_song_retry_at", 0):
            return _snapshot(generator, cand)
        try:
            rows = ask(cand.song_name, cand.artist)
        except _api.AnimePackApiError as exc:
            # Optional enrichment must not retry an unavailable endpoint for
            # every distinct song. Keep failures transient and retry later.
            generator._same_song_retry_at = time.monotonic() + 120
            generator._log_rare("Одинаковые песни",
                                f"AnisongDB: одинаковые песни не проверены: {exc}")
            return _snapshot(generator, cand)
        rows = [row for row in (rows or []) if _same(row, cand)]
        generator.db_cache.remember_memo("same_song_anime_v1", key, rows)
        return rows
    finally:
        _ASKING.release()


def _snapshot(generator, cand) -> list:
    """Строки той же песни из сохранённого каталога; в memo не пишутся."""
    local = getattr(generator.anisong, "songs_by_name_artist_snapshot", None)
    if not callable(local):
        return []
    return [row for row in local(cand.song_name) if _same(row, cand)]


def join_posters(generator, cand, primary_data: bytes, primary_ext: str) -> None:
    """Склеивает постеры показанных тайтлов; недоступные удаляет из ответа."""
    if not cand.song_alternates or not primary_data:
        return
    from PIL import Image

    try:
        primary = Image.open(io.BytesIO(primary_data)).convert("RGB")
        primary.load()
    except Exception:  # noqa: BLE001
        cand.song_alternates = []
        return
    images = [primary]
    kept = []
    for row in cand.song_alternates:
        card = row.get("anime") or {}
        probe = _api.SongCandidate({}, card)
        poster = card.get("poster") or {}
        url = str(poster.get("originalUrl") or poster.get("mainUrl") or "")
        data, _ext = generator._poster_bytes(probe, url)
        if not data:
            continue
        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
            image.load()
        except Exception:  # noqa: BLE001
            continue
        images.append(image)
        kept.append(row)
    cand.song_alternates = kept
    if len(images) < 2:
        return
    height = max(image.height for image in images)
    ready = [image.resize(
        (max(1, round(image.width * height / max(1, image.height))), height),
        Image.Resampling.LANCZOS) for image in images]
    strip = Image.new("RGB", (sum(image.width for image in ready), height),
                      "black")
    x = 0
    for image in ready:
        strip.paste(image, (x, 0))
        x += image.width
    buf = io.BytesIO()
    strip.save(buf, "PNG")
    name = generator._save_reusable_image(
        buf.getvalue(), f"{cand.file_base}_posters", ".png")
    if name:
        cand.poster_name = name
        cand.has_poster = True


def song_hint(cand) -> str:
    """Все типы применения композиции, перечисленные в ответе вопроса."""
    kinds = {cand.base_kind}
    kinds.update(_api.song_kind((row.get("song") or {}).get("songType"))
                 for row in cand.song_alternates)
    labels = [_api.HINT_LABELS[kind] for kind in _api.SONG_KINDS if kind in kinds]
    return "/".join(labels) or _api.KIND_TITLES.get(cand.base_kind, cand.base_kind)


def _song_key(name: str, artist: str) -> str:
    return "|".join(" ".join(str(value).casefold().split())
                    for value in (name, artist))


def _same(row: dict, cand) -> bool:
    return (_song_key(row.get("songName"), row.get("songArtist"))
            == _song_key(cand.song_name, cand.artist))


def _mal(row: dict) -> int:
    try:
        return int((row.get("linked_ids") or {}).get("myanimelist") or 0)
    except (TypeError, ValueError):
        return 0


def _card_mal(card: dict) -> int:
    try:
        return int(card.get("malId") or 0)
    except (TypeError, ValueError):
        return 0


def _franchise(card: dict) -> str:
    return (str((card or {}).get("franchise") or "").strip()
            or _api.title_root((card or {}).get("russian")
                               or (card or {}).get("name")))
