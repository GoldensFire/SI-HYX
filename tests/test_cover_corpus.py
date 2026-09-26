# -*- coding: utf-8 -*-
"""Разметка каверов как регрессионная сеть: цифры гейта не должны падать.

Правки в cover_meta_rules выглядят безобидно («добавлю слово в мусорные»), а
стоят recall: слово Sheets в канале однажды убило настоящие фортепианные каверы,
а имя соседней песни, равное имени аниме, — двадцать каверов опенинга. Оба раза
ловил не тест, а ручной прогон пробы. Здесь те же три числа считаются на
размеченном корпусе при каждом `python -m pytest`.

Сети нет: корпус — сохранённые заголовки (tools/cover_cases.json).
"""
import json

import pytest

from tools.cover_cases import LABELS, labelled_cases, load, songs
from tools.cover_probe import gate_quality, score_gate

# Порог выпуска из отчёта по этапу 1. Числа НЕ подогнаны под текущий прогон:
# запас нужен, чтобы обычная правка словаря не валила тест из-за одного
# заголовка, но обвал был виден сразу.
MIN_TITLES = 300         # меньше — выборка слишком мала, чтобы ей верить
MIN_CATEGORY = 0.98      # мусор КАТЕГОРИИ портит вопрос: это цена функции
MAX_WASTE = 0.25         # утечки ТОЖДЕСТВА звук отвергнет, цена — загрузка
# Recall сам по себе порогом выпуска НЕ является, и вот почему: на вопрос нужен
# ОДИН подтверждённый кавер, а не все существующие. Потерянные — это почти
# всегда заголовок без маркера исполнения («Guren No Yumiya | Blinding
# Sunrise») и японское название вместо ромадзи («美しき残酷な世界»), которых в
# метаданных AnisongDB просто нет. Поэтому здесь два разных порога: общий — от
# обвала, а рабочий запас мерится ПО ПЕСНЯМ.
MIN_RECALL = 0.85
MIN_PER_SONG = 4         # замер: у худшей песни корпуса остаётся 5


def test_corpus_is_big_enough_and_covers_all_three_classes():
    cases = labelled_cases()
    assert len(cases) >= MIN_TITLES
    labels = [label for *_rest, label in cases]
    for name in LABELS:
        # Точность, посчитанная на классе из пяти примеров, ничего не значит.
        assert labels.count(name) >= 40, f"мало примеров класса {name}"
    # Песни размечаются целиком, поэтому широта корпуса — это число песен.
    assert len({key for key, *_rest in load()["cases"]}) >= 10


def test_gate_quality_stays_above_the_release_bar():
    counts, _reasons, _mistakes = score_gate(labelled_cases())
    quality = gate_quality(counts)
    assert quality["recall"] >= MIN_RECALL, f"потеряли каверы: {quality}"
    assert quality["category"] >= MIN_CATEGORY, f"мусор в паке: {quality}"
    assert quality["waste"] <= MAX_WASTE, f"лишние загрузки: {quality}"


def test_every_song_keeps_enough_covers_to_choose_from():
    """Запас считается по песням, а не в среднем: средний recall ничего не
    обещает песне, у которой в пуле осталось пусто."""
    import cover_meta
    data = load()
    refs = {key: cover_meta.song_ref(row, row.get("siblings") or ())
            for key, row in data["songs"].items()}
    kept = dict.fromkeys(refs, 0)
    for key, _vid, duration, channel, title, label in data["cases"]:
        if label != "cover":
            continue
        if cover_meta.classify(title, channel, duration, refs[key])["state"] == "ok":
            kept[key] += 1
    thin = {key: count for key, count in kept.items() if count < MIN_PER_SONG}
    assert not thin, f"песни без запаса каверов: {thin}"


def test_songs_carry_everything_the_probes_need():
    for key, row in songs().items():
        assert row.get("annSongId"), key
        assert row.get("songName") and row.get("songType"), key
        # Без `audio` нечего скачать с AMQ, и звуковая проба песню не проверит.
        assert str(row.get("audio") or "").endswith(".mp3"), key
        assert row["songName"] not in (row.get("siblings") or []), key


def test_cases_are_unique_per_song():
    """Один и тот же id под одной песней — копипаста при разметке: такой случай
    молча удваивает вес одного заголовка в статистике."""
    seen = set()
    for key, vid, _duration, _channel, _title, _label in load()["cases"]:
        assert (key, vid) not in seen, f"{key} {vid}"
        seen.add((key, vid))


def test_loader_rejects_broken_markup(tmp_path):
    good = load()
    broken = tmp_path / "bad.json"
    case = list(good["cases"][0])
    case[5] = "maybe"
    broken.write_text(json.dumps(dict(good, cases=[case])), encoding="utf-8")
    with pytest.raises(ValueError):
        load(broken)
    case[5], case[0] = "cover", "нет-такой-песни"
    broken.write_text(json.dumps(dict(good, cases=[case])), encoding="utf-8")
    with pytest.raises(ValueError):
        load(broken)
