# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackSettings: рамки узнаваемости по родам вопросов. Namespace: animepack.

Свойства подключаются в тело PackSettings обычным импортом (см.
pack_settings.py) — одна связная задача: какой род вопросов какую рамку
сложности слушает и по какой ширине вообще искать кандидатов.
"""
from __future__ import annotations
import animepack as _api


@property
def level_bounds(self) -> dict:
    """{род вопроса: (мин, макс)} — рамки сложности по родам вопросов.

    У книг и артов рамка своя (просьба пользователя), у всего остального —
    общая «Сложность пака». Ключ None — та самая общая рамка."""
    general = (int(self.level_min), int(self.level_max))
    manga = (int(self.manga_level_min), int(self.manga_level_max))
    art = (int(self.art_level_min), int(self.art_level_max))
    plot = (int(self.plot_level_min), int(self.plot_level_max))
    out = {None: general, _api.MANGA_KIND: manga, _api.PLOT_KIND: plot}
    out[_api.STUDIO_KIND] = self.studio_level_range
    # Уровень персонажа равен уровню его тайтла, то есть известен ещё ДО
    # выбора героя. Своя рамка персонажей поэтому проверяется тут же, при
    # выборе рода вопроса: раньше тайтл 9-го уровня при рамке 3…8 доезжал до
    # запроса персонажей и только там отбрасывался (жалоба пользователя).
    out[_api.CHAR_KIND] = self.char_level_range
    out.update({k: art for k in (_api.AI_ART_KIND, _api.PIXIV_ART_KIND)})
    out.update({k: self.song_level_range
                for k in _api.SONG_KINDS + (_api.VIDEO_KIND,)})
    return out

@property
def song_level_range(self) -> tuple:
    """Рамка узнаваемости песенных вопросов; None в полях — как у пака."""
    low = self.level_min if self.song_level_min is None else self.song_level_min
    high = self.level_max if self.song_level_max is None else self.song_level_max
    return (int(low), int(high))

@property
def char_level_range(self) -> tuple:
    """Рамка сложности вопросов-персонажей (своя, «Персонажи» на вкладке)."""
    low = int(getattr(self, "char_level_min", 1) or 1)
    high = int(getattr(self, "char_level_max", _api.MAX_LEVEL)
               or _api.MAX_LEVEL)
    return (low, max(low, high))

@property
def studio_level_range(self) -> tuple:
    """Рамка узнаваемости студий; None в полях — как у всего пака."""
    low = (self.level_min if self.studio_level_min is None
           else self.studio_level_min)
    high = (self.level_max if self.studio_level_max is None
            else self.studio_level_max)
    return (int(low), int(high))

def level_range(self, kind=None) -> tuple:
    """Рамка сложности для этого рода вопросов."""
    return self.level_bounds.get(kind) or self.level_bounds[None]

@property
def level_span(self) -> tuple:
    """Самая широкая рамка среди ЗАДЕЙСТВОВАННЫХ родов вопросов.

    По ней отбираются кандидаты из каталога: род вопроса выбирается позже,
    и заранее неизвестно, станет тайтл кадром (общая рамка) или артом
    (своя). Точную рамку своего рода вопрос проходит уже в _pick_kind."""
    shares = self.mix_shares
    bounds = self.level_bounds
    arts = (_api.AI_ART_KIND, _api.PIXIV_ART_KIND)
    own = arts + (_api.PLOT_KIND, _api.STUDIO_KIND, _api.CHAR_KIND)
    used = [bounds[k] for k in own if shares.get(k)]
    # Песни и ролики — та же история, что и арты: у них своя рамка.
    if shares.get("songs") or shares.get(_api.VIDEO_KIND):
        used.append(self.song_level_range)
    # Общая рамка нужна, только пока в паке есть хоть что-то, кроме родов
    # со своей рамкой и книг: у пака из одних артов их рамка и есть
    # единственная, а лишняя ширина жгла бы кандидатов впустую.
    skip = set(own) | {"songs", _api.VIDEO_KIND, _api.MANGA_KIND}
    if any(v for k, v in shares.items() if k not in skip) or not used:
        used.append(bounds[None])
    return (min(b[0] for b in used), max(b[1] for b in used))
