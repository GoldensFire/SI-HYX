# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Почему пак недобрался — цифрами. Namespace: animepack.

Прежний отчёт называл «годными» тайтлы, прошедшие только ПЕРВИЧНЫЕ фильтры
(дубли, тип/год/оценка/жанры, рамка сложности пака). После них кандидату ещё
предстояли выбор рода вопроса, средняя сложность, персонажи, внешние источники
и сама загрузка, и куда делись «годные» — по отчёту понять было нельзя.
Заодно аниме и книги складывались в одно число («база дала 6 627 тайтлов»),
хотя приходят они из разных каталогов и отсеиваются по-разному.

Здесь три раздела: каталоги, судьба кандидатов (со сходящейся арифметикой) и
роды вопросов «нужно / получено / не хватило». Совет в конце зависит от того,
что именно съело кандидатов, а не печатается всегда один и тот же.
"""
from __future__ import annotations
import animepack as _api


MEDIA_TITLES = {"anime": "аниме", "manga": "книг"}


def _by_media(counter) -> str:
    """«(аниме 12 811, книг 5 778)» — или пусто, если каталог один."""
    rows = [(MEDIA_TITLES.get(key, key), int(num))
            for key, num in sorted(counter.items()) if num]
    if len(rows) < 2:
        return ""
    return " (" + ", ".join(f"{name} {num}" for name, num in rows) + ")"


def _catalogs(gen) -> None:
    """Сколько карточек просмотрено и сколько прошло первичные фильтры."""
    if not gen._seen_titles:
        gen.log("База не дала ни одной карточки — проверьте фильтры каталога "
                "или нажмите «Обновить базу».")
        return
    gen.log(f"Карточек просмотрено: {gen._seen_titles}"
            f"{_by_media(gen._seen_by_media)}.")
    gen.log(f"Прошли первичные фильтры (дубли, тип/год/оценка/жанры, рамка "
            f"сложности пака): {gen._good_titles}"
            f"{_by_media(gen._good_by_media)}.")
    for reason, num in gen._skips.most_common():
        if num:
            gen.log(f"  • отсеяно «{reason}»: {num}")


def _fates(gen, got: int) -> None:
    """Судьба кандидатов, прошедших первичные фильтры."""
    tries = sum(gen._tries.values())
    drops = sum(gen._drops.values())
    late = sum(gen._late.values())
    waiting = len(gen._level_bench)
    gen.log(f"Из них дошли до попытки собрать вопрос: {tries}; вопросов "
            f"вышло {got}.")
    for reason, num in gen._drops.most_common():
        if num:
            gen.log(f"  • до загрузки не дошёл «{reason}»: {num}")
    if gen._level_benched:
        back = gen._level_reused
        tail = (f", из них вернулись в дело {back}" if back else
                ", вернуть в дело не понадобилось" if not waiting else "")
        gen.log(f"  • откладывалось ради средней сложности: "
                f"{gen._level_benched}{tail}")
    if waiting:
        gen.log(f"  • так и ждут на скамейке средней сложности: {waiting}")
    if gen._failed_media:
        gen.log(f"  • попытка сорвалась (медиа, сюжет, персонаж): "
                f"{gen._failed_media}")
    if gen._rejected_media:
        gen.log(f"  • отвергнут по сложности уже при загрузке "
                f"(«в избранном», персонажи): {gen._rejected_media}")
    early = getattr(gen, "_early_repeat_attempts", 0)
    if early:
        gen.log(f"  • повтор найден при поиске, до подготовки медиа: {early}")
    for reason, num in gen._late.most_common():
        if num:
            gen.log(f"  • вопрос был готов, но не пригодился «{reason}»: {num}")
    # Отказы по источникам: Pixiv, MangaDex, сакуга, сюжет, места, персонажи.
    # Их считает _log_rare — там же, где гасятся повторы одной и той же жалобы.
    with gen._warn_lock:
        rows = sorted(gen._warn_counts.items(), key=lambda r: (-r[1], r[0]))
    for tag, num in rows:
        if num:
            gen.log(f"  • отказы «{tag}»: {num}")
    # Арифметика: всё, что прошло первичные фильтры, должно куда-то деться.
    spent = tries + drops + waiting
    rest = gen._good_titles - spent
    if rest > 0:
        gen.log(f"  • остались нерассмотренными (пак уже добран или "
                f"остановлен): {rest}")
    lost = tries - got - gen._failed_media - gen._rejected_media - late - early
    if lost > 0:
        gen.log(f"  • попытки без объяснения (загрузка ещё шла): {lost}")
    summary = getattr(getattr(gen, "pixiv", None), "summary", None)
    if callable(summary):
        note = str(summary() or "")
        if note:
            gen.log(note)


def _kinds(gen, quotas, counts) -> None:
    """«нужно / получено / не хватило» по каждому роду вопросов."""
    want = dict(gen.s.question_quotas)
    if not counts:
        return
    order = _api.SONG_KINDS + (_api.VIDEO_KIND,) + _api.SILENT_KINDS
    rows = [k for k in order if want.get(k) or counts.get(k)]
    if not rows:
        return
    gen.log("По родам вопросов:")
    for kind in rows:
        need = int(want.get(kind, 0) or 0)
        made = int(counts.get(kind, 0) or 0)
        name = _api.KIND_TITLES.get(kind, kind)
        tail = f", попыток {gen._tries[kind]}" if gen._tries[kind] else ""
        # Квота могла поменяться на ходу: места умерших родов вопросов
        # раздаются живым (см. _share_out_dead).
        now = int((quotas or {}).get(kind, need) or 0)
        moved = f", мест стало {now}" if quotas is not None and now != need else ""
        gen.log(f"  • {name}: нужно {need}, получено {made}, "
                f"не хватило {max(0, need - made)}{moved}{tail}")


# ── совет по делу ────────────────────────────────────────────────────────
def _years_are_wide(settings) -> bool:
    """Диапазон годов и так почти полный — расширять его нечего."""
    try:
        first = int(settings.year_from)
        last = int(settings.year_to)
    except (TypeError, ValueError):
        return True
    return first <= 1970 and last >= _api._current_year() - 1


def _advice(gen, got: int, total: int) -> list[str]:
    """Что и правда мешало набрать пак — по самому крупному счёту."""
    tips: list[str] = []
    skips = gen._skips
    need = max(1, total - got)
    hard = skips["рамки сложности пака"] + skips["рамки сложности манги"]
    if hard >= need:
        tips.append(f"расширить рамки сложности: по ним не прошло {hard} "
                    "карточек")
    if skips["франшиза уже в паке"] >= need:
        tips.append("разрешить повтор франшизы: одна серия закрывает сразу "
                    "все свои части")
    if skips["уже спрашивали в чужих паках"] >= need:
        tips.append("убрать часть паков из «не повторять из этих .siq»")
    if skips["фильтры (тип, год, оценка, жанры)"] >= need:
        what = "оценку, типы аниме или жанры"
        if not _years_are_wide(gen.s):
            what = "годы, оценку, типы аниме или жанры"
        tips.append(f"ослабить {what}")
    if gen._level_benched >= need and int(gen.s.level_avg or 0):
        tips.append(f"сдвинуть среднюю сложность ({gen.s.level_avg}): под неё "
                    f"не подошло {gen._level_benched} кандидатов")
    if sum(gen._drops.values()) >= need:
        tips.append("поменять доли родов вопросов: кандидаты были, а мест "
                    "под их тайтлы уже не оставалось")
    if gen._failed_media + gen._rejected_media >= need:
        tips.append("убавить долю родов вопросов, которые чаще всего "
                    "срывались на загрузке (см. отказы выше)")
    # «Обновить базу» — только когда карточек и правда мало. Когда их вдоволь,
    # а кандидатов съели фильтры и квоты, этот совет уводил в сторону.
    if gen._good_titles < total * 2:
        tips.append("нажать «Обновить базу»: карточек в кэше каталога меньше, "
                    "чем нужно на пак такого размера")
    return tips


def _log_shortage(self, got: int, total: int, quotas=None, counts=None) -> None:
    """Почему кандидатов не хватило — цифрами, а не «кандидаты кончились»."""
    self.log(f"Кандидаты кончились: набрано {got} вопросов из {total}.")
    _catalogs(self)
    _fates(self, got)
    _kinds(self, quotas, counts)
    tips = _advice(self, got, total)
    if tips:
        self.log("Что делать: " + "; ".join(tips) + ".")
    else:
        self.log("Что делать: подходящих карточек в каталоге по этим "
                 "настройкам почти не осталось — ослабьте фильтры или "
                 "уменьшите пак.")
