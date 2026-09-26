# -*- coding: utf-8 -*-
"""Audio bench: does the chroma+Qmax core really tell this song from any other.

Этап 2 отвечает на один вопрос: КАКОЕ число сравнивать с порогом. Сырой счёт
Qmax растёт с длиной записи, поэтому нужен знаменатель, и выбрать его можно
только замером на настоящих парах «эталон AMQ — кавер с YouTube».

    python tools/cover_audio_probe.py --fetch          # сеть: эталоны + каверы
    python tools/cover_audio_probe.py --score          # без сети: матрица

`--fetch` качает по разметке tools/cover_cases.json: эталон каждой песни с AMQ
и звук кандидатов (формат 139 — 48 кбит/с m4a, ~1.5 МБ). `--score` считает
хрому один раз, потом сравнивает КАЖДОГО кандидата с КАЖДЫМ эталоном: свой
эталон даёт положительную пару, чужие — отрицательные, и их сразу тысячи.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                # noqa: E402

import cover_audio as audio                                       # noqa: E402
import cover_meta                                                 # noqa: E402
from cover_cases import load                                      # noqa: E402

AMQ = "https://naedist.animemusicquiz.com/"
# Записи, размеченные как «другая песня», которые отрицательной парой БЫТЬ НЕ
# МОГУТ: нужная композиция в них действительно звучит. Проверено на ОРИГИНАЛАХ —
# «Chiisana Tenohira» против «Dango Daikazoku» даёт 75.5 очка при чистоте пути
# 0.65 и общем 33-секундном фрагменте (Jun Maeda переиспользовал материал), тогда
# как чужие эталоны между собой дают 14 (медиана) и 29 (максимум).
CONTAINS_SONG = {
    "HLDVlzLWxN0": "двадцатиминутное ассорти по Clannad",
    "UgY-VfEGuxk": "медли из двух песен одного тайтла",
    "Io_H8uqFO10": "общий фрагмент с другой песней того же автора",
}
WORK = Path(tempfile.gettempdir()) / "si_hyx_cover_bench"
# Кандидатов на песню: хватает, чтобы увидеть разброс по типам каверов, и не
# превращает прогон в получасовую загрузку.
PER_SONG = 10


def run(cmd, timeout=180):
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 1, "", "истекло время ожидания"
    except OSError as error:
        return 1, "", str(error)
    return done.returncode, done.stdout, done.stderr


def tool(name):
    local = Path(__file__).resolve().parent.parent / "bin" / f"{name}.exe"
    return str(local) if local.is_file() else name


def pairs(limit=PER_SONG):
    """(песни, кандидаты) по разметке: каверы и ЧУЖИЕ песни, мусор не берём.

    Мусор категории качать незачем: в нём играет тот же оригинал, и звук его
    примет — это уже известно и решается гейтом, а не порогом."""
    data = load()
    songs, wanted = data["songs"], []
    kept = {key: 0 for key in songs}
    for key, vid, duration, channel, title, label in data["cases"]:
        if label == "junk":
            continue
        song = cover_meta.song_ref(songs[key], songs[key].get("siblings") or ())
        verdict = cover_meta.classify(title, channel, duration, song)
        if label == "cover":
            if verdict["state"] != "ok" or kept[key] >= limit:
                continue
            kept[key] += 1
        wanted.append({"song": key, "id": vid, "label": label, "title": title,
                       "type": verdict["type"], "strength": verdict["strength"]})
    return songs, wanted


def fetch_reference(name, path):
    import urllib.request
    request = urllib.request.Request(AMQ + name,
                                     headers={"User-Agent": "SI-HYX-probe"})
    with urllib.request.urlopen(request, timeout=120) as answer:
        path.write_bytes(answer.read())


def fetch_candidate(vid, path):
    code, _out, err = run([tool("yt-dlp"), "-f", "139/140/251/bestaudio",
                           "-o", str(path), "--no-part", "--no-warnings",
                           "--socket-timeout", "20", "--retries", "3",
                           f"https://www.youtube.com/watch?v={vid}"])
    return code == 0 or path.is_file(), err.strip()[:120]


def fetch(work, limit):
    songs, wanted = pairs(limit)
    work.mkdir(parents=True, exist_ok=True)
    todo = []
    for key, row in songs.items():
        target = work / f"ref_{key}.mp3"
        if not target.is_file():
            todo.append(("эталон", key, lambda t=target, n=row["audio"]:
                         fetch_reference(n, t)))
    seen = set()
    for cand in wanted:
        if cand["id"] in seen:
            continue
        seen.add(cand["id"])
        target = work / f"cand_{cand['id']}.m4a"
        if not target.is_file():
            todo.append(("кавер", cand["id"],
                         lambda t=target, v=cand["id"]: fetch_candidate(v, t)))
    print(f"{len(songs)} эталонов, {len(seen)} кандидатов; качать {len(todo)}")
    started = time.perf_counter()
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(job): (kind, name) for kind, name, job in todo}
        for done, (kind, name) in ((f, jobs[f]) for f in futures.as_completed(jobs)):
            try:
                done.result()
                mark = "+"
            except Exception as error:                 # noqa: BLE001 — отчёт
                mark = f"! {error}"
            print(f"  {mark} {kind} {name}")
    print(f"загрузка: {time.perf_counter() - started:.0f} с")
    (work / "wanted.json").write_text(
        json.dumps(wanted, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def features(path, work):
    """Хрома файла, с кешем: декодирование и STFT — самое дорогое здесь."""
    cache = work / "feat" / (path.stem + ".npy")
    if cache.is_file():
        return np.load(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    wav = work / "tmp.wav"
    code, _out, err = run(audio.decode_args(tool("ffmpeg"), path, wav))
    if code or not wav.is_file():
        raise RuntimeError(f"ffmpeg: {err.strip()[:120]}")
    chroma = audio.chroma(audio.read_wav(wav))
    wav.unlink(missing_ok=True)
    np.save(cache, chroma)
    return chroma


def null_score(ref, cover, seed=0):
    """Уровень случайного совпадения для ЭТОЙ пары: та же плотность, но время
    кавера перемешано, поэтому длинных диагоналей быть не должно."""
    rng = np.random.default_rng(seed)
    shuffled = cover[rng.permutation(cover.shape[0])]
    return audio.align(ref, shuffled)["score"]


def score(work, out_path):
    wanted = json.loads((work / "wanted.json").read_text(encoding="utf-8"))
    refs, rows = {}, []
    for path in sorted(work.glob("ref_*.mp3")):
        refs[path.stem[4:]] = features(path, work)
    print("эталоны: " + ", ".join(f"{k}={v.shape[0]}" for k, v in refs.items()))
    started = time.perf_counter()
    for number, cand in enumerate(wanted, 1):
        path = work / f"cand_{cand['id']}.m4a"
        if not path.is_file():
            continue
        try:
            chroma = features(path, work)
        except (RuntimeError, ValueError) as error:
            print(f"  ! {cand['id']}: {error}")
            continue
        row = dict(cand, frames=int(chroma.shape[0]), scores={}, spans={})
        for name, ref in refs.items():
            result = audio.align(ref, chroma)
            row["scores"][name] = round(result["score"], 2)
            if name == cand["song"]:
                row["null"] = round(null_score(ref, chroma), 2)
                row["tempo"] = round(result["tempo"], 3)
                row["ref_frames"] = int(ref.shape[0])
                row["spans"] = {"ref": result["ref_span"],
                                "cov": result["cov_span"]}
        rows.append(row)
        print(f"  {number:3d}/{len(wanted)} {cand['label']:5} {cand['song']:12} "
              f"своя {row['scores'][cand['song']]:7.1f} "
              f"чужая {max(v for k, v in row['scores'].items() if k != cand['song']):7.1f} "
              f"null {row['null']:6.1f}  {cand['title'][:44]}")
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"\n{len(rows)} кандидатов, {len(rows) * len(refs)} пар, "
          f"{time.perf_counter() - started:.0f} с -> {out_path}")
    return 0


def report(work):
    """Вердикты cover_match на всём стенде: recall, ложные, окна.

    Это и есть воспроизводимый замер, на котором стоят пороги cover_match."""
    import random

    import cover_match

    wanted = json.loads((work / "wanted.json").read_text(encoding="utf-8"))
    feats = {path.stem: np.load(path)
             for path in sorted((work / "feat").glob("*.npy"))}
    rng = random.Random(7)
    counts = {"cover": [0, 0], "other": [0, 0]}
    reasons, windows, contains = {}, [], []
    for cand in wanted:
        key, ref_key = f"cand_{cand['id']}", f"ref_{cand['song']}"
        if key not in feats or ref_key not in feats:
            continue
        verdict = cover_match.verify(feats[ref_key], feats[key],
                                     strength=cand["strength"], rng=rng)
        if cand["id"] in CONTAINS_SONG and verdict["ok"]:
            contains.append((cand["id"], verdict["norm"]))
            continue
        row = counts.setdefault(cand["label"], [0, 0])
        row[0 if verdict["ok"] else 1] += 1
        if verdict["ok"]:
            windows.append(verdict["windows"])
        else:
            reasons[verdict["reason"]] = reasons.get(verdict["reason"], 0) + 1
    kept, lost = counts["cover"]
    bad_in, bad_out = counts["other"]
    windows.sort()
    print(f"  каверов принято      {kept:3d}/{kept + lost:<3d}  "
          f"recall          {kept / max(1, kept + lost):.3f}")
    print(f"  чужих песен принято  {bad_in:3d}/{bad_in + bad_out:<3d}  "
          f"ложных          {bad_in / max(1, bad_in + bad_out):.3f}")
    print(f"  причины отказов: {reasons}")
    print(f"  годных 20-секундных окон на кавер: минимум {windows[0]}, "
          f"медиана {windows[len(windows) // 2]}")
    for vid, norm in contains:
        print(f"  вне счёта: {CONTAINS_SONG[vid]} — {norm:.2f} "
              f"(нужная песня в записи есть, отвергает гейт)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="сеть: скачать")
    parser.add_argument("--score", action="store_true", help="без сети: считать")
    parser.add_argument("--report", action="store_true",
                        help="без сети: вердикты cover_match на стенде")
    parser.add_argument("--dir", default=str(WORK), help="рабочая папка")
    parser.add_argument("--per-song", type=int, default=PER_SONG)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    work = Path(args.dir)
    out = Path(args.out) if args.out else work / "scores.json"
    if args.fetch:
        return fetch(work, args.per_song)
    if args.score:
        return score(work, out)
    if args.report:
        return report(work)
    parser.print_help()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
