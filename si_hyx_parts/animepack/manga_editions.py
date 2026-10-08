# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Three comic edition shares, including migration of older checkboxes."""
KEYS = ("manga", "manhwa", "manhua")
LABELS = {"manga": "Манга", "manhwa": "Манхва", "manhua": "Маньхуа"}
SUPPORTED = KEYS + ("one_shot", "doujin")


def shares(settings) -> dict:
    manhwa = max(0, min(100, int(settings.manga_pct_manhwa or 0)))
    manhua = max(0, min(100, int(settings.manga_pct_manhua or 0)))
    raw = {"manga": max(0, 100 - manhwa - manhua),
           "manhwa": manhwa, "manhua": manhua}
    kinds = settings.manga_kinds
    enabled = [k for k in KEYS if kinds.get(k) or
               (k == "manga" and (kinds.get("one_shot") or kinds.get("doujin")))]
    if not enabled:
        return dict.fromkeys(KEYS, 0)
    weights = {k: raw[k] for k in enabled}
    if not any(weights.values()):
        weights = dict.fromkeys(enabled, 1)
    total = sum(weights.values())
    result = {k: weights.get(k, 0) * 100 // total for k in KEYS}
    rest = 100 - sum(result.values())
    order = sorted(enabled, key=lambda k: -(weights[k] * 100 % total))
    for key in order[:rest]:
        result[key] += 1
    return result


def migrate(settings, source) -> None:
    old = source.get("manga_kinds") or {}
    settings.manga_kinds = {k: bool(settings.manga_kinds.get(k)) for k in SUPPORTED}
    if (not any(settings.manga_kinds.values())
            and any(old.get(k) for k in ("light_novel", "novel"))):
        settings.manga_kinds.update(dict.fromkeys(KEYS, True))
    values = shares(settings)
    settings.manga_pct_manhwa = values["manhwa"]
    settings.manga_pct_manhua = values["manhua"]


def edition(card) -> str:
    kind = str(card.get("kind") or "").lower()
    return kind if kind in ("manhwa", "manhua") else "manga"


# ── Своя сложность у каждого издания ─────────────────────────────────────
# Манга, манхва и маньхуа узнаются по-разному, поэтому у каждой своя рамка
# «от … до» и своя средняя (просьба пользователя). Поля манги — прежние
# manga_level_*; у манхвы и маньхуа — manhwa_level_* и manhua_level_*.

def _field(key, name) -> str:
    return f"{key}_level_{name}"


def level_range(settings, key) -> tuple:
    """Рамка сложности издания: (от, до)."""
    low = int(getattr(settings, _field(key, "min")))
    high = int(getattr(settings, _field(key, "max")))
    return low, max(low, high)


def level_avg(settings, key) -> int:
    """Средняя сложность издания; 0 — «любая»."""
    return int(getattr(settings, _field(key, "avg"), 0) or 0)


def active(settings) -> list:
    """Издания с ненулевой долей в книжной части пака."""
    values = shares(settings)
    return [k for k in KEYS if values[k]] or ["manga"]


def span(settings) -> tuple:
    """Самая широкая рамка среди задействованных изданий.

    Её видит код, которому издание кандидата неизвестно (квоты, запас средней);
    точную рамку своего издания книга проходит в card_range."""
    bands = [level_range(settings, k) for k in active(settings)]
    return min(b[0] for b in bands), max(b[1] for b in bands)


def card_range(settings, card) -> tuple:
    """Рамка сложности для этой книги — по её изданию."""
    return level_range(settings, edition(card or {}))


def average_target(settings) -> int:
    """Средняя всей книжной части: средние изданий, взвешенные по их долям.

    Издание с «любой» средней в счёт не идёт и тянется к общей книжной средней.
    Ни у одного издания средней нет — 0: книги считаются вместе с остальным
    паком, как и раньше."""
    values = shares(settings)
    weighted = [(level_avg(settings, k), values[k] or 1) for k in active(settings)
                if level_avg(settings, k)]
    if not weighted:
        return 0
    total = sum(w for _, w in weighted)
    return int(round(sum(a * w for a, w in weighted) / total))


def aim(settings, card, value):
    """Уровень, к которому тянется книга этого издания.

    value — нужный сейчас уровень всей книжной части. Своя средняя издания
    сдвигает его на столько же, на сколько она отличается от общей книжной;
    у «любой» сдвига нет."""
    if value is None:
        return None
    key = edition(card or {})
    own, common = level_avg(settings, key), average_target(settings)
    if own and common:
        value += own - common
    low, high = level_range(settings, key)
    return max(low, min(high, value))


def migrate_levels(settings, source) -> None:
    """Настройки до раздельных рамок: манхва и маньхуа повторяют мангу."""
    for key in KEYS[1:]:
        for name in ("min", "max", "avg"):
            if _field(key, name) not in source:
                setattr(settings, _field(key, name),
                        getattr(settings, _field("manga", name)))


def validate_levels(settings) -> list:
    """Ошибки рамок и средних по задействованным изданиям."""
    problems = []
    names = {"manga": "манги", "manhwa": "манхвы", "manhua": "маньхуа"}
    for key in active(settings):
        low = int(getattr(settings, _field(key, "min")))
        high = int(getattr(settings, _field(key, "max")))
        if low > high:
            problems.append(f"Сложность {names[key]}: «от» больше, чем «до».")
            continue
        avg = level_avg(settings, key)
        if avg and not low <= avg <= high:
            problems.append(f"Средняя сложность {names[key]} {avg} не попадает "
                            f"в рамки «от {low} до {high}».")
    return problems
