# -*- coding: utf-8 -*-
"""Cover-pipeline probe: collect real YouTube candidates, score the metadata gate.

Этап 1 проверяет САМОЕ РИСКОВАННОЕ звено — гейт по заголовку. Проверка звука
(cover_audio) отвечает «та ли это композиция» и на замерах не дала ни одного
ложного срабатывания, но реакция, туториал, lyric-видео и сырой рип содержат ту
же музыку и проходят её насквозь. Значит precision всей функции держится на
этом гейте, и его цену надо знать заранее.

    python tools/cover_probe.py --collect            # сеть: собрать корпус
    python tools/cover_probe.py --meta-only          # без сети: оценить гейт
    python tools/cover_probe.py --meta-only --show-ok

`--meta-only` работает по разметке из tools/cover_cases.py, а с `--corpus`
берёт свежесобранный JSON (там разметки нет — печатает только вердикты).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cover_meta                                                # noqa: E402
import cover_search                                              # noqa: E402

ANISONG = "https://anisongdb.com/api/mal_ids_request"
CORPUS = Path(__file__).resolve().parent / "cover_corpus.json"


def run(cmd, timeout=90):
    """(код, stdout, stderr). Кодировка задана явно: без неё Windows берёт
    cp1251 и японские заголовки приезжают кракозябрами."""
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 1, "", "истекло время ожидания"
    except OSError as error:
        return 1, "", str(error)
    return done.returncode, done.stdout, done.stderr


def ytdlp_cmd():
    for name in ("yt-dlp.exe", "yt-dlp"):
        exe = Path(__file__).resolve().parent.parent / "bin" / name
        if exe.is_file():
            return [str(exe)]
    return [sys.executable, "-m", "yt_dlp"]


def songs_for(mal_ids):
    """Строки AnisongDB по MAL id (прямой запрос, без импорта приложения)."""
    import urllib.request
    payload = json.dumps({"mal_ids": [int(i) for i in mal_ids]}).encode("utf-8")
    request = urllib.request.Request(
        ANISONG, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "SI-HYX-probe"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        rows = json.loads(answer.read().decode("utf-8"))
    return [r for r in rows if r.get("audio") and r.get("songName")]


def collect(mal_ids, per_song, out_path):
    """Поиск по каждой песне -> JSON с СЫРЫМИ кандидатами (без вердиктов).

    Заголовки сохраняем целиком: обрезанный заголовок теряет маркер исполнения,
    и разметка по нему была бы недействительной."""
    base, entries = ytdlp_cmd(), []
    rows = songs_for(mal_ids)
    # Соседние песни того же аниме — бесплатно из того же ответа AnisongDB, а
    # закрывают самую неприятную коллизию (кавер другого OP/ED этого тайтла).
    family: dict = {}
    for row in rows:
        family.setdefault(row.get("annId"), []).append(str(row.get("songName") or ""))
    for row in rows:
        siblings = [n for n in family.get(row.get("annId"), [])
                    if n and n != row.get("songName")]
        song = cover_meta.song_ref(row, siblings)
        started = time.perf_counter()
        raw = []
        for query, limit, stage in cover_search.queries(song):
            if stage > 2:
                continue
            raw.extend(cover_search.search(query, limit, run, base))
        raw = cover_search.dedup(raw)
        keep = ("annId", "annSongId", "songName", "songArtist", "songType",
                "animeENName", "animeJPName", "animeAltName", "songLength", "audio")
        entries.append({"song": dict({k: row.get(k) for k in keep},
                                     siblings=siblings),
                        "candidates": raw})
        print(f"{row['songType']:11} {row['songName'][:34]:34} "
              f"{len(raw):3d} кандидатов  {time.perf_counter() - started:.1f}s")
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    total = sum(len(e["candidates"]) for e in entries)
    print(f"\n{len(entries)} песен, {total} кандидатов -> {out_path}")


def gate_quality(counts) -> dict:
    """Три класса -> три числа, которыми и меряется гейт.

    Живут здесь, а не в печати: этими же числами tests/test_cover_corpus.py
    держит порог, чтобы «улучшение», уронившее точность пака, валило прогон, а
    не оставалось незамеченным в логе."""
    kept, lost = counts["cover"]
    junk_in, other_in = counts["junk"][0], counts["other"][0]
    accepted = kept + junk_in + other_in
    return {"recall": kept / max(1, kept + lost),
            "category": 1.0 - junk_in / max(1, accepted),
            "waste": other_in / max(1, accepted), "accepted": accepted}


def score_gate(labelled, show_ok=False):
    """Гейт против разметки. Считаем ТРИ класса, а не два.

    Цена утечки зависит от её рода. «junk» (оригинал, реакция, туториал,
    off-vocal, ИИ-перепевка) звук пропускает насквозь — такая утечка портит
    вопрос, и только она определяет точность функции. «other» — настоящее
    исполнение ДРУГОЙ песни; его звук отвергает уверенно (0 ложных на ~140
    парах), так что утечка стоит одной лишней загрузки."""
    counts = {k: [0, 0] for k in ("cover", "junk", "other")}   # [прошло, нет]
    reasons: dict = {}
    mistakes = []
    for song, title, channel, duration, label in labelled:
        verdict = cover_meta.classify(title, channel, duration, song)
        passed = verdict["state"] == "ok"
        counts.setdefault(label, [0, 0])[0 if passed else 1] += 1
        if label == "cover" and not passed:
            mistakes.append(("ПОТЕРЯН кавер", verdict["reason"], title))
        elif label == "junk" and passed:
            mistakes.append(("ПРОПУЩЕН мусор", verdict["type"], title))
        elif label == "other" and passed:
            mistakes.append(("не та песня", verdict["strength"], title))
        elif show_ok and label == "cover":
            mistakes.append((f"ok/{verdict['strength']}", verdict["type"], title))
        if not passed:
            reasons[verdict["reason"]] = reasons.get(verdict["reason"], 0) + 1
    return counts, reasons, mistakes


def meta_only(show_ok):
    from cover_cases import labelled_cases
    cases = labelled_cases()
    counts, reasons, mistakes = score_gate(cases, show_ok)
    kept, lost = counts["cover"]
    junk_in, junk_out = counts["junk"]
    other_in, other_out = counts["other"]
    print(f"корпус: {len(cases)} заголовков — {kept + lost} каверов, "
          f"{junk_in + junk_out} мусора, {other_in + other_out} другой песни\n")
    for kind, detail, title in mistakes:
        print(f"  {kind:16} {detail:22} {title[:74]}")
    quality = gate_quality(counts)
    recall, category, waste = (quality["recall"], quality["category"],
                               quality["waste"])
    print(f"\n  принято каверов      {kept:3d}/{kept + lost:<3d}   recall          {recall:.3f}")
    print(f"  мусора КАТЕГОРИИ     {junk_in:3d}/{junk_in + junk_out:<3d}   "
          f"точность пака   {category:.3f}   <- это и есть цена функции")
    print(f"  утечек ТОЖДЕСТВА     {other_in:3d}/{other_in + other_out:<3d}   "
          f"лишних загрузок {waste:.3f}   <- их отвергнет звук")
    print("  причины отказов: " + ", ".join(
        f"{name}={count}" for name, count in sorted(reasons.items(),
                                                    key=lambda kv: -kv[1])))
    # Гейт годен, если пак не портится и лишняя работа умеренная.
    return 0 if category >= 0.98 and waste <= 0.25 else 1


def corpus_only(path):
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    for entry in entries:
        song = cover_meta.song_ref(entry["song"], entry["song"].get("siblings") or ())
        pool, bad = cover_meta.screen(entry["candidates"], song, limit=99)
        print(f"\n=== {entry['song']['songType']} «{entry['song']['songName']}» "
              f"— годных {len(pool)} из {len(entry['candidates'])}")
        for row in pool:
            print(f"   + {row['strength']:6} {row['type']:10} "
                  f"{row['duration']:4d}s {row['title'][:66]}")
        for row in bad:
            print(f"   - {row['reason']:22} {row['duration']:4d}s "
                  f"{row['title'][:66]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true",
                        help="сеть: собрать корпус кандидатов в JSON")
    parser.add_argument("--meta-only", action="store_true",
                        help="без сети: оценить гейт по разметке cover_cases")
    parser.add_argument("--corpus", default="", help="JSON вместо разметки")
    parser.add_argument("--show-ok", action="store_true",
                        help="печатать и принятых, а не только ошибки")
    parser.add_argument("--mal", default="",
                        help="MAL id через запятую (по умолчанию — набор проб)")
    parser.add_argument("--per-song", type=int, default=30)
    parser.add_argument("--out", default=str(CORPUS))
    args = parser.parse_args()

    if args.collect:
        from cover_cases import PROBE_MAL_IDS
        ids = ([int(x) for x in args.mal.split(",") if x.strip()]
               if args.mal else PROBE_MAL_IDS)
        collect(ids, args.per_song, Path(args.out))
        return 0
    if args.corpus:
        return corpus_only(args.corpus)
    if args.meta_only:
        return meta_only(args.show_ok)
    parser.print_help()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
