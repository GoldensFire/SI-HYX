# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Средняя сложность по родам вопросов. Namespace: animepack.

У пака одна общая средняя узнаваемость (level_avg), но не всякому роду вопросов
она годится. У книг узнаваемость и меряется-то по своей шкале
(MANGA_INDEX_LEVELS), а арт — это не кадр: по фанатскому рисунку тайтл узнают
хуже, и под арты обычно берут заметные тайтлы, даже когда остальной пак собран
из редкостей. Рамки «от … до» у тех и других уже свои (см. level_bounds), а
теперь своя и СЕРЕДИНА (просьба пользователя).

Род вопроса со своей средней в общую не попадает вовсе: иначе двадцать книг с
их собственной шкалой утащили бы среднюю всего пака и генератор погнался бы за
ней кадрами. Своей средней нет (ноль — «любая») — вопрос считается вместе со
всеми, как раньше.
"""
from __future__ import annotations
import animepack as _api

# Ключи «корзин» средней сложности. None — общая средняя пака.
ART_BUCKET = "art"
MANGA_BUCKET = "manga"
PLOT_BUCKET = "plot"
SONG_BUCKET = "song"
STUDIO_BUCKET = "studio"

# Как зовётся корзина в логе.
BUCKET_TITLES = {ART_BUCKET: "артов", MANGA_BUCKET: "манги",
                 PLOT_BUCKET: "сюжета", SONG_BUCKET: "песен",
                 STUDIO_BUCKET: "студий"}
# Все корзины со своей средней — одним списком. Перечислять их по именам на
# стороне генератора нельзя: добавленный сюда «сюжет» так и остался без своего
# списка набранных уровней, и пак из одного сюжета падал с KeyError: 'plot'.
LEVEL_BUCKETS = tuple(BUCKET_TITLES)

# Какое поле настроек задаёт среднюю для корзины.
BUCKET_FIELDS = {ART_BUCKET: "art_level_avg", MANGA_BUCKET: "manga_level_avg",
                 PLOT_BUCKET: "plot_level_avg", SONG_BUCKET: "song_level_avg",
                 STUDIO_BUCKET: "studio_level_avg"}


def level_bucket(kind) -> _api.Optional[str]:
    """В какую корзину средней сложности попадает этот род вопросов."""
    if kind == _api.MANGA_KIND:
        return MANGA_BUCKET
    if kind == _api.PLOT_KIND:
        return PLOT_BUCKET
    if kind in (_api.AI_ART_KIND, _api.PIXIV_ART_KIND):
        return ART_BUCKET
    if kind in _api.SONG_KINDS or kind == _api.VIDEO_KIND:
        return SONG_BUCKET
    if kind == _api.STUDIO_KIND:
        return STUDIO_BUCKET
    return None


def level_avg_target(settings, bucket) -> int:
    """Просимая средняя для корзины (0 — не следить)."""
    field = BUCKET_FIELDS.get(bucket)
    if field is None:
        return int(getattr(settings, "level_avg", 0) or 0)
    return int(getattr(settings, field, 0) or 0)


def own_bucket(settings, kind) -> _api.Optional[str]:
    """Корзина вопроса с учётом настроек: своя средняя — своя корзина.

    Ноль в «своей» средней означает «следить как за всем остальным», поэтому
    такой вопрос возвращается в общую корзину (None)."""
    bucket = level_bucket(kind)
    if bucket and not level_avg_target(settings, bucket):
        return None
    return bucket


def short_pack_average_error(settings, songs) -> str:
    """Check every requested average before publishing any complete pack."""
    from .manga_targets import final_error
    strict_error = final_error(settings, songs)
    if strict_error:
        return strict_error
    groups: dict[str | None, list[int]] = {}
    for cand in songs:
        groups.setdefault(own_bucket(settings, cand.kind), []).append(question_level(cand))
    for bucket, values in groups.items():
        target = level_avg_target(settings, bucket)
        if target and sum(values) != target * len(values):
            where = BUCKET_TITLES[bucket] if bucket else "пака"
            actual = sum(values) / len(values)
            return (f"Средняя сложность {where}: {actual:.1f}, просили {target}. "
                    "Подходящих вопросов не нашлось; пакет не создан.")
    target = int(getattr(settings, 'char_level_avg', 0) or 0)
    characters = [int(c.char_level) for c in songs if getattr(c, 'is_character', False)] if target else []
    if target and characters and sum(characters) != target * len(characters):
        return (f'Средняя сложность персонажей: {sum(characters) / len(characters):.1f}, '
                f'просили {target}. Готовые вопросы сохраняются для точечного добора.')
    return ""


def question_level(candidate):
    """The selected question's level, before optional presentation substitutions."""
    value = getattr(candidate, 'selection_level', None)
    return int((getattr(candidate, 'level', 0) if value is None else value) or 0)


level_bucket.__module__ = _api.__name__
level_avg_target.__module__ = _api.__name__
own_bucket.__module__ = _api.__name__
_api.level_bucket = level_bucket
_api.level_avg_target = level_avg_target
_api.own_bucket = own_bucket
