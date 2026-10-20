# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Кто проверяет картинки пака: Gemini или только локальные модели.

В режиме OCR ни одна визуальная проверка не ходит в Gemini: кадры, студии,
кадры с эффектами, арты Pixiv, страницы манги и видеоряд опенингов сверяются
с названиями тайтла локально (local_visual_ocr + local_title_match),
персонажей в кадрах и студиях ищет детектор голов (local_character_detect),
он же выбирает сцену вебтуна (local_scene). Рисовку Pixiv и чужие франшизы
на арте локально не оценить: Pixiv отсекает их только по меткам.
Отрывки серий (проверка сцены со звуком, перевод субтитров) — не визуальная
проверка и остаются на Gemini."""
from __future__ import annotations

import copy

GEMINI = "gemini"
OCR = "ocr"
MODES = (GEMINI, OCR)
# Сходство надписи с названием, с которого сомнительный кадр бракуется
# (нижняя граница «uncertain» в local_title_match.decide).
SIMILAR = 82.0


def ocr_only(settings) -> bool:
    return getattr(settings, "visual_checker", GEMINI) == OCR


def effective(settings):
    """Копия настроек, в которой все визуальные проверки локальные.

    Флаги секций переводятся один раз здесь, чтобы весь генератор видел
    согласованную картину: «название — локально», без досмотра Gemini.
    Выбор сцены манги (manga_character_crop) остаётся как выбран: его делает
    local_scene."""
    if not ocr_only(settings):
        return settings
    # copy, а не dataclasses.replace: from_dict может добавить поля вне
    # объявленных, и replace потерял бы их.
    local = copy.copy(settings)
    local.pixiv_title_check_mode = "local"
    local.pixiv_gemini_check = False
    local.manga_title_check_mode = "local"
    return local


def frame_verdict(generator, candidate, data: bytes) -> dict:
    """Вердикт кадра в форме frame_visual_check.check, но локально.

    Надпись сверяет OCR, персонажей ищет детектор голов
    (local_character_detect). Надпись, похожая на название, бракует кадр так
    же, как узнанное название, — переспросить некого, а кадров у тайтла
    хватает."""
    from .local_character_detect import has_characters
    from .local_title_match import decide, titles
    from .local_visual_ocr import note, read
    rows, elapsed, cached = read(generator, data)
    result = decide(rows, titles(candidate.anime or {}))
    # «uncertain» бывает двух видов: надпись почти совпала с названием (порог
    # decide — от 82%) или текст просто нечитаем (японские вывески, сходство
    # 5–40%). Бракуем только первый: в пробном паке второй дал 31 ложный отказ.
    reject = result["status"] == "title" or (result["status"] == "uncertain"
                                              and result["similarity"] >= SIMILAR)
    note(generator, "кадра", result, elapsed, cached, False)
    people = False if reject else has_characters(generator, data)
    reason = (f"OCR: «{result['ocr']}» ≈ «{result['title']}»" if reject
              else "персонажей в кадре нет" if not people
              else "названия не видно, персонажи есть")
    return {"accept": not reject, "has_title_text": reject,
            "has_characters": people, "reason": reason}
