# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Цены и раскладка вопросов по раундам; форматирование длительности. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api

# Караоке дешевле такой же обычной песни, сакуга с тегом genga — дороже.
KARAOKE_PRICE_STEP = -1
SAKUGA_GENGA_STEP = 1


def sakuga_genga(cand) -> bool:
    """У вырезки Sakugabooru стоит тег genga."""
    tags = (getattr(cand, "sakuga", None) or {}).get("tags") or ()
    return "genga" in tags

def _split_total(total: int, weights: dict) -> dict:
    """Делит total между ключами по весам «наибольшим остатком»: сумма долей
    всегда ровно total, а лишние единицы достаются тем, у кого дробная часть
    больше. Так ползунок «60/25/15» на 20 вопросах не теряет ни одного."""
    base = sum(max(0, int(v)) for v in weights.values())
    if total <= 0 or base <= 0:
        return {k: 0 for k in weights}
    exact = {k: max(0, int(v)) * total / base for k, v in weights.items()}
    out = {k: int(v) for k, v in exact.items()}
    rest = total - sum(out.values())
    for key in sorted(exact, key=lambda k: (exact[k] - out[k], exact[k]),
                      reverse=True):
        if rest <= 0:
            break
        out[key] += 1
        rest -= 1
    return out

_split_total.__module__ = _api.__name__
_api._split_total = _split_total

def _scale_quotas(quotas: dict, target: int) -> dict:
    """Ужимает квоты по типам песен так, чтобы их сумма стала ровно target.
    Пропорции сохраняются, остаток раздаётся по наибольшей дробной части."""
    base = sum(max(0, int(v)) for v in quotas.values())
    if target <= 0 or base <= 0:
        return {k: 0 for k in quotas}
    exact = {k: max(0, int(v)) * target / base for k, v in quotas.items()}
    out = {k: int(v) for k, v in exact.items()}
    rest = target - sum(out.values())
    for key in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True):
        if rest <= 0:
            break
        out[key] += 1
        rest -= 1
    return out

_scale_quotas.__module__ = _api.__name__
_api._scale_quotas = _scale_quotas

def price_for_difficulty(difficulty) -> int:
    """Цена вопроса по сложности AMQ: угадываемая песня стоит дёшево."""
    try:
        d = float(difficulty)
    except (TypeError, ValueError):
        return 1
    for threshold, price in _api._PRICE_RANGES:
        if d >= threshold:
            return price
    return 1

price_for_difficulty.__module__ = _api.__name__
_api.price_for_difficulty = price_for_difficulty


def price_for_level(level) -> int:
    """Базовая цена по фиксированному уровню 1…15: ровная шкала 6…20."""
    try:
        number = int(level)
    except (TypeError, ValueError):
        number = 1
    number = max(1, min(_api.MAX_LEVEL, number))
    return _api._PRICE_MIN + number - 1

price_for_level.__module__ = _api.__name__
_api.price_for_level = price_for_level

def assign_prices(songs: list, s: _api.PackSettings) -> list:
    """Проставляет cand.price всем отобранным вопросам и возвращает их же.

    База у ВСЕХ вопросов одна и та же — фиксированный уровень узнаваемости
    тайтла 1…15. Каждый соседний уровень даёт ровно одно очко: 1-й стоит 6,
    2-й — 7, …, 15-й — 20. Поэтому цена больше не зависит от случайного
    состава конкретного пака и не склеивает уровни 1–4 в одну шестёрку.

    Сверху идут надбавки за род вопроса:

    * песня — за тип (эндинг +2, OST +4) и за сложность угадывания в AMQ
      (сложность 80 даёт +2, ноль — все десять, см. song_difficulty_bonus);
      караоке на очко дешевле той же песни без текста на экране;
    * арт с Pixiv и манга с аниме-экранизацией — ровно +2; сакуга с тегом
      genga — +1;
    * вопрос по сюжету — цена тайтла, умноженная на PLOT_PRICE_MULT;
    * персонаж — фиксированная надбавка за роль: +4 за главного и +6 за
      второстепенного героя, минус скидка за «в избранном» (до −3, см.
      char_fav_price_shift);
    * студия — средняя цена трёх показанных тайтлов × STUDIO_PRICE_MULT."""
    from . import price_parts as parts
    from .character_title_filter import character_named_in_title
    for cand in songs:
        base = _api.price_for_level(cand.level)
        # Разбивку копим по ходу дела: её показывает подсказка на ячейке
        # «Цена» в таблице состава пака (просьба пользователя).
        lines = parts.start(cand.level, base)
        if cand.is_character:
            main = bool((cand.character or {}).get("main"))
            named = character_named_in_title(cand.character or {},
                                             cand.anime or {})
            role_name = ("Имя персонажа уже в названии"
                         if named else
                         ("Главный персонаж" if main
                          else "Второстепенный персонаж"))
            step = (_api.CHAR_TITLE_PRICE_STEP if named
                    else _api._CHAR_PRICE_STEP[main])
            parts.add_step(lines, role_name, step)
            base += step
            # Много «в избранном» — героя узнают, вопрос дешевле (просьба
            # пользователя). Скидка не больше надбавки за роль: персонаж
            # никогда не стоит меньше кадра из своего тайтла.
            fav_step = max(-step, _api.char_fav_price_shift(cand))
            fav = int(getattr(cand, "char_favorites", -1) or 0)
            parts.add_step(lines, f"В избранном у {fav} чел.", fav_step)
            base += fav_step
        # Вопрос по сюжету стоит в ПОЛТОРА раза дороже, чем тот же тайтл стоил
        # бы кадром (просьба пользователя): помнить события куда труднее, чем
        # узнать картинку.
        if cand.kind == _api.PLOT_KIND:
            plot = int(round(base * _api.PLOT_PRICE_MULT))
            parts.add_mult(lines, "Вопрос по сюжету", base, plot)
            base = plot
        # Студия — в полтора раза дороже средней цены трёх показанных
        # тайтлов (просьба пользователя), а не цены одного тайтла-затравки.
        if cand.kind == _api.STUDIO_KIND:
            from .studio_question import studio_price
            mean, studio = studio_price(cand.studio_levels, base)
            lines.append(f"Средняя цена трёх тайтлов: {mean:.1f}")
            parts.add_mult(lines, f"Студия (×{_api.STUDIO_PRICE_MULT:g})",
                           int(round(mean)), studio)
            base = studio
        if cand.is_video:
            # Видеоряд позволяет узнать тайтл по картинке: цена как у кадра.
            step = 0
        elif cand.is_silent:
            # Манге надбавка положена, только пока её знают по экранизации: у
            # книги без аниме цена и так посчитана по своей, книжной шкале.
            step = (0 if (cand.is_manga and not cand.adapted_from)
                    else _api._SILENT_PRICE_STEP.get(cand.kind, 0))
            parts.add_step(lines, _api.KIND_TITLES.get(cand.kind, cand.kind), step)
            # Вырезка с тегом genga — черновые рисунки ключевых кадров, а не
            # готовая анимация: узнать тайтл по ним труднее (просьба
            # пользователя).
            if cand.is_sakuga and sakuga_genga(cand):
                parts.add_step(lines, "Сакуга с тегом genga", SAKUGA_GENGA_STEP)
                step += SAKUGA_GENGA_STEP
        else:
            # Надбавка за музыку считает песню и кавер вместе (одни и те же
            # десять очков на обе, см. cover_difficulty).
            kind_step = _api._KIND_PRICE_STEP.get(cand.base_kind, 0)
            music_step = _api.music_difficulty_bonus(cand)
            parts.add_step(lines, _api.KIND_TITLES.get(cand.base_kind,
                                                       cand.base_kind), kind_step)
            parts.add_step(lines, "Трудно угадать песню", music_step)
            step = kind_step + music_step
            # Караоке показывает текст песни на экране — подсказка, которой
            # у обычной песни нет: на очко дешевле (просьба пользователя).
            if cand.music_effect == "karaoke":
                parts.add_step(lines, "Караоке", KARAOKE_PRICE_STEP)
                step += KARAOKE_PRICE_STEP
        if cand.is_frame and cand.frame_has_characters is False:
            parts.add_step(lines, "В кадре нет персонажей", 2)
            step += 2
        cand.price = max(_api._PRICE_MIN, base + step)
        cand.price_parts = parts.finish(lines, cand.price, _api._PRICE_MIN)
    return songs

assign_prices.__module__ = _api.__name__
_api.assign_prices = assign_prices

def arrange_questions(songs: list, s: _api.PackSettings) -> list[list]:
    """Раскладка пака: список тем, в каждой — вопросы в том порядке, в каком они
    попадут в content.xml. Одно место на всех, чтобы таблица во вкладке и сам
    пак не разъезжались.

    Обычно вопросы в теме идут по возрастанию цены; галочка «в разнобой»
    (`shuffle_questions`) оставляет их ровно в том порядке, в каком их набрал
    генератор (а он этот список уже перемешал) — цены тогда скачут, как в живых
    паках. Само перемешивание живёт в select_songs, а не здесь: функция обязана
    быть чистой, иначе таблица во вкладке и содержимое пака разъедутся."""
    _api.assign_prices(songs, s)
    ordered = list(songs)
    shuffled = bool(getattr(s, "shuffle_questions", False))
    if getattr(s, "sort_by_index", False) and not shuffled:
        # Пак идёт от самых узнаваемых тайтлов к самым безвестным.
        ordered.sort(key=lambda c: c.index, reverse=True)
    per_theme = max(1, int(s.questions))
    chunks = [ordered[i:i + per_theme] for i in range(0, len(ordered), per_theme)]
    if shuffled:
        return chunks
    return [sorted(chunk, key=lambda c: c.price) for chunk in chunks]

arrange_questions.__module__ = _api.__name__
_api.arrange_questions = arrange_questions

def fmt_duration(seconds) -> str:
    """Секунды → «00:01:05». В ASPG строка склеивалась вручную и давала
    «00:00:3» (без ведущего нуля), а при большом времени картинок — минус."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    total = max(1, total)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

fmt_duration.__module__ = _api.__name__
_api.fmt_duration = fmt_duration

def fmt_elapsed(seconds) -> str:
    """Длительность генерации по-человечески: «3 мин 20 с», «48 с», «1 ч 5 мин»."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)
    if total < 60:
        return f"{total} с"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    return f"{m} мин {s} с" if s else f"{m} мин"

fmt_elapsed.__module__ = _api.__name__
_api.fmt_elapsed = fmt_elapsed


def song_difficulty_bonus(difficulty) -> int:
    """0…SONG_DIFF_BONUS_MAX очков сверху за сложность песни."""
    try:
        d = float(difficulty)
    except (TypeError, ValueError):
        return 0
    if d <= 0 or d > 100:
        return 0
    return int(round((100.0 - d) / 100.0 * _api.SONG_DIFF_BONUS_MAX))

song_difficulty_bonus.__module__ = _api.__name__
_api.song_difficulty_bonus = song_difficulty_bonus
