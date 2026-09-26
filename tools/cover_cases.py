# -*- coding: utf-8 -*-
"""Labelled real YouTube titles for the metadata gate, plus the probe song set.

Сама разметка лежит ДАННЫМИ — tools/cover_cases.json. Питоновским литералом она
была, пока случаев было полторы сотни; на нынешних трёх с лишним сотнях он
перевалил бы предел размера файла, а diff новой разметки утонул бы в кавычках.
Здесь остались только чтение и договор о метках.

Заголовки НАСТОЯЩИЕ и целиком: собраны `cover_probe.py --collect`, обрезанный
заголовок теряет маркер исполнения, и разметка по нему была бы недействительной.
Метки поставлены глазами:

    "cover" — новое ИСПОЛНЕНИЕ нужной композиции; гейт обязан пропустить
    "junk"  — мусор КАТЕГОРИИ: оригинал, автозалив «— Topic», реакция,
              туториал, сборник, субтитры поверх оригинала, off-vocal,
              nightcore, ИИ-перепевка. Звук такое пропускает насквозь (на
              замерах 314, 113 и 371 очка при пороге 60), поэтому отсечь его
              может ТОЛЬКО гейт, и только эти утечки портят пак
    "other" — настоящее исполнение, но ДРУГОЙ песни: «Ima Koko Kara» вместо
              «Ima Koko», кавер соседнего OP/ED, песня с похожей фразой в
              названии. Это вопрос тождества, его уверенно решает звук, так
              что утечка стоит одной лишней загрузки, а не плохого вопроса

Неоднозначные по существу случаи в корпус не взяты: мерить точность по примерам,
где сам ответ спорен, нельзя. Одно и то же видео под разными песнями размечено
раздельно — кавер опенинга для эндинга того же аниме это «other».

Песни размечаются ЦЕЛИКОМ: у выбранной песни метку получают все найденные
кандидаты. Разметить «интересные» заголовки из многих песен было бы дешевле, но
отбор подстраивался бы под сам гейт, и точность вышла бы придуманной.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "cover_cases.json"
LABELS = ("cover", "junk", "other")


def load(path=DATA) -> dict:
    """Разметка целиком: {"probe_mal_ids", "songs", "cases"}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = {row[5] for row in data["cases"]} - set(LABELS)
    if unknown:
        raise ValueError(f"неизвестные метки: {sorted(unknown)}")
    missing = {row[0] for row in data["cases"]} - set(data["songs"])
    if missing:
        raise ValueError(f"случаи ссылаются на неизвестные песни: {sorted(missing)}")
    return data


# Пробный набор аниме для --collect. Подобран так, чтобы в нём были: очень
# популярный OP, средние OP/ED, редкие ED, тайтл с тремя ED (коллизии внутри
# одного аниме), тайтл, где название ЭНДИНГА совпадает с названием самого аниме
# (вырожденное имя, см. cover_meta), вставки, песня с обиходным английским
# названием («again», «Torches» — сотни чужих песен зовутся так же),
# инструментальный оригинал («Tank!») и эндинг, который сам является кавером
# джазового стандарта («Fly Me to the Moon»).
PROBE_MAL_IDS = tuple(load()["probe_mal_ids"])


def songs(path=DATA) -> dict:
    """{ключ: строка AnisongDB} — для звуковой пробы нужен ещё и `audio`."""
    return load(path)["songs"]


def labelled_cases(path=DATA):
    """[(song_ref, заголовок, канал, секунды, метка)] — то, что ест cover_probe."""
    import cover_meta
    data = load(path)
    refs = {key: cover_meta.song_ref(row, row.get("siblings") or ())
            for key, row in data["songs"].items()}
    return [(refs[key], title, channel, duration, label)
            for key, _vid, duration, channel, title, label in data["cases"]]
