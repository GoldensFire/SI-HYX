# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# tools/clean_cover_cache.py — выбросить из кладовой каверов осечки, которые
# записаны не про ролик, а про стенку YouTube.
#
# Откуда взялось. Пока `cover_search.fatal_reason` не знал про отказ по частоте
# запросов, а `trim_error` резал stderr с хвоста, поломка ВСЕГО поиска попадала
# в кладовую как «этот ролик не скачался». Один живой прогон пометил так 362
# кандидата, у 18 песен — все двенадцать разом; в кладовой на момент разбора
# лежало 2929 таких записей, 87% из них — хвост от «Sign in to confirm you're
# not a bot».
#
# Сейчас у осечек есть срок (cover_cache.FAIL_TTL_DAYS), поэтому кладовая
# вылечилась бы и сама — через двое суток. Этот скрипт нужен, чтобы не ждать.
#
# Вердикты звука (`audio`), находки поиска (`videos`) и историю использования
# (`use`) НЕ трогает: они про сам звук и стенкой не испорчены.
#
# Запуск:
#   python tools/clean_cover_cache.py            # только посчитать
#   python tools/clean_cover_cache.py --apply    # и вправду переписать
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cover_cache  # noqa: E402  — путь к проекту добавлен выше

# Приметы «это не ролик виноват». Часть повторяет cover_search.FATAL_MARKS, но
# список здесь СВОЙ и длиннее нарочно: в кладовой лежат записи, сделанные
# прежним trim_error, — у них от сообщения остался только хвост, и приметы в
# начале абзаца («Sign in to confirm…») в них уже нет.
WALL_MARKS = (
    # Стенка «подтвердите, что вы не робот» — по хвосту ссылки на вики.
    "pass-cookies-to-yt-dlp",
    "how to manually pass cookies",
    "sign in to confirm",
    "not a bot",
    # Отказ по частоте запросов.
    "exceeding the rate limit",
    "try again later",
    "isnt-available-try-again-later",
    "sleep-requests",
    "delay between video requests",
    "http error 429",
    "too many requests",
    "http error 403",
    # Волна легла целиком: ни один ролик не скачался. Ровно так выглядит
    # стенка, и ровно это писалось каждому кандидату волны.
    "yt-dlp не отдал звук",
    "yt-dlp не ответил",
    "yt-dlp не найден",
    "остановлено",
)


def is_wall(reason: str) -> bool:
    """Осечка записана про стенку YouTube, а не про ролик."""
    low = str(reason or "").casefold()
    if not low:
        # Пустая причина — тоже не показание: сказать про ролик нечего.
        return True
    if low.count("video unavailable") > 1:
        # Несколько «Video unavailable» в одном сообщении — это стенка на
        # волну из нескольких ссылок, а не один снятый ролик.
        return True
    return any(mark in low for mark in WALL_MARKS)


def clean_entry(entry: dict) -> tuple[dict, int, int]:
    """(запись без осечек-стенок, сколько выброшено, сколько оставлено)."""
    fail = entry.get("fail")
    if not isinstance(fail, dict):
        return entry, 0, 0
    kept = {vid: row for vid, row in fail.items()
            if not is_wall((row or {}).get("reason"))}
    gone = len(fail) - len(kept)
    if not gone:
        return entry, 0, len(kept)
    out = dict(entry)
    if kept:
        out["fail"] = kept
    else:
        out.pop("fail", None)
    return out, gone, len(kept)


def sweep(directory: str, apply: bool = False) -> tuple[int, int, int]:
    """(песен тронуто, осечек выброшено, осечек оставлено)."""
    songs = dropped = kept = 0
    try:
        names = sorted(os.listdir(directory))
    except OSError as error:
        print(f"Кладовая не читается: {error}")
        return 0, 0, 0
    for name in names:
        if not name.endswith(".json"):
            continue
        file = os.path.join(directory, name)
        try:
            with open(file, encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        fresh, gone, left = clean_entry(entry)
        kept += left
        if not gone:
            continue
        songs += 1
        dropped += gone
        if not apply:
            continue
        tmp = f"{file}.clean.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(fresh, handle, ensure_ascii=False)
            os.replace(tmp, file)
        except OSError as error:
            print(f"  {name}: не переписалось — {error}")
            try:
                os.remove(tmp)
            except OSError:
                pass
    return songs, dropped, kept


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Убрать из кладовой каверов осечки, записанные про стенку "
                    "YouTube, а не про ролик.")
    parser.add_argument("--apply", action="store_true",
                        help="переписать файлы (без него — только посчитать)")
    parser.add_argument("--dir", default=cover_cache.CACHE_DIR,
                        help="папка кладовой (по умолчанию — рядом с настройками)")
    args = parser.parse_args(argv)

    print(f"Кладовая: {args.dir}")
    songs, dropped, kept = sweep(args.dir, apply=args.apply)
    if not dropped:
        print("Осечек-стенок не нашлось — чистить нечего.")
        return 0
    what = "выброшено" if args.apply else "нашлось (не тронуто)"
    print(f"Осечек про стенку {what}: {dropped} у {songs} песен.")
    print(f"Осечек про сами ролики оставлено: {kept}.")
    if not args.apply:
        print("Повторите с --apply, чтобы и вправду переписать.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
