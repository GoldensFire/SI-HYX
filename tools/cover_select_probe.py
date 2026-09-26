# -*- coding: utf-8 -*-
"""Стенд этапа 3: кэш и политика выбора кавера.

Вопрос этапа — не «та ли композиция» (на него отвечают cover_meta и
cover_match), а «что увидит игрок, если генерировать паки год подряд». Стенд
берёт настоящие вердикты стенда звука (tools/cover_audio_probe.py: 15 песен,
193 кандидата, хрома уже посчитана в feat/), складывает их в НАСТОЯЩИЙ
cover_cache во временной папке и разыгрывает 52 пака — по одному в неделю.

    python tools/cover_select_probe.py            # без сети, ~15 с
    python tools/cover_select_probe.py --packs 52 --policy all

Сравниваются три политики: «лучший по счёту», «равновероятно» и нынешняя
(уверенность × разнообразие типов × остывание). Печатается, сколько РАЗНЫХ
роликов и РАЗНЫХ участков успевает прозвучать, сколько раз кавер повторился
подряд и попадает ли выбранный участок в то место песни, которое запросил
генератор (trim_start).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                # noqa: E402

import cover_cache as cache                                       # noqa: E402
import cover_match as match                                       # noqa: E402
import cover_meta                                                 # noqa: E402
import cover_select as select                                     # noqa: E402
from cover_cases import load as load_cases                        # noqa: E402

BENCH = Path(tempfile.gettempdir()) / "si_hyx_cover_bench"
WEEK = 7 * 86400.0
PACKS = 52
REF_SECONDS = 90.0          # эталоны AMQ: полторы минуты


def build(bench: Path, work: Path) -> dict:
    """Настоящий кэш из настоящих вердиктов стенда звука ({песня: пул})."""
    cache.CACHE_DIR = str(work)
    wanted = json.loads((bench / "wanted.json").read_text(encoding="utf-8"))
    feats = {p.stem: np.load(p) for p in sorted((bench / "feat").glob("*.npy"))}
    songs = load_cases()["songs"]
    rows = collections.defaultdict(list)
    for cand in wanted:
        rows[cand["song"]].append(cand)
    refs = {}
    started = time.perf_counter()
    for key, cands in sorted(rows.items()):
        ref_key = f"ref_{key}"
        if ref_key not in feats:
            continue
        cache.put_ref_chroma(key, feats[ref_key])
        found = [{"id": c["id"], "title": c["title"], "channel": "",
                  "duration": 200, "views": 1000} for c in cands]
        cache.remember_search(key, found, queries=["стенд"], found=len(found),
                              song=songs[key].get("songName") or key)
        for cand in cands:
            feat = feats.get(f"cand_{cand['id']}")
            if feat is None:
                continue
            verdict = match.verify(feats[ref_key], feat,
                                   strength=cand["strength"] or "weak")
            cache.remember_audio(key, cand["id"], verdict, verdict["good"])
        refs[key] = cover_meta.song_ref(songs[key], songs[key].get("siblings") or ())
    print(f"кэш собран за {time.perf_counter() - started:.0f} с")
    return refs


def pools(refs) -> dict:
    """{песня: подтверждённые каверы} — чтением из кэша, как в генераторе."""
    out = {}
    for key, song in sorted(refs.items()):
        entry = cache.load(key)
        pool, _bad = cache.screened(entry, song)
        good = cache.confirmed(pool)
        if good:
            out[key] = good
    return out


def one_pack(policy, songs, refs, rng, now):
    """Один пак: по кандидату на песню. Возвращает [(песня, id, ref_at)]."""
    picks, seen_types = [], collections.Counter()
    for key in songs:
        entry = cache.load(key)
        pool, _bad = cache.screened(entry, refs[key])
        rows = cache.confirmed(pool)
        if not rows:
            continue
        prefer = round(rng.uniform(0.0, REF_SECONDS - match.WANT_SECONDS), 1)
        if policy == "top":
            row = max(rows, key=lambda r: r["norm"])
            spot = match.choose(row["windows"], rng, prefer)
            got = dict(row, ref_at=spot["at"]) if spot else {}
        elif policy == "uniform":
            row = rng.choice(rows)
            spot = match.choose(row["windows"], rng, prefer)
            got = dict(row, ref_at=spot["at"]) if spot else {}
        else:
            got = select.pick(rows, rng=rng, now=now,
                              skip=cache.last_used(entry),
                              seen_types=seen_types, prefer=prefer)
        if not got:
            continue
        seen_types[got.get("type") or ""] += 1
        picks.append((key, got["id"], got["ref_at"], got.get("type") or "",
                      prefer))
        if policy == "policy":
            cache.remember_use(key, got["id"], got["ref_at"], when=now)
    return picks, seen_types


def reset_uses(refs):
    """Забыть историю использования — чтобы политики сравнивались с нуля."""
    for key in refs:
        entry = cache.load(key)
        entry.pop("use", None)
        entry.pop("last", None)
        cache.save(key, entry)


def simulate(policy, refs, packs, seed=7):
    reset_uses(refs)
    ready = pools(refs)
    songs = sorted(ready)
    rng = random.Random(seed)
    now = time.time()
    used = collections.defaultdict(list)
    spots = collections.defaultdict(set)
    repeats, hits, total = 0, 0, 0
    types_per_pack = []
    for number in range(packs):
        picks, seen = one_pack(policy, songs, refs, rng, now + number * WEEK)
        for key, vid, ref_at, _kind, prefer in picks:
            if used[key] and used[key][-1] == vid:
                repeats += 1
            used[key].append(vid)
            spots[key].add(round(ref_at / select.WINDOW_GAP))
            total += 1
            hits += abs(ref_at - prefer) <= match.WINDOW_STEP
        types_per_pack.append(len(seen))
    videos = [len(set(v)) for v in used.values()]
    have = [len(ready[key]) for key in used]
    top = [collections.Counter(v).most_common(1)[0][1] / len(v)
           for v in used.values()]
    return {"policy": policy, "picks": total, "repeats": repeats,
            "videos": sum(videos) / max(1, len(videos)),
            "have": sum(have) / max(1, len(have)),
            "spots": sum(len(s) for s in spots.values()) / max(1, len(spots)),
            "top_share": sum(top) / max(1, len(top)),
            "types": sum(types_per_pack) / max(1, len(types_per_pack)),
            "prefer_hit": hits / max(1, total)}


# Замеренная цена одного кандидата: загрузка формата 139 и разбор (декод 0.5 с,
# хрома 0.8 с, вердикт 0.02 с) — см. tools/cover_audio_probe.py.
FETCH_SECONDS = 1.2
CPU_SECONDS = 1.3


def cost(refs, want, parallel=6):
    """Сколько кандидатов придётся ПОСЛУШАТЬ, чтобы набрать `want` каверов.

    Порядок тот же, каким их отдаёт гейт (сперва назвавшие песню), и волнами —
    ровно как в cover_service.ensure. Вердикты настоящие, со стенда звука."""
    listened, waits, reached = [], [], 0
    for key, song in sorted(refs.items()):
        entry = cache.load(key)
        pool, _bad = cache.screened(entry, song)
        good = {row["id"] for row in cache.confirmed(pool)}
        todo, taken, ok, wall = list(pool), 0, 0, 0.0
        while todo and ok < want:
            need = want - ok
            wave, todo = todo[:need], todo[need:]
            taken += len(wave)
            ok += sum(row["id"] in good for row in wave)
            # Волна идёт параллельно: её цена — самый долгий кандидат.
            wall += (FETCH_SECONDS + CPU_SECONDS) * max(
                1, (len(wave) + parallel - 1) // parallel)
        listened.append(taken)
        waits.append(wall)
        reached += ok >= want
    listened.sort()
    waits.sort()
    middle = len(listened) // 2
    print(f"{chr(10)}Первый пак, нужно {want} подтверждённых кавера на песню:")
    print(f"  слушаем кандидатов: медиана {listened[middle]}, "
          f"максимум {listened[-1]}, всего {sum(listened)} на "
          f"{len(listened)} песен")
    print(f"  набрали нужное: {reached} песен из {len(listened)}")
    print(f"  ждём проверки: медиана {waits[middle]:.1f} с, "
          f"максимум {waits[-1]:.1f} с при {parallel} потоках "
          f"(плюс 6 с поиск и 0.8 с хрома эталона — по одному разу навсегда)")
    print("  следующие паки: ноль загрузок на проверку, одна на резку выбранного")
    return listened


def report(rows, work: Path):
    print(f"\n{'политика':10} {'роликов':>8} {'из':>5} {'участков':>9} "
          f"{'доля топ-1':>11} {'типов/пак':>10} {'подряд':>7} {'то место':>9}")
    for row in rows:
        print(f"{row['policy']:10} {row['videos']:8.1f} {row['have']:5.1f} "
              f"{row['spots']:9.1f} {row['top_share']:11.2f} "
              f"{row['types']:10.1f} {row['repeats']:7d} "
              f"{row['prefer_hit']:9.3f}")
    songs, size = cache.stats()
    print(f"\nкладовая: {songs} композиций, {size / 1024:.0f} КиБ "
          f"({size / 1024 / max(1, songs):.1f} КиБ на песню) -> {work}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(BENCH), help="папка стенда звука")
    parser.add_argument("--packs", type=int, default=PACKS)
    parser.add_argument("--policy", default="all",
                        choices=("all", "policy", "top", "uniform"))
    parser.add_argument("--want", type=int, default=3,
                        help="сколько подтверждённых каверов набирать (cover_pool)")
    args = parser.parse_args()
    bench = Path(args.dir)
    if not (bench / "wanted.json").is_file():
        print(f"нет стенда звука в {bench}: сперва "
              f"python tools/cover_audio_probe.py --fetch")
        return 1
    work = bench / "cache_probe"
    refs = build(bench, work)
    names = (("policy", "top", "uniform") if args.policy == "all"
             else (args.policy,))
    report([simulate(name, refs, args.packs) for name in names], work)
    cost(refs, max(1, args.want))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
