# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Вопрос-СТУДИЯ: три франшизы одной студии.

Вопрос показывает ровно три кадра из трёх разных франшиз, которые
нарисовала одна студия. Надпись «Назовите студию» показывается одновременно
с каждым кадром или его видео появления в течение четырёх секунд.

Ответ — только имя студии. Картинка ответа — склеенные слева направо
постеры этих же трёх аниме, в порядке кадров. Одна студия в одном паке
второй раз не выбирается. Студии лежат в карточке Shikimori
(`studios { id name }` в ANIME_FIELDS); у карточек из старой базы этого поля
нет вовсе — тогда оно доспрашивается на тайтл и оседает в memo кэша, как
«в избранном» и превью серий.

Public namespace: animepack.
"""
from __future__ import annotations
import animepack as _api


def studio_names(generator, cand) -> list[str]:
    """Студии тайтла по порядку («» — не узнали ни одной).

    Карточка из свежей базы уже несёт `studios`. У карточки постарше поля нет
    ВОВСЕ — и это не то же самое, что «студия не указана»: проверяем наличие
    ключа, а не пустоту (иначе тайтлы без студии переспрашивались бы каждый
    раз)."""
    card = cand.anime or {}
    if "studios" in card:
        return _clean(card.get("studios"))
    try:
        tid = int(card.get("id") or 0)
    except (TypeError, ValueError):
        tid = 0
    if not tid:
        return []
    known = generator.db_cache.memo("studios", tid, _api.ENRICHMENT_CACHE_TTL)
    if known is not None:
        with generator._media_cache_lock:
            generator._media_cache_hits["метаданные"] += 1
        return _clean(known)
    try:
        rows = generator.shikimori.animes_by_ids([tid])
    except Exception:  # noqa: BLE001 — без студии вопроса просто не будет
        return []
    raw = (rows or [{}])[0].get("studios") if rows else []
    # Оставляем id студии на самой карточке: он нужен, чтобы при бедном или
    # старом локальном каталоге допросить у Shikimori другие её аниме.
    card["studios"] = list(raw or [])
    generator.db_cache.remember_memo("studios", tid, card["studios"])
    return _clean(card["studios"])


def studio_possible(card) -> bool:
    """Стоит ли вообще пробовать этот тайтл вопросом-студией.

    Проверка бесплатная и потому идёт ещё при выборе рода вопроса: у карточки
    из свежей базы студии лежат прямо в ней, и тайтл без них незачем доводить
    до загрузки кадров. У карточки постарше поля нет вовсе — такую не
    отвергаем, студии ей доспросят при загрузке."""
    card = card or {}
    return "studios" not in card or len(_clean(card.get("studios"))) == 1


def single_studio(card) -> bool:
    """Тайтл нарисовала ровно одна студия.

    Кадры для вопроса-студии берутся ТОЛЬКО у таких (просьба пользователя):
    по совместной работе («Bones × MAPPA») студию не угадать — кадр одинаково
    «принадлежит» обеим. Карточка без поля studios проверку не проходит:
    за другие работы студии ручаться нечем."""
    card = card or {}
    return "studios" in card and len(_clean(card.get("studios"))) == 1


def _clean(rows) -> list[str]:
    """Имена студий из карточки: строками, без пустых и без повторов."""
    out, seen = [], set()
    for row in (rows or []):
        name = (str(row.get("name") or "").strip()
                if isinstance(row, dict) else str(row or "").strip())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def download_frames(generator, cand) -> bool:
    """Три кадра из трёх аниме одной студии и склейка их постеров."""
    if _api.STUDIO_KIND in generator._dead_kinds:
        cand.rejected = True
        return False
    choices = studio_names(generator, cand)
    if not choices:
        generator.log(f"«{cand.title_ru}» без студии в карточке — беру "
                      "следующий тайтл")
        return False
    if len(choices) > 1:
        generator._log_rare("Студии", f"«{cand.title_ru}» сделали несколько "
                            f"студий ({', '.join(choices)}) — беру следующий "
                            "тайтл")
        return False
    for studio in choices:
        cards = _cards_for_studio(generator, cand, studio)
        if (len(cards) < _api.STUDIO_FRAMES
                or not _reserve(generator, cand, studio, cards[:1])):
            continue
        assets = []
        for card in cards:
            if (generator.stopped() or len(assets) >= _api.STUDIO_FRAMES
                    or _api.STUDIO_KIND in generator._dead_kinds):
                break
            from .studio_reservations import reserve_card, release_card
            if not reserve_card(generator, cand, card):
                continue
            got = _download_one(generator, cand, card, len(assets) + 1)
            if got:
                assets.append((card, *got))
            else:
                release_card(generator, cand, card)
        if len(assets) == _api.STUDIO_FRAMES and _save_poster_strip(
                generator, cand, [row[3] for row in assets]):
            cand.studios = [studio]
            cand.studio_cards = [row[0] for row in assets]
            from .studio_reservations import retain_cards
            retain_cards(generator, cand, cand.studio_cards)
            cand.studio_levels = [_card_level(generator, row[0])
                                  for row in assets]
            names, urls = [row[1] for row in assets], [row[2] for row in assets]
            cand.frame_name, cand.frame_url = names[0], urls[0]
            cand.extra_frames, cand.extra_frame_urls = names[1:], urls[1:]
            cand.has_frame = True
            return True
        for _card, _name, url, _poster in assets:
            _forget_frame(generator, url)
        _unreserve(generator, cand)
    if not generator.stopped():
        generator.log(f"«{cand.title_ru}»: у студии не набралось трёх "
                      "разных франшиз с кадром и постером — беру "
                      "следующий тайтл")
    return False


def _card_level(generator, card: dict) -> int:
    """Уровень узнаваемости одного из показанных тайтлов — как у вопроса-кадра."""
    try:
        franchise = float(generator._franchise_index(card) or 0.0)
    except Exception:  # noqa: BLE001 — индекс франшизы не обязателен
        franchise = 0.0
    probe = _api.SongCandidate({}, card, kind=_api.STUDIO_KIND,
                               franchise_index=franchise)
    return probe.level


def studio_price(levels, fallback: int) -> tuple[float, int]:
    """(средняя цена тайтлов, цена вопроса) — в полтора раза дороже средней."""
    prices = [_api.price_for_level(level) for level in levels or ()]
    mean = sum(prices) / len(prices) if prices else float(fallback)
    return mean, int(round(mean * _api.STUDIO_PRICE_MULT))


def _catalog(generator) -> dict[str, list[dict]]:
    """{имя студии casefold: карточки}; собирается один раз."""
    with generator._studio_lock:
        if generator._studio_catalog is None:
            out: dict[str, list[dict]] = {}
            for card in generator.db_cache.all_cards("anime"):
                if not isinstance(card, dict):
                    continue
                for name in _clean(card.get("studios")):
                    out.setdefault(name.casefold(), []).append(card)
            generator._studio_catalog = out
        return generator._studio_catalog


def _card_key(card) -> tuple:
    try:
        return (int((card or {}).get("id") or 0),
                int((card or {}).get("malId") or 0))
    except (TypeError, ValueError):
        return (0, 0)


def _franchise_marks(card: dict) -> set[str]:
    """Признаки одной серии: франшиза Shikimori и корень названия.

    Корень страхует старые и неполные карточки, где ``franchise`` пусто:
    разные сезоны такого тайтла всё равно не должны дать два кадра.
    """
    franchise = str((card or {}).get("franchise") or "").strip()
    if franchise:
        return {franchise}
    root = _api.title_root((card or {}).get("russian")
                           or (card or {}).get("name"))
    key = _api.franchise_key(card or {})
    return {root or key} if root or key else set()


def _pack_marks(card: dict) -> set[str]:
    """Use the same franchise and title-root keys as ordinary pack questions."""
    from si_hyx_parts.animepack.generator_catalog import _franchise_marks
    return set(_franchise_marks(card))


def _cards_for_studio(generator, cand, studio: str) -> list[dict]:
    """Основной тайтл и разные франшизы той же студии в случайном порядке."""
    primary = cand.anime or {}
    rest = list(_catalog(generator).get(studio.casefold(), ()))
    # Старые базы часто собраны до появления поля studios: в них у «Гинтамы
    # 3» Sunrise уже виден после точечного запроса, а других работ Sunrise в
    # локальном индексе будто нет. Один запрос по id студии добирает реальные
    # карточки вместо ложного «не набралось трёх разных франшиз».
    studio_id = _studio_id(primary, studio)
    fetch = getattr(generator.shikimori, "random_animes", None)
    if studio_id and callable(fetch):
        try:
            rest += list(fetch(page=1, limit=50, studios=(studio_id,),
                               order="ranked") or [])
        except Exception:  # noqa: BLE001 — локальный каталог остаётся запасным
            pass
    with generator._studio_lock:
        generator.rng.shuffle(rest)
    out, seen_ids, seen_franchises = [], set(), set()
    for card in [primary, *rest]:
        key = _card_key(card)
        if not any(key) or key in seen_ids:
            continue
        marks = _franchise_marks(card)
        if marks & seen_franchises:
            continue
        if (card is not primary and not generator.s.dup_franchise
                and _pack_marks(card) & generator._used_franchise):
            continue
        if card is not primary and generator._root_excluded(card):
            continue
        # Совместные работы нескольких студий в вопрос не идут: по такому
        # кадру студию не угадать (просьба пользователя).
        if card is not primary and not single_studio(card):
            continue
        try:
            if card is not primary and not _api.filter_anime(card, generator.s):
                continue
        except Exception:  # noqa: BLE001 — неполная старая карточка
            continue
        seen_ids.add(key)
        seen_franchises.update(marks)
        out.append(card)
    return out


def _studio_id(card: dict, wanted: str) -> int:
    """Id названной студии из карточки (ноль у старой строковой записи)."""
    for row in ((card or {}).get("studios") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().casefold() != wanted.casefold():
            continue
        try:
            return int(row.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _reserve(generator, cand, studio: str, cards: list[dict]) -> bool:
    key = studio.casefold()
    with generator._studio_lock:
        if key in generator._used_studios or key in generator._excluded_studios:
            return False
        primary = set(getattr(cand, "_reserved", ()) or ())
        extra = set().union(*(_pack_marks(card) for card in cards[1:]))
        if (not generator.s.dup_franchise
                and extra & (generator._used_franchise - primary)):
            return False
        generator._used_studios.add(key)
        generator._used_franchise.update(extra)
        cand._studio_reserved_franchises = tuple(extra)
        cand._studio_reserved = key
    return True


def _unreserve(generator, cand) -> None:
    key = getattr(cand, "_studio_reserved", "")
    if not key:
        return
    cand._studio_reserved = ""
    with generator._studio_lock:
        generator._used_studios.discard(key)
        for mark in getattr(cand, "_studio_reserved_franchises", ()):
            generator._used_franchise.discard(mark)
        cand._studio_reserved_franchises = ()


def _forget_frame(generator, url: str) -> None:
    with generator._frames_lock:
        generator._frames_used.discard(_api.frame_url_key(url))


def _download_one(generator, cand, card: dict, number: int):
    """(файл кадра, url, PIL-постер) или None."""
    import io
    from PIL import Image

    probe = _api.SongCandidate({}, card, kind=_api.STUDIO_KIND)
    poster = card.get("poster") or {}
    poster_url = str(poster.get("originalUrl") or poster.get("mainUrl") or "")
    data, _ext = generator._poster_bytes(probe, poster_url)
    if not data:
        return None
    try:
        poster_image = Image.open(io.BytesIO(data)).convert("RGB")
        poster_image.load()
    except Exception:  # noqa: BLE001
        return None
    from .frame_visual_check import select
    selected = select(generator, probe)
    if selected is None:
        return None
    frame, ext = selected
    url = probe.frame_url
    try:
        name = generator._save_reusable_image(
            frame, f"{cand.file_base}_studio{number}", ext,
            reuse=False)
    except Exception as exc:  # noqa: BLE001
        _forget_frame(generator, url)
        generator.log(f"Кадр «{probe.title_ru}» не скачался: {exc}")
        return None
    if not name:
        _forget_frame(generator, url)
        return None
    return name, url, poster_image


def _save_poster_strip(generator, cand, posters) -> bool:
    """Горизонтальная склейка как в «Редактирование фото»: по высоте."""
    import io
    from PIL import Image

    if len(posters) != _api.STUDIO_FRAMES:
        return False
    height = max(image.height for image in posters)
    ready = []
    for image in posters:
        width = max(1, round(image.width * height / max(1, image.height)))
        ready.append(image.resize((width, height), Image.Resampling.LANCZOS))
    strip = Image.new("RGB", (sum(image.width for image in ready), height), "black")
    x = 0
    for image in ready:
        strip.paste(image, (x, 0))
        x += image.width
    buf = io.BytesIO()
    strip.save(buf, "PNG")
    try:
        name = generator._save_reusable_image(
            buf.getvalue(), f"{cand.file_base}_poster", ".png")
    except Exception as exc:  # noqa: BLE001
        generator.log(f"Постеры «{cand.title_ru}» не склеились: {exc}")
        return False
    cand.poster_name = name or cand.poster_name
    cand.has_poster = bool(name)
    return cand.has_poster


def frame_seconds(settings) -> int:
    """Каждый кадр студии показывается ровно четыре секунды."""
    return _api.STUDIO_FRAME_SECONDS


def append_items(q_param, cand, settings) -> None:
    """Кадры вопроса и надпись над каждым из них — в <param name="question">."""
    seconds = frame_seconds(settings)
    from .entrance_content import append_image
    for name in cand.question_frames:
        task = _api.ET.SubElement(q_param, "item", {"waitForFinish": "False"})
        task.text = _api.STUDIO_TASK_TEXT
        append_image(q_param, cand, name, seconds)


studio_names.__module__ = _api.__name__
download_frames.__module__ = _api.__name__
append_items.__module__ = _api.__name__
