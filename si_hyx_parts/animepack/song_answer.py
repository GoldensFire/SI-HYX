# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Правильный ответ кандидата: сам ответ и все засчитываемые варианты.

Отдельным модулем, потому что это связная задача со своими правилами на каждый
род вопросов (персонаж, сюжет, студия, место), а сама карточка кандидата
упёрлась в предел размера. Свойства подключаются в тело SongCandidate обычным
импортом — см. song_candidate.py.

Public namespace: animepack.
"""
from __future__ import annotations
import animepack as _api
from .plot_explanation import candidate_titles, without_titles


# ── правильный ответ ─────────────────────────────────────────────────
@property
def title_with_year(self) -> str:
    """«Название (год)» с тегом песни, если он есть."""
    title = self.title_ru.strip()
    year = self.year
    # У части тайтлов Shikimori сам держит год в названии («Могучий Атом
    # (2003)») — второй раз его дописывать не надо, а тег песни встаёт
    # перед годом («Могучий Атом OP1 (2003)»).
    if year:
        title = _api.re.sub(rf"\s*\(\s*{year}\s*\)\s*$", "", title)
    tag = self.tag
    if tag:
        title = f"{title} {tag}"
    if year:
        title = f"{title} ({year})".strip()
    return title

@property
def main_answer(self) -> str:
    """«Русское название OP1 (год) — 『Песня』». У вопроса-персонажа на месте
    песни стоит имя персонажа: «Название (2020) — 『Имя』». Без того и
    другого остаётся просто название с годом — так и просили."""
    title = self.title_with_year
    if self.is_studio and self.studio_name:
        # Три кадра уже из трёх разных франшиз, поэтому единственный
        # общий и правильный ответ — сама студия, без названия тайтла.
        return self.studio_name
    if self.is_character and self.char_name:
        return f"{title} — 『{self.char_name}』"
    if self.song_name:
        if self.song_alternates:
            placements = [(self.anime, self.song)] + [
                (row.get("anime") or {}, row.get("song") or {})
                for row in self.song_alternates]
            title = " / ".join(_placement_title(card, song)
                               for card, song in placements)
        return f"{title} — 『{self.song_name}』"
    return title

def answer_variants(self) -> list[str]:
    """Все засчитываемые варианты ответа: основной, голое русское название и
    остальные имена тайтла с Shikimori (ромадзи, английское, «лицензировано
    в РФ под названием», синонимы). Дубли схлопываются без учёта регистра —
    SIGame сверяет ответы построчно.

    Порядок: сперва основной ответ, потом ИНЫЕ названия (ромадзи,
    английское, лицензионное, синонимы), а голое русское название — в самом
    конце: сразу после основного оно смотрится копией («Повар-боец Сома
    (2014), Повар-боец Сома…»).

    Отдельные иероглифические варианты не берём: ведущему их не прочитать, а
    игроку не набрать. Но основной русский ответ сохраняется целиком, даже
    когда внутри него японскими символами написано настоящее название песни.
    """
    if self.plot_answers:
        # Вопрос по сюжету с ответом-ДЕТАЛЬЮ: тайтл в таком вопросе назван
        # прямо, а угадывают саму деталь — её написания и засчитываем.
        # Страница вики, с которой взят пересказ, идёт последней строкой:
        # ведущему видно, откуда вопрос, и спорный ответ можно свериться.
        short = self.plot_answers[0]
        expanded = without_titles(
            _expanded_plot_answer(short, self.plot_explanation),
            candidate_titles(self))
        return _api._dedup_answers([expanded] + list(self.plot_answers)
                                   + [self.source_link])
    if self.kind == _api.PLOT_KIND:
        variants = ([without_titles(self.plot_explanation, candidate_titles(self))]
                    if self.plot_explanation else []) + [self.main_answer]
    else:
        variants = [self.main_answer]
    if self.is_studio:
        # Засчитывается имя ЛЮБОЙ из студий тайтла: у совместных работ их
        # две-три, и «Студия Пьеро» там не вернее «A-1 Pictures». Названия
        # аниме среди вариантов нет вовсе — вопрос не о нём.
        variants.extend(self.studios)
        return _api._dedup_answers(variants)
    if self.is_character:
        # В вопросе-персонаже угадывают ПЕРСОНАЖА, а не тайтл: голое
        # название аниме верным ответом быть не должно, иначе вопрос
        # решается с одного взгляда на постер.
        #
        # Название произведения пишется РОВНО ОДИН РАЗ — в основном ответе,
        # а доп-варианты состоят из одних только других имён персонажа
        # (просьба пользователя). Раньше каждое имя дублировалось ещё и в
        # паре с названием, и список ответов выглядел как десять почти
        # одинаковых строк.
        variants.extend(self.char_names)
        if self.cover_link:
            variants.append(self.cover_link)
        if self.source_link:
            variants.append(self.source_link)
        return _api._dedup_answers(variants)
    variants.append(self.anime.get("name"))            # ромадзи
    variants.append(self.anime.get("english"))
    for syn in (self.anime.get("synonyms") or []):
        variants.append(syn)
    variants.append(self.anime.get("licenseNameRu"))   # «Лицензировано в РФ»
    if not self.is_character and not self.is_studio:
        variants.append(self.popular_franchise_title)
    for row in self.song_alternates:
        card = row.get("anime") or {}
        variants.extend([card.get("russian"), card.get("name"),
                         card.get("english"), card.get("licenseNameRu")])
        variants.extend(card.get("synonyms") or [])
    if self.adapted_from:
        # У вопроса по манге с экранизацией засчитываются и ВСЕ русские
        # названия самого аниме. Shikimori нередко держит привычный перевод
        # лишь в synonyms (например «Перерождение сильнейшего экзорциста в
        # другом мире»), поэтому одного поля russian недостаточно.
        variants.append(self.adapted_from.get("russian"))
        variants.append(self.adapted_from.get("licenseNameRu"))
        variants.extend(
            syn for syn in (self.adapted_from.get("synonyms") or [])
            if _api.re.search(r"[А-Яа-яЁё]", str(syn or "")))
    variants.append(self.title_ru)                     # то же, но без года
    if self.art_link:
        # Адрес арта на Pixiv — последней строкой (просьба пользователя):
        # назвать его никто не назовёт, зато в редакторе и у ведущего
        # сразу видно, откуда взята картинка.
        variants.append(self.art_link)
    if self.cover_link:
        # То же самое для кавера: последней строкой — адрес ролика, из
        # которого взято исполнение (просьба пользователя).
        variants.append(self.cover_link)
    if self.source_link:
        # И для остальных вопросов «откуда картинка»: глава на MangaDex,
        # пост на Sakugabooru, страница вики с
        # пересказом (просьба пользователя).
        variants.append(self.source_link)
    return _api._dedup_answers(variants)


def _expanded_plot_answer(keyword: str, explanation: str) -> str:
    """Первый ответ объясняет факт и явно называет то, что засчитывается."""
    keyword = str(keyword or "").strip()
    explanation = str(explanation or "").strip()
    if not explanation:
        return keyword
    exact = (keyword and _api.re.search(
        rf"(?<!\w){_api.re.escape(keyword)}(?!\w)", explanation,
        _api.re.IGNORECASE))
    if keyword and not exact:
        return f"{keyword} — {explanation}"
    return explanation


def _placement_title(card: dict, song: dict) -> str:
    title = str(card.get("russian") or card.get("name") or "").strip()
    try:
        year = int((card.get("airedOn") or {}).get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    if year:
        title = _api.re.sub(rf"\s*\(\s*{year}\s*\)\s*$", "", title)
    tag = _api.song_tag(song.get("songType"))
    if tag:
        title += f" {tag}"
    if year:
        title += f" ({year})"
    return title.strip()

